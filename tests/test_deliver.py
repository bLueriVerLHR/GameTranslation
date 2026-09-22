#!/usr/bin/env python3
"""Unit tests for rpgmaker/deliver.py - the Windows-side delivery bridge.

Covers the powershell.exe existence check in _run_powershell(): it must fail
fast with a cross-system hint when the Windows-side PowerShell binary is
missing, and must pass the command through unchanged when it is present.
"""
import subprocess

import pytest

from rpgmaker import deliver


class TestPsQuote:
    """PowerShell single-quote escaping: a folder named "Bob's Game" used to
    produce an unbalanced-quote parse error in the middle of deliver."""

    def test_plain_path_is_wrapped(self):
        assert deliver.ps_quote(r"C:\Games\X") == r"'C:\Games\X'"

    def test_apostrophe_is_doubled(self):
        assert deliver.ps_quote("Bob's Game") == "'Bob''s Game'"

    def test_dollar_and_spaces_stay_literal(self):
        # single quotes suppress PowerShell variable expansion
        assert deliver.ps_quote("$env:TEMP dir") == "'$env:TEMP dir'"

    def test_remove_windows_side_quotes_the_path(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(deliver, "_run_powershell",
                            lambda cmd: seen.setdefault("cmd", cmd))
        deliver._remove_windows_side(r"D:\Games\Bob's Game")
        assert "'D:\\Games\\Bob''s Game'" in seen["cmd"]


class TestRunPowershell:
    def test_missing_powershell_raises_with_hint(self, monkeypatch):
        # WSL image without WSLInterop / no PowerShell anywhere: fail fast.
        monkeypatch.delenv("POWERSHELL_EXE", raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(FileNotFoundError) as ei:
            deliver._run_powershell("Remove-Item x")
        msg = str(ei.value)
        assert "powershell.exe not found" in msg
        assert "install PowerShell on the Windows side" in msg
        assert "请在 Windows 侧安装 PowerShell" in msg

    def test_powershell_present_passes_command(self, monkeypatch):
        # Present binary: the command is handed to it and its exit code
        # decides success.
        exe = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        monkeypatch.delenv("POWERSHELL_EXE", raising=False)
        monkeypatch.setattr("shutil.which",
                            lambda name: exe if name == "powershell.exe"
                            else None)
        calls = {}

        def fake_run(cmdline, **kwargs):
            calls["cmdline"] = cmdline
            calls["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmdline, 0, stdout="ok",
                                               stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        r = deliver._run_powershell("Remove-Item -LiteralPath 'x'")
        assert calls["cmdline"][0] == exe
        assert calls["cmdline"][-1] == "Remove-Item -LiteralPath 'x'"
        assert "-NoProfile" in calls["cmdline"]
        assert r.stdout == "ok"
        # shared runner contract: UTF-8 decoding + a finite timeout
        assert calls["kwargs"]["encoding"] == "utf-8"
        assert isinstance(calls["kwargs"]["timeout"], (int, float))

    def test_powershell_nonzero_exit_raises_runtime_error(self, monkeypatch):
        exe = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        monkeypatch.delenv("POWERSHELL_EXE", raising=False)
        monkeypatch.setattr("shutil.which",
                            lambda name: exe if name == "powershell.exe"
                            else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmdline, **kwargs:
                subprocess.CompletedProcess(cmdline, 1, stdout="",
                                            stderr="boom"))
        with pytest.raises(RuntimeError) as ei:
            deliver._run_powershell("exit 1")
        assert "powershell failed (1)" in str(ei.value)
        assert "boom" in str(ei.value)
