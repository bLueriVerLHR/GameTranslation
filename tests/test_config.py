#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/config.py - platform mapping, application
resolution and location derivation.

Covers the single-native-form path convention (a path is stored once, in the
form of the platform that owns the resource) and the layered application
resolver: environment override -> explicit local config (globs allowed) ->
probing of well-known install locations -> PATH, with the probe layer
disabled globally by tests/conftest.py unless a test opts in.
"""
import json
import logging
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
    """localize() maps a stored native path to the current platform's view."""

    def test_wsl_windows_form_converted(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.localize("D:/Games") == "/mnt/d/Games"
        assert config.localize(r"C:\Games") == "/mnt/c/Games"

    def test_wsl_native_passthrough(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.localize("/tmp/opencode") == "/tmp/opencode"
        assert config.localize("3rd/7zz") == "3rd/7zz"

    def test_win32_mnt_form_converted(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: False)
        assert config.localize("/mnt/d/Games") == "D:\\Games"

    def test_win32_native_passthrough(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: False)
        assert config.localize("D:/Games") == "D:/Games"
        assert config.localize("/home/user/game") == "/home/user/game"

    def test_empty_input(self, monkeypatch):
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.localize("") == ""
        assert config.localize(None) is None


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


class TestExpand:
    def test_env_token(self, monkeypatch):
        monkeypatch.setenv("TESTVAR", "value")
        assert config._expand("%TESTVAR%/x") == "value/x"

    def test_unknown_token_passthrough(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        assert config._expand("%NO_SUCH_VAR%/x") == "%NO_SUCH_VAR%/x"

    def test_separators_normalized(self):
        assert config._expand(r"C:\a\b") == "C:/a/b"


class TestRegistry:
    """The TOOLS table is the single source of truth for applications."""

    def test_keys_unique(self):
        keys = [t.key for t in config.TOOLS]
        assert len(keys) == len(set(keys))

    def test_every_entry_is_complete(self):
        for tool in config.TOOLS:
            assert tool.env, tool.key
            assert tool.exe or tool.probe, tool.key
            assert tool.purpose and tool.hint, tool.key
            assert tool.side in ("native", "win32"), tool.key
            assert tool.path_form in ("view", "windows"), tool.key

    def test_resolver_exists_on_config(self):
        # doctor resolves each tool through the config module so a single
        # tool can be monkeypatched out in tests.
        for tool in config.TOOLS:
            assert callable(getattr(config, tool.resolver)), tool.key

    def test_by_key_index(self):
        for tool in config.TOOLS:
            assert config.TOOLS_BY_KEY[tool.key] is tool

    def test_win7z_uses_the_7z_config_key(self):
        tool = config.TOOLS_BY_KEY["win7z"]
        assert tool.cfg == "7z"
        assert tool.path_form == "windows"
        assert tool.resolver == "win_7z"


class TestToolResolution:
    """Layered resolution: env -> config -> probe -> PATH."""

    def test_env_override_wins(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("FFMPEG", str(exe))
        assert config.find_ffmpeg() == config._posix(str(exe))

    def test_env_override_windows_form_for_win_tools(self, monkeypatch,
                                                     tmp_path):
        exe = tmp_path / "7z.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("SEVENZ_WIN", str(exe))
        # path_form == "windows": the value is handed to PowerShell
        got = config.win_7z()
        assert got.replace("\\", "/") == config._posix(str(exe))

    def test_env_override_missing_file_falls_through(self, monkeypatch,
                                                     tmp_path):
        monkeypatch.setenv("FFMPEG", str(tmp_path / "nope"))
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert config.find_ffmpeg() is None

    def test_config_override(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.bin"
        exe.write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path, {"wsl": {"ffmpeg": str(exe)},
                                          "win32": {"ffmpeg": str(exe)}})
        monkeypatch.delenv("FFMPEG", raising=False)
        assert config.find_ffmpeg() == config._posix(str(exe))

    def test_config_glob_resolves_newest(self, monkeypatch, tmp_path):
        for ver in ("1.0", "2.0", "10.0"):
            d = tmp_path / ("ffmpeg-%s" % ver) / "bin"
            d.mkdir(parents=True)
            (d / "ffmpeg.exe").write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path,
                  {"wsl": {"ffmpeg": "ffmpeg-*/bin/ffmpeg.exe"},
                   "win32": {"ffmpeg": "ffmpeg-*/bin/ffmpeg.exe"}})
        monkeypatch.delenv("FFMPEG", raising=False)
        got = config.find_ffmpeg()
        assert got.endswith("ffmpeg-10.0/bin/ffmpeg.exe"), got

    def test_config_relative_path_resolves_against_config_dir(
            self, monkeypatch, tmp_path):
        # a relative entry means "relative to docs/table/", so the config file
        # itself stays machine-independent
        cfg = tmp_path / "env_config.json"
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        (tmp_path / "3rd").mkdir()
        exe = tmp_path / "3rd" / "7zz"
        exe.write_bytes(b"x")
        cfg.write_text(json.dumps({"tools": {"wsl": {"7z": "3rd/7zz"}}}),
                       encoding="utf-8")
        monkeypatch.delenv("SEVENZ", raising=False)
        assert config.find_7z() == config._posix(str(exe))

    def test_win_key_reads_win32_section(self, monkeypatch, tmp_path):
        exe = tmp_path / "7z.exe"
        exe.write_bytes(b"x")
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"tools": {"win32": {"7z": str(exe)}}}),
                       encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("SEVENZ_WIN", raising=False)
        monkeypatch.delenv("SEVENZ", raising=False)
        assert config.win_7z() == str(exe)

    def test_probe_finds_tool_under_anchor(self, monkeypatch, tmp_path):
        d = tmp_path / "ffmpeg-9.9" / "bin"
        d.mkdir(parents=True)
        exe = d / "ffmpeg.exe"
        exe.write_bytes(b"x")
        monkeypatch.delenv("GT_NO_PROBE", raising=False)
        monkeypatch.setattr(config, "_anchor_paths", lambda side: [str(tmp_path)])
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert config.find_ffmpeg() == config._posix(str(exe))

    def test_probe_skipped_when_disabled(self, monkeypatch, tmp_path):
        d = tmp_path / "ffmpeg-9.9" / "bin"
        d.mkdir(parents=True)
        (d / "ffmpeg.exe").write_bytes(b"x")
        monkeypatch.setenv("GT_NO_PROBE", "1")
        monkeypatch.setattr(config, "_anchor_paths", lambda side: [str(tmp_path)])
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert config.find_ffmpeg() is None

    def test_anchors_only_return_existing_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "missing"))
        anchors = config._anchor_paths("win32")
        assert config._posix(str(tmp_path)) in anchors
        assert config._posix(str(tmp_path / "missing")) not in anchors

    def test_path_lookup_is_last_resort(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FFMPEG", raising=False)
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            tmp_path / "absent.json")
        monkeypatch.setattr(shutil, "which",
                            lambda name: "/opt/bin/ffmpeg" if name == "ffmpeg"
                            else None)
        assert config.find_ffmpeg() == "/opt/bin/ffmpeg"

    def test_not_found_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FFMPEG", raising=False)
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            tmp_path / "absent.json")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert config.find_ffmpeg() is None

    def test_resolve_tool_accepts_key_or_entry(self, monkeypatch, tmp_path):
        exe = tmp_path / "rg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("RG", str(exe))
        assert config.resolve_tool("rg") == config._posix(str(exe))
        assert config.resolve_tool(config.TOOLS_BY_KEY["rg"]) == \
            config._posix(str(exe))

    def test_resolve_tool_reports_source(self, monkeypatch, tmp_path):
        exe = tmp_path / "rg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("RG", str(exe))
        path, source = config.resolve_tool("rg", with_source=True)
        assert path == config._posix(str(exe))
        assert source == "env"
        monkeypatch.delenv("RG", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert config.resolve_tool("rg", with_source=True) == (None, None)

    def test_find_powershell_uses_shared_resolver(self, monkeypatch, tmp_path):
        exe = tmp_path / "powershell.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("POWERSHELL_EXE", str(exe))
        assert config.find_powershell() == config._posix(str(exe))

    def test_find_node_shared_with_the_test_harness(self, monkeypatch,
                                                    tmp_path):
        """Node is only used by the KAG audio runtime tests now (syntax
        checking and asar reading are in-process), but the resolver entry
        stays so those tests probe it the same way as every other tool."""
        exe = tmp_path / "node.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("NODE", str(exe))
        assert config.find_node() == config._posix(str(exe))

    @staticmethod
    def _cfg(monkeypatch, tmp_path, tools_section):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"tools": tools_section}), encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)


