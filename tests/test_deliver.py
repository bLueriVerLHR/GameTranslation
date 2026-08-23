#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/deliver.py - the Windows-side delivery bridge.

Covers the powershell.exe existence check in _run_powershell(): it must fail
fast with a cross-system hint when the Windows-side PowerShell binary is
missing, and must pass the command through unchanged when it is present.
"""
import subprocess

import pytest

from rpgmaker import deliver


class TestRunPowershell:
    def test_missing_powershell_raises_with_hint(self, monkeypatch):
        # WSL image without WSLInterop / Windows-side PowerShell: fail fast.
        monkeypatch.setattr("shutil.which",
                            lambda name: None if name == "powershell.exe"
                            else "/usr/bin/whatever")
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
        monkeypatch.setattr("shutil.which",
                            lambda name: exe if name == "powershell.exe"
                            else None)
        calls = {}

        def fake_run(cmdline, capture_output=False, text=False):
            calls["cmdline"] = cmdline
            return subprocess.CompletedProcess(cmdline, 0, stdout="ok",
                                               stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        r = deliver._run_powershell("Remove-Item -LiteralPath 'x'")
        assert calls["cmdline"][0] == exe
        assert calls["cmdline"][-1] == "Remove-Item -LiteralPath 'x'"
        assert "-NoProfile" in calls["cmdline"]
        assert r.stdout == "ok"

    def test_powershell_nonzero_exit_raises_runtime_error(self, monkeypatch):
        exe = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        monkeypatch.setattr("shutil.which",
                            lambda name: exe if name == "powershell.exe"
                            else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmdline, capture_output=False, text=False:
                subprocess.CompletedProcess(cmdline, 1, stdout="",
                                            stderr="boom"))
        with pytest.raises(RuntimeError) as ei:
            deliver._run_powershell("exit 1")
        assert "powershell failed (1)" in str(ei.value)
        assert "boom" in str(ei.value)
