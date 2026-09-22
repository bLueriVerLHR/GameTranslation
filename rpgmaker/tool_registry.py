#!/usr/bin/env python3
"""tool_registry.py - the one table of external applications, and its resolver.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).
This module owns exactly one responsibility: which external programs the
toolkit may shell out to, and how a usable path is found for each.

Adding an external application therefore means adding one :class:`Tool` entry
to :data:`TOOLS`; the ``find_*`` wrappers, the ``doctor`` report and
``pipeline.py doctor --json`` all read the same table, so no other file needs
to change.  **This is the only place in the repo that looks a program up** -
no other module may call ``shutil.which`` or vend its own search function.

Resolution order, for every tool:

    environment override -> explicit machine-config value (globs allowed)
    -> probe of well-known install locations -> PATH

``GT_NO_PROBE=1`` disables only the filesystem-probing layer (hermetic tests,
locked-down machines), keeping env/config/PATH.
"""
import glob
import logging
import os
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import PureWindowsPath

from . import proctools
from . import platform
from . import settings
from .platform import posix, view  # pure helpers, no platform branching

__all__ = [
    "TOOLS",
    "TOOLS_BY_KEY",
    "Tool",
    "ToolStatus",
    "find_ffmpeg",
    "find_git",
    "find_node",
    "find_powershell",
    "probe_report",
    "resolve_tool",
    "run_powershell",
    "win_7z",
]

log = logging.getLogger("rpgmaker.tool_registry")

# Windows-side PowerShell has to exist before the cross-system bridge can
# work, but it must not hang an unattended run either.
POWERSHELL_TIMEOUT = 3600


class ToolStatus(str, Enum):
    """What role a tool plays, so a missing one can be reported honestly.

    ``REQUIRED``          - a build cannot be completed without it.
    ``OPTIONAL``          - the toolkit degrades to a slower Python fallback.
    ``DEV_ONLY``          - development workflow (repo tooling), never a build.
    ``TEST_ONLY``         - only a test executes it; a build does not need it.
    ``WINDOWS_BRIDGE``    - only the cross-system bridge uses it, and only on
                            the platform that owns the Windows-side bytes.

    ``doctor`` turns a missing tool into WARN or MISS by this value (see
    ``rpgmaker.doctor._is_fatal``), which is why it is data on the entry rather
    than a sentence in a docstring.  ``WINDOWS_BRIDGE`` is the one case doctor
    cannot settle from the status alone: the bridge only exists on WSL, so an
    absent ``powershell.exe`` is a failure there and a non-event on Windows.
    """

    REQUIRED = "required"
    OPTIONAL = "optional"
    DEV_ONLY = "dev-only"
    TEST_ONLY = "test-only"
    WINDOWS_BRIDGE = "windows-bridge"

    @property
    def missing_is_fatal(self) -> bool:
        """Whether an absent tool makes a build fail (vs. degrade)."""
        return self is ToolStatus.REQUIRED


