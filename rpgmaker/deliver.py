#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deliver a finished build to the Windows storage side.

Recursive copies of many small files across the WSL<->Windows boundary
(9P) are slow, so the write-back instead:

  1. compresses the build locally (fast native filesystem),
  2. copies the single archive into the archives dir, overwriting the
     previous archive (usually the source one),
  3. deletes any stale folder of the same name in the games dir, then
     extracts the archive into the games dir.

Only one big file ever crosses the boundary. The delete/extract touch the
storage side; when that side is Windows (/mnt/*) from inside WSL, the work
is delegated to the Windows-side tools via powershell.exe (Windows 7z.exe /
Remove-Item) - a WSL-native tool must never process Windows-side files
(AGENTS.md, "cross-system file handling" CRITICAL rule).
"""
import logging
import os
import shutil
from pathlib import Path

from . import archive as archive_mod
from . import compress as compress_mod
from . import config

log = logging.getLogger("rpgmaker.deliver")


def ps_quote(value):
    """Single-quote `value` for a PowerShell command line.

    Inside single quotes PowerShell expands nothing (no $vars, no spaces),
    which is exactly what a path needs - but a literal ' must be doubled or
    it terminates the string early. A game folder named "Bob's Game" used to
    break `deliver` mid-run with an unbalanced-quote parse error.
    """
    return "'" + str(value).replace("'", "''") + "'"


def deliver(folder, archive=None, games=None, archives=None, level=15,
            name=None):
    """Compress `folder`, copy the archive into `archives`, then extract it
    into `games` (deleting any stale same-name folder there first).

    Defaults: `archives`/`games` come from env_config.json deliverables
    (games_dir/archives_dir), `archive` is written to temp_dir first.
    `name` is the delivered name used for both the archive and the games-dir
    folder (default: the folder's own basename), so a work-slot layout that
    builds into `.../out/` can still deliver under the game's real name.
    Returns the archive path in `archives`.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError("folder not found: %s" % folder)
    name = name or folder.name
    if not name:
        raise ValueError("cannot derive game name from %s" % folder)
    archives = Path(archives or config.archives_dir())
    games = Path(games or config.games_dir())
    local = Path(archive or Path(config.temp_dir()) / (name + ".7z"))
    local.parent.mkdir(parents=True, exist_ok=True)

    log.info("deliver %s -> archives=%s games=%s", name, archives, games)

    # archive.create() appends .7z to a *relative* path (the historical -o
    # semantics) and returns the path it actually wrote; integrity-test THAT
    # one, not the requested one.  Measured failure: --archive "<name>" wrote
    # "<name>.7z" into the cwd while the test looked at "<name>" and reported
    # a bogus "local archive failed integrity test".
    local = Path(compress_mod.compress(str(folder), str(local), level=level))
    if not compress_mod.test_archive(str(local)):
        raise RuntimeError("local archive failed integrity test: %s" % local)

    os.makedirs(archives, exist_ok=True)
    dst_archive = archives / (name + ".7z")
    shutil.copy2(local, dst_archive)
    log.info("archive copied: %s (%.1f MB)", dst_archive,
             os.path.getsize(dst_archive) / 1e6)

    target = games / name
    if os.path.exists(target):
        if config.is_windows_side(target):
            _remove_windows_side(target)
        else:
            log.info("removing stale folder %s", target)
            shutil.rmtree(target)
    os.makedirs(games, exist_ok=True)
    # The archive stores the build folder under its own basename, so the wrapper
    # entry to extract is the FOLDER's name, while the delivered name may differ
    # (a build living in .../out/ delivered under the game's real name).
    _extract(dst_archive, games, folder.name)
    if name != folder.name:
        extracted = games / folder.name
        final = games / name
        if final.exists():
            if config.is_windows_side(final):
                _remove_windows_side(final)
            else:
                shutil.rmtree(final)
        os.replace(str(extracted), str(final))       # same volume: instant
        log.info("renamed extracted folder %s -> %s", extracted, final)

    log.info("delivered: %s / %s", dst_archive, target)
    return str(dst_archive)


def _refuse_cross_side(what, path, hint):
    """Raise the CRITICAL cross-side refusal: the tool about to process
    `path` runs on the other platform than the file itself (AGENTS.md)."""
    raise RuntimeError(
        "refusing to %s %s from inside WSL: a file and the tool processing "
        "it must live on the same platform (AGENTS.md CRITICAL cross-system "
        "rule). %s" % (what, path, hint))


def _run_powershell(command):
    """Run `command` in Windows PowerShell (Windows-side operations only).

    Thin alias over config.run_powershell so the interpreter lookup, the
    cross-system failure hint and the exit-code handling live in one place
    (shared with the WSL bridge in rpgmaker/config.py).
    """
    return config.run_powershell(command)


def _remove_windows_side(target):
    """Delete a Windows-side folder via PowerShell Remove-Item (WSL python
    must not touch /mnt/* files). Single-quoted paths: double quotes would
    expand $vars inside the command; the trailing $? check makes a failed
    removal exit non-zero even under -ErrorAction SilentlyContinue."""
    _run_powershell("Remove-Item -Recurse -Force -LiteralPath %s "
                    "-ErrorAction SilentlyContinue; if (-not $?) { exit 1 }"
                    % ps_quote(config.to_windows_path(target)))
    log.info("removed stale folder %s (Windows side)", target)


def _extract(archive, dest, name):
    """Extract only the `name/` entry of `archive` into `dest`.

    Platform routing is the ARCHIVE's format plus the DESTINATION's platform:
    a WSL-side destination is handled in-process by py7zr (no binary), while
    a Windows-side (/mnt/*) destination is handed to Windows 7z.exe through
    powershell.exe - a WSL-native process must never write that tree
    (AGENTS.md CRITICAL cross-system rule).
    """
    archive_win = config.is_windows_side(archive)
    dest_win = config.is_windows_side(dest)
    if archive_win != dest_win:
        _refuse_cross_side(
            "extract", archive,
            "archive and destination are on different platforms; copy the "
            "archive to the destination side first, then extract there.")
    if archive_win:
        return _extract_windows_side(archive, dest, name)
    return _extract_wsl_side(archive, dest, name)


def _extract_wsl_side(archive, dest, name):
    """WSL-side destination: py7zr extracts in-process (no 7-Zip needed)."""
    targets = [n for n in archive_mod.names(str(archive))
               if n == name or n.startswith(name + "/")]
    if not targets:
        raise RuntimeError("archive %s has no %s/ entry" % (archive, name))
    archive_mod.extract(str(archive), str(dest), targets=targets)
    return _check_extracted(dest, name)


def _extract_windows_side(archive, dest, name):
    win7z = config.win_7z()
    if not win7z:
        _refuse_cross_side(
            "extract", archive,
            "Windows 7z.exe not found - install 7-Zip-Zstandard on the "
            "Windows side (probed: Program Files/7-Zip*), or set SEVENZ_WIN "
            "to its full path; alternatively run the extraction on the "
            "Windows side manually.")
    command = "& {0} x -y {1} {2} {3}; if (-not $?) {{ exit 1 }}".format(
        ps_quote(win7z), "-o" + ps_quote(config.to_windows_path(dest)),
        ps_quote(config.to_windows_path(archive)), ps_quote(name))
    log.info("running (Windows side): %s", command)
    _run_powershell(command)
    return _check_extracted(dest, name)


def _check_extracted(dest, name):
    target = Path(dest) / name
    if not target.is_dir():
        raise RuntimeError("extract did not produce %s" % target)
    log.info("extracted -> %s", target)
    return str(target)
