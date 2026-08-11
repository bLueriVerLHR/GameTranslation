#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/build.py JoiPlay folder build."""
import os

from conftest import make_game

from rpgmaker import build


class TestBuildJoiplay:
    def test_build_strips_nwjs(self, game_dir, fake_tools):
        root, web = game_dir
        out = os.path.join(os.path.dirname(root), "out")
        build.build_joiplay(web, out, workers=2)
        for fn in ("Game.exe", "nw.dll", "icudtl.dat"):
            assert not os.path.exists(os.path.join(out, fn)), fn
        for rel in ("index.html", "js/main.js", "js/plugins.js",
                    "js/rmmz_core.js", "data/System.json",
                    "audio/bgm/bgm1.ogg", "img/pictures/pic1.png",
                    "fonts/used_font.ttf", "css/main.css"):
            assert os.path.isfile(os.path.join(out, rel)), rel

    def test_keep_movies_false_drops_movies(self, game_dir, fake_tools):
        _root, web = game_dir
        out = os.path.join(os.path.dirname(web), "out-nomovie")
        build.build_joiplay(web, out, keep_movies=False, workers=2)
        assert not os.path.isdir(os.path.join(out, "movies"))

    def test_missing_dirs_skipped(self, tmp_path, fake_tools):
        web = make_game(str(tmp_path / "g"))
        os.rmdir(os.path.join(web, "effects"))
        out = str(tmp_path / "out")
        build.build_joiplay(web, out, workers=2)
        assert not os.path.isdir(os.path.join(out, "effects"))
