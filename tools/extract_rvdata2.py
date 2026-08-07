#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
extract_rvdata2.py - Build a static-translation work package from an RPG
Maker VX Ace game by parsing the .rvdata2 (Ruby Marshal) files from zero.

Outputs the SAME work package contract as build_translation.py (MZ/MV), so
the rest of the pipeline (gen_translation_shards, merge_plain_chunks,
merge_translation, bake) works unchanged:

  template.json    {key: ""} - message blocks (consecutive 401/405 lines
                   joined with \n), choices, DB display fields, System UI,
                   map/common-event names, notes (untagged only)
  kinds.json       key -> kind
  structure.json   maps in story order (@order) -> events -> ordered blocks
  context.json     key -> {"where", "window"} (context only, not translated)
  names.json       candidate character names
  name_macros.json \N[x] / \P[x] -> actor name (macros, never translated)

VX Ace command codes: 101 show text (face only, no speaker name), 401/405
message lines, 102 choices, 402/403/404 choice branches, 408/108 comments,
122 control variables (int only, skip), 355/655 scripts (never translate),
320 actor name change (params [actorId, name]).

Usage:
    python extract_rvdata2.py <game_dir> <out_dir>
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402
from rvdata2_io import load_rvdata2  # noqa: E402

CTRL = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?")
JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")
NAME_LINE = re.compile(r"^(?:[\u3040-\u30ff\u4e00-\u9fff]|・)+[さんちゃん君様先生嬢ぽ]?$")
DIRECTIVE = re.compile(r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)
NOTE_TAG = re.compile(r"<[A-Za-z_@][^>]*>")
NOTE_JSON = re.compile(r"^\s*[{\[\"]")
TAG_STRIP = re.compile(r"<[^>]*>")
WINDOW = 2

DISPLAY_KEYS = {"name", "nickname", "profile", "description",
                "message1", "message2", "message3", "message4", "text"}
EVENT_TEXT_IDX = {402: [0], 320: [1]}
SYSTEM_TEXT_FIELDS = ["terms", "messages", "commands", "skill_types",
                      "weapon_types", "armor_types", "elements",
                      "equip_types", "variables", "switches"]
TALK_CODES = (401, 405, 101, 102)

SKIP_KEYS = {"@data", "@screen_x", "@screen_y", "@scroll_x", "@scroll_y",
             "@encounter_list", "@parallax_name", "@battleback1_name",
             "@battleback2_name", "@bgm", "@bgs", "@title_name",
             "@gameover_name", "@party_name", "@currency_unit",
             "@version_id", "@start_map_id", "@start_x", "@start_y"}


def log(msg):
    print(msg, flush=True)


def ev_containers(data):
    """Events from a map/CommonEvents object (VX Ace events = dict)."""
    if isinstance(data, dict):
        evs = data.get("@events") or {}
        if isinstance(evs, dict):
            return [evs[k] for k in sorted(evs, key=lambda k: (k is None, k))
                    if isinstance(evs[k], dict)]
        if isinstance(evs, list):
            return [e for e in evs if isinstance(e, dict)]
    return []


def is_map_file(fname):
    return bool(re.match(r"Map\d{3}\.rvdata2$", fname))


def talk_lines(lst):
    out = []
    for idx, cmd in enumerate(lst):
        code = cmd.get("@code")
        params = cmd.get("@parameters") or []
        if code in (401, 405):
            out.append((idx, params[0] if params and isinstance(params[0], str)
                        else None))
        elif code == 101:
            out.append((idx, "【表情:%s】" % params[0]
                        if params and isinstance(params[0], str) else None))
        elif code == 102:
            choices = params[0] if params and isinstance(params[0], list) else []
            out.append((idx, "【选项】%s" % " / ".join(
                str(x) for x in choices if isinstance(x, str))))
        else:
            out.append((idx, None))
    return out


def window_for(idx, tl, radius=WINDOW):
    pos = [i for i, (ci, _) in enumerate(tl) if ci == idx]
    if not pos:
        return []
    p = pos[0]
    return [t for _, t in tl[max(0, p - radius):p + radius + 1] if t is not None]


class Collector(object):
    def __init__(self):
        self.keys = set()
        self.kind_of = {}
        self.context = {}
        self.count = collections.Counter()
        self.name_cands = collections.Counter()

    def add(self, key, kind, where="", window=None):
        if not key or not JA.search(key):
            return
        # functional plugin-tag lines (e.g. <装備タイプ:5>) have no JA left
        # once tags are stripped - never display text, never translated
        if TAG_STRIP.sub("", key) and not JA.search(TAG_STRIP.sub("", key)):
            return
        self.keys.add(key)
        self.kind_of.setdefault(key, kind)
        self.context.setdefault(key, {"where": where, "window": window or []})
        self.count[key] += 1

    def add_name(self, s):
        if s and len(s) <= 14 and not CTRL.search(s) and NAME_LINE.match(s):
            self.name_cands[s] += 1


