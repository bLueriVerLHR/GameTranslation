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
import logging
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILE = REPO_ROOT / "docs" / "table" / "env_config.json"

log = logging.getLogger("rpgmaker.config")

# Tags whose missing-default WARNING was already emitted this process, so the
# warning is logged exactly once instead of once per call (review §6.2 / E).
_warned_defaults = set()


def _warn_once(tag, message):
    """Log a WARNING at most once per (tag) per process: a silent fallback to
    a built-in default that does not exist should be noticed, not repeated."""
    if tag in _warned_defaults:
        return
    _warned_defaults.add(tag)
    log.warning(message)

# RPGMaker encrypted asset magic header (both MZ ".png_/.ogg_" and MV ".rpgmvp/.rpgmvo")
RPGMV_HEADER = bytes.fromhex("5250474d560000000003010000000000")

# Audio re-encode thresholds (bits/sec), from the workflow guide.
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
# Editor / repack junk that can usually be dropped from img/ (never loaded at runtime).
IMG_JUNK_EXTS = {".txt", ".clip", ".tmx", ".bak"}

# Legacy Windows defaults, kept as last-resort fallbacks on native Windows.
DEFAULT_FFMPEG_DIR = str(
    Path(os.environ.get(
        "LOCALAPPDATA",
        os.path.join(os.path.expanduser("~"), "AppData", "Local"),
    )) / "Temp" / "opencode" / "ffmpeg_x" / "ffmpeg-8.1.2-essentials_build" / "bin"
)
DEFAULT_SEVENZ = r"C:\Program Files\7-Zip-Zstandard\7z.exe"
# Windows-side 7z, used when files live on the Windows side (see
# is_windows_side / the AGENTS.md CRITICAL cross-system rule).
DEFAULT_WIN_SEVENZ = DEFAULT_SEVENZ


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


def is_windows_side(path):
    """True when `path` points at a Windows-side file from inside WSL.

    Windows-side files (/mnt/*) must be processed by the Windows-side tools
    only - WSL-native tools (7zz, python) touching them is forbidden
    (AGENTS.md, "cross-system file handling" CRITICAL rule).
    """
    if not is_wsl():
        return False
    return _posix(path).startswith("/mnt/")


def _posix(path):
    """Normalize a path string to forward-slash form (accepts both Windows
    and POSIX separators via pathlib, no manual separator handling)."""
    return PureWindowsPath(str(path)).as_posix()


def to_windows_path(path):
    """Convert a /mnt/<drive>/... path to Windows form (D:\\...); anything
    else is returned unchanged."""
    parts = PurePosixPath(_posix(path)).parts
    if len(parts) < 4 or parts[1] != "mnt" or len(parts[2]) != 1:
        return str(path)
    # "\\" segment = drive root (pathlib semantics, not string joining).
    return str(PureWindowsPath(parts[2].upper() + ":", "\\", *parts[3:]))


def to_wsl_path(path):
    """Map a Windows-form path (C:\\... or /mnt/...) to the WSL mount view
    (/mnt/c/...) so it can be stat/read from WSL. Relative inputs are
    returned unchanged."""
    pw = PureWindowsPath(str(path))
    if not pw.drive:
        return str(path)
    return str(Path("/mnt") / pw.drive[0].lower() / Path(*pw.parts[1:]).as_posix())


def _win_tool(name, env_var, default=""):
    """Windows-side tool binary by name: <ENV_VAR> env ->
    env_config tools.win32.<name> -> default; None when absent.  The win32
    section is read explicitly because these tools serve Windows-side
    files even when the current platform is WSL.  A configured path that
    cannot be resolved (e.g. %ProgramFiles% tokens unexpandable on WSL)
    falls through to the default."""
    p = os.environ.get(env_var)
    if not p:
        p = _expand(_pick(_win32_section(_load_env_config().get("tools")),
                          name) or "")
    if p and os.path.isfile(to_wsl_path(p)):
        return str(p)
    # configured value absent OR unresolvable (e.g. %ProgramFiles% tokens
    # unexpandable on WSL) -> fall back to the default
    if default and os.path.isfile(to_wsl_path(default)):
        return str(default)
    return None


def win_7z():
    """Windows-side 7z binary, for processing files stored on the Windows
    side. Resolution: SEVENZ_WIN env -> env_config tools.win32.7z ->
    DEFAULT_WIN_SEVENZ; None when the binary is not present."""
    p = _win_tool("7z", "SEVENZ_WIN", DEFAULT_WIN_SEVENZ)
    if p is None and DEFAULT_WIN_SEVENZ:
        _warn_once(
            "win7z-default",
            "default Windows 7z not found (%s); set SEVENZ_WIN or "
            "env_config.json tools.win32.7z to enable Windows-side "
            "extraction" % DEFAULT_WIN_SEVENZ)
    return p


