#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qc_translation_chunks.py - LEGACY (JSON-chunk QC, superseded by the
two-file chunk layout + tools/merge_plain_chunks.py).  Kept for old work
packages.

QC + repair + merge for subagent-translated chunks.

- repair: agents write raw `\C[27]` (single backslash) and unescaped `"`
  inside strings -> fix invalid escapes line-by-line (only on the VALUE side,
  after the first '"' following ': '), then re-parse.
- validate: every input key present exactly, no extras, no empty values,
  same \\n line count, no kana left in values.
- merge: completion.json {key: value} + report.
"""
import argparse
import json
import os
import re

KANA = re.compile(r"[\u3040-\u30ff\uff65-\uff9f]")
VALUE_KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")
CTRL_TOK = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?")
VALID_ESC = re.compile(r"\\([^\"\\/bfnrtu])", re.S)
UNCERTAIN = re.compile(r"【[^】]*\?[^】]*】")
# \RB[a,b] ruby/annotation: parameter COUNT matters, content may legitimately
# be translated (e.g. \RB[悪霊,レイス] -> \RB[恶灵,幽灵]) - never flag a diff.
CTRL_NORM = re.compile(r"\\[A-Za-z]+\[([^\]]*)\]")


def ctrl_signature(s):
    """Control-code sequence as a comparable signature: the ordered list of
    (token-name, arg-count) tuples. Translated args inside \\RB[] / \\C[..]
    style codes don't produce false diffs; only the code structure matters."""
    return [("%s" % m.group(0)[1:m.group(0).find("[")],
             m.group(1).count(",") + 1)
            for m in CTRL_NORM.finditer(s)]


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


def validate(src, out):
    issues = []
    miss = [k for k in src if k not in out]
    extra = [k for k in out if k not in src]
    empty = [k for k in out if not out[k]]
    newline_diff = []
    kana_left = []
    order_diff = []
    ctrl_diff = []
    dbl_backslash = []
    uncertain = []
    for k, v in out.items():
        if k in src and isinstance(v, str):
            if v.count("\n") != k.count("\n"):
                newline_diff.append(k)
            if VALUE_KANA.search(CTRL_TOK.sub("", v)):
                kana_left.append(k)
            if sorted(CTRL_TOK.findall(k)) != sorted(CTRL_TOK.findall(v)) and \
                    sorted(ctrl_signature(k)) != sorted(ctrl_signature(v)):
                ctrl_diff.append(k)
            if "\\\\" in v:
                dbl_backslash.append(k)
            if UNCERTAIN.search(v):
                uncertain.append(k)
    if list(src.keys()) != list(out.keys()):
        order_diff = [k for k in src if k not in out] or \
            [k for k in out if k not in src]
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
        issues.append("KEY ORDER MISMATCH: %s" % order_diff[:3])
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
        issues = []
        out = patch_altered_keys(src, out, issues)
        issues = validate(src, out)
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

