#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmz/config.py path/platform helpers."""
import os
import sys

import pytest

from rpgmz import config


class TestPathConversions:
    def test_posix_windows_backslashes(self):
        if not hasattr(config, "_posix"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        assert config._posix(r"C:\Games\Foo") == "C:/Games/Foo"

    def test_to_windows_path_wsl_form(self):
        if not hasattr(config, "to_windows_path"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        assert config.to_windows_path("/mnt/d/Games/Foo") == "D:\\Games\\Foo"

    def test_to_windows_path_windows_form_passthrough(self):
        if not hasattr(config, "to_windows_path"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        assert config.to_windows_path(r"C:\Games") == r"C:\Games"

    def test_to_windows_path_non_mnt_unchanged(self):
        if not hasattr(config, "to_windows_path"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        assert config.to_windows_path("/home/user/game") == "/home/user/game"

    def test_to_wsl_path(self):
        if not hasattr(config, "to_wsl_path"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        assert config.to_wsl_path(r"C:\Games\Foo") == "/mnt/c/Games/Foo"

    def test_to_wsl_path_relative_unchanged(self):
        if not hasattr(config, "to_wsl_path"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        assert config.to_wsl_path("Games") == "Games"

    def test_roundtrip(self):
        if not hasattr(config, "to_windows_path") or not hasattr(config, "to_wsl_path"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        for p in ("/mnt/d/Games/Foo", r"D:\Games\Foo"):
            assert config.to_windows_path(p) == r"D:\Games\Foo"
            assert config.to_wsl_path(config.to_windows_path(p)) == "/mnt/d/Games/Foo"

    def test_is_windows_side(self):
        if not hasattr(config, "is_windows_side"):
            pytest.skip("cross-system helpers not merged to this branch yet")
        # Only meaningful inside WSL; on native platforms it is always False.
        if config.is_wsl():
            assert config.is_windows_side("/mnt/c/foo")
            assert not config.is_windows_side("/home/user/foo")
        else:
            assert config.is_windows_side("/mnt/c/foo") is False


class TestConfigLookups:
    def test_env_var_wins(self, monkeypatch, tmp_path):
        p = tmp_path / "ffmpeg.bin"
        p.write_bytes(b"x")
        monkeypatch.setenv("FFMPEG", str(p))
        assert config.find_ffmpeg() == str(p)

    def test_path_fallback(self, monkeypatch):
        monkeypatch.delenv("FFMPEG", raising=False)
        q = config.find_ffmpeg()
        assert isinstance(q, str) and q

    def test_pick_platform_section(self):
        section = {"7z": {"wsl": "/usr/bin/7zz", "win32": "C:/7z.exe"}}
        assert config._pick(section, "7z")

    def test_expand_env_tokens(self, monkeypatch):
        monkeypatch.setenv("TESTVAR", "value")
        assert config._expand("%TESTVAR%/x") == "value/x"

    def test_load_env_config_missing_is_empty(self, monkeypatch):
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            config.REPO_ROOT / "does-not-exist.json")
        assert config._load_env_config() == {}


class TestMagicConstants:
    def test_rpgmv_header_length(self):
        assert len(config.RPGMV_HEADER) == 16

    def test_nwjs_runtime_contains_exe(self):
        assert "Game.exe" in config.NWJS_RUNTIME
