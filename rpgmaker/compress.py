#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compress a JoiPlay folder into a `.7z` archive using 7-Zip-Zstandard.
Exposed as a plain function + CLI subcommand; NOT run by default in the
pipeline (so the project stays testable)."""
import logging
import os
import subprocess

from . import config, runtime

log = logging.getLogger("rpgmaker.compress")


def compress(folder, archive, level=15, threads=None):
    """Create a zstd 7z archive of `folder`. Returns archive path.

    Any existing file at `archive` is deleted first: `7z a` APPENDS to an
    existing archive, so re-running on a stale `.7z` would double its size
    (old entries kept + new ones added).

    `threads`: None = auto-tuned `-mmt=N` from the machine (runtime.py),
    an int forces that many threads, False/0 disables multi-threading.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError("folder not found: %s" % folder)
    if archive.endswith(".7z"):
        pass
    elif not os.path.isabs(archive):
        archive = archive + ".7z"
    if os.path.isfile(archive):
        os.remove(archive)
        log.info("removed stale archive %s", archive)
    sevenz = config.find_7z()
    if not sevenz:
        raise FileNotFoundError(
            "7-Zip not found - install 7-Zip-Zstandard or set the SEVENZ env var")
    cmd = [sevenz, "a", "-t7z", "-m0=zstd", "-mx=%d" % level]
    if threads is None:
        threads = runtime.auto_workers("compress", path=folder)
    if threads:
        if threads is True:
            cmd.append("-mmt=on")
        else:
            cmd.append("-mmt=%d" % int(threads))
    cmd += [archive, folder]
    log.info("running: %s", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("7z failed:\n%s" % r.stderr[-2000:])
    log.info("archive created: %s (%.1f MB)",
             archive, os.path.getsize(archive) / 1e6)
    return archive


def test_archive(archive):
    """Verify archive integrity with `7z t`. Returns True on success."""
    sevenz = config.find_7z()
    if not sevenz:
        raise FileNotFoundError(
            "7-Zip not found - install 7-Zip-Zstandard or set the SEVENZ env var")
    r = subprocess.run([sevenz, "t", archive], capture_output=True, text=True)
    ok = r.returncode == 0 and "Everything is Ok" in r.stdout
    log.info("archive test: %s", "OK" if ok else "FAILED")
    return ok
