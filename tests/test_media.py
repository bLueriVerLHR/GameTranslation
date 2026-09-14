#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rpgmaker/media.py - the PyAV-based probe/decode surface.

Everything here runs in-process: the audio fixture is a committed real Ogg
Vorbis file (tests/fixtures/sine_loop.ogg, 5.8 KB, LOOPSTART/LOOPLENGTH at
stream level) and the video fixture is encoded by PyAV itself when the build
has libvpx-vp9.  No ffmpeg/ffprobe binary is involved.
"""
import math
import os
import struct
import sys
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from conftest import REAL_OGG, real_ogg  # noqa: E402

from rpgmaker import media  # noqa: E402


def make_wav(path, seconds=1.0, rate=22050, channels=1):
    """A real WAV file written with the stdlib (no encoder needed)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            v = int(9000 * math.sin(2 * math.pi * 440 * i / rate))
            for _ in range(channels):
                frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return str(path)


def make_video(path, frames=5, width=32, height=32, rate=5):
    """A tiny VP9 WebM produced by PyAV (skips if the build lacks libvpx)."""
    av = pytest.importorskip("av")
    if not media.has_codec("libvpx-vp9"):
        pytest.skip("this PyAV build has no libvpx-vp9 encoder")
    with av.open(str(path), "w", format="webm") as out:
        stream = out.add_stream("libvpx-vp9", rate=rate)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "40", "cpu-used": "8", "b:v": "0"}
        for i in range(frames):
            frame = av.VideoFrame(width, height, "yuv420p")
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            frame.pts = i
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return str(path)


class TestProbeAudio:
    def test_real_ogg_reports_every_field(self):
        info = media.probe(REAL_OGG)
        assert info["codec"] == "vorbis"
        assert info["channels"] == 1
        assert info["sample_rate"] == 22050
        assert 1.9 < info["duration"] < 2.1
        assert info["size"] == os.path.getsize(REAL_OGG)

    def test_stream_level_loop_tags_are_read(self):
        """The regression the ffprobe query had: LOOPSTART/LOOPLENGTH live in
        the Vorbis comment (stream level), which `format=...tags` missed."""
        info = media.probe(REAL_OGG)
        assert info["loopstart"] == "22050"
        assert info["looplength"] == "22050"

    def test_wav_probe_matches_its_header(self, tmp_path):
        path = make_wav(tmp_path / "sine.wav", seconds=1.5, rate=16000,
                        channels=2)
        info = media.probe(path)
        assert info["codec"] == "pcm_s16le"
        assert info["channels"] == 2
        assert info["sample_rate"] == 16000
        assert 1.4 < info["duration"] < 1.6
        assert info["loopstart"] is None

    def test_missing_file_is_an_error_dict(self, tmp_path):
        info = media.probe(str(tmp_path / "nope.ogg"))
        assert "error" in info
        assert set(info) == {"error"}

    def test_garbage_file_is_an_error_dict(self, tmp_path):
        bad = tmp_path / "bad.ogg"
        bad.write_bytes(b"not audio at all")
        assert "error" in media.probe(str(bad))

    def test_audio_file_has_no_video_stream(self, tmp_path):
        assert "error" in media.probe_video(real_ogg(str(tmp_path / "a.ogg")))


class TestDecode:
    def test_ok_on_real_ogg(self):
        ok, reason = media.decode_ok(REAL_OGG)
        assert ok is True
        assert "frames" in reason

    def test_ok_on_wav(self, tmp_path):
        path = make_wav(tmp_path / "s.wav", seconds=0.5)
        assert media.decode_ok(path)[0] is True

    def test_truncated_file_fails(self, tmp_path):
        raw = open(REAL_OGG, "rb").read()
        path = tmp_path / "trunc.ogg"
        path.write_bytes(raw[:len(raw) // 3])
        ok, reason = media.decode_ok(str(path))
        assert ok is False
        assert reason

    def test_garbage_file_fails(self, tmp_path):
        path = tmp_path / "garbage.ogg"
        path.write_bytes(b"not audio at all")
        ok, reason = media.decode_ok(str(path))
        assert ok is False
        assert reason


class TestProbeVideo:
    def test_generated_webm_is_probed(self, tmp_path):
        path = make_video(tmp_path / "v.webm", frames=5, rate=5)
        info = media.probe_video(path)
        assert info["codec"] == "vp9"
        assert (info["width"], info["height"]) == (32, 32)
        assert 0.8 < info["duration"] < 1.2
        assert media.decode_ok(path)[0] is True

    def test_missing_file_is_an_error_dict(self, tmp_path):
        assert "error" in media.probe_video(str(tmp_path / "nope.webm"))


def test_has_codec_reports_this_build():
    # PyAV always ships the decoders the toolkit needs; encoders vary by build
    assert media.has_codec("vorbis") is True
    assert media.has_codec("definitely-not-a-codec") is False
