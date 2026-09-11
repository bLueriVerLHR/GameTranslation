#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared configuration: platform detection, application resolution, paths.

Three responsibilities, in this order:

1. **Platform** - which OS/container we run on, and how a path is spelled
   there: ``is_wsl`` / ``platform_key`` / ``is_windows_side`` and the
   conversions ``to_windows_path`` / ``to_wsl_path`` / ``localize``.

2. **Applications** - the single declarative table ``TOOLS`` plus the
   layered resolver ``resolve_tool()``::

       environment override -> explicit local config -> PROBE well-known
       install locations -> PATH lookup

   Adding an external application therefore means adding one ``TOOLS``
   entry; the ``find_*`` wrappers, the ``doctor`` report and the
   ``pipeline.py probe`` output all read the same table, so no other file
   needs to change.

3. **Locations** - work/deliverable folders and bundled fonts. A path is
   stored ONCE, in the native form of the platform that owns the resource
   (Windows resources as ``C:/..``/``D:/..``, POSIX resources as ``/tmp/..``);
   ``localize()`` maps it to the current platform's view.

Nothing here is mandatory configuration: the gitignored local file
``docs/table/env_config.json`` only *overrides* what the probing layer
derives anyway, and deliverable folders are probed then created on demand.

Environment overrides: every ``TOOLS`` entry names its own variable
(``FFMPEG``, ``SEVENZ``, ``SEVENZ_WIN``, ``POWERSHELL_EXE``, ...);
``GT_NO_PROBE=1`` disables filesystem probing (hermetic tests, locked-down
machines) while keeping the env/config/PATH layers.
"""
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILE = REPO_ROOT / "docs" / "table" / "env_config.json"

log = logging.getLogger("rpgmaker.config")

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


# ---------------------------------------------------------------- platform

def is_wsl() -> bool:
    """True when running inside WSL (Linux with a Microsoft kernel)."""
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def platform_key() -> str:
    """Current platform key used inside env_config.json."""
    if is_wsl():
        return "wsl"
    if sys.platform == "win32":
        return "win32"
    return "linux"


def is_windows_side(path: str) -> bool:
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


def to_windows_path(path: str) -> str:
    """Convert a /mnt/<drive>/... path to Windows form (D:\\...); anything
    else is returned unchanged."""
    parts = PurePosixPath(_posix(path)).parts
    if len(parts) < 4 or parts[1] != "mnt" or len(parts[2]) != 1:
        return str(path)
    # "\\" segment = drive root (pathlib semantics, not string joining).
    return str(PureWindowsPath(parts[2].upper() + ":", "\\", *parts[3:]))


def to_wsl_path(path: str) -> str:
    """Map a Windows-form path (C:\\... or /mnt/...) to the WSL mount view
    (/mnt/c/...) so it can be stat/read from WSL.  The result is always in
    POSIX form (assembled from path parts, not through os.sep), so the helper
    behaves identically whether it runs on WSL or on Windows.  Relative
    inputs are returned unchanged."""
    pw = PureWindowsPath(str(path))
    if not pw.drive:
        return str(path)
    drive = pw.drive[0].lower()
    tail = "/".join(pw.parts[1:])
    return "/mnt/%s/%s" % (drive, tail) if tail else "/mnt/%s" % drive


def localize(path):
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


# ---------------------------------------------------------------- local env config

def _load_env_config():
    """Read the gitignored machine config (docs/table/env_config.json).

    The file is an optional OVERRIDE layer: a missing, corrupt or wrongly
    shaped file simply means "use probing and built-in defaults", so every
    failure path returns an empty mapping instead of raising."""
    if not LOCAL_ENV_FILE.is_file():
        return {}
    try:
        data = json.loads(LOCAL_ENV_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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


def _expand(path):
    """Expand %VAR% tokens and normalize separators for cross-platform use.
    Unknown tokens are left verbatim so an unresolvable Windows path stays
    visibly unresolvable instead of silently collapsing."""
    if not path:
        return path
    path = re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), path)
    return _posix(path)


# Tags whose once-per-process note was already emitted, so a long batch
# calling config repeatedly does not repeat the same line.
_warned_defaults = set()


def _note_once(tag, message):
    """Log an INFO note at most once per (tag) per process: "here is the
    folder/app we resolved and why" is useful once, noise on every call."""
    if tag in _warned_defaults:
        return
    _warned_defaults.add(tag)
    log.info(message)


