#!/usr/bin/env python3
"""Tests for rpgmaker/media.py - the PyAV-based probe/decode surface.

Everything here runs in-process: the audio fixture is a committed real Ogg
Vorbis file (tests/fixtures/sine_loop.ogg, 5.8 KB, LOOPSTART/LOOPLENGTH at
stream level) and the video fixture is encoded by PyAV itself when the build
has libvpx-vp9.  No ffmpeg/ffprobe binary is involved.

Marked `media` where a real codec is the point (video encode/decode/transcode:
the PyAV wheel must carry libvpx-vp9, and the assertions are about container
and codec details).  Probing a committed Ogg stays in the fast layer - the
fixture is tracked, so it works on any machine.
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

from conftest import REAL_OGG, make_wmv, real_ogg  # noqa: E402

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


def ogg_crc(data):
    """Ogg page CRC (poly 0x04C11DB7, no reflection, no final xor)."""
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) if crc & 0x80000000 else (crc << 1)
            crc &= 0xFFFFFFFF
    return crc


def ogg_with_bad_utf8_tags(src, dst):
    """Copy `src`, writing Shift-JIS bytes into a Vorbis comment value.

    Length-preserving, so only that one page's CRC has to be recomputed.
    Returns the new path.
    """
    data = bytearray(Path(src).read_bytes())
    pos = 0
    while pos < len(data):
        assert data[pos:pos + 4] == b"OggS", f"not an Ogg page at {pos}"
        nsegs = data[pos + 26]
        seg_table = data[pos + 27:pos + 27 + nsegs]
        body = pos + 27 + nsegs
        body_len = sum(seg_table)
        if data[body:body + 7] == b"\x03vorbis":
            vlen = struct.unpack_from("<I", data, body + 7)[0]
            count_at = body + 11 + vlen
            first_at = count_at + 4
            clen = struct.unpack_from("<I", data, first_at)[0]
            key, sep, value = bytes(data[first_at + 4:first_at + 4 + clen]).partition(b"=")
            assert sep and len(value) >= 2, "fixture comment has no value to corrupt"
            eq_at = first_at + 4 + len(key) + 1
            data[eq_at:eq_at + 2] = b"\x82\xa0"
            struct.pack_into("<I", data, pos + 22, 0)
            struct.pack_into("<I", data, pos + 22,
                             ogg_crc(bytes(data[pos:body + body_len])))
            break
        pos = body + body_len
    else:  # pragma: no cover - the fixture always carries a comment header
        raise AssertionError("no Vorbis comment header found")
    Path(dst).write_bytes(bytes(data))
    return str(dst)


class TestProbeAudio:
    def test_non_utf8_vorbis_tags_do_not_break_probe(self, tmp_path):
        """Shift-JIS Vorbis comments must not make valid audio look broken.

        Japanese doujin tools write comments in Shift-JIS; PyAV decodes tag
        values as UTF-8 and used to raise UnicodeDecodeError, which made the
        probe fail and `verify --decode` report the file as corrupt.
        """
        src = ogg_with_bad_utf8_tags(REAL_OGG, tmp_path / "sjis.ogg")
        import av

        with pytest.raises(UnicodeDecodeError):
            av.open(src)  # documents what the toolkit has to tolerate
        info = media.probe(src)
        assert "error" not in info, info
        assert info["codec"] == "vorbis"
        assert 1.9 < info["duration"] < 2.1

    def test_non_utf8_vorbis_tags_do_not_break_decode_check(self, tmp_path):
        src = ogg_with_bad_utf8_tags(REAL_OGG, tmp_path / "sjis.ogg")
        ok, reason = media.decode_ok(src)
        assert ok is True, reason

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
    @pytest.mark.media
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


class TestTranscodeToWebm:
    """The VP9 + Opus step that used to shell out to ffmpeg."""

    pytestmark = pytest.mark.media

    def test_round_trip_produces_webm_vp9_opus(self, tmp_path):
        src = make_wmv(tmp_path / "in.wmv", seconds=1.0)
        dst = str(tmp_path / "out.webm")
        media.transcode_to_webm(src, dst)
        video = media.probe_video(dst)
        assert video["codec"] == "vp9"
        assert (video["width"], video["height"]) == (64, 48)
        audio = media.probe(dst)
        assert audio["codec"] == "opus"
        assert audio["sample_rate"] == media.OPUS_RATE
        assert audio["channels"] == 2          # mono source -> stereo output
        assert media.decode_ok(dst)[0] is True

    def test_duration_survives_the_round_trip(self, tmp_path):
        src = make_wmv(tmp_path / "in.wmv", seconds=2.0, rate=5)
        dst = str(tmp_path / "out.webm")
        media.transcode_to_webm(src, dst)
        assert abs(media.probe_video(dst)["duration"] - 2.0) < 0.3

    def test_frame_count_is_preserved(self, tmp_path):
        src = make_wmv(tmp_path / "in.wmv", seconds=1.0, rate=10)
        dst = str(tmp_path / "out.webm")
        media.transcode_to_webm(src, dst)
        frames = 0
        import av

        with av.open(dst) as c:
            vstream = next(s for s in c.streams if s.type == "video")
            for _frame in c.decode(vstream):
                frames += 1
        assert frames == 10

    def test_video_only_source_needs_no_audio_stream(self, tmp_path):
        src = make_wmv(tmp_path / "silent.wmv", seconds=0.5, audio=False)
        dst = str(tmp_path / "out.webm")
        media.transcode_to_webm(src, dst)
        assert media.probe_video(dst)["codec"] == "vp9"
        assert "error" in media.probe(dst)     # no audio stream at all
        assert media.decode_ok(dst)[0] is True

    def test_crf_option_reaches_the_encoder(self, tmp_path):
        """Detail-heavy frames: a very low quality target must be smaller."""
        src = make_wmv(tmp_path / "in.wmv", seconds=1.0, rate=10, noise=True)
        small = tmp_path / "small.webm"
        large = tmp_path / "large.webm"
        media.transcode_to_webm(src, str(small), crf=60)
        media.transcode_to_webm(src, str(large), crf=0)
        assert os.path.getsize(small) < os.path.getsize(large)

    def test_missing_input_raises(self, tmp_path):
        # PyAV raises its own FileNotFoundError for a missing container; the
        # point of the assertion is that the failure is an OSError and not,
        # say, a silent success.
        with pytest.raises(OSError):
            media.transcode_to_webm(str(tmp_path / "nope.wmv"),
                                    str(tmp_path / "out.webm"))

    def test_audio_only_input_is_rejected(self, tmp_path):
        src = real_ogg(str(tmp_path / "a.ogg"))
        with pytest.raises(ValueError):
            media.transcode_to_webm(src, str(tmp_path / "out.webm"))
