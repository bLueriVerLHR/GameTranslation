"""Unit tests for kirikiri/tlg.py (TLG5/TLG6 decoder)."""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kirikiri import tlg



def zero_run_stream(count):
    """Golomb stream for a single zero-run of `count` pixels (bit0 = zero flag)."""
    bit_count = count.bit_length()
    bits = [0] + [0] * (bit_count - 1) + [1]
    bits += [(count - (1 << (bit_count - 1))) >> i & 1 for i in range(bit_count - 1)]
    nbytes = (len(bits) + 7) // 8
    stream = bytearray(nbytes)
    for bi, b in enumerate(bits):
        stream[bi // 8] |= b << (bi % 8)
    return stream

def make_tlg6_payload(w, h, colors):
    """Build a minimal TLG6 stream (all-zero pixels, zero-run per block)."""
    H = 8
    W = 8
    xbc = (w - 1) // W + 1
    ybc = (h - 1) // H + 1
    payload = bytearray()
    payload += struct.pack("<i", 512)  # max_bit_length
    # filter types: all zero (no filter), LZSS: flags=0x00 + N literals 0x00
    nbytes = xbc * ybc
    lit = b"\x00" * nbytes
    body = b""
    for i in range(0, len(lit), 8):
        body += b"\x00" + lit[i:i + 8]
    payload += struct.pack("<i", len(body))
    payload += body
    for _ in range(ybc):
        for c in range(colors):
            # one zero-run block: golomb stream with bit0=0 (zero flag) and
            # unary count covering the block pixel count (8 rows x full width)
            stream = zero_run_stream(8 * w)
            payload += struct.pack("<i", len(stream) * 8)
            payload += bytes(stream)
    return bytes(payload)


def build_tlg6_blocks(w, h, colors=4):
    """Synthetic TLG6 where each 8-row block is a single zero-run of
    pixel_count entries (requires w >= 8 so per-block counts are uniform)."""
    H = 8
    W = 8
    xbc = (w - 1) // W + 1
    ybc = (h - 1) // H + 1
    header = b"TLG6.0\x00raw\x1a" + bytes([colors, 0, 0, 0]) + struct.pack("<II", w, h)
    payload = bytearray()
    payload += struct.pack("<i", 512)
    nbytes = xbc * ybc
    lit = b"\x00" * nbytes
    body = b""
    for i in range(0, len(lit), 8):
        body += b"\x00" + lit[i:i + 8]
    payload += struct.pack("<i", len(body))
    payload += body
    for _ in range(ybc):
        for c in range(colors):
            stream = zero_run_stream(8 * w)
            payload += struct.pack("<i", len(stream) * 8)
            payload += bytes(stream)
    return wrap_tlg0(header + bytes(payload))


def wrap_tlg0(inner):
    """Wrap raw TLG6 bytes in a TLG0.0 SDS header."""
    return b"TLG0.0\x00sds\x1a" + struct.pack("<I", len(inner)) + inner


def build_tlg6(w, h, colors=4):
    header = b"TLG6.0\x00raw\x1a" + bytes([colors, 0, 0, 0]) + struct.pack("<II", w, h)
    return wrap_tlg0(header + make_tlg6_payload(w, h, colors))


class TestHeader:
    def test_parse_tlg0_wrapped_tlg6(self):
        data = build_tlg6(8, 8)
        ver, w, h, colors, off = tlg.parse_header(data)
        assert ver == 6
        assert (w, h) == (8, 8)
        assert colors == 4

    def test_parse_bare_tlg6(self):
        header = b"TLG6.0\x00raw\x1a\x04\x00\x00\x00" + struct.pack("<II", 16, 16)
        ver, w, h, colors, off = tlg.parse_header(header + make_tlg6_payload(16, 16, 4))
        assert ver == 6
        assert (w, h) == (16, 16)

    def test_parse_unknown_magic(self):
        with pytest.raises(tlg.TlgError):
            tlg.parse_header(b"NOTATLG" + b"\x00" * 32)

    def test_parse_too_small(self):
        with pytest.raises(tlg.TlgError):
            tlg.parse_header(b"TLG0.0\x00sds\x1a")

    def test_parse_tlg6_bad_colors(self):
        data = b"TLG6.0\x00raw\x1a\x07\x00\x00\x00" + struct.pack("<II", 8, 8) + b"\x00" * 8
        with pytest.raises(tlg.TlgError):
            tlg.parse_header(wrap_tlg0(data))


class TestDecode:
    def test_decode_allzero(self):
        data = build_tlg6_blocks(8, 8)
        rgba = tlg.decode(data)
        assert len(rgba) == 8 * 8 * 4
        assert rgba == b"\x00" * (8 * 8 * 4)

    def test_decode_allzero_3colors(self):
        data = build_tlg6_blocks(8, 8, colors=3)
        rgba = tlg.decode(data)
        assert len(rgba) == 8 * 8 * 4

    def test_decode_wide_narrow(self):
        for (w, h) in [(8, 8), (8, 7), (16, 8), (24, 24), (32, 16), (40, 32)]:
            data = build_tlg6_blocks(w, h)
            rgba = tlg.decode(data)
            assert len(rgba) == w * h * 4, (w, h)

    def test_decode_real_file(self):
        p = Path(__file__).resolve().parent.parent / "tmp" / "taimanin_work" / "unpacked"
        real = sorted(p.glob("**/*.tlg"))
        if not real:
            pytest.skip("no real TLG files present")
        data = (real[0]).read_bytes()
        ver, w, h, colors, _ = tlg.parse_header(data)
        rgba = tlg.decode(data)
        assert len(rgba) == w * h * 4

    def test_decode_to_png(self, tmp_path):
        data = build_tlg6_blocks(8, 8)
        out = tmp_path / "out.png"
        w, h = tlg.decode_to_png(data, str(out))
        assert out.exists()
        assert out.stat().st_size > 0
        assert (w, h) == (8, 8)


class TestNumbaPath:
    def test_fast_path_matches_pure(self):
        data = build_tlg6_blocks(16, 16)
        ver, w, h, colors, off = tlg.parse_header(data)
        if not tlg._USE_NUMBA:
            pytest.skip("numba not available")
        fast = bytes(tlg._decode_tlg6_fast(data, w, h, colors, off))
        pure = tlg._decode_tlg6(data, w, h, colors, off)
        assert fast == pure

    def test_real_fast_matches_pure(self):
        p = Path(__file__).resolve().parent.parent / "tmp" / "taimanin_work" / "unpacked"
        real = sorted(p.glob("**/*.tlg"))
        if not real:
            pytest.skip("no real TLG files present")
        if not tlg._USE_NUMBA:
            pytest.skip("numba not available")
        data = real[0].read_bytes()
        ver, w, h, colors, off = tlg.parse_header(data)
        fast = bytes(tlg._decode_tlg6_fast(data, w, h, colors, off))
        pure = tlg._decode_tlg6(data, w, h, colors, off)
        assert fast == pure
