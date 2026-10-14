#!/usr/bin/env python3
"""Integration tests: packaging and delivery on a synthetic game.

Runs clean -> compress -> extract -> deliver with the in-process backend,
exercises the same steps through the real CLI as a subprocess, and checks
that already-translated data survives packaging unchanged (the write-back
half of the translation flow is covered by
`tests/test_translation_pipeline.py`).
"""
import json
import os
import subprocess
import sys

import pytest

from tests.helpers import make_game, make_png_bytes

from rpgmaker import archive as archive_mod
from rpgmaker import clean, compress, deliverables, deliver, tool_registry


class TestPackageAndDeliver:
    def test_clean_then_compress_roundtrip(self, tmp_path):
        root = str(tmp_path / "src")
        web = make_game(root)
        clean.cleanup_all(web)
        archive = str(tmp_path / "game.7z")
        compress.compress(web, archive)
        assert compress.test_archive(archive) is True

    def test_compressed_archive_has_game(self, tmp_path):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "out")
        os.makedirs(out)
        with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html>\n")
        archive = str(tmp_path / "g.7z")
        compress.compress(out, archive, threads=2)
        assert compress.test_archive(archive) is True
        # the folder is stored under its own basename
        assert "out/index.html" in archive_mod.names(archive)

    def test_compress_needs_no_7z_binary(self, tmp_path, monkeypatch):
        """The packaged backend is in-process: no 7-Zip required to package.

        There is no native-``7z`` resolver to disable any more (py7zr never
        spawns a process), so assert its absence instead - re-adding one has
        to come with a caller and this test updated.
        """
        assert not hasattr(tool_registry, "find_7z")
        root = str(tmp_path / "src")
        web = make_game(root)
        archive = compress.compress(web, str(tmp_path / "g.7z"))
        assert compress.test_archive(archive) is True

    def test_deliver_roundtrip(self, tmp_path, monkeypatch):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "build")
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")
        compress.compress(web, str(tmp_path / "seed.7z"))

        monkeypatch.setattr(deliverables, "temp_dir", lambda: str(tmp_path / "temp"))
        arch = deliver.deliver(web, games=games, archives=archives)
        assert os.path.isfile(arch)
        assert os.path.isdir(os.path.join(games, "src"))

    def test_deliver_replaces_stale_folder(self, tmp_path, monkeypatch):
        root = str(tmp_path / "src")
        web = make_game(root)
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")

        stale = os.path.join(games, "src")
        os.makedirs(stale)
        with open(os.path.join(stale, "stale.txt"), "w", encoding="utf-8") as f:
            f.write("old")
        monkeypatch.setattr(deliverables, "temp_dir", lambda: str(tmp_path / "temp"))
        deliver.deliver(web, games=games, archives=archives)
        assert not os.path.exists(os.path.join(games, "src", "stale.txt"))

    def test_extract_wsl_side_reports_a_missing_archive(self):
        """The WSL-side extract is pure py7zr, so a missing archive surfaces
        as the file error itself - no external 7-Zip lookup is involved."""
        assert not hasattr(tool_registry, "find_7z")
        with pytest.raises(FileNotFoundError):
            deliver._extract_wsl_side("a.7z", "dest", "name")


class TestTranslatedDataSurvivesPackaging:
    def test_chinese_text_is_preserved_through_pack_and_extract(self, tmp_path):
        root = str(tmp_path / "src")
        web = make_game(root)
        data_path = os.path.join(web, "data", "Map001.json")
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
        data["events"] = [{"name": "こんにちは"}]
        data["displayName"] = "译文"
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        archive = compress.compress(web, str(tmp_path / "t.7z"))
        dest = str(tmp_path / "unpacked")
        archive_mod.extract(archive, dest)
        with open(os.path.join(dest, "src", "data", "Map001.json"),
                  encoding="utf-8") as f:
            text = f.read()
        assert "译文" in text
        assert "こんにちは" in text


class TestCli:
    def _run(self, *argv):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return subprocess.run(
            [sys.executable, os.path.join(repo, "pipeline.py"), *argv],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=repo)

    def test_pipeline_clean_cli(self, tmp_path):
        root = str(tmp_path / "src")
        web = make_game(root)
        r = self._run("clean", web)
        assert r.returncode == 0, r.stderr

    def test_pipeline_compress_cli(self, tmp_path):
        root = str(tmp_path / "src")
        web = make_game(root)
        archive = str(tmp_path / "cli.7z")
        r = self._run("compress", web, "-o", archive)
        assert r.returncode == 0, r.stderr
        assert os.path.isfile(archive)
        assert compress.test_archive(archive) is True

    def test_pipeline_doctor_cli_is_machine_readable(self, tmp_path):
        r = self._run("doctor", "--json")
        assert r.returncode in (0, 1), r.stderr
        assert json.loads(r.stdout)["tools"] is not None


def test_make_game_gives_a_web_root(tmp_path):
    """The fixture this file leans on: a detectable MZ web root."""
    web = make_game(str(tmp_path / "src"))
    assert os.path.isfile(os.path.join(web, "index.html"))
    assert os.path.isdir(os.path.join(web, "data"))
    assert make_png_bytes(4, 4)[:8] == b"\x89PNG\r\n\x1a\n"
