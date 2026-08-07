#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch the translation dict so character names use consistent Chinese
transliterations.  The replacement rules are game-specific and MUST come from
an external rules file, never hardcoded here:

rules.json:
{
  "value_replacements": [["旧译", "新译"], ...],   # applied to every value, in order
  "name_keys": {"日文名": "中文名", ...}            # exact key -> canonical value
}

Replacement-order tricks (e.g. protecting a proper noun via a placeholder so a
generic rule can't mangle it) are a rule-file concern - see the example in
the docstring of gen_csv_shards.py's tone block for the general pattern.

Usage: python patch_names.py <in_dict.json> <out_dict.json> [rules.json]
Writes a new JSON; the original dict is not modified.  Without rules.json the
script is a no-op (reports 0 changes).
"""
import json
import sys


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        D = json.load(f)

    rules = {}
    if len(sys.argv) == 4:
        with open(sys.argv[3], encoding="utf-8") as f:
            rules = json.load(f)
    else:
        print("no rules file given - nothing to do")
        return

    value_replacements = rules.get("value_replacements", [])
    name_keys = rules.get("name_keys", {})

    changed = 0
    for k, v in list(D.items()):
        if not isinstance(v, str):
            continue
        new_v = v
        for old, new in value_replacements:
            new_v = new_v.replace(old, new)
        if new_v != v:
            D[k] = new_v
            changed += 1

    for k, v in name_keys.items():
        if D.get(k) != v:
            D[k] = v
            changed += 1

    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False, indent=2)
    print("patched %d entries -> %s" % (changed, sys.argv[2]))


if __name__ == "__main__":
    main()
