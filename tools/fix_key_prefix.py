#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_key_prefix.py - repair agent output where values start with the key
text ("original line + translated line", e.g. V = K + "\\n" + translation).
Strips the leading key from every affected value in a chunks dir.

Usage:
    python tools\\fix_key_prefix.py <work_dir> [--chunks chunks]
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
        out = json.load(open(tp, encoding="utf-8"))
        ch = 0
        for k, v in out.items():
            if isinstance(v, str) and v.startswith(k) and len(v) > len(k):
                rest = v[len(k):]
                rest = rest.lstrip("\n")
                if rest and rest != v:
                    out[k] = rest
                    ch += 1
        if ch:
            json.dump(out, open(tp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("%s: stripped key-prefix in %d values"
                  % (os.path.basename(tp), ch))
            total += ch
    print("total:", total)


if __name__ == "__main__":
    main()
