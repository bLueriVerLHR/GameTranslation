#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
build_translation.py - Build a static-translation work package from an RPG
Maker MZ game (replaces the old extract_text.py for the new workflow).

Produces five files in <out_dir>:
  template.json    merged {key: ""} of every translatable static string
  names.json       candidate character names -> proposed translations ("" = TBD)
  structure.json   scene tree: maps (story order) -> events -> ordered text
                   items (message blocks, choice labels, names, help texts)
  context.json     key -> {"where": location, "window": neighbouring dialogue
                   lines} - CONTEXT ONLY, nothing here is translated.  Shard
                   generators inject this into each chunk's context.md.
  name_macros.json {"\\N[1]": "<zh-name>"} - CONTROL-CODE NAME MACROS: like C++ /
                   LaTeX macros, the code is a substitution reference, NOT
                   translatable text.  \N[x] / \P[x] resolve to the actor's
                   name in Actors.json, which IS translated normally (DB).
                   Shard generators print this table in context.md so agents
                   understand a macro as "this is character X's name" and
                   leave the code itself untouched.

Why blocks: dialogue is stored one 401 command per line, but a message is a
run of consecutive 401 commands.  Keys for such runs are the lines joined
with "\n", so the translator sees and translates whole messages with context.
Baking (bake_translation.py) joins the same runs and looks the key up
exactly - no greedy fragment replacement, so no cross-branch pollution.

Plugin menu text: every JA-bearing string in js/plugins.js plugin parameters
is extracted too (kind "plugin") so plugin UI/menus can be localized; the
baker writes them back (see bake_translation.py).  Disable with --no-plugins.

Usage:
    python build_translation.py <game_dir> <out_dir> [--no-plugins]
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

SPLIT = re.compile(r"\n")
CTRL = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?")
JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
NAME_LINE = re.compile(r"^(?:[\u3040-\u30ff\u4e00-\u9fff]|・)+[さんちゃん君様先生嬢ぽ]?$")
DIRECTIVE = re.compile(r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)
WINDOW = 2

DISPLAY_KEYS = {"name", "nickname", "profile", "description",
                "message1", "message2", "message3", "message4", "text"}
