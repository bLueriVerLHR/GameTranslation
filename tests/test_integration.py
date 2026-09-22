#!/usr/bin/env python3
"""Integration tests: the full conversion pipeline on a synthetic game.

Runs build -> decrypt -> clean -> verify -> serve smoke test -> compress
-> deliver with the fake tools, plus a real CLI invocation as a subprocess
and a translated-build flow (bake a KV into the data and re-verify).
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import free_port, make_game

from rpgmaker import build, clean, compress, decrypt, deliverables, serve, tool_registry, verify


class TestFullPipeline:
    def test_end_to_end(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root, encrypted=True)
        out = str(tmp_path / "out")

        # encrypted asset to decrypt (plaintext is a real PNG so verify
        # passes after decryption)
        from conftest import make_png_bytes
        plain = make_png_bytes(16, 16)
        from rpgmaker import constants as cfg
        enc = bytearray(cfg.RPGMV_HEADER + plain)
        key = bytes.fromhex("0123456789abcdef0123456789abcdef")
        for i in range(min(16, len(enc) - 16)):
            enc[16 + i] ^= key[i]
        with open(os.path.join(web, "img", "pictures", "secret.png_"), "wb") as f:
            f.write(bytes(enc))

        build.build_joiplay(web, out, workers=2)
        decrypt.decrypt_and_clear(out)
        clean.cleanup_all(out)
        assert verify.verify_all(out, workers=2) == []

        results, ok = serve.smoke_test(out, port=free_port())
        assert ok, results

        archive = str(tmp_path / "game.7z")
        compress.compress(out, archive)
        assert compress.test_archive(archive)

    def test_compressed_archive_has_build(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "out")
        build.build_joiplay(web, out, workers=2)
        archive = str(tmp_path / "g.7z")
        compress.compress(out, archive, threads=2)
        assert compress.test_archive(archive) is True
        # the build folder is stored under its own basename
        from rpgmaker import archive as archive_mod
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
        out = str(tmp_path / "out")
        build.build_joiplay(web, out, workers=2)
        archive = compress.compress(out, str(tmp_path / "g.7z"))
        assert compress.test_archive(archive) is True


class TestDeliver:
    def test_deliver_roundtrip(self, tmp_path, fake_tools, monkeypatch):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "build")
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")
        build.build_joiplay(web, out, workers=2)

        from rpgmaker import deliver
        monkeypatch.setattr(deliverables, "temp_dir", lambda: str(tmp_path / "temp"))
        arch = deliver.deliver(out, games=games, archives=archives)
        assert os.path.isfile(arch)
        assert os.path.isdir(os.path.join(games, "build"))

    def test_deliver_replaces_stale_folder(self, tmp_path, fake_tools,
                                          monkeypatch):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "build")
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")
        build.build_joiplay(web, out, workers=2)

        stale = os.path.join(games, "build")
        os.makedirs(stale)
        with open(os.path.join(stale, "stale.txt"), "w", encoding="utf-8") as f:
            f.write("old")
        from rpgmaker import deliver
        monkeypatch.setattr(deliverables, "temp_dir", lambda: str(tmp_path / "temp"))
        deliver.deliver(out, games=games, archives=archives)
        assert not os.path.exists(os.path.join(games, "build", "stale.txt"))

    def test_extract_wsl_side_reports_a_missing_archive(self, monkeypatch):
        """The WSL-side extract is pure py7zr, so a missing archive surfaces
        as the file error itself - no external 7-Zip lookup is involved."""
        from rpgmaker import deliver
        assert not hasattr(tool_registry, "find_7z")
        with pytest.raises(FileNotFoundError):
            deliver._extract_wsl_side("a.7z", "dest", "name")


class TestCli:
    def test_pipeline_build_cli(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "out")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["FFMPEG"] = fake_tools["ffmpeg"]
        r = subprocess.run(
            [sys.executable, os.path.join(repo, "pipeline.py"), "build",
             web, "-o", out, "--workers", "2"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, cwd=repo)
        assert r.returncode == 0, r.stderr
        assert os.path.isfile(os.path.join(out, "index.html"))
        assert not os.path.exists(os.path.join(out, "Game.exe"))

    def test_pipeline_verify_cli_exit_codes(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "out")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["FFMPEG"] = fake_tools["ffmpeg"]
        build.build_joiplay(web, out, workers=2)
        r = subprocess.run(
            [sys.executable, os.path.join(repo, "pipeline.py"), "verify", out],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, cwd=repo)
        assert r.returncode == 0
        # corrupt a PNG -> verify must fail
        with open(os.path.join(out, "img", "pictures", "pic1.png"), "wb") as f:
            f.write(b"broken")
        r = subprocess.run(
            [sys.executable, os.path.join(repo, "pipeline.py"), "verify", out],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, cwd=repo)
        assert r.returncode == 1


class TestTranslatedBuild:
    def test_translated_text_survives_build_and_verify(self, tmp_path, fake_tools):
        """A build carrying already-translated data passes the pipeline checks.

        (Writing the translation into data/ is bake_translation.py's job; this
        test covers the build + verify half of the flow.)
        """
        root = str(tmp_path / "src")
        web = make_game(root)
        data_path = os.path.join(web, "data", "Map001.json")
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
        data["events"] = [{"name": "こんにちは"}]
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        out = str(tmp_path / "out")
        build.build_joiplay(web, out, workers=2)
        with open(os.path.join(out, "data", "Map001.json"), encoding="utf-8") as f:
            assert "こんにちは" in f.read()  # not baked, just verify content
        assert verify.verify_all(out, workers=2) == []
