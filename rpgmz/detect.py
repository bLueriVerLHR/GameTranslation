#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Detect the engine / deploy layout of an RPG Maker game folder."""
import os


def is_web_root(dirpath):
    """True if `dirpath` is a web deploy root (contains index.html + js/)."""
    return os.path.isfile(os.path.join(dirpath, "index.html")) and os.path.isdir(
        os.path.join(dirpath, "js")
    )


def find_web_root(game_dir):
    """Return the folder that should be served as the web root.

    - MZ root deploy: index.html at game root.
    - MV: game root usually has a `www/` folder with index.html.
    - If the root already *is* a web root, return it unchanged.
    """
    if is_web_root(game_dir):
        return game_dir
    www = os.path.join(game_dir, "www")
    if is_web_root(www):
        return www
    return None


def is_mz(web_root):
    return os.path.isfile(os.path.join(web_root, "js", "rmmz_core.js"))


def is_mv(web_root):
    return os.path.isfile(os.path.join(web_root, "js", "rpg_core.js"))


def audio_exts(web_root):
    """Set of audio extensions actually present under audio/."""
    audio_dir = os.path.join(web_root, "audio")
    exts = set()
    if os.path.isdir(audio_dir):
        for dp, _dn, fns in os.walk(audio_dir):
            for fn in fns:
                exts.add(os.path.splitext(fn)[1].lower())
    return exts


def has_encrypted_extensions(web_root):
    """True if any asset name carries a trailing underscore (MZ encrypted form)."""
    for sub in ("img", "audio"):
        base = os.path.join(web_root, sub)
        if not os.path.isdir(base):
            continue
        for dp, _dn, fns in os.walk(base):
            for fn in fns:
                if fn.endswith("_"):
                    return True
    return False