EVENT_TEXT_IDX = {101: [4], 402: [0], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = ["terms", "message", "commands", "equipTypes",
                      "weaponTypes", "armorTypes", "skillTypes", "element"]
SYSTEM_TEXT_ARRAYS = ["variables", "switches"]


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Walkers
# ---------------------------------------------------------------------------
def ev_containers(data):
    out = []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    for key in ("events", "commonEvents"):
        arr = data.get(key) or []
        out.extend(x for x in arr if isinstance(x, dict))
    return out


def command_lists(data):
    for ev in ev_containers(data):
        if isinstance(ev.get("list"), list):
            yield ev["list"]
        for pg in ev.get("pages") or []:
            if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                yield pg["list"]


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
            out.append((idx, params[0] if params and isinstance(params[0], str)
                        else None))
        elif code == 101 and len(params) >= 5 and isinstance(params[4], str):
            out.append((idx, "【%s】" % params[4]))
        elif code == 102 and params and isinstance(params[0], list):
            out.append((idx, "【选项】%s" % " / ".join(
                str(x) for x in params[0] if isinstance(x, str))))
        else:
            out.append((idx, None))
    return out


def window_for(idx, tl, radius=WINDOW):
    pos = [i for i, (ci, _) in enumerate(tl) if ci == idx]
    if not pos:
        return []
    p = pos[0]
    return [t for _, t in tl[max(0, p - radius):p + radius + 1] if t is not None]


# ---------------------------------------------------------------------------
# Key collectors
# ---------------------------------------------------------------------------
class Collector(object):
    def __init__(self):
        self.keys = set()            # all keys
        self.kind_of = {}            # key -> kind
        self.context = {}            # key -> {"where": ..., "window": [...]}
        self.count = collections.Counter()
        self.name_cands = collections.Counter()

    def add(self, key, kind, where="", window=None):
        if not key:
            return
        self.keys.add(key)
        self.kind_of.setdefault(key, kind)
        self.context.setdefault(key, {"where": where, "window": window or []})
        self.count[key] += 1

    def add_name(self, s):
        if s and len(s) <= 14 and not CTRL.search(s) and NAME_LINE.match(s):
            self.name_cands[s] += 1


def build_name_macros(data_dir):
    """\\N[x] / \\P[x] -> actor name, from Actors.json.  These are macros
    (like C++/LaTeX): the code itself is never translated, the referenced
    actor name is translated in the DB.  The table helps agents understand
    what a code means when they see it in a key."""
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


def iter_message_blocks(cmds, collector, kind="block", where=""):
    """Yield (block_key, [line, ...]) for runs of consecutive 401/405 cmds."""
    tl = talk_lines(cmds)
    i, n = 0, len(cmds)
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
        key = "\n".join(lines)
        collector.add(key, kind, where, window_for(i, tl))
        yield key, lines
        if len(lines) == 1 and key and not CTRL.search(key) \
                and NAME_LINE.match(key.strip()) and len(key.strip()) <= 14:
            collector.name_cands[key.strip()] += 1
        # line keys are redundant for in-block lines: a standalone line is
        # already its own 1-line block key.
        i = j


def process_commands(cmds, collector, where=""):
    tl = talk_lines(cmds)
    for idx, cmd in enumerate(cmds):
        code = cmd.get("code")
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        if code == 102 and params and isinstance(params[0], list):
            for x in params[0]:
                if isinstance(x, str) and JA.search(x):
                    collector.add(x, "choice", where, window_for(idx, tl))
        elif code in EVENT_TEXT_IDX:
            for i2 in EVENT_TEXT_IDX[code]:
                if i2 < len(params) and isinstance(params[i2], str) \
                        and params[i2]:
                    if code == 101 and len(params) >= 5:
                        collector.add_name(params[4])
                    collector.add(params[i2], "event-text", where,
                                  window_for(idx, tl))
        elif code == 122:
            # skip script operands (operandType == 4): params[4] is JS code
            if len(params) > 3 and params[3] == 4:
                pass
            else:
                for i2 in (3, 4):
                    if i2 < len(params) and isinstance(params[i2], str) \
                            and params[i2]:
                        collector.add(params[i2], "event-text", where,
                                      window_for(idx, tl))
        elif code == 408:
            if params and isinstance(params[0], str) and params[0] \
                    and not DIRECTIVE.match(params[0]):
                collector.add(params[0], "help", where, window_for(idx, tl))


def process_db(obj, collector, where=""):
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in DISPLAY_KEYS and isinstance(v, str) and JA.search(v):
                collector.add(v, "db-" + k, where, [])
            elif k == "note" and isinstance(v, str) and JA.search(v):
                collector.add(v, "note", where, [])
            else:
                process_db(v, collector, where)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, collector, where)


def process_system(system, collector):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            collect_values(system[f], collector, "System.json")


def collect_values(obj, collector, where=""):
    if isinstance(obj, str):
        if JA.search(obj):
            collector.add(obj, "system", where, [])
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_values(v, collector, where)
    elif isinstance(obj, list):
        for v in obj:
            collect_values(v, collector, where)


def extract_plugin_text(game_dir, collector):
    """JA-bearing strings in js/plugins.js plugin parameters (kind 'plugin')."""
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.exists(path):
        return 0
    try:
        plugins = plugins_io.parse_plugins_js(
            open(path, encoding="utf-8-sig").read())
    except Exception as e:  # noqa: BLE001 - keep the build going
        log("WARN: plugins.js parse failed (%s) - plugin text skipped" % e)
        return 0
    n = 0
    for where, val in plugins_io.iter_plugin_strings(plugins, JA):
        collector.add(val, "plugin", where, [])
        n += 1
    return n


