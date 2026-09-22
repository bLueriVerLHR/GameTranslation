#!/usr/bin/env python3
"""settings.py - the local private-data layout and the machine config.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).
This module owns exactly one responsibility: where a *gitignored* local
resource lives, and what the optional machine config in it says.

``docs/reference/local-layout.md`` is the authoritative prose; this file is
the only place in the repo that knows the physical layout, so the owner can
move private data without anything grepping for path strings.

Nothing here is mandatory configuration.  A missing, corrupt or wrongly
shaped machine config simply means "use probing and built-in defaults"; every
failure is reported (so ``doctor`` can surface it) but never raised at import
time, and never silently degrades into a different layout.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .platform import platform_key, posix

__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "KNOWN_SECTIONS",
    "LEGACY_PRIVATE_ROOT",
    "LOCAL_ENV_FILE",
    "PRIVATE_PATHS",
    "PRIVATE_ROOT",
    "MachineConfig",
    "PrivateLocation",
    "expand_env",
    "load_machine_config",
    "migration_status",
    "pick",
    "private_dir",
    "private_path",
    "section_platform",
    "win32_section",
]

log = logging.getLogger("rpgmaker.settings")

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------- local private data

@dataclass(frozen=True)
class PrivateLocation:
    """One logical local-data location and its two possible spellings.

    ``current`` is the layout the project is moving to; ``legacy`` is the
    pre-migration path, honoured as a **read-only** fallback so both
    generations work from the same checkout.  ``legacy`` is None for data
    that never lived in the old tree.

    Dropping the legacy spelling once the owner has moved the files is the
    only edit needed to finish the migration - which is why the fallback is a
    data column here rather than a branch somewhere in the code.
    """

    current: str
    legacy: str | None = None
    kind: str = "dir"


# Logical locations of gitignored local data.  Every other module asks for
# one of these by name; none of them concatenates a local path.
PRIVATE_PATHS = {
    "dictionaries": PrivateLocation(".private/dictionaries"),
    "secrets": PrivateLocation(".private/secrets"),
    "fonts": PrivateLocation(".asset/fonts", "docs/table/fonts"),
    "bin": PrivateLocation(".tools/bin", "docs/table/3rd"),
    "env-config": PrivateLocation(
        ".private/config/environment.json", "docs/table/env_config.json",
        kind="file"),
    "font-paths": PrivateLocation(
        ".private/config/local_font_path.txt", "docs/table/local_font_path.txt",
        kind="file"),
}

# Roots the two layouts are relative to.  ``.private/`` and ``.asset/`` are
# siblings of ``.tools/``; the legacy layout was a single ``docs/table/``
# tree, which is why the legacy spellings above repeat that prefix.
PRIVATE_ROOT = REPO_ROOT / ".private"
LEGACY_PRIVATE_ROOT = REPO_ROOT / "docs" / "table"


def private_path(key, repo_root=None) -> Path:
    """Resolve a logical private-data location; returns a ``Path``.

    ``repo_root`` anchors the lookup to another checkout or tree (a test may
    embed its own); the default is this installation's repository root.

    The result is the current layout unless it does not exist *and* the
    legacy one does - so an unmigrated checkout keeps working, and a
    half-migrated one resolves each key independently.  Callers never branch
    on which generation won: that is an implementation detail of the
    migration, not something a module should know.
    """
    try:
        loc = PRIVATE_PATHS[key]
    except KeyError:
        # Re-raised as a diagnostic message; the original KeyError only
        # repeated the key, so there is no cause worth chaining.
        raise KeyError(f"unknown private location {key!r} (see PRIVATE_PATHS)") from None
    root = Path(repo_root) if repo_root else REPO_ROOT
    here = root / loc.current
    if loc.legacy is None or here.exists():
        return here
    previous = root / loc.legacy
    return previous if previous.exists() else here


def private_dir(key, *parts, repo_root=None) -> Path:
    """``private_path(key)`` with extra path components appended."""
    return private_path(key, repo_root=repo_root).joinpath(*parts)


def migration_status(repo_root=None) -> list:
    """Which private locations still resolve through the legacy tree.

    Reported by ``doctor`` so a half-finished migration is visible instead of
    surfacing later as "the font policy silently did not apply".  Returns one
    dict per key: ``key``, ``path``, ``source`` (``current`` / ``legacy`` /
    ``missing``) and ``legacy_available``.
    """
    root = Path(repo_root) if repo_root else REPO_ROOT
    report = []
    for key, loc in sorted(PRIVATE_PATHS.items()):
        here = root / loc.current
        previous = root / loc.legacy if loc.legacy else None
        if here.exists():
            source = "current"
        elif previous is not None and previous.exists():
            source = "legacy"
        else:
            source = "missing"
        report.append({
            "key": key,
            "path": str(private_path(key, repo_root=repo_root)),
            "source": source,
            "legacy_available": bool(previous is not None and previous.exists()),
        })
    return report


LOCAL_ENV_FILE = private_path("env-config")


# ---------------------------------------------------------------- machine config

# Bumped when the machine config grows a key whose absence changes behaviour;
# a file declaring a NEWER version than this build understands is reported
# rather than partially honoured.
CONFIG_SCHEMA_VERSION = 1

# Sections this build understands.  An unknown section is a reportable
# problem (a typo would otherwise be an invisible no-op), not an error: the
# file is an override layer and must stay forward-compatible.
KNOWN_SECTIONS = frozenset({"version", "tools", "deliverables"})


@dataclass(frozen=True)
class MachineConfig:
    """An optional local override file, plus what was wrong with it.

    ``raw`` is the validated mapping (empty when there was no usable file);
    ``problems`` is a tuple of human-readable defects for ``doctor``.  The
    object is deliberately total: every failure mode yields an empty ``raw``
    and a populated ``problems``, so a caller can never end up with a
    half-applied config.
    """

    path: Path
    raw: dict = field(default_factory=dict)
    problems: tuple = ()
    present: bool = False
    version: int = CONFIG_SCHEMA_VERSION

    @property
    def ok(self) -> bool:
        return not self.problems

    def section(self, name):
        """One top-level section, or ``{}`` when absent/not a mapping."""
        value = self.raw.get(name)
        return value if isinstance(value, dict) else {}


def _validate(raw, path):
    """Validate a parsed machine config; returns ``(mapping, problems)``."""
    if not isinstance(raw, dict):
        return {}, (f"{path}: top level must be a JSON object",)
    problems = []
    version = raw.get("version")
    if version is not None:
        if not isinstance(version, int) or isinstance(version, bool):
            problems.append(f"{path}: 'version' must be an integer")
        elif version > CONFIG_SCHEMA_VERSION:
            problems.append(
                "%s: version %d is newer than this build understands (%d)"
                % (path, version, CONFIG_SCHEMA_VERSION))
    problems.extend(f"{path}: unknown section {name!r}" for name in sorted(raw)
                    if name not in KNOWN_SECTIONS)
    for name in ("tools", "deliverables"):
        value = raw.get(name)
        if value is not None and not isinstance(value, dict):
            problems.append(f"{path}: {name!r} must be a JSON object")
    return raw, tuple(problems)


def load_machine_config(path=None) -> MachineConfig:
    """Read and validate the machine config; never raises.

    A missing file is normal (``present=False``, no problems).  A corrupt or
    wrongly shaped file yields ``problems`` and an empty mapping, because
    acting on half a config is worse than falling back to probing: the
    operator would get a silently different layout from the one they wrote.
    """
    path = Path(path) if path is not None else LOCAL_ENV_FILE
    if not path.is_file():
        return MachineConfig(path=path, present=False)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return MachineConfig(path=path, present=True,
                             problems=(f"{path}: cannot read ({exc})",))
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        return MachineConfig(path=path, present=True,
                             problems=(f"{path}: invalid JSON ({exc})",))
    raw, problems = _validate(parsed, path)
    version = raw.get("version")
    if problems:
        # Acting on half a config is worse than falling back to probing: the
        # operator would get a silently different layout from the one they
        # wrote.  So a file with any problem contributes NOTHING, and the
        # problems are what doctor reports.
        raw = {}
    return MachineConfig(
        path=path, raw=raw, problems=problems, present=True,
        version=version if isinstance(version, int) else CONFIG_SCHEMA_VERSION,
    )


def pick(section, name):
    """Return a config value by name (plain values only)."""
    if not isinstance(section, dict):
        return None
    return section.get(name)


def section_platform(section):
    """Pick the current platform's sub-dict of a platform-first section.

    ``{wsl: {...}, win32: {...}}`` selects by :func:`platform_key`; a plain
    section (no platform keys) is returned unchanged, which is what keeps a
    single-platform config file readable.
    """
    if not isinstance(section, dict):
        return {}
    if not any(k in section for k in ("wsl", "win32", "linux")):
        return section
    for key in (platform_key(), "linux", "wsl", "win32"):
        if isinstance(section.get(key), dict):
            return section[key]
    return {}


def win32_section(section):
    """The win32 sub-dict of a platform-first section.

    Windows-only tools live there and must be findable regardless of the
    current platform, which is why this does not go through
    :func:`section_platform`.
    """
    if not isinstance(section, dict):
        return {}
    sub = section.get("win32")
    return sub if isinstance(sub, dict) else {}


def expand_env(path):
    """Expand ``%VAR%`` tokens and normalize separators for cross-platform
    use.

    Unknown tokens are left verbatim, so an unresolvable Windows path stays
    visibly unresolvable instead of silently collapsing to a relative one.
    """
    if not path:
        return path
    path = re.sub(r"%([^%]+)%",
                  lambda m: os.environ.get(m.group(1), m.group(0)), path)
    return posix(path)
