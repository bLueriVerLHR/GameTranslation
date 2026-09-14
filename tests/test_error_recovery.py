#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Error-recovery tests (review report §3.4 / remaining-issues D):

Three failure families that the toolkit must survive without a bare crash:

  tool missing     - a required binary (ffmpeg/ffprobe/7z) cannot be
                     resolved: the module raises FileNotFoundError whose
                     message names the tool AND carries an install hint
                     (config._find_tool returns None and every caller turns
                     that into an actionable error).
  corrupted input  - truncated / bad-magic / bad-header files must raise a
                     SPECIFIC exception (or degrade to a documented status),
                     never a bare traceback.
  permission       - a denied file/subprocess operation must either raise
                     PermissionError (specific, meaningful) or degrade to a
                     recorded status (audio transcode keeps the batch alive).

Permission cases use monkeypatched raises - never real filesystem perms -
so the suite stays deterministic on any platform / sandbox.
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from conftest import make_game  # noqa: E402

from rpgmaker import audio, compress, config, decrypt, verify  # noqa: E402
from rpgmaker import deliver  # noqa: E402
from tyrano import audio as tyrano_audio  # noqa: E402


def _make_folder(tmp_path, name="game"):
    folder = str(tmp_path / name)
    os.makedirs(os.path.join(folder, "data"), exist_ok=True)
    with open(os.path.join(folder, "index.html"), "w") as f:
        f.write("<!DOCTYPE html>\n")
    return folder


def _patch_powershell(monkeypatch):
    """Make the Windows-bridge PowerShell lookup deterministic."""
    exe = ("/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe")
    monkeypatch.setattr(
        "shutil.which",
        lambda name: exe if name == "powershell.exe" else None)


# ---------------------------------------------------------------------------
# 1. Tool missing: every caller raises FileNotFoundError with an install hint
# ---------------------------------------------------------------------------

class TestToolMissingMessage:
    """The error message must name the missing tool and point at the fix
    (install it or set the env var) - a silent fallback would be a trap."""

    def test_audio_probe_needs_no_ffprobe(self, game_dir, monkeypatch):
        """Probing is in-process (PyAV) now: a missing ffprobe/ffmpeg must not
        stop it."""
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffprobe", lambda: None)
        monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
        assert len(audio.probe_all(web, workers=1, sample=1)) == 1

    def test_audio_reencode_all_hint(self, game_dir, monkeypatch):
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            audio.reencode_all(web, {}, workers=1)
        assert "ffmpeg" in str(ei.value)
        assert "install" in str(ei.value).lower()

    def test_compress_needs_no_sevenz_binary(self, tmp_path, monkeypatch):
        """Packaging moved to py7zr (in-process), so a missing 7-Zip is no
        longer an error - only the Windows-side bridge needs the binary."""
        folder = _make_folder(tmp_path)
        monkeypatch.setattr(config, "find_7z", lambda: None)
        path = compress.compress(folder, str(tmp_path / "g.7z"))
        assert compress.test_archive(path) is True

    def test_test_archive_reports_a_corrupt_file_as_false(self, tmp_path):
        """A corrupt/mistyped archive is a False verdict plus an ERROR log,
        not an exception and not a silent pass."""
        archive = str(tmp_path / "g.7z")
        with open(archive, "wb") as f:
            f.write(b"stub")
        assert compress.test_archive(archive) is False

    def test_verify_decode_needs_no_ffmpeg(self, game_dir, monkeypatch):
        """Decode verification is in-process (PyAV): no binary required."""
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
        monkeypatch.setattr(config, "find_ffprobe", lambda: None)
        assert isinstance(verify.verify_decode(web, workers=1), list)

    def test_tyrano_convert_all_hint(self, tmp_path, monkeypatch):
        root = str(tmp_path / "g")
        os.makedirs(os.path.join(root, "data", "sound"), exist_ok=True)
        with open(os.path.join(root, "data", "sound", "a.mp3"), "wb") as f:
            f.write(b"\xff\xfb" + b"M" * 100)
        monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            tyrano_audio.convert_all(root, workers=1)
        assert "ffmpeg" in str(ei.value)
        assert "install" in str(ei.value).lower()

    def test_deliver_windows_bridge_missing_7z_hint(self, monkeypatch):
        """The Windows-side bridge is the only path that still needs a 7-Zip
        binary; its refusal must name the tool and the fix."""
        monkeypatch.setattr(config, "win_7z", lambda: None)
        with pytest.raises(RuntimeError) as ei:
            deliver._extract_windows_side("a.7z", "dest", "name")
        msg = str(ei.value)
        assert "7-Zip" in msg
        assert "SEVENZ_WIN" in msg

    def test_deliver_wsl_extract_reports_a_missing_archive(self, monkeypatch):
        """WSL-side extraction runs in-process: a missing archive is a clean
        error, not a tool-resolution failure."""
        monkeypatch.setattr(config, "is_windows_side", lambda p: False)
        with pytest.raises(OSError):
            deliver._extract_wsl_side("no_such.7z", "dest", "name")


