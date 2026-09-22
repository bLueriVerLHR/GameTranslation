#!/usr/bin/env python3
"""platform.py - which platform we run on, and how a path is spelled there.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).
This module owns exactly one responsibility: the platform axis.

Every path in the project is stored ONCE, in the native form of the platform
that owns the resource (Windows resources as ``C:/..``/``D:/..``, POSIX
resources as ``/tmp/..``).  The helpers here map such a stored path to the
view of the current platform, and :class:`PathRef` carries that ownership
explicitly instead of passing bare strings between layers.

The rule this encodes is CRITICAL in ``AGENTS.md``: a file on the Windows
side must be processed by a Windows-side tool, never by a WSL-native one.
:func:`is_windows_side` is the predicate the archive handling uses to enforce
it, and :func:`side_of` / :class:`PathRef` are what let a write operation
check ownership once at its entrance rather than re-deriving it per call.
"""
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = [
    "CrossSideError",
    "PathDomain",
    "PathRef",
    "SideReport",
    "StorageSide",
    "check_same_side",
    "display_path",
    "domain_of",
    "is_windows_os",
    "is_windows_side",
    "is_wsl",
    "localize",
    "platform_key",
    "posix",
    "ref",
    "require_same_side",
    "require_native_paths",
    "resolve_ref",
    "side_of",
    "to_windows_path",
    "to_wsl_path",
    "view",
]


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


def is_windows_os() -> bool:
    """True when the interpreter itself runs on Windows (not WSL)."""
    return sys.platform == "win32"


def platform_key() -> str:
    """Current platform key used inside the private machine config."""
    if is_wsl():
        return "wsl"
    if is_windows_os():
        return "win32"
    return "linux"


def posix(path) -> str:
    """Normalize a path to forward-slash form.

    Accepts Windows and POSIX separators via pathlib, so no call site does
    manual separator replacement."""
    return PureWindowsPath(str(path)).as_posix()


def display_path(path, root=None) -> str:
    """A log-friendly spelling of `path`: relative to `root`, else absolute.

    Never call bare ``os.path.relpath(path)``: a one-argument relpath resolves
    against ``os.getcwd()``, and on Windows the CWD can sit on a different
    drive than the path (CI checks out to ``D:`` while ``tempfile`` hands out
    ``C:``), which raises ``ValueError: path is on mount 'C:', start on mount
    'D:'``.  Measured on the Windows CI runner before this helper existed.

    Falls back to the absolute spelling when the two paths are not relative
    to each other for any reason, so a log line can never break a build.

    Without a `root` the path is returned unchanged: that keeps the helper
    CWD-independent, so calling it can never depend on where the process
    happens to have been started.
    """
    text = str(path)
    if root is None:
        return text
    try:
        relative = os.path.relpath(text, str(root))
    except ValueError:
        return text
    # A path on another drive/mount has no meaningful ".." spelling; keep the
    # absolute form rather than a chain of parent traversals nothing can read.
    return text if relative.startswith(os.pardir) else relative


def is_windows_side(path) -> bool:
    """True when `path` points at a Windows-side file from inside WSL.

    Windows-side files (``/mnt/*``) must be processed by the Windows-side
    tools only - WSL-native tools (7zz, python) touching them is forbidden
    (AGENTS.md, "cross-system file handling" CRITICAL rule).  Outside WSL
    this is always False, because there is no other side to be on.
    """
    if not is_wsl():
        return False
    return side_of(path) is StorageSide.WINDOWS


def to_windows_path(path) -> str:
    """Convert a ``/mnt/<drive>/...`` path to Windows form (``D:\\...``);
    anything else is returned unchanged."""
    parts = PurePosixPath(posix(path)).parts
    if len(parts) < 3 or parts[1] != "mnt" or not _is_drive_letter(parts[2]):
        return str(path)
    # the drive-root segment is spelled as a separate part (pathlib
    # semantics, not string joining) so /mnt/d itself maps to D:\ too.
    return str(PureWindowsPath(parts[2].upper() + ":", "\\", *parts[3:]))


def _is_drive_letter(text) -> bool:
    """True for a single ASCII letter (``c``, ``D``) - a Windows drive.

    Guards both mount conversions: ``/mnt/cc`` is a directory named ``cc``
    on a POSIX box rather than a Windows mount, and a UNC path's ``drive``
    is the host/share rather than a letter, so neither may be rewritten into
    drive form (nor mangled into a bogus mount path).
    """
    return len(text) == 1 and text.isascii() and text.isalpha()


