#!/usr/bin/env python3
"""The application registry and the
layered resolver: env -> tool_registry -> probe -> PATH.

Split out of tests/test_config.py when rpgmaker/tool_registry.py was split
(PLAN Phase 4): patching a name on the facade no longer reaches the code
that reads it, so each test now patches the module that owns the name.
"""

import ast
import shutil

import json

import subprocess

import pytest

from rpgmaker import platform
from rpgmaker import tool_registry
from rpgmaker import settings


class TestRegistry:
    """The TOOLS table is the single source of truth for applications."""

    def test_keys_unique(self):
        keys = [t.key for t in tool_registry.TOOLS]
        assert len(keys) == len(set(keys))

    def test_every_entry_is_complete(self):
        for tool in tool_registry.TOOLS:
            assert tool.env, tool.key
            assert tool.exe or tool.probe, tool.key
            assert tool.purpose and tool.hint, tool.key
            assert tool.side in ("native", "win32"), tool.key
            assert tool.path_form in ("view", "windows"), tool.key

    def test_resolver_exists_on_config(self):
        # doctor resolves each tool through the tool_registry module so a single
        # tool can be monkeypatched out in tests.
        for tool in tool_registry.TOOLS:
            assert callable(getattr(tool_registry, tool.resolver)), tool.key

    def test_by_key_index(self):
        for tool in tool_registry.TOOLS:
            assert tool_registry.TOOLS_BY_KEY[tool.key] is tool

    def test_win7z_uses_the_7z_config_key(self):
        tool = tool_registry.TOOLS_BY_KEY["win7z"]
        assert tool.cfg == "7z"
        assert tool.path_form == "windows"
        assert tool.resolver == "win_7z"


