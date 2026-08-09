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

Only one big file ever crosses the boundary; the extraction runs on the
storage side (sequential 9P reads + writes).
"""
import logging
import os
import shutil
import subprocess

from . import compress as compress_mod
from . import config

log = logging.getLogger("rpgmz.deliver")


def deliver(folder, archive=None, games=None, archives=None, level=15):
    """Compress `folder`, copy the archive into `archives`, then extract it
    into `games` (deleting any stale same-name folder there first).

    Defaults: `archives`/`games` come from env_config.json deliverables
    (games_dir/archives_dir), `archive` is written to temp_dir first.
    Returns the archive path in `archives`.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError("folder not found: %s" % folder)
    name = os.path.basename(os.path.normpath(folder))
    if not name:
        raise ValueError("cannot derive game name from %s" % folder)
    archives = archives or config.archives_dir()
    games = games or config.games_dir()
    local = archive or os.path.join(config.temp_dir(), name + ".7z")

    log.info("deliver %s -> archives=%s games=%s", name, archives, games)

    compress_mod.compress(folder, local, level=level)
    if not compress_mod.test_archive(local):
        raise RuntimeError("local archive failed integrity test: %s" % local)

    os.makedirs(archives, exist_ok=True)
    dst_archive = os.path.join(archives, name + ".7z")
    shutil.copy2(local, dst_archive)
    log.info("archive copied: %s (%.1f MB)", dst_archive,
             os.path.getsize(dst_archive) / 1e6)

    target = os.path.join(games, name)
    if os.path.exists(target):
        log.info("removing stale folder %s", target)
        shutil.rmtree(target)
    os.makedirs(games, exist_ok=True)
    _extract(dst_archive, games, name)

    log.info("delivered: %s / %s", dst_archive, target)
    return dst_archive


def _extract(archive, dest, name):
    """Extract only the `name/` entry of `archive` into `dest`."""
    sevenz = config.find_7z()
    cmd = [sevenz, "x", "-y", archive, "-o%s" % dest, name]
    log.info("running: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("7z extract failed:\n%s" % r.stderr[-2000:])
    target = os.path.join(dest, name)
    if not os.path.isdir(target):
        raise RuntimeError("extract did not produce %s" % target)
    log.info("extracted -> %s", target)
    return target
