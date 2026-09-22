#!/usr/bin/env python3
"""prefill.py - harvest a runtime MTool/AI dictionary into the v2 library.

Repacked MZ/MV builds usually ship a translation dictionary the repacker's tool
applied at runtime (``<title>.json``, ``AI翻译.json``, ``…翻译文件.json``…).
The values are what the game owner already saw and approved, but the *keys* are
runtime-shaped: control codes stripped, whole messages joined with ``\\n``, plus
fragment entries for substrings.  Baking such a dictionary directly is what the
guide forbids - a greedy fragment pass destroys sentences.

The v2 key list is per displayed string (one 401 command at a time), so a
runtime dictionary can seed it safely by *exact* lookup:

1. the key text as-is;
2. control codes stripped, re-wrapping the value in the source's leading and
   trailing codes (only when the codes sit at the ends - a code in the middle
   of the line is left for the translator);
3. nothing else.  No substring/progressively-shorter matching: that is the
   failure mode the exact-match rule exists to prevent.

Everything produced here still goes through ``translation.cli append`` - the
single write path - so a candidate that breaks the control-code, kana, line
break or JSON-structure gate is rejected before it reaches the library.
Candidates that would fail are filtered out here and reported instead, so a
25,000-entry harvest does not fail as one all-or-nothing batch.
"""
import json
import logging
import os
import re
from collections import Counter

from . import mvkeys, rawlib

log = logging.getLogger(__name__)

__all__ = ["load_runtime_dict", "harvest", "write_batch"]

#: MTool writes its dictionaries as JSON with ``//`` comments - not JSON.
_COMMENT_RE = re.compile(r"^\s*//.*$", re.M)


def load_runtime_dict(path):
    """Read a runtime translation dictionary (tolerates ``//`` comment lines).

    The file is UTF-8 with or without a BOM.  A dictionary that is not a flat
    ``{source: translation}`` object is a hard error: silently reading half of
    it would look like "the dictionary only covered half the game".
    """
    with open(path, encoding="utf-8-sig") as handle:
        text = handle.read()
    text = _COMMENT_RE.sub("", text)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object of {{source: translation}}")
    return {key: value for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str) and value}


def _split_ends(text):
    """``(leading codes, inner text, trailing codes)`` of `text`.

    ``split_keep_codes`` also emits empty text pieces (a leading and a trailing
    one); they are dropped here so "is this piece a code" decides the split.
    """
    pieces = [(is_code, piece)
              for is_code, piece in rawlib.split_keep_codes(text) if piece]
    lead, index = [], 0
    while index < len(pieces) and pieces[index][0]:
        lead.append(pieces[index][1])
        index += 1
    trail, end = [], len(pieces) - 1
    while end >= index and pieces[end][0]:
        trail.append(pieces[end][1])
        end -= 1
    trail.reverse()
    inner = "".join(piece for _, piece in pieces[index:end + 1])
    return "".join(lead), inner, "".join(trail)


def harvest(work_dir, dict_path, allow_ids=None):
    """``(clean candidates, report)`` for the current key list.

    ``allow_ids`` restricts the harvest (used by tests).  The report counts
    every outcome so an operator can see whether a low hit rate is the
    dictionary's fault or the wrapper's.
    """
    entries = mvkeys.load_keys(work_dir)
    runtime = load_runtime_dict(dict_path)
    stripped = {}
    for key, value in runtime.items():
        bare = rawlib.readable_text(key).strip() or key.strip()
        if bare:
            stripped.setdefault(bare, value)

    stats = Counter()
    candidates = {}
    problems = Counter()
    for entry in entries:
        key_id, source = entry["id"], entry["ja"]
        if allow_ids is not None and key_id not in allow_ids:
            continue
        value = runtime.get(source)
        if value:
            stats["exact"] += 1
        else:
            bare = rawlib.readable_text(source).strip() or source.strip()
            value = stripped.get(bare)
            if not value:
                stats["miss"] += 1
                continue
            lead, inner, trail = _split_ends(source)
            if rawlib.parse_codes(inner):
                # Codes in the middle of the line: the dictionary has no codes
                # at all (they are display text), so the only honest thing left
                # is to leave this key to the translator.
                stats["mid-line codes"] += 1
                continue
            if rawlib.parse_codes(value):
                stats["value already coded"] += 1
            else:
                value = lead + value + trail
                stats["stripped"] += 1
        candidates[key_id] = value

    total = sum(stats.values())
    allowed = dict(candidates)
    for key_id, message in rawlib.validate_blocks(work_dir, allowed):
        candidates.pop(key_id, None)
        problems[message.split(":")[0][:60]] += 1
    report = {
        "keys": total,
        "candidates": len(allowed),
        "harvested": len(candidates),
        "rejected": len(allowed) - len(candidates),
        "missed": stats.get("miss", 0) + stats.get("mid-line codes", 0),
        "lookup": dict(sorted(stats.items())),
        "rejected_by": dict(sorted(problems.items())),
    }
    return candidates, report


def write_batch(path, values):
    """Write candidates in the library's own batch format (``@@@id@@@`` + raw)."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for key_id, text in values.items():
            handle.write(f"@@@{key_id}@@@\n{text}\n")
    return path
