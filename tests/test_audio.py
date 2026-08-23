#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/audio.py probing and re-encoding policy."""
import os
import random

import pytest

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


class TestToolMissing:
    """Missing tool binaries raise FileNotFoundError with an install hint."""

    def test_probe_all_raises_when_ffprobe_missing(self, game_dir, monkeypatch):
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffprobe", lambda: None)
        with pytest.raises(FileNotFoundError):
            audio.probe_all(web, workers=1)

    def test_reencode_all_raises_when_ffmpeg_missing(self, game_dir,
                                                     monkeypatch):
        _root, web = game_dir
        monkeypatch.setattr(config, "find_ffmpeg", lambda: None)
        with pytest.raises(FileNotFoundError):
            audio.reencode_all(web, {}, workers=1)


class TestStrategyPattern:
    """Review §5.1: the re-encode policy is a strategy list.  pick_strategy
    must map (channels, bitrate) to the same class as the old inline
    branches, and the classes must be first-class so a new codec policy can
    extend the list without touching transcode_one."""

    def _info(self, ch, fsize, dur=10.0):
        return {"duration": "%.4f" % dur, "size": str(fsize),
                "channels": str(ch)}

    def test_pick_mono_voice(self):
        br = config.MONO_BITRATE_THRESHOLD
        s = audio.pick_strategy(self._info(1, br * 10 // 8 + 8))
        assert isinstance(s, audio.MonoVoiceStrategy)
        assert s.args() == ["-ar", "32000", "-ac", "1", "-c:a", "libvorbis",
                            "-q:a", "2"]

    def test_pick_stereo_music(self):
        br = config.STEREO_BITRATE_THRESHOLD
        s = audio.pick_strategy(self._info(2, br * 10 // 8 + 8))
        assert isinstance(s, audio.StereoMusicStrategy)
        assert s.args() == ["-c:a", "libvorbis", "-q:a", "3"]

    def test_pick_keep_original_below_thresholds(self):
        s = audio.pick_strategy(self._info(1, 1000, 10.0))
        assert isinstance(s, audio.KeepOriginalStrategy)
        assert s.args() == []

    def test_pick_mono_priority_over_music(self):
        # a mono file above BOTH thresholds must pick MonoVoice (priority)
        mono = config.MONO_BITRATE_THRESHOLD * 10 // 8 + 8
        stereo = config.STEREO_BITRATE_THRESHOLD * 10 // 8 + 8
        s = audio.pick_strategy(self._info(1, max(mono, stereo)))
        assert isinstance(s, audio.MonoVoiceStrategy)

    def test_strategy_order_is_priority(self):
        assert [type(s) for s in audio.STRATEGIES] == [
            audio.MonoVoiceStrategy, audio.StereoMusicStrategy,
            audio.KeepOriginalStrategy]

    def test_missing_size_raises_like_legacy(self):
        # a missing "size" key must surface as exc (KeyError) exactly as the
        # old inline code did - MonoVoice.applies touches info["size"] first
        with pytest.raises(KeyError):
            audio.pick_strategy({"duration": "10.0", "channels": "2"})


class TestRandomSamplePolicy:
    """Random-sampled (channels, size, duration) triples must map to the
    documented re-encode policy (AGENTS.md task-rule 4: random sampling, not
    fixed spot checks):

      ch == 1 and bitrate > 64000    -> 32k mono re-encode (-ar 32000 -ac 1)
      ch != 1 and bitrate > 112000   -> stereo q3 re-encode (-q:a 3)
      else                           -> keep
      duration < 1.0                 -> keep (degenerate short placeholder)
      duration <= 0                  -> skip

    Every assert is an invariant for ANY sampled triple, so a fixed seed
    keeps the run reproducible without ever making it flaky.
    """

    MONO = config.MONO_BITRATE_THRESHOLD
    STEREO = config.STEREO_BITRATE_THRESHOLD

    @staticmethod
    def _fake_ffmpeg(monkeypatch, captured):
        """Stub subprocess.run to simulate ffmpeg: writes a tiny output
        (always smaller than the source -> 'reencoded') and records the
        command so the mono/music arg selection can be asserted."""
        def fake_run(cmd, **kw):
            captured.append(cmd)
            with open(cmd[-1], "wb") as f:
                f.write(b"\x00")

            class _R:
                returncode = 0
                stderr = ""
                stdout = ""
            return _R()
        monkeypatch.setattr(audio.subprocess, "run", fake_run)

    def _expected(self, dur, ch, br):
        """Status the documented policy requires for this input."""
        if dur <= 0:
            return "skip"
        if dur < 1.0:
            return "keep"
        if ch == 1 and br > self.MONO:
            return "reencoded"
        if ch != 1 and br > self.STEREO:
            return "reencoded"
        return "keep"

    def test_random_sample_matches_policy(self, tmp_path, monkeypatch):
        rng = random.Random(20260820)
        captured = []
        self._fake_ffmpeg(monkeypatch, captured)
        samples = [(rng.choice([1, 2, 6]), rng.uniform(1.0, 90.0),
                    rng.randrange(1000, 6_000_000)) for _ in range(80)]
        for idx, (ch, dur, fsize) in enumerate(samples):
            path = tmp_path / ("s%d.ogg" % idx)
            path.write_bytes(b"\x00" * fsize)
            br = audio.bitrate_calc(fsize, dur)
            info = {"duration": "%.6f" % dur, "size": str(fsize),
                    "channels": str(ch)}
            captured.clear()
            _p, status, _saved = audio.transcode_one("unused", str(path), info)
            assert status == self._expected(dur, ch, br), \
                (ch, dur, fsize, br, status)
            if status == "reencoded" and ch == 1:
                cmd = captured[0]
                assert "-ac" in cmd and "1" in cmd
                assert "-ar" in cmd and "32000" in cmd
            elif status == "reencoded" and ch != 1:
                cmd = captured[0]
                assert "-q:a" in cmd and "3" in cmd
                assert "-ac" not in cmd  # music stays stereo
            else:
                assert captured == []  # keep/skip never invoke ffmpeg

    def test_threshold_boundaries(self, tmp_path, monkeypatch):
        """Exactly at a threshold -> keep (strict >); just above -> re-encode.
        Catches off-by-one regressions in the policy branches."""
        captured = []
        self._fake_ffmpeg(monkeypatch, captured)
        for ch, br_base in ((1, self.MONO), (2, self.STEREO)):
            dur = 10.0
            fsize_exact = br_base * 10 // 8
            fsize_above = br_base * 10 // 8 + 8
            for fsize, exp in ((fsize_exact, "keep"),
                               (fsize_above, "reencoded")):
                path = tmp_path / ("b%d_%d.ogg" % (ch, fsize))
                path.write_bytes(b"\x00" * fsize)
                captured.clear()
                info = {"duration": "%.4f" % dur, "size": str(fsize),
                        "channels": str(ch)}
                _p, status, _saved = audio.transcode_one(
                    "unused", str(path), info)
                assert status == exp, (ch, fsize, status, exp)

    def test_edge_short_and_bad_durations(self, tmp_path, monkeypatch):
        """Degenerate durations: skip on missing/<=0, keep on < 1s (a
        re-encode would produce a broken Ogg)."""
        captured = []
        self._fake_ffmpeg(monkeypatch, captured)
        path = tmp_path / "edge.ogg"
        path.write_bytes(b"\x00" * 100000)
        cases = [
            ({"duration": "0", "size": "100000", "channels": "2"}, "skip"),
            ({"duration": "-1", "size": "100000", "channels": "2"}, "skip"),
            ({"duration": "0.5", "size": "100000", "channels": "2"}, "keep"),
            ({"duration": "0.999", "size": "9000000", "channels": "2"}, "keep"),
            ({"duration": "60", "size": "100000", "channels": "0"}, "keep"),
        ]
        for info, exp in cases:
            captured.clear()
            _p, status, _saved = audio.transcode_one("unused", str(path), info)
            assert status == exp, (info, status, exp)
            assert captured == []
        # channels=0 with a high bitrate behaves like non-mono (music path)
        captured.clear()
        _p, status, _saved = audio.transcode_one(
            "unused", str(path),
            {"duration": "60", "size": "9000000", "channels": "0"})
        assert status == "reencoded", status
        assert "-q:a" in captured[0] and "3" in captured[0]
