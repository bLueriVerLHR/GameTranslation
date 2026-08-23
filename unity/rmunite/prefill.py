"""Prefill each game's translated.json from a previous game's translations + handle character names.

Usage: python prefill.py <work_dir> <game_key> [--names names.json]

The parameter parsing lives inside main() so the module can be imported
without executing anything (this package is a set of standalone tools that
share per-game helpers).
"""
import argparse
import json
import os
import re


def translate_line(text, base, names):
    """Translate one key: exact base hit first, then 【Name】 prefix
    replacement (look the body up in base, replacing the name)."""
    # exact match first
    if text in base:
        return base[text]
    # [Name] prefix replacement
    m = re.match(r"^(【([^】]+)】)(.*)$", text)
    if m:
        name, rest = m.group(2), m.group(3)
        newname = names.get(name)
        if newname:
            tail = base.get(rest, rest)
            return "【" + newname + "】" + tail
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir", help="work dir holding the series base translated.json")
    ap.add_argument("game_key", help="per-game subdir name in the work dir")
    ap.add_argument("--names", default="",
                    help="optional {game_key: {name: translation}} table file; "
                         "without it the 【name】 prefix is left untouched")
    args = ap.parse_args()

    out = os.path.abspath(args.work_dir)
    key = args.game_key
    base = json.load(open(os.path.join(out, "translated.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(out, key, "keys_target_meta.json"),
                          encoding="utf-8"))

    # character name table per game (from CharacterActorSO if present, plus
    # known series names)
    names = {}
    if args.names and os.path.exists(args.names):
        names = json.load(open(args.names, encoding="utf-8")).get(key, {})

    final = {}
    unresolved = []
    for k in meta:
        t = translate_line(k, base, names)
        if t:
            final[k] = t
        else:
            unresolved.append(k)

    with open(os.path.join(out, key, "translated_prefill.json"), "w",
              encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=1)

    print("%s: total=%d prefill=%d unresolved=%d"
          % (key, len(meta), len(final), len(unresolved)))
    with open(os.path.join(out, key, "unresolved.txt"), "w",
              encoding="utf-8") as f:
        for t in unresolved:
            f.write(t.replace("\n", "\\n") + "\n")


if __name__ == "__main__":
    main()
