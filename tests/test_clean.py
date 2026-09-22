#!/usr/bin/env python3
"""Unit tests for rpgmaker/clean.py safe cleanup."""
import os

import pytest
from conftest import fs_is_case_sensitive, make_game

from rpgmaker import clean


class TestImgJunk:
    def test_removes_junk_keeps_png(self, game_dir, fake_tools):
        _root, web = game_dir
        removed, freed = clean.remove_img_junk(web)
        assert removed == 2  # junk.txt + junk.clip
        assert freed > 0
        assert not os.path.exists(os.path.join(web, "img", "junk.txt"))
        assert os.path.exists(os.path.join(web, "img", "pictures", "pic1.png"))

    def test_dry_run(self, game_dir, fake_tools):
        _root, web = game_dir
        clean.remove_img_junk(web, dry_run=True)
        assert os.path.exists(os.path.join(web, "img", "junk.txt"))


class TestFonts:
    def test_removes_unused_fonts(self, game_dir, fake_tools):
        _root, web = game_dir
        removed, freed = clean.remove_unused_fonts(web)
        # unused_font.otf + CaseFont.TTF are both unreferenced
        assert removed == 2
        assert freed > 0
        assert not os.path.exists(os.path.join(web, "fonts", "unused_font.otf"))
        assert os.path.exists(os.path.join(web, "fonts", "used_font.ttf"))

    def test_case_mismatch_renamed(self, game_dir, fake_tools):
        _root, web = game_dir
        if not fs_is_case_sensitive(web):
            pytest.skip("case-insensitive filesystem: the rename is a no-op")
        css = os.path.join(web, "css", "main.css")
        with open(css, "a", encoding="utf-8") as f:
            f.write('@font-face { src: url("casefont.ttf"); }\n')
        removed, _freed = clean.remove_unused_fonts(web)
        # after cleanup the on-disk name matches the referenced case
        assert os.path.exists(os.path.join(web, "fonts", "casefont.ttf"))
        assert not os.path.exists(os.path.join(web, "fonts", "CaseFont.TTF"))
        assert removed == 1  # only the truly unused otf

    def test_references_split_on_commas(self, tmp_path, fake_tools):
        web = make_game(str(tmp_path / "g"))
        css = os.path.join(web, "css", "main.css")
        with open(css, "a", encoding="utf-8") as f:
            f.write('@font-face { src: url("used_font.ttf,unused_font.otf,'
                    'casefont.ttf"); }\n')
        removed, _freed = clean.remove_unused_fonts(web)
        assert removed == 0  # all referenced via comma-joined token


class TestTilesets:
    def test_removes_unreferenced(self, game_dir, fake_tools):
        _root, web = game_dir
        removed, freed = clean.remove_unused_tilesets(web)
        assert removed == 1  # unused.png
        assert os.path.exists(os.path.join(web, "img", "tilesets", "World_A1.png"))
        assert not os.path.exists(os.path.join(web, "img", "tilesets", "unused.png"))

    def test_keeps_prefix_variant_of_referenced_name(self, game_dir,
                                                     fake_tools):
        _root, web = game_dir
        tiles_dir = os.path.join(web, "img", "tilesets")
        # a plugin references "World_A1_2" (built dynamically) somewhere in
        # js/; World_A1.png is a prefix variant -> must be kept
        js = os.path.join(web, "js", "main.js")
        with open(js, "a", encoding="utf-8") as f:
            f.write('loadTileset("World_A1_2");')
        removed, _freed = clean.remove_unused_tilesets(web)
        assert os.path.exists(os.path.join(tiles_dir, "World_A1.png"))
        assert not os.path.exists(os.path.join(tiles_dir, "unused.png"))
        assert removed == 1


class TestCleanupAll:
    def test_total_freed(self, game_dir, fake_tools):
        _root, web = game_dir
        total = clean.cleanup_all(web)
        assert total > 0

    def test_dry_run_no_changes(self, game_dir, fake_tools):
        _root, web = game_dir
        clean.cleanup_all(web, dry_run=True)
        assert os.path.exists(os.path.join(web, "img", "junk.txt"))
        assert os.path.exists(os.path.join(web, "fonts", "unused_font.otf"))
        assert os.path.exists(os.path.join(web, "img", "tilesets", "unused.png"))
