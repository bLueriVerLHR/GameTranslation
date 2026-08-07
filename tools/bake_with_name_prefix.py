#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bake_with_name_prefix.py - Re-bake an MTool dict with name-prefix-aware exact
matching, on top of bake_translation.py.

MTool repacks store dialogue lines as "\\N<name>\\u3000body" (name often mangled
to "\\n[N]" by the repack), while the dict keys are the bare body lines.  Plain
exact matching therefore misses every prefixed line.  This tool reuses
bake_translation.py's walkers but extends the lookup:

    1. exact whole-line key first (as before)
    2. if the line starts with "\\N<", strip the name tag + optional
       "\\u3000" separator, and look the body up exactly; on a hit the
       translated body is written back KEEPING the name tag

Exact-match only - no fragment replacement, so no cross-branch pollution.

Usage:
    python bake_with_name_prefix.py <game_dir> <out_dir> --trs dict.json
"""
import argparse
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bake_translation as B

log = logging.getLogger("bake-prefix")

NAME_TAG_RE = re.compile(r'(\\N<.*?>)\s*(\u3000*)(.*)$', re.S)


def exact(s, D):
    v = D.get(s)
    if isinstance(v, str) and v:
        return v
    if s.startswith("\\N<"):
        m = NAME_TAG_RE.match(s)
        if m and m.group(3):
            body = D.get(m.group(3))
            if isinstance(body, str) and body:
                return m.group(1) + m.group(2) + body
    if s.startswith("\\CL"):
        body = s[3:]
        if body.startswith("\\{"):
            body = body[2:]
        elif body.startswith("{"):
            body = body[1:]
        v = D.get(body)
        if isinstance(v, str) and v:
            return "\\CL" + v
    return None


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--trs", required=True, help="MTool dict JSON ({jp: zh})")
    args = ap.parse_args()

    game_dir = os.path.abspath(args.game_dir)
    out_dir = os.path.abspath(args.out_dir)
    if not os.path.isdir(game_dir):
        sys.exit("game_dir not found: %s" % game_dir)
    if os.path.abspath(out_dir) == game_dir:
        sys.exit("out_dir must differ from game_dir")

    D = json.load(open(args.trs, encoding="utf-8"))
    log.info("loaded %d dict entries", len(D))

    log.info("copying %s -> %s", game_dir, out_dir)
    import shutil
    shutil.copytree(game_dir, out_dir, dirs_exist_ok=True)

    B.decrypt_dir(out_dir)
    B.clear_encryption_flags(out_dir)
    orig = B.exact
    B.exact = exact
    try:
        B.translate_data(out_dir, D)
    finally:
        B.exact = orig
    log.info("done -> %s", out_dir)


if __name__ == "__main__":
    main()
