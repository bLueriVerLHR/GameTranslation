#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bake_translation.py - Static-bake a translated template into an RPG Maker MZ
game (the new workflow's bake step; replaces the greedy logic of the old
translate_rpgmz.py).

EXACT-MATCH ONLY: no greedy fragment replacement.  A string is replaced iff
its full text is a key of the translation dict.  Message blocks (runs of
consecutive 401/405 commands) are looked up joined with "\n" first (matching
build_translation.py), then each line raw.  This guarantees a translated
branch never leaks fragments into another branch.

Plugin menu text: js/plugins.js plugin parameter strings are exact-matched
too (the strings build_translation.py extracted as kind "plugin").  Control
codes inside them are macros (\\N[x] etc.) and stay verbatim.

Usage:
    python bake_translation.py <game_dir> <out_dir> --trs translated.json
                               [--glossary glossary.json]
                               [--min-coverage 0.5] [--force]

  game_dir   built JoiPlay folder (decrypted, shrunk) or any MZ game root
  out_dir    full copy of game_dir with translations baked in
  --trs      the filled template ({key: value})
  --glossary optional {name: value} overrides (applied to keys in the dict)
  --min-coverage  refuse to bake when the dict translates less than this
                   fraction of the game's kana-bearing display strings
                   (default 0.5); a low-coverage bake leaves most of the game
                   in Japanese and contaminates later completion passes - do a
                   full translation instead (extract_remaining_text.py ->
                   subagent chunks -> merge).  --force overrides the refusal.
  --no-kv    do not write translation_kv.json into out_dir (default: written)
