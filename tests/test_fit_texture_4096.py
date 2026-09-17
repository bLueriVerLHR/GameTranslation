#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/fit_texture_4096.py (atlas re-tiling + IconSet crop).

Path setup comes from tests/conftest.py (repo root + tools/).
"""
import json
import os

from PIL import Image

import fit_texture_4096 as ft


# ---------------------------------------------------------------------------
# synthetic assets
# ---------------------------------------------------------------------------

def _frame_pixels(fw, fh, seed):
    """Distinct RGBA pattern per frame so any misplacement is caught."""
    px = Image.new("RGBA", (fw, fh))
    data = []
    for y in range(fh):
        for x in range(fw):
            data.append(((seed * 37 + x * 3) % 256,
                         (seed * 53 + y * 5) % 256,
                         (seed * 97 + x + y) % 256,
                         255 if (x + y + seed) % 7 else 128))
    px.putdata(data)
    return px


def _write_strip(web_root, name, fw, fh, count):
    """A horizontal Aseprite strip (PNG + sibling JSON in hash shape)."""
    pic = web_root / "img" / "pictures"
    pic.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGBA", (fw * count, fh), (0, 0, 0, 0))
    frames = {}
    for i in range(count):
        px = _frame_pixels(fw, fh, i + 1)
        sheet.paste(px, (i * fw, 0))
        frames["f%d.ase" % i] = {
            "frame": {"x": i * fw, "y": 0, "w": fw, "h": fh},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": fw, "h": fh},
            "sourceSize": {"w": fw, "h": fh},
            "duration": 100 + i,
        }
    png = pic / (name + ".png")
    sheet.save(str(png), "PNG")
    jsn = pic / (name + ".json")
    meta = {"app": "test", "size": {"w": fw * count, "h": fh},
            "frameTags": [{"name": "loop", "from": 0, "to": count - 1,
                            "direction": "forward"}]}
    jsn.write_text(json.dumps({"frames": frames, "meta": meta},
                              ensure_ascii=False), encoding="utf-8")
    return png, jsn, sheet


def _read_json(path):
    with open(str(path), encoding="utf-8") as f:
        return json.load(f)


def _rects(jsdata):
    raw = jsdata["frames"]
    vals = list(raw.values()) if isinstance(raw, dict) else raw
    return [(f["frame"]["x"], f["frame"]["y"], f["frame"]["w"],
             f["frame"]["h"]) for f in vals]


# ---------------------------------------------------------------------------
# atlas
# ---------------------------------------------------------------------------

class TestAtlas:
    def test_retiles_and_keeps_frames_pixel_exact(self, tmp_path):
        png, jsn, original = _write_strip(tmp_path, "anim", 100, 40, 5)
        rc = ft.main(["atlas", str(tmp_path), "--limit", "256"])
        assert rc == 0
        with Image.open(str(png)) as im:
            assert im.size == (200, 120)  # 2 cols x 3 rows, both <= 256
            new = im.convert("RGBA")
        rects = _rects(_read_json(jsn))
        assert [r[:2] for r in rects] == \
            [(0, 0), (100, 0), (0, 40), (100, 40), (0, 80)]
        assert {r[2:] for r in rects} == {(100, 40)}
        for i, (x, y, w, h) in enumerate(rects):
            src = original.crop((i * 100, 0, i * 100 + 100, 40))
            assert new.crop((x, y, x + w, y + h)).tobytes() \
                == src.tobytes(), "frame %d moved losslessly" % i

    def test_json_meta_and_per_frame_data_survive(self, tmp_path):
        png, jsn, _ = _write_strip(tmp_path, "anim", 100, 40, 5)
        before = _read_json(jsn)
        ft.main(["atlas", str(tmp_path), "--limit", "256"])
        after = _read_json(jsn)
        assert after["meta"]["size"] == {"w": 200, "h": 120}
        assert after["meta"]["frameTags"] == before["meta"]["frameTags"]
        durations = [f["duration"] for f in after["frames"].values()]
        assert durations == [100 + i for i in range(5)]
        names = list(after["frames"].keys())
        assert names == ["f%d.ase" % i for i in range(5)]
        ss = [f["spriteSourceSize"] for f in after["frames"].values()]
        assert all(s == {"x": 0, "y": 0, "w": 100, "h": 40} for s in ss)

    def test_array_shaped_frames_supported(self, tmp_path):
        png, jsn, _ = _write_strip(tmp_path, "anim", 100, 40, 4)
        data = _read_json(jsn)
        data["frames"] = list(data["frames"].values())
        jsn.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        rc = ft.main(["atlas", str(tmp_path), "--limit", "200"])
        assert rc == 0
        assert len(_rects(_read_json(jsn))) == 4

    def test_fitting_sheet_untouched(self, tmp_path):
        png, jsn, _ = _write_strip(tmp_path, "small", 100, 40, 2)
        pb, jb = png.read_bytes(), jsn.read_bytes()
        rc = ft.main(["atlas", str(tmp_path), "--limit", "4096"])
        assert rc == 0
        assert png.read_bytes() == pb
        assert jsn.read_bytes() == jb

    def test_mixed_frame_sizes_refused_and_untouched(self, tmp_path):
        png, jsn, _ = _write_strip(tmp_path, "odd", 100, 40, 3)
        data = _read_json(jsn)
        vals = list(data["frames"].values())
        vals[1]["frame"]["w"] = 80  # breaks uniformity
        jsn.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        pb, jb = png.read_bytes(), jsn.read_bytes()
        rc = ft.main(["atlas", str(tmp_path), "--limit", "256"])
        assert rc == 1
        assert png.read_bytes() == pb
        assert jsn.read_bytes() == jb

    def test_missing_json_refused(self, tmp_path):
        png, jsn, _ = _write_strip(tmp_path, "lonely", 100, 40, 3)
        os.remove(str(jsn))
        pb = png.read_bytes()
        rc = ft.main(["atlas", str(tmp_path), "--limit", "256"])
        assert rc == 1
        assert png.read_bytes() == pb

    def test_columns_capped_at_frame_count(self, tmp_path):
        # 4 frames of 32x400 under limit 512: a naive widest-first search
        # would pick 16 columns and pad the sheet to 512x400 (67% empty);
        # the search must cap columns at the frame count (4 -> 128x400).
        png, _, _ = _write_strip(tmp_path, "wide", 32, 400, 4)
        rc = ft.main(["atlas", str(tmp_path), "--limit", "512"])
        assert rc == 0
        with Image.open(str(png)) as im:
            assert im.size == (128, 400)

    def test_no_layout_fits_refused(self, tmp_path):
        # limit 256: 2 cols x 2 rows of 100x200 = 400 px high (too tall),
        # 1 col x 3 rows = 600 px (too tall) -> nothing fits.
        png, jsn, _ = _write_strip(tmp_path, "tall", 100, 200, 3)
        pb, jb = png.read_bytes(), jsn.read_bytes()
        rc = ft.main(["atlas", str(tmp_path), "--limit", "256"])
        assert rc == 1
        assert png.read_bytes() == pb
        assert jsn.read_bytes() == jb

    def test_dry_run_changes_nothing(self, tmp_path):
        png, jsn, _ = _write_strip(tmp_path, "anim", 100, 40, 5)
        pb, jb = png.read_bytes(), jsn.read_bytes()
        rc = ft.main(["atlas", str(tmp_path), "--limit", "256", "--dry-run"])
        assert rc == 0
        assert png.read_bytes() == pb
        assert jsn.read_bytes() == jb

    def test_missing_pictures_dir_is_a_noop(self, tmp_path):
        rc = ft.main(["atlas", str(tmp_path)])
        assert rc == 0

    def test_limit_defaults_to_config(self, tmp_path):
        from rpgmaker import config
        # 50 frames x 100 px = 5000 px wide: oversized under the default cap,
        # so this exercises the default instead of silently being a noop.
        png, jsn, _ = _write_strip(tmp_path, "anim", 100, 40, 50)
        rc = ft.main(["atlas", str(tmp_path)])
        assert rc == 0
        with Image.open(str(png)) as im:
            assert im.size == (4000, 80)  # capped at count: 40 cols x 2 rows
            assert max(im.size) <= config.PNG_MAX_DIMENSION
        assert len(_rects(_read_json(jsn))) == 50


# ---------------------------------------------------------------------------
# iconset
# ---------------------------------------------------------------------------

def _write_iconset(web_root, cols_px=64, rows=20):
    sysdir = web_root / "img" / "system"
    sysdir.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGBA", (cols_px, rows * ft.ICON_SIZE), (0, 0, 0, 0))
    # one opaque marker icon in the first and the last row
    for row in (0, rows - 1):
        im.paste(Image.new("RGBA", (ft.ICON_SIZE, ft.ICON_SIZE),
                           (250, 10, 10, 255)),
                 (0, row * ft.ICON_SIZE))
    p = sysdir / "IconSet.png"
    im.save(str(p), "PNG")
    return p


class TestIconset:
    def test_crops_at_row_boundary(self, tmp_path):
        p = _write_iconset(tmp_path, rows=20)
        rc = ft.main(["iconset", str(tmp_path), "--limit", "256"])
        assert rc == 0
        with Image.open(str(p)) as im:
            assert im.size == (64, 256)  # 8 rows, multiple of 32
            rgba = im.convert("RGBA")
            # capacity of the cropped sheet: 8 kept rows x 16 columns = 128
            assert im.size[1] // ft.ICON_SIZE * ft.ICON_COLUMNS == 128
        # first row (kept) marker intact
        assert rgba.getpixel((5, 5)) == (250, 10, 10, 255)
        # last kept row is row 7: no marker there, so pixel is transparent
        assert rgba.getpixel((5, 7 * ft.ICON_SIZE + 5))[3] == 0

    def test_fitting_sheet_untouched(self, tmp_path):
        p = _write_iconset(tmp_path, rows=4)
        before = p.read_bytes()
        rc = ft.main(["iconset", str(tmp_path), "--limit", "4096"])
        assert rc == 0
        assert p.read_bytes() == before

    def test_wide_sheet_refused(self, tmp_path):
        p = _write_iconset(tmp_path, cols_px=512, rows=20)
        before = p.read_bytes()
        rc = ft.main(["iconset", str(tmp_path), "--limit", "256"])
        assert rc == 1
        assert p.read_bytes() == before

    def test_limit_below_icon_grid_refused(self, tmp_path):
        # limit < 32 would compute zero rows and crop an empty sheet.
        p = _write_iconset(tmp_path, rows=20)
        before = p.read_bytes()
        rc = ft.main(["iconset", str(tmp_path), "--limit", "16"])
        assert rc == 1
        assert p.read_bytes() == before

    def test_missing_file_is_a_noop(self, tmp_path):
        rc = ft.main(["iconset", str(tmp_path)])
        assert rc == 0

    def test_dry_run_changes_nothing(self, tmp_path):
        p = _write_iconset(tmp_path, rows=20)
        before = p.read_bytes()
        rc = ft.main(["iconset", str(tmp_path), "--limit", "256",
                      "--dry-run"])
        assert rc == 0
        assert p.read_bytes() == before