@dataclass(frozen=True)
class Tool:
    """One external application the toolkit may shell out to.

    key          registry key (also the ``tools.<section>.<key>`` name in the
                 machine config unless ``config_key`` overrides it)
    env          environment variable that overrides everything else
    exe          executable names tried by the PATH lookup (in order)
    side         ``"native"`` = belongs to the platform running this code,
                 ``"win32"`` = a Windows-side binary (used to process files
                 that live on the Windows side, see the AGENTS.md CRITICAL
                 rule)
    probe        glob patterns, relative to the probe anchors, tried in
                 order; the newest match wins (version dirs sort naturally)
    path_form    ``"view"`` = return a path executable from *here* (what
                 subprocess needs on this platform), ``"windows"`` = return
                 the Windows-form path (what gets handed to a Windows-side
                 tool / PowerShell command line)
    status       what depends on it (see :class:`ToolStatus`)
    purpose      what needs it - shown by doctor/probe
    hint         what to do when it is missing
    """

    key: str
    env: str
    exe: tuple = ()
    side: str = "native"
    probe: tuple = ()
    path_form: str = "view"
    status: ToolStatus = ToolStatus.REQUIRED
    purpose: str = ""
    hint: str = ""
    config_key: str = ""
    resolver_name: str = ""

    @property
    def cfg(self) -> str:
        return self.config_key or self.key

    @property
    def resolver(self) -> str:
        """Name of the wrapper resolving this tool.

        ``doctor`` calls it through the module, so a test can monkeypatch one
        tool's lookup without touching the resolver itself.
        """
        return self.resolver_name or (f"find_{self.key}")


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
        key="node", env="NODE", exe=("node", "node.exe"),
        probe=("*/nvm/installs/*/node.exe", "nodejs/node.exe"),
        status=ToolStatus.TEST_ONLY,
        purpose="executing generated JavaScript in the KAG runtime tests",
        hint="needed only by tests/test_kag_audio_runtime.py; set NODE or "
             "install Node.js to run that layer",
    ),
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
        status=ToolStatus.REQUIRED,
        purpose="Vorbis encoding for the audio step (media probe is in-process)",
        hint="install ffmpeg (with libvorbis) or set FFMPEG / "
             "config tools.<platform>.ffmpeg",
    ),
    Tool(
        key="git", env="GIT", exe=("git", "git.exe"),
        probe=("Git/cmd/git.exe", "Git/bin/git.exe",
               "Programs/Git/cmd/git.exe"),
        status=ToolStatus.DEV_ONLY,
        purpose="repo versioning / hygiene (development workflow only)",
        hint="only needed for the development workflow, not for conversion",
    ),
    Tool(
        key="powershell", env="POWERSHELL_EXE",
        exe=("powershell.exe", "pwsh.exe"), side="win32",
        probe=("System32/WindowsPowerShell/v1.0/powershell.exe",
               "PowerShell/*/pwsh.exe"),
        status=ToolStatus.WINDOWS_BRIDGE,
        purpose="run Windows-side operations from WSL (deliver, archive handling)",
        hint="install PowerShell on the Windows side / "
             "请在 Windows 侧安装 PowerShell",
    ),
    Tool(
        key="win7z", env="SEVENZ_WIN", exe=("7z.exe", "7z"), side="win32",
        config_key="7z", path_form="windows", resolver_name="win_7z",
        probe=("7-Zip*/7z.exe", "Programs/7-Zip*/7z.exe"),
        status=ToolStatus.WINDOWS_BRIDGE,
        purpose="extract Windows-side (/mnt/*) archives via PowerShell",
        hint="install 7-Zip-Zstandard on Windows or set SEVENZ_WIN / "
             "config tools.win32.7z",
    ),
)

TOOLS_BY_KEY = {t.key: t for t in TOOLS}


def probe_disabled():
    """True when filesystem probing is switched off (``GT_NO_PROBE``)."""
    return os.environ.get("GT_NO_PROBE", "") not in ("", "0", "false", "False")


def _in_form(view_path, tool):
    """Convert a view-space hit into the form the caller asked for.

    Paths are normalized to forward slashes (the project's stored form) so
    the mixed separators glob produces on Windows never leak into configs,
    logs or PowerShell command lines.
    """
    view_path = posix(view_path)
    if tool.path_form != "windows":
        return view_path
    win = platform.to_windows_path(view_path)
    pw = PureWindowsPath(win)
    # Only re-spell a path that really is a Windows path: a POSIX path (e.g.
    # a hermetic test fixture) must not be mangled into \\tmp\\.. form.
    return str(pw) if pw.drive else win


