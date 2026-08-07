#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_plain_chunks.py - Merge the two-file chunk format into a
translation KV dict.

For every chunks/chunk_NN.ja.txt with a matching chunk_NN.zh.txt:
  - unescape both files (plain_io: \\n = real newline, \\\\ = one backslash),
  - zip keys with their translations (line N of zh.txt = line N of ja.txt),
  - QC the pair (line count, kana left, control-code tokens, empty values,
    uncertainty markers, double backslashes),
  - merge into the output dict.

Writes <work_dir>/chunks_translated.json (default) - the agent-chunk merge
that merge_translation.py combines with prefilled hits / sweep rules into the
final translated.json.

Usage:
    python merge_plain_chunks.py <work_dir> [--out chunks_translated.json]
                                 [--strict] [--no-report]
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402

KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")
CTRL_TOK = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?")
CTRL_NORM = re.compile(r"\\[A-Za-z]+\[([^\]]*)\]")
UNCERTAIN = re.compile(r"【[^】]*\?[^】]*】")


def ctrl_signature(s):
    """Control-code sequence as a comparable signature: ordered list of
    (token-name, arg-count) pairs; translated args don't produce false diffs."""
    return [("%s" % m.group(0)[1:m.group(0).find("[")],
             m.group(1).count(",") + 1)
            for m in CTRL_NORM.finditer(s)]


def qc_pair(keys, vals, idx):
    """QC one chunk pair.  Returns (issues: [str], ok: bool)."""
    issues = []
    if len(keys) != len(vals):
        issues.append("line count mismatch: ja=%d zh=%d"
                      % (len(keys), len(vals)))
        return issues, False
    newline_diff = kana_left = ctrl_diff = empty = uncertain = 0
    dbl_backslash = 0
    for k, v in zip(keys, vals):
        if not isinstance(v, str):
            continue
        if v.count("\n") != k.count("\n"):
            newline_diff += 1
        if KANA.search(CTRL_TOK.sub("", v)):
            kana_left += 1
        if sorted(CTRL_TOK.findall(k)) != sorted(CTRL_TOK.findall(v)) and \
                sorted(ctrl_signature(k)) != sorted(ctrl_signature(v)):
            ctrl_diff += 1
        if "\\\\" in v:
            dbl_backslash += 1
        if UNCERTAIN.search(v):
            uncertain += 1
        if not v:
            empty += 1
    if newline_diff:
        issues.append("newline-count mismatch: %d" % newline_diff)
    if kana_left:
        issues.append("kana still in values: %d" % kana_left)
    if ctrl_diff:
        issues.append("control-code tokens differ: %d" % ctrl_diff)
    if empty:
        issues.append("empty single-line values: %d" % empty)
    if dbl_backslash:
        issues.append("double-backslash values: %d" % dbl_backslash)
    if uncertain:
        issues.append("uncertainty markers 【?】 left: %d" % uncertain)
    return issues, not issues


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_dir")
    ap.add_argument("--out", default="chunks_translated.json")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when any chunk has issues")
    args = ap.parse_args()

    work = os.path.abspath(args.work_dir)
    chunks_dir = os.path.join(work, "chunks")
    merged = {}
    problems = 0
    chunks = 0

    for p in sorted(glob.glob(os.path.join(chunks_dir, "chunk_*.ja.txt"))):
        m = re.search(r"chunk_(\d+)\.ja\.txt$", p)
        if not m:
            continue
        num = int(m.group(1))
        keys, vals = plain_io.load_pair(chunks_dir, num)
        if keys is None:
            if os.path.exists(plain_io.ja_path(chunks_dir, num)):
                print("chunk_%02d: zh.txt missing (not translated)" % num)
            continue
        chunks += 1
        issues, ok = qc_pair(keys, vals, num)
        if not ok:
            problems += 1
        for k, v in zip(keys, vals):
            merged[k] = v
        tag = "OK" if ok else "ISSUES"
        print("chunk_%02d: %d keys  [%s]%s"
              % (num, len(keys), tag,
                 ": " + "; ".join(issues) if issues else ""))

    with open(os.path.join(work, args.out), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    print("merged: %d keys (%d chunks) -> %s" % (len(merged), chunks, args.out))
    if problems:
        print("WARN: %d/%d chunks have issues (see above)" % (problems, chunks))
        if args.strict:
            sys.exit(1)


if __name__ == "__main__":
    main()
