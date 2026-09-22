#!/usr/bin/env python3
"""fit_texture_4096.py - fit oversized PNGs to the mobile texture cap without
breaking pixel-grid addressing.

Android WebView/PixiJS cap WebGL textures at PNG_MAX_DIMENSION (rpgmaker/
config.py) px per side; larger PNGs render as black blocks on phones.
``downscale_images.py`` rescales whole images, which is right for plain art
but wrong for two asset kinds where pixel geometry is semantic:

- **Aseprite sprite sheets** (``img/pictures/<name>.png`` + sibling
  ``<name>.json``): sprite-sheet plugins address frames by pixel rect read
  from the JSON. Rescaling the PNG desynchronizes the rects (frames smear or
  crop). This tool instead re-tiles the uniform frame grid to fit the cap and
  rewrites the frame rects (``frame.x/y`` and ``meta.size``) in the JSON, so
  every frame stays pixel-exact, animation order (and sounds keyed by frame
  index) keeps working, and ``frameTags`` need no rewrite (they reference
  frame indices, which keep their order).

- **IconSet grids** (``img/system/IconSet.png``): MV/MZ address icons as
  ``index % 16 * 32`` / ``index // 16 * 32``. Rescaling breaks the 32 px grid
  for every icon in the game. The sheet is instead **cropped** at a 32 px row
  boundary to fit the cap. Icons beyond the crop disappear from the game, so
  check the build's highest used icon index first (data ``iconIndex`` fields
  and icon-related plugin parameters) before cropping.

Plain pictures (CG, backgrounds, standing art) must keep using
``downscale_images.py``.

Usage:
  python fit_texture_4096.py atlas <web_root>   [--dry-run] [--limit N]
  python fit_texture_4096.py iconset <web_root> [--dry-run] [--limit N]
"""
import glob
import json
import logging
import math
import os
import sys
from typing import Annotated

from PIL import Image

import typer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402
from rpgmaker import constants  # noqa: E402

log = logging.getLogger("fit_texture_4096")

# Icon addressing grid of MV/MZ (Window_Base._iconWidth/_iconHeight).
ICON_SIZE = 32
# Icons per row of the standard IconSet sheet.
ICON_COLUMNS = 16

APP = cliutil.app(help=__doc__)


def _frame_list(data):
    """Return the ordered Aseprite frame list, or None if frames is absent."""
    raw = data.get("frames")
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, list):
        return raw
    return None


