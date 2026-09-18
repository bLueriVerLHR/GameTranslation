#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bake_translation.py - Static-bake a translated template into an RPG Maker MZ
game (the new workflow's bake step; replaces the greedy logic of the old
translate_rpgmaker.py).

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
                   fraction of the game's translatable key list
                   (translation.mvkeys; default 0.5); a low-coverage bake
                   leaves most of the game in Japanese and contaminates later
                   completion passes - do a full translation instead
                   (extract_remaining_text.py -> subagent chunks -> merge).
                   --force overrides the refusal.
  --no-kv    do not write translation_kv.json into out_dir (default: written)
"""

import glob
import json
import logging
import os
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Optional


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import japanese_utils  # noqa: E402
import plain_io  # noqa: E402
import plugins_io  # noqa: E402
import rpgmaker_common  # noqa: E402
import rpgmaker_constants  # noqa: E402
from rpgmaker import cliutil, config  # noqa: E402
from translation import mvkeys  # noqa: E402
from translate_rpgmaker import (  # noqa: E402
    apply_font_policy, clear_encryption_flags, decrypt_dir,
)

log = logging.getLogger("bake")

# Kana detection (canonical, shared via japanese_utils): ・/ー/・ are
# punctuation that also appears in translated Chinese lines, never counted.
KANA = japanese_utils.KANA

# A script line (355/655, or a 122 script operand) is display text only when
# kana appears INSIDE a quoted string literal (comments stay raw).
QUOTED = re.compile(r"['\"`][^'\"`]*[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e][^'\"`]*['\"`]")

# Coverage stats, filled by exact() during a translate_data pass.
STATS = {"hit": 0, "miss": 0}

# Per-thread coverage counters for the parallel bake path (review §4.2:
# map-level parallelism).  Each worker thread sets its own local dict so
# exact()/exact_loc() accumulate into it instead of racing the shared
# STATS; the main thread (and the tests) keep using STATS directly.
_thread_stats = threading.local()


def _stats():
    """Coverage counters for the current thread: a worker thread's local
    dict when set, else the shared module STATS (which tests inspect)."""
    local = getattr(_thread_stats, "value", None)
    return local if local is not None else STATS

# Bake coverage gate: refuse to bake when the dict translates less than this
# fraction of the game's kana-bearing display strings (see --min-coverage).
DEFAULT_MIN_COVERAGE = 0.5

DISPLAY_KEYS = {"name", "nickname", "profile", "description",
                "message1", "message2", "message3", "message4", "text"}
EVENT_TEXT_IDX = {101: [4], 402: [0, 1], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = rpgmaker_constants.SYSTEM_TEXT_FIELDS
SYSTEM_TEXT_ARRAYS = rpgmaker_constants.SYSTEM_TEXT_ARRAYS


def is_event_container(data):
    return rpgmaker_common.is_event_container(data)


def ev_containers(data):
    return rpgmaker_common.ev_containers(data)


LOC_SEP = "\x1f"


def exact_loc(s, D, loc):
    """Location-aware exact lookup: prefer the located key `s\x1f<loc>`
    (context-specific translation for this occurrence), fall back to the
    plain key `s` (shared translation, older dicts stay compatible)."""
    if s is None:
        return None
    if loc:
        v = D.get(s + LOC_SEP + loc)
        if isinstance(v, str) and v:
            if v != s:
                _stats()["hit"] += 1
            return v
    return exact(s, D)


def exact(s, D):
    """Exact lookup; None means 'no translation for this string'.  Updates the
    coverage stats for kana-bearing display strings."""
    if s is None:
        return None
    v = D.get(s)
    if isinstance(v, str) and v:
        if v != s:
            _stats()["hit"] += 1
        return v
    if KANA.search(s):
        _stats()["miss"] += 1
    return None


def coverage():
    n = STATS["hit"] + STATS["miss"]
    return (STATS["hit"] / n) if n else None


def key_coverage(game_dir, D, note_tags=mvkeys.DEFAULT_NOTE_TAGS):
    """``(covered, total, missing)`` of the game's key list against the dict.

    The gate's denominator is the key list (``translation.mvkeys``) - the set
    of strings the translation flow owns - and NOT every kana-bearing string a
    data traversal happens to touch.  Counting lookups over-counts: bake looks
    up the joined block first (``line1\\nline2``) and then each line, and it
    also visits fields ``mvkeys`` deliberately skips (animation and event
    names).  Measured against one real MZ build, that inflated the misses so
    much that 80% of the key list read as 7.3% - the gate would have refused
    *every* bake of a complete translation (100* covered/total is what the
    operator reads as 'coverage' everywhere else too: ``translation.cli
    status`` reports the same fraction).
    """
    entries = mvkeys.keys_of(game_dir, note_tags=note_tags)
    missing = [entry["ja"] for entry in entries if not D.get(entry["ja"])]
    return len(entries) - len(missing), len(entries), missing


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


def _process_block(cmds, D, loc):
    """Consecutive 401/405 runs are matched as one joined block first (the
    located key `s\x1f<loc>#c<block_start>`), then fall back to per-line
    exact matches (each line's own command index).  Extra translation lines
    beyond the original block length are appended as new commands."""
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
        # block lookup (located first: the block's own command index)
        block = "\n".join(lines)
        value = exact_loc(block, D, loc + "#c%d" % i)
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
            # per-line exact fallback (each line's own command index)
            for k in range(i, j):
                params = cmds[k].get("parameters") or []
                if params and isinstance(params[0], str):
                    v = exact_loc(params[0], D, loc + "#c%d" % k)
                    if v is not None:
                        params[0] = v
        i = j


def _process_single_code(cmds, D, loc):
    """Individual command codes: choices, display-text indices, script
    operands, script lines, plugin-command args and comment lines, each
    exact-matched with its own command index `s\x1f<loc>#c<idx>`."""
    for ci, cmd in enumerate(cmds):
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        code = cmd.get("code")
        cloc = loc + "#c%d" % ci
        if code == 102 and params and isinstance(params[0], list):
            for idx, x in enumerate(params[0]):
                if isinstance(x, str):
                    v = exact_loc(x, D, cloc)
                    if v is not None:
                        params[0][idx] = v
        elif code in EVENT_TEXT_IDX:
            for idx in EVENT_TEXT_IDX[code]:
                if idx < len(params) and isinstance(params[idx], str):
                    v = exact_loc(params[idx], D, cloc)
                    if v is not None:
                        params[idx] = v
        elif code == 122:
            # script operands (operandType == 4) store display strings in
            # variables (shown later via \V[n]): exact-match the whole JS
            # literal.  Non-literal script expressions are left alone.
            if len(params) > 3 and params[3] == 4:
                if len(params) > 4 and isinstance(params[4], str) and params[4] \
                        and params[4][0] in "'\"" and QUOTED.search(params[4]):
                    v = exact_loc(params[4], D, cloc)
                    if v is not None:
                        params[4] = v
            else:
                for idx in (3, 4):
                    if idx < len(params) and isinstance(params[idx], str):
                        v = exact_loc(params[idx], D, cloc)
                        if v is not None:
                            params[idx] = v
        elif code in (355, 655):
            # script lines with kana inside a quoted literal are display text
            # (e.g. BattleManager._logWindow.addText('...')): exact-match the
            # whole line so the translated string stays valid JS.
            if params and isinstance(params[0], str) and QUOTED.search(params[0]):
                v = exact_loc(params[0], D, cloc)
                if v is not None:
                    params[0] = v
        elif code == 357:
            # plugin command arguments: exact-match kana-bearing string VALUES
            # in the arg dict (display text).  params[2] (Japanese command
            # name) is a functional lookup key - never matched.
            if len(params) > 3 and isinstance(params[3], dict):
                _translate_arg_values(params[3], D, cloc)
        elif code == 408:
            if params and isinstance(params[0], str):
                v = exact_loc(params[0], D, cloc)
                if v is not None:
                    params[0] = v
                    params[0] = v


def process_commands(cmds, D, loc=""):
    """One pass over a command list: blocks first, then individual codes.
    loc = stable traversal path (file#evN#pgM) rebuilt to match the
    build_translation.py location keys; every exact match prefers the
    located key `s\x1f<loc>#c<idx>` and falls back to the plain key."""
    _process_block(cmds, D, loc)
    _process_single_code(cmds, D, loc)


def _translate_arg_values(obj, D, loc=""):
    """Exact-match string values (recursively) in a plugin-command arg dict."""
    if isinstance(obj, dict):
        for k in obj:
            obj[k] = _translate_arg_values(obj[k], D, loc + "#" + str(k))
        return obj
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = _translate_arg_values(obj[i], D, loc + "[%d]" % i)
        return obj
    if isinstance(obj, str) and KANA.search(obj):
        v = exact_loc(obj, D, loc)
        if v is not None:
            return v
    return obj


def process_db(obj, D, loc=""):
    if isinstance(obj, dict):
        # battle-event command lists inside DB files (Troops.json pages):
        # process their display strings like any other event list.
        lst = obj.get("list")
        if isinstance(lst, list) and lst and isinstance(lst[0], dict) \
                and "code" in lst[0]:
            process_commands(lst, D, loc)
            return
        for k, v in list(obj.items()):
            kloc = loc + "#" + str(k)
            if k in DISPLAY_KEYS and isinstance(v, str):
                nv = exact_loc(v, D, kloc)
                if nv is not None:
                    obj[k] = nv
            elif k == "note" and isinstance(v, str):
                nv = exact_loc(v, D, kloc)
                if nv is not None:
                    obj[k] = nv
            else:
                process_db(v, D, kloc)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            process_db(v, D, loc + "[%d]" % i)


def process_system(system, D):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            system[f] = translate_values(system[f], D,
                                         "System.json#" + f)


def translate_values(obj, D, loc=""):
    if isinstance(obj, str):
        v = exact_loc(obj, D, loc)
        return v if v is not None else obj
    if isinstance(obj, dict):
        for k in obj:
            obj[k] = translate_values(obj[k], D, loc + "#" + str(k))
        return obj
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = translate_values(obj[i], D, loc + "[%d]" % i)
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
            pname = p.get("name")
            if not isinstance(pname, str):
                pname = "?"
            params = p.get("parameters")
            if not isinstance(params, (dict, list)):
                continue
            items = params.items() if isinstance(params, dict) \
                else [(i, v) for i, v in enumerate(params)]
            for key, val in items:
                if isinstance(val, str):
                    v = exact_loc(val, D,
                                  "js/plugins.js#%s#%s" % (pname, key))
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
        # Intentional catch-all: parse_plugins_js() is a heuristic JS parser
        # and may raise any of ValueError/IndexError/TypeError/KeyError on
        # malformed plugin params. Any failure degrades to a textual
        # (regex) replacement fallback instead of aborting the bake.
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


def _translate_events(data, D, fname, event_names, refs):
    """Translate one event-container file: map displayName, per-event names,
    <TE:name>/<namePop:name> note refs, and every event page's command list.
    `event_names` accumulates the (translated) event names and `refs` the
    note refs for the post-bake dangling-ref check."""
    if isinstance(data, dict):
        dn = data.get("displayName")
        if isinstance(dn, str):
            v = exact_loc(dn, D, fname + "#displayName")
            if v is not None:
                data["displayName"] = v
    for evi, ev in enumerate(ev_containers(data)):
        eloc = "%s#ev%d" % (fname, evi)
        if isinstance(ev.get("name"), str):
            v = exact_loc(ev["name"], D, eloc + "#name")
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
        for li, lst in enumerate(lists):
            process_commands(lst, D, eloc + "#pg%d" % li)


def _translate_scenario(root, D, write):
    """Bake scenario/Scenario.json (ExternMessage-style flows): dict values
    are translated per-key, list values are treated as command lists."""
    scenario_path = os.path.join(root, "scenario", "Scenario.json")
    if not os.path.exists(scenario_path):
        return
    with open(scenario_path, encoding="utf-8-sig") as f:
        scenario = json.load(f)
    if isinstance(scenario, dict):
        for k, v in list(scenario.items()):
            if isinstance(v, list):
                process_commands(v, D, "scenario#" + k)
            elif isinstance(v, str):
                nv = exact_loc(v, D, "scenario#" + k)
                if nv is not None:
                    scenario[k] = nv
    elif isinstance(scenario, list):
        for i, chunk in enumerate(scenario):
            if isinstance(chunk, list):
                process_commands(chunk, D, "scenario[%d]" % i)
    if write:
        with open(scenario_path, "w", encoding="utf-8") as f:
            json.dump(scenario, f, ensure_ascii=False, indent=2)
    log.info("baked scenario/Scenario.json")


def _report_name_refs(refs, event_names):
    """Post-bake check: every <TE:name>/<namePop:name> ref must resolve to a
    (translated) event name, else the name-based lookup fails at runtime."""
    if not refs:
        return
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


def _translate_file(path, D, fname, write):
    """Translate one data file in isolation.  Returns (event_names, refs,
    stats) so translate_data() can merge results without any shared mutable
    state: the per-thread coverage counters avoid racing the module STATS
    (review §4.2: map-level parallelism with correct JSON parse/write-back)."""
    local = {"hit": 0, "miss": 0}
    _thread_stats.value = local
    event_names = set()
    refs = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        if is_event_container(data):
            _translate_events(data, D, fname, event_names, refs)
        if fname == "System.json":
            process_system(data, D)
        else:
            process_db(data, D, fname)
        if write:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    finally:
        _thread_stats.value = None
    return event_names, refs, local


def translate_data(root, D, write=True, workers=None):
    """Bake the dict into every data file.  write=False is the coverage
    measurement pass: identical traversal, no files touched.

    `workers` > 1 translates the data files on a thread pool (each file is
    read, translated and written independently, so JSON parse + write-back
    are safe to parallelize; review §4.2).  Default (None/1) is the exact
    legacy single-threaded path.  Per-file results are merged in the sorted
    file order, so the baked output and the coverage totals are identical
    regardless of the worker count."""
    data_dir = os.path.join(root, "data")
    files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    event_names = set()
    refs = []
    stats_total = {"hit": 0, "miss": 0}

    def run(path, fname):
        return _translate_file(path, D, fname, write)

    if workers and workers > 1 and len(files) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(lambda p: run(p, os.path.basename(p)), files))
    else:
        results = [run(p, os.path.basename(p)) for p in files]

    for ev, rf, st in results:
        event_names.update(ev)
        refs.extend(rf)
        stats_total["hit"] += st["hit"]
        stats_total["miss"] += st["miss"]
    STATS.update(hit=stats_total["hit"], miss=stats_total["miss"])
    log.info("%s %d data files", "baked" if write else "scanned", len(files))

    n_pl = translate_plugins(root, D, write)
    if n_pl:
        log.info("baked %d plugin strings in js/plugins.js", n_pl)

    _translate_scenario(root, D, write)

    if write:
        _report_name_refs(refs, event_names)


def cmd(game_dir: Annotated[str, cliutil.Argument(help="source game directory")],
        out_dir: Annotated[str, cliutil.Argument(help="baked output directory")],
        trs: Annotated[str, cliutil.Option("--trs", help="filled template JSON")],
        glossary: Annotated[str, cliutil.Option(
            "--glossary", help="name overrides JSON")] = "",
        min_coverage: Annotated[float, cliutil.Option(
            "--min-coverage", help="refuse to bake below this coverage "
            "(default %s)" % DEFAULT_MIN_COVERAGE)] = DEFAULT_MIN_COVERAGE,
        force: Annotated[bool, cliutil.Option(
            "--force", help="bake anyway when coverage is below "
            "--min-coverage")] = False,
        no_kv: Annotated[bool, cliutil.Option(
            "--no-kv", help="do not write translation_kv.json")] = False,
        workers: Annotated[Optional[int], cliutil.Option(
            "--workers", help="parallel data-file workers for the bake pass "
            "(default: single-threaded; >1 translates the data files "
            "concurrently - output is identical, only the coverage totals "
            "are accumulated per worker)")] = None,
        cjk_font: Annotated[str, cliutil.Option(
            "--cjk-font", help="CJK ttf to bundle (MV: gamefont.css split; MZ: "
            "swap the main @font-face src). Default: resolved via "
            "CJK_FONT_PATH / docs/table/local_font_path.txt / "
            "auto-discovery of docs/table/fonts/")] = "",
        jp_font: Annotated[str, cliutil.Option(
            "--jp-font", help="Japanese fallback font for kana/JP punctuation "
            "(second line of docs/table/local_font_path.txt, JP_FONT_PATH, "
            "or auto-discovery of docs/table/fonts/; default: the game's "
            "original font)")] = "",
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)
    if not cjk_font:
        cjk_font = config.find_cjk_font() or ""
    if not jp_font:
        jp_font = config.find_jp_font() or ""

    game_dir = os.path.abspath(game_dir)
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(game_dir):
        return cliutil.fail("game_dir not found: %s" % game_dir)
    if os.path.abspath(out_dir) == game_dir:
        return cliutil.fail("out_dir must differ from game_dir")

    D = plain_io.load_json(trs)
    if glossary:
        G = plain_io.load_json(glossary)
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

    # Coverage gate: measure the dict against the game's translatable key
    # list BEFORE copying anything.  A low-coverage bake leaves most of the
    # game in Japanese and contaminates later completion passes (partial block
    # values, half-translated scenes) - the clean path is a full translation
    # from scratch.  --force overrides for intentional phase-1 harvest bakes.
    covered = total = 0
    coverage_ratio = None
    if glob.glob(os.path.join(game_dir, "data", "*.json")):
        covered, total, missing = key_coverage(game_dir, D)
        if total:
            coverage_ratio = covered / total
            log.info("coverage: %d/%d keys translated = %.1f%% (%d key(s) "
                     "left to a translator)", covered, total,
                     100 * coverage_ratio, len(missing))
            if coverage_ratio < min_coverage and not force:
                for sample in missing[:10]:
                    log.info("  untranslated key: %s", sample[:80])
                return cliutil.fail(
                    "REFUSING to bake: coverage %.1f%% < %.0f%% (existing "
                    "translation file covers too little - the bake would leave "
                    "most of the game in Japanese and contaminate a later "
                    "completion pass).\n"
                    "  Do a FULL translation instead: extract_remaining_text.py "
                    "<game_dir> <work> -> subagent chunks -> merge -> bake.\n"
                    "  To bake anyway (intentional partial harvest): --force.\n"
                    "  To adjust the threshold: --min-coverage N."
                    % (100 * coverage_ratio, 100 * min_coverage))
    else:
        log.info("no data/*.json in game_dir (encrypted data?) - coverage "
                 "check skipped; bake on the decrypted build for the gate")

    log.info("copying %s -> %s", game_dir, out_dir)
    shutil.copytree(game_dir, out_dir, dirs_exist_ok=True)

    decrypt_dir(out_dir)
    clear_encryption_flags(out_dir)
    STATS.update(hit=0, miss=0)
    translate_data(out_dir, D, write=True, workers=workers)
    if coverage_ratio is not None:
        log.info("baked %d of the game's %d keys (%.1f%% key coverage)",
                 covered, total, 100 * coverage_ratio)
    apply_font_policy(out_dir, cjk_font, jp_font)
    if not no_kv:
        kv_path = os.path.join(out_dir, "translation_kv.json")
        with open(kv_path, "w", encoding="utf-8") as f:
            json.dump(D, f, ensure_ascii=False, indent=1)
        log.info("archived translation KV -> %s", kv_path)
    log.info("done -> %s", out_dir)
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="bake_translation.py")


if __name__ == "__main__":
    raise SystemExit(main())
