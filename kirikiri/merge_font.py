#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge a Chinese font with a Japanese font into one CJK TTF.

The Chinese font goes first, so its glyphs win for every codepoint both
fonts cover; the Japanese font supplies the kanji the Chinese font lacks.
Both inputs are rescaled to a common units-per-em (2048) before merging.

Useful for KiriKiri games whose configured font has no GB glyphs - the
merged font is installed (or registered) for the game, so dialogue renders
without tofu boxes.  Exact font registration is game-specific; record what
worked in docs/table/<Game>/notes.md.

Usage:
    python3 kirikiri/merge_font.py <cn_font> <jp_font> <out.ttf> [--upm 2048]
"""

import os
import sys
from typing import Annotated

_HERE = os.path.dirname(os.path.abspath(__file__))
# Repo root, appended (not inserted) so a same-named sibling module in
# this directory still wins.
sys.path.append(os.path.dirname(_HERE))
from rpgmaker import cliutil  # noqa: E402

try:
    from fontTools.ttLib import TTFont, TTCollection
except ImportError as exc:                     # pragma: no cover - hint path
    raise ImportError(
        "fontTools is required to merge the Chinese and Japanese fonts - "
        "install the optional extra (pip install -e \".[fonts]\")") from exc


def _open_font(path):
    if path.lower().endswith(".ttc"):
        return TTCollection(path).fonts[0]
    return TTFont(path)


def scale_to(font_path, out_path, target_upm):
    """Rescale a font's metrics to a common units-per-em."""
    font = _open_font(font_path)
    cur = font["head"].unitsPerEm
    factor = target_upm / cur
    font["head"].unitsPerEm = target_upm

    glyf = font["glyf"]
    for gname in glyf.glyphOrder:
        glyph = glyf[gname]
        if glyph.numberOfContours > 0:
            glyph.coordinates = glyph.coordinates * factor
        if glyph.isComposite():
            for comp in glyph.components:
                comp.x = int(comp.x * factor)
                comp.y = int(comp.y * factor)

    for tag in ("hmtx", "vmtx"):
        if tag in font:
            for name in list(font[tag].metrics):
                adv, lsb = font[tag].metrics[name]
                font[tag].metrics[name] = (int(adv * factor), int(lsb * factor))

    if "hhea" in font:
        hhea = font["hhea"]
        hhea.ascender = int(hhea.ascender * factor)
        hhea.descender = int(hhea.descender * factor)
    os2 = font["OS/2"]
    os2.sTypoAscender = int(os2.sTypoAscender * factor)
    os2.sTypoDescender = int(os2.sTypoDescender * factor)
    os2.sTypoLineGap = int(os2.sTypoLineGap * factor)
    os2.usWinAscent = int(os2.usWinAscent * factor)
    os2.usWinDescent = int(os2.usWinDescent * factor)

    font.save(out_path)
    return out_path


def merge_fonts(cn_font, jp_font, out_path, upm):
    from fontTools.merge import Merger

    tmp_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(tmp_dir, exist_ok=True)
    cn_scaled = os.path.join(tmp_dir, "_cn_%d.ttf" % upm)
    jp_scaled = os.path.join(tmp_dir, "_jp_%d.ttf" % upm)
    scale_to(cn_font, cn_scaled, upm)
    scale_to(jp_font, jp_scaled, upm)

    merged = Merger().merge([cn_scaled, jp_scaled])
    merged.save(out_path)
    return out_path


def cmd(cn_font: Annotated[str, cliutil.Argument(
            help="Chinese font first (glyph priority)")],
        jp_font: Annotated[str, cliutil.Argument(
            help="Japanese font (lacks GB glyphs)")],
        out_ttf: Annotated[str, cliutil.Argument(help="merged TTF to write")],
        upm: Annotated[int, cliutil.Option(
            "--upm", help="units per em used for both inputs")] = 2048,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Merge a Chinese and a Japanese font into one CJK TTF."""
    cliutil.setup_logging(verbose, quiet, log_file)
    if not os.path.exists(cn_font) or not os.path.exists(jp_font):
        return cliutil.fail("input font not found")
    merge_fonts(cn_font, jp_font, out_ttf, upm)
    print("merged size:", os.path.getsize(out_ttf), out_ttf)
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="merge_font.py")


if __name__ == "__main__":
    raise SystemExit(main())
