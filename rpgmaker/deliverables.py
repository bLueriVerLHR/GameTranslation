#!/usr/bin/env python3
"""deliverables.py - where finished builds and archives are written.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).
This module owns exactly one responsibility: resolving the deliverable and
temp folders.

Every folder follows the same layered rule, and the layer a value came from
is reported rather than hidden:

    environment variable -> machine config -> probe of conventional folders
    -> built-in default (created on demand)

``workspace_root`` is read through the :mod:`rpgmaker.workspace` module (not
imported as a value) so redirecting it in one place also redirects the
deliverable defaults - otherwise a test could patch the workspace root and
still see builds land beside the repo.

Probing is what lets a fresh machine - or a moved drive - keep working with
nobody editing a config file: an existing ``Games`` / ``GamesCompress`` folder
is adopted wherever the operator keeps it.  A path is always *stored* in the
native form of the platform that owns it and localized on read, per the
single-native-form convention in :mod:`rpgmaker.platform`.

No machine path lives in the repo: the conventional folder names below are
relative, and the probe bases supply the machine-specific part.
"""
import logging
import os

from . import workspace
from . import platform
from .platform import view  # pure helpers, no platform branching
from .settings import expand_env, load_machine_config, pick

__all__ = [
    "archives_dir",
    "creatable",
    "deliverable_bases",
    "games_dir",
    "probe_deliverable",
    "temp_dir",
    "win_temp_dir",
]

log = logging.getLogger("rpgmaker.deliverables")

# Tags whose once-per-process note was already emitted, so a long batch
# calling games_dir() repeatedly does not repeat the same line.  Module-local
# rather than logsetup's global once-store on purpose: a test resets this
# without disturbing every other once-per-process warning in the process.
_noted_defaults: set[str] = set()


def _note_once(tag, message):
    """Log an INFO note at most once per tag per process.

    "Here is the folder we resolved and why" is useful once and noise on
    every call, which is why this is a note rather than a warning: a derived
    default is normal operation, not a recovered problem.
    """
    if tag in _noted_defaults:
        return
    _noted_defaults.add(tag)
    log.info(message)

# Candidate folder names probed under every base, in order.  The historical
# convention (Games / GamesCompress beside the workspace) comes first, then
# lowercase / nested variants.
_DELIVERABLE_NAMES = {
    "games": ("Games", "games", "GameTranslation/games"),
    "archives": ("GamesCompress", "archives", "GameTranslation/archives"),
}


def _probe_disabled():
    """True when filesystem probing is switched off (``GT_NO_PROBE``)."""
    return os.environ.get("GT_NO_PROBE", "") not in ("", "0", "false", "False")


def _volume_roots():
    """Native-form filesystem roots to probe, in drive order.

    Windows letters on Windows, ``/mnt/<letter>`` on WSL.  Only existing
    roots are returned, so an unprovisioned machine does not pay for stats it
    will not use.
    """
    if platform.is_windows_os():
        candidates = [f"{chr(c)}:/" for c in range(ord("C"), ord("Z") + 1)]
    elif platform.is_wsl():
        candidates = [f"/mnt/{chr(c).lower()}"
                      for c in range(ord("c"), ord("z") + 1)]
    else:
        candidates = ["/", "/mnt"]
    return [cand for cand in candidates if os.path.isdir(view(cand))]


def _home_dir():
    """Native-form user home directory (Windows or POSIX)."""
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return expand_env(home)


def deliverable_bases():
    """Directories whose children are probed for deliverable folders.

    Order: the workspace root first (most specific), then every volume root,
    then ``$HOME`` - so an existing conventionally named folder is adopted
    wherever the operator keeps it, and the most specific match wins.
    """
    bases = [workspace.workspace_root()]
    bases.extend(_volume_roots())
    bases.append(_home_dir())
    seen = []
    for base in bases:
        if base and base not in seen:
            seen.append(base)
    return seen


def _default_output_root():
    """Where deliverables go when nothing was configured and no existing
    folder was probed: the workspace root (created on demand by ``deliver``)."""
    return workspace.workspace_root()


def probe_deliverable(kind):
    """First existing conventional deliverable folder, or None.

    Probing means a fresh machine (or a moved drive) keeps working without
    anyone editing a config file: an existing ``Games``/``GamesCompress``
    folder is adopted, otherwise the caller's default is created on demand.
    """
    if _probe_disabled():
        return None
    for base in deliverable_bases():
        for name in _DELIVERABLE_NAMES[kind]:
            cand = os.path.join(base, name)
            if os.path.isdir(view(cand)):
                log.debug("deliverable %s probed: %s", kind, cand)
                return expand_env(cand)
    return None


