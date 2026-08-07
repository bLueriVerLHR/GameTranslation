#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract remaining Japanese (kana-bearing) display strings from an
already-translated build, in STORY ORDER (MapInfos order -> map -> event ->
page -> command), with a context WINDOW of neighbouring dialogue lines for
each key. Used for the subagent completion workflow.

Keys are per-line / per-field EXACT strings, matching bake_translation.py's
exact lookup (block keys are avoided on purpose: a block may contain already
translated Chinese lines that must not be retranslated).

Also extracts JA-bearing js/plugins.js plugin parameter strings (kind
"plugin", --no-plugins to skip) and writes name_macros.json (\\N[x]/\\P[x]
actor-name macros - control codes are substitution references, never
translated; the referenced name is translated in the DB).
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402
import plugins_io  # noqa: E402

CTRL = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?")
# A line that is ONLY control codes (e.g. \M[お], \V[5], \C[27]) is a lookup
# reference or style switch, never display text - ExternMessage \M[ID] keys
# MUST stay Japanese (the CSV bodies they reference are translated instead).
CTRL_ONLY = re.compile(r"^(?:\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?)+[\s\u3000]*$")
# Kana detection: EXCLUDE U+30FB (・) / U+30FC (ー) / U+30A0 - punctuation that
# appears in already-translated Chinese lines (・ prefixed conditions) and
# floods the template with false keys. Canonical form from docs/translation.md.
KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")
NAME_LINE = re.compile(r"^(?:[\u3040-\u30ff\u4e00-\u9fff]|・)+[さんちゃん君様先生嬢ぽ]?$")
DIRECTIVE = re.compile(r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)
# Plugin-tagged notes (e.g. AlchemySystem `<recipe> {"material": ...}`) are
# functional plugin data, never display text - keep them raw. A note is also
# skipped when it is pure JSON (recipe material lists embedded as objects).
NOTE_TAG = re.compile(r"<[A-Za-z_@][^>]*>")
NOTE_JSON = re.compile(r"^\s*[{\[\"]")
WINDOW = 2

DISPLAY_KEYS = {"name", "nickname", "profile", "description",
                "message1", "message2", "message3", "message4", "text"}
EVENT_TEXT_IDX = {101: [4], 402: [0], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = ["terms", "message", "commands", "equipTypes",
                      "weaponTypes", "armorTypes", "skillTypes", "element"]
SYSTEM_TEXT_ARRAYS = ["variables", "switches"]
TALK_CODES = (401, 405, 101, 102)


def log(msg):
    print(msg, flush=True)


def ev_containers(data):
    out = []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    for key in ("events", "commonEvents"):
        arr = data.get(key) or []
        out.extend(x for x in arr if isinstance(x, dict))
    return out


def is_event_container(data):
    if isinstance(data, dict):
        return "events" in data or "commonEvents" in data
    if isinstance(data, list):
        return any(isinstance(x, dict) and ("list" in x or "pages" in x)
                   for x in data)
    return False


def talk_lines(lst):
    """[(index, raw_text_or_None)] for all talk-ish commands in a list."""
    out = []
    for idx, cmd in enumerate(lst):
        code = cmd.get("code")
        params = cmd.get("parameters") or []
        if code in (401, 405):
            out.append((idx, params[0] if params and isinstance(params[0], str) else None))
        elif code == 101 and len(params) >= 5 and isinstance(params[4], str):
            out.append((idx, "【%s】" % params[4]))
        elif code == 102 and params and isinstance(params[0], list):
            out.append((idx, "【选项】%s" % " / ".join(str(x) for x in params[0] if isinstance(x, str))))
        else:
            out.append((idx, None))
    return out


def window_for(idx, tl, radius=WINDOW):
    pos = [i for i, (ci, _) in enumerate(tl) if ci == idx]
    if not pos:
        return []
    p = pos[0]
    return [t for _, t in tl[max(0, p - radius):p + radius + 1] if t is not None]


def walk_commands(cmds, col, where):
    tl = talk_lines(cmds)
    for idx, cmd in enumerate(cmds):
        code = cmd.get("code")
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        if code in (401, 405) and params and isinstance(params[0], str) and params[0]:
            col.add(params[0], "block-line", where, window_for(idx, tl))
            if len(params[0]) <= 14 and not CTRL.search(params[0]) \
                    and NAME_LINE.match(params[0].strip()):
                col.add_name(params[0].strip())
        elif code == 102 and params and isinstance(params[0], list):
            for x in params[0]:
                if isinstance(x, str) and x:
                    col.add(x, "choice", where, window_for(idx, tl))
        elif code in EVENT_TEXT_IDX:
            for pidx in EVENT_TEXT_IDX[code]:
                if pidx < len(params) and isinstance(params[pidx], str) \
                        and params[pidx]:
                    if code == 101 and len(params) >= 5:
                        col.add_name(params[4])
                    col.add(params[pidx], "event-text", where, window_for(idx, tl))
        elif code == 122:
            # skip script operands (operandType == 4): params[4] is JS code,
            # never display text
            if len(params) > 3 and params[3] == 4:
                pass
            else:
                for pidx in (3, 4):
                    if pidx < len(params) and isinstance(params[pidx], str) \
                            and params[pidx]:
                        col.add(params[pidx], "event-text", where, window_for(idx, tl))
        elif code == 408:
            if params and isinstance(params[0], str) and params[0] \
                    and not DIRECTIVE.match(params[0]):
                col.add(params[0], "help", where, window_for(idx, tl))


def process_db(obj, col, where=""):
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in DISPLAY_KEYS and isinstance(v, str):
                col.add(v, "db-" + k, where, [])
            elif k == "note" and isinstance(v, str):
                if v and NOTE_TAG.search(v):
                    continue  # plugin-parsed note (recipe/config) - keep raw
                if v and NOTE_JSON.match(v) and len(v) > 80:
                    continue  # embedded JSON blob - functional, not display text
                col.add(v, "note", where, [])
            else:
                process_db(v, col, where)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, col, where)