class TestRunPowershell:
    def test_missing_raises_with_cross_system_hint(self, monkeypatch):
        monkeypatch.delenv("POWERSHELL_EXE", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        with pytest.raises(FileNotFoundError) as ei:
            config.run_powershell("Remove-Item x")
        msg = str(ei.value)
        assert "powershell.exe not found" in msg
        assert "Windows 侧安装 PowerShell" in msg

    def test_passes_command_and_returns_result(self, monkeypatch, tmp_path):
        import subprocess
        exe = tmp_path / "powershell.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("POWERSHELL_EXE", str(exe))
        seen = {}

        def fake_run(cmdline, **kwargs):
            seen["cmdline"] = cmdline
            seen["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmdline, 0, "ok", "")

        monkeypatch.setattr(config.proctools.subprocess, "run", fake_run)
        r = config.run_powershell("Get-Date")
        assert seen["cmdline"][-1] == "Get-Date"
        assert "-NoProfile" in seen["cmdline"]
        assert r.stdout == "ok"
        # every external call decodes as UTF-8 (never the host locale codec)
        # and carries a timeout, so a stuck PowerShell cannot hang the run
        assert seen["kwargs"]["encoding"] == "utf-8"
        assert seen["kwargs"]["timeout"] == config.POWERSHELL_TIMEOUT

    def test_nonzero_exit_raises(self, monkeypatch, tmp_path):
        import subprocess
        exe = tmp_path / "powershell.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("POWERSHELL_EXE", str(exe))
        monkeypatch.setattr(
            config.proctools.subprocess, "run",
            lambda cmdline, **kwargs:
                subprocess.CompletedProcess(cmdline, 1, "", "boom"))
        with pytest.raises(RuntimeError) as ei:
            config.run_powershell("exit 1")
        assert "powershell failed (1)" in str(ei.value)
        assert "boom" in str(ei.value)


class TestProbeReport:
    def test_shape_and_sources(self, monkeypatch, tmp_path):
        exe = tmp_path / "rg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("RG", str(exe))
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            tmp_path / "absent.json")
        report = config.probe_report()
        by = {r["key"]: r for r in report}
        assert set(by) == {t.key for t in config.TOOLS}
        assert by["rg"]["path"] == config._posix(str(exe))
        assert by["rg"]["source"] == "env"
        assert by["rg"]["hint"] == ""
        # unresolved tools report None plus their remediation hint
        assert by["ffmpeg"]["path"] is None
        assert by["ffmpeg"]["source"] is None
        assert by["ffmpeg"]["hint"]


class TestDeliverable:
    """Single native-form path in config; localized for the current platform."""

    _HOME = "/home/tester"

    def _cfg(self, monkeypatch, tmp_path, deliverables):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"deliverables": deliverables}),
                       encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.setattr(config, "_home_dir", lambda: self._HOME)
        monkeypatch.delenv("GAMES_DIR", raising=False)
        monkeypatch.delenv("ARCHIVES_DIR", raising=False)

    def _isolate_probe(self, monkeypatch, tmp_path, workspace=None,
                       roots=()):
        """Probe only the given roots, so the host's own Games folders never
        influence the assertion."""
        monkeypatch.delenv("GT_NO_PROBE", raising=False)
        monkeypatch.setattr(config, "workspace_root",
                            lambda: config._posix(str(workspace or tmp_path)))
        monkeypatch.setattr(config, "_volume_roots",
                            lambda: [config._posix(str(r)) for r in roots])
        monkeypatch.setattr(config, "_home_dir", lambda: self._HOME)

    def test_games_native_form_localized(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"games": "D:/Games"})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.games_dir() == "/mnt/d/Games"

    def test_env_var_wins(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"games": "D:/Games"})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        monkeypatch.setenv("GAMES_DIR", "/mnt/d/Other")
        assert config.games_dir() == "/mnt/d/Other"

    def test_unconfigured_derives_default_from_workspace(self, monkeypatch,
                                                         tmp_path):
        # Nothing configured and nothing probed -> the workspace root beside
        # this checkout is the base, created on demand by deliver.
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(config, "workspace_root",
                            lambda: "/work/ws")
        monkeypatch.setattr(config, "_volume_roots", lambda: [])
        assert config.games_dir() == "/work/ws/Games"
        assert config.archives_dir() == "/work/ws/GamesCompress"

    def test_workspace_sibling_folder_is_adopted(self, monkeypatch, tmp_path):
        # The documented layout: output lives beside the project, so an
        # existing <workspace>/Games is used without any configuration.
        self._cfg(monkeypatch, tmp_path, {})
        (tmp_path / "Games").mkdir()
        (tmp_path / "GamesCompress").mkdir()
        self._isolate_probe(monkeypatch, tmp_path)
        assert config.games_dir() == config._posix(str(tmp_path / "Games"))
        assert config.archives_dir() == \
            config._posix(str(tmp_path / "GamesCompress"))

    def test_probe_bases_put_the_workspace_first(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(config, "workspace_root", lambda: "/work/ws")
        monkeypatch.setattr(config, "_volume_roots",
                            lambda: ["/mnt/c", "/mnt/d"])
        bases = config._deliverable_bases()
        assert bases[0] == "/work/ws"
        assert bases[1:3] == ["/mnt/c", "/mnt/d"]
        assert bases[-1] == self._HOME
        assert len(bases) == len(set(bases))

    def test_existing_conventional_folder_on_a_volume_is_adopted(
            self, monkeypatch, tmp_path):
        # The probe also adopts a conventionally named folder on a volume
        # root, so an operator who keeps output outside the workspace is
        # picked up automatically.
        self._cfg(monkeypatch, tmp_path, {})
        (tmp_path / "Games").mkdir()
        self._isolate_probe(monkeypatch, tmp_path, workspace=tmp_path / "other",
                            roots=(tmp_path,))
        assert config.games_dir() == config._posix(str(tmp_path / "Games"))

    def test_probe_ignores_missing_conventional_folder(self, monkeypatch,
                                                       tmp_path):
        monkeypatch.delenv("GT_NO_PROBE", raising=False)
        monkeypatch.setattr(config, "workspace_root", lambda: "/work/none")
        monkeypatch.setattr(config, "_volume_roots", lambda: [])
        monkeypatch.setattr(config, "_home_dir", lambda: self._HOME)
        assert config._probe_deliverable("archives") is None
        assert config._probe_deliverable("games") is None

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
                            "win32": "C:/Temp"}})
        monkeypatch.setattr(config, "is_wsl", lambda: False)
        assert config.temp_dir() == "C:/Temp"

    def test_temp_nested_dict_win_temp_dir(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"temp": {"persist": "/home/me/forge/tmp",
                            "tmpfs": "/tmp/opencode",
                            "win32": "C:/Temp"}})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.win_temp_dir() == "/mnt/c/Temp"

    def test_temp_missing_nested_falls_back_to_legacy(self, monkeypatch,
                                                      tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(config, "is_wsl", lambda: True)
        assert config.temp_dir() == "/tmp/opencode"


class TestLoadEnvConfig:
    def test_missing_file_is_empty(self, monkeypatch):
        monkeypatch.setattr(config, "LOCAL_ENV_FILE",
                            config.REPO_ROOT / "does-not-exist.json")
        assert config._load_env_config() == {}

    def test_corrupt_file_is_empty(self, monkeypatch, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{ not json", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        assert config._load_env_config() == {}

    def test_reads_platform_and_overrides(self, monkeypatch, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"platform": "wsl"}), encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        assert config._load_env_config()["platform"] == "wsl"


class TestCreatable:
    def test_existing_dir(self, tmp_path):
        assert config._creatable(str(tmp_path))

    def test_missing_leaf_under_existing_dir(self, tmp_path):
        assert config._creatable(str(tmp_path / "a" / "b"))

    def test_blocked_by_a_file_ancestor(self, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        assert config._creatable(str(blocker / "games")) is False


class TestDefaultNote:
    """The 'we derived this folder' note is informational and once-only."""

    @staticmethod
    def _cfg(monkeypatch, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.setattr(config, "_home_dir", lambda: "/home/tester")
        monkeypatch.delenv("GAMES_DIR", raising=False)

    def test_default_notes_once_for_derived_default(self, monkeypatch,
                                                    tmp_path, caplog):
        self._cfg(monkeypatch, tmp_path)
        monkeypatch.setattr(config, "workspace_root", lambda: "/work/ws")
        monkeypatch.setattr(config, "_volume_roots", lambda: [])
        with caplog.at_level(logging.INFO, logger="rpgmaker.config"):
            config.games_dir()
            config.games_dir()
        notes = [r.message for r in caplog.records
                 if "deliverables.games" in r.message]
        assert len(notes) == 1
        assert all(r.levelno == logging.INFO for r in caplog.records)

    def test_no_note_when_configured(self, monkeypatch, tmp_path, caplog):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps(
            {"deliverables": {"games": "/tmp/somewhere"}}), encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("GAMES_DIR", raising=False)
        with caplog.at_level(logging.INFO, logger="rpgmaker.config"):
            assert config.games_dir() == "/tmp/somewhere"
        assert not [r for r in caplog.records
                    if "deliverables.games" in r.message]

    def test_no_note_when_env_set(self, monkeypatch, tmp_path, caplog):
        self._cfg(monkeypatch, tmp_path)
        monkeypatch.setenv("GAMES_DIR", "/tmp/from-env")
        with caplog.at_level(logging.INFO, logger="rpgmaker.config"):
            assert config.games_dir() == "/tmp/from-env"
        assert not [r for r in caplog.records
                    if "deliverables.games" in r.message]


class TestFonts:
    def test_cjk_font_env_override(self, monkeypatch, tmp_path):
        f = tmp_path / "cjk.otf"
        f.write_bytes(b"x")
        monkeypatch.setenv("CJK_FONT_PATH", str(f))
        assert config.find_cjk_font() == str(f)

    def test_jp_font_env_override(self, monkeypatch, tmp_path):
        f = tmp_path / "jp.otf"
        f.write_bytes(b"x")
        monkeypatch.setenv("JP_FONT_PATH", str(f))
        assert config.find_jp_font() == str(f)

    def test_missing_fonts_return_none(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CJK_FONT_PATH", raising=False)
        monkeypatch.delenv("JP_FONT_PATH", raising=False)
        monkeypatch.setattr(config, "FONTS_DIR", tmp_path / "no-fonts")
        monkeypatch.setattr(config, "_read_font_paths", lambda: [])
        assert config.find_cjk_font() is None
        assert config.find_jp_font() is None


class TestMagicConstants:
    def test_rpgmv_header_length(self):
        assert len(config.RPGMV_HEADER) == 16

    def test_nwjs_runtime_contains_exe(self):
        assert "Game.exe" in config.NWJS_RUNTIME

    def test_no_hardcoded_tool_paths(self):
        # Machine paths must never live in the repo: the resolver probes for
        # them instead. Guard against a regression that re-introduces one.
        src = (config.REPO_ROOT / "rpgmaker" / "config.py").read_text(
            encoding="utf-8")
        assert "Program Files" not in src or "%ProgramFiles%" in src
        assert "DEFAULT_SEVENZ" not in src
        assert "DEFAULT_FFMPEG_DIR" not in src
