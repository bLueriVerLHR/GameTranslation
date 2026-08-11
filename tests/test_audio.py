#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/audio.py probing and re-encoding policy."""
import os

from conftest import make_game

from rpgmaker import audio, config


class TestBitrateCalc:
    def test_known_values(self):
        assert audio.bitrate_calc(16000, 2.0) == 64000
        assert audio.bitrate_calc(28000, 2.0) == 112000
        assert audio.bitrate_calc(1000, 1.0) == 8000

    def test_zero_duration(self):
        assert audio.bitrate_calc(1000, 0) == 0
        assert audio.bitrate_calc(1000, None) == 0


class TestProbe:
    def test_probe_one_ok(self, game_dir, fake_tools):
        _root, web = game_dir
        ffprobe = config.find_ffprobe()
        info = audio.probe_one(ffprobe, os.path.join(web, "audio", "bgm", "bgm1.ogg"))
        assert info["codec"] == "vorbis"
        assert info["channels"] == 2
        assert float(info["duration"]) > 0

    def test_probe_one_missing_file(self, game_dir, fake_tools):
        _root, web = game_dir
        ffprobe = config.find_ffprobe()
        info = audio.probe_one(ffprobe, os.path.join(web, "audio", "missing.ogg"))
        assert "error" in info

    def test_probe_all_sample(self, game_dir, fake_tools):
        _root, web = game_dir
        infos = audio.probe_all(web, workers=2, sample=2)
        assert len(infos) == 2

    def test_iter_audio_files(self, game_dir, fake_tools):
        _root, web = game_dir
        files = list(audio.iter_audio_files(web))
        assert len(files) == 3  # bgm1, bgm_mono, se1
        assert all(f.endswith(".ogg") for f in files)


class TestReencode:
    def test_keep_low_bitrate(self, game_dir, fake_tools):
        _root, web = game_dir
        infos = audio.probe_all(web, workers=2)
        counts, saved = audio.reencode_all(web, infos, workers=1)
        # default bit_rate == threshold -> not > -> all kept
        assert counts.get("keep", 0) == 3
        assert saved == 0

    def test_reencode_high_bitrate(self, game_dir, fake_tools, monkeypatch):
        monkeypatch.setenv("FAKE_HIGH_BITRATE", "1")
        _root, web = game_dir
        infos = audio.probe_all(web, workers=2)
        counts, saved = audio.reencode_all(web, infos, workers=1)
        assert counts.get("keep", 0) == 0
        assert counts.get("reencoded", 0) + counts.get("no-gain", 0) == 3
        assert saved >= 0

    def test_transcode_one_short_file_kept(self, tmp_path, fake_tools):
        p = tmp_path / "tiny.ogg"
        p.write_bytes(b"O" * 100)
        info = {"duration": "0.5", "size": "100", "channels": "2"}
        path, status, saved = audio.transcode_one("unused", str(p), info)
        assert status == "keep"
        assert saved == 0

    def test_probe_csv(self, game_dir, tmp_path, fake_tools):
        _root, web = game_dir
        infos = audio.probe_all(web, workers=1, sample=1)
        out = str(tmp_path / "report.csv")
        audio.write_probe_csv(infos, out)
        with open(out, encoding="utf-8-sig") as f:
            assert "file" in f.read()
