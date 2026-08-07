#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_translation.py - Final merge of prefilled (MTool exact hits) + agent
chunks into translated.json, with an optional terminology sweep.

Consolidated from the long-run session merge script. Sweep rules come from a
JSON list [[from, to], ...] or {"from": "to"} file, applied IN ORDER.

WARNING (substring bomb, docs/translation.md §4.2): a sweep target
that itself contains the prefix of another rule (色经验值->色色经验值) will be
re-hit if applied later. Order rules longest-first, and afterwards re-scan
the output for any malformed target strings.

Usage:
    python tools\\merge_translation.py <work_dir> --chunks chunks_translated.json \\
        --prefilled <prefilled.json> [--sweep <sweep_rules.json>] [--out translated.json]

  --chunks    the merge_plain_chunks.py output (agent chunks).  Omitted for
              legacy: globs chunks/*.translated.json.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402


def load_sweeps(path):
    rules = plain_io.load_json(path)
    if isinstance(rules, dict):
        rules = list(rules.items())
    # longest-first so longer targets apply before their own prefixes
    rules.sort(key=lambda r: len(r[0]), reverse=True)
    return rules


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_dir")
    ap.add_argument("--chunks", default="",
                    help="merge_plain_chunks.py output (default: glob legacy "
                         "chunks/*.translated.json)")
    ap.add_argument("--prefilled", default="",
                    help="prefilled.json (MTool exact hits); optional")
    ap.add_argument("--sweep", default="",
                    help="terminology sweep rules JSON (list of pairs)")
    ap.add_argument("--out", default="translated.json")
    args = ap.parse_args()

    work = os.path.abspath(args.work_dir)
    sweeps = load_sweeps(args.sweep) if args.sweep else []

    def sweep(v):
        for a, b in sweeps:
            v = v.replace(a, b)
        return v

    merged = {}
    if args.chunks:
        d = plain_io.load_json(os.path.join(work, args.chunks))
        for k, v in d.items():
            merged[k] = sweep(v)
        print("chunks merged: %d keys (from %s)" % (len(merged), args.chunks))
    else:
        for p in sorted(glob.glob(os.path.join(work, "chunks", "*.translated.json"))):
            d = plain_io.load_json(p)
            for k, v in d.items():
                merged[k] = sweep(v)
        print("chunks merged: %d keys" % len(merged))

    if args.prefilled:
        pref = plain_io.load_json(args.prefilled)
        pref_swept = 0
        for k, v in pref.items():
            nv = sweep(v)
            if nv != v:
                pref_swept += 1
            merged[k] = nv
        print("prefilled merged: %d keys (%d swept)" % (len(pref), pref_swept))
    print("sweep rules applied: %d" % len(sweeps))

    tpl = plain_io.load_json(os.path.join(work, "template.json"))
    missing = [k for k in tpl if k not in merged]
    extra = [k for k in merged if k not in tpl]
    print("merged keys: %d | template keys: %d | missing: %d | extra: %d"
          % (len(merged), len(tpl), len(missing), len(extra)))

    out = os.path.join(work, args.out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    print("wrote %s with %d keys" % (out, len(merged)))


if __name__ == "__main__":
    main()