# ---------------------------------------------------------------------------
# 2. Corrupted input: a specific exception, not a bare crash
# ---------------------------------------------------------------------------

class TestCorruptedInput:
    def test_decrypt_truncated_body_returns_false(self, tmp_path):
        # a valid header but a body shorter than the 16-byte XOR window is
        # still decrypted (XOR loop is bounded by body length); the graceful
        # path is returning True with the short body - never a crash
        plain = b"\x00\x00\x00"
        body = bytearray(plain)
        for i in range(len(body)):
            body[i] ^= 0x01
        src = tmp_path / "t.png_"
        src.write_bytes(config.RPGMV_HEADER + bytes(body))
        dst = tmp_path / "t.png"
        assert decrypt._decrypt_to(str(src), b"\x01" * 16, str(dst)) is True
        assert dst.read_bytes() == plain

    def test_decrypt_bad_magic_returns_false(self, tmp_path):
        # a corrupt magic header must be treated as custom encryption, not crash
        src = tmp_path / "u.png_"
        src.write_bytes(b"BADSIG" + b"\x00" * 40)
        dst = tmp_path / "u.png"
        assert decrypt._decrypt_to(str(src), b"\x01" * 16, str(dst)) is False
        assert src.exists() and not dst.exists()

    def test_load_encryption_key_truncated_json(self, tmp_path):
        # truncated JSON in System.json -> None (custom/runtime decryption)
        web = make_game(str(tmp_path / "g"))
        p = os.path.join(web, "data", "System.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"encryptionKey": "0123')
        assert decrypt.load_encryption_key(web) is None

    def test_verify_data_json_truncated_reported(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        p = os.path.join(web, "data", "Trunc.json")
        with open(p, "wb") as f:
            f.write(b'{"name": "x"')  # valid JSON prefix, cut off
        bad = verify.verify_data_json(web)
        assert any(fn == "Trunc.json" for fn, _ in bad)

    def test_verify_system_flags_non_json_degrades(self, tmp_path):
        web = make_game(str(tmp_path / "g"))
        p = os.path.join(web, "data", "System.json")
        with open(p, "wb") as f:
            f.write(b"\x00" * 8)
        # not plain JSON -> flags check skipped, no crash
        assert verify.verify_system_flags(web) == []

    def test_probe_one_binary_garbage_error_dict(self, tmp_path, monkeypatch):
        # ffprobe returning garbage must surface as an error dict, not raise
        class _R:
            returncode = 1
            stdout = "not json at all"
            stderr = ""
        monkeypatch.setattr(audio.subprocess, "run",
                            lambda *a, **kw: _R())
        info = audio.probe_one("unused", str(tmp_path / "x.ogg"))
        assert "error" in info

    def test_probe_one_nonzero_returncode(self, tmp_path, monkeypatch):
        # ffprobe exiting non-zero -> JSONDecodeError path -> error dict
        class _R:
            returncode = 1
            stdout = ""
            stderr = ""
        monkeypatch.setattr(audio.subprocess, "run",
                            lambda *a, **kw: _R())
        info = audio.probe_one("unused", str(tmp_path / "x.ogg"))
        assert "error" in info


# ---------------------------------------------------------------------------
# 3. Permission denied: specific exception or documented degradation
# ---------------------------------------------------------------------------

class TestPermissionDenied:
    def test_audio_transcode_degrades_on_permission_error(self, tmp_path,
                                                          monkeypatch):
        # ffmpeg spawn denied -> OSError family -> recorded status, batch alive
        def denied(cmd, **kw):
            raise PermissionError("execution denied")
        monkeypatch.setattr(audio.subprocess, "run", denied)
        path = tmp_path / "a.ogg"
        path.write_bytes(b"\x00" * 100000)
        info = {"duration": "10", "size": "100000", "channels": "1"}
        _p, status, saved = audio.transcode_one("unused", str(path), info)
        assert status.startswith("exc:")
        assert saved == 0

    def test_tyrano_convert_one_degrades_on_permission_error(self, tmp_path,
                                                             monkeypatch):
        def denied(cmd, **kw):
            raise PermissionError("execution denied")
        monkeypatch.setattr(tyrano_audio.subprocess, "run", denied)
        p = tmp_path / "b.mp3"
        p.write_bytes(b"\xff\xfb" + b"M" * 100)
        assert tyrano_audio.convert_one("unused", str(p)) is None
        assert p.exists()  # original left in place

    def test_decrypt_permission_error_propagates_specifically(self, tmp_path,
                                                              monkeypatch):
        # a read-denied asset raises PermissionError (a specific, meaningful
        # error) rather than an unhandled bare crash
        src = tmp_path / "p.png_"
        src.write_bytes(config.RPGMV_HEADER + b"\x00" * 32)
        real_open = open

        def denied(path, *a, **kw):
            if str(path) == str(src):
                raise PermissionError("access denied")
            return real_open(path, *a, **kw)
        monkeypatch.setattr("builtins.open", denied)
        with pytest.raises(PermissionError):
            decrypt._decrypt_to(str(src), b"\x01" * 16, str(tmp_path / "p.png"))

    def test_compress_permission_error_propagates_specifically(self, tmp_path,
                                                               monkeypatch):
        """A permission failure while packing must surface as the specific
        OSError - archive.create() must never swallow a backend error."""
        from rpgmaker import archive
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
        """The packaged backend is in-process: packaging must work with no
        7-Zip binary available anywhere (only the Windows bridge needs it)."""
        folder = _make_folder(tmp_path)
        monkeypatch.setattr(config, "find_7z", lambda: None)
        monkeypatch.setattr(config, "win_7z", lambda: None)

        def boom(*_a, **_kw):
            raise AssertionError("compress() must not spawn a process")
        monkeypatch.setattr("rpgmaker.proctools.subprocess.run", boom)
        path = compress.compress(folder, str(tmp_path / "g.7z"))
        assert compress.test_archive(path) is True

    def test_build_translation_permission_error_propagates(self, tmp_path,
                                                           monkeypatch):
        # a denied data JSON read is a real failure - it must surface as the
        # specific OSError subclass, never get swallowed
        import build_translation as bt
        root = str(tmp_path / "game")
        data = os.path.join(root, "data")
        os.makedirs(data)
        os.makedirs(os.path.join(root, "js"))
        with open(os.path.join(data, "Map001.json"), "w", encoding="utf-8") as f:
            json.dump({"@name": "Map001", "displayName": "", "events": []}, f)
        with open(os.path.join(data, "MapInfos.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        with open(os.path.join(data, "System.json"), "w", encoding="utf-8") as f:
            json.dump({}, f)
        with open(os.path.join(data, "CommonEvents.json"), "w",
                  encoding="utf-8") as f:
            json.dump([], f)
        with open(os.path.join(data, "Actors.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        with open(os.path.join(data, "Items.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
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
    in-process), so an unreadable/foreign 7z.exe cannot break compress().

    The equivalent risk moved to the Windows-side bridge, where a broken
    powershell/7z.exe still surfaces as a real error instead of a silent
    success - covered below and in tests/test_deliver_bridge.py.
    """

    def test_broken_sevenz_binary_does_not_affect_compress(self, tmp_path,
                                                          monkeypatch):
        folder = _make_folder(tmp_path)
        script = tmp_path / "noexec_7z.bin"
        script.write_bytes(b"not an executable")
        if os.name == "posix":
            script.chmod(0o644)  # readable, NOT executable
        monkeypatch.setenv("SEVENZ", str(script))
        path = compress.compress(folder, str(tmp_path / "g.7z"))
        assert compress.test_archive(path) is True

    def test_windows_bridge_still_fails_loudly(self, tmp_path, monkeypatch):
        """The bridge keeps its old contract: a spawn error propagates."""
        _patch_powershell(monkeypatch)
        monkeypatch.setattr(config, "is_windows_side", lambda p: True)
        monkeypatch.setattr(config, "win_7z", lambda: "C:/Tools/7z.exe")

        def denied(cmd, **kw):
            raise PermissionError("7z not executable")
        monkeypatch.setattr("rpgmaker.proctools.subprocess.run", denied)
        with pytest.raises(PermissionError):
            deliver._extract_windows_side(str(tmp_path / "a.7z"),
                                          str(tmp_path / "games"), "game")
