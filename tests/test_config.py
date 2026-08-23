#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/config.py path/platform helpers.

Covers the single-native-form path convention: every path is stored once
in the form of the platform where the resource lives; the code detects the
current platform and converts (_localize -> to_wsl_path/to_windows_path).
Tools are indexed [platform][tool] because the binaries differ per side.
"""
import json
import logging
import os
import shutil
import sys

import pytest

from rpgmaker import config


class TestPathConversions:
    def test_posix_windows_backslashes(self):
        assert config._posix(r"C:\Games\Foo") == "C:/Games/Foo"

    def test_to_windows_path_wsl_form(self):
        assert config.to_windows_path("/mnt/d/Games/Foo") == "D:\\Games\\Foo"

    def test_to_windows_path_windows_form_passthrough(self):
        assert config.to_windows_path(r"C:\Games") == r"C:\Games"

    def test_to_windows_path_non_mnt_unchanged(self):
        assert config.to_windows_path("/home/user/game") == "/home/user/game"

    def test_to_wsl_path(self):
        assert config.to_wsl_path(r"C:\Games\Foo") == "/mnt/c/Games/Foo"

    def test_to_wsl_path_relative_unchanged(self):
        assert config.to_wsl_path("Games") == "Games"

    def test_roundtrip(self):
        for p in ("/mnt/d/Games/Foo", r"D:\Games\Foo"):
            assert config.to_windows_path(p) == r"D:\Games\Foo"
            assert config.to_wsl_path(config.to_windows_path(p)) == "/mnt/d/Games/Foo"

    def test_is_windows_side(self):
        # Only meaningful inside WSL; on native platforms it is always False.
        if config.is_wsl():
            assert config.is_windows_side("/mnt/c/foo")
            assert not config.is_windows_side("/home/user/foo")
        else:
            assert config.is_windows_side("/mnt/c/foo") is False


class TestLocalize:
    """_localize maps a stored native path to the current platform's view."""

    def test_wsl_windows_form_converted(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config._localize("D:/Games") == "/mnt/d/Games"
        assert config._localize(r"C:\Games") == "/mnt/c/Games"

    def test_wsl_native_passthrough(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config._localize("/tmp/opencode") == "/tmp/opencode"
        assert config._localize("3rd/7zz") == "3rd/7zz"

    def test_win32_mnt_form_converted(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: False)
        assert config._localize("/mnt/d/Games") == "D:\\Games"

    def test_win32_native_passthrough(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: False)
        assert config._localize("D:/Games") == "D:/Games"
        assert config._localize("/home/user/game") == "/home/user/game"

    def test_empty_input(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config._localize("") == ""
        assert config._localize(None) is None


class TestPick:
    """Plain name -> value lookups (no per-key platform mapping anymore)."""

    def test_plain_value(self):
        assert config._pick({"a": "x"}, "a") == "x"

    def test_missing_key(self):
        assert config._pick({"a": "x"}, "b") is None

    def test_non_dict(self):
        assert config._pick(None, "a") is None
        assert config._pick("str", "a") is None


class TestSectionPlatform:
    """Platform-first sections: {wsl: {...}, win32: {...}}."""

    def test_wsl_subdict(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        sec = {"wsl": {"7z": "3rd/7zz"}, "win32": {"7z": "C:/7z.exe"}}
        assert config._section_platform(sec) == {"7z": "3rd/7zz"}

    def test_win32_subdict(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: False)
        monkeypatch.setattr(sys, "platform", "win32")
        sec = {"wsl": {"7z": "3rd/7zz"}, "win32": {"7z": "C:/7z.exe"}}
        assert config._section_platform(sec) == {"7z": "C:/7z.exe"}

    def test_plain_section_passthrough(self):
        assert config._section_platform({"a": "x"}) == {"a": "x"}

    def test_empty_and_non_dict(self):
        assert config._section_platform(None) == {}
        assert config._section_platform("str") == {}
        assert config._section_platform({"wsl": {}, "win32": {}}) == {}


class TestWin32Section:
    """Windows-only tools must be found regardless of the current platform."""

    def test_win32_subdict(self):
        sec = {"wsl": {"7z": "x"}, "win32": {"7z": "C:/7z.exe"}}
        assert config._win32_section(sec) == {"7z": "C:/7z.exe"}

    def test_missing_and_non_dict(self):
        assert config._win32_section({"wsl": {"7z": "x"}}) == {}
        assert config._win32_section(None) == {}
        assert config._win32_section("str") == {}


class TestDeliverable:
    """Single native-form path in config; localized for the current platform."""

    def _cfg(self, monkeypatch, tmp_path, deliverables):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"deliverables": deliverables}),
                       encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)

    def test_games_native_form_localized(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"games": "D:/Games"})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.games_dir() == "/mnt/d/Games"

    def test_env_var_wins(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"games": "D:/Games"})
        monkeypatch.setenv("GAMES_DIR", "/mnt/d/Other")
        assert config.games_dir() == "/mnt/d/Other"

    def test_missing_config_default_localized(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.games_dir() == "/mnt/d/Games"

    def test_temp_native_posix(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"temp": "/tmp/opencode"})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.temp_dir() == "/tmp/opencode"

    def test_win_temp_localized(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"win_temp": "C:/Users/me/AppData/Local/Temp"})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.win_temp_dir() == "/mnt/c/Users/me/AppData/Local/Temp"

    def test_temp_nested_dict_persist_on_wsl(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"temp": {"persist": "/home/me/forge/tmp",
                            "tmpfs": "/tmp/opencode",
                            "win32": "%LOCALAPPDATA%/Temp"}})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.temp_dir() == "/home/me/forge/tmp"

    def test_temp_nested_dict_win32_on_windows(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"temp": {"persist": "/home/me/forge/tmp",
                            "tmpfs": "/tmp/opencode",
                            "win32": "C:/Users/me/AppData/Local/Temp"}})
        monkeypatch.setattr(config, "is_wsl", lambda: False)
        assert config.temp_dir() == "C:/Users/me/AppData/Local/Temp"

    def test_temp_nested_dict_win_temp_dir(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"temp": {"persist": "/home/me/forge/tmp",
                            "tmpfs": "/tmp/opencode",
                            "win32": "C:/Users/me/AppData/Local/Temp"}})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.win_temp_dir() == "/mnt/c/Users/me/AppData/Local/Temp"

    def test_temp_missing_nested_falls_back_to_legacy(self, monkeypatch,
                                                      tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.temp_dir() == "/tmp/opencode"


class TestWinTools:
    """Windows-side tools resolve from env_config tools.win32.<name>."""

    def _cfg(self, monkeypatch, tmp_path, win32_tools):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"tools": {"win32": win32_tools}}),
                       encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)

    def test_ffmpeg_resolved(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.exe"
        exe.write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path, {"ffmpeg": str(exe)})
        assert config.win_ffmpeg() == str(exe)

    def test_ffmpeg_missing_entry_returns_none(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.delenv("WIN_FFMPEG", raising=False)
        assert config.win_ffmpeg() is None

    def test_ffmpeg_missing_file_returns_none(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"ffmpeg": str(tmp_path / "nope.exe")})
        monkeypatch.delenv("WIN_FFMPEG", raising=False)
        assert config.win_ffmpeg() is None

    def test_env_var_wins(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.exe"
        exe.write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path, {"ffmpeg": str(tmp_path / "other.exe")})
        monkeypatch.setenv("WIN_FFMPEG", str(exe))
        assert config.win_ffmpeg() == str(exe)

    def test_unresolvable_config_falls_back_to_default(self, monkeypatch,
                                                       tmp_path):
        # %ProgramFiles% tokens cannot expand on WSL: the configured value
        # is truthy but points nowhere; the working default must win.
        self._cfg(monkeypatch, tmp_path,
                  {"7z": "%ProgramFiles%/7-Zip-Zstandard/7z.exe"})
        monkeypatch.delenv("SEVENZ_WIN", raising=False)
        if os.path.isfile(config.to_wsl_path(config.DEFAULT_WIN_SEVENZ)):
            assert config.win_7z() == config.DEFAULT_WIN_SEVENZ
        else:
            assert config.win_7z() is None

    def test_unresolvable_config_no_default_returns_none(self, monkeypatch,
                                                         tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"ffmpeg": "%ProgramFiles%/nope/ffmpeg.exe"})
        monkeypatch.delenv("WIN_FFMPEG", raising=False)
        assert config.win_ffmpeg() is None

    def test_rg_resolved(self, monkeypatch, tmp_path):
        exe = tmp_path / "rg.exe"
        exe.write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path, {"rg": str(exe)})
        assert config.win_rg() == str(exe)

    def test_7z_configured(self, monkeypatch, tmp_path):
        exe = tmp_path / "7z.exe"
        exe.write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path, {"7z": str(exe)})
        monkeypatch.delenv("SEVENZ_WIN", raising=False)
        assert config.win_7z() == str(exe)

    def test_7z_default_fallback_none(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.delenv("SEVENZ_WIN", raising=False)
        monkeypatch.setattr(config, "DEFAULT_WIN_SEVENZ", "")
        assert config.win_7z() is None


class TestFindToolPlatformSection:
    """_find_tool reads the current platform's tools sub-dict."""

    def test_7z_resolved_from_wsl_section(self, monkeypatch, tmp_path):
        cfg = tmp_path / "env_config.json"
        sevenz = tmp_path / "3rd" / "7zz"
        sevenz.parent.mkdir()
        sevenz.write_bytes(b"x")
        cfg.write_text(json.dumps({"tools": {"wsl": {"7z": "3rd/7zz"}}}),
                       encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("SEVENZ", raising=False)
        assert config.find_7z() == str(sevenz)


class TestConfigLookups:
    def test_env_var_wins(self, monkeypatch, tmp_path):
        p = tmp_path / "ffmpeg.bin"
        p.write_bytes(b"x")
        monkeypatch.setenv("FFMPEG", str(p))
        assert config.find_ffmpeg() == str(p)

    def test_path_fallback(self, monkeypatch, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("FFMPEG", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
        assert config.find_ffmpeg() == "/usr/bin/ffmpeg"

    def test_find_tool_not_found_returns_none(self, monkeypatch, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("FFMPEG", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert config.find_ffmpeg() is None
        assert config._find_tool("FFMPEG", "ffmpeg", "", ("ffmpeg",)) is None

    def test_expand_env_tokens(self, monkeypatch):
        monkeypatch.setenv("TESTVAR", "value")
        assert config._expand("%TESTVAR%/x") == "value/x"

    def test_expand_unknown_token_passthrough(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        assert config._expand("%NO_SUCH_VAR%/x") == "%NO_SUCH_VAR%/x"

    def test_load_env_config_missing_is_empty(self, monkeypatch):
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            config.REPO_ROOT / "does-not-exist.json")
        assert config._load_env_config() == {}


class TestMagicConstants:
    def test_rpgmv_header_length(self):
        assert len(config.RPGMV_HEADER) == 16

    def test_nwjs_runtime_contains_exe(self):
        assert "Game.exe" in config.NWJS_RUNTIME


class TestMissingDefaultWarnings:
    """Review §6.2 / E: a built-in default (Windows 7z, D:/ deliverable
    folders) whose path does not exist must log a WARNING - but exactly ONCE
    per process, so a long batch calling config repeatedly does not spam.

    Every test resets the module sentinel so the once-per-process guarantee
    is asserted in isolation (a prior test in the session may have already
    logged the same tag).
    """

    @staticmethod
    def _reset(monkeypatch):
        monkeypatch.setattr(config, "_warned_defaults", set())

    def _warns(self, caplog, needle):
        return [r.message for r in caplog.records
                if r.levelno >= logging.WARNING and needle in r.message]

    def test_win7z_default_missing_warns_once(self, monkeypatch, caplog):
        self._reset(monkeypatch)
        # default not present -> win_7z() resolves to None and warns once
        monkeypatch.setattr(config, "DEFAULT_WIN_SEVENZ", r"C:\missing\7z.exe")
        monkeypatch.delenv("SEVENZ_WIN", raising=False)
        with caplog.at_level(logging.WARNING, logger="rpgmaker.config"):
            assert config.win_7z() is None
            assert config.win_7z() is None   # second call -> still one warn
        warns = self._warns(caplog, "Windows 7z")
        assert len(warns) == 1

    def test_win7z_configured_no_warn(self, monkeypatch, caplog, tmp_path):
        self._reset(monkeypatch)
        exe = tmp_path / "7z.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("SEVENZ_WIN", str(exe))
        with caplog.at_level(logging.WARNING, logger="rpgmaker.config"):
            assert config.win_7z() == str(exe)
        assert self._warns(caplog, "Windows 7z") == []

    def test_games_dir_default_missing_warns_once(self, monkeypatch, caplog):
        self._reset(monkeypatch)
        monkeypatch.delenv("GAMES_DIR", raising=False)
        # empty env_config -> built-in default used; force it "missing" so
        # the WARN fires regardless of the host filesystem
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            config.REPO_ROOT / "does-not-exist.json")
        monkeypatch.setattr(config.os.path, "exists", lambda p: False)
        with caplog.at_level(logging.WARNING, logger="rpgmaker.config"):
            p = config.games_dir()
            assert p.endswith("Games")
            config.games_dir()
        warns = self._warns(caplog, "deliverables.games")
        assert len(warns) == 1

    def test_games_dir_configured_no_warn(self, monkeypatch, caplog, tmp_path):
        self._reset(monkeypatch)
        target = tmp_path / "Games"
        target.mkdir()
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"deliverables": {"games": str(target)}}),
                       encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("GAMES_DIR", raising=False)
        with caplog.at_level(logging.WARNING, logger="rpgmaker.config"):
            assert config.games_dir() == str(target)
        assert self._warns(caplog, "deliverables.games") == []

    def test_archives_dir_default_missing_warns_once(self, monkeypatch,
                                                     caplog):
        self._reset(monkeypatch)
        monkeypatch.delenv("ARCHIVES_DIR", raising=False)
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            config.REPO_ROOT / "does-not-exist.json")
        monkeypatch.setattr(config.os.path, "exists", lambda p: False)
        with caplog.at_level(logging.WARNING, logger="rpgmaker.config"):
            config.archives_dir()
            config.archives_dir()
        warns = self._warns(caplog, "deliverables.archives")
        assert len(warns) == 1
