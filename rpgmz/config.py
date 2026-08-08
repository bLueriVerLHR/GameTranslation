#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared configuration for the RPG Maker -> JoiPlay toolkit.

Tool discovery order: environment variable override, then known defaults,
then PATH lookup. Everything is a plain function so the CLI can refresh
resolved paths at runtime.
"""
import os
import shutil

# RPGMaker encrypted asset magic header (both MZ ".png_/.ogg_" and MV ".rpgmvp/.rpgmvo")
RPGMV_HEADER = bytes.fromhex("5250474d560000000003010000000000")

# Audio re-encode thresholds (bits/sec), from the workflow guide.
MONO_BITRATE_THRESHOLD = 64000
STEREO_BITRATE_THRESHOLD = 112000

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
# Editor / repack junk that can usually be dropped from img/ (never loaded at runtime).
IMG_JUNK_EXTS = {".txt", ".clip", ".tmx", ".bak"}

DEFAULT_FFMPEG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local")),
    "Temp", "opencode", "ffmpeg_x", "ffmpeg-8.1.2-essentials_build", "bin",
)
DEFAULT_SEVENZ = r"C:\Program Files\7-Zip-Zstandard\7z.exe"


def _candidate(base, name):
    return os.path.join(base, name) if base else name


def find_ffmpeg():
    p = os.environ.get("FFMPEG")
    if p and os.path.isfile(p):
        return p
    p = _candidate(DEFAULT_FFMPEG_DIR, "ffmpeg.exe")
    if os.path.isfile(p):
        return p
    p = shutil.which("ffmpeg")
    return p or "ffmpeg"


def find_ffprobe():
    p = os.environ.get("FFPROBE")
    if p and os.path.isfile(p):
        return p
    p = _candidate(DEFAULT_FFMPEG_DIR, "ffprobe.exe")
    if os.path.isfile(p):
        return p
    p = shutil.which("ffprobe")
    return p or "ffprobe"


def find_7z():
    p = os.environ.get("SEVENZ")
    if p and os.path.isfile(p):
        return p
    if os.path.isfile(DEFAULT_SEVENZ):
        return DEFAULT_SEVENZ
    p = shutil.which("7z")
    return p or "7z"


# Preferred CJK font for translated builds. Machine paths never live in the
# repo - resolve at runtime:
#   1. env var CJK_FONT_PATH
#   2. gitignored local override file docs/table/local_font_path.txt (first line)
#   3. None (caller keeps the plain fallback list)


def find_cjk_font():
    p = os.environ.get("CJK_FONT_PATH")
    if p and os.path.isfile(p):
        return p
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "docs", "table", "local_font_path.txt")
    try:
        with open(local, encoding="utf-8") as f:
            for line in f:
                p = line.strip()
                if p and os.path.isfile(p):
                    return p
    except OSError:
        pass
    return None