# ---------------------------------------------------------------------------
# Scene tree
# ---------------------------------------------------------------------------
def build_tree(data, map_id, map_name, display_name, collector):
    """Return the ordered text items of a map/event file for structure.json."""
    items = []
    for ev in ev_containers(data):
        ev_items = {"id": ev.get("id"), "name": ev.get("name"),
                    "items": []}
        where = "%s / EV%03d %s" % (map_name or "?", ev.get("id", 0),
                                    ev.get("name") or "")
        if ev.get("name"):
            collector.add(ev["name"], "event-name", where, [])
        lists = []
        if isinstance(ev.get("list"), list):
            lists.append(ev["list"])
        for pg in ev.get("pages") or []:
            if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                lists.append(pg["list"])
        for lst in lists:
            process_commands(lst, collector, where)
            for block_key, lines in iter_message_blocks(lst, collector,
                                                        where=where):
                ev_items["items"].append({"kind": "block", "key": block_key})
            for c in lst:
                params = c.get("parameters") or []
                if c.get("code") == 102 and params and isinstance(params[0], list):
                    for x in params[0]:
                        if isinstance(x, str) and x in collector.keys:
                            ev_items["items"].append({"kind": "choice", "key": x})
        items.append(ev_items)
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--no-plugins", action="store_true",
                    help="skip js/plugins.js parameter text extraction")
    args = ap.parse_args()

    game_dir = os.path.abspath(args.game_dir)
    out_dir = os.path.abspath(args.out_dir)
    data_dir = os.path.join(game_dir, "data")
    if not os.path.isdir(data_dir):
        sys.exit("no data/ dir under %s" % game_dir)
    os.makedirs(out_dir, exist_ok=True)

    col = Collector()

    # story order from MapInfos
    mapinfos_path = os.path.join(data_dir, "MapInfos.json")
    map_order = []
    map_names = {}
    if os.path.exists(mapinfos_path):
        mi = plain_io.load_json(mapinfos_path)
        for x in mi:
            if x:
                map_order.append((x["id"], x.get("name", "")))
                map_names[x["id"]] = x.get("name", "")

    # per-file collection + tree
    tree = []
    for path in sorted(os.listdir(data_dir)):
        if not path.endswith(".json"):
            continue
        fname = os.path.basename(path)
        with open(os.path.join(data_dir, path), encoding="utf-8-sig") as f:
            data = json.load(f)
        if is_event_container(data):
            map_id = None
            m = re.match(r"Map(\d+)\.json", fname)
            if m:
                map_id = int(m.group(1))
            disp = data.get("displayName") or "" if isinstance(data, dict) else ""
            if disp:
                col.add(disp, "displayName", fname, [])
            if map_id is not None:
                tree.append({"id": map_id, "events": []})
                cur = tree[-1]
                cur["items"] = build_tree(data, map_id, map_names.get(map_id, fname),
                                          disp, col)
            elif fname == "CommonEvents.json":
                tree.append({"id": -1, "events": []})
                tree[-1]["items"] = build_tree(data, None, "CommonEvents",
                                               disp, col)
            else:
                build_tree(data, None, fname, disp, col)
        elif fname == "System.json":
            process_system(data, col)
        else:
            process_db(data, col, fname)

    if not args.no_plugins:
        n = extract_plugin_text(game_dir, col)
        if n:
            log("plugin parameter text: %d strings" % n)

    # drop pure-ASCII keys (EV001-style ids, "OK", ...) - nothing to translate
    ja_keys = {k for k in col.keys if JA.search(k)}
    template = {k: "" for k in sorted(ja_keys, key=lambda k: (-col.count[k], k))}
    col.kind_of = {k: v for k, v in col.kind_of.items() if k in ja_keys}
    col.context = {k: col.context[k] for k in ja_keys}

    # names: name-position + frequent standalone lines
    names = {}
    actors_path = os.path.join(data_dir, "Actors.json")
    if os.path.exists(actors_path):
        for a in plain_io.load_json(actors_path):
            if a and a.get("name"):
                names[a["name"]] = [""]
    for cand, n in col.name_cands.most_common(120):
        names.setdefault(cand, [""])

    name_macros = build_name_macros(data_dir)

    with open(os.path.join(out_dir, "template.json"), "w", encoding="utf-8-sig") as f:
        json.dump(template, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "names.json"), "w", encoding="utf-8-sig") as f:
        json.dump(names, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "kinds.json"), "w", encoding="utf-8-sig") as f:
        json.dump(col.kind_of, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "structure.json"), "w", encoding="utf-8-sig") as f:
        json.dump({"maps": tree}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "context.json"), "w", encoding="utf-8-sig") as f:
        json.dump(col.context, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "name_macros.json"), "w",
              encoding="utf-8-sig") as f:
        json.dump(name_macros, f, ensure_ascii=False, indent=1)

    log("template: %d keys; names: %d candidates; maps: %d; name macros: %d"
        % (len(template), len(names), len(tree), len(name_macros)))


if __name__ == "__main__":
    main()
