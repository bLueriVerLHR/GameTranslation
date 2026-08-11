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

    def test_audio_exts(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        exts = detect.audio_exts(web)
        assert ".ogg" in exts

    def test_has_encrypted_extensions_false(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        assert detect.has_encrypted_extensions(web) is False
