#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the JoiPlay folder: copy only the web files, skip NW.js runtime + junk.

Copies run in parallel: one thread per web dir + one pool for root files, so the
build is I/O-bound on disk bandwidth instead of a single-threaded walk.
"""
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

from . import config, runtime

log = logging.getLogger("rpgmaker.build")


def _copy_file(src, dst):
    shutil.copy2(src, dst)
    return dst


def _copy_many(web_root, dst, dirs, root_files, workers):
    """Copy `dirs` (whole trees) + `root_files` (single files) in parallel."""
    ignores = shutil.ignore_patterns(*config.NWJS_RUNTIME)
    jobs = []
    for d in dirs:
        src_dir = os.path.join(web_root, d)
        if not os.path.isdir(src_dir):
            log.info("skip %s (not present)", d)
            continue
        dst_dir = os.path.join(dst, d)
        jobs.append(lambda sd=src_dir, dd=dst_dir:
                    shutil.copytree(sd, dd, dirs_exist_ok=True, ignore=ignores))
    for fn in root_files:
        jobs.append(lambda s=os.path.join(web_root, fn), d=os.path.join(dst, fn):
                    _copy_file(s, d))
    if not jobs:
        return
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda j: j(), jobs))


def extra_asset_dirs(web_root):
    """Source directories beyond `WEB_DIRS` that still carry game data.

    Plugin asset folders (DragonBones skeletons/atlases, plugin UI bundles,
    custom data trees) are not MZ standard folders, so a fixed folder list
    drops them silently and those plugins break at runtime with
    "Failed to load".  Every directory that is neither an NW.js runtime folder
    nor repack tooling is treated as game data and copied; the skipped ones
    are reported so a dropped tree is never invisible.
    """
    skip = {d.lower() for d in config.NWJS_RUNTIME} | {
        d.lower() for d in config.REPACK_JUNK_DIRS}
    web = {d.lower() for d in config.WEB_DIRS}
    extra = []
    for name in sorted(os.listdir(web_root)):
        if not os.path.isdir(os.path.join(web_root, name)):
            continue
        # Case-insensitive compare: on Windows/macOS "Audio" *is* WEB_DIRS'
        # "audio", and copying both would race two threads onto the same
        # destination files (WinError 32).
        if name.lower() in web:
            continue
        if name.lower() in skip:
            log.info("skipping non-web dir %s/ (runtime or repack tooling)", name)
            continue
        extra.append(name)
    return extra


def build_joiplay(web_root, dst, keep_movies=True, workers=None):
    """Copy `web_root` into `dst`, skipping NW.js runtime files and editor junk.

    Returns the destination path.
    """
    workers = runtime.resolve_workers("copy", workers, path=web_root)
    os.makedirs(dst, exist_ok=True)
    dirs = list(config.WEB_DIRS)
    if not keep_movies:
        dirs.remove("movies")
    extra = extra_asset_dirs(web_root)
    if extra:
        log.info("extra asset dirs beyond WEB_DIRS: %s", ", ".join(extra))
    dirs += extra

    root_files = [
        fn for fn in sorted(os.listdir(web_root))
        if fn not in config.NWJS_RUNTIME
        and os.path.isfile(os.path.join(web_root, fn))
    ]
    _copy_many(web_root, dst, dirs, root_files, workers)
    log.info("copied %d root files", len(root_files))
    for d in dirs:
        dst_dir = os.path.join(dst, d)
        if os.path.isdir(dst_dir):
            log.info("copied %s/ (%d items)", d, _count_files(dst_dir))
    return dst


def _count_files(root):
    n = 0
    for _dp, _dn, fns in os.walk(root):
        n += len(fns)
    return n
