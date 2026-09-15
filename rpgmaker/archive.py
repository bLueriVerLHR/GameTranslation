#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""archive.py - the single 7z surface: create / test / list / extract.

Two backends, chosen by *where the files are*, never by preference:

* **py7zr** (in-process, the default).  No external binary, no argv building,
  no stdout parsing.  Writes the delivery format with the ZStandard filter;
  integrity is py7zr's own CRC pass (`testzip()`).
  Why it replaced the 7-Zip CLI as the default - measured on a 265 MB /
  3009-file game-like tree (`-mx=15` / zstd level 15):

      engine                              wall     archive   read by 7z.exe
      7z.exe a -t7z -m0=zstd -mmt=on     5.3 s    251.7 MB        -
      py7zr (FILTER_ZSTD, level 15)      3.1 s    251.7 MB       yes

  Same size (7z.exe reports ``Method = ZSTD`` for the py7zr archive), same
  container, 1.7x faster, and no external tool to resolve.

* **7-Zip CLI** (``proctools``) for the Windows-side bridge only.  AGENTS.md's
  CRITICAL cross-system rule forbids a WSL-native process from writing a
  Windows-side (``/mnt/*``) tree, so ``deliver`` still hands those paths to
  ``7z.exe`` through ``powershell.exe``.  ``extract()`` refuses such a
  destination and points at that bridge instead of silently violating the
  rule.

Both backends read each other's archives (verified both directions), so the
choice is invisible to callers and to the owner's tooling.
"""
import logging
import os

from . import config

log = logging.getLogger("rpgmaker.archive")

SUFFIX = ".7z"
DEFAULT_LEVEL = 15


def _py7zr():
    """Import py7zr lazily with an actionable error (it is a declared dep)."""
    try:
        import py7zr
    except ImportError as exc:  # pragma: no cover - packaging error
        raise RuntimeError(
            "py7zr is required for 7z archives - install it with "
            "`pip install py7zr` (or `pip install -e .` in this repo)") from exc
    return py7zr


def filters_for(level=DEFAULT_LEVEL):
    """py7zr filter chain for the delivery format: plain ZStandard.

    `level` maps 1:1 onto zstd's compression level (the same number the old
    ``-mx`` passed to 7z.exe), so existing ``--level`` values keep meaning.
    """
    py7zr = _py7zr()
    return [{"id": py7zr.FILTER_ZSTD, "level": int(level)}]


def create(folder, archive, level=DEFAULT_LEVEL, threads=None, wrapper=True):
    """Create `archive` (7z + zstd) from `folder`; returns the archive path.

    The folder is stored under its own basename, which is what the previous
    ``7z a <archive> <folder>`` did and what ``deliver`` expects to extract.
    Pass ``wrapper=False`` to store the folder's *contents* at the archive root
    instead: that is the shape a device-side importer wants (JoiPlay opens an
    archive whose root holds ``index.html``) and the shape the delivered folders
    under the games dir have (measured: 50 of 51 delivered builds keep
    ``index.html`` at their own root).
    `threads` is accepted for call-site compatibility: py7zr has no ``-mmt``
    equivalent for writing (it measured faster than 7z.exe -mmt anyway), so
    it only controls multiprocessing on the extraction side.
    """
    py7zr = _py7zr()
    if not os.path.isdir(folder):
        raise FileNotFoundError("folder not found: %s" % folder)
    # Historical `-o` semantics: a relative path gets the .7z suffix, an
    # absolute one is used verbatim (callers pass an explicit filename).
    if not archive.endswith(SUFFIX) and not os.path.isabs(archive):
        archive += SUFFIX
    if os.path.isfile(archive):
        os.remove(archive)
        log.info("removed stale archive %s", archive)

    root = os.path.basename(os.path.normpath(folder)) if wrapper else ""
    log.info("running: py7zr zstd level=%s %s <- %s (wrapper=%s)",
             level, archive, folder, wrapper)
    with py7zr.SevenZipFile(archive, "w", filters=filters_for(level)) as a:
        if wrapper:
            a.writeall(folder, root)
        else:
            # writeall(folder, "") would store the folder itself under its
            # absolute path (py7zr falls back to the real path for an empty
            # arcname), so add each top-level entry under its own name.
            for name in sorted(os.listdir(folder)):
                a.writeall(os.path.join(folder, name), name)
    size = os.path.getsize(archive)
    log.info("archive created: %s (%.1f MB)", archive, size / 1e6)
    return archive


def verify(archive):
    """Verify archive integrity (CRC pass over every member). True = OK."""
    py7zr = _py7zr()
    if not os.path.isfile(archive):
        log.error("archive test: FAILED (%s) - no such file", archive)
        return False
    try:
        with py7zr.SevenZipFile(archive, "r") as a:
            bad = a.testzip()
    except Exception as exc:  # noqa: BLE001 - any read failure = corrupt
        # A corrupt archive must never be reported on an INFO line: callers
        # check this return value and exit non-zero.
        log.error("archive test: FAILED (%s) - %s: %s",
                  archive, type(exc).__name__, exc)
        return False
    if bad:
        log.error("archive test: FAILED (%s) - bad member: %s", archive, bad)
        return False
    log.info("archive test: OK (%s)", archive)
    return True


def names(archive):
    """Every member path in the archive (posix-style, as stored)."""
    py7zr = _py7zr()
    with py7zr.SevenZipFile(archive, "r") as a:
        return a.getnames()


def extract(archive, dest, targets=None, threads=None):
    """Extract `targets` (default: everything) into `dest`.

    Refuses a Windows-side destination from WSL: that write must go through
    the Windows-side bridge in `deliver` (AGENTS.md CRITICAL rule), not
    through this process.  Returns `dest`.
    """
    if config.is_windows_side(dest):
        raise RuntimeError(
            "refusing to extract into a Windows-side path (%s) from WSL: a "
            "WSL-native process must not write a /mnt/* tree (AGENTS.md "
            "cross-system rule) - use deliver's Windows-side bridge, which "
            "hands the archive to 7z.exe via powershell.exe" % dest)
    py7zr = _py7zr()
    os.makedirs(dest, exist_ok=True)
    log.info("extracting %s -> %s%s", archive, dest,
             "" if not targets else " (%d target(s))" % len(targets))
    with py7zr.SevenZipFile(archive, "r", mp=bool(threads)) as a:
        a.extract(path=dest, targets=targets)
    return dest
