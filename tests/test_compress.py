#!/usr/bin/env python3
"""Unit tests for rpgmaker/compress.py + rpgmaker/archive.py (7z + zstd).

The archive work is done in-process by py7zr (a declared dependency), so
these tests exercise the real container: no fake 7-Zip, no argv assertions.
The 7-Zip CLI is only involved in the Windows-side bridge, which is covered
by tests/test_deliver_bridge.py.

Still verified here: the delivery format really is ZStandard, a stale
archive is replaced (never appended to), integrity passes for good archives
and fails loudly for corrupt ones, and no external 7-Zip binary is needed at
all for the same-side path.
"""
import os

import pytest
import py7zr

from rpgmaker import archive, compress, platform, tool_registry


def _make_folder(tmp_path, name="game"):
    folder = str(tmp_path / name)
    os.makedirs(os.path.join(folder, "data"), exist_ok=True)
    # encoding="utf-8" is required, not cosmetic: without it the Japanese
    # title below is encoded with the host locale codec, which raises
    # UnicodeEncodeError under Windows' default cp1252.
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html>\n")
    with open(os.path.join(folder, "data", "System.json"), "w",
              encoding="utf-8") as f:
        f.write('{"gameTitle": "テスト"}\n')
    return folder


def _methods(archive_path):
    """Compression methods recorded in the archive (py7zr's own names)."""
    with py7zr.SevenZipFile(archive_path, "r") as a:
        return tuple(a.archiveinfo().method_names)


def _is_zstd(archive_path):
    # py7zr names it "ZStandard"; 7z.exe prints "ZSTD" for the same container
    return any(m.lower() in ("zstd", "zstandard") for m in _methods(archive_path))


class TestCompressArchive:
    def test_creates_archive(self, tmp_path):
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        assert path == str(tmp_path / "game.7z")
        assert os.path.isfile(path)
        assert compress.test_archive(path) is True

    def test_archive_is_zstandard_and_stores_the_basename(self, tmp_path):
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        assert _is_zstd(path)
        names = archive.names(path)
        assert "game/index.html" in names
        assert "game/data/System.json" in names

    def test_relative_archive_gets_extension(self, tmp_path, monkeypatch):
        folder = _make_folder(tmp_path)
        monkeypatch.chdir(tmp_path)
        path = compress.compress(folder, "rel")
        assert path == "rel.7z"
        assert os.path.isfile(path)

    def test_absolute_non_7z_kept_untouched(self, tmp_path):
        # current behavior: an absolute path without .7z is not mangled
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "archive"))
        assert path == str(tmp_path / "archive")

    def test_stale_archive_replaced_not_appended(self, tmp_path):
        # `7z a` APPENDS to an existing archive, so a stale .7z must not be
        # kept: the new archive contains only the current tree.
        folder = _make_folder(tmp_path)
        path = str(tmp_path / "game.7z")
        with open(path, "wb") as f:
            f.write(b"STALE-OLD-BYTES")
        compress.compress(folder, path)
        assert compress.test_archive(path) is True
        assert "game/index.html" in archive.names(path)

    def test_missing_folder_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compress.compress(str(tmp_path / "nope"),
                              str(tmp_path / "game.7z"))

    def test_no_sevenz_binary_is_needed(self, tmp_path, monkeypatch):
        """The whole point of the py7zr backend: packaging no longer depends
        on an installed 7-Zip (only the Windows-side bridge does).

        There is no native-``7z`` resolver left to disable - py7zr never
        spawns a process - so assert that directly instead of monkeypatching
        a resolver that no longer exists.
        """
        assert not hasattr(tool_registry, "find_7z")
        monkeypatch.setattr(tool_registry, "win_7z", lambda: None)
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        assert compress.test_archive(path) is True

    @pytest.mark.parametrize("level", [1, 15])
    def test_level_is_passed_to_zstd(self, tmp_path, level):
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "g.7z"), level=level)
        assert _is_zstd(path)
        assert compress.test_archive(path) is True

    def test_threads_argument_is_accepted(self, tmp_path):
        # py7zr has no -mmt equivalent; the parameter stays for compatibility
        folder = _make_folder(tmp_path)
        for threads in (None, True, False, 0, 4):
            path = compress.compress(folder, str(tmp_path / (f"g{threads}.7z")),
                                     threads=threads)
            assert compress.test_archive(path) is True