def _grid_cells(frames):
    """Return (rects, fw, fh) when frames tile a uniform grid, else None."""
    rects = []
    for f in frames:
        r = (f.get("frame") or {}) if isinstance(f, dict) else {}
        if not all(isinstance(r.get(k), int) for k in ("x", "y", "w", "h")):
            return None
        rects.append((r["x"], r["y"], r["w"], r["h"]))
    if not rects:
        return None
    ws = {r[2] for r in rects}
    hs = {r[3] for r in rects}
    if len(ws) != 1 or len(hs) != 1:
        return None
    fw, fh = ws.pop(), hs.pop()
    if fw <= 0 or fh <= 0:
        return None
    cells = set()
    for x, y, _, _ in rects:
        if x % fw or y % fh:
            return None
        cell = (x // fw, y // fh)
        if cell in cells:
            return None
        cells.add(cell)
    return rects, fw, fh


def _pick_columns(count, fw, fh, limit):
    """Widest column count whose whole re-tiled grid fits ``limit``, else 0.

    Columns are capped at ``count`` so a small frame count can never pad
    the re-tiled sheet with mostly-empty columns.
    """
    for cols in range(min(count, limit // fw), 0, -1):
        rows = math.ceil(count / cols)
        if cols * fw <= limit and rows * fh <= limit:
            return cols
    return 0


def _load_json(path):
    """Load a JSON file; raise ValueError carrying the underlying reason."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(exc) from exc


def _save_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fix_atlas(web_root, limit, dry_run=False):
    """Re-tile oversized Aseprite sheets (PNG + JSON) to fit ``limit``.

    Returns 0 when every oversized sheet was handled, 1 when any sheet had to
    be left untouched (still oversized).
    """
    pic_dir = os.path.join(web_root, "img", "pictures")
    if not os.path.isdir(pic_dir):
        log.info("atlas: no img/pictures directory; nothing to do")
        return 0
    oversized = []
    for p in glob.glob(os.path.join(pic_dir, "*.png")):
        with Image.open(p) as im:
            w, h = im.size
        if max(w, h) > limit:
            oversized.append(p)
    if not oversized:
        log.info("atlas: no sheet beyond %d px", limit)
        return 0
    failures = 0
    for png in sorted(oversized):
        js = os.path.splitext(png)[0] + ".json"
        if not os.path.isfile(js):
            log.warning("%s: no sibling .json to rewrite frame rects from - "
                        "left untouched (still oversized)", png)
            failures += 1
            continue
        with Image.open(png) as sheet_im:
            sheet = sheet_im.convert("RGBA")
        try:
            data = _load_json(js)
            frames = _frame_list(data)
            if frames is None:
                raise ValueError("frames is neither a list nor an object")
            grid = _grid_cells(frames)
            if grid is None:
                raise ValueError("frames are not a uniform non-overlapping "
                                 "grid; refusing to re-tile")
            rects, fw, fh = grid
            count = len(rects)
            cols = _pick_columns(count, fw, fh, limit)
            if cols <= 0:
                raise ValueError("%d frames of %dx%d cannot fit %d px in any "
                                 "column layout" % (count, fw, fh, limit))
            rows = math.ceil(count / cols)
            new_w, new_h = cols * fw, rows * fh
            log.info("%s: %dx%d, %d frames %dx%d -> %dx%d (grid %dx%d)",
                     os.path.basename(png), sheet.width, sheet.height, count,
                     fw, fh, new_w, new_h, cols, rows)
            if dry_run:
                continue
            out = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
            for i, (x, y, _, _) in enumerate(rects):
                nx, ny = (i % cols) * fw, (i // cols) * fh
                region = sheet.crop((x, y, x + fw, y + fh))
                out.paste(region, (nx, ny))
                if out.crop((nx, ny, nx + fw, ny + fh)).tobytes() \
                        != region.tobytes():
                    raise RuntimeError("frame %d pixel verification mismatch"
                                       % i)
                frame = frames[i]["frame"]
                frame["x"], frame["y"] = nx, ny
            meta = data.get("meta")
            if isinstance(meta, dict):
                meta["size"] = {"w": new_w, "h": new_h}
            out.save(png, optimize=True)
            _save_json(js, data)
            log.info("%s: rewrote sheet + %d frame rects", os.path.basename(js),
                     count)
        except (ValueError, KeyError, RuntimeError) as exc:
            log.error("%s: %s - left untouched (still oversized)", png, exc)
            failures += 1
        finally:
            sheet.close()
    return 1 if failures else 0


def fix_iconset(web_root, limit, dry_run=False):
    """Crop img/system/IconSet.png to ``limit`` at a 32 px row boundary.

    Returns 0 on success/no-op, 1 when the sheet cannot be fixed by cropping
    (width already beyond the cap, or limit below the 32 px icon grid).
    """
    path = os.path.join(web_root, "img", "system", "IconSet.png")
    if not os.path.isfile(path):
        log.info("iconset: no img/system/IconSet.png; nothing to do")
        return 0
    if limit < ICON_SIZE:
        log.error("%s: limit %d is below the %d px icon grid; cropping "
                  "would produce an empty sheet - left untouched",
                  path, limit, ICON_SIZE)
        return 1
    with Image.open(path) as im:
        w, h = im.size
        if max(w, h) <= limit:
            log.info("iconset: %dx%d already fits %d px", w, h, limit)
            return 0
        if w > limit:
            log.error("%s: width %d already exceeds %d px; cropping columns "
                      "would break icon index math - left untouched",
                      path, w, limit)
            return 1
        rows = min(h // ICON_SIZE, limit // ICON_SIZE)
        new_h = rows * ICON_SIZE
        log.info("iconset: %dx%d -> %dx%d (keeps icon indices 0..%d; icons "
                 "beyond the crop vanish)", w, h, w, new_h,
                 rows * ICON_COLUMNS - 1)
        if dry_run:
            return 0
        im.crop((0, 0, w, new_h)).save(path, optimize=True)
    return 0


@APP.command()
def atlas(web_root: Annotated[str, typer.Argument(help="JoiPlay web root")],
          limit: Annotated[int, typer.Option(
              "--limit", help="per-side texture cap in px")] =
          constants.PNG_MAX_DIMENSION,
          dry_run: Annotated[bool, typer.Option(
              "--dry-run", help="report only, don't modify")] = False,
          verbose: cliutil.Verbose = False,
          quiet: cliutil.Quiet = False,
          log_file: cliutil.LogFile = None) -> int:
    """Re-tile oversized Aseprite sheets (PNG + JSON rects) to fit the cap."""
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("fit texture", web_root=web_root)
    return fix_atlas(web_root, limit, dry_run)


@APP.command()
def iconset(web_root: Annotated[str, typer.Argument(help="JoiPlay web root")],
            limit: Annotated[int, typer.Option(
                "--limit", help="per-side texture cap in px")] =
            constants.PNG_MAX_DIMENSION,
            dry_run: Annotated[bool, typer.Option(
                "--dry-run", help="report only, don't modify")] = False,
            verbose: cliutil.Verbose = False,
            quiet: cliutil.Quiet = False,
            log_file: cliutil.LogFile = None) -> int:
    """Crop img/system/IconSet.png to the cap at a 32 px row boundary."""
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("fit texture", web_root=web_root)
    return fix_iconset(web_root, limit, dry_run)


def main(argv=None) -> int:
    return cliutil.run(APP, argv, prog="fit_texture_4096.py")


if __name__ == "__main__":
    raise SystemExit(main())