def win_ffmpeg():
    """Windows-side ffmpeg binary (WinGet install), for processing files
    stored on the Windows side. Resolution: WIN_FFMPEG env ->
    env_config tools.win32.ffmpeg; None when not configured/absent."""
    return _win_tool("ffmpeg", "WIN_FFMPEG")


def win_rg():
    """Windows-side ripgrep binary (WinGet install), for searching files
    stored on the Windows side. Resolution: WIN_RG env ->
    env_config tools.win32.rg; None when not configured/absent."""
    return _win_tool("rg", "WIN_RG")


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
    """Return a config value by name (plain values only)."""
    if not isinstance(section, dict):
        return None
    return section.get(name)


def _section_platform(section):
    """Pick the current platform's sub-dict of a platform-first config
    section ({wsl: {...}, win32: {...}}); a plain section (no platform
    keys) is returned unchanged for backward compatibility."""
    if not isinstance(section, dict):
        return {}
    if not any(k in section for k in ("wsl", "win32", "linux")):
        return section
    for key in (platform_key(), "linux", "wsl", "win32"):
        if isinstance(section.get(key), dict):
            return section[key]
    return {}


def _win32_section(section):
    """The win32 sub-dict of a platform-first config section; Windows-only
    tools live there and must be found regardless of the current platform."""
    if not isinstance(section, dict):
        return {}
    sub = section.get("win32")
    return sub if isinstance(sub, dict) else {}


def _localize(path):
    """Map a stored native path to the current platform's view.

    A path is stored ONCE, in the form of the platform where the resource
    physically lives (Windows-side resources as C:/.. or D:/.., WSL-side
    resources as /tmp/..).  On WSL a Windows-form path is converted to its
    /mnt/<drive>/.. view; on Windows a /mnt/.. path is converted back.
    Paths already in the current platform's form pass through unchanged.
    """
    if not path:
        return path
    return to_wsl_path(path) if is_wsl() else to_windows_path(path)


def _expand(path):
    """Expand %VAR% tokens and normalize separators for cross-platform use."""
    if not path:
        return path
    path = re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), path)
    return _posix(path)


def _deliverable(env_var, cfg_name, default=""):
    """Environment variable -> env_config deliverables.<name> -> default;
    the stored/default path is native-form and gets localized for the
    current platform.  Plain (scalar) values only: the nested
    deliverables.temp dict is handled by _temp_dir_cfg()."""
    p = os.environ.get(env_var)
    if not p:
        p = _pick(_load_env_config().get("deliverables"), cfg_name)
    if isinstance(p, dict):
        p = None
    return _localize(_expand(p or default))


def _temp_dir_cfg(key):
    """A deliverables.temp sub-path (persist / tmpfs / win32), accepting
    both the nested dict format {persist, tmpfs, win32} and the legacy
    plain-string format (all keys fall back to the same value)."""
    t = _pick(_load_env_config().get("deliverables"), "temp")
    if isinstance(t, dict):
        p = t.get(key)
    else:
        p = t if isinstance(t, str) else None
    return _localize(_expand(p or ""))


def temp_dir():
    """Work directory for temp copies: the persistent large-work dir on
    WSL (deliverables.temp.persist), the Windows %TEMP% on Windows
    (deliverables.temp.win32)."""
    return _temp_dir_cfg("persist" if is_wsl() else "win32") \
        or _deliverable("TEMP_DIR", "temp",
                        "%LOCALAPPDATA%/Temp/opencode"
                        if sys.platform == "win32" else "/tmp/opencode")


# ---------------------------------------------------------------- deliverables

def _warn_missing_default_deliverable(env_var, cfg_name, path):
    """Warn once when a deliverables built-in default is actually in use
    (no env var, no env_config entry) and the path does not exist - the
    operator should configure env_config.json instead of silently relying on
    a legacy Windows default."""
    if os.environ.get(env_var):
        return
    cfg = _load_env_config().get("deliverables")
    if isinstance(cfg, dict) and cfg.get(cfg_name):
        return
    if not path or os.path.exists(path):
        return
    _warn_once(
        "default:%s" % cfg_name,
        "no deliverables.%s in env_config.json; using built-in default %s "
        "which does not exist - add deliverables.%s to configure a real "
        "folder" % (cfg_name, path, cfg_name))