def to_wsl_path(path) -> str:
    """Map a Windows-form path (``C:\\...`` or ``/mnt/...``) to the WSL
    mount view (``/mnt/c/...``) so it can be stat/read from WSL.

    The result is always in POSIX form (assembled from path parts, not
    through ``os.sep``), so the helper behaves identically whether it runs on
    WSL or on Windows.  Relative inputs are returned unchanged.
    """
    pw = PureWindowsPath(str(path))
    if not pw.drive:
        return str(path)
    drive = pw.drive[0].lower()
    # A UNC path has no WSL mount, so it is returned as stored rather than
    # mangled into a bogus mount path.
    if not _is_drive_letter(drive):
        return str(path)
    tail = "/".join(pw.parts[1:])
    return f"/mnt/{drive}/{tail}" if tail else f"/mnt/{drive}"


def localize(path):
    """Map a stored native path to the current platform's view.

    A path is stored ONCE, in the form of the platform where the resource
    physically lives (Windows-side resources as ``C:/..`` or ``D:/..``,
    WSL-side resources as ``/tmp/..``).  On WSL a Windows-form path is
    converted to its ``/mnt/<drive>/..`` view; on Windows a ``/mnt/..`` path
    is converted back.  Paths already in the current platform's form pass
    through unchanged.
    """
    if not path:
        return path
    return to_wsl_path(path) if is_wsl() else to_windows_path(path)


def view(path):
    """The current platform's stat/glob view of a stored path.

    Windows-form paths become ``/mnt/<drive>/..`` on WSL; POSIX paths are
    used as-is.  Probing always happens in view space, so a single
    implementation serves both platforms.
    """
    if not path:
        return path
    return to_wsl_path(path) if is_wsl() else posix(path)


# Pre-split private spellings, kept importable inside the package so the
# modules that already use them did not have to change in the same commit.
_posix = posix
_view = view


# ------------------------------------------------- same-side write guard

class CrossSideError(RuntimeError):
    """A declared path set mixes storage sides (AGENTS.md CRITICAL rule).

    A :class:`RuntimeError` subclass so callers that already catch
    ``RuntimeError`` keep working - the class exists so a caller can trap the
    ownership failure specifically instead of matching on a message.
    """

    def __init__(self, what, detail):
        self.what = what
        self.detail = detail
        super().__init__(f"refusing to {what}: {detail}")


@dataclass(frozen=True)
class SideReport:
    """Structured diagnostic for one declared path set.

    ``ok`` is the whole answer; ``offenders`` names the paths that disagree
    with the majority side, so a report can point at the actual mistake
    instead of only saying "mismatch".
    """

    ok: bool
    sides: dict = field(default_factory=dict)
    offenders: tuple = ()
    detail: str = ""

    def require(self, what):
        """Raise :class:`CrossSideError` unless the set is same-side."""
        if not self.ok:
            raise CrossSideError(what, self.detail)
        return True


def check_same_side(paths) -> SideReport:
    """Check that every named path in `paths` belongs to one storage side.

    `paths` is a mapping of role -> path (``{"archive": a, "dest": d}``), so
    a diagnostic can name the role rather than a bare value.  Called at the
    ENTRANCE of every write operation: a handler about to run a WSL-native
    tool over a Windows-side file must fail *before* doing any work, which is
    the acceptance criterion of PLAN Phase 4.

    A role whose side cannot be derived (a relative path, or anything
    classified :class:`StorageSide.NATIVE`) is ignored rather than guessed:
    guessing a side for a relative path is exactly the mistake the CRITICAL
    rule punishes, and this function is not given the base to resolve it
    against.
    """
    paths = dict(paths)
    sides = {}
    for role, value in paths.items():
        if value is None:
            continue
        side = side_of(value)
        if side is StorageSide.NATIVE:
            continue
        sides[role] = side
    if len(set(sides.values())) <= 1:
        return SideReport(ok=True, sides=sides)
    # The majority side is what the caller intended; the others are the
    # mistake, and naming them is the difference between a fixable message
    # and a hunt.
    counts: dict[StorageSide, int] = {}
    for side in sides.values():
        counts[side] = counts.get(side, 0) + 1
    expected = max(sorted(counts, key=str), key=lambda s: counts[s])
    offenders = tuple(
        f"{role}={paths[role]} ({sides[role].value})"
        for role in sorted(sides) if sides[role] is not expected)
    detail = (
        "a file and the tool processing it must live on the same platform "
        "(AGENTS.md CRITICAL cross-system rule); the declared set mixes "
        "storage sides - expected {}-side: {}".format(expected.value, ", ".join(offenders)))
    return SideReport(ok=False, sides=sides, offenders=offenders,
                      detail=detail)


