#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""qc_translation_chunks.py - LEGACY (JSON-chunk QC, superseded by the
two-file chunk layout + tools/merge_plain_chunks.py).  Kept for old work
packages.

QC + repair + merge for subagent-translated chunks.

- repair: agents write raw ``\C[27]`` (single backslash) and unescaped ``"``
  inside strings -> fix invalid escapes line-by-line (only on the VALUE side,
  after the first '"' following ': '), then re-parse.
- validate: every input key present exactly, no extras, no empty values,
  same ``\n`` line count, no kana left in values.
- merge: completion.json {key: value} + report.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctrl_codes  # noqa: E402
import japanese_utils  # noqa: E402

# The canonical KANA (search pattern) is the value check; KANA_BLOCKS_HW was
# the older block-range variant and is no longer used.
VALUE_KANA = japanese_utils.KANA
VALID_ESC = re.compile(r"\\([^\"\\/bfnrtu])", re.S)
UNCERTAIN = re.compile(r"【[^】]*\?[^】]*】")
# \RB[a,b] ruby/annotation: parameter COUNT matters, content may legitimately
# be translated (e.g. \RB[悪霊,レイス] -> \RB[evil spirit,ghost]) - never flag a diff.


ctrl_signature = ctrl_codes.ctrl_signature


def repair_file(path):
    """Repair invalid escapes (whole line, keys AND values) so it parses."""
    raw = open(path, encoding="utf-8").read()
    try:
        json.loads(raw)
        return raw, False
    except json.JSONDecodeError:
        pass
    lines = raw.split("\n")
    out = []
    fixed = 0
    for ln in lines:
        if '\\' in ln:
            nl = VALID_ESC.sub(lambda mm: "\\\\" + mm.group(1), ln)
            if nl != ln:
                fixed += 1
            ln = nl
        out.append(ln)
    return "\n".join(out), fixed


def order_divergence(src, out):
    """Positions where `src` and `out` share a slot but not a key.

    Missing/extra keys are reported separately; this catches the case the old
    check could never see - all keys present but reordered - which matters
    because the ja/zh chunk contract is line-by-line.  Returns (src_key,
    out_key) pairs.
    """
    shared_src = [k for k in src if k in out]
    shared_out = [k for k in out if k in src]
    return [(a, b) for a, b in zip(shared_src, shared_out) if a != b]


def validate(src, out):
    issues = []
    miss = [k for k in src if k not in out]
    extra = [k for k in out if k not in src]
    empty = [k for k in out if not out[k]]
    newline_diff = []
    kana_left = []
    ctrl_diff = []
    dbl_backslash = []
    uncertain = []
    for k, v in out.items():
        # Object keys are strings in practice; the isinstance guard keeps a
        # hand-built dict (tests, future callers) from raising here.
        if k in src and isinstance(k, str) and isinstance(v, str):
            if v.count("\n") != k.count("\n"):
                newline_diff.append(k)
            if VALUE_KANA.search(ctrl_codes.strip_ctrl(v)):
                kana_left.append(k)
            if (sorted(ctrl_codes.CTRL_TOKEN.findall(k))
                    != sorted(ctrl_codes.CTRL_TOKEN.findall(v))
                    and sorted(ctrl_signature(k)) != sorted(ctrl_signature(v))):
                ctrl_diff.append(k)
            if "\\\\" in v:
                dbl_backslash.append(k)
            if UNCERTAIN.search(v):
                uncertain.append(k)
    order_diff = order_divergence(src, out)
    if miss:
        issues.append("missing keys: %s" % miss[:6])
    if extra:
        issues.append("extra keys: %s" % extra[:6])
    if empty:
        issues.append("empty values: %s" % empty[:6])
    if newline_diff:
        issues.append("newline-count mismatch: %d keys" % len(newline_diff))
    if kana_left:
        issues.append("kana still in values: %d keys" % len(kana_left))
    if order_diff:
        issues.append("KEY ORDER MISMATCH: %d positions, first %r -> %r"
                      % (len(order_diff), order_diff[0][0], order_diff[0][1]))
    if ctrl_diff:
        issues.append("control-code tokens differ: %d keys" % len(ctrl_diff))
    if dbl_backslash:
        issues.append("double-backslash values: %d keys" % len(dbl_backslash))
    if uncertain:
        issues.append("uncertainty markers 【?】 left: %d keys" % len(uncertain))
    return issues


def levenshtein(a, b):
    if abs(len(a) - len(b)) > 3:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (ca != cb))
        prev = cur
        if min(prev) > 3:
            return 99
    return prev[-1]


def patch_altered_keys(src, out, issues):
    """For each input key missing from the output, take the value of the
    closest extra key (edit distance <= 3) and rename that key."""
    miss = [k for k in src if k not in out]
    extra = [k for k in out if k not in src]
    patched = []
    # 1) agent escaped a control-code backslash in the KEY: unescape it
    for k in miss:
        for x in extra:
            if x.replace("\\\\", "\\") == k or x.replace("\\", "") == k:
                out[k] = out.pop(x)
                extra.remove(x)
                patched.append((k, x))
                break
    # 2) edit-distance patching
    for k in list(miss):
        if k in out:
            continue
        best, bd = None, 99
        for x in extra:
            d = levenshtein(k, x)
            if d < bd:
                best, bd = x, d
        if best is not None and bd <= 3:
            out[k] = out.pop(best)
            extra.remove(best)
            patched.append((k, best))
    if patched:
        issues.append("patched %d altered keys" % len(patched))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--merge", default="completion.json",
                    help="output merged translation file name")
    args = ap.parse_args()

    work = os.path.abspath(args.work_dir)
    chunks_dir = os.path.join(work, "chunks")
    merged = {}
    report = []

    for path in sorted(os.listdir(chunks_dir)):
        if not path.endswith(".json") or ".translated." not in path:
            continue
        name = path[:-len(".json")]
        src_path = os.path.join(chunks_dir, name.replace(".translated", "") + ".json")
        if not os.path.exists(src_path):
            report.append("%s: SOURCE MISSING" % path)
            continue
        src = json.load(open(src_path, encoding="utf-8"))
        p = os.path.join(chunks_dir, path)
        fixed = 0
        for attempt in range(3):
            text, fixed = repair_file(p)
            if fixed:
                open(p, "w", encoding="utf-8").write(text)
            try:
                out = json.loads(text)
                break
            except json.JSONDecodeError as e:
                if fixed == 0:
                    report.append("%s: REPAIR UNABLE (%s)" % (path, str(e)[:60]))
                    out = None
                    break
        if out is None:
            continue
        patched = []
        out = patch_altered_keys(src, out, patched)
        # The rename report used to be thrown away here (a plain rebinding of
        # `issues`), so a repaired chunk looked clean in the report.
        issues = patched + validate(src, out)
        if issues:
            report.append("%s: %d keys, ISSUES: %s"
                          % (path, len(out), "; ".join(issues)))
        else:
            report.append("%s: OK (%d keys)%s" % (path, len(out),
                                                  " [escapes repaired %d]" % fixed if fixed else ""))
        for k, v in out.items():
            if k in src:
                merged[k] = v

    with open(os.path.join(work, args.merge), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    print("merged:", len(merged), "entries ->", args.merge)
    for r in report:
        print(r)


if __name__ == "__main__":
    main()

