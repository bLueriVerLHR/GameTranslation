#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_text.py - Companion to translate_rpgmz.py

Creates a key-value translation template from an RPG Maker MZ game when you
have NO translation file yet. Run it, translate the output JSON, then feed the
result back to translate_rpgmz.py via --trs.

    python extract_text.py <game_dir> [--output translations.json]

Output JSON format (one entry per translatable text line):
    { "キャラ名": "", "俺の妻だ。": "", ... }

Fill the empty strings with your translation, keep values equal to the key for
names you do not want to change, then run:
    python translate_rpgmz.py <game_dir> <out_dir> --trs translations.json
"""

import argparse
import glob
import json
import os
import re
import sys

# Same whitelist as translate_rpgmz.py
DISPLAY_KEYS = {
    "name", "nickname", "profile", "description",
    "message1", "message2", "message3", "message4", "text",
}
EVENT_TEXT_IDX = {401: [0], 405: [0], 101: [4], 402: [1], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = ["terms", "message", "commands", "equipTypes",
                      "weaponTypes", "armorTypes", "skillTypes", "element"]
SYSTEM_TEXT_ARRAYS = ["variables", "switches"]

# Same directive guard as translate_rpgmz.py: comment (408) lines used as
# plugin commands are not display text and must not be extracted.
DIRECTIVE_RE = re.compile(
    r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)

SEGMENT_RE = re.compile(r"(\\\.|\n)")

# Japanese text detector: hiragana / katakana / CJK ideographs
JA_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def is_japanese(s):
    return bool(JA_RE.search(s))


def collect_segments(s, out):
    """Split a text on line-break control codes into clean lines."""
    for part in SEGMENT_RE.split(s):
        if part in ("\\", ".", "\n"):
            continue
        part = part.strip()
        if part and is_japanese(part):
            out.append(part)


def process_commands(cmds, out):
    for cmd in cmds:
        code = cmd.get("code")
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        if code == 102 and params and isinstance(params[0], list):
            for x in params[0]:
                if isinstance(x, str):
                    collect_segments(x, out)
        elif code in EVENT_TEXT_IDX:
            for idx in EVENT_TEXT_IDX[code]:
                if idx < len(params) and isinstance(params[idx], str) and params[idx]:
                    collect_segments(params[idx], out)
        elif code == 122:
            for idx in (3, 4):
                if idx < len(params) and isinstance(params[idx], str) and params[idx]:
                    collect_segments(params[idx], out)
        elif code == 408:
            if params and isinstance(params[0], str) and params[0] and \
                    not DIRECTIVE_RE.match(params[0]):
                collect_segments(params[0], out)


def process_db(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in DISPLAY_KEYS and isinstance(v, str):
                collect_segments(v, out)
            else:
                process_db(v, out)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, out)


def process_system(system, out):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            collect_values(system[f], out)


def collect_values(obj, out):
    if isinstance(obj, str):
        collect_segments(obj, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_values(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_values(v, out)


def iter_event_containers(data):
    containers = []
    if isinstance(data, list):
        containers = data
    elif isinstance(data, dict):
        for key in ("events", "commonEvents"):
            arr = data.get(key)
            if isinstance(arr, list):
                containers.extend(arr)
    return containers


def iter_command_lists(data):
    for ev in iter_event_containers(data):
        if not isinstance(ev, dict):
            continue
        lst = ev.get("list")
        if isinstance(lst, list):
            yield lst
        pages = ev.get("pages")
        if isinstance(pages, list):
            for pg in pages:
                if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                    yield pg["list"]


def is_event_container(data):
    if isinstance(data, dict):
        return "events" in data or "commonEvents" in data
    if isinstance(data, list):
        return any(isinstance(x, dict) and ("list" in x or "pages" in x) for x in data)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_dir", help="source game folder")
    ap.add_argument("--output", default="translations.json",
                    help="output JSON template path (default: translations.json)")
    args = ap.parse_args()

    game_dir = os.path.abspath(args.game_dir)
    if not os.path.isdir(game_dir):
        sys.exit("game_dir not found: %s" % game_dir)

    seen = []
    data_dir = os.path.join(game_dir, "data")
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if is_event_container(data):
            if isinstance(data, dict):
                dn = data.get("displayName")
                if isinstance(dn, str) and dn:
                    collect_segments(dn, seen)
            for lst in iter_command_lists(data):
                process_commands(lst, seen)
            for ev in iter_event_containers(data):
                if isinstance(ev, dict) and isinstance(ev.get("name"), str) and ev["name"]:
                    collect_segments(ev["name"], seen)
        elif os.path.basename(path) == "System.json":
            process_system(data, seen)
        else:
            process_db(data, seen)

    scenario_path = os.path.join(data_dir, "..", "scenario", "Scenario.json")
    if os.path.isfile(scenario_path):
        with open(scenario_path, encoding="utf-8") as f:
            scenario = json.load(f)
        for chunk in scenario.values() if isinstance(scenario, dict) else scenario:
            if isinstance(chunk, list):
                process_commands(chunk, seen)
            elif isinstance(chunk, str):
                collect_segments(chunk, seen)

    unique = list(dict.fromkeys(seen))
    template = {k: "" for k in unique}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)

    print("extracted %d unique text entries -> %s" % (len(unique), args.output))


if __name__ == "__main__":
    main()
