#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Control-code helpers shared by the translation tools (single source).

Control codes are engine escape sequences that must survive translation
byte-for-byte (`\\N[1]`, `\\C[2]`, `\\RB[显示,名]`, Wolf RPG's `:name[..]`).
Extraction, chunk QC and merging all need the same two answers - what codes
does this string carry (`ctrl_signature`) and what text is left once they are
removed (`strip_ctrl`) - so the regexes live here instead of in the five
copies that had already drifted apart.

`CTRL_TOKEN` is the whole escape (the union of the RPG Maker `\\Name[args]`
and Wolf RPG `:name[args]` spellings); `CTRL_ARGS` is the RPG Maker form with
the argument list captured, which is what `ctrl_signature` needs.
"""

import re

CTRL_TOKEN = re.compile(r"\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?")

CTRL_ARGS = re.compile(r"\\[A-Za-z]+\[([^\]]*)\]")


def ctrl_signature(s):
    """Control codes of `s` as a comparable signature.

    The signature is the ordered list of (code-name, argument-count) pairs,
    so a translated argument inside `\\RB[显示,名]` / `\\C[..]` does not show
    up as a diff - only the code structure matters.  Two strings are
    control-code compatible when their signatures are equal.
    """
    return [(m.group(0)[1:m.group(0).find("[")],
             m.group(1).count(",") + 1)
            for m in CTRL_ARGS.finditer(s)]


def strip_ctrl(s):
    """`s` with every control code removed (for kana/residual checks)."""
    return CTRL_TOKEN.sub("", s)