# ---------------------------------------------------------------- tools

@dataclass(frozen=True)
class Tool:
    """One external application the toolkit may shell out to.

    key          registry key (also the env_config tools.<section>.<key> name
                 unless config_key overrides it)
    env          environment variable that overrides everything else
    exe          executable names tried by the PATH lookup (in order)
    side         "native" = belongs to the platform running this code,
                 "win32"  = a Windows-side binary (used to process files that
                 live on the Windows side, see the AGENTS.md CRITICAL rule)
    probe        glob patterns, relative to the probe anchors, tried in order;
                 the newest match wins (version dirs sort naturally)
    path_form    "view"    = return a path executable from *here* (what
                             subprocess needs on this platform),
                 "windows" = return the Windows-form path (what gets handed
                             to a Windows-side tool / PowerShell command line)
    purpose      what needs it - shown by doctor/probe
    hint         what to do when it is missing
    """

    key: str
    env: str
    exe: tuple = ()
    side: str = "native"
    probe: tuple = ()
    path_form: str = "view"
    purpose: str = ""
    hint: str = ""
    config_key: str = ""
    resolver_name: str = ""

    @property
    def cfg(self) -> str:
        return self.config_key or self.key

    @property
    def resolver(self) -> str:
        """Name of the `config` wrapper resolving this tool (doctor calls it
        through the module, so tests can monkeypatch a single tool)."""
        return self.resolver_name or ("find_%s" % self.key)


# Windows anchors usable from WSL too (the %VAR% tokens below are unset
# there, so the literal C: roots keep Windows-side probing working).
_WIN_ANCHOR_TOKENS = (
    "%ProgramFiles%", "%ProgramFiles(x86)%", "%LOCALAPPDATA%", "%APPDATA%",
    "%USERPROFILE%", "%SystemRoot%", "%ProgramData%",
)
_WIN_ANCHOR_LITERAL = (
    "C:/Program Files", "C:/Program Files (x86)", "C:/Windows",
    "C:/ProgramData", "C:/",
)
_POSIX_ANCHOR_TOKENS = ("/usr/bin", "/usr/local/bin", "/usr/sbin", "/opt",
                        "%HOME%/.local/bin")

TOOLS = (
    Tool(
        key="ffmpeg", env="FFMPEG", exe=("ffmpeg",),
        probe=(
            "ffmpeg*/bin/ffmpeg.exe",
            "Microsoft/WinGet/Packages/*/*/bin/ffmpeg.exe",
            "Microsoft/WinGet/Links/ffmpeg.exe",
            "scoop/apps/ffmpeg/current/bin/ffmpeg.exe",
            "scoop/shims/ffmpeg.exe",
            "ffmpeg",
        ),
        purpose="audio probe + re-encode (audio.py, verify.py)",
        hint="install ffmpeg (with libvorbis) or set FFMPEG / "
             "config tools.<platform>.ffmpeg",
    ),
    Tool(
        key="ffprobe", env="FFPROBE", exe=("ffprobe",),
        probe=(
            "ffmpeg*/bin/ffprobe.exe",
            "Microsoft/WinGet/Packages/*/*/bin/ffprobe.exe",
            "Microsoft/WinGet/Links/ffprobe.exe",
            "scoop/apps/ffmpeg/current/bin/ffprobe.exe",
            "scoop/shims/ffprobe.exe",
            "ffprobe",
        ),
        purpose="audio probing (audio.py)",
        hint="ships with ffmpeg; install ffmpeg or set FFPROBE",
    ),
    Tool(
        key="7z", env="SEVENZ", exe=("7z", "7zz", "7za", "7z.exe"),
        probe=(
            "7-Zip*/7z.exe", "Programs/7-Zip*/7z.exe",
            "3rd/7zz", "3rd/7z", "7zz", "7z",
        ),
        purpose="archive create/test/extract (compress.py, deliver.py)",
        hint="install 7-Zip-Zstandard (zstd support) or set SEVENZ / "
             "config tools.<platform>.7z",
    ),
    Tool(
        key="rg", env="RG", exe=("rg", "rg.exe"),
        probe=("Microsoft/WinGet/Packages/*/*/rg.exe",
               "Microsoft/WinGet/Links/rg.exe",
               "scoop/apps/ripgrep/current/rg.exe", "ripgrep*/rg.exe"),
        purpose="fast content search in builds (clean/verify)",
        hint="optional; degrades to a Python fallback when absent",
    ),
    Tool(
        key="git", env="GIT", exe=("git", "git.exe"),
        probe=("Git/cmd/git.exe", "Git/bin/git.exe",
               "Programs/Git/cmd/git.exe"),
        purpose="repo versioning / hygiene (dev workflow only)",
        hint="only needed for the development workflow, not for conversion",
    ),
    Tool(
        key="npx", env="NPX", exe=("npx", "npx.cmd", "npx.exe"),
        probe=("nodejs/npx.cmd", "*/nvm/installs/*/npx.cmd", "nvm/*/npx.cmd",
               "npx"),
        purpose="TyranoScript builds unpack app.asar via npx @electron/asar",
        hint="install Node.js (nodejs.org); only needed for tyrano games",
    ),
    Tool(
        key="powershell", env="POWERSHELL_EXE",
        exe=("powershell.exe", "pwsh.exe"), side="win32",
        probe=("System32/WindowsPowerShell/v1.0/powershell.exe",
               "PowerShell/*/pwsh.exe"),
        purpose="run Windows-side operations from WSL (deliver, wsl_capture)",
        hint="install PowerShell on the Windows side / "
             "请在 Windows 侧安装 PowerShell",
    ),
    Tool(
        key="win7z", env="SEVENZ_WIN", exe=("7z.exe", "7z"), side="win32",
        config_key="7z", path_form="windows", resolver_name="win_7z",
        probe=("7-Zip*/7z.exe", "Programs/7-Zip*/7z.exe"),
        purpose="extract Windows-side (/mnt/*) archives via PowerShell",
        hint="install 7-Zip-Zstandard on Windows or set SEVENZ_WIN / "
             "config tools.win32.7z",
    ),
)

