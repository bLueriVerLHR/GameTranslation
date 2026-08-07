#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final_qc.py - Final QC on the MERGED translation file (translated.json /
completion.json), after the per-chunk pass.

Consolidated from long-run session scripts (final_qc.py + audit_prefilled.py).
Run against the merged output of qc_translation_chunks.py --merge.

Checks (each printed with a count + samples):
  empty values, kana residual, line-count mismatch vs key, double backslash,
  【?】 uncertainty markers, identity values (value == key, len > 2),
  control-code token diff key-vs-value.

Usage:
    python tools\\final_qc.py <merged.json> [--exempt kana_whitelist.txt]
"""
import argparse
import json
import re
import sys

KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")
CODE = re.compile(r"\\[A-Za-z]+(?:\[[^\]]*\])?")
UNCERTAIN = re.compile(r"【[^】]*\?[^】]*】")
CTRL_NORM = re.compile(r"\\[A-Za-z]+\[([^\]]*)\]")


def ctrl_signature(s):
    """Control-code sequence as a comparable signature: ordered list of
    (token-name, arg-count) tuples; translated args don't diff, only structure."""
    return [("%s" % m.group(0)[1:m.group(0).find("[")],
             m.group(1).count(",") + 1)
            for m in CTRL_NORM.finditer(s)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("merged_json")
    ap.add_argument("--exempt", default="",
                    help="file with regexes (one per line) matched against "
                         "VALUES; matching values are exempted from the kana "
                         "residual check (e.g. onomatopoeia, author-name lines)")
    args = ap.parse_args()

    p = json.load(open(args.merged_json, encoding="utf-8"))
    exemptions = []
    if args.exempt and sys.stdin and args.exempt != "-":
        for line in open(args.exempt, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                exemptions.append(re.compile(line))

    empty, kana, lines, dbl, mark, ident, code = [], [], [], [], [], [], []
    for k, v in p.items():
        if not isinstance(v, str):
            continue
        if not v.strip():
            empty.append(k)
        if KANA.search(v):
            if not any(ex.search(v) for ex in exemptions):
                kana.append((k, v))
        if v.count("\n") != k.count("\n"):
            lines.append((k, v))
        if "\\\\" in v:
            dbl.append((k, v))
        if UNCERTAIN.search(v):
            mark.append((k, v))
        if v == k and len(k) > 2:
            ident.append((k, v))
        if sorted(CODE.findall(k)) != sorted(CODE.findall(v)) and \
                sorted(ctrl_signature(k)) != sorted(ctrl_signature(v)):
            code.append((k, v))

    def report(name, items, show=10):
        print("%s: %d" % (name, len(items)))
        for item in items[:show]:
            if isinstance(item, tuple):
                print("   ", repr(item[0])[:70], "=>", repr(item[1])[:70])
            else:
                print("   ", repr(item)[:80])

    report("empty values", empty)
    report("kana residual", kana)
    report("line-count mismatches", lines)
    report("double-backslash values", dbl)
    report("uncertainty markers", mark)
    report("identity values (len>2)", ident)
    report("control-code token diffs", code)


if __name__ == "__main__":
    main()
