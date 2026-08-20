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
import subprocess
from pathlib import Path

from . import compress as compress_mod
from . import config

log = logging.getLogger("rpgmaker.deliver")


def deliver(folder, archive=None, games=None, archives=None, level=15):
    """Compress `folder`, copy the archive into `archives`, then extract it
    into `games` (deleting any stale same-name folder there first).

    Defaults: `archives`/`games` come from env_config.json deliverables
    (games_dir/archives_dir), `archive` is written to temp_dir first.
    Returns the archive path in `archives`.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError("folder not found: %s" % folder)
    name = folder.name
    if not name:
        raise ValueError("cannot derive game name from %s" % folder)
    archives = Path(archives or config.archives_dir())
    games = Path(games or config.games_dir())
    local = Path(archive or Path(config.temp_dir()) / (name + ".7z"))

    log.info("deliver %s -> archives=%s games=%s", name, archives, games)

    compress_mod.compress(str(folder), str(local), level=level)
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
    _extract(dst_archive, games, name)

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
    """Run `command` in Windows PowerShell (Windows-side operations only)."""
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("powershell failed (%s):\n%s"
                           % (r.returncode, (r.stderr or r.stdout)[-2000:]))
    return r


def _remove_windows_side(target):
    """Delete a Windows-side folder via PowerShell Remove-Item (WSL python
    must not touch /mnt/* files). Single-quoted paths: double quotes would
    expand $vars inside the command; the trailing $? check makes a failed
    removal exit non-zero even under -ErrorAction SilentlyContinue."""
    _run_powershell("Remove-Item -Recurse -Force -LiteralPath '%s' "
                    "-ErrorAction SilentlyContinue; if (-not $?) { exit 1 }"
                    % config.to_windows_path(target))
    log.info("removed stale folder %s (Windows side)", target)


def _extract(archive, dest, name):
    """Extract only the `name/` entry of `archive` into `dest`.

    The 7z binary and its input files must be on the same platform: WSL-side
    files use the WSL 7zz; Windows-side (/mnt/*) files are handed to the
    Windows 7z.exe via powershell.exe.
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
    sevenz = config.find_7z()
    if not sevenz:
        raise FileNotFoundError(
            "7-Zip not found - install 7-Zip-Zstandard or set the SEVENZ env var")
    if config.is_windows_side(sevenz):
        _refuse_cross_side(
            "extract", archive,
            "SEVENZ points at the Windows 7z but the inputs are WSL-side; "
            "unset SEVENZ to use the WSL 7zz for WSL-side files.")
    cmd = [sevenz, "x", "-y", str(archive), "-o%s" % dest, name]
    log.info("running: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("7z extract failed:\n%s" % r.stderr[-2000:])
    return _check_extracted(dest, name)


def _extract_windows_side(archive, dest, name):
    win7z = config.win_7z()
    if not win7z:
        _refuse_cross_side(
            "extract", archive,
            "Windows 7z.exe not found (SEVENZ_WIN / tools.win7z / %s); "
            "install it or run the extraction on the Windows side manually."
            % config.DEFAULT_WIN_SEVENZ)
    command = "& '{0}' x -y '-o{1}' '{2}' '{3}'; if (-not $?) {{ exit 1 }}".format(
        win7z, config.to_windows_path(dest),
        config.to_windows_path(archive), name)
    log.info("running (Windows side): %s", command)
    _run_powershell(command)
    return _check_extracted(dest, name)


def _check_extracted(dest, name):
    target = Path(dest) / name
    if not target.is_dir():
        raise RuntimeError("extract did not produce %s" % target)
    log.info("extracted -> %s", target)
    return str(target)