def require_same_side(what, **paths) -> SideReport:
    """`check_same_side` + raise; returns the passing report.

    Sugar for the common call shape::

        platform.require_same_side("extract", archive=archive, dest=dest)
    """
    report = check_same_side(paths)
    report.require(what)
    return report


# ------------------------------------------------------- ownership types

class StorageSide(str, Enum):
    """Which storage a path physically lives on.

    ``WINDOWS`` - the bytes live on the Windows filesystem (spelled
    ``C:/..``, or reached as ``/mnt/c/..`` from WSL).  Only Windows-side
    tools may process it.
    ``POSIX``   - the bytes live on a POSIX filesystem (WSL ``/tmp``,
    ``/home``, a Linux container).
    ``NATIVE``  - the side this process runs on.  This is the answer for a
    relative path, which cannot be classified without a base: guessing a
    side for it is exactly the mistake the CRITICAL rule punishes.
    """

    WINDOWS = "windows"
    POSIX = "posix"
    NATIVE = "native"


class PathDomain(str, Enum):
    """Coarse classification of how a path is *spelled*.

    Used for diagnostics and for the path property tests.  It is deliberately
    not a behavioural switch: which handler to use comes from
    :class:`StorageSide`, so a path cannot change behaviour just by being
    written with a different separator.
    """

    WINDOWS_DRIVE = "windows-drive"
    WINDOWS_UNC = "windows-unc"
    WSL_MOUNT = "wsl-mount"
    POSIX = "posix"
    RELATIVE = "relative"
    EMPTY = "empty"
    EXOTIC = "exotic"


def _is_unc_path(text) -> bool:
    """True for a UNC path: a *double* separator with a host after it.

    ``\\\\host\\share`` and ``//host/share`` are both UNC - the separator
    style is not what makes a path UNC.  The bare ``//`` and ``\\\\\\\\`` are
    NOT (there is no host to name), which is why two characters used to be
    enough to disagree with the property test that pins relative/exotic
    paths to a derivable ``NATIVE`` side.
    """
    return bool(text.replace("\\", "/").strip("/"))


def domain_of(path) -> PathDomain:
    """Classify a path spelling; never raises, never touches the filesystem.

    Safe to call on unvalidated operator input, which is why it is pure: a
    classification that could fail would have to be wrapped in try/except at
    every call site, and an unclassifiable path is reported as ``EXOTIC``
    rather than coerced into a known form.
    """
    text = "" if path is None else str(path)
    if not text.strip():
        return PathDomain.EMPTY
    if text.startswith(("\\\\", "//")):
        if not _is_unc_path(text):
            # A bare separator run names no host at all: nothing can be
            # derived from it, so it must not be reported as Windows-side.
            return PathDomain.EXOTIC
        # ``//wsl$/...`` is the Windows view of a POSIX path; the domain is
        # still UNC (it is spelled as a share) but the *side* is POSIX.
        return PathDomain.WINDOWS_UNC
    if PureWindowsPath(text).drive:
        return PathDomain.WINDOWS_DRIVE
    parts = PurePosixPath(posix(text)).parts
    if not parts or not text.startswith("/"):
        return PathDomain.RELATIVE
    if (len(parts) >= 3 and parts[1] == "mnt" and _is_drive_letter(parts[2])):
        return PathDomain.WSL_MOUNT
    return PathDomain.POSIX


def side_of(path) -> StorageSide:
    """The storage side a *stored* path belongs to.

    A WSL mount path belongs to ``WINDOWS``: the bytes really live on the
    Windows filesystem, which is the whole point of the CRITICAL rule.  A
    recognised Windows form is ``WINDOWS`` too.  Everything else that is
    classified is ``POSIX``; a relative or exotic path has no derivable side
    and is reported as ``NATIVE``.
    """
    if isinstance(path, PathRef):
        return path.side
    text = posix(path).lower()
    if text.startswith(("//wsl$/", "//wsl.localhost/")):
        return StorageSide.POSIX
    domain = domain_of(path)
    if domain in (PathDomain.WINDOWS_DRIVE, PathDomain.WINDOWS_UNC,
                  PathDomain.WSL_MOUNT):
        return StorageSide.WINDOWS
    if domain is PathDomain.POSIX:
        return StorageSide.POSIX
    return StorageSide.NATIVE


