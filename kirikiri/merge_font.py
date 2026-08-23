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

import argparse
import os
import sys

from fontTools.ttLib import TTFont, TTCollection


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


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cn_font", help="Chinese font first (glyph priority)")
    ap.add_argument("jp_font", help="Japanese font (lacks GB glyphs)")
    ap.add_argument("out_ttf")
    ap.add_argument("--upm", type=int, default=2048)
    args = ap.parse_args()

    if not os.path.exists(args.cn_font) or not os.path.exists(args.jp_font):
        print("error: input font not found", file=sys.stderr)
        raise SystemExit(1)
    merge_fonts(args.cn_font, args.jp_font, args.out_ttf, args.upm)
    print("merged size:", os.path.getsize(args.out_ttf), args.out_ttf)


if __name__ == "__main__":
    main()
