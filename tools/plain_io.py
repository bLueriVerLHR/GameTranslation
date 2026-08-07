#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plain_io.py - shared escaping + IO for the two-file chunk format.

chunk_NN.ja.txt / chunk_NN.zh.txt: ONE key (or one translation) PER LINE,
no quotes, no JSON, no ===KEY=== separators.  Line N of zh.txt is the
translation of line N of ja.txt (1:1).

Escaping (identical in both files):
  real newline in the message  -> literal two chars  \n
  literal backslash            -> double backslash   \\
  literal carriage return      -> literal two chars  \r
Everything else stays as-is (full-width spaces \\u3000, kana, kanji,
punctuation).  A key whose control code \\C[27] contains a single backslash
is written \\\\C[27] in the file.

The mapping is unambiguous: `\\` always means one literal backslash and `\\n`
always means a real newline, so a key containing the literal text \\n
(backslash + n) round-trips safely as `\\\\n`.

Agents keep the same escape structure in zh.txt: the same NUMBER of `\\n`
escapes as the key line (message-window line count) and control codes with
the `\\\\` prefix.
"""
import os
import json


def load_json(path):
    """Tolerant JSON load (skips a UTF-8 BOM that Windows tools write)."""
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def escape_line(s):
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return "".join(out)


def unescape_line(s):
    out = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def save_lines(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(escape_line(x) for x in lines) + "\n")


def load_lines(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text.startswith("\ufeff"):
        text = text[1:]
    if not text:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return [unescape_line(x) for x in text.split("\n")] if text else []


def ja_path(chunks_dir, num):
    return os.path.join(chunks_dir, "chunk_%02d.ja.txt" % num)


def zh_path(chunks_dir, num):
    return os.path.join(chunks_dir, "chunk_%02d.zh.txt" % num)


def load_pair(chunks_dir, num):
    """(keys, values) for a chunk; (None, None) when either file is missing."""
    jp, zp = ja_path(chunks_dir, num), zh_path(chunks_dir, num)
    if not os.path.exists(jp) or not os.path.exists(zp):
        return None, None
    return load_lines(jp), load_lines(zp)
