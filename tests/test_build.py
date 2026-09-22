#!/usr/bin/env python3
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

    def test_extra_asset_dir_copied(self, tmp_path, fake_tools):
        """Non-standard plugin asset folders must survive the build."""
        web = make_game(str(tmp_path / "g"))
        bone = os.path.join(web, "dragonbones")
        os.makedirs(bone)
        with open(os.path.join(bone, "ske.json"), "w", encoding="utf-8") as f:
            f.write('{"armature": []}\n')
        with open(os.path.join(bone, "tex.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        out = str(tmp_path / "out")
        build.build_joiplay(web, out, workers=2)
        assert os.path.isfile(os.path.join(out, "dragonbones", "ske.json"))
        assert os.path.isfile(os.path.join(out, "dragonbones", "tex.png"))

    def test_repack_tool_dirs_dropped(self, tmp_path, fake_tools):
        """MTool / repack tooling directories never enter the build."""
        web = make_game(str(tmp_path / "g"))
        for name in ("Tool", "MTool", "Dictionaries"):
            os.makedirs(os.path.join(web, name))
            with open(os.path.join(web, name, "x.bin"), "wb") as f:
                f.write(b"junk")
        out = str(tmp_path / "out")
        build.build_joiplay(web, out, workers=2)
        for name in ("Tool", "MTool", "Dictionaries"):
            assert not os.path.isdir(os.path.join(out, name)), name

    def test_extra_asset_dirs_reports_only_real_dirs(self, tmp_path, fake_tools):
        web = make_game(str(tmp_path / "g"))
        os.makedirs(os.path.join(web, "character"))
        os.makedirs(os.path.join(web, "swiftshader"))
        extra = build.extra_asset_dirs(web)
        assert "character" in extra
        assert "swiftshader" not in extra
        assert "img" not in extra

    def test_extra_asset_dirs_is_case_insensitive(self, tmp_path):
        """A differently-cased web/runtime folder must not become an extra."""
        web = tmp_path / "w"
        for name in ("Audio", "Fonts", "locales", "dragonbones"):
            (web / name).mkdir(parents=True)
        assert build.extra_asset_dirs(str(web)) == ["dragonbones"]
