#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_translation_to_patch.py - Inject a translated.json ({ja: zh})
dictionary into rewolf-trans patch txt files.

rewolf-trans patch format:
    > BEGIN STRING
    <original lines>
    > CONTEXT [NEW] <loc>
    > CONTEXT [NEW] <loc>
    <translated lines>          <- inserted here (after CONTEXT, before END)
    > END STRING

The translated block is the non-instruction lines between the last CONTEXT
and END STRING.  Original lines stay untouched (rewolf-trans uses the
context location for matching, not the original text).

Usage:
    python tools/apply_translation_to_patch.py <patch_dir> <translated.json>
"""
import argparse
import glob
import json
import os

BEGIN = "> BEGIN STRING"
END = "> END STRING"
CTX = "> CONTEXT"


def inject(path, t, stats):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Normalize line endings; patch files may use \r\n.
    crlf = "\r\n" in text
    lines = text.splitlines()
    out = []
    i = 0
    changed = False
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == BEGIN:
            # scan block: original lines, then CONTEXT lines, then
            # (possibly existing) translated lines, then END STRING.
            j = i + 1
            original = []
            contexts = []
            translated = []
            state = "original"
            while j < n and lines[j].strip() != END:
                s = lines[j].strip()
                if s.startswith(CTX):
                    state = "context"
                    contexts.append(lines[j])
                elif state == "context" and not lines[j].strip():
                    pass  # blank separator between CONTEXT and translation
                elif state == "context":
                    state = "translated"
                    translated.append(lines[j])
                elif state == "translated":
                    translated.append(lines[j])
                else:
                    original.append(lines[j])
                j += 1
            if j >= n:
                out.extend(lines[i:])
                break
            key = "\n".join(original)
            # translated.json keys carry the trailing newline that the
            # multi-line message ends with; the patch stores one line per
            # message segment without it.
            key_nl = key + "\n"
            val = t.get(key_nl)
            if val is None:
                val = t.get(key)
            if val is not None and val != key:
                out.append(lines[i])
                out.extend(original)
                out.extend(contexts)
                out.append("")
                out.extend(val.split("\n"))
                out.append(lines[j])  # END STRING
                changed = True
                stats["applied"] += 1
                i = j + 1
                continue
            # no translation: keep the block verbatim
            out.extend(lines[i : j + 1])
            i = j + 1
            continue
        out.append(line)
        i += 1
    if changed:
        sep = "\r\n" if crlf else "\n"
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(sep.join(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("patch_dir", help="directory containing rewt-patch/")
    ap.add_argument("translated_json")
    args = ap.parse_args()

    t = json.load(open(args.translated_json, encoding="utf-8"))
    stats = {"applied": 0, "files": 0}
    root = os.path.join(args.patch_dir, "rewt-patch")
    for path in sorted(glob.glob(os.path.join(root, "**", "*.txt"), recursive=True)):
        if path.endswith("_Danger.txt") or path.endswith("_Extra.txt"):
            continue
        before = stats["applied"]
        inject(path, t, stats)
        if stats["applied"] > before:
            stats["files"] += 1
    print("applied %d strings across %d files" % (stats["applied"], stats["files"]))


if __name__ == "__main__":
    main()
