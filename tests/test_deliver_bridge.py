#!/usr/bin/env python3
"""Platform-bridge tests for rpgmaker/deliver.py (review report §3.4 / D).

The deliver write-back must respect the AGENTS.md CRITICAL cross-system
rule: a Windows-side (/mnt/*) file is only ever touched by the Windows-side
tools, routed through powershell.exe (Windows 7z.exe / Remove-Item); a
WSL-side file uses the local 7zz.  `platform.is_windows_side` is monkeypatched
both ways and every external process is replaced with a recorder at the
shared runner seam (`rpgmaker.proctools`), so the branch selection is
verified without executing anything.

Also covered: the cross-side refusal (archive and dest on different
platforms), the missing win-7z refusal, and the PowerShell failure path.
"""
import os

import pytest

from rpgmaker import deliver, proctools, deliverables, platform, tool_registry

# Resolved Windows-side PowerShell path, as returned by the shared resolver
# inside tool_registry.run_powershell().  Tests pin it so the assertion is hermetic
# regardless of the machine's PATH.
_POWERSHELL_EXE = ("/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/"
                   "powershell.exe")


def _patch_powershell(monkeypatch):
    """Make _run_powershell resolve to a deterministic PowerShell path."""
    monkeypatch.setattr(
        "shutil.which",
        lambda name: _POWERSHELL_EXE if name == "powershell.exe" else None)


def _recorder(monkeypatch, calls, returncode=0):
    """Replace the shared process runner with a recorder returning success."""
    class _R:
        def __init__(self, cmd, rc):
            self.args = cmd
            self.returncode = rc
            self.stdout = "Everything is Ok"
            self.stderr = ""

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return _R(cmd, returncode)
    monkeypatch.setattr(proctools.subprocess, "run", fake_run)
    return fake_run


def _make_archive_and_dest(tmp_path):
    archive = str(tmp_path / "game.7z")
    dest = str(tmp_path / "games")
    os.makedirs(dest)
    with open(archive, "wb") as f:
        f.write(b"FAKE")
    return archive, dest


def _make_real_archive(tmp_path, name="game"):
    """A real py7zr archive containing `name/index.html` - the WSL-side
    extraction is in-process now, so these tests use a real container."""
    import py7zr
    src = tmp_path / "src" / name
    src.mkdir(parents=True)
    (src / "index.html").write_text("<!DOCTYPE html>\n", encoding="utf-8")
    (src / "data").mkdir()
    (src / "data" / "System.json").write_text("{}\n", encoding="utf-8")
    path = str(tmp_path / (name + ".7z"))
    with py7zr.SevenZipFile(path, "w",
                            filters=[{"id": py7zr.FILTER_ZSTD,
                                      "level": 1}]) as a:
        a.writeall(str(src), name)
    return path, str(tmp_path / "games")


class TestWslSide:
    """is_windows_side == False -> py7zr in-process, no external binary."""

    def test_wsl_side_extracts_with_py7zr(self, tmp_path, monkeypatch):
        archive, dest = _make_real_archive(tmp_path)
        monkeypatch.setattr(platform, "is_windows_side", lambda p: False)
        calls = []
        _recorder(monkeypatch, calls)

        target = os.path.join(dest, "game")
        out = deliver._extract_wsl_side(archive, dest, "game")
        assert out == target
        assert os.path.isfile(os.path.join(target, "index.html"))
        # no subprocess at all: neither 7z.exe nor PowerShell
        assert calls == []

    def test_wsl_side_does_not_need_a_7z_binary(self, tmp_path, monkeypatch):
        # There is no native-7z resolver to disable any more: py7zr owns the
        # WSL side in-process, so the property this test guards is now
        # structural.  Assert the absence explicitly so re-adding a 7z
        # resolver has to come with a caller and a test.
        assert not hasattr(tool_registry, "find_7z")
        archive, dest = _make_real_archive(tmp_path)
        monkeypatch.setattr(platform, "is_windows_side", lambda p: False)
        out = deliver._extract_wsl_side(archive, dest, "game")
        assert os.path.isfile(os.path.join(out, "index.html"))

    def test_wsl_side_absent_entry_raises(self, tmp_path, monkeypatch):
        archive, dest = _make_real_archive(tmp_path)
        monkeypatch.setattr(platform, "is_windows_side", lambda p: False)
        with pytest.raises(RuntimeError) as ei:
            deliver._extract_wsl_side(archive, dest, "other")
        assert "no other/ entry" in str(ei.value)

    def test_wsl_side_corrupt_archive_raises(self, tmp_path, monkeypatch):
        import py7zr
        archive, dest = _make_archive_and_dest(tmp_path)   # b"FAKE" body
        monkeypatch.setattr(platform, "is_windows_side", lambda p: False)
        # The archive layer must let the container library's own error out
        # rather than swallowing it; Bad7zFile is py7zr's "not a 7z file".
        with pytest.raises(py7zr.exceptions.Bad7zFile):
            deliver._extract_wsl_side(archive, dest, "game")


