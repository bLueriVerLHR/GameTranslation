#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_csv_shards.py - Split the ExternMessage.csv body template
(csv_template.json) into small translation chunks for dedicated subagents.

Companion to build_csv_template.py. Chunk keys are full CSV bodies (Japanese);
chunks are bucketed by total key char length (--max-chars), preserving CSV
row order. Each chunk gets a context.md with the ExternMessage-specific rules:

  - keep \\M[ID] references verbatim (IDs must stay Japanese)
  - :name[名前,顔] -> translate 名前 only, keep the face-set token
  - keep :bg / :layout / :face commands, keep the \\n line structure

Usage:
    python gen_csv_shards.py <work_dir> [--max-chars 5000] [--start N] [--resume]
"""
import argparse
import glob
import json
import os

CSV_MD = """# Translation chunk {num} - ExternMessage.csv bodies (part {part})

Translate every key in chunk_{num}.json from Japanese to Simplified Chinese.
Write the result to chunk_{num}.translated.json as {{ key: value }}.

Each key is ONE whole dialogue-scene body from the game's ExternMessage.csv
(the game engine replaces \\\\M[ID] in events with these bodies, then renders
:name[...] as the speaker name window). Translate the whole scene as one
coherent piece.

## Hard rules
- OUTPUT KEYS MUST BE BYTE-IDENTICAL TO INPUT KEYS. Never trim, reorder or
  "clean up" a key (control codes, \\n and full-width spaces are meaningful).
- \\\\M[ID] references: keep the ID inside the brackets BYTE-IDENTICAL
  (Japanese). Translate the plain text around them.
- :name[名前,顔セット]: translate 名前 (the speaker name) per the glossary;
  KEEP the second token (e.g. Actor1) byte-identical. For :name[\\,Actor1]
  (narrative/narration window) keep the backslash as-is.
- :bg[dim] / :layout[center] / :face[...] and any other :xxx[...] commands:
  keep byte-identical.
- Keep the same number of \\n lines in the value as in the key (each line is
  one message-window line; pad short translations with "" lines).
- Keep \\u3000 full-width-space indentation and \\C[xx]\\C[0] color pairs.
- Never translate inside \\M[...] brackets, if(s[..]) expressions or
  script/:script blocks.
- Names must follow the glossary below EXACTLY (characters, places, shops).

## Tone (from the game owner)
- Faithful to the original (忠于原文), do not invent or censor.
- Match the game's own mood: comedy scenes keep the humor and comedic pacing;
  story/reveal scenes keep suspense, do NOT spoil foreshadowing or twists.
- Adult-content scenes: keep the content faithful and word it the way a
  native Chinese speaker would - colloquial, natural. Avoid stiff
  Japanese-style phrasing.
- Length: keep the meaning; shorten only if a line would clearly overflow the
  message window (4 lines max per window, 2 windows per page).

## Glossary (mandatory)
{glossary}

## Terminology (mandatory)
{terms}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_dir")
    ap.add_argument("--max-chars", type=int, default=5000)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out-dir", default="chunks",
                    help="chunk subdirectory (default: chunks)")
    args = ap.parse_args()

    work = os.path.abspath(args.work_dir)
    tpl = json.load(open(os.path.join(work, "csv_template.json"),
                         encoding="utf-8"))
    glossary = json.load(open(os.path.join(work, "glossary.json"),
                              encoding="utf-8"))
    try:
        terms = json.load(open(os.path.join(work, "terms.json"),
                               encoding="utf-8"))
    except FileNotFoundError:
        terms = {}
    gtxt = "\n".join("  %s -> %s" % (k, v) for k, v in glossary.items())
    ttxt = "\n".join("  %s -> %s" % (k, v) for k, v in terms.items())

    chunks_dir = os.path.join(work, args.out_dir)
    os.makedirs(chunks_dir, exist_ok=True)

    if args.resume:
        done = set()
        for p in glob.glob(os.path.join(chunks_dir, "*.translated.json")):
            raw = open(p, "rb").read()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            done.update(json.loads(raw.decode("utf-8")))
        tpl = {k: v for k, v in tpl.items() if k not in done}
        print("resume: %d keys already translated, %d remaining"
              % (len(done), len(tpl)))

    keys = list(tpl.keys())
    buckets, cur, cur_len = [], [], 0
    for k in keys:
        if cur and cur_len + len(k) > args.max_chars:
            buckets.append(cur)
            cur, cur_len = [], 0
        cur.append(k)
        cur_len += len(k)
    if cur:
        buckets.append(cur)

    num = args.start
    part = 0
    for b in buckets:
        base = os.path.join(chunks_dir, "chunk_%02d" % num)
        chunk = {k: "" for k in b}
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=1)
        md = CSV_MD.format(num="%02d" % num, part=part, glossary=gtxt,
                           terms=ttxt)
        with open(base + ".context.md", "w", encoding="utf-8") as f:
            f.write(md)
        print("chunk %02d: %d keys, %d chars" % (num, len(b),
                                                 sum(len(k) for k in b)))
        num += 1
        part += 1
    print("wrote %d chunks (%02d..%02d)" % (len(buckets), args.start, num - 1))


if __name__ == "__main__":
    main()
