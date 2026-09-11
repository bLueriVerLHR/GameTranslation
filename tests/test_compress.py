#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/compress.py 7z-zstd packaging.

The 7z binary is a fake injected via the SEVENZ env var (conftest
fake_tools), so the archive content and integrity checks run hermetic.
Command-argument construction is verified by capturing subprocess.run;
error paths (missing folder, missing/failing 7z) are covered separately.
"""
import os
import re
import subprocess

import pytest

from rpgmaker import compress, config


def _make_folder(tmp_path, name="game"):
    folder = str(tmp_path / name)
    os.makedirs(os.path.join(folder, "data"), exist_ok=True)
    with open(os.path.join(folder, "index.html"), "w") as f:
        f.write("<!DOCTYPE html>\n")
    return folder


def _failing_7z(tmp_path, launcher_factory, msg="boom"):
    """A fake 7z that always fails (exit 1, stderr=msg).

    Built from a Python stub wrapped in a platform-appropriate launcher, so
    the same test exercises the failure path on POSIX and on Windows."""
    script = tmp_path / "failing_7z.py"
    script.write_text(
        "import sys\n"
        "print(%r, file=sys.stderr)\n" % msg +
        "sys.exit(1)\n", encoding="utf-8")
    return launcher_factory(script)


class TestCompressArchive:
    def test_creates_archive(self, tmp_path, fake_tools):
        folder = _make_folder(tmp_path)
        archive = compress.compress(folder, str(tmp_path / "game.7z"))
        assert archive == str(tmp_path / "game.7z")
        assert os.path.isfile(archive)
        with open(archive) as f:
            assert f.read() == "FAKE-7Z-ARCHIVE\n"

    def test_relative_archive_gets_extension(self, tmp_path, fake_tools,
                                             monkeypatch):
        folder = _make_folder(tmp_path)
        monkeypatch.chdir(tmp_path)
        archive = compress.compress(folder, "rel")
        assert archive == "rel.7z"
        assert os.path.isfile(archive)

    def test_absolute_non_7z_kept_untouched(self, tmp_path, fake_tools):
        # current behavior: an absolute path without .7z is not mangled
        folder = _make_folder(tmp_path)
        archive = compress.compress(folder, str(tmp_path / "archive"))
        assert archive == str(tmp_path / "archive")

    def test_stale_archive_replaced_not_appended(self, tmp_path, fake_tools):
        # `7z a` APPENDS to an existing archive, so compress() deletes a
        # stale .7z first (old entries must not be kept + new ones added).
        folder = _make_folder(tmp_path)
        archive = str(tmp_path / "game.7z")
        with open(archive, "wb") as f:
            f.write(b"STALE-OLD-BYTES")
        compress.compress(folder, archive)
        with open(archive) as f:
            assert f.read() == "FAKE-7Z-ARCHIVE\n"

    def test_missing_folder_raises(self, tmp_path, fake_tools):
        with pytest.raises(FileNotFoundError):
            compress.compress(str(tmp_path / "nope"),
                              str(tmp_path / "game.7z"))


class TestCommandArgs:
    """Capture the 7z argv to verify -m0=zstd / -mx / -mmt construction."""

    def _capture(self, monkeypatch, folder, archive, **kw):
        calls = []
        existed_at_run = []

        def fake_run(cmd, **kwargs):
            # mimic the fake 7z: create the archive so compress()'s size
            # logging works; record whether the path existed at call time.
            calls.append(cmd)
            existed_at_run.append(os.path.exists(cmd[-2]))
            with open(cmd[-2], "wb") as f:
                f.write(b"FAKE-7Z-ARCHIVE\n")
            return subprocess.CompletedProcess(cmd, 0,
                                               stdout="Everything is Ok",
                                               stderr="")

        monkeypatch.setattr("rpgmaker.compress.subprocess.run", fake_run)
        compress.compress(folder, archive, **kw)
        return calls[0], existed_at_run[0]

    def test_zstd_level_and_explicit_threads(self, tmp_path, fake_tools,
                                             monkeypatch):
        folder = _make_folder(tmp_path)
        archive = str(tmp_path / "game.7z")
        cmd, _existed = self._capture(monkeypatch, folder, archive,
                                      level=15, threads=2)
        assert cmd[0] == config.find_7z()
        assert cmd[1:5] == ["a", "-t7z", "-m0=zstd", "-mx=15"]
        assert "-mmt=2" in cmd
        assert cmd[-2:] == [archive, folder]

    def test_threads_true_maps_to_on(self, tmp_path, fake_tools, monkeypatch):
        folder = _make_folder(tmp_path)
        cmd, _e = self._capture(monkeypatch, folder, str(tmp_path / "g.7z"),
                                threads=True)
        assert "-mmt=on" in cmd

    def test_threads_false_disables_mmt(self, tmp_path, fake_tools,
                                        monkeypatch):
        folder = _make_folder(tmp_path)
        cmd, _e = self._capture(monkeypatch, folder, str(tmp_path / "g.7z"),
                                threads=False)
        assert not any(a.startswith("-mmt") for a in cmd)

    def test_threads_zero_disables_mmt(self, tmp_path, fake_tools,
                                       monkeypatch):
        folder = _make_folder(tmp_path)
        cmd, _e = self._capture(monkeypatch, folder, str(tmp_path / "g.7z"),
                                threads=0)
        assert not any(a.startswith("-mmt") for a in cmd)

    def test_threads_none_auto_tunes(self, tmp_path, fake_tools, monkeypatch):
        folder = _make_folder(tmp_path)
        cmd, _e = self._capture(monkeypatch, folder, str(tmp_path / "g.7z"),
                                threads=None)
        mmt = [a for a in cmd if a.startswith("-mmt=")]
        assert len(mmt) == 1
        assert re.fullmatch(r"-mmt=\d+", mmt[0])

    def test_stale_archive_removed_before_run(self, tmp_path, fake_tools,
                                              monkeypatch):
        folder = _make_folder(tmp_path)
        archive = str(tmp_path / "game.7z")
        with open(archive, "wb") as f:
            f.write(b"STALE")
        _cmd, existed = self._capture(monkeypatch, folder, archive)
        assert existed is False  # stale archive was removed before 7z ran


class TestArchiveIntegrity:
    def test_ok_archive(self, tmp_path, fake_tools):
        archive = str(tmp_path / "game.7z")
        with open(archive, "wb") as f:
            f.write(b"stub")
        assert compress.test_archive(archive) is True

    def test_failing_7z_returns_false(self, tmp_path, monkeypatch,
                                      launcher_factory):
        archive = str(tmp_path / "game.7z")
        with open(archive, "wb") as f:
            f.write(b"stub")
        monkeypatch.setenv("SEVENZ", _failing_7z(tmp_path, launcher_factory))
        assert compress.test_archive(archive) is False


class TestErrorPaths:
    def test_7z_missing_raises(self, tmp_path, monkeypatch):
        # find_7z() resolves to a binary that does not exist -> the subprocess
        # fails loudly instead of silently producing a broken archive.
        folder = _make_folder(tmp_path)
        monkeypatch.setattr("rpgmaker.config.find_7z",
                            lambda: str(tmp_path / "no_such_7z"))
        with pytest.raises(FileNotFoundError):
            compress.compress(folder, str(tmp_path / "game.7z"))

    def test_7z_failure_raises_with_stderr(self, tmp_path, monkeypatch,
                                           launcher_factory):
        folder = _make_folder(tmp_path)
        monkeypatch.setenv("SEVENZ", _failing_7z(tmp_path, launcher_factory))
        with pytest.raises(RuntimeError) as ei:
            compress.compress(folder, str(tmp_path / "game.7z"))
        assert "boom" in str(ei.value)