class TestWindowsSide:
    """is_windows_side == True -> PowerShell + Windows 7z.exe, and the paths
    are converted to Windows form (D:\\...)."""

    def _windows_harness(self, tmp_path, monkeypatch, calls,
                         win7z="C:/Tools/7z.exe"):
        archive, dest = _make_archive_and_dest(tmp_path)
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(tool_registry, "win_7z", lambda: win7z)
        monkeypatch.setattr(platform, "is_windows_side", lambda p: True)
        monkeypatch.setattr(platform, "to_windows_path", lambda p: "D:" + p)
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
        monkeypatch.setattr(tool_registry, "win_7z", lambda: None)
        monkeypatch.setattr(platform, "is_windows_side", lambda p: True)
        calls = []
        _recorder(monkeypatch, calls)
        with pytest.raises(RuntimeError) as ei:
            deliver._extract_windows_side(archive, dest, "game")
        assert "refusing" in str(ei.value).lower()
        assert "7z.exe" in str(ei.value)
        assert calls == []

    def test_remove_windows_side_uses_powershell(self, tmp_path, monkeypatch):
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(platform, "is_windows_side", lambda p: True)
        monkeypatch.setattr(platform, "to_windows_path",
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
        monkeypatch.setattr(platform, "is_windows_side", lambda p: True)
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
        if not archive_win:
            # WSL-side extraction is in-process: it needs a real container
            import py7zr
            src = tmp_path / "build"
            src.mkdir()
            (src / "index.html").write_text("x", encoding="utf-8")
            with py7zr.SevenZipFile(archive, "w") as a:
                a.writeall(str(src), "game")
        else:
            with open(archive, "wb") as f:
                f.write(b"FAKE")
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(tool_registry, "win_7z", lambda: "C:/7z.exe")
        monkeypatch.setattr(platform, "is_windows_side",
                            lambda p: archive_win if p == archive else dest_win)
        _recorder(monkeypatch, calls)
        return archive, dest

    def test_both_wsl_local_tool(self, tmp_path, monkeypatch):
        calls = []
        archive, dest = self._dispatch(tmp_path, monkeypatch, calls,
                                       False, False)
        deliver._extract(archive, dest, "game")
        # in-process py7zr: no external tool is spawned at all
        assert calls == []
        assert os.path.isfile(os.path.join(dest, "game", "index.html"))

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
        # full deliver() with everything on the WSL side: py7zr compresses,
        # the archive is copied, py7zr extracts.  Cross-side flags are mocked
        # so the branch logic is what is under test.
        root = str(tmp_path / "src")
        os.makedirs(os.path.join(root, "data"))
        # encoding="utf-8" everywhere: without it this file is written with
        # the host locale codec, which raises UnicodeEncodeError for CJK under
        # Windows' cp1252 default.
        with open(os.path.join(root, "index.html"), "w",
                  encoding="utf-8") as f:
            f.write("<!DOCTYPE html>\n")
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")

        calls = []
        monkeypatch.setattr(proctools.subprocess, "run",
                            lambda cmd, **kw: calls.append(cmd))
        monkeypatch.setattr(platform, "is_windows_side", lambda p: False)
        monkeypatch.setattr(deliverables, "temp_dir", lambda: str(tmp_path))

        out = str(tmp_path / "build")
        os.makedirs(os.path.join(out, "data"))
        with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html>\n")

        arch = deliver.deliver(out, games=games, archives=archives)
        assert os.path.isfile(arch)
        assert os.path.isfile(os.path.join(games, "build", "index.html"))
        # neither 7z.exe nor PowerShell may run for a WSL-side delivery
        assert calls == []