def iter_message_blocks(cmds, collector, where=""):
    """Yield (block_key, [line, ...]) for runs of consecutive 401/405 cmds."""
    tl = talk_lines(cmds)
    i, n = 0, len(cmds)
    while i < n:
        code = cmds[i].get("@code")
        if code not in (401, 405):
            i += 1
            continue
        j = i
        lines = []
        while j < n and cmds[j].get("@code") in (401, 405):
            params = cmds[j].get("@parameters") or []
            lines.append(params[0] if params and isinstance(params[0], str)
                         else "")
            j += 1
        key = "\n".join(lines)
        collector.add(key, "block", where, window_for(i, tl))
        yield key, lines
        if len(lines) == 1 and key and not CTRL.search(key) \
                and NAME_LINE.match(key.strip()) and len(key.strip()) <= 14:
            collector.name_cands[key.strip()] += 1
        i = j


def process_commands(cmds, collector, where=""):
    tl = talk_lines(cmds)
    for idx, cmd in enumerate(cmds):
        code = cmd.get("@code")
        params = cmd.get("@parameters")
        if not isinstance(params, list):
            continue
        if code == 102 and params and isinstance(params[0], list):
            for x in params[0]:
                if isinstance(x, str):
                    collector.add(x, "choice", where, window_for(idx, tl))
        elif code in EVENT_TEXT_IDX:
            for pidx in EVENT_TEXT_IDX[code]:
                if pidx < len(params) and isinstance(params[pidx], str) \
                        and params[pidx]:
                    collector.add(params[pidx], "event-text", where,
                                  window_for(idx, tl))
        elif code == 408:
            if params and isinstance(params[0], str) and params[0] \
                    and not DIRECTIVE.match(params[0]):
                collector.add(params[0], "help", where, window_for(idx, tl))


