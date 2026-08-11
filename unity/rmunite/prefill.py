"""Prefill each game's translated.json from a previous game's translations + handle character names.
Usage: python prefill.py <work_dir> <game_key> [--names names.json]"""
import argparse
import json
import os
import re

ap = argparse.ArgumentParser()
ap.add_argument("work_dir", help="work dir holding the series base translated.json")
ap.add_argument("game_key", help="per-game subdir name in the work dir")
ap.add_argument("--names", default="",
                help="optional {game_key: {name: translation}} table file; "
                     "without it the 【name】 prefix is left untouched")
args = ap.parse_args()

OUT = os.path.abspath(args.work_dir)
KEY = args.game_key
base = json.load(open(os.path.join(OUT, "translated.json"), encoding="utf-8"))
meta = json.load(open(os.path.join(OUT, KEY, "keys_target_meta.json"), encoding="utf-8"))

# character name table per game (from CharacterActorSO if present, plus known series names)
NAMES = {}
if args.names and os.path.exists(args.names):
    NAMES = json.load(open(args.names, encoding="utf-8")).get(KEY, {})

def translate_line(text, names):
    # exact match first
    if text in base:
        return base[text]
    # [名字] prefix replacement
    m = re.match(r"^(【([^】]+)】)(.*)$", text)
    if m:
        prefix, name, rest = m.group(1), m.group(2), m.group(3)
        newname = names.get(name)
        if newname:
            tail = base.get(rest, rest)
            return "【" + newname + "】" + tail
    return None

final = {}
unresolved = []
for k in meta:
    t = translate_line(k, NAMES)
    if t:
        final[k] = t
    else:
        unresolved.append(k)

with open(os.path.join(OUT, KEY, "translated_prefill.json"), "w", encoding="utf-8") as f:
    json.dump(final, f, ensure_ascii=False, indent=1)

print(f"{KEY}: total={len(meta)} prefill={len(final)} unresolved={len(unresolved)}")
with open(os.path.join(OUT, KEY, "unresolved.txt"), "w", encoding="utf-8") as f:
    for t in unresolved:
        f.write(t.replace("\n", "\\n") + "\n")
