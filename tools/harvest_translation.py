#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harvest_translation.py - Harvest a runtime MTool/AI translation dict into the
extracted template (build_translation.py) so it can be baked statically.

MTool runtime dicts key on DISPLAYED text: control codes are stripped, the
inline speaker-name line (line 1 of a message block) is dropped, notes are
keyed from "<SG説明:" onward, and messages broken by line-wrap appear as
per-line fragments.  That layout is incompatible with the per-line static
data, but the VALUES are exactly what the game owner already approved, so we
re-join them into template keys with an exact-match harvest:

   for each template key, in order:
     1. exact match in the dict
     2. control codes stripped, match
     3. blocks: drop the speaker-name first line, match the rest
        (a first line is a speaker name ONLY when it is short pure
        kana/kanji + optional honorific after stripping codes — dialogue
        lines without corner brackets are never dropped as names)
     4. blocks: match each body line as a fragment, join the values
     5. event-text keys wrapped in double quotes: match the inner text
     6. notes: match from the first "<SG説明" tag onward

Keys with no match are written to <work_dir>/missing.json for AI translation.

Usage:
    python harvest_translation.py <work_dir> <mtool_dict.json> --out translated.json
"""
import argparse
import json
import logging
import os
import re
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
log = logging.getLogger("harvest")

# Multi-letter control codes too: \FX[F]\FFFFF[1000Kenji_0004] must strip
# fully, not just \F + residue (the block-prefix class).
CODE_RE = re.compile(r"\\[A-Za-z]+(\[[^\]]*\])?")


def strip_codes(s):
    return CODE_RE.sub("", s).strip()


def leading_codes(s):
    m = re.match(r"^((?:\\[A-Za-z]+\[[^\]]*\])+)", s)
    return m.group(1) if m else ""


def trailing_codes(s):
    m = re.search(r"((?:\\[A-Za-z]+\[[^\]]*\])+)$", s)
    return m.group(1) if m else ""


# A real speaker-name first line: pure kana/kanji (optional honorific suffix),
# no corner brackets, no punctuation, no control codes (codes stripped first:
# \C[3]<name> is still a name), short.  Anything else — dialogue without 「」,
# FX/code-prefixed dialogue — is BODY text: treating it as a dropped "name"
# leaves the first dialogue line untranslated inside the prefilled block value
# (MZ job 2026-08: 2,187 partial blocks; fix = drop those block keys so the
# per-line fragment path / missing keys cover every line).
NAME_LINE = re.compile(r"^(?:[\u3040-\u30ff\u4e00-\u9fff]|・)+"
                       r"[さんちゃん君様先生嬢ぽ]?$")


def is_name_line(line):
    if not line or "\u300c" in line or "\u300d" in line:
        return False
    stripped = strip_codes(line).strip()
    return bool(stripped) and len(stripped) <= 14 \
        and NAME_LINE.match(stripped) is not None


def split_block(k):
    lines = k.split("\n")
    if len(lines) > 1 and is_name_line(lines[0]):
        return lines[0], lines[1:]
    return None, lines


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_dir")
    ap.add_argument("dict_path", help="MTool/AI runtime translation JSON")
    ap.add_argument("--out", default="translated.json",
                    help="output harvested translation JSON")
    args = ap.parse_args()

    work = os.path.abspath(args.work_dir)
    t = json.load(open(os.path.join(work, "template.json"), encoding="utf-8-sig"))
    kinds = json.load(open(os.path.join(work, "kinds.json"), encoding="utf-8-sig"))
    d = json.load(open(args.dict_path, encoding="utf-8"))
    log.info("template %d keys, dict %d entries", len(t), len(d))

    snorm = {}
    for k, v in d.items():
        snorm.setdefault(strip_codes(k), v)

    def lookup(s):
        v = d.get(s)
        if isinstance(v, str) and v:
            return v
        v = snorm.get(strip_codes(s))
        if isinstance(v, str) and v:
            return v
        return None

    def rebuild_name(name_line):
        name = strip_codes(name_line)
        v = lookup(name)
        if v and name in d or (v and not any(c.isalpha() and ord(c) < 128 for c in name)):
            return name_line.replace(name, v) if name in name_line else name_line
        return name_line

    translated = {}
    missing = {}
    stats = {"exact": 0, "strip": 0, "drop-name": 0, "fragment": 0,
             "quoted": 0, "note": 0, "miss": 0}

    for k, _ in t.items():
        kd = kinds.get(k, "?")
        val = None
        how = None

        v = d.get(k)
        if isinstance(v, str) and v:
            val, how = v, "exact"
        else:
            sv = snorm.get(strip_codes(k))
            if isinstance(sv, str) and sv and "\n" not in k:
                pre, suf = leading_codes(k), trailing_codes(k)
                val, how = pre + sv + suf, "strip"
            elif isinstance(sv, str) and sv:
                val, how = sv, "strip"
            elif "\n" in k:
                name_line, body = split_block(k)
                rest = "\n".join(body)
                rv = snorm.get(strip_codes(rest))
                if isinstance(rv, str) and rv:
                    if name_line is not None:
                        val = rebuild_name(name_line) + "\n" + rv
                        how = "drop-name"
                    else:
                        val, how = rv, "strip"
                else:
                    body_s = [strip_codes(l) for l in body if l.strip()]
                    if body_s and all(b in snorm and snorm[b] for b in body_s):
                        lines = [rebuild_name(name_line)] if name_line is not None else []
                        lines += [snorm[b] for b in body_s]
                        val, how = "\n".join(lines), "fragment"
        if val is None and kd == "event-text" and len(k) >= 2 and k.startswith('"') and k.endswith('"'):
            inner = k[1:-1]
            iv = snorm.get(strip_codes(inner))
            if isinstance(iv, str) and iv:
                val, how = '"' + iv + '"', "quoted"
        if val is None and kd == "note":
            i = k.find("<SG説明")
            if i >= 0:
                nv = snorm.get(strip_codes(k[i:]))
                if isinstance(nv, str) and nv:
                    pre = leading_codes(k[:i])
                    val, how = pre + k[:i] + nv, "note"
        if val is None:
            missing[k] = ""
            stats["miss"] += 1
        else:
            translated[k] = val
            stats[how] += 1

    out = os.path.join(work, args.out)
    json.dump(translated, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(missing, open(os.path.join(work, "missing.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    log.info("harvested %d / %d keys: %s", len(translated), len(t), stats)
    log.info("missing %d -> %s", len(missing),
             os.path.join(work, "missing.json"))


if __name__ == "__main__":
    main()