def process_db(obj, collector, where=""):
    """Whitelist-walk any decoded DB object: DISPLAY_KEYS fields + notes."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if not isinstance(k, str) or k.startswith("@"):
                k = k.lstrip("@")
            if k in DISPLAY_KEYS and isinstance(v, str) and JA.search(v):
                collector.add(v, "db-" + k, where, [])
            elif k == "note" and isinstance(v, str) and JA.search(v):
                if NOTE_TAG.search(v) or (NOTE_JSON.match(v) and len(v) > 80):
                    continue  # functional plugin data, never display text
                collector.add(v, "note", where, [])
            elif isinstance(v, (dict, list)):
                process_db(v, collector, where)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, collector, where)


def process_system(system, collector):
    for f in SYSTEM_TEXT_FIELDS:
        v = system.get("@" + f)
        if v is not None:
            collect_values(v, collector, "System.json")


def collect_values(obj, collector, where=""):
    if isinstance(obj, str):
        if JA.search(obj) and not obj.startswith("@"):
            collector.add(obj, "system", where, [])
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_values(v, collector, where)
    elif isinstance(obj, list):
        for v in obj:
            collect_values(v, collector, where)


def build_name_macros(actors):
    macros = {}
    for a in actors or []:
        if not isinstance(a, dict) or not a.get("@name"):
            continue
        for code in ("N", "P"):
            macros["\\%s[%d]" % (code, a.get("@id", 0))] = a["@name"]
    return macros


def build_structure_tree(ce_data, collector, where_prefix):
    """Ordered text items of one rvdata2 container for structure.json."""
    items = []
    for ev in ev_containers(ce_data):
        ev_items = {"id": ev.get("@id"), "name": ev.get("@name"), "items": []}
        where = "%s / EV%03d %s" % (where_prefix, ev.get("@id", 0),
                                    ev.get("@name") or "")
        if ev.get("@name"):
            collector.add(ev["@name"], "event-name", where, [])
        for pg in ev.get("@pages") or []:
            if not isinstance(pg, dict):
                continue
            lst = pg.get("@list") or []
            process_commands(lst, collector, where)
            for block_key, _lines in iter_message_blocks(lst, collector, where):
                ev_items["items"].append({"kind": "block", "key": block_key})
            for c in lst:
                params = c.get("@parameters") or []
                if c.get("@code") == 102 and params and isinstance(params[0], list):
                    for x in params[0]:
                        if isinstance(x, str) and x in collector.keys:
                            ev_items["items"].append({"kind": "choice", "key": x})
        items.append(ev_items)
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_dir")
    ap.add_argument("out_dir")
    args = ap.parse_args()

    game_dir = os.path.abspath(args.game_dir)
    out_dir = os.path.abspath(args.out_dir)
    data_dir = os.path.join(game_dir, "data")
    if not os.path.isdir(data_dir):
        sys.exit("no data/ dir under %s" % game_dir)
    os.makedirs(out_dir, exist_ok=True)

    col = Collector()

    # story order from MapInfos (@order)
    map_order = []   # (order, id, name)
    mi_path = os.path.join(data_dir, "MapInfos.rvdata2")
    mi_data = load_rvdata2(mi_path) if os.path.exists(mi_path) else []
    for x in mi_data or []:
        if isinstance(x, dict):
            map_order.append((x.get("@order", 0), x.get("@id", 0),
                              x.get("@name", "")))
    map_order.sort(key=lambda t: (t[0], t[1]))
    map_name = {i: n for _o, i, n in map_order}

    # 1) maps in story order
    tree = []
    seen_maps = set()
    for _o, mid, mname in map_order:
        fname = "Map%03d.rvdata2" % mid
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            continue
        data = load_rvdata2(path)
        if not isinstance(data, dict):
            continue
        seen_maps.add(fname)
        disp = data.get("@display_name") or ""
        if disp:
            col.add(disp, "displayName", mname, [])
        node = {"id": mid, "events": []}
        node["items"] = build_structure_tree(data, col, mname or fname)
        tree.append(node)

    # 2) map files missing from MapInfos (defensive)
    for fname in sorted(os.listdir(data_dir)):
        if not is_map_file(fname) or fname in seen_maps:
            continue
        data = load_rvdata2(os.path.join(data_dir, fname))
        if not isinstance(data, dict):
            continue
        m = re.match(r"Map(\d{3})\.rvdata2", fname)
        tree.append({"id": int(m.group(1)), "events": []})
        tree[-1]["items"] = build_structure_tree(data, col, fname)

    # 3) CommonEvents (dialogue-heavy: names + blocks + choices)
    ce_path = os.path.join(data_dir, "CommonEvents.rvdata2")
    if os.path.exists(ce_path):
        ce = load_rvdata2(ce_path)
        ce_items = []
        for ev in ev_containers({"@events": ce} if isinstance(ce, list) else ce):
            where = "CommonEvents / EV%03d %s" % (ev.get("@id", 0),
                                                  ev.get("@name") or "")
            ev_items = {"id": ev.get("@id"), "name": ev.get("@name"),
                        "items": []}
            if ev.get("@name"):
                col.add(ev["@name"], "event-name", "CommonEvents", [])
            for lst in ([ev["@list"]] if isinstance(ev.get("@list"), list)
                        else []):
                process_commands(lst, col, where)
                for block_key, _l in iter_message_blocks(lst, col, where):
                    ev_items["items"].append({"kind": "block", "key": block_key})
                for c in lst:
                    params = c.get("@parameters") or []
                    if c.get("@code") == 102 and params and \
                            isinstance(params[0], list):
                        for x in params[0]:
                            if isinstance(x, str) and x in collector.keys:
                                ev_items["items"].append(
                                    {"kind": "choice", "key": x})
            ce_items.append(ev_items)
        tree.append({"id": -1, "events": [], "items": ce_items})

    # 4) DB files + System
    for fname in ("System.rvdata2", "Actors.rvdata2", "Classes.rvdata2",
                  "Skills.rvdata2", "Items.rvdata2", "Weapons.rvdata2",
                  "Armors.rvdata2", "Enemies.rvdata2", "States.rvdata2",
                  "Animations.rvdata2", "Tilesets.rvdata2", "Troops.rvdata2",
                  "CommonEvents.rvdata2"):
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            continue
        data = load_rvdata2(path)
        if fname == "System.rvdata2" and isinstance(data, dict):
            process_system(data, col)
            if data.get("@game_title"):
                col.add(data["@game_title"], "system", "System.json", [])
            continue
        process_db(data, col, fname)

    # 5) names: actors + frequent standalone lines
    names = {}
    actors = load_rvdata2(os.path.join(data_dir, "Actors.rvdata2")) \
        if os.path.exists(os.path.join(data_dir, "Actors.rvdata2")) else []
    for a in actors or []:
        if isinstance(a, dict) and a.get("@name"):
            names[a["@name"]] = [""]
    for cand, n in col.name_cands.most_common(120):
        names.setdefault(cand, [""])

    template = {k: "" for k in sorted(
        col.keys, key=lambda k: (-col.count[k], k))}
    col.kind_of = {k: v for k, v in col.kind_of.items() if k in col.keys}
    col.context = {k: col.context[k] for k in col.keys}

    with open(os.path.join(out_dir, "template.json"), "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "kinds.json"), "w", encoding="utf-8") as f:
        json.dump(col.kind_of, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "structure.json"), "w", encoding="utf-8") as f:
        json.dump({"maps": tree}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "context.json"), "w", encoding="utf-8") as f:
        json.dump(col.context, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "names.json"), "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "name_macros.json"), "w",
              encoding="utf-8") as f:
        json.dump(build_name_macros(actors), f, ensure_ascii=False, indent=1)

    log("template: %d keys; names: %d candidates; maps: %d"
        % (len(template), len(names), len(tree)))


if __name__ == "__main__":
    main()
