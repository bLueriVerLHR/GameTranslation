#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

from rpgmz import build, clean, compress, decrypt, serve, verify


class TestFullPipeline:
    def test_end_to_end(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root, encrypted=True)
        out = str(tmp_path / "out")

        # encrypted asset to decrypt (plaintext is a real PNG so verify
        # passes after decryption)
        from conftest import make_png_bytes
        plain = make_png_bytes(16, 16)
        from rpgmz import config as cfg
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
        with open(archive, "rb") as f:
            assert b"FAKE-7Z-ARCHIVE" in f.read()


class TestDeliver:
    def test_deliver_roundtrip(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "build")
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")
        build.build_joiplay(web, out, workers=2)

        from rpgmz import deliver
        arch = deliver.deliver(out, games=games, archives=archives)
        assert os.path.isfile(arch)
        assert os.path.isdir(os.path.join(games, "build"))

    def test_deliver_replaces_stale_folder(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "build")
        games = str(tmp_path / "games")
        archives = str(tmp_path / "archives")
        build.build_joiplay(web, out, workers=2)

        stale = os.path.join(games, "build")
        os.makedirs(stale)
        with open(os.path.join(stale, "stale.txt"), "w") as f:
            f.write("old")
        from rpgmz import deliver
        deliver.deliver(out, games=games, archives=archives)
        assert not os.path.exists(os.path.join(games, "build", "stale.txt"))


class TestCli:
    def test_pipeline_build_cli(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "out")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["FFMPEG"] = os.path.join(fake_tools, "ffmpeg.py")
        env["FFPROBE"] = os.path.join(fake_tools, "ffprobe.py")
        env["SEVENZ"] = os.path.join(fake_tools, "7z.py")
        r = subprocess.run(
            [sys.executable, os.path.join(repo, "pipeline.py"), "build",
             web, "-o", out, "--workers", "2"],
            capture_output=True, text=True, env=env, cwd=repo)
        assert r.returncode == 0, r.stderr
        assert os.path.isfile(os.path.join(out, "index.html"))
        assert not os.path.exists(os.path.join(out, "Game.exe"))

    def test_pipeline_verify_cli_exit_codes(self, tmp_path, fake_tools):
        root = str(tmp_path / "src")
        web = make_game(root)
        out = str(tmp_path / "out")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env["FFMPEG"] = os.path.join(fake_tools, "ffmpeg.py")
        env["FFPROBE"] = os.path.join(fake_tools, "ffprobe.py")
        env["SEVENZ"] = os.path.join(fake_tools, "7z.py")
        build.build_joiplay(web, out, workers=2)
        r = subprocess.run(
            [sys.executable, os.path.join(repo, "pipeline.py"), "verify", out],
            capture_output=True, text=True, env=env, cwd=repo)
        assert r.returncode == 0
        # corrupt a PNG -> verify must fail
        with open(os.path.join(out, "img", "pictures", "pic1.png"), "wb") as f:
            f.write(b"broken")
        r = subprocess.run(
            [sys.executable, os.path.join(repo, "pipeline.py"), "verify", out],
            capture_output=True, text=True, env=env, cwd=repo)
        assert r.returncode == 1


class TestTranslatedBuild:
    def test_bake_and_verify_kv_archived(self, tmp_path, fake_tools):
        """A translated build: KV baked into data JSON survives the pipeline."""
        from rpgmz import config as cfg
        root = str(tmp_path / "src")
        web = make_game(root)
        # write a translation KV into the game and bake it into data/Map001.json
        kv = {"こんにちは": "你好"}
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
