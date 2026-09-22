#!/usr/bin/env python3
"""downscale_images.py - downscale oversized PNG images for mobile rendering.

Android WebView/PixiJS cap WebGL textures at 4096 px per side; PNGs larger
than that (usually tall standing art) render as black blocks on phones.

The single-build policy: every build downscales any PNG whose width or height
exceeds the limit (aspect ratio + alpha preserved) so the same folder runs on
both PC and Android. No separate LowRes sibling build is produced anymore.

The default per-side limit is PNG_MAX_DIMENSION (rpgmaker/constants.py).

Usage:
  python downscale_images.py <web_root> [--glob PATTERN] [--limit N]
                                   [--dry-run] [--workers N]

`--glob` selects which PNGs to scan, relative to the root.  RPG Maker
builds keep the default (``img/**/*.png``); other layouts (TyranoScript
ships art under ``data/fgimage``, ``data/bgimage``, ``data/image``) pass
``--glob "**/*.png"``.
"""
import glob
import logging
import os
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import constants  # noqa: E402
from rpgmaker import runtime  # noqa: E402

from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("downscale_images")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# signature (8) + IHDR length/type (8) + width/height (8)
PNG_HEADER_BYTES = 24
# RPG Maker MZ/MV layout; other engines pass --glob explicitly.
DEFAULT_GLOB = os.path.join("img", "**", "*.png")


def png_size(path):
    """Return (w, h) from the IHDR header, or None if not a readable PNG.

    The header is read directly (not via an image library) so thousands of
    files can be checked without decoding any pixels.  A file that carries
    the PNG signature but is shorter than a header (an interrupted copy) is
    reported as unreadable instead of raising struct.error.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(PNG_HEADER_BYTES)
    except OSError:
        return None
    if head[:8] != PNG_MAGIC:
        return None
    if len(head) < 24:
        log.debug("%s: PNG signature but truncated header (%d bytes), skipped",
                  path, len(head))
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


def scan(root, limit, workers, dry_run, pattern=DEFAULT_GLOB):
    """Downscale every PNG matched by `pattern`; returns how many matched."""
    workers = runtime.resolve_workers("png", workers, path=root)
    found = glob.glob(os.path.join(root, pattern), recursive=True)
    sizes = {f: png_size(f) for f in found}
    sizes = {f: s for f, s in sizes.items() if s}
    oversized = [f for f, s in sizes.items() if max(s) > limit]
    log.info("%d PNGs total, %d exceed the %d px limit",
             len(sizes), len(oversized), limit)
    if dry_run:
        for f in sorted(oversized):
            log.info("  would downscale %s (%dx%d)",
                     os.path.relpath(f, root), *sizes[f])
        return len(sizes)
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
    return len(sizes)


def cmd(web_root: Annotated[str, cliutil.Argument(
            help="game web root (contains the images)")],
        pattern: Annotated[str, cliutil.Option(
            "--glob", help="PNG glob relative to the root (default: "
            "img/**/*.png; TyranoScript builds pass '**/*.png')"
        )] = DEFAULT_GLOB,
        limit: Annotated[int, cliutil.Option(
            "--limit", help="max pixels per side")] = constants.PNG_MAX_DIMENSION,
        dry_run: Annotated[bool, cliutil.Option(
            "--dry-run", help="report only, write nothing")] = False,
        workers: Annotated[int | None, cliutil.Option(
            "--workers", help="parallel workers (default: auto-tuned to "
            "the machine)")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("downscale images", web_root=web_root)
    root = os.path.abspath(web_root)
    if not os.path.isdir(root):
        print(f"not a directory: {root}", file=sys.stderr)
        return 1
    if not scan(root, limit, workers, dry_run, pattern=pattern):
        print(f"no PNG matched {pattern} under {root} (RPG Maker uses img/; pass "
              "--glob '**/*.png' for other layouts)",
              file=sys.stderr)
        return 1
    return 0


app = cliutil.command_app(cmd, help=__doc__)
# argparse used the module docstring as the command description; keep that
# visible in --help (a collapsed single-command app shows the command help).
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="downscale_images.py")


if __name__ == "__main__":
    raise SystemExit(main())
