#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Platform-bridge tests for rpgmaker/deliver.py (review report §3.4 / D).

The deliver write-back must respect the AGENTS.md CRITICAL cross-system
rule: a Windows-side (/mnt/*) file is only ever touched by the Windows-side
tools, routed through powershell.exe (Windows 7z.exe / Remove-Item); a
WSL-side file uses the local 7zz.  `config.is_windows_side` is monkeypatched
both ways and every external subprocess is replaced with a recorder, so the
branch selection is verified without executing anything.

Also covered: the cross-side refusal (archive and dest on different
platforms), the missing win-7z refusal, and the PowerShell failure path.
"""
import os

import pytest

from rpgmaker import config, deliver

# Resolved Windows-side PowerShell path, as returned by the shared resolver
# inside config.run_powershell().  Tests pin it so the assertion is hermetic
# regardless of the machine's PATH.
_POWERSHELL_EXE = ("/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/"
                   "powershell.exe")


def _patch_powershell(monkeypatch):
    """Make _run_powershell resolve to a deterministic PowerShell path."""
    monkeypatch.setattr(
        "shutil.which",
        lambda name: _POWERSHELL_EXE if name == "powershell.exe" else None)


def _recorder(monkeypatch, calls, returncode=0):
    """Replace deliver.subprocess.run with a recorder returning success."""
    class _R:
        def __init__(self, cmd, rc):
            self.args = cmd
            self.returncode = rc
            self.stdout = "Everything is Ok"
            self.stderr = ""

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return _R(cmd, returncode)
    monkeypatch.setattr(deliver.subprocess, "run", fake_run)
    return fake_run


def _make_archive_and_dest(tmp_path):
    archive = str(tmp_path / "game.7z")
    dest = str(tmp_path / "games")
    os.makedirs(dest)
    with open(archive, "wb") as f:
        f.write(b"FAKE")
    return archive, dest


class TestWslSide:
    """is_windows_side == False -> local 7zz with plain POSIX paths."""

    def test_wsl_side_local_7z_command(self, tmp_path, monkeypatch):
        archive, dest = _make_archive_and_dest(tmp_path)
        sevenz = str(tmp_path / "7zz")
        with open(sevenz, "wb") as f:
            f.write(b"x")
        monkeypatch.setattr(config, "find_7z", lambda: sevenz)
        monkeypatch.setattr(config, "is_windows_side", lambda p: False)
        calls = []
        _recorder(monkeypatch, calls)

        target = str(tmp_path / "games" / "game")
        os.makedirs(target)
        out = deliver._extract_wsl_side(archive, dest, "game")
        assert out == target
        assert len(calls) == 1
        cmd, _kw = calls[0]
        assert cmd[0] == sevenz
        assert cmd[1:3] == ["x", "-y"]
        assert archive in cmd
        assert "-o%s" % dest in cmd
        assert "game" in cmd
        # PowerShell must never run on the WSL side
        assert not any("powershell.exe" in c for c, _ in calls)

    def test_wsl_side_missing_7z_raises(self, monkeypatch):
        monkeypatch.setattr(config, "find_7z", lambda: None)
        monkeypatch.setattr(config, "is_windows_side", lambda p: False)
        with pytest.raises(FileNotFoundError):
            deliver._extract_wsl_side("a.7z", "dest", "name")

    def test_wsl_side_refuses_windows_7z(self, tmp_path, monkeypatch):
        # SEVENZ pointing at the Windows 7z while inputs are WSL-side is a
        # cross-side violation: refuse instead of mixing tools
        archive, dest = _make_archive_and_dest(tmp_path)
        win7z = r"C:\Program Files\7-Zip-Zstandard\7z.exe"
        monkeypatch.setattr(config, "find_7z", lambda: win7z)
        # inputs are WSL-side, but the configured 7z itself is Windows-side
        monkeypatch.setattr(config, "is_windows_side",
                            lambda p: p == win7z)
        calls = []
        _recorder(monkeypatch, calls)
        with pytest.raises(RuntimeError) as ei:
            deliver._extract_wsl_side(archive, dest, "game")
        assert "refusing" in str(ei.value).lower()
        assert calls == []

    def test_wsl_extract_7z_failure_raises(self, tmp_path, monkeypatch):
        archive, dest = _make_archive_and_dest(tmp_path)
        sevenz = str(tmp_path / "7zz")
        with open(sevenz, "wb") as f:
            f.write(b"x")
        monkeypatch.setattr(config, "find_7z", lambda: sevenz)
        monkeypatch.setattr(config, "is_windows_side", lambda p: False)
        calls = []
        _recorder(monkeypatch, calls, returncode=1)
        with pytest.raises(RuntimeError):
            deliver._extract_wsl_side(archive, dest, "game")


class TestWindowsSide:
    """is_windows_side == True -> PowerShell + Windows 7z.exe, and the paths
    are converted to Windows form (D:\\...)."""

    def _windows_harness(self, tmp_path, monkeypatch, calls,
                         win7z="C:/Tools/7z.exe"):
        archive, dest = _make_archive_and_dest(tmp_path)
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(config, "win_7z", lambda: win7z)
        monkeypatch.setattr(config, "is_windows_side", lambda p: True)
        monkeypatch.setattr(config, "to_windows_path", lambda p: "D:" + p)
        _recorder(monkeypatch, calls)
        return archive, dest

    def test_windows_side_powershell_win7z(self, tmp_path, monkeypatch):
        calls = []
        archive, dest = self._windows_harness(tmp_path, monkeypatch, calls)
        target = str(tmp_path / "games" / "game")
        os.makedirs(target)
        out = deliver._extract_windows_side(archive, dest, "game")
        assert out == target
        assert len(calls) == 1
        cmd, _kw = calls[0]
        assert cmd[0].endswith("powershell.exe")
        assert "-NoProfile" in cmd and "-Command" in cmd
        command = cmd[cmd.index("-Command") + 1]
        assert "C:/Tools/7z.exe" in command
        assert "game.7z" in command
        assert "game" in command
        assert "$?" in command

    def test_windows_side_missing_win7z_refuses(self, tmp_path, monkeypatch):
        archive, dest = _make_archive_and_dest(tmp_path)
        monkeypatch.setattr(config, "win_7z", lambda: None)
        monkeypatch.setattr(config, "is_windows_side", lambda p: True)
        calls = []
        _recorder(monkeypatch, calls)
        with pytest.raises(RuntimeError) as ei:
            deliver._extract_windows_side(archive, dest, "game")
        assert "refusing" in str(ei.value).lower()
        assert "7z.exe" in str(ei.value)
        assert calls == []

    def test_remove_windows_side_uses_powershell(self, tmp_path, monkeypatch):
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(config, "is_windows_side", lambda p: True)
        monkeypatch.setattr(config, "to_windows_path",
                            lambda p: "D:" + p)
        calls = []
        _recorder(monkeypatch, calls)
        deliver._remove_windows_side(str(tmp_path / "stale"))
        assert len(calls) == 1
        cmd, _kw = calls[0]
        assert cmd[0].endswith("powershell.exe")
        command = cmd[cmd.index("-Command") + 1]
        assert "Remove-Item" in command
        assert "-LiteralPath" in command
        assert "$?" in command

    def test_powershell_failure_raises(self, tmp_path, monkeypatch):
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(config, "is_windows_side", lambda p: True)
        calls = []
        _recorder(monkeypatch, calls, returncode=1)
        with pytest.raises(RuntimeError) as ei:
            deliver._run_powershell("Remove-Item x")
        assert "powershell failed" in str(ei.value)


class TestExtractDispatch:
    """_extract picks the branch from is_windows_side and refuses mixes."""

    def _dispatch(self, tmp_path, monkeypatch, calls, archive_win, dest_win):
        archive = str(tmp_path / "a.7z")
        dest = str(tmp_path / "games")
        os.makedirs(dest)
        with open(archive, "wb") as f:
            f.write(b"FAKE")
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(config, "find_7z",
                            lambda: str(tmp_path / "7zz"))
        monkeypatch.setattr(config, "win_7z", lambda: "C:/7z.exe")
        monkeypatch.setattr(config, "is_windows_side",
                            lambda p: archive_win if p == archive else dest_win)
        _recorder(monkeypatch, calls)
        return archive, dest

    def test_both_wsl_local_tool(self, tmp_path, monkeypatch):
        calls = []
        archive, dest = self._dispatch(tmp_path, monkeypatch, calls,
                                       False, False)
        target = str(tmp_path / "games" / "game")
        os.makedirs(target)
        deliver._extract(archive, dest, "game")
        cmd, _kw = calls[0]
        assert cmd[0] != "powershell.exe"

    def test_both_windows_powershell_tool(self, tmp_path, monkeypatch):
        calls = []
        archive, dest = self._dispatch(tmp_path, monkeypatch, calls,
                                       True, True)
        target = str(tmp_path / "games" / "game")
        os.makedirs(target)
        deliver._extract(archive, dest, "game")
        cmd, _kw = calls[0]
        assert cmd[0].endswith("powershell.exe")

    def test_cross_side_refused(self, tmp_path, monkeypatch):
        calls = []
        archive, dest = self._dispatch(tmp_path, monkeypatch, calls,
                                       True, False)
        with pytest.raises(RuntimeError) as ei:
            deliver._extract(archive, dest, "game")
        assert "refusing" in str(ei.value).lower()
        assert calls == []


class TestDeliverBranchSelection:
    def test_wsl_deliver_uses_local_compress_and_extract(
            self, tmp_path, monkeypatch):
        # full deliver() with everything on the WSL side: compress + copy
        # + local extract.  Subprocess and cross-side flags are mocked so the
        # branch logic is what is under test.
        from rpgmaker import compress as compress_mod
        root = str(tmp_path / "src")
        os.makedirs(os.path.join(root, "data"))
        with open(os.path.join(root, "index.html"), "w") as f:
            f.write("<!DOCTYPE html>\n")
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")

        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            # the fake 7z "creates" the archive on compress and the extracted
            # target folder on extract
            if len(cmd) > 2 and cmd[1] in ("a", "t", "x"):
                if cmd[1] == "a":
                    with open(cmd[-2], "wb") as f:
                        f.write(b"FAKE-7Z\n")
                elif cmd[1] == "x":
                    # cmd: [7z, x, -y, archive, -o<dest>, name]
                    dname = next(a for a in cmd if a.startswith("-o"))[2:]
                    os.makedirs(os.path.join(dname, cmd[-1]), exist_ok=True)
            class _R:
                returncode = 0
                stdout = "Everything is Ok"
                stderr = ""
            return _R()
        monkeypatch.setattr(compress_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(deliver.subprocess, "run", fake_run)
        monkeypatch.setattr(config, "find_7z",
                            lambda: str(tmp_path / "7zz"))
        monkeypatch.setattr(config, "is_windows_side", lambda p: False)
        monkeypatch.setattr(config, "temp_dir", lambda: str(tmp_path))

        sevenz = str(tmp_path / "7zz")
        with open(sevenz, "wb") as f:
            f.write(b"x")

        out = str(tmp_path / "build")
        os.makedirs(os.path.join(out, "data"))
        with open(os.path.join(out, "index.html"), "w") as f:
            f.write("<!DOCTYPE html>\n")

        arch = deliver.deliver(out, games=games, archives=archives)
        assert os.path.isfile(arch)
        assert os.path.isdir(os.path.join(games, "build"))
        # no PowerShell anywhere on the WSL side
        assert not any("powershell.exe" in c for c in calls)