TOOLS_BY_KEY = {t.key: t for t in TOOLS}


def _probe_disabled():
    """True when filesystem probing is switched off (GT_NO_PROBE)."""
    return os.environ.get("GT_NO_PROBE", "") not in ("", "0", "false", "False")


def _view(path):
    """The current platform's stat/glob view of a native path.

    Windows-form paths become /mnt/<drive>/.. on WSL; POSIX paths are used
    as-is. Probing always happens in view space so a single implementation
    serves both platforms."""
    if not path:
        return path
    return to_wsl_path(path) if is_wsl() else _posix(path)


def _in_form(view_path, tool):
    """Convert a view-space hit into the form the caller asked for.

    Paths are normalized to forward slashes (the project's stored form) so
    the mixed separators glob produces on Windows never leak into configs,
    logs or PowerShell command lines."""
    view_path = _posix(view_path)
    if tool.path_form != "windows":
        return view_path
    win = to_windows_path(view_path)
    pw = PureWindowsPath(win)
    # Only re-spell a path that really is a Windows path: a POSIX path (e.g.
    # a hermetic test fixture) must not be mangled into \\tmp\\.. form.
    return str(pw) if pw.drive else win


def _natural_key(text):
    """Sort key that orders version-ish names naturally (v2 before v10), so
    the newest install wins when a probe pattern matches several versions.

    Numeric runs are zero-padded instead of converted to int: every element
    stays a string, so two different paths can never raise TypeError while
    being compared."""
    return [p.zfill(12) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", str(text))]


def _glob_hits(view_pattern):
    """Files matching a view-space glob, newest-looking path first.

    The full path is the sort key (not the file name), because version
    directories live above the binary: WinGet installs as
    ``Packages/<pkg>/<version>/bin/ffmpeg.exe``."""
    try:
        hits = glob.glob(view_pattern)
    except (OSError, re.error):
        return []
    hits.sort(key=_natural_key, reverse=True)
    return [_posix(h) for h in hits if os.path.isfile(h)]


def _anchor_paths(side):
    """View-space directories that `Tool.probe` patterns resolve against.

    Only existing directories are returned, so probing on an unknown machine
    costs a handful of stats.  Windows anchors are also emitted on WSL (as
    literal C:/.. paths) so Windows-side tools stay findable there.  The
    project-local `docs/table/3rd/` bin dir is POSIX-only on purpose: it holds
    the Linux 7zz, while on Windows the installed 7-Zip is probed instead."""
    tokens = []
    if side == "win32":
        tokens += list(_WIN_ANCHOR_TOKENS)
        if not _is_windows_os():
            tokens += list(_WIN_ANCHOR_LITERAL)
    elif _is_windows_os():
        tokens += list(_WIN_ANCHOR_TOKENS)
    else:
        tokens += list(_POSIX_ANCHOR_TOKENS)
        tokens.append(str(REPO_ROOT / "docs" / "table" / "3rd"))
    anchors = []
    for token in tokens:
        view = _view(_expand(token))
        if view and view not in anchors and os.path.isdir(view):
            anchors.append(view)
    return anchors


def _is_windows_os():
    return sys.platform == "win32"


def _probe(tool):
    """Search well-known install locations for `tool`; view-space hit or None."""
    if _probe_disabled():
        return None
    anchors = _anchor_paths(tool.side)
    for anchor in anchors:
        for pattern in tool.probe:
            hits = _glob_hits(os.path.join(anchor, pattern))
            if hits:
                log.debug("probe %s: %s", tool.key, hits[0])
                return hits[0]
    return None


def _config_override(tool):
    """Explicit env_config override for `tool` (may be a glob pattern).

    The value is relative to the config file's own dir when it is relative,
    so the file stays machine-independent.  Returns a view-space path."""
    tools_section = _load_env_config().get("tools")
    section = (_win32_section(tools_section) if tool.side == "win32"
               else _section_platform(tools_section))
    raw = _expand(_pick(section, tool.cfg) or "")
    if not raw:
        return None
    if not raw.startswith("/") and not PureWindowsPath(raw).drive:
        raw = str(LOCAL_ENV_FILE.parent / raw)
    if any(ch in raw for ch in "*?["):
        hits = _glob_hits(_view(raw))
        return hits[0] if hits else None
    view = _view(raw)
    return view if os.path.isfile(view) else None


def _path_lookup(tool):
    """PATH lookup (last resort), in the current platform's view."""
    for name in tool.exe:
        hit = shutil.which(name)
        if hit:
            return hit
    return None


def resolve_tool(tool, with_source=False):
    """Resolve one `Tool` (or registry key) to a usable path.

    Order: environment variable -> explicit env_config value (globs allowed)
    -> probe of well-known install locations -> PATH.  Returns None when the
    application is genuinely absent, so callers can distinguish "found" from
    "not found" (a silent tool-name string would hide the error).

    With `with_source=True` returns ``(path, source)`` where source is one of
    ``env`` / ``config`` / ``probe`` / ``path`` / None - used by the probe
    report so every resolved path can be explained.
    """
    if isinstance(tool, str):
        tool = TOOLS_BY_KEY[tool]

    override = os.environ.get(tool.env)
    if override:
        view = _view(_expand(override))
        if view and os.path.isfile(view):
            return (_in_form(view, tool), "env") if with_source else _in_form(view, tool)

    hit = _config_override(tool)
    if hit:
        return (_in_form(hit, tool), "config") if with_source else _in_form(hit, tool)

    hit = _probe(tool)
    if hit:
        return (_in_form(hit, tool), "probe") if with_source else _in_form(hit, tool)

    hit = _path_lookup(tool)
    if hit:
        return (_in_form(hit, tool), "path") if with_source else _in_form(hit, tool)

    return (None, None) if with_source else None


def find_ffmpeg():
    return resolve_tool("ffmpeg")


def find_ffprobe():
    return resolve_tool("ffprobe")


def find_7z():
    return resolve_tool("7z")


def find_rg():
    return resolve_tool("rg")


def find_git():
    return resolve_tool("git")


def find_npx():
    """Locate the npx launcher (Node.js package runner).

    Single source of truth for both the RPG Maker tooling and
    `tyrano/asar.py` (the asar unpacker used to be its own duplicate)."""
    return resolve_tool("npx")


def find_powershell():
    """Locate PowerShell: POWERSHELL_EXE env -> env_config -> probe -> PATH.

    On WSL this is the /mnt/c/.. view (executable from here); on Windows the
    native Windows path.  Returns None when missing."""
    return resolve_tool("powershell")


def win_7z():
    """Windows-side 7z binary, for processing files stored on the Windows
    side; returned in Windows form (it is handed to PowerShell). None when
    absent."""
    return resolve_tool("win7z")


def run_powershell(command, exe=None):
    """Run `command` in PowerShell (Windows-side operations only).

    Shared by `rpgmaker/deliver.py` and `tools/wsl_capture.py` so the
    interpreter lookup and the failure message live in one place.  Fails
    fast with a cross-system hint when PowerShell is unavailable (e.g. a WSL
    image without WSLInterop installed).
    """
    exe = exe or find_powershell()
    if not exe:
        raise FileNotFoundError(
            "powershell.exe not found - install PowerShell on the Windows "
            "side / 请在 Windows 侧安装 PowerShell")
    r = subprocess.run([exe, "-NoProfile", "-Command", command],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("powershell failed (%s):\n%s"
                           % (r.returncode, (r.stderr or r.stdout)[-2000:]))
    return r


def probe_report():
    """Machine-readable resolution report for every registered tool.

    Returns a list of dicts (key, path, source, purpose, side, hint) so
    `pipeline.py probe` can print the resolved environment instead of anyone
    having to go hunting for install paths by hand.
    """
    report = []
    for tool in TOOLS:
        path, source = resolve_tool(tool, with_source=True)
        report.append({
            "key": tool.key,
            "path": path,
            "source": source,
            "side": tool.side,
            "purpose": tool.purpose,
            "hint": "" if path else tool.hint,
        })
    return report


# ---------------------------------------------------------------- deliverables

def _volume_roots():
    """Native-form filesystem roots to probe for deliverable folders, in
    drive order (C: first) - Windows letters on Windows, /mnt/<letter> on
    WSL. Only existing roots are returned."""
    roots = []
    if _is_windows_os():
        candidates = ["%s:/" % chr(c) for c in range(ord("C"), ord("Z") + 1)]
    elif is_wsl():
        candidates = ["/mnt/%s" % chr(c).lower()
                      for c in range(ord("c"), ord("z") + 1)]
    else:
        candidates = ["/", "/mnt"]
    for cand in candidates:
        if os.path.isdir(_view(cand)):
            roots.append(cand)
    return roots


def _home_dir():
    """Native-form user home directory (Windows or POSIX)."""
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return _expand(home)


def workspace_root():
    """The workspace directory that holds this checkout.

    Deliverables belong next to the sources, so the tool library's own parent
    directory is both the first probe base and the default output root - the
    output folders live beside the repo (`<workspace>/Games`,
    `<workspace>/GamesCompress`) instead of somewhere machine-specific.
    Overridable for tests and exotic layouts."""
    return str(REPO_ROOT.parent)


def _deliverable_bases():
    """Directories whose children are probed for deliverable folders, in
    order: the workspace root first (most specific), then every volume root,
    then $HOME - so an existing conventionally named folder is adopted
    wherever the operator keeps it."""
    bases = [workspace_root()]
    bases.extend(_volume_roots())
    bases.append(_home_dir())
    seen = []
    for base in bases:
        if base and base not in seen:
            seen.append(base)
    return seen


# Candidate folder names probed under every base, in order.  The historical
# convention (Games / GamesCompress beside the workspace) comes first, then
# lowercase / nested variants.  These are RELATIVE names: no machine path
# lives in the repo, the bases above supply the machine-specific part.
_DELIVERABLE_NAMES = {
    "games": ("Games", "games", "GameTranslation/games"),
    "archives": ("GamesCompress", "archives", "GameTranslation/archives"),
}


def _default_output_root():
    """Where deliverables go when nothing was configured and no existing
    folder was probed: the workspace root (created on demand by `deliver`)."""
    return workspace_root()


def _probe_deliverable(kind):
    """First existing conventional deliverable folder, or None.

    Probing means a fresh machine (or a moved drive) keeps working without
    anyone editing a config file: an existing Games/GamesCompress folder is
    adopted, otherwise the caller's default is created on demand."""
    if _probe_disabled():
        return None
    for base in _deliverable_bases():
        for name in _DELIVERABLE_NAMES[kind]:
            cand = os.path.join(base, name)
            if os.path.isdir(_view(cand)):
                log.debug("deliverable %s probed: %s", kind, cand)
                return _expand(cand)
    return None


def _deliverable(env_var, cfg_name, default="", probe=None):
    """Environment variable -> env_config deliverables.<name> -> probe of
    conventional folders -> default.  The stored/default path is native-form
    and gets localized for the current platform.  Plain (scalar) values only:
    the nested deliverables.temp dict is handled by _temp_dir_cfg()."""
    p = os.environ.get(env_var)
    if not p:
        p = _pick(_load_env_config().get("deliverables"), cfg_name)
    if isinstance(p, dict):
        p = None
    if p:
        return localize(_expand(p))
    if probe:
        hit = _probe_deliverable(probe)
        if hit:
            return localize(hit)
    return localize(_expand(default))


def _temp_dir_cfg(key):
    """A deliverables.temp sub-path (persist / tmpfs / win32), accepting
    both the nested dict format {persist, tmpfs, win32} and the legacy
    plain-string format (all keys fall back to the same value)."""
    t = _pick(_load_env_config().get("deliverables"), "temp")
    if isinstance(t, dict):
        p = t.get(key)
    else:
        p = t if isinstance(t, str) else None
    return localize(_expand(p or ""))


def temp_dir():
    """Work directory for temp copies: the persistent large-work dir on
    WSL (deliverables.temp.persist), the Windows %TEMP% on Windows
    (deliverables.temp.win32); the fallback default follows the same
    platform split."""
    wsl = is_wsl()
    return _temp_dir_cfg("persist" if wsl else "win32") \
        or _deliverable("TEMP_DIR", "temp",
                        "/tmp/opencode" if wsl
                        else "%LOCALAPPDATA%/Temp/opencode")


def _note_default_deliverable(env_var, cfg_name, path, probe):
    """Note once where a deliverable folder was derived from when nothing
    was configured and no conventional folder was probed - the operator
    should know where a build is about to land, and how to pin it."""
    if os.environ.get(env_var):
        return
    cfg = _load_env_config().get("deliverables")
    if isinstance(cfg, dict) and cfg.get(cfg_name):
        return
    if probe and _probe_deliverable(probe):
        return
    _note_once(
        "default:%s" % cfg_name,
        "deliverables.%s not configured and no conventional folder found; "
        "using %s (created on demand) - set %s or deliverables.%s to "
        "change it" % (cfg_name, path, env_var, cfg_name))


def _creatable(path):
    """True when `path` can be created on demand: its nearest existing
    ancestor is a writable directory."""
    cur = _view(path)
    while cur and not os.path.exists(cur):
        parent = os.path.dirname(cur.rstrip("/\\"))
        if parent == cur:
            return False
        cur = parent
    return bool(cur) and os.path.isdir(cur) and os.access(cur, os.W_OK)


def games_dir() -> str:
    """Deliverable folder for finished game builds: env GAMES_DIR ->
    deliverables.games -> probed conventional folder -> default
    `<workspace>/Games` (created on demand)."""
    probe = "games"
    p = _deliverable("GAMES_DIR", "games",
                     os.path.join(_default_output_root(),
                                  _DELIVERABLE_NAMES[probe][0]), probe)
    _note_default_deliverable("GAMES_DIR", "games", p, probe)
    return p


def archives_dir() -> str:
    """Deliverable folder for finished game archives: env ARCHIVES_DIR ->
    deliverables.archives -> probed conventional folder -> default
    `<workspace>/GamesCompress` (created on demand)."""
    probe = "archives"
    p = _deliverable("ARCHIVES_DIR", "archives",
                     os.path.join(_default_output_root(),
                                  _DELIVERABLE_NAMES[probe][0]), probe)
    _note_default_deliverable("ARCHIVES_DIR", "archives", p, probe)
    return p


def win_temp_dir() -> str:
    """Windows-side temp for downloads and Windows-only tools (the Windows
    %TEMP% folder; stored native: %LOCALAPPDATA%/Temp, localized to
    /mnt/c/... on WSL).  Reads the nested deliverables.temp.win32 key
    (legacy plain deliverables.win_temp accepted)."""
    p = _temp_dir_cfg("win32")
    if p:
        return p
    return _deliverable("WIN_TEMP_DIR", "win_temp", "%LOCALAPPDATA%/Temp")


# ---------------------------------------------------------------- fonts

# Preferred CJK font for translated builds. Machine paths never live in the
# repo - resolve at runtime:
#   1. env var CJK_FONT_PATH / JP_FONT_PATH
#   2. gitignored local override file docs/table/local_font_path.txt (lines 1/2)
#   3. the bundled fonts dir docs/table/fonts/ (auto-discovered: a SC
#      Simplified-Chinese font for CJK, a J Japanese font as the JP fallback)
#   4. None (caller keeps the plain fallback list)
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