def process_system(system, col):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            collect_values(system[f], col)


def collect_values(obj, col):
    if isinstance(obj, str):
        col.add(obj, "system", "System.json", [])
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_values(v, col)
    elif isinstance(obj, list):
        for v in obj:
            collect_values(v, col)


class Collector(object):
    def __init__(self):
        self.order = []                    # keys in story order
        self.kind_of = {}
        self.context = {}
        self.counts = collections.Counter()
        self.name_cands = collections.Counter()
        self._seen = set()

    def add(self, s, kind, where="", window=None):
        if not s or not KANA.search(s):
            return
        if CTRL_ONLY.match(s):
            return  # pure control-code line (\M[ID] lookup / style switch)
        if kind != "block-line" and CTRL.search(s) and len(s) < 6:
            return
        if s not in self._seen:
            self._seen.add(s)
            self.order.append(s)
            self.kind_of[s] = kind
            self.context[s] = {"where": where, "window": window or []}
        self.counts[kind] += 1

    def add_name(self, s):
        if s and len(s) <= 14 and not CTRL.search(s) and NAME_LINE.match(s):
            self.name_cands[s] += 1


def extract_plugin_text(game_dir, col):
    """JA-bearing strings in js/plugins.js plugin parameters (kind 'plugin')."""
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.exists(path):
        return 0
    try:
        plugins = plugins_io.parse_plugins_js(
            open(path, encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        log("WARN: plugins.js parse failed (%s) - plugin text skipped" % e)
        return 0
    n = 0
    for where, val in plugins_io.iter_plugin_strings(plugins, KANA):
        col.add(val, "plugin", where, [])
        n += 1
    return n


def build_name_macros(data_dir):
    """\\N[x] / \\P[x] -> actor name (macro table, never translated itself)."""
    macros = {}
    actors_path = os.path.join(data_dir, "Actors.json")
    if not os.path.exists(actors_path):
        return macros
    for a in plain_io.load_json(actors_path):
        if not a or not a.get("name"):
            continue
        for code in ("N", "P"):
            macros["\\%s[%d]" % (code, a.get("id", 0))] = a["name"]
    return macros


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--no-plugins", action="store_true",
                    help="skip js/plugins.js parameter text extraction")
    args = ap.parse_args()

    game_dir = os.path.abspath(args.game_dir)
    out_dir = os.path.abspath(args.out_dir)
    data_dir = os.path.join(game_dir, "data")
    os.makedirs(out_dir, exist_ok=True)

    col = Collector()

    mi_path = os.path.join(data_dir, "MapInfos.json")
    map_order = []
    if os.path.exists(mi_path):
        for x in plain_io.load_json(mi_path):
            if x:
                map_order.append((x["id"], x.get("name", "")))

    # 1) maps in story order
    for mid, mname in map_order:
        path = os.path.join(data_dir, "Map%03d.json" % mid)
        if not os.path.exists(path):
            path = os.path.join(data_dir, "Map%d.json" % mid)
        if not os.path.exists(path):
            continue
        data = plain_io.load_json(path)
        if not isinstance(data, dict):
            continue
        disp = data.get("displayName") or ""
        if disp:
            col.add(disp, "displayName", mname, [])
        for ev in sorted(ev_containers(data), key=lambda e: e.get("id", 0)):
            where = "%s / EV%03d %s" % (mname or path, ev.get("id", 0), ev.get("name") or "")
            if ev.get("name"):
                col.add(ev["name"], "event-name", mname, [])
            lists = []
            if isinstance(ev.get("list"), list):
                lists.append(ev["list"])
            for pg in ev.get("pages") or []:
                if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                    lists.append(pg["list"])
            for lst in lists:
                walk_commands(lst, col, where)

    # 2) remaining map files not in MapInfos (defensive)
    for fname in sorted(os.listdir(data_dir)):
        m = re.match(r"Map(\d+)\.json", fname)
        if not m:
            continue
        if int(m.group(1)) in {x for x, _ in map_order}:
            continue
        data = plain_io.load_json(os.path.join(data_dir, fname))
        if not isinstance(data, dict):
            continue
        for ev in sorted(ev_containers(data), key=lambda e: e.get("id", 0)):
            where = "%s / %s" % (fname, ev.get("name") or "")
            if ev.get("name"):
                col.add(ev["name"], "event-name", fname, [])
            lists = []
            if isinstance(ev.get("list"), list):
                lists.append(ev["list"])
            for pg in ev.get("pages") or []:
                if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                    lists.append(pg["list"])
            for lst in lists:
                walk_commands(lst, col, where)

    # 3) CommonEvents
    ce_path = os.path.join(data_dir, "CommonEvents.json")
    if os.path.exists(ce_path):
        data = plain_io.load_json(ce_path)
        for ev in sorted(ev_containers(data), key=lambda e: e.get("id", 0)):
            where = "CommonEvents / EV%03d %s" % (ev.get("id", 0), ev.get("name") or "")
            if ev.get("name"):
                col.add(ev["name"], "event-name", "CommonEvents", [])
            if isinstance(ev.get("list"), list):
                walk_commands(ev["list"], col, where)

    # 4) System + DB files (UI, no story context needed)
    sys_path = os.path.join(data_dir, "System.json")
    if os.path.exists(sys_path):
        process_system(plain_io.load_json(sys_path), col)
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".json") or fname == "System.json" \
                or re.match(r"Map\d+\.json", fname) or fname == "MapInfos.json" \
                or fname == "CommonEvents.json":
            continue
        data = plain_io.load_json(os.path.join(data_dir, fname))
        process_db(data, col, fname)

    if not args.no_plugins:
        n = extract_plugin_text(game_dir, col)
        if n:
            log("plugin parameter text: %d strings" % n)

    template = {k: "" for k in col.order}
    kinds = {k: col.kind_of[k] for k in col.order}
    ctx = {k: col.context[k] for k in col.order}
    names = {}
    actors_path = os.path.join(data_dir, "Actors.json")
    if os.path.exists(actors_path):
        for a in plain_io.load_json(actors_path) or []:
            if a and a.get("name"):
                names[a["name"]] = [""]
    for cand, n in col.name_cands.most_common(80):
        names.setdefault(cand, [""])

    with open(os.path.join(out_dir, "template.json"), "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "kinds.json"), "w", encoding="utf-8") as f:
        json.dump(kinds, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "context.json"), "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "names.json"), "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "name_macros.json"), "w",
              encoding="utf-8") as f:
        json.dump(build_name_macros(data_dir), f, ensure_ascii=False, indent=1)

    log("template keys: %d" % len(col.order))
    log("by kind: %s" % dict(col.counts.most_common()))
    log("order sample: %s" % col.order[:8])


if __name__ == "__main__":
    main()