def _deliverable(env_var, cfg_name, default="", probe=None):
    """Environment variable -> ``deliverables.<name>`` -> probed folder ->
    default.

    The stored/default path is native-form and gets localized for the current
    platform.  Plain (scalar) values only: the nested ``deliverables.temp``
    dict is handled by :func:`_temp_dir_cfg`.
    """
    p = os.environ.get(env_var)
    if not p:
        p = pick(load_machine_config().section("deliverables"), cfg_name)
    if isinstance(p, dict):
        p = None
    if p:
        return platform.localize(expand_env(p))
    if probe:
        hit = probe_deliverable(probe)
        if hit:
            return platform.localize(hit)
    return platform.localize(expand_env(default))


def _temp_dir_cfg(key):
    """A ``deliverables.temp`` sub-path (``persist`` / ``tmpfs`` / ``win32``).

    Accepts both the nested dict format ``{persist, tmpfs, win32}`` and the
    legacy plain-string format (every key then falls back to the same value).
    """
    t = pick(load_machine_config().section("deliverables"), "temp")
    p = t.get(key) if isinstance(t, dict) else t if isinstance(t, str) else None
    return platform.localize(expand_env(p or ""))


def temp_dir() -> str:
    """Work directory for temp copies.

    The persistent large-work dir on WSL (``deliverables.temp.persist``), the
    Windows ``%TEMP%`` on Windows (``deliverables.temp.win32``); the fallback
    default follows the same platform split.
    """
    wsl = platform.is_wsl()
    return _temp_dir_cfg("persist" if wsl else "win32") \
        or _deliverable("TEMP_DIR", "temp",
                        "/tmp/gametrans" if wsl
                        else "%LOCALAPPDATA%/Temp/gametrans")


def _note_default_deliverable(env_var, cfg_name, path, probe):
    """Note once where a deliverable folder was derived from when nothing was
    configured and no conventional folder was probed.

    The operator should know where a build is about to land, and how to pin
    it - an INFO line once per process, not on every call.
    """
    if os.environ.get(env_var):
        return
    cfg = load_machine_config().section("deliverables")
    if cfg.get(cfg_name):
        return
    if probe and probe_deliverable(probe):
        return
    _note_once(
        f"default:{cfg_name}",
        f"deliverables.{cfg_name} not configured and no conventional folder found; "
        f"using {path} (created on demand) - set {env_var} or deliverables.{cfg_name} to "
        "change it")


def creatable(path) -> bool:
    """True when `path` can be created on demand.

    That means its nearest existing ancestor is a writable directory, which is
    what ``deliver`` needs in order to create the folder lazily.  Reported
    rather than attempted, so ``doctor`` can check without side effects.
    """
    cur = view(path)
    while cur and not os.path.exists(cur):
        parent = os.path.dirname(cur.rstrip("/\\"))
        if parent == cur:
            return False
        cur = parent
    return bool(cur) and os.path.isdir(cur) and os.access(cur, os.W_OK)


def games_dir() -> str:
    """Deliverable folder for finished game builds.

    ``GAMES_DIR`` -> ``deliverables.games`` -> probed conventional folder ->
    default ``<workspace>/Games`` (created on demand).
    """
    probe = "games"
    p = _deliverable("GAMES_DIR", "games",
                     os.path.join(_default_output_root(),
                                  _DELIVERABLE_NAMES[probe][0]), probe)
    _note_default_deliverable("GAMES_DIR", "games", p, probe)
    return p


def archives_dir() -> str:
    """Deliverable folder for finished game archives.

    ``ARCHIVES_DIR`` -> ``deliverables.archives`` -> probed conventional
    folder -> default ``<workspace>/GamesCompress`` (created on demand).
    """
    probe = "archives"
    p = _deliverable("ARCHIVES_DIR", "archives",
                     os.path.join(_default_output_root(),
                                  _DELIVERABLE_NAMES[probe][0]), probe)
    _note_default_deliverable("ARCHIVES_DIR", "archives", p, probe)
    return p


def win_temp_dir() -> str:
    """Windows-side temp for downloads and Windows-only tools.

    The Windows ``%TEMP%`` folder; stored native (``%LOCALAPPDATA%/Temp``),
    localized to ``/mnt/c/...`` on WSL.  Reads the nested
    ``deliverables.temp.win32`` key (legacy plain ``deliverables.win_temp``
    accepted).
    """
    p = _temp_dir_cfg("win32")
    if p:
        return p
    return _deliverable("WIN_TEMP_DIR", "win_temp", "%LOCALAPPDATA%/Temp")
