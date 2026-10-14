#!/usr/bin/env python3
"""Error-recovery tests: the toolkit must survive failing inputs.

Three failure families, none of which may end in a bare traceback:

  tool missing     - the Windows-side bridge cannot resolve ``7z.exe`` /
                     PowerShell: the refusal names the tool and the fix.
  corrupted input  - a truncated archive or a bad member raises the module's
                     documented error, or degrades to a recorded status.
  permission       - a denied file or subprocess operation raises the specific
                     OSError; a batch step records the failure instead.

Permission cases use monkeypatched raises - never real filesystem perms - so
the suite stays deterministic on any platform or sandbox.  Parser-level
corruption contracts live in `tests/test_format_fuzz.py`, and the per-format
readers in their own files (`test_xp3tool.py`, `test_dxarchive.py`,
`test_archive.py`).
"""
import json
import os

import pytest

from rpgmaker import archive, compress, deliver, platform, tool_registry


def _make_folder(tmp_path, name="game"):
    folder = str(tmp_path / name)
    os.makedirs(os.path.join(folder, "data"), exist_ok=True)
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html>\n")
    return folder


def _patch_powershell(monkeypatch):
    """Make the Windows-bridge PowerShell lookup deterministic."""
    exe = ("/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe")
    monkeypatch.setattr(
        "shutil.which",
        lambda name: exe if name == "powershell.exe" else None)


# ---------------------------------------------------------------------------
# 1. Tool missing: the caller names the tool and the fix
# ---------------------------------------------------------------------------

class TestToolMissingMessage:
    """A missing tool must never degrade into a silent no-op."""

    def test_compress_needs_no_sevenz_binary(self, tmp_path):
        """Packaging is in-process (py7zr), so no 7-Zip binary is involved.

        There is no native-``7z`` resolver to disable: the WSL side never
        spawns 7-Zip, and the Windows-side bridge uses ``win_7z``.
        """
        assert not hasattr(tool_registry, "find_7z")
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "g.7z"))
        assert compress.test_archive(path) is True

    def test_test_archive_reports_a_corrupt_file_as_false(self, tmp_path):
        """A corrupt or mistyped archive is a False verdict plus an ERROR log,
        not an exception and not a silent pass."""
        broken = str(tmp_path / "g.7z")
        with open(broken, "wb") as f:
            f.write(b"stub")
        assert compress.test_archive(broken) is False

    def test_deliver_windows_bridge_missing_7z_hint(self, monkeypatch):
        """The Windows-side bridge is the only path that needs a 7-Zip
        binary; its refusal must name the tool and the fix."""
        monkeypatch.setattr(tool_registry, "win_7z", lambda: None)
        with pytest.raises(RuntimeError) as ei:
            deliver._extract_windows_side("a.7z", "dest", "name")
        msg = str(ei.value)
        assert "7-Zip" in msg
        assert "SEVENZ_WIN" in msg

    def test_deliver_wsl_extract_reports_a_missing_archive(self, monkeypatch):
        """WSL-side extraction runs in-process: a missing archive is a clean
        file error, not a tool-resolution failure."""
        monkeypatch.setattr(platform, "is_windows_side", lambda p: False)
        with pytest.raises(OSError):
            deliver._extract_wsl_side("no_such.7z", "dest", "name")


# ---------------------------------------------------------------------------
# 2. Corrupted input: a specific verdict, not a bare crash
# ---------------------------------------------------------------------------

class TestCorruptedInput:
    def test_a_corrupt_archive_content_is_reported_false(self, tmp_path):
        """A *member-level* failure must also be False, not only an open failure.

        Measured: py7zr's `testzip()` raises on every corruption shape we could
        produce (32 single-byte flips across a real archive returned a member 0
        times), so the `bad` branch of `archive._verdict` is unreachable through
        the filesystem and would otherwise be untested - a guard nobody can
        exercise is a guard that silently stops guarding.  The mutation table
        removes `if bad:`; this test is what notices.
        """
        assert archive._verdict("x.7z", bad="game/b.txt") is False
        assert archive._verdict("x.7z", error=None, bad=None) is True
        assert archive._verdict("x.7z", error=OSError("boom")) is False


