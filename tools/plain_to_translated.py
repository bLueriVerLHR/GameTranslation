#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plain_to_translated.py - LEGACY (old ===KEY=== plain format, superseded by
the two-file chunk layout: chunk_NN.ja.txt + chunk_NN.zh.txt + 
tools/merge_plain_chunks.py).  Kept for old work packages.

Convert a plain-text translation file into the chunk_NN.translated.json
the bake step expects.

Why: subagents writing JSON content through the Write tool regularly break on
keys/values that contain raw double quotes or backslash control codes (\\C,
\\{...) - the content itself is JSON and needs escaping. This helper lets the
agent write a PLAIN TEXT file instead (quotes/backslashes need no escaping)
and does the JSON escaping here with json.dump.

Plain text format (chunk_NN.plain.txt):
  One entry per KEY in the SAME ORDER as the keys of chunk_NN.json.
  Entries are separated by a line containing exactly: ===KEY===
  Inside an entry, physical lines = the \\n-separated lines of the message
  (an empty physical line becomes an empty-string pad line).
  The line-count rule still applies: same number of lines as the key.

Usage:
  python plain_to_translated.py <chunk_NN.json> <chunk_NN.plain.txt> <out.json>
"""
import json
import sys

MARK = "===KEY==="


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    src_path, plain_path, out_path = sys.argv[1:4]
    with open(src_path, encoding="utf-8") as f:
        src = json.load(f)
    with open(plain_path, encoding="utf-8") as f:
        text = f.read()
    if text.startswith("\ufeff"):
        text = text[1:]
    if not text.endswith("\n"):
        text += "\n"
    entries = [e.rstrip("\n").split("\n") for e in text.split(MARK + "\n")]
    if entries and entries[0] == [""]:
        entries = entries[1:]
    src_keys = list(src.keys())
    if len(entries) != len(src_keys):
        print("ERROR: %d entries in plain file, %d keys in source"
              % (len(entries), len(src_keys)))
        sys.exit(2)
    out = {}
    for key, lines in zip(src_keys, entries):
        if not any(lines) and False:
            pass
        if len(lines) == 1 and lines[0] == "":
            lines = [""]
        out[key] = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote %d keys -> %s" % (len(out), out_path))


if __name__ == "__main__":
    main()