class TestArchiveIntegrity:
    def test_ok_archive(self, tmp_path):
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        assert compress.test_archive(path) is True

    def test_corrupt_archive_returns_false(self, tmp_path):
        path = str(tmp_path / "game.7z")
        with open(path, "wb") as f:
            f.write(b"not a 7z file at all")
        assert compress.test_archive(path) is False

    def test_truncated_archive_returns_false(self, tmp_path):
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        raw = open(path, "rb").read()
        with open(path, "wb") as f:
            f.write(raw[:len(raw) // 2])
        assert compress.test_archive(path) is False

    def test_missing_archive_returns_false(self, tmp_path):
        assert compress.test_archive(str(tmp_path / "nope.7z")) is False

    def test_flipped_payload_byte_is_detected(self, tmp_path):
        """CRC pass must notice damaged member data, not just a bad header."""
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        raw = bytearray(open(path, "rb").read())
        # the last 64 bytes belong to the (uncompressed-stored) footer area of
        # the packed data; flipping them must make verify() fail
        raw[-40] ^= 0xFF
        with open(path, "wb") as f:
            f.write(bytes(raw))
        try:
            ok = compress.test_archive(path)
        except Exception:                      # noqa: BLE001 - also a failure
            ok = False
        assert ok is False


class TestArchiveModule:
    def test_extract_targets_one_subtree(self, tmp_path):
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        dest = tmp_path / "out"
        targets = [n for n in archive.names(path) if n.startswith("game/")]
        archive.extract(path, str(dest), targets=targets)
        assert (dest / "game" / "index.html").is_file()

    def test_extract_refuses_a_windows_side_destination(self, tmp_path,
                                                        monkeypatch):
        """AGENTS.md CRITICAL rule: a WSL-native process must not write a
        /mnt/* tree, so extract() refuses that destination outright.

        The destination is a tmp_path tree and `is_windows_side` is what
        declares it foreign: using a literal `/mnt/c/...` here would mean that
        a REGRESSION of this guard (the mutation table removes it) writes to a
        real drive path on a Windows host instead of failing in the sandbox.
        """
        folder = _make_folder(tmp_path)
        path = compress.compress(folder, str(tmp_path / "game.7z"))
        foreign = str(tmp_path / "mnt-c" / "games" / "game")
        monkeypatch.setattr(platform, "is_windows_side", lambda p: True)
        with pytest.raises(RuntimeError) as ei:
            archive.extract(path, foreign)
        assert "cross-system" in str(ei.value).lower()
        assert not os.path.exists(foreign)

    def test_filters_use_zstd_at_the_requested_level(self):
        py7zr_filters = archive.filters_for(9)
        assert py7zr_filters == [{"id": py7zr.FILTER_ZSTD, "level": 9}]


class TestCorruptArchiveFailsTheRun:
    """A 7z integrity failure must not leave a green exit code behind."""

    def test_pipeline_compress_exits_1(self, tmp_path, monkeypatch):
        import pipeline
        from conftest import make_game
        web = make_game(str(tmp_path / "g"))
        monkeypatch.setattr(compress, "compress", lambda *a, **kw: "x.7z")
        monkeypatch.setattr(compress, "test_archive", lambda a: False)
        with pytest.raises(SystemExit) as ei:
            pipeline.main(["compress", web, "-o", str(tmp_path / "game.7z")])
        assert ei.value.code == 1

    def test_pipeline_compress_ok_stays_0(self, tmp_path, monkeypatch):
        import pipeline
        from conftest import make_game
        web = make_game(str(tmp_path / "g"))
        monkeypatch.setattr(compress, "compress", lambda *a, **kw: "x.7z")
        monkeypatch.setattr(compress, "test_archive", lambda a: True)
        assert pipeline.main(["compress", web, "-o",
                              str(tmp_path / "game.7z")]) is None