def games_dir():
    """Deliverable folder for finished game builds (stored native:
    D:/Games; localized to /mnt/d/Games on WSL)."""
    p = _deliverable("GAMES_DIR", "games", "D:/Games")
    _warn_missing_default_deliverable("GAMES_DIR", "games", p)
    return p


def archives_dir():
    """Deliverable folder for game archives (stored native:
    D:/GamesCompress; localized to /mnt/d/GamesCompress on WSL)."""
    p = _deliverable("ARCHIVES_DIR", "archives", "D:/GamesCompress")
    _warn_missing_default_deliverable("ARCHIVES_DIR", "archives", p)
    return p


def win_temp_dir():
    """Windows-side temp for downloads and Windows-only tools (the Windows
    %TEMP% folder; stored native: %LOCALAPPDATA%/Temp, localized to
    /mnt/c/... on WSL).  Reads the nested deliverables.temp.win32 key
    (legacy plain deliverables.win_temp accepted)."""
    p = _temp_dir_cfg("win32")
    if p:
        return p
    return _deliverable("WIN_TEMP_DIR", "win_temp", "%LOCALAPPDATA%/Temp")


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
    """Resolve a tool binary: env var -> env_config.json (current platform
    section) -> default -> PATH.  Returns None when no binary is found, so
    callers can distinguish "found" from "not found" (a missing tool is a
    caller error, not a silently-usable tool-name string)."""
    p = os.environ.get(env_var)
    if p and os.path.isfile(p):
        return p
    cfg = _expand(_pick(_section_platform(_load_env_config().get("tools")),
                        cfg_name) or "")
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
    return None


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


def find_npx():
    """Locate the npx launcher (Node.js package runner). Same resolution as
    _find_tool (NPX env -> env_config -> PATH), plus an explicit npx.cmd
    fallback on Windows: shutil.which may miss .cmd shims in some setups
    (mirrors tyrano/asar.py find_npx)."""
    p = _find_tool("NPX", "npx", "", ("npx",))
    if not p and sys.platform == "win32":
        p = shutil.which("npx.cmd")
    return p


# Preferred CJK font for translated builds. Machine paths never live in the
# repo - resolve at runtime:
#   1. env var CJK_FONT_PATH / JP_FONT_PATH
#   2. gitignored local override file docs/table/local_font_path.txt (lines 1/2)
#   3. the bundled fonts dir docs/table/fonts/ (auto-discovered: a SC
#      Simplified-Chinese font for CJK, a J Japanese font as the JP fallback)
#   4. None (caller keeps the plain fallback list)

# Fonts live in the gitignored local dir docs/table/fonts/ (owner-supplied
# font files, not committed).  The auto-discovery below resolves them from
# wherever the repo is checked out; fresh machines add fonts there or set
# CJK_FONT_PATH / JP_FONT_PATH.
FONTS_DIR = REPO_ROOT / "docs" / "table" / "fonts"


def _read_font_paths():
    """Read the local font override file; returns (cjk_path, jp_path).

    A relative path resolves against docs/table/ (the file's own directory),
    so the file can stay machine-independent (e.g. "fonts/GlowSansSC-...").
    """
    local = REPO_ROOT / "docs" / "table" / "local_font_path.txt"
    paths = []
    try:
        for line in local.read_text(encoding="utf-8").splitlines():
            p = line.strip()
            if not p:
                continue
            cand = Path(p)
            if not cand.is_absolute():
                cand = local.parent / p
            if cand.is_file():
                paths.append(str(cand))
    except OSError:
        pass
    return paths


def _discover_font(pattern):
    """Auto-discover a font file inside docs/table/fonts/ by filename
    pattern (case-insensitive). Prefers a "-Regular" weight variant when
    present, else the first match. Returns the path or None."""
    if not FONTS_DIR.is_dir():
        return None
    first = None
    try:
        for f in sorted(FONTS_DIR.iterdir()):
            if not f.is_file():
                continue
            name = f.name.lower()
            if name.startswith(pattern):
                if first is None:
                    first = str(f)
                if "-regular" in name:
                    return str(f)
    except OSError:
        pass
    return first


def find_cjk_font():
    p = os.environ.get("CJK_FONT_PATH")
    if p and os.path.isfile(p):
        return p
    paths = _read_font_paths()
    if paths:
        return paths[0]
    return _discover_font("glowsanssc")


def find_jp_font():
    """Japanese fallback font (second line of local_font_path.txt, or
    JP_FONT_PATH env var). None when unset - callers keep the game's
    original font for Japanese text."""
    p = os.environ.get("JP_FONT_PATH")
    if p and os.path.isfile(p):
        return p
    paths = _read_font_paths()
    if len(paths) > 1:
        return paths[1]
    return _discover_font("glowsansj")
