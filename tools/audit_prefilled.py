#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_prefilled.py - Audit an MTool-exact-hit prefilled file BEFORE merging:
flag values that still contain kana lines (multi-line block keys where one
line missed the dict), so leftover lines are hand-translated early instead of
polluting the bake.

Consolidated from the long-run session audit_prefilled.py (docs/translation.md).

Usage:
    python tools\\audit_prefilled.py <prefilled.json> [--out <fixed.json>]
"""
import argparse
import json
import re

KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("prefilled")
    args = ap.parse_args()

    p = json.load(open(args.prefilled, encoding="utf-8"))
    residual = []
    for k, v in p.items():
        kl = k.split("\n")
        vl = v.split("\n")
        if len(vl) != len(kl):
            residual.append((k, v, "line-count mismatch"))
            continue
        for i, (kk, vv) in enumerate(zip(kl, vl)):
            if KANA.search(vv) and not KANA.search(kk):
                residual.append((k, v, "line %d: %s" % (i, vv[:40])))
                break

    print("values with residual kana / mismatched lines: %d / %d"
          % (len(residual), len(p)))
    for k, v, why in residual[:20]:
        print("  K:", repr(k)[:70])
        print("  V:", repr(v)[:70], "|", why)


if __name__ == "__main__":
    main()
