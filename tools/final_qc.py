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
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctrl_codes  # noqa: E402
import japanese_utils  # noqa: E402

KANA = japanese_utils.KANA
CODE = re.compile(r"\\[A-Za-z]+(?:\[[^\]]*\])?")
UNCERTAIN = re.compile(r"【[^】]*\?[^】]*】")
ctrl_signature = ctrl_codes.ctrl_signature

# Report sections, in the order main() prints them: (label, finding key).
REPORTS = (
    ("empty values", "empty"),
    ("kana residual", "kana"),
    ("line-count mismatches", "lines"),
    ("double-backslash values", "dbl"),
    ("uncertainty markers", "mark"),
    ("identity values (len>2)", "ident"),
    ("control-code token diffs", "code"),
)


def collect(p, exemptions=()):
    """Findings of the merged dictionary, keyed by report name.

    `p` is the merged {ja: zh} mapping; non-string values are skipped (a
    malformed entry is not a translation problem to report here).
    `exemptions` are compiled regexes matched against VALUES to silence the
    kana-residual check (onomatopoeia, author-name lines).
    """
    found = {key: [] for _label, key in REPORTS}
    for k, v in p.items():
        if not isinstance(v, str):
            continue
        if not v.strip():
            found["empty"].append(k)
        if KANA.search(v):
            if not any(ex.search(v) for ex in exemptions):
                found["kana"].append((k, v))
        if v.count("\n") != k.count("\n"):
            found["lines"].append((k, v))
        if "\\\\" in v:
            found["dbl"].append((k, v))
        if UNCERTAIN.search(v):
            found["mark"].append((k, v))
        if v == k and len(k) > 2:
            found["ident"].append((k, v))
        if sorted(CODE.findall(k)) != sorted(CODE.findall(v)) and \
                sorted(ctrl_signature(k)) != sorted(ctrl_signature(v)):
            found["code"].append((k, v))
    return found


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

    found = collect(p, exemptions)

    def report(name, items, show=10):
        print("%s: %d" % (name, len(items)))
        for item in items[:show]:
            if isinstance(item, tuple):
                print("   ", repr(item[0])[:70], "=>", repr(item[1])[:70])
            else:
                print("   ", repr(item)[:80])

    for label, key in REPORTS:
        report(label, found[key])


if __name__ == "__main__":
    main()
