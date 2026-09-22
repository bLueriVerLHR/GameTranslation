#!/usr/bin/env python3
"""Detect the engine / deploy layout of an RPG Maker game folder."""
import os

# A playable web root carries its database either plain (data/) or encrypted
# (data_encrypted/, which decrypt.py turns back into data/).
DATA_DIRS = ("data", "data_encrypted")


def has_game_data(dirpath):
    """True when `dirpath` carries the game database (plain or encrypted).

    `index.html` + `js/` alone is NOT enough: MTool-style "launcher" repacks
    keep the MZ engine and the assets at the root but move the whole data
    store into the tool's own pack, so building that root would silently
    produce a game with no database at all.  Requiring the data directory
    makes such a folder fail loudly instead.
    """
    return any(os.path.isdir(os.path.join(dirpath, d)) for d in DATA_DIRS)


def is_web_root(dirpath):
    """True if `dirpath` is a web deploy root (index.html + js/ + data)."""
    return (os.path.isfile(os.path.join(dirpath, "index.html"))
            and os.path.isdir(os.path.join(dirpath, "js"))
            and has_game_data(dirpath))


def find_web_root(game_dir):
    """Return the folder that should be served as the web root.

    - MZ root deploy: index.html at game root.
    - MV: game root usually has a `www/` folder with index.html.
    - If the root already *is* a web root, return it unchanged.

    Returns None when no folder qualifies (the caller reports it) - e.g. an
    MTool-style launcher root, whose game data lives in the tool's pack
    rather than in `data/`.
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
        for _dp, _dn, fns in os.walk(audio_dir):
            for fn in fns:
                exts.add(os.path.splitext(fn)[1].lower())
    return exts


def has_encrypted_extensions(web_root):
    """True if any asset name carries a trailing underscore (MZ encrypted form)."""
    for sub in ("img", "audio"):
        base = os.path.join(web_root, sub)
        if not os.path.isdir(base):
            continue
        for _dp, _dn, fns in os.walk(base):
            for fn in fns:
                if fn.endswith("_"):
                    return True
    return False
