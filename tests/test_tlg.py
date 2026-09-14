"""Unit tests for kirikiri/tlg.py (TLG5/TLG6 decoder)."""

import os
import random
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


# ---------------------------------------------------------------------------
# Synthetic TLG6 with real filter types and non-zero pixels.
# Regression for two historical bugs:
#   1. LZSS literal branch forgot `o += 1` (filter_types corrupted after any
#      literal run -> every image corrupted).
#   2. TLG6 filter value was computed once per block instead of per pixel
#      (GARbro applies the color-correlation filter to the *current* inbuf
#      value on every pixel).
# Both were invisible to all-zero synthetic images and are verified against
# the GARbro C# decoder output below.
# ---------------------------------------------------------------------------

GOLOMB_N = 4


def _golomb_stream(values):
    """Encode non-zero pixel values with the TLG6 Golomb codec (mirrors
    tlg._decode_golomb: zero flag bit0=1, unary run count, k-bit values)."""
    bits = [1]  # bit0: segment is non-zero
    count = len(values)
    bit_count = count.bit_length() - 1
    bits += [0] * bit_count + [1]
    bits += [(count - (1 << bit_count)) >> i & 1 for i in range(bit_count)]
    a = 0
    n = GOLOMB_N - 1
    for val in values:
        if val <= 128:
            v = 2 * val - 1
        else:
            v = 2 * (256 - val)
        k = tlg._GOLOMB_TABLE[a * GOLOMB_N + n]
        bc = v >> k
        extra = v & ((1 << k) - 1)
        bits += [0] * bc + [1]
        bits += [(extra >> i) & 1 for i in range(k)]
        a += v >> 1
        n -= 1
        if n < 0:
            a >>= 1
            n = GOLOMB_N - 1
    nbytes = (len(bits) + 7) // 8
    out = bytearray(nbytes)
    for bi, b in enumerate(bits):
        out[bi // 8] |= b << (bi % 8)
    return bytes(out)


def _lzss_literals(data):
    """LZSS stream with all-literal tokens (flags byte 0x00 per 8 bytes)."""
    out = bytearray()
    for i in range(0, len(data), 8):
        chunk = data[i:i + 8]
        out += b"\x00" + chunk + b"\x00" * (8 - len(chunk))
    return bytes(out)


def build_tlg6_filtered(w, h, colors, filter_types, pixel_values):
    """Synthetic TLG6 with explicit per-block filter types and non-zero
    pixel values (one shared value sequence per channel)."""
    xbc = (w - 1) // 8 + 1
    ybc = (h - 1) // 8 + 1
    assert len(filter_types) == xbc * ybc
    header = b"TLG6.0\x00raw\x1a" + bytes([colors, 0, 0, 0]) + struct.pack("<II", w, h)
    payload = bytearray()
    stream = _golomb_stream(pixel_values)
    payload += struct.pack("<i", len(stream) * 8 + 64)
    ft = _lzss_literals(bytes(filter_types))
    payload += struct.pack("<i", len(ft)) + ft
    for _ in range(ybc):
        for _c in range(colors):
            payload += struct.pack("<i", len(stream) * 8) + stream
    return wrap_tlg0(header + bytes(payload))


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
        p = Path(__file__).resolve().parent.parent / "tmp" / "kiri_work" / "unpacked"
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


class TestRegressionBugs:
    """Regression tests for the two historical decoder bugs that corrupted
    every real game image while all synthetic tests stayed green.

    Reference outputs were produced by compiling GARbro's ImageTLG.cs TLG6
    path verbatim (dotnet) and decoding the same synthetic files.
    """

    def _filtered_image(self, w=64, h=8, ftype=2, colors=3):
        xbc = (w - 1) // 8 + 1
        ybc = (h - 1) // 8 + 1
        filter_types = [ftype] * (xbc * ybc)
        pixel_values = [(i % 253) + 1 for i in range(h * w)]
        return build_tlg6_filtered(w, h, colors, filter_types, pixel_values)

    def test_lzss_literal_advances_output(self):
        # Bug 1: literal branch omitted `o += 1`; every literal overwrote
        # outbuf[0] and filter_types after the first literal was garbage.
        outbuf = bytearray(16)
        text = bytearray(4096)
        # flags=0x00 (8 literal tokens) + 8 literal bytes "ABCDEFGH"
        inbuf = b"\x00ABCDEFGH"
        out, _ = tlg._lzss_decompress_slide(outbuf, inbuf, text, 0)
        assert bytes(out[:8]) == b"ABCDEFGH"
        # literal after copy also advances
        out2 = bytearray(16)
        text2 = bytearray(4096)
        # flags=0b00000001: token0=copy(mpos=0,mlen=3 from zeroed text),
        # then 7 literal tokens; copy writes 3 zero bytes, then literals
        inbuf2 = b"\x01\x00\x00XYZ"
        out2, _ = tlg._lzss_decompress_slide(out2, inbuf2, text2, 0)
        assert bytes(out2[:6]) == b"\x00\x00\x00XYZ"

    def test_filter_type_applied_per_pixel(self):
        # Bug 2: filter value was computed once per block; GARbro computes
        # it from the current inbuf pixel on every pixel (inbuf_index steps).
        # With per-pixel values 1,2,3.. and filter type 2 the two behaviors
        # diverge immediately; the C#-verified expected output is below.
        data = self._filtered_image()
        rgba = tlg.decode(data)
        assert len(rgba) == 64 * 8 * 4
        # pixels are RGBA bytes: [R, G, B, A]
        # filter 2: r=r0+g0, g=g0, b=b0+g0 with MED prediction from
        # zeroline (3-color, alpha=0xFF); verified against C# GARbro decode.
        # (r and b are equal here, so B/R order does not show in this value)
        assert bytes(rgba[0:4]) == b"\x02\x01\x02\xff"
        assert bytes(rgba[4:8]) == b"\x06\x03\x06\xff"
        assert bytes(rgba[8:12]) == b"\x0c\x06\x0c\xff"

    def test_filtered_decode_matches_garbro_reference(self):
        # Decode the C#-verified reference (hex dump produced by compiling
        # GARbro ImageTLG.cs TLG6 path verbatim) for the same synthetic file.
        # GARbro's buffer is B,G,R,A; decode() returns the R,G,B,A contract,
        # so the reference is recorded here already channel-swapped.
        data = self._filtered_image()
        rgba = tlg.decode(data)
        ref_hex = (
            "020102ff060306ff0c060cff140a14ff1e0f1eff2a152aff381c38ff"
            "482448ff"  # first 9 pixels, unchanged: r == b for filter 2 here
            "3a9d3aff2e172eff249224ff1c0e1cff168b16ff120912ff"
            "108810ff100810ff"
        )
        assert rgba[:64].hex() == ref_hex

    def test_swap_rb_moves_channels_and_is_its_own_inverse(self):
        # Regression: decode() used to return the decoder's internal B,G,R,A
        # buffers while documenting RGBA, so Pillow read blue as red and every
        # converted image was red/blue swapped (sprites came out blue-skinned,
        # event stills blue where the matching pre-rendered movie is pink).
        assert tlg._swap_rb(b"\x01\x02\x03\x04") == b"\x03\x02\x01\x04"
        assert tlg._swap_rb(b"\xff\x00\x10\x80") == b"\x10\x00\xff\x80"
        once = tlg._swap_rb(b"\x01\x02\x03\x04\x05\x06\x07\x08")
        assert tlg._swap_rb(once) == b"\x01\x02\x03\x04\x05\x06\x07\x08"

    def test_decode_contract_is_rgba_on_real_fixture(self):
        from PIL import Image

        fixture = Path(__file__).resolve().parent / "fixtures" / "tlg"
        files = sorted(fixture.glob("*.tlg"))
        if not files:
            pytest.skip("no TLG fixtures present")
        data = files[0].read_bytes()
        _v, w, h, _c, _o = tlg.parse_header(data)
        rgba = tlg.decode(data)
        # the fixture must have pixels where R and B differ, otherwise the
        # order assertion below could never fail (non-vacuous check)
        r = rgba[0::4]
        b = rgba[2::4]
        assert r != b, "fixture has no R/B distinction to test with"
        # and the returned buffer must be R,G,B,A, i.e. equal to what Pillow
        # reads back from the PNG written through decode_to_png
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "x.png")
            tlg.decode_to_png(data, out)
            back = Image.open(out).convert("RGBA").tobytes()
        assert back == rgba

    def test_filtered_various_filters(self):
        # Every filter type 0..31 must decode without error and differ from
        # the all-zero case (filter transforms applied per pixel).
        for ftype in range(32):
            data = self._filtered_image(ftype=ftype)
            rgba = tlg.decode(data)
            assert len(rgba) == 64 * 8 * 4
            # filter 0/1 are identity on the value: output must be non-zero
            assert any(rgba[::4])

    def test_filtered_various_colors(self):
        for colors in (3, 4):
            data = self._filtered_image(colors=colors)
            rgba = tlg.decode(data)
            assert len(rgba) == 64 * 8 * 4

    def test_filtered_narrow_width(self):
        # Fractional last block (width not a multiple of 8) exercises the
        # second line_generic call path with per-pixel filters.
        for w in (8, 15, 16, 20):
            data = self._filtered_image(w=w, h=8)
            rgba = tlg.decode(data)
            assert len(rgba) == w * 8 * 4

    def test_numba_path_matches_pure_filtered(self):
        if not tlg._USE_NUMBA:
            pytest.skip("numba not available")
        data = self._filtered_image()
        ver, w, h, colors, off = tlg.parse_header(data)
        fast = bytes(tlg._decode_tlg6_fast(data, w, h, colors, off))
        pure = tlg._decode_tlg6(data, w, h, colors, off)
        assert fast == pure