"""

import argparse
import glob
import json
import logging
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plain_io  # noqa: E402
import plugins_io  # noqa: E402
from rpgmz import config  # noqa: E402
from translate_rpgmz import (  # noqa: E402
    apply_font_policy, clear_encryption_flags, decrypt_dir,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("bake")

# Kana detection (canonical, same as extract_remaining_text.py): ・/ー/・ are
# punctuation that also appears in translated Chinese lines, never counted.
KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")

# A script line (355/655, or a 122 script operand) is display text only when
# kana appears INSIDE a quoted string literal (comments stay raw).
QUOTED = re.compile(r"['\"`][^'\"`]*[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e][^'\"`]*['\"`]")

# Coverage stats, filled by exact() during a translate_data pass.
STATS = {"hit": 0, "miss": 0}

DISPLAY_KEYS = {"name", "nickname", "profile", "description",
                "message1", "message2", "message3", "message4", "text"}
EVENT_TEXT_IDX = {101: [4], 402: [0, 1], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = ["terms", "message", "commands", "equipTypes",
                      "weaponTypes", "armorTypes", "skillTypes", "element"]
SYSTEM_TEXT_ARRAYS = ["variables", "switches"]


def is_event_container(data):
    if isinstance(data, dict):
        return "events" in data or "commonEvents" in data
    if isinstance(data, list):
        return any(isinstance(x, dict) and ("list" in x or "pages" in x)
                   for x in data)
    return False


def ev_containers(data):
    out = []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    for key in ("events", "commonEvents"):
        arr = data.get(key) or []
        out.extend(x for x in arr if isinstance(x, dict))
    return out


def exact(s, D):
    """Exact lookup; None means 'no translation for this string'.  Updates the
    coverage stats for kana-bearing display strings."""
    if s is None:
        return None
    v = D.get(s)
    if isinstance(v, str) and v:
        if v != s:
            STATS["hit"] += 1
        return v
    if KANA.search(s):
        STATS["miss"] += 1
    return None


def coverage():
    n = STATS["hit"] + STATS["miss"]
    return (STATS["hit"] / n) if n else None


_REF_TAGS = ("TE", "namePop")
_REF_RE = re.compile(r"<(TE|namePop):([^>]+)>")


def _translate_note_refs(note, D, refs=None):
    """Translate <TE:name>/<namePop:name> style note references so they keep
    matching the translated event names (TemplateEvent.js looks up templates
    by name, namePop by map event name).  Refs with control codes (\\v[n] etc.)
    are left untouched.  Every ref (translated or not) is appended to `refs`
    as (tag, name) for the post-bake dangling-ref check."""
    if refs is None:
        refs = []

    def repl(m):
        tag, name = m.group(1), m.group(2)
        if name.isdigit():
            # numeric refs are TemplateEvent ID-based lookups, never matched
            # against an event NAME - skip both translation and the dangling
            # check (a numeric "name" can never resolve to a map event).
            return m.group(0)
        if "\\" in name or "[" in name:
            # control-code refs are never translated: still record them so a
            # TRANSLATED event name of the same raw text is caught as dangling
            # (one side translated, the other not = runtime lookup failure)
            refs.append((tag, name))
            return m.group(0)
        v = exact(name, D)
        final = v if v is not None else name
        refs.append((tag, final))
        return "<%s:%s>" % (tag, final)

    return _REF_RE.sub(repl, note)


def process_commands(cmds, D):
    """One pass over a command list: blocks first, then individual codes."""
    n = len(cmds)
    i = 0
    while i < n:
        code = cmds[i].get("code")
        if code not in (401, 405):
            i += 1
            continue
        j = i
        lines = []
        while j < n and cmds[j].get("code") == code:
            params = cmds[j].get("parameters") or []
            lines.append(params[0] if params and isinstance(params[0], str)
                         else "")
            j += 1
        # block lookup
        block = "\n".join(lines)
        value = exact(block, D)
        if value is not None:
            vlines = value.split("\n")
            # pad shorter translations with "" so no command keeps Japanese
            vlines = vlines + [""] * (len(lines) - len(vlines))
            k = i
            for vline in vlines[: len(lines)]:
                params = cmds[k].get("parameters") or []
                if not params:
                    cmds[k]["parameters"] = [""]
                cmds[k]["parameters"][0] = vline
                k += 1
            for extra in vlines[len(lines):]:
                tmpl = dict(cmds[j - 1])
                tmpl["parameters"] = [extra]
                cmds.insert(j, tmpl)
                j += 1
        else:
            # per-line exact fallback
            for k in range(i, j):
                params = cmds[k].get("parameters") or []
                if params and isinstance(params[0], str):
                    v = exact(params[0], D)
                    if v is not None:
                        params[0] = v
        i = j

    for cmd in cmds:
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        code = cmd.get("code")
        if code == 102 and params and isinstance(params[0], list):
            for idx, x in enumerate(params[0]):
                if isinstance(x, str):
                    v = exact(x, D)
                    if v is not None:
                        params[0][idx] = v
        elif code in EVENT_TEXT_IDX:
            for idx in EVENT_TEXT_IDX[code]:
                if idx < len(params) and isinstance(params[idx], str):
                    v = exact(params[idx], D)
                    if v is not None:
                        params[idx] = v
        elif code == 122:
            # script operands (operandType == 4) store display strings in
            # variables (shown later via \V[n]): exact-match the whole JS
            # literal.  Non-literal script expressions are left alone.
            if len(params) > 3 and params[3] == 4:
                if len(params) > 4 and isinstance(params[4], str) and params[4] \
                        and params[4][0] in "'\"" and QUOTED.search(params[4]):
                    v = exact(params[4], D)
                    if v is not None:
                        params[4] = v
            else:
                for idx in (3, 4):
                    if idx < len(params) and isinstance(params[idx], str):
                        v = exact(params[idx], D)
                        if v is not None:
                            params[idx] = v
        elif code in (355, 655):
            # script lines with kana inside a quoted literal are display text
            # (e.g. BattleManager._logWindow.addText('...')): exact-match the
            # whole line so the translated string stays valid JS.
            if params and isinstance(params[0], str) and QUOTED.search(params[0]):
                v = exact(params[0], D)
                if v is not None:
                    params[0] = v
        elif code == 357:
            # plugin command arguments: exact-match kana-bearing string VALUES
            # in the arg dict (display text).  params[2] (Japanese command
            # name) is a functional lookup key - never matched.
            if len(params) > 3 and isinstance(params[3], dict):
                _translate_arg_values(params[3], D)
        elif code == 408:
            if params and isinstance(params[0], str):
                v = exact(params[0], D)
                if v is not None:
                    params[0] = v


def _translate_arg_values(obj, D):
    """Exact-match string values (recursively) in a plugin-command arg dict."""
    if isinstance(obj, dict):
        for k in obj:
            obj[k] = _translate_arg_values(obj[k], D)
        return obj
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = _translate_arg_values(obj[i], D)
        return obj
    if isinstance(obj, str) and KANA.search(obj):
        v = exact(obj, D)
        if v is not None:
            return v
    return obj


def process_db(obj, D):
    if isinstance(obj, dict):
        # battle-event command lists inside DB files (Troops.json pages):
        # process their display strings like any other event list.
        lst = obj.get("list")
        if isinstance(lst, list) and lst and isinstance(lst[0], dict) \
                and "code" in lst[0]:
            process_commands(lst, D)
            return
        for k, v in list(obj.items()):
            if k in DISPLAY_KEYS and isinstance(v, str):
                nv = exact(v, D)
                if nv is not None:
                    obj[k] = nv
            elif k == "note" and isinstance(v, str):
                nv = exact(v, D)
                if nv is not None:
                    obj[k] = nv
            else:
                process_db(v, D)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, D)


def process_system(system, D):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            system[f] = translate_values(system[f], D)


def translate_values(obj, D):
    if isinstance(obj, str):
        v = exact(obj, D)
        return v if v is not None else obj
    if isinstance(obj, dict):
        for k in obj:
            obj[k] = translate_values(obj[k], D)
        return obj
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = translate_values(obj[i], D)
        return obj
    return obj


def translate_plugins(root, D, write=True):
    """Bake plugin menu text in js/plugins.js: exact-match every JA-bearing
    parameter string against D.  Parse-and-reserialize first; falls back to a
    textual exact-match pass when the file does not parse.  write=False =
    coverage measurement only."""
    path = os.path.join(root, "js", "plugins.js")
    if not os.path.exists(path):
        return 0
    text = open(path, encoding="utf-8-sig").read()
    try:
        plugins = plugins_io.parse_plugins_js(text)
        n = 0
        for p in plugins:
            params = p.get("parameters")
            if not isinstance(params, (dict, list)):
                continue
            items = params.items() if isinstance(params, dict) \
                else [(i, v) for i, v in enumerate(params)]
            for key, val in items:
                if isinstance(val, str):
                    v = exact(val, D)
                    if v is not None:
                        params[key] = v
                        n += 1
        if n:
            if write:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(plugins_io.dump_plugins_js(plugins))
        else:
            log.info("plugins.js parsed, no plugin strings translated")
        return n
    except Exception as e:  # noqa: BLE001
        log.warning("plugins.js parse failed (%s) - textual fallback", e)
        n = 0

        def repl(m):
            nonlocal n
            try:
                s = json.loads(m.group(0))
            except ValueError:
                return m.group(0)
            v = exact(s, D) if isinstance(s, str) else None
            if v is not None:
                n += 1
                return json.dumps(v, ensure_ascii=False)
            return m.group(0)
        out = plugins_io.JS_STR.sub(repl, text)
        if n and write:
            with open(path, "w", encoding="utf-8") as f:
                f.write(out)
        return n


def translate_data(root, D, write=True):
    """Bake the dict into every data file.  write=False is the coverage
    measurement pass: identical traversal, no files touched."""
    data_dir = os.path.join(root, "data")
    files = 0
    event_names = set()
    refs = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        if is_event_container(data):
            if isinstance(data, dict):
                dn = data.get("displayName")
                if isinstance(dn, str):
                    v = exact(dn, D)
                    if v is not None:
                        data["displayName"] = v
            for ev in ev_containers(data):
                if isinstance(ev.get("name"), str):
                    v = exact(ev["name"], D)
                    if v is not None:
                        ev["name"] = v
                    event_names.add(ev["name"])
                # TemplateEvent-style note refs: <TE:name> must keep matching
                # the (translated) template event name, else template lookup
                # fails and unconditional autorun events re-fire forever.
                # <namePop:name> must keep matching the named map event.
                note = ev.get("note")
                if note:
                    new_note = _translate_note_refs(note, D, refs)
                    if new_note != note:
                        ev["note"] = new_note
                lists = []
                if isinstance(ev.get("list"), list):
                    lists.append(ev["list"])
                for pg in ev.get("pages") or []:
                    if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                        lists.append(pg["list"])
                for lst in lists:
                    process_commands(lst, D)
        elif os.path.basename(path) == "System.json":
            process_system(data, D)
        else:
            process_db(data, D)
        if write:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        files += 1
    log.info("%s %d data files", "baked" if write else "scanned", files)

    n_pl = translate_plugins(root, D, write)
    if n_pl:
        log.info("baked %d plugin strings in js/plugins.js", n_pl)

    scenario_path = os.path.join(root, "scenario", "Scenario.json")
    if os.path.exists(scenario_path):
        with open(scenario_path, encoding="utf-8-sig") as f:
            scenario = json.load(f)
        if isinstance(scenario, dict):
            for k, v in list(scenario.items()):
                if isinstance(v, list):
                    process_commands(v, D)
                elif isinstance(v, str):
                    nv = exact(v, D)
                    if nv is not None:
                        scenario[k] = nv
        elif isinstance(scenario, list):
            for chunk in scenario:
                if isinstance(chunk, list):
                    process_commands(chunk, D)
        if write:
            with open(scenario_path, "w", encoding="utf-8") as f:
                json.dump(scenario, f, ensure_ascii=False, indent=2)
        log.info("baked scenario/Scenario.json")

    if write and refs:
        dangling = [(t, n) for t, n in refs if n not in event_names]
        log.info("name-ref check: %d <TE:/<namePop:> refs vs %d event names",
                 len(refs), len(event_names))
        if dangling:
            log.warning("dangling name refs (match no event name - the "
                        "lookup WILL fail at runtime):")
            for t, n in sorted(dangling):
                log.warning("  <%s:%s>", t, n)
        else:
            log.info("all name refs resolve to an event name")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--trs", required=True, help="filled template JSON")
    ap.add_argument("--glossary", default="", help="name overrides JSON")
    ap.add_argument("--min-coverage", type=float, default=0.5,
                    help="refuse to bake below this coverage (default 0.5)")
    ap.add_argument("--force", action="store_true",
                    help="bake anyway when coverage is below --min-coverage")
    ap.add_argument("--no-kv", action="store_true",
                    help="do not write translation_kv.json")
    ap.add_argument("--cjk-font", default="",
                    help="CJK ttf to bundle (MV: gamefont.css split; MZ: "
                         "swap the main @font-face src). Default: resolved "
                         "via CJK_FONT_PATH / docs/table/local_font_path.txt")
    args = ap.parse_args()
    if not args.cjk_font:
        args.cjk_font = config.find_cjk_font() or ""

    game_dir = os.path.abspath(args.game_dir)
    out_dir = os.path.abspath(args.out_dir)
    if not os.path.isdir(game_dir):
        sys.exit("game_dir not found: %s" % game_dir)
    if os.path.abspath(out_dir) == game_dir:
        sys.exit("out_dir must differ from game_dir")

    D = plain_io.load_json(args.trs)
    if args.glossary:
        G = plain_io.load_json(args.glossary)
        for k, v in G.items():
            if v and (k not in D or not D.get(k)):
                D[k] = v
    # Identity entries (v == k with kana) are untranslated leftovers: in the
    # dict they SHADOW per-line fallbacks (the block lookup 'succeeds' with the
    # unchanged Japanese text), so they must never reach the bake (MZ job
    # 2026-08: 123 removed, residual 24 -> 21).
    dropped = [k for k, v in D.items() if v == k and KANA.search(k)]
    for k in dropped:
        del D[k]
    if dropped:
        log.info("dropped %d identity entries (v == k with kana, shadow per-line "
                 "fallbacks)", len(dropped))
    log.info("loaded %d translation entries", len(D))

    # Coverage gate: measure the dict against the game's kana-bearing display
    # strings BEFORE copying anything.  A low-coverage bake leaves most of the
    # game in Japanese and contaminates later completion passes (partial block
    # values, half-translated scenes) - the clean path is a full translation
    # from scratch.  --force overrides for intentional phase-1 harvest bakes.
    if glob.glob(os.path.join(game_dir, "data", "*.json")):
        STATS.update(hit=0, miss=0)
        translate_data(game_dir, D, write=False)
        cov = coverage()
        if cov is not None:
            log.info("coverage: %d hit / %d missed = %.1f%%",
                     STATS["hit"], STATS["miss"], 100 * cov)
            if cov < args.min_coverage and not args.force:
                sys.exit(
                    "REFUSING to bake: coverage %.1f%% < %.0f%% (existing "
                    "translation file covers too little - the bake would leave "
                    "most of the game in Japanese and contaminate a later "
                    "completion pass).\n"
                    "  Do a FULL translation instead: extract_remaining_text.py "
                    "<game_dir> <work> -> subagent chunks -> merge -> bake.\n"
                    "  To bake anyway (intentional partial harvest): --force.\n"
                    "  To adjust the threshold: --min-coverage N."
                    % (100 * cov, 100 * args.min_coverage))
    else:
        log.info("no data/*.json in game_dir (encrypted data?) - coverage "
                 "check skipped; bake on the decrypted build for the gate")

    log.info("copying %s -> %s", game_dir, out_dir)
    shutil.copytree(game_dir, out_dir, dirs_exist_ok=True)

    decrypt_dir(out_dir)
    clear_encryption_flags(out_dir)
    STATS.update(hit=0, miss=0)
    translate_data(out_dir, D, write=True)
    cov = coverage()
    if cov is not None:
        log.info("baked coverage: %d hit / %d missed = %.1f%%",
                 STATS["hit"], STATS["miss"], 100 * cov)
    apply_font_policy(out_dir, args.cjk_font)
    if not args.no_kv:
        kv_path = os.path.join(out_dir, "translation_kv.json")
        with open(kv_path, "w", encoding="utf-8") as f:
            json.dump(D, f, ensure_ascii=False, indent=1)
        log.info("archived translation KV -> %s", kv_path)
    log.info("done -> %s", out_dir)


if __name__ == "__main__":
    main()