class TestToolResolution:
    """Layered resolution: env -> tool_registry -> probe -> PATH."""

    def test_env_override_wins(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("FFMPEG", str(exe))
        assert tool_registry.find_ffmpeg() == platform.posix(str(exe))

    def test_env_override_windows_form_for_win_tools(self, monkeypatch,
                                                     tmp_path):
        exe = tmp_path / "7z.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("SEVENZ_WIN", str(exe))
        # path_form == "windows": the value is handed to PowerShell
        got = tool_registry.win_7z()
        assert got.replace("\\", "/") == platform.posix(str(exe))

    def test_env_override_missing_file_falls_through(self, monkeypatch,
                                                     tmp_path):
        monkeypatch.setenv("FFMPEG", str(tmp_path / "nope"))
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert tool_registry.find_ffmpeg() is None

    def test_config_override(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.bin"
        exe.write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path, {"wsl": {"ffmpeg": str(exe)},
                                          "win32": {"ffmpeg": str(exe)}})
        monkeypatch.delenv("FFMPEG", raising=False)
        assert tool_registry.find_ffmpeg() == platform.posix(str(exe))

    def test_config_glob_resolves_newest(self, monkeypatch, tmp_path):
        for ver in ("1.0", "2.0", "10.0"):
            d = tmp_path / (f"ffmpeg-{ver}") / "bin"
            d.mkdir(parents=True)
            (d / "ffmpeg.exe").write_bytes(b"x")
        self._cfg(monkeypatch, tmp_path,
                  {"wsl": {"ffmpeg": "ffmpeg-*/bin/ffmpeg.exe"},
                   "win32": {"ffmpeg": "ffmpeg-*/bin/ffmpeg.exe"}})
        monkeypatch.delenv("FFMPEG", raising=False)
        got = tool_registry.find_ffmpeg()
        assert got.endswith("ffmpeg-10.0/bin/ffmpeg.exe"), got

    def test_config_relative_path_resolves_against_config_dir(
            self, monkeypatch, tmp_path):
        # a relative entry means "relative to the config file's own dir", so
        # the config file itself stays machine-independent
        cfg = tmp_path / "env_config.json"
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
        (tmp_path / "3rd").mkdir()
        exe = tmp_path / "3rd" / "ffmpeg"
        exe.write_bytes(b"x")
        cfg.write_text(json.dumps({"tools": {"wsl": {"ffmpeg": "3rd/ffmpeg"}}}),
                       encoding="utf-8")
        monkeypatch.delenv("FFMPEG", raising=False)
        assert tool_registry.find_ffmpeg() == platform.posix(str(exe))

    def test_win_key_reads_win32_section(self, monkeypatch, tmp_path):
        exe = tmp_path / "7z.exe"
        exe.write_bytes(b"x")
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"tools": {"win32": {"7z": str(exe)}}}),
                       encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("SEVENZ_WIN", raising=False)
        monkeypatch.delenv("SEVENZ", raising=False)
        assert tool_registry.win_7z() == str(exe)

    def test_probe_finds_tool_under_anchor(self, monkeypatch, tmp_path):
        d = tmp_path / "ffmpeg-9.9" / "bin"
        d.mkdir(parents=True)
        exe = d / "ffmpeg.exe"
        exe.write_bytes(b"x")
        monkeypatch.delenv("GT_NO_PROBE", raising=False)
        monkeypatch.setattr(tool_registry, "_anchor_paths", lambda side: [str(tmp_path)])
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert tool_registry.find_ffmpeg() == platform.posix(str(exe))

    def test_probe_skipped_when_disabled(self, monkeypatch, tmp_path):
        d = tmp_path / "ffmpeg-9.9" / "bin"
        d.mkdir(parents=True)
        (d / "ffmpeg.exe").write_bytes(b"x")
        monkeypatch.setenv("GT_NO_PROBE", "1")
        monkeypatch.setattr(tool_registry, "_anchor_paths", lambda side: [str(tmp_path)])
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert tool_registry.find_ffmpeg() is None

    def test_anchors_only_return_existing_dirs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ProgramFiles", str(tmp_path))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "missing"))
        anchors = tool_registry._anchor_paths("win32")
        assert platform.posix(str(tmp_path)) in anchors
        assert platform.posix(str(tmp_path / "missing")) not in anchors

    def test_path_lookup_is_last_resort(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FFMPEG", raising=False)
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE",
                            tmp_path / "absent.json")
        monkeypatch.setattr(shutil, "which",
                            lambda name: "/opt/bin/ffmpeg" if name == "ffmpeg"
                            else None)
        assert tool_registry.find_ffmpeg() == "/opt/bin/ffmpeg"

    def test_not_found_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FFMPEG", raising=False)
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE",
                            tmp_path / "absent.json")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert tool_registry.find_ffmpeg() is None

    def test_resolve_tool_accepts_key_or_entry(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("FFMPEG", str(exe))
        assert tool_registry.resolve_tool("ffmpeg") == platform.posix(str(exe))
        assert tool_registry.resolve_tool(
            tool_registry.TOOLS_BY_KEY["ffmpeg"]) == platform.posix(str(exe))

    def test_resolve_tool_reports_source(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("FFMPEG", str(exe))
        path, source = tool_registry.resolve_tool("ffmpeg", with_source=True)
        assert path == platform.posix(str(exe))
        assert source == "env"
        monkeypatch.delenv("FFMPEG", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert tool_registry.resolve_tool("ffmpeg", with_source=True) == \
            (None, None)

    def test_find_powershell_uses_shared_resolver(self, monkeypatch, tmp_path):
        exe = tmp_path / "powershell.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("POWERSHELL_EXE", str(exe))
        assert tool_registry.find_powershell() == platform.posix(str(exe))

    def test_find_node_shared_with_the_test_harness(self, monkeypatch,
                                                    tmp_path):
        """Node is only used by the KAG audio runtime tests now (syntax
        checking and asar reading are in-process), but the resolver entry
        stays so those tests probe it the same way as every other tool."""
        exe = tmp_path / "node.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("NODE", str(exe))
        assert tool_registry.find_node() == platform.posix(str(exe))

    @staticmethod
    def _cfg(monkeypatch, tmp_path, tools_section):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"tools": tools_section}), encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)


class TestRunPowershell:
    def test_missing_raises_with_cross_system_hint(self, monkeypatch):
        monkeypatch.delenv("POWERSHELL_EXE", raising=False)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        with pytest.raises(FileNotFoundError) as ei:
            tool_registry.run_powershell("Remove-Item x")
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

        monkeypatch.setattr(tool_registry.proctools.subprocess, "run", fake_run)
        r = tool_registry.run_powershell("Get-Date")
        assert seen["cmdline"][-1] == "Get-Date"
        assert "-NoProfile" in seen["cmdline"]
        assert r.stdout == "ok"
        # every external call decodes as UTF-8 (never the host locale codec)
        # and carries a timeout, so a stuck PowerShell cannot hang the run
        assert seen["kwargs"]["encoding"] == "utf-8"
        assert seen["kwargs"]["timeout"] == tool_registry.POWERSHELL_TIMEOUT

    def test_nonzero_exit_raises(self, monkeypatch, tmp_path):
        import subprocess
        exe = tmp_path / "powershell.exe"
        exe.write_bytes(b"x")
        monkeypatch.setenv("POWERSHELL_EXE", str(exe))
        monkeypatch.setattr(
            tool_registry.proctools.subprocess, "run",
            lambda cmdline, **kwargs:
                subprocess.CompletedProcess(cmdline, 1, "", "boom"))
        with pytest.raises(RuntimeError) as ei:
            tool_registry.run_powershell("exit 1")
        assert "powershell failed (1)" in str(ei.value)
        assert "boom" in str(ei.value)