class TestGarbroFixture:
    """Real-file regression against GARbro-decoded BMP fixtures.

    The .tlg/.bmp pairs under tests/fixtures/tlg/ were produced by GARbro
    (authoritative TLG decoder): tlg = original game file, bmp = GARbro
    export. GARbro GUI exports alpha-flattened 32bpp BMP (bottom-up rows).
    decode() returns RGBA, so the BMP's B,G,R,X rows are read in R,G,B order
    and the planes line up directly.
    """

    FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tlg"

    def _fixtures(self):
        if not self.FIXTURE.is_dir():
            return []
        return sorted(self.FIXTURE.glob("*.tlg"))

    def test_fixtures_exist(self):
        assert self._fixtures(), "tests/fixtures/tlg missing"

    def test_each_fixture_matches_garbro_bmp(self):
        import struct as _struct

        for tlg_path in self._fixtures():
            name = tlg_path.stem
            bmp_path = tlg_path.with_suffix(".bmp")
            assert bmp_path.exists(), bmp_path
            data = tlg_path.read_bytes()
            ver, w, h, colors, _ = tlg.parse_header(data)
            rgba = tlg.decode(data)
            assert len(rgba) == w * h * 4
            # decode() returns R,G,B,A - read the planes straight through
            rows = []
            for y in range(h):
                row = rgba[y * w * 4:(y + 1) * w * 4]
                rows.append([(row[x], row[x + 1], row[x + 2])
                             for x in range(0, w * 4, 4)])
            got_rgb = [c for r in rows for c in r]

            with bmp_path.open("rb") as f:
                bmp = f.read()
            off = _struct.unpack_from("<I", bmp, 10)[0]
            bw, bh = _struct.unpack_from("<ii", bmp, 18)
            assert (bw, bh) == (w, h), (name, (bw, bh), (w, h))
            stride = w * 4
            # BMP rows are bottom-up; unpack BGRX per row
            ref_rgb = []
            for y in range(h):
                row = bmp[off + (h - 1 - y) * stride: off + (h - 1 - y) * stride + stride]
                for x in range(0, w * 4, 4):
                    ref_rgb.append((row[x + 2], row[x + 1], row[x]))
            assert got_rgb == ref_rgb, f"RGB mismatch: {name}"

    def test_fixture_numba_matches_pure(self):
        if not tlg._USE_NUMBA:
            pytest.skip("numba not available")
        for tlg_path in self._fixtures():
            data = tlg_path.read_bytes()
            ver, w, h, colors, off = tlg.parse_header(data)
            fast = bytes(tlg._decode_tlg6_fast(data, w, h, colors, off))
            pure = tlg._decode_tlg6(data, w, h, colors, off)
            assert fast == pure, tlg_path.name


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
        p = Path(__file__).resolve().parent.parent / "tmp" / "kiri_work" / "unpacked"
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


