#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""downscale_images.py - downscale oversized PNG images for mobile rendering.

Android WebView/PixiJS cap WebGL textures at 4096 px per side; PNGs larger
than that (usually tall standing art) render as black blocks on phones.

The single-build policy: every build downscales any PNG whose width or height
exceeds the limit (aspect ratio + alpha preserved) so the same folder runs on
both PC and Android. No separate LowRes sibling build is produced anymore.

Usage:
  python downscale_images.py <web_root> [--limit 4096] [--dry-run] [--workers N]
"""
import argparse
import glob
import logging
import os
import struct
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmz import runtime  # noqa: E402

log = logging.getLogger("downscale_images")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_size(path):
    """Return (w, h) from the IHDR header, or None if not a readable PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
    except OSError:
        return None
    if head[:8] != PNG_MAGIC:
        return None
    return struct.unpack(">II", head[16:24])


def downscale_one(path, limit):
    old = png_size(path)
    if not old or max(old) <= limit:
        return None
    with Image.open(path) as img:
        scale = min(1.0, limit / img.width, limit / img.height)
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        img = img.resize((w, h), Image.LANCZOS)
        img.save(path, "PNG")
    return old, (w, h)


def scan(root, limit, workers, dry_run):
    workers = runtime.resolve_workers("png", workers, path=root)
    pattern = os.path.join(root, "img", "**", "*.png")
    sizes = {f: png_size(f) for f in glob.glob(pattern, recursive=True)}
    sizes = {f: s for f, s in sizes.items() if s}
    oversized = [f for f, s in sizes.items() if max(s) > limit]
    log.info("%d PNGs total, %d exceed the %d px limit",
             len(sizes), len(oversized), limit)
    if dry_run:
        for f in sorted(oversized):
            log.info("  would downscale %s (%dx%d)",
                     os.path.relpath(f, root), *sizes[f])
        return
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(downscale_one, f, limit): f for f in oversized}
        for fut in futures:
            f = futures[fut]
            res = fut.result()
            if res:
                done += 1
                log.info("  downscaled %s %dx%d -> %dx%d",
                         os.path.relpath(f, root), *res[0], *res[1])
    log.info("downscaled %d images", done)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("web_root", help="game web root (contains img/)")
    ap.add_argument("--limit", type=int, default=4096,
                    help="max pixels per side (default 4096)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--workers", type=int, default=None,
                    help="parallel workers (default: auto-tuned to the machine)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = os.path.abspath(args.web_root)
    if not os.path.isdir(os.path.join(root, "img")):
        sys.exit("not a web root: %s" % root)
    scan(root, args.limit, args.workers, args.dry_run)


if __name__ == "__main__":
    main()