# ---------------------------------------------------------------------------
# 3. Permission denied: specific exception or documented degradation
# ---------------------------------------------------------------------------

class TestPermissionDenied:
    def test_compress_permission_error_propagates_specifically(self, tmp_path,
                                                               monkeypatch):
        """A permission failure while packing must surface as the specific
        OSError - archive.create() must never swallow a backend error."""
        folder = _make_folder(tmp_path)

        class _Denied:
            FILTER_ZSTD = 53

            @staticmethod
            def SevenZipFile(*_a, **_kw):
                raise PermissionError("access denied")

        monkeypatch.setattr(archive, "_py7zr", lambda: _Denied)
        with pytest.raises(PermissionError):
            compress.compress(folder, str(tmp_path / "g.7z"))

    def test_compress_spawns_no_external_tool(self, tmp_path, monkeypatch):
        """The backend is in-process: packaging must work with no 7-Zip
        binary available anywhere (only the Windows bridge needs one)."""
        assert not hasattr(tool_registry, "find_7z")
        folder = _make_folder(tmp_path)
        monkeypatch.setattr(tool_registry, "win_7z", lambda: None)

        def boom(*_a, **_kw):
            raise AssertionError("compress() must not spawn a process")
        monkeypatch.setattr("rpgmaker.proctools.subprocess.run", boom)
        path = compress.compress(folder, str(tmp_path / "g.7z"))
        assert compress.test_archive(path) is True

    def test_build_translation_permission_error_propagates(self, tmp_path,
                                                           monkeypatch):
        # a denied data JSON read is a real failure - it must surface as the
        # specific OSError subclass, never get swallowed
        from tools import build_translation as bt
        root = str(tmp_path / "game")
        data = os.path.join(root, "data")
        os.makedirs(data)
        os.makedirs(os.path.join(root, "js"))
        for name, payload in (("Map001.json",
                               {"@name": "Map001", "displayName": "",
                                "events": []}),
                              ("MapInfos.json", []),
                              ("System.json", {}),
                              ("CommonEvents.json", []),
                              ("Actors.json", []),
                              ("Items.json", [])):
            with open(os.path.join(data, name), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        with open(os.path.join(root, "js", "plugins.js"), "w",
                  encoding="utf-8") as f:
            f.write("var $plugins = [];\n")

        real_open = open

        def denied(path, *a, **kw):
            if str(path).endswith("Map001.json"):
                raise PermissionError("access denied")
            return real_open(path, *a, **kw)
        monkeypatch.setattr("builtins.open", denied)
        monkeypatch.setattr("sys.argv",
                            ["build_translation.py", root,
                             str(tmp_path / "work")])
        with pytest.raises(PermissionError):
            bt.main()


class TestUnreadableSevenzBinary:
    """The 7-Zip binary is no longer on the packaging path (py7zr is
    in-process) and there is no native ``7z`` resolver left at all, so an
    unreadable or foreign 7z.exe cannot break compress() even in principle.

    The equivalent risk moved to the Windows-side bridge, where a broken
    PowerShell or 7z.exe still surfaces as a real error instead of a silent
    success - covered below and in the bridge tests.
    """

    def test_broken_sevenz_binary_does_not_affect_compress(self, tmp_path):
        assert not hasattr(tool_registry, "find_7z")
        folder = _make_folder(tmp_path)
        script = tmp_path / "noexec_7z.bin"
        script.write_bytes(b"not an executable")
        if os.name == "posix":
            script.chmod(0o644)  # readable, NOT executable
        path = compress.compress(folder, str(tmp_path / "g.7z"))
        assert compress.test_archive(path) is True

    def test_windows_bridge_still_fails_loudly(self, tmp_path, monkeypatch):
        """The bridge keeps its old contract: a spawn error propagates."""
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(platform, "is_windows_side", lambda p: True)
        monkeypatch.setattr(tool_registry, "win_7z", lambda: "C:/Tools/7z.exe")

        def denied(cmd, **kw):
            raise PermissionError("7z not executable")
        monkeypatch.setattr("rpgmaker.proctools.subprocess.run", denied)
        with pytest.raises(PermissionError):
            deliver._extract_windows_side(str(tmp_path / "a.7z"),
                                          str(tmp_path / "games"), "game")