@dataclass(frozen=True)
class PathRef:
    """A path that knows which storage side owns it.

    Critical inputs (archive, extraction target, work directory) carry their
    ownership through the call chain instead of being reduced to a bare
    string that a later layer has to re-classify — re-classifying is where
    the cross-system rule gets violated by accident.

    ``stored`` keeps the original spelling verbatim, so round-tripping never
    rewrites a path the operator typed.  Every accessor is a pure function of
    ``stored`` plus the current platform, which keeps the object cheap and
    safe to hash and compare.
    """

    stored: str
    side: StorageSide = StorageSide.NATIVE

    # -- constructors ---------------------------------------------------

    @classmethod
    def parse(cls, path) -> "PathRef":
        """Classify a stored path into an owned reference."""
        if isinstance(path, cls):
            return path
        return cls("" if path is None else os.fspath(path), side_of(path))

    @classmethod
    def windows(cls, path) -> "PathRef":
        """A reference known (not guessed) to be Windows-side."""
        return cls(str(path), StorageSide.WINDOWS)

    @classmethod
    def posix(cls, path) -> "PathRef":
        """A reference known (not guessed) to be POSIX-side."""
        return cls(str(path), StorageSide.POSIX)

    # -- classification -------------------------------------------------

    @property
    def domain(self) -> PathDomain:
        return domain_of(self.stored)

    @property
    def is_windows(self) -> bool:
        """True when the bytes live on the Windows side.

        Independent of the current platform: a ``/mnt/c/..`` path is Windows
        side even though this process can open it.  This is the predicate the
        archive handlers check before running a WSL-native tool.
        """
        return self.side is StorageSide.WINDOWS

    @property
    def needs_windows_tool(self) -> bool:
        """True when only a Windows-side tool may process this path.

        False on Windows itself (every local tool is a Windows tool there),
        True on WSL for Windows-side bytes — the case the CRITICAL rule is
        about.
        """
        return self.is_windows and not is_windows_os()

    # -- spellings ------------------------------------------------------

    def windows_form(self) -> str:
        """Stored path spelled the way a Windows tool expects it."""
        if self.domain is PathDomain.WINDOWS_DRIVE:
            return str(PureWindowsPath(self.stored))
        return to_windows_path(self.stored)

    def wsl_form(self) -> str:
        """Stored path spelled as the WSL mount view (``/mnt/c/..``)."""
        if self.domain is PathDomain.WSL_MOUNT:
            return posix(self.stored)
        return to_wsl_path(self.stored)

    def view(self) -> str:
        """Stored path spelled so this interpreter can stat/open it."""
        return view(self.stored)

    def for_side(self, tool_side: str) -> str:
        """Spelling a handler whose ``Tool.side`` is `tool_side` needs.

        ``"win32"`` handlers are handed Windows form; ``"native"`` handlers
        the form executable from here.  Centralising this is what stops each
        call site from re-deriving the spelling and getting one case wrong.
        """
        return self.windows_form() if tool_side == "win32" else self.view()

    def exists(self) -> bool:
        """Whether the path exists in this platform's view."""
        return os.path.exists(self.view())

    def __str__(self) -> str:
        return self.stored

    def __fspath__(self) -> str:
        return self.view()


def ref(path) -> PathRef:
    """Shorthand for :meth:`PathRef.parse`."""
    return PathRef.parse(path)


def resolve_ref(path) -> PathRef:
    """Resolve relative paths and links before choosing an I/O handler.

    Inspecting path metadata is allowed; opening file contents is not. Foreign
    absolute spellings must not be reinterpreted relative to this host's cwd.
    """
    owned = ref(path)
    if not owned.stored.strip() or "\x00" in owned.stored:
        raise ValueError("I/O path must be nonempty and contain no NUL")
    native = StorageSide.POSIX if is_wsl() or not is_windows_os() else StorageSide.WINDOWS
    if owned.side not in (StorageSide.NATIVE, native):
        return owned
    resolved = Path(localize(owned.stored)).resolve()
    return ref(resolved)


def require_native_paths(what, **paths) -> dict[str, PathRef]:
    """Return owned paths only if this interpreter may process ALL of them.

    Unlike check_same_side, this compares paths to the processor, not merely
    to each other. It resolves relative paths and symlinks so a cwd or linked
    parent on the other storage side cannot bypass the gate.
    """
    native = StorageSide.POSIX if is_wsl() or not is_windows_os() else StorageSide.WINDOWS
    owned = {role: resolve_ref(path) for role, path in paths.items()}
    offenders = tuple(
        f"{role}={path} ({path.side.value})" for role, path in owned.items()
        if path.side is not native or is_windows_side(str(path)))
    report = SideReport(
        ok=not offenders, sides={role: path.side for role, path in owned.items()},
        offenders=offenders,
        detail=(f"AGENTS.md CRITICAL cross-system rule: {native.value}-side "
                f"processor cannot handle {', '.join(offenders)}; use a tool "
                "on the storage side or copy a single archive first"))
    report.require(what)
    return owned
