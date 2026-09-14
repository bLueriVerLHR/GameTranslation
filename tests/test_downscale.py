#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/downscale_images.py mobile-safe PNG downscaling."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import pytest

import downscale_images as di


@pytest.fixture
def web_root(tmp_path):
    root = tmp_path / "web"
    (root / "img" / "pictures").mkdir(parents=True)
    return root


def _png(w, h, path):
    from PIL import Image
    Image.new("RGBA", (w, h), (0, 255, 0, 255)).save(str(path), "PNG")
    return path


class TestPngSize:
    def test_reads_ihdr(self, web_root):
        p = _png(100, 50, web_root / "img" / "pictures" / "a.png")
        assert di.png_size(str(p)) == (100, 50)

    def test_non_png(self, web_root):
        p = web_root / "img" / "pictures" / "b.png"
        p.write_bytes(b"not a png")
        assert di.png_size(str(p)) is None

    def test_missing_file(self, web_root):
        assert di.png_size(str(web_root / "nope.png")) is None

    def test_truncated_png_header_is_not_a_crash(self, web_root):
        """The PNG signature followed by fewer than 24 bytes (interrupted
        copy) used to raise struct.error from a report-only code path."""
        p = web_root / "img" / "pictures" / "trunc.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d" + b"IHDR")
        assert di.png_size(str(p)) is None


class TestDownscaleOne:
    def test_under_limit_untouched(self, web_root):
        p = _png(64, 48, web_root / "img" / "pictures" / "ok.png")
        assert di.downscale_one(str(p), 4096) is None

    def test_oversized_downscaled(self, web_root):
        p = _png(5000, 10, web_root / "img" / "pictures" / "wide.png")
        old, new = di.downscale_one(str(p), 4096)
        assert old == (5000, 10)
        assert new[0] == 4096
        assert new[1] <= 10
        assert di.png_size(str(p)) == new

    def test_tall_art(self, web_root):
        p = _png(10, 5000, web_root / "img" / "pictures" / "tall.png")
        di.downscale_one(str(p), 4096)
        w, h = di.png_size(str(p))
        assert h == 4096 and w <= 10


class TestScan:
    def test_scan_downscales(self, web_root):
        _png(100, 100, web_root / "img" / "pictures" / "small.png")
        _png(6000, 8, web_root / "img" / "pictures" / "big.png")
        di.scan(str(web_root), 4096, workers=2, dry_run=False)
        assert di.png_size(str(web_root / "img" / "pictures" / "big.png"))[0] == 4096
        assert di.png_size(str(web_root / "img" / "pictures" / "small.png")) == (100, 100)

    def test_dry_run_writes_nothing(self, web_root, capsys):
        _png(6000, 8, web_root / "img" / "pictures" / "big.png")
        di.scan(str(web_root), 4096, workers=1, dry_run=True)
        assert di.png_size(str(web_root / "img" / "pictures" / "big.png"))[0] == 6000
