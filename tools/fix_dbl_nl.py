#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_dbl_nl.py - repair values that contain literal \\n text where the KEY
has a real newline: convert literal \\n back to real newlines. Opposite of
fix_literal_nl.py. (Agent wrote "\\n" escape text for actual line breaks.)

Usage:
    python tools\\fix_dbl_nl.py <work_dir> [--chunks chunks]
"""
import argparse
import glob
import json
import os


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_dir")
    ap.add_argument("--chunks", default="chunks")
    args = ap.parse_args()
    W = os.path.join(os.path.abspath(args.work_dir), args.chunks)
    total = 0
    for tp in sorted(glob.glob(os.path.join(W, "*.translated.json"))):
        src_path = tp.replace(".translated.json", ".json")
        if not os.path.exists(src_path):
            continue
        src = json.load(open(src_path, encoding="utf-8"))
        out = json.load(open(tp, encoding="utf-8"))
        ch = 0
        for k, v in out.items():
            if "\\n" not in v:
                continue
            if k.count("\n") > 0 and v.count("\n") < k.count("\n"):
                out[k] = v.replace("\\n", "\n")
                ch += 1
        if ch:
            json.dump(out, open(tp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("%s: %d literal-\\n -> real-newline" % (os.path.basename(tp), ch))
            total += ch
    print("total:", total)


if __name__ == "__main__":
    main()