def _natural_key(text):
    """Sort key that orders version-ish names naturally (v2 before v10).

    Numeric runs are zero-padded instead of converted to int: every element
    stays a string, so two different paths can never raise TypeError while
    being compared.
    """
    return [p.zfill(12) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", str(text))]


def _glob_hits(view_pattern):
    """Files matching a view-space glob, newest-looking path first.

    The full path is the sort key (not the file name), because version
    directories live above the binary: WinGet installs as
    ``Packages/<pkg>/<version>/bin/ffmpeg.exe``.
    """
    try:
        hits = glob.glob(view_pattern)
    except (OSError, re.error):
        return []
    hits.sort(key=_natural_key, reverse=True)
    return [posix(h) for h in hits if os.path.isfile(h)]


def _anchor_paths(side):
    """View-space directories that ``Tool.probe`` patterns resolve against.

    Only existing directories are returned, so probing on an unknown machine
    costs a handful of stats.  Windows anchors are also emitted on WSL (as
    literal ``C:/..`` paths) so Windows-side tools stay findable there.
    """
    tokens = []
    if side == "win32":
        tokens += list(_WIN_ANCHOR_TOKENS)
        if not platform.is_windows_os():
            tokens += list(_WIN_ANCHOR_LITERAL)
    elif platform.is_windows_os():
        tokens += list(_WIN_ANCHOR_TOKENS)
    else:
        tokens += list(_POSIX_ANCHOR_TOKENS)
        tokens.append(str(settings.private_path("bin")))
    anchors = []
    for token in tokens:
        v = view(settings.expand_env(token))
        if v and v not in anchors and os.path.isdir(v):
            anchors.append(v)
    return anchors


def _probe(tool):
    """Search well-known install locations for `tool`; view-space hit or None."""
    if probe_disabled():
        return None
    for anchor in _anchor_paths(tool.side):
        for pattern in tool.probe:
            hits = _glob_hits(os.path.join(anchor, pattern))
            if hits:
                log.debug("probe %s: %s", tool.key, hits[0])
                return hits[0]
    return None


def _config_override(tool):
    """Explicit machine-config override for `tool` (may be a glob pattern).

    The value is relative to the config file's own dir when it is relative,
    so the file stays machine-independent.  Returns a view-space path.
    """
    tools_section = settings.load_machine_config().section("tools")
    section = (settings.win32_section(tools_section) if tool.side == "win32"
               else settings.section_platform(tools_section))
    raw = settings.expand_env(settings.pick(section, tool.cfg) or "")
    if not raw:
        return None
    if not raw.startswith("/") and not PureWindowsPath(raw).drive:
        raw = str(settings.LOCAL_ENV_FILE.parent / raw)
    if any(ch in raw for ch in "*?["):
        hits = _glob_hits(view(raw))
        return hits[0] if hits else None
    v = view(raw)
    return v if os.path.isfile(v) else None


def _path_lookup(tool):
    """PATH lookup (last resort), in the current platform's view."""
    for name in tool.exe:
        hit = shutil.which(name)
        if hit:
            return hit
    return None


def resolve_tool(tool, with_source=False):
    """Resolve one :class:`Tool` (or registry key) to a usable path.

    Order: environment variable -> explicit machine config (globs allowed)
    -> probe of well-known install locations -> PATH.  Returns None when the
    application is genuinely absent, so callers can distinguish "found" from
    "not found" (returning the tool *name* instead would hide the error until
    the subprocess fails).

    With ``with_source=True`` returns ``(path, source)`` where source is one
    of ``env`` / ``config`` / ``probe`` / ``path`` / None - used by the probe
    report so every resolved path can be explained.
    """
    if isinstance(tool, str):
        tool = TOOLS_BY_KEY[tool]

    override = os.environ.get(tool.env)
    if override:
        v = view(settings.expand_env(override))
        if v and os.path.isfile(v):
            return (_in_form(v, tool), "env") if with_source else _in_form(v, tool)

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


def find_git():
    return resolve_tool("git")


def find_node():
    """JavaScript runtime - used by the KAG audio runtime tests only.

    Syntax checking is in-process (``rpgmaker.jssyntax``) and app.asar is read
    by the ``asar`` package, so no tool needs Node.js any more; the remaining
    user is ``tests/test_kag_audio_runtime.py``, which really does have to
    execute the generated JavaScript to observe its runtime behaviour.
    """
    return resolve_tool("node")


def find_powershell():
    """Locate PowerShell: ``POWERSHELL_EXE`` -> config -> probe -> PATH.

    On WSL this is the ``/mnt/c/..`` view (executable from here); on Windows
    the native Windows path.  Returns None when missing.
    """
    return resolve_tool("powershell")


def win_7z():
    """Windows-side 7z binary, for processing files stored on the Windows
    side; returned in Windows form (it is handed to PowerShell).  None when
    absent."""
    return resolve_tool("win7z")


def run_powershell(command, exe=None):
    """Run `command` in PowerShell (Windows-side operations only).

    Shared by the Windows-side bridge (``rpgmaker/deliver.py``) so the
    interpreter lookup and the failure message live in one place.  Fails fast
    with a cross-system hint when PowerShell is unavailable (e.g. a WSL image
    without WSLInterop installed).
    """
    exe = exe or find_powershell()
    if not exe:
        raise FileNotFoundError(
            "powershell.exe not found - install PowerShell on the Windows "
            "side / 请在 Windows 侧安装 PowerShell")
    r = proctools.run([exe, "-NoProfile", "-Command", command],
                      timeout=POWERSHELL_TIMEOUT, label="powershell",
                      check=False)
    if r.returncode != 0:
        raise RuntimeError(f"powershell failed ({r.returncode}):\n{proctools.tail(r)}")
    return r


def probe_report():
    """Machine-readable resolution report for every registered tool.

    Returns a list of dicts so ``pipeline.py doctor --json`` can print the
    resolved environment instead of anyone hunting for install paths by hand.
    Each row is ``{key, path, source, side, status, purpose, hint}``; the key
    set is part of the stable ``doctor --json`` contract.
    """
    report = []
    for tool in TOOLS:
        path, source = resolve_tool(tool, with_source=True)
        report.append({
            "key": tool.key,
            "path": path,
            "source": source,
            "side": tool.side,
            "status": tool.status.value,
            "purpose": tool.purpose,
            "hint": "" if path else tool.hint,
        })
    return report
