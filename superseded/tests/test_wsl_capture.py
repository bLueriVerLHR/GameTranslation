#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/wsl_capture.py (window-targeted screenshots).

The powershell.exe invocation is replaced by the portable fake tool
(tests/fake_tools/fake_powershell.py, wrapped in a platform launcher and
injected via the POWERSHELL_EXE env var); the Windows temp dir is
monkeypatched to a tmp_path so the whole flow is hermetic (positive /
negative / edge cases).
"""
import os
import sys
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import pytest  # noqa: E402

import wsl_capture  # noqa: E402

FAKE = None  # resolved per-test through the fake_powershell fixture
SCRIPT_SRC = os.path.join(REPO_ROOT, "tools", "capture_window.ps1")


@pytest.fixture
def fake_env(fake_powershell, monkeypatch, tmp_path):
    """Point the wrapper at the fake powershell + a hermetic Windows temp."""
    monkeypatch.setattr(wsl_capture.config, "win_temp_dir", lambda: str(tmp_path))
    return tmp_path


def run_main(argv, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["wsl_capture.py"] + argv)
    return wsl_capture.main()


# ------------------------------------------------------------- interop

def test_interop_ok_with_override(monkeypatch):
    # an explicit POWERSHELL_EXE override is trusted (tests / exotic setups)
    monkeypatch.setenv("POWERSHELL_EXE", "/custom/powershell")
    assert wsl_capture.interop_ok("/custom/powershell") is True


def test_interop_ok_on_native_windows(monkeypatch):
    monkeypatch.delenv("POWERSHELL_EXE", raising=False)
    monkeypatch.setattr(wsl_capture.config, "is_wsl", lambda: False)
    assert wsl_capture.interop_ok("C:/Windows/powershell.exe") is True
    assert wsl_capture.interop_ok(None) is False


def test_interop_ok_with_entry(monkeypatch, tmp_path):
    monkeypatch.delenv("POWERSHELL_EXE", raising=False)
    monkeypatch.setattr(wsl_capture.config, "is_wsl", lambda: True)
    (tmp_path / "WSLInterop").write_text("enabled\n")
    assert wsl_capture.interop_ok("", binfmt_root=str(tmp_path)) is True


def test_interop_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("POWERSHELL_EXE", raising=False)
    monkeypatch.setattr(wsl_capture.config, "is_wsl", lambda: True)
    assert wsl_capture.interop_ok("", binfmt_root=str(tmp_path)) is False


# ------------------------------------------------------------- deploy

def test_deploy_copies_script(fake_env):
    win = wsl_capture.config.win_temp_dir()
    script = wsl_capture.deploy_script(win)
    deployed = os.path.join(win, "capture_window.ps1")
    assert os.path.exists(deployed)
    assert open(deployed, encoding="utf-8").read() == \
        open(SCRIPT_SRC, encoding="utf-8").read()
    assert Path(script) == Path(win) / "capture_window.ps1"


def test_deploy_idempotent_skips_fresh(fake_env, monkeypatch):
    win = wsl_capture.config.win_temp_dir()
    deployed = os.path.join(win, "capture_window.ps1")
    os.makedirs(win, exist_ok=True)
    with open(deployed, "w", encoding="utf-8") as f:
        f.write("stale content")
    # make deployed newer than the source -> must NOT be overwritten
    future = os.path.getmtime(SCRIPT_SRC) + 1000
    os.utime(deployed, (future, future))
    wsl_capture.deploy_script(win)
    assert open(deployed, encoding="utf-8").read() == "stale content"


def test_deploy_refreshes_stale(fake_env):
    win = wsl_capture.config.win_temp_dir()
    deployed = os.path.join(win, "capture_window.ps1")
    os.makedirs(win, exist_ok=True)
    with open(deployed, "w", encoding="utf-8") as f:
        f.write("old")
    os.utime(deployed, (0, 0))  # older than the source
    wsl_capture.deploy_script(win)
    assert open(deployed, encoding="utf-8").read() == \
        open(SCRIPT_SRC, encoding="utf-8").read()


# ------------------------------------------------------------- args

def test_args_window_mode():
    class A:
        process = "GamePro"
        title = "確認"
        out = "shot.png"
        full = False
        window_only = True
        force_visible = True
        width = 0
        height = 0
        dir = r"C:\tmp\shots"
    cmd = wsl_capture.build_args(A(), r"C:\tmp", r"C:\tmp\capture_window.ps1")
    assert cmd[:4] == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert cmd[4] == r"C:\tmp\capture_window.ps1"
    assert "-ProcessName" in cmd and "GamePro" in cmd
    assert "-Title" in cmd and "確認" in cmd
    assert "-OutDir" in cmd and r"C:\tmp" in cmd
    assert "-Out" in cmd and "shot.png" in cmd
    assert "-Full" not in cmd
    assert "-WindowOnly:$false" not in cmd
    assert "-ForceVisible:$false" not in cmd


def test_args_full_mode():
    class A:
        process = None
        title = None
        out = None
        full = True
        window_only = True
        force_visible = True
        width = 1280
        height = 720
        dir = "/tmp/out"
    cmd = wsl_capture.build_args(A(), "/tmp/out", "/tmp/cap.ps1")
    assert "-Full" in cmd
    assert "-ProcessName" not in cmd
    assert "-Width" in cmd and "1280" in cmd
    assert "-Height" in cmd and "720" in cmd


def test_args_flags_false():
    class A:
        process = "Game"
        title = None
        out = None
        full = False
        window_only = False
        force_visible = False
        width = 0
        height = 0
        dir = "/tmp/out"
    cmd = wsl_capture.build_args(A(), "/tmp/out", "/tmp/cap.ps1")
    assert "-WindowOnly:$false" in cmd
    assert "-ForceVisible:$false" in cmd


# ------------------------------------------------- script shape (PowerShell)

def _script_text():
    with open(SCRIPT_SRC, encoding="utf-8") as fh:
        return fh.read()


def test_script_considers_every_process_with_that_name():
    # A multi-process app (Chromium/Electron/launchers) runs several processes
    # under one image name and the window owner is not necessarily the first
    # one: matching only the first PID reported "no visible window" for such
    # apps.  The script must build a PID set instead.
    text = _script_text()
    assert "$targetPids" in text, "multi-PID matching was lost"
    assert "$targetPids.ContainsKey" in text
    assert "Select-Object -First 1\n    if (-not $proc)" not in text, \
        "the old single-PID lookup is back"


def test_script_prefers_a_titled_window():
    # Chromium spawns untitled helper windows; the real app window carries a
    # title, so prefer it over a bigger but titleless helper.
    text = _script_text()
    assert "$titled" in text


def test_script_restores_and_moves_before_capture():
    # Occluded/minimized windows must be restored and moved into view, and
    # the capture must retry the classic flag when the modern one fails.
    text = _script_text()
    assert "SW_RESTORE" in text and "MoveWindow" in text
    assert "PrintWindow($rect.Hwnd, $hdc, 2)" in text
    assert "PrintWindow($rect.Hwnd, $hdc, 0)" in text
    assert "CopyFromScreen" in text, "screen fallback was removed"


def test_script_reports_paths_as_utf8():
    # Non-ASCII output paths must survive the round trip to the caller.
    assert "[System.Text.Encoding]::UTF8" in _script_text()


# ------------------------------------------------------------- end-to-end

def test_capture_success(fake_env, tmp_path, monkeypatch):
    out_dir = tmp_path / "shots"
    code = run_main(["--process", "GamePro", "--dir", str(out_dir),
                     "--out", "shot.png"], monkeypatch, tmp_path)
    assert code == 0
    assert os.path.exists(out_dir / "shot.png")


def test_capture_no_window(fake_env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PS_FAIL", "no visible window")
    code = run_main(["--process", "Ghost", "--dir", str(tmp_path)],
                    monkeypatch, tmp_path)
    assert code == 1


def test_capture_missing_output(fake_env, tmp_path, monkeypatch):
    # fake prints a path but creates nothing -> wrapper must fail
    monkeypatch.setenv("FAKE_PS_FAIL", "printed path only")
    code = run_main(["--process", "GamePro", "--dir", str(tmp_path)],
                    monkeypatch, tmp_path)
    assert code == 1


def test_capture_full_screen(fake_env, tmp_path, monkeypatch):
    out_dir = tmp_path / "full"
    code = run_main(["--full", "--dir", str(out_dir)], monkeypatch, tmp_path)
    assert code == 0
    assert len(list(out_dir.iterdir())) == 1


def test_args_no_outdir_default():
    # --dir omitted -> the capture script uses its own Pictures default
    class A:
        process = "GamePro"
        title = None
        out = None
        full = False
        window_only = True
        force_visible = True
        width = 0
        height = 0
        dir = None
    cmd = wsl_capture.build_args(A(), None, "/tmp/cap.ps1")
    assert "-OutDir" not in cmd
    assert "-ProcessName" in cmd


def test_capture_no_process_without_full(fake_env, tmp_path, monkeypatch,
                                         capsys):
    """--process is required in window mode: usage error, exit code 2."""
    assert run_main(["--dir", str(tmp_path)], monkeypatch, tmp_path) == 2
    assert "--process is required unless --full" in capsys.readouterr().err


def test_powershell_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("POWERSHELL_EXE", raising=False)
    monkeypatch.setattr(wsl_capture, "powershell_exe", lambda: None)
    code = run_main(["--process", "GamePro", "--dir", str(tmp_path)],
                    monkeypatch, tmp_path)
    assert code == 2


def test_powershell_exe_delegates_to_shared_resolver(monkeypatch):
    monkeypatch.delenv("POWERSHELL_EXE", raising=False)
    monkeypatch.setattr(wsl_capture.config, "find_powershell",
                        lambda: "/shared/powershell.exe")
    assert wsl_capture.powershell_exe() == "/shared/powershell.exe"


def test_interop_missing_reports_fix(monkeypatch, tmp_path, capsys,
                                     fake_powershell):
    # POWERSHELL_EXE is set by the fixture (trusted), so force the check off
    monkeypatch.setattr(wsl_capture, "interop_ok", lambda p: False)
    code = run_main(["--process", "GamePro", "--dir", str(tmp_path)],
                    monkeypatch, tmp_path)
    assert code == 2
    assert "WSLInterop" in capsys.readouterr().err
