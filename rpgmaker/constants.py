#!/usr/bin/env python3
"""constants.py - RPG Maker build constants.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).
These are facts about the engine's output layout and the JoiPlay target, not
configuration: nothing here is machine-specific and nothing is ever probed or
overridden, so it lives away from the resolver machinery.

Deliberately NOT re-exported through ``rpgmaker.config`` as a *new* home: the
old import path still works (see ``config.py``), but new code should import
from here so the constants are not entangled with path resolution.
"""
__all__ = [
    "IMG_JUNK_EXTS",
    "MONO_BITRATE_THRESHOLD",
    "NWJS_RUNTIME",
    "PNG_MAX_DIMENSION",
    "REPACK_JUNK_DIRS",
    "RPGMV_HEADER",
    "STEREO_BITRATE_THRESHOLD",
    "WEB_DIRS",
]

# RPGMaker encrypted asset magic header (both MZ ".png_/.ogg_" and MV
# ".rpgmvp/.rpgmvo").
RPGMV_HEADER = bytes.fromhex("5250474d560000000003010000000000")

# Audio re-encode thresholds (bits/sec), from the workflow guide: media above
# these is worth re-encoding for the mobile target.
MONO_BITRATE_THRESHOLD = 64000
STEREO_BITRATE_THRESHOLD = 112000

# Android WebView/PixiJS cap WebGL textures at 4096 px per side; PNGs beyond
# this (usually tall standing art) render as black blocks on phones.  Used by
# tools/downscale_images.py as the default per-side limit.
PNG_MAX_DIMENSION = 4096

# Web folders that JoiPlay actually needs (MZ root deploy).
WEB_DIRS = [
    "audio", "css", "data", "data_encrypted", "dataEx", "effects", "fonts",
    "icon", "img", "js", "movies", "scenario",
]

# NW.js desktop runtime files to strip from the root of an MZ deploy.
NWJS_RUNTIME = [
    "Game.exe", "nw.dll", "nw_elf.dll", "node.dll", "icudtl.dat",
    "libEGL.dll", "libGLESv2.dll", "d3dcompiler_47.dll", "resources.pak",
    "swiftshader", "ffmpeg.dll", "nw_100_percent.pak", "nw_200_percent.pak",
    "notification_helper.exe", "v8_context_snapshot.bin", "natives_blob.bin",
    "snapshot_blob.bin", "locales", "credits.html", "debug.log",
    "lastLoadedTrsFile", "package.json", "save",
]

# Repack tooling that never belongs in a JoiPlay build.  These are *extra*
# directories (not standard MZ web folders, not NW.js runtime), so `build`
# drops them while copying every other extra directory as plugin assets.
REPACK_JUNK_DIRS = [
    "Tool", "MTool", "Dictionaries", "TrsData", "__pycache__", "node_modules",
]

# Editor / repack junk that can usually be dropped from img/ (never loaded at
# runtime).
IMG_JUNK_EXTS = {".txt", ".clip", ".tmx", ".bak"}