class TestToolStatus:
    """PLAN Phase 4 task 8: a tool's status says who must install it.

    Without this the only signal was a hint string, so a CI image that lacks a
    dev-only tool looked the same as one missing a required encoder.
    """

    EXPECTED = {
        "ffmpeg": "required",
        "node": "test-only",
        "git": "dev-only",
        "powershell": "windows-bridge",
        "win7z": "windows-bridge",
    }

    def test_every_tool_declares_a_status(self):
        for tool in tool_registry.TOOLS:
            assert isinstance(tool.status, tool_registry.ToolStatus), tool.key

    def test_the_assignment_is_pinned(self):
        actual = {t.key: t.status.value for t in tool_registry.TOOLS}
        assert actual == self.EXPECTED

    def test_only_required_is_fatal_when_missing(self):
        fatal = {t.key for t in tool_registry.TOOLS
                 if t.status.missing_is_fatal}
        assert fatal == {"ffmpeg"}

    def test_missing_is_fatal_is_a_status_property(self):
        for status in tool_registry.ToolStatus:
            expected = status is tool_registry.ToolStatus.REQUIRED
            assert status.missing_is_fatal is expected, status

    def test_the_report_carries_the_status(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE",
                            tmp_path / "absent.json")
        rows = {r["key"]: r for r in tool_registry.probe_report()}
        for tool in tool_registry.TOOLS:
            assert rows[tool.key]["status"] == tool.status.value, tool.key


def _resolver_call_sites():
    """{resolver-name: [(rel, lineno)]} for real ``Call`` nodes only.

    AST, not a substring search: an earlier version of this test matched
    ``find_7z(`` inside a docstring and passed a resolver that no module ever
    called.  ``tests/`` is returned separately because a ``test-only`` tool's
    users *are* the tests.
    """
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "*.py"], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace").stdout.split()
    wanted = {t.resolver for t in tool_registry.TOOLS}
    production, tests = {}, {}
    for rel in files:
        with open(rel, encoding="utf-8") as handle:
            try:
                tree = ast.parse(handle.read())
            except SyntaxError as exc:  # pragma: no cover - repo is linted
                raise AssertionError(f"{rel} is not parseable: {exc}") from exc
        bucket = tests if rel.startswith("tests/") else production
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (getattr(node.func, "attr", None)
                    or getattr(node.func, "id", None))
            if name in wanted:
                bucket.setdefault(name, []).append((rel, node.lineno))
    return production, tests


def test_no_dead_resolver_is_registered():
    """PLAN Phase 4 task 8: a resolver with no caller is dead code.

    An entry that nothing resolves hides the fact that the feature it
    described is gone - the same judgement that removed the ``ffprobe``
    lookups (see docs/experience-misc.md 10.4).  ``doctor`` calling every
    resolver through ``getattr(tool_registry, name)`` does NOT count: it
    reports on a tool, it does not use one, so a resolver reachable only from
    doctor would still be dead.

    A ``test-only`` tool is looked for in the tests and every other status in
    production code, because that status is exactly the claim that the tests
    are its users.
    """
    production, tests = _resolver_call_sites()
    for tool in tool_registry.TOOLS:
        if tool.status is tool_registry.ToolStatus.TEST_ONLY:
            callers, where = tests.get(tool.resolver), "the tests"
        else:
            callers, where = production.get(tool.resolver), "production code"
        assert callers, (
            f"tool {tool.key!r} registers resolver {tool.resolver!r} but nothing in {where} calls it - "
            "delete the entry or wire the caller")


def test_no_resolver_is_registered_twice():
    """Two registry entries sharing a resolver would make one unreachable."""
    resolvers = [t.resolver for t in tool_registry.TOOLS]
    assert len(resolvers) == len(set(resolvers))


class TestProbeReport:
    def test_shape_and_sources(self, monkeypatch, tmp_path):
        exe = tmp_path / "ffmpeg.bin"
        exe.write_bytes(b"x")
        monkeypatch.setenv("FFMPEG", str(exe))
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE",
                            tmp_path / "absent.json")
        report = tool_registry.probe_report()
        by = {r["key"]: r for r in report}
        assert set(by) == {t.key for t in tool_registry.TOOLS}
        assert by["ffmpeg"]["path"] == platform.posix(str(exe))
        assert by["ffmpeg"]["source"] == "env"
        assert by["ffmpeg"]["hint"] == ""
        # unresolved tools report None plus their remediation hint
        monkeypatch.delenv("FFMPEG", raising=False)
        by = {r["key"]: r for r in tool_registry.probe_report()}
        assert by["ffmpeg"]["path"] is None
        assert by["ffmpeg"]["source"] is None
        assert by["ffmpeg"]["hint"]
