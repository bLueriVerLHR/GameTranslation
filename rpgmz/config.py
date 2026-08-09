#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared configuration for the RPG Maker -> JoiPlay toolkit.

Machine-specific paths (deliverable folders, tool binaries, venv) live in
the gitignored local file docs/table/env_config.json (see docs/table/README.md).
The config records the current platform (e.g. "wsl"); all tools are pure
native tools of that platform (7z-zstd binary ships inside docs/table/3rd/),
and only file storage locations are machine-specific. Every lookup follows
the same order: environment variable override -> env_config.json ->
built-in default -> PATH lookup. Paths use forward slashes and %VAR% tokens
are expanded at runtime; config paths relative to the repo are resolved
against the config file's own directory (docs/table/).
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILE = REPO_ROOT / "docs" / "table" / "env_config.json"

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

# Legacy Windows defaults, kept as last-resort fallbacks on native Windows.
DEFAULT_FFMPEG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local")),
    "Temp", "opencode", "ffmpeg_x", "ffmpeg-8.1.2-essentials_build", "bin",
)
DEFAULT_SEVENZ = r"C:\Program Files\7-Zip-Zstandard\7z.exe"


# ---------------------------------------------------------------- platform

def is_wsl():
    """True when running inside WSL (Linux with a Microsoft kernel)."""
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def platform_key():
    """Current platform key used inside env_config.json."""
    if is_wsl():
        return "wsl"
    if sys.platform == "win32":
        return "win32"
    return "linux"


def recorded_platform():
    """Platform recorded in env_config.json (informational only; the code
    still detects the actual platform at runtime)."""
    return _load_env_config().get("platform") or platform_key()


# ---------------------------------------------------------------- local env config

def _load_env_config():
    """Read the gitignored machine config (docs/table/env_config.json)."""
    if not LOCAL_ENV_FILE.is_file():
        return {}
    try:
        return json.loads(LOCAL_ENV_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _pick(section, name):
    """Pick the value for the current platform from a config section.

    Values are plain (current platform only); a name -> {platform: value}
    mapping is also accepted for forward compatibility.
    """
    if not isinstance(section, dict):
        return None
    entry = section.get(name)
    if isinstance(entry, dict) and any(k in entry for k in ("wsl", "win32", "linux")):
        for key in (platform_key(), "linux", "wsl", "win32"):
            if entry.get(key):
                return entry[key]
        return None
    return entry


def _expand(path):
    """Expand %VAR% tokens and normalize separators for cross-platform use."""
    if not path:
        return path
    path = re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), path)
    return path.replace("\\", "/")


def _resolve(env_var, cfg_section, cfg_name, default=""):
    """Environment variable -> env_config.json -> default (all expanded)."""
    p = os.environ.get(env_var)
    if p:
        return p
    p = _pick(cfg_section, cfg_name)
    return _expand(p or default)


# ---------------------------------------------------------------- deliverables

def games_dir():
    """Deliverable folder for finished game builds (D:/Games <-> /mnt/d/Games)."""
    return _resolve("GAMES_DIR", _load_env_config().get("deliverables"), "games",
                    "D:/Games" if sys.platform == "win32" else "/mnt/d/Games")


def archives_dir():
    """Deliverable folder for game archives (D:/GamesCompress <-> /mnt/d/GamesCompress)."""
    return _resolve("ARCHIVES_DIR", _load_env_config().get("deliverables"), "archives",
                    "D:/GamesCompress" if sys.platform == "win32" else "/mnt/d/GamesCompress")


def temp_dir():
    """Work directory for temp copies (%LOCALAPPDATA%/Temp/opencode <-> /tmp/opencode)."""
    return _resolve("TEMP_DIR", _load_env_config().get("deliverables"), "temp",
                    "%LOCALAPPDATA%/Temp/opencode" if sys.platform == "win32"
                    else "/tmp/opencode")


# ---------------------------------------------------------------- venv

def venv_dir():
    """Project virtualenv directory (created locally, gitignored)."""
    rel = _pick(_load_env_config().get("venv"), "dir") or ".venv"
    return REPO_ROOT / rel


def venv_python():
    """Python interpreter inside the project venv (best compatibility)."""
    exe = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return str(venv_dir() / exe)


# ---------------------------------------------------------------- tools

def _find_tool(env_var, cfg_name, win_default="", names=()):
    """Resolve a tool binary: env var -> env_config.json -> default -> PATH."""
    p = os.environ.get(env_var)
    if p and os.path.isfile(p):
        return p
    cfg = _expand(_pick(_load_env_config().get("tools"), cfg_name) or "")
    if cfg and not os.path.isabs(cfg):
        cfg = str(LOCAL_ENV_FILE.parent / cfg)
    if cfg and os.path.isfile(cfg):
        return cfg
    if sys.platform == "win32" and win_default and os.path.isfile(win_default):
        return win_default
    for name in names:
        q = shutil.which(name)
        if q:
            return q
    return cfg or (names[0] if names else (win_default or cfg_name))


def find_ffmpeg():
    return _find_tool("FFMPEG", "ffmpeg",
                      os.path.join(DEFAULT_FFMPEG_DIR, "ffmpeg.exe"), ("ffmpeg",))


def find_ffprobe():
    return _find_tool("FFPROBE", "ffprobe",
                      os.path.join(DEFAULT_FFMPEG_DIR, "ffprobe.exe"), ("ffprobe",))


def find_7z():
    return _find_tool("SEVENZ", "7z", DEFAULT_SEVENZ, ("7z", "7zz", "7za"))


def find_rg():
    return _find_tool("RG", "rg", "", ("rg",))


def find_git():
    return _find_tool("GIT", "git", "", ("git",))


# Preferred CJK font for translated builds. Machine paths never live in the
# repo - resolve at runtime:
#   1. env var CJK_FONT_PATH / JP_FONT_PATH
#   2. gitignored local override file docs/table/local_font_path.txt (lines 1/2)
#   3. None (caller keeps the plain fallback list)


def _read_font_paths():
    """Read the local font override file; returns (cjk_path, jp_path)."""
    local = REPO_ROOT / "docs" / "table" / "local_font_path.txt"
    paths = []
    try:
        for line in local.read_text(encoding="utf-8").splitlines():
            p = line.strip()
            if p and os.path.isfile(p):
                paths.append(p)
    except OSError:
        pass
    return paths


def find_cjk_font():
    p = os.environ.get("CJK_FONT_PATH")
    if p and os.path.isfile(p):
        return p
    paths = _read_font_paths()
    return paths[0] if paths else None


def find_jp_font():
    """Japanese fallback font (second line of local_font_path.txt, or
    JP_FONT_PATH env var). None when unset - callers keep the game's
    original font for Japanese text."""
    p = os.environ.get("JP_FONT_PATH")
    if p and os.path.isfile(p):
        return p
    paths = _read_font_paths()
    return paths[1] if len(paths) > 1 else None
