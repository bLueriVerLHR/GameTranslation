#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safe image/font cleanup.

What is safe to delete (verified against this engine):
- non-PNG junk files in img/ (.txt/.clip/.tmx/.bak) - never loaded at runtime
- fonts whose filename is referenced nowhere in data/ + js/
- tilesets not referenced by Tilesets.json tilesetNames (case-insensitive)

CGs in img/pictures are deliberately NEVER deleted: this game builds many CG
filenames dynamically from variables, so a "not found in corpus" heuristic is
not trustworthy for them.
"""
import json
import logging
import os
import re

from . import config

log = logging.getLogger("rpgmz.clean")


def _corpus_text(web_root):
    """All data JSON + all js text + css/font css, used for reference checks.

    Font references live in data/, js/, css/*.css and fonts/*.css (MV declares
    @font-face in fonts/gamefont.css), so css must be part of the corpus or a
    real game font gets deleted as "unused"."""
    parts = []
    data_dir = os.path.join(web_root, "data")
    js_dir = os.path.join(web_root, "js")
    for base in (data_dir, js_dir,
                 os.path.join(web_root, "css"),
                 os.path.join(web_root, "fonts")):
        if not os.path.isdir(base):
            continue
        for dp, _dn, fns in os.walk(base):
            for fn in fns:
                p = os.path.join(dp, fn)
                try:
                    with open(p, encoding="utf-8-sig", errors="replace") as f:
                        parts.append(f.read())
                except Exception:
                    pass
    return "\n".join(parts)


def remove_img_junk(web_root, dry_run=False):
    """Delete non-PNG files under img/ (editor/repack leftovers)."""
    img_dir = os.path.join(web_root, "img")
    removed, freed = 0, 0
    if not os.path.isdir(img_dir):
        return 0, 0
    for dp, _dn, fns in os.walk(img_dir):
        for fn in fns:
            if os.path.splitext(fn)[1].lower() in config.IMG_JUNK_EXTS:
                p = os.path.join(dp, fn)
                freed += os.path.getsize(p)
                if not dry_run:
                    os.remove(p)
                removed += 1
    log.info("removed %d junk img files (%s), freed %.1f KB",
             removed, "dry-run" if dry_run else "done", freed / 1024)
    return removed, freed


FONT_EXTS = {".ttf", ".otf", ".ttc", ".woff", ".woff2", ".eot"}


def _font_references(web_root):
    """Set of font filenames (original case) mentioned in data/js/css.

    Uses a broad class so CJK font filenames (e.g. ラノベPOP.ttf) match too.
    Tokens are matched first (linear), then filtered by extension, because a
    greedy-class + suffix regex can backtrack quadratically on long runs of
    characters (e.g. binary SDK blobs shipped under js/)."""
    corpus = _corpus_text(web_root)
    refs = set()
    for m in re.finditer(r"[^\s\"'():;]+", corpus):
        # Escaped quotes in js (\"...\") glue trailing backslashes onto the
        # filename token; strip them so `font.ttf\"` still ends in .ttf.
        # Comma-joined plugin params ("TW.ttf,CN.ttf,JP.ttf") come through as
        # ONE token; split on commas so each font matches individually.
        for tok in m.group(0).rstrip("\\").split(","):
            if re.search(r"\.(?:ttf|otf|ttc|woff2?|eot)$", tok, re.IGNORECASE):
                refs.add(tok)
    return refs


def remove_unused_fonts(web_root, dry_run=False):
    """Delete fonts not referenced anywhere in data/js.

    Matching is case-insensitive; if a font is referenced but only under a
    different case (e.g. on-disk `onryou.TTF` vs referenced `onryou.ttf`),
    rename it to the exact referenced name so Android's case-sensitive
    filesystem still finds it.
    """
    fonts_dir = os.path.join(web_root, "fonts")
    if not os.path.isdir(fonts_dir):
        return 0, 0
    refs = _font_references(web_root)
    # References may include a dir prefix (e.g. "fonts/ship.otf"), so match
    # on the basename, keeping the referenced name for the case-fix rename.
    refs_by_lower = {os.path.basename(r).lower(): os.path.basename(r) for r in refs}
    removed, freed, renamed = 0, 0, 0
    for fn in os.listdir(fonts_dir):
        p = os.path.join(fonts_dir, fn)
        if not os.path.isfile(p):
            continue
        if os.path.splitext(fn)[1].lower() not in FONT_EXTS:
            continue
        target = refs_by_lower.get(fn.lower())
        if target:
            if target != fn:  # case mismatch -> align to referenced name
                if not dry_run:
                    os.rename(p, os.path.join(fonts_dir, target))
                renamed += 1
            continue
        freed += os.path.getsize(p)
        if not dry_run:
            os.remove(p)
        removed += 1
    log.info("removed %d unused fonts, renamed %d for case (%s), freed %.1f MB",
             removed, renamed, "dry-run" if dry_run else "done", freed / 1e6)
    return removed, freed


def _referenced_tilesets(web_root):
    names = []
    tilesets_path = os.path.join(web_root, "data", "Tilesets.json")
    if not os.path.isfile(tilesets_path):
        return set()
    try:
        with open(tilesets_path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        log.warning("data/Tilesets.json not plain JSON (custom runtime-decryption); "
                    "tileset cleanup skipped")
        return set()
    for ts in data:
        if ts and ts.get("tilesetNames"):
            names.extend(n for n in ts["tilesetNames"] if n)
    return set(n.lower() for n in names)


def _corpus_referenced_tilesets(web_root):
    """Tileset stems mentioned anywhere in data/js/css (plugin/script loads).

    Linear token scan (see _font_references): a greedy `[A-Za-z0-9_&%\-]+\.png`
    pattern backtracks quadratically on long alphanumeric runs."""
    corpus = _corpus_text(web_root)
    refs = set()
    for m in re.finditer(r"[A-Za-z0-9_&%\-]+", corpus):
        tok = m.group(0)
        if tok.lower().endswith(".png"):
            refs.add(tok[:-4].lower())
    return refs


def remove_unused_tilesets(web_root, dry_run=False):
    """Delete tileset PNGs not referenced by Tilesets.json nor anywhere in the
    data/js/css corpus (case-insensitive, excluding prefix-variants like name_2).

    The corpus check protects tilesets loaded by plugins/scripts (e.g. world-map
    plugins that build names dynamically like World_A1/A2/B/C) even when they
    are not listed in Tilesets.json."""
    tiles_dir = os.path.join(web_root, "img", "tilesets")
    if not os.path.isdir(tiles_dir):
        return 0, 0
    referenced = _referenced_tilesets(web_root) | _corpus_referenced_tilesets(web_root)
    removed, freed = 0, 0
    for fn in os.listdir(tiles_dir):
        if not fn.lower().endswith(".png"):
            continue
        stem = os.path.splitext(fn)[0]
        low = stem.lower()
        if low in referenced:
            continue
        if any(n.lower().startswith(low + "_") for n in referenced):
            continue
        p = os.path.join(tiles_dir, fn)
        freed += os.path.getsize(p)
        if not dry_run:
            os.remove(p)
        removed += 1
    log.info("removed %d unused tilesets (%s), freed %.1f MB",
             removed, "dry-run" if dry_run else "done", freed / 1e6)
    return removed, freed


def cleanup_all(web_root, dry_run=False):
    total = 0
    for fn in (remove_img_junk, remove_unused_fonts, remove_unused_tilesets):
        _r, _f = fn(web_root, dry_run=dry_run)
        total += _f
    log.info("cleanup freed %.1f MB total", total / 1e6)
    return total
