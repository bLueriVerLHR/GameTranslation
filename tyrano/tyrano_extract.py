#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TyranoScript / TyranoBuilder scenario (.ks) parsing helpers.

TyranoBuilder compiles each game screen into a .ks file whose display text
lives inside [tb_start_text mode=N] ... [_tb_end_text] blocks.  A block may
carry a speaker line ("#Name"), then text lines; each text line mixes
TyranoScript tags ([font color=...], [l], [r], [p] ...) with the Japanese
fragments that are the translation targets.  Text also appears in
text="..." attributes of glink / tb_ptext_show / p_notify /
tb_alert_dialog tags.

All parsing here is conservative: lines that are comments (";"), speaker
name alone ("#Name" handled by the caller), pure-tag lines with no Japanese
and lines with unbalanced brackets are never treated as translatable.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import japanese_utils  # noqa: E402

KANA = japanese_utils.KANA
JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
TEXT_ATTR = re.compile(r'\btext\s*=\s*"([^"]*)"')

TB_BLOCK_OPEN = re.compile(r"^\s*\[tb_start_text\b[^\]]*\]\s*$")
TB_BLOCK_CLOSE = re.compile(r"^\s*\[_tb_end_text\]\s*$")
SPEAKER = re.compile(r"^#(\S.*)$")

# Tags whose text="..." attribute is display text to translate.
TEXT_ATTR_TAGS = ("glink", "tb_ptext_show", "p_notify", "tb_alert_dialog",
                  "tb_dialog")


def detect_encoding(raw):
    """Detect the byte encoding of a .ks file (TyranoBuilder outputs UTF-8,
    but keep the shared heuristic for robustness)."""
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


def split_tag_attrs(tag):
    """Split the attribute block of a [tag ...] span (or a bare tag body)
    into (name, value) pairs.

    Attribute names keep their original case; values are unquoted (double
    or single quotes).  Malformed spans degrade to name-only pairs.
    """
    body = tag.strip()
    if body.startswith("["):
        body = body[1:]
    if body.endswith("]"):
        body = body[:-1]
    parts = re.findall(r'([a-zA-Z_][\w]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))',
                       body)
    return [(n, v1 or v2 or v3) for n, v1, v2, v3 in parts]


def tag_name(tag):
    """Return the tag name of a [..] span ("" when not a tag)."""
    body = tag.strip()
    if not (body.startswith("[") and body.endswith("]")):
        return ""
    m = re.match(r"\[\s*([a-zA-Z_][\w]*)", body)
    return m.group(1) if m else ""


def block_text_lines(text):
    """Yield the translatable lines inside every
    [tb_start_text]..[_tb_end_text] block, each as (raw_line, kind).

    kind is "speaker" for a #Name speaker line, "text" for a display text
    line.  Comments, blank lines, empty speaker lines and tag-only lines
    are skipped entirely.
    """
    inside = False
    for raw in text.splitlines():
        if TB_BLOCK_OPEN.match(raw):
            inside = True
            continue
        if TB_BLOCK_CLOSE.match(raw):
            inside = False
            continue
        if not inside:
            continue
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        m = SPEAKER.match(line)
        if m:
            yield raw, "speaker"
            continue
        if line == "#":
            continue
        yield raw, "text"


def text_attr_lines(text):
    """Yield (raw_line, attr_value) for display-text text="..." attributes
    on glink / tb_ptext_show / p_notify / tb_alert_dialog / tb_dialog."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("[") or not line.endswith("]"):
            continue
        name = tag_name(line)
        if name not in TEXT_ATTR_TAGS:
            continue
        for attr, val in split_tag_attrs(line):
            if attr == "text" and val:
                yield raw, val


def translatable(line):
    """True when a line carries Japanese display text to translate:
    speaker line or JA in body / text="..." attribute, brackets balanced."""
    if SPEAKER.match(line.strip()):
        return True
    depth = 0
    quoted = False
    for c in line:
        if c == '"':
            quoted = not quoted
        elif c == "[" and not quoted:
            depth += 1
        elif c == "]" and not quoted:
            depth -= 1
    if depth != 0:
        return False
    if JA.search(line):
        return True
    return any(JA.search(v) for _a, v in split_tag_attrs(line))


def display_text(line):
    """Readable display text for context windows: speaker names and
    text="..." attribute values shown, other tags stripped."""
    m = SPEAKER.match(line.strip())
    if m:
        return m.group(1).strip()
    parts = [v.strip() for n, v in split_tag_attrs(line)
             if n == "text" and v.strip()]
    body = re.sub(r"\[[^\]]*\]", "", line).strip()
    if body:
        parts.insert(0, body)
    return " | ".join(parts)


def scenario_storage_refs(text):
    """Ordered [call]/[jump] scenario-file references (used for story-order
    tracing).  Returns (refs, has_next)."""
    refs = []
    for m in re.finditer(r"\[(?:call|jump)\b([^\]]*)\]", text):
        attrs = dict(split_tag_attrs(m.group(1)))
        if attrs.get("storage"):
            refs.append(attrs["storage"])
    return refs, bool(re.search(r"\[next\]", text))
