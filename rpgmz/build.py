#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the JoiPlay folder: copy only the web files, skip NW.js runtime + junk.

Copies run in parallel: one thread per web dir + one pool for root files,
orchestrated by asyncio, so the build is I/O-bound on disk bandwidth instead
of a single-threaded walk.
"""
import asyncio
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

from . import config

log = logging.getLogger("rpgmz.build")

DEFAULT_WORKERS = 6


def _copy_file(src, dst):
    shutil.copy2(src, dst)
    return dst


async def _copy_many(web_root, dst, dirs, root_files, workers):
    """Copy `dirs` (whole trees) + `root_files` (single files) in parallel."""
    loop = asyncio.get_running_loop()
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
        await asyncio.gather(*(loop.run_in_executor(ex, j) for j in jobs))


def build_joiplay(web_root, dst, keep_movies=True, workers=DEFAULT_WORKERS):
    """Copy `web_root` into `dst`, skipping NW.js runtime files and editor junk.

    Returns the destination path.
    """
    os.makedirs(dst, exist_ok=True)
    dirs = list(config.WEB_DIRS)
    if not keep_movies:
        dirs.remove("movies")

    root_files = [
        fn for fn in sorted(os.listdir(web_root))
        if fn not in config.NWJS_RUNTIME
        and os.path.isfile(os.path.join(web_root, fn))
    ]
    asyncio.run(_copy_many(web_root, dst, dirs, root_files, workers))
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
