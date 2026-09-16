#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KiriKiri scenario (.ks) parsing helpers shared by the translation tools.

Encoding detection, bracket-paired tag splitting and translatability checks.
All tag/attribute handling here is conservative: anything ambiguous is
treated as untranslatable so a broken key can never corrupt a jump target
or a control code.
"""

import logging
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import japanese_utils  # noqa: E402

log = logging.getLogger("kirikiri.ks_extract")

# Kana (incl. half-width katakana) marks Japanese text.  CJK kanji alone is
# not enough (Chinese shares the block), so residuals are checked with KANA.
KANA = japanese_utils.KANA
JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
TEXT_ATTR = re.compile(r'\btext\s*=\s*"([^"]*)"')
STORAGE_ATTR = re.compile(r'\bstorage\s*=\s*"([^"]+)"')
# Display text also lives in attributes whose name is not `text`.  Game macros
# carry their visible strings in their own parameter names: measured on one
# KAG3 title, [NAME_M n="..."] speaker names (91 still-Japanese occurrences),
# [SELECT_CENTER text="..." sel_1="..."] prompts and choice labels, [title
# name="..."].  Only the literal text="..." used to count, so those lines were
# never extracted and the shipped build showed Japanese choice labels.
# Every attribute can hold display text EXCEPT code-carrying ones: their values
# are expressions, and translating a string literal inside one would break the
# comparison (e.g. [if exp="f.name=='ゆき'"]).
ATTR = re.compile(r'([A-Za-z_][\w.-]*)\s*=\s*"([^"]*)"')
CODE_ATTRS = frozenset({"exp", "js", "script", "eval", "condition"})
# Reference attributes: KAG3 scenario files and labels legitimately carry
# Japanese names (storage="シナリオ.ks", tag_1="*選択"), and a label is a jump
# target - translating one breaks the jump.  Never treat these as display text.
FUNCTIONAL_ATTRS = frozenset({"storage", "target", "file", "tag", "path",
                              "folder", "url", "src", "name_id", "id"})
FUNCTIONAL_PREFIXES = ("file_", "tag_")

# --- code vs. display text --------------------------------------------------
# TyranoScript exposes game state through identifiers that may legally be
# Japanese: `f.ライブファン表示`, `&f.アイテム名[0]`, `sf.Clear_Flag`,
# `mp.name`.  Those are references, not text - translating one breaks every
# line that mentions it.  Raw TJS/JS also lives inside
# [iscript]/[tb_start_tyrano_code] blocks ([eval] is a single-line tag, not a
# block).  A kana check that ignores this reports ~10% "residual" on a fully
# translated build, almost all of it identifiers.
VAR_REF = re.compile(
    r"&(?:f|sf|tf|mp)\.[A-Za-z0-9_\u3040-\u30ff\u4e00-\u9fff]+"
    r"(?:\[[^\]]*\])?")
CODE_STMT = re.compile(
    r"^\s*(?:if|else|for|while|switch|case|var|let|const|function|return|"
    r"break|continue|console|delete|new|try|catch|finally|throw|do)\b"
    r"|^\s*(?:sf|f|tf|mp)\.[^\s=]*\s*=[^=]"
    r"|^\s*[}{]")
# KAG3 also has a bracketless short-tag dialect that writes the very same
# tags as `@iscript` / `@endscript` (alongside `@cg file=..`, `@playbgm ..`).
# Measured on one KAG3 title: 1556 lines sit inside such blocks and 429 of
# them carry Japanese (plugin comments, inline remarks, Japanese identifiers).
# Recognising only the bracketed form fed that raw TJS straight into the
# translation template while the QC - which shares this helper - scanned the
# same code for "residual kana", i.e. both ends were wrong in opposite
# directions.  Only 17 Japanese string literals live inside those blocks for
# the same title (15 developer warnings from two plugins plus 2 volume-menu
# labels), so dropping whole blocks loses no dialogue.
CODE_BLOCK_OPEN = re.compile(r"(?:\[|@)(?:iscript|script|tb_start_tyrano_code)\b")
CODE_BLOCK_CLOSE = re.compile(r"(?:\[|@)(?:endscript|_tb_end_tyrano_code)\b")


def iter_candidate_lines(text, where=None):
    """Yield (line_number, line) for every line a translator could own.

    Shared by the extractor and the QC so both agree on what counts as text:
    raw TJS/JS blocks (`[iscript]`/`@iscript` .. `[endscript]`/`@endscript`),
    `;` comment lines and `*` label lines are dropped.  Line numbers are
    1-based and match the source file, which is what the write-back step
    keys on, so a dropped line is never renumbered.
    """
    in_code = False
    for idx, raw in enumerate(text.split("\n"), start=1):
        s = raw.strip()
        if in_code:
            if CODE_BLOCK_CLOSE.search(s):
                in_code = False
            continue
        # A `;` line is a comment: it cannot open a code block even when it
        # documents one (`;[iscript]`).  Checked before the opener so a
        # commented-out tag can never swallow the rest of the file.
        if not s or s.startswith("*") or s.startswith(";"):
            continue
        if CODE_BLOCK_OPEN.search(s):
            # `[iscript] ... [endscript]` on one line opens and closes at once.
            in_code = not CODE_BLOCK_CLOSE.search(s)
            continue
        yield idx, raw
    if in_code:
        log.warning("%s: unterminated code block (opened by [iscript] or "
                    "@iscript); every line after the opener was skipped - "
                    "check the file for an unclosed script block",
                    where or "<text>")


def iter_display_lines(text, where=None):
    """Yield (line_number, line) for every line that may carry display text.

    Skips comments, `*` label lines, raw TJS/JS code blocks and code
    statements, and strips variable references (`&f.name`) from what is
    yielded.  A kana check built on this sees only text a translator is
    allowed to touch, so identifiers never show up as false "residuals".
    """
    for idx, raw in iter_candidate_lines(text, where):
        if CODE_STMT.match(raw.strip()):
            continue
        yield idx, VAR_REF.sub("", raw)


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
    """Values of the display-text attributes inside tags.

    Any attribute except the code-carrying ones (``exp``/``js``/``script`` …):
    a game macro's own parameter names are where its visible strings live, so
    restricting this to ``text="..."`` silently skipped every custom macro
    (speaker names, choice labels, window captions) and those lines were never
    translated.
    """
    out = []
    for kind, value in segments:
        if kind == "tag":
            for name, val in ATTR.findall(value):
                low = name.lower()
                if low in CODE_ATTRS or low in FUNCTIONAL_ATTRS:
                    continue
                if low.startswith(FUNCTIONAL_PREFIXES):
                    continue
                out.append(val)
    return out


def display_text(line):
    """Readable display text for context windows: body plus display-attribute
    values, tags stripped."""
    segments, balanced = split_line(line)
    parts = [body_text(segments).strip()]
    parts += [a.strip() for a in tag_text_attrs(segments)]
    return " | ".join(p for p in parts if p), balanced


def translatable(line):
    """True when the line carries display text to translate: JA text in the
    body or in a display attribute, and all brackets closed."""
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