class TestRandomSampleDecode:
    """Random-sampled TLG6 dimension/color/filter combinations must decode to
    the correct output (AGENTS.md task-rule 4: sample randomly instead of
    re-checking one fixed image).  The asserts are invariants that hold for
    ANY sampled combination, so the fixed seeds never make them flaky.

    Note: the filtered builder here writes each block's Golomb stream with
    exactly its own pixel count AND the filter-type LZSS stream without
    trailing padding.  The shared _lzss_literals helper pads to 8 bytes, which
    silently overflows the pure decoder when the block count is not a multiple
    of 8 (the numba path masks that overflow); the correct stream below works
    for arbitrary block counts on both paths.
    """

    H = 8
    W = 8

    @classmethod
    def _lzss_exact_literals(cls, data):
        """All-literal LZSS stream: 0x00 flag per 8 literals, NO padding."""
        out = bytearray()
        for i in range(0, len(data), 8):
            out += b"\x00" + data[i:i + 8]
        return bytes(out)

    @classmethod
    def _build_filtered(cls, w, h, colors, filter_types, pixel_values):
        xbc = (w - 1) // cls.W + 1
        ybc = (h - 1) // cls.H + 1
        assert len(filter_types) == xbc * ybc
        header = (b"TLG6.0\x00raw\x1a" + bytes([colors, 0, 0, 0])
                  + struct.pack("<II", w, h))
        block_streams = []
        for y in range(0, h, cls.H):
            ylim = min(y + cls.H, h)
            pc = (ylim - y) * w
            pv_block = pixel_values[y * w: y * w + pc]
            block_streams.append(_golomb_stream(pv_block))
        max_bits = max(len(s) * 8 for s in block_streams)
        payload = bytearray()
        payload += struct.pack("<i", max_bits + 64)
        ft = cls._lzss_exact_literals(bytes(filter_types))
        payload += struct.pack("<i", len(ft)) + ft
        for s in block_streams:
            for _c in range(colors):
                payload += struct.pack("<i", len(s) * 8) + s
        return wrap_tlg0(header + bytes(payload))

    def test_random_dimensions_and_colors(self):
        rng = random.Random(20260821)
        for _ in range(25):
            colors = rng.choice([1, 3, 4])
            if colors == 1:
                # colors==1 keeps one stream per block, so the wrapped file
                # needs a large enough area to exceed the 64-byte parse min
                # (16x16 would stay under it -> use a verified-safe pool)
                w, h = rng.choice([(16, 24), (24, 16), (24, 24), (32, 16),
                                   (16, 32), (40, 40), (32, 32), (40, 24),
                                   (24, 40), (40, 16), (16, 40)])
            else:
                # verified-safe for colors 3/4 (w=1/h=1 slim cases can stay
                # under the 64-byte parse minimum -> separate edge test)
                w = rng.choice([7, 8, 9, 15, 16, 24, 40])
                h = rng.choice([7, 8, 9, 16, 17, 24])
            data = build_tlg6_blocks(w, h, colors)
            rgba = tlg.decode(data)
            assert len(rgba) == w * h * 4, (w, h, colors)
            if colors == 3:
                # 3-color zero buffers -> RGB 0, alpha pinned to 0xFF
                assert rgba[0::4] == b"\x00" * (w * h)
                assert rgba[1::4] == b"\x00" * (w * h)
                assert rgba[2::4] == b"\x00" * (w * h)
                assert rgba[3::4] == b"\xff" * (w * h)
            else:
                assert rgba == b"\x00" * (w * h * 4)

    def test_slim_edge_dimensions(self):
        """w=1 / h=1 images (single column/row, fractional blocks) still
        decode to the exact size; uses dims that stay above the 64-byte
        parse minimum."""
        for colors in (3, 4):
            for w, h in [(1, 9), (1, 16), (1, 24), (9, 1), (16, 1), (40, 1)]:
                data = build_tlg6_blocks(w, h, colors)
                rgba = tlg.decode(data)
                assert len(rgba) == w * h * 4, (w, h, colors)
                if colors == 3:
                    assert rgba[3::4] == b"\xff" * (w * h)
                else:
                    assert rgba == b"\x00" * (w * h * 4)

    def test_random_filter_types_decode(self):
        rng = random.Random(20260822)
        for _ in range(20):
            w = rng.choice([7, 8, 9, 15, 16, 24, 40])
            h = rng.choice([7, 8, 9, 16, 17, 24])
            colors = rng.choice([3, 4])
            xbc = (w - 1) // 8 + 1
            ybc = (h - 1) // 8 + 1
            filter_types = [rng.randrange(32) for _ in range(xbc * ybc)]
            pixel_values = [(i % 253) + 1 for i in range(h * w)]
            data = self._build_filtered(w, h, colors, filter_types,
                                        pixel_values)
            rgba = tlg.decode(data)
            assert len(rgba) == w * h * 4, (w, h, colors)
            # non-zero pixels must survive the per-pixel filter path
            assert (any(rgba[0::4]) or any(rgba[1::4])
                    or any(rgba[2::4])), (w, h, colors)

    def test_random_numba_matches_pure(self):
        if not tlg._USE_NUMBA:
            pytest.skip("numba not available")
        rng = random.Random(20260823)
        for _ in range(15):
            w = rng.choice([7, 8, 9, 15, 16, 24, 40])
            h = rng.choice([7, 8, 9, 16, 17, 24])
            colors = rng.choice([3, 4])
            xbc = (w - 1) // 8 + 1
            ybc = (h - 1) // 8 + 1
            filter_types = [rng.randrange(32) for _ in range(xbc * ybc)]
            pixel_values = [(i % 253) + 1 for i in range(h * w)]
            data = self._build_filtered(w, h, colors, filter_types,
                                        pixel_values)
            ver, ww, hh, cc, off = tlg.parse_header(data)
            fast = bytes(tlg._decode_tlg6_fast(data, ww, hh, cc, off))
            pure = tlg._decode_tlg6(data, ww, hh, cc, off)
            assert fast == pure, (w, h, colors)

    def test_random_short_truncations_raise(self):
        """Edge: ANY file shorter than 64 bytes must raise TlgError."""
        rng = random.Random(20260824)
        good = build_tlg6_blocks(24, 24, 4)
        for _ in range(10):
            n = rng.randrange(0, 64)
            with pytest.raises(tlg.TlgError):
                tlg.parse_header(good[:n])

    def test_random_bad_magic_raises(self):
        """Edge: corrupting any magic byte must raise TlgError."""
        rng = random.Random(20260825)
        good = build_tlg6_blocks(24, 24, 4)
        for _ in range(10):
            data = bytearray(good)
            pos = rng.randrange(0, 8)
            data[pos] = (data[pos] + 1) % 256
            with pytest.raises(tlg.TlgError):
                tlg.parse_header(bytes(data))
