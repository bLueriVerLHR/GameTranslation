#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/detect.py engine/layout detection."""
import os

from conftest import make_game

from rpgmaker import detect


class TestWebRootDetection:
    def test_mz_root_deploy(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        assert detect.is_web_root(web)
        assert detect.find_web_root(web) == web
        assert detect.is_mz(web)
        assert not detect.is_mv(web)

    def test_mv_www_layout(self, tmp_path):
        root = str(tmp_path / "g")
        web = make_game(root, mv=True)
        assert detect.is_web_root(root) is False
        assert detect.find_web_root(root) == web
        assert detect.is_mv(web)
        assert not detect.is_mz(web)

    def test_no_web_root(self, tmp_path):
        assert detect.find_web_root(str(tmp_path)) is None

    def test_engine_without_data_is_not_a_web_root(self, tmp_path):
        # MTool-style launcher repack: index.html + js/ at the root, but the
        # game database lives in the tool's own pack (Tool/www/data).
        root = tmp_path / "mtool_repack"
        (root / "js").mkdir(parents=True)
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "js" / "rmmz_core.js").write_text("// core", encoding="utf-8")
        (root / "Tool" / "www" / "data").mkdir(parents=True)
        assert detect.is_web_root(str(root)) is False
        assert detect.find_web_root(str(root)) is None

    def test_encrypted_data_counts_as_game_data(self, tmp_path):
        root = tmp_path / "g"
        (root / "js").mkdir(parents=True)
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "js" / "rmmz_core.js").write_text("// core", encoding="utf-8")
        (root / "data_encrypted").mkdir()
        assert detect.is_web_root(str(root)) is True

    def test_has_game_data_helper(self, tmp_path):
        assert detect.has_game_data(str(tmp_path)) is False
        (tmp_path / "data").mkdir()
        assert detect.has_game_data(str(tmp_path)) is True

    def test_audio_exts(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        exts = detect.audio_exts(web)
        assert ".ogg" in exts

    def test_has_encrypted_extensions_false(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        assert detect.has_encrypted_extensions(web) is False
