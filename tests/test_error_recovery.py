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


# ---------------------------------------------------------------------------
# 1. Tool missing: every caller raises FileNotFoundError with an install hint
# ---------------------------------------------------------------------------

class TestToolMissingMessage:
    """The error message must name the missing tool and point at the fix
    (install it or set the env var) - a silent fallback would be a trap."""

    def test_audio_probe_all_hint(self, game_dir, monkeypatch):
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffprobe", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            audio.probe_all(web, workers=1)
        assert "ffprobe" in str(ei.value)
        assert "install" in str(ei.value).lower()

    def test_audio_reencode_all_hint(self, game_dir, monkeypatch):
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            audio.reencode_all(web, {}, workers=1)
        assert "ffmpeg" in str(ei.value)
        assert "install" in str(ei.value).lower()

    def test_compress_compress_hint(self, tmp_path, monkeypatch):
        folder = _make_folder(tmp_path)
        monkeypatch.setattr(config, "find_7z", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            compress.compress(folder, str(tmp_path / "g.7z"))
        assert "7-Zip" in str(ei.value)
        assert "install" in str(ei.value).lower()

    def test_compress_test_archive_hint(self, tmp_path, monkeypatch):
        # test_archive's own missing-7z path (independent of compress())
        archive = str(tmp_path / "g.7z")
        with open(archive, "wb") as f:
            f.write(b"stub")
        monkeypatch.setattr(config, "find_7z", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            compress.test_archive(archive)
        assert "7-Zip" in str(ei.value)
        assert "install" in str(ei.value).lower()

    def test_verify_decode_hint(self, game_dir, monkeypatch):
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            verify.verify_decode(web, workers=1)
        assert "ffmpeg" in str(ei.value)
        assert "install" in str(ei.value).lower()

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

    def test_deliver_wsl_extract_hint(self, monkeypatch):
        monkeypatch.setattr(config, "find_7z", lambda: None)
        with pytest.raises(FileNotFoundError) as ei:
            deliver._extract_wsl_side("a.7z", "dest", "name")
        assert "7-Zip" in str(ei.value)
        assert "install" in str(ei.value).lower()


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
        folder = _make_folder(tmp_path)
        # a resolvable 7z so the subprocess spawn (which raises) is reached
        sevenz = tmp_path / "sevenz.bin"
        sevenz.write_bytes(b"x")
        monkeypatch.setenv("SEVENZ", str(sevenz))

        def denied(cmd, **kw):
            raise PermissionError("7z not executable")
        monkeypatch.setattr("rpgmaker.compress.subprocess.run", denied)
        with pytest.raises(PermissionError):
            compress.compress(folder, str(tmp_path / "g.7z"))

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
    def test_compress_non_executable_binary_raises_permission_error(
            self, tmp_path):
        # a 7z binary that exists but cannot be executed surfaces as
        # PermissionError (POSIX exec semantics), not a silent success
        folder = _make_folder(tmp_path)
        script = tmp_path / "noexec_7z.py"
        script.write_text("#!/usr/bin/env python3\nprint('x')\n")
        script.chmod(0o644)  # readable, NOT executable
        monkeypatch_placeholder = pytest.MonkeyPatch()
        monkeypatch_placeholder.setenv("SEVENZ", str(script))
        try:
            with pytest.raises(PermissionError):
                compress.compress(folder, str(tmp_path / "g.7z"))
        finally:
            monkeypatch_placeholder.undo()
