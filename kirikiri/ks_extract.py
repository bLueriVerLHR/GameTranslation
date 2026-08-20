#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KiriKiri scenario (.ks) parsing helpers shared by the translation tools.

Encoding detection, bracket-paired tag splitting and translatability checks.
All tag/attribute handling here is conservative: anything ambiguous is
treated as untranslatable so a broken key can never corrupt a jump target
or a control code.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import japanese_utils  # noqa: E402

# Kana (incl. half-width katakana) marks Japanese text.  CJK kanji alone is
# not enough (Chinese shares the block), so residuals are checked with KANA.
KANA = japanese_utils.KANA
JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
TEXT_ATTR = re.compile(r'\btext\s*=\s*"([^"]*)"')
STORAGE_ATTR = re.compile(r'\bstorage\s*=\s*"([^"]+)"')


def detect_encoding(raw):
    """Detect the byte encoding of a .ks file (UTF-16 LE/BE, UTF-8, Shift-JIS)."""
    if not raw:
        return "utf-8"
    if raw[:2] == b"\xff\xfe":
        return "utf-16"
    if raw[:2] == b"\xfe\xff":
        return "utf-16-be"
    nulls = raw.count(b"\x00")
    if nulls > len(raw) // 8:
        even = raw[0::2].count(b"\x00")
        odd = raw[1::2].count(b"\x00")
        return "utf-16-be" if odd > even else "utf-16"
    for enc in ("utf-8", "shift_jis", "cp932"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "cp932"


def load_ks(path):
    """Read a .ks file; returns (text, encoding_name)."""
    with open(path, "rb") as f:
        raw = f.read()
    enc = detect_encoding(raw)
    text = raw.decode(enc)
    if text.startswith("\ufeff"):
        text = text[1:]
    return text, enc


def split_line(line):
    """Split a .ks line into (kind, value) segments.

    kind is "tag" for a [..] span (nested brackets and quoted attribute
    values are handled) and "text" for everything else.  Returns
    (segments, balanced) where balanced is False when a bracket never
    closes - such lines are never translated.
    """
    segments = []
    buf = []
    depth = 0
    i, n = 0, len(line)
    while i < n:
        if line[i] == "[":
            if buf:
                segments.append(("text", "".join(buf)))
                buf = []
            depth, quoted, j = 1, False, i + 1
            while j < n and depth:
                c = line[j]
                if c == '"':
                    quoted = not quoted
                elif c == "[" and not quoted:
                    depth += 1
                elif c == "]" and not quoted:
                    depth -= 1
                j += 1
            segments.append(("tag", line[i:j]))
            i = j
        else:
            buf.append(line[i])
            i += 1
    if buf:
        segments.append(("text", "".join(buf)))
    return segments, depth == 0


def body_text(segments):
    """Display text outside of any tag."""
    return "".join(v for kind, v in segments if kind == "text")


def tag_text_attrs(segments):
    """Values of every text="..." attribute inside tags."""
    out = []
    for kind, value in segments:
        if kind == "tag":
            out.extend(TEXT_ATTR.findall(value))
    return out


def display_text(line):
    """Readable display text for context windows: body plus text="..."
    attribute values, tags stripped."""
    segments, balanced = split_line(line)
    parts = [body_text(segments).strip()]
    parts += [a.strip() for a in tag_text_attrs(segments)]
    return " | ".join(p for p in parts if p), balanced


def translatable(line):
    """True when the line carries display text to translate: JA text in the
    body or in a text="..." attribute, and all brackets closed."""
    segments, balanced = split_line(line)
    return balanced and translatable_segments(segments)


def translatable_segments(segments):
    if JA.search(body_text(segments)):
        return True
    return any(JA.search(t) for t in tag_text_attrs(segments))


def scenario_storage_refs(text):
    """Ordered [call]/[jump] scenario-file references (only these tags use
    storage for scenario files - @bg etc. also carry a storage attribute
    but point at assets) and whether [next] appears."""
    refs = []
    for m in re.finditer(r"\[(?:call|jump)\b([^\]]*)\]", text):
        sm = STORAGE_ATTR.search(m.group(1))
        if sm:
            refs.append(sm.group(1))
    return refs, bool(re.search(r"\[next\]", text))
