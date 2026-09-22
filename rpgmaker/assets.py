#!/usr/bin/env python3
"""assets.py - where the registered fonts live, and how one is chosen.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).
This module owns exactly one responsibility: resolving the font a translated
build must use.

Resolution order for the CJK (Simplified-Chinese) font:

    1. environment variable ``CJK_FONT_PATH`` / ``JP_FONT_PATH``
    2. the local font-paths override file (a gitignored private file whose
       lines are: CJK first, Japanese fallback second)
    3. the registered font directory (auto-discovered)
    4. None - the caller keeps the game's own font

Machine paths never live in the repo, and the directory comes from the single
mapping in :mod:`rpgmaker.settings`, so moving the private data never means
editing this module again.

Font *policy* (apply it to a self-translated build, preserve an existing
translation's font, ``auto`` only inspects and warns) is a separate concern
and lives with the bake step - this module answers "which file", not "should
it be applied".
"""
import logging
import os
from pathlib import Path

from .settings import private_path

__all__ = [
    "FONTS_DIR",
    "discover_font",
    "find_cjk_font",
    "find_jp_font",
    "read_font_paths",
]

log = logging.getLogger("rpgmaker.assets")

FONTS_DIR = private_path("fonts")


def read_font_paths():
    """Read the local font override file; returns ``[cjk, jp, ...]`` paths.

    A relative entry resolves against that file's own directory, so the file
    can stay machine-independent (e.g. ``fonts/GlowSansSC-...``).  Entries
    that do not exist are dropped rather than returned as broken paths -
    a stale line should not become a failed font application later.
    """
    local = private_path("font-paths")
    paths = []
    try:
        lines = local.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        p = line.strip()
        if not p or p.startswith("#"):
            continue
        cand = Path(p)
        if not cand.is_absolute():
            cand = local.parent / p
        if cand.is_file():
            paths.append(str(cand))
    return paths


def discover_font(pattern):
    """Auto-discover a registered font by filename prefix (case-insensitive).

    Prefers a ``-Regular`` weight variant when present, else the first match,
    so a family shipped with several weights does not resolve at random.
    Returns the path or None.
    """
    if not FONTS_DIR.is_dir():
        return None
    first = None
    try:
        entries = sorted(FONTS_DIR.iterdir())
    except OSError:
        return None
    for f in entries:
        if not f.is_file():
            continue
        name = f.name.lower()
        if name.startswith(pattern):
            if first is None:
                first = str(f)
            if "-regular" in name:
                return str(f)
    return first


def find_cjk_font():
    """The Simplified-Chinese font for a translated build, or None.

    ``None`` means "no font configured", which is a reportable condition, not
    a silent fallback: the caller decides whether that is fatal (font policy
    ``required``) or merely a warning (``auto``).
    """
    p = os.environ.get("CJK_FONT_PATH")
    if p and os.path.isfile(p):
        return p
    paths = read_font_paths()
    if paths:
        return paths[0]
    return discover_font("glowsanssc")


def find_jp_font():
    """Japanese fallback font: the second line of the local font-paths file,
    or ``JP_FONT_PATH``.

    None when unset - callers then keep the game's original font for Japanese
    text, which is the correct behaviour for a build that is not fully
    translated.
    """
    p = os.environ.get("JP_FONT_PATH")
    if p and os.path.isfile(p):
        return p
    paths = read_font_paths()
    if len(paths) > 1:
        return paths[1]
    return discover_font("glowsansj")
