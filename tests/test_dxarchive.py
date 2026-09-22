#!/usr/bin/env python3
"""Unit tests for wolfrpg/dxarchive.py DXArchive v8 unpacker.

The LZ and Huffman encoders below were derived from the decoder semantics
and cross-verified empirically against the real decoder (bit layout:
header MSB-first, payload path-bits packed LSB-first).  They build valid
streams from scratch, so the tests run without any .wolf fixture file.
"""
import random
import struct
import zlib

import pytest

from wolfrpg import dxarchive as dx


# ---------------------------------------------------------------- key math

class TestKey:
    def test_key_create_structure(self):
        key = dx.key_create(b"DXLIBARC")
        assert len(key) == 7
        even = b"DLBR"
        odd = b"XIAC"
        c0 = zlib.crc32(even) & 0xFFFFFFFF
        c1 = zlib.crc32(odd) & 0xFFFFFFFF
        assert key == struct.pack("<II", c0, c1)[:7]

    def test_key_create_short_source_appends_default(self):
        assert dx.key_create(b"") == dx.key_create(b"DXLIBARC")

    def test_key_deterministic(self):
        assert dx.key_create(b"game") == dx.key_create(b"game")

    def test_key_conv_roundtrip(self):
        data = bytearray(b"0123456789abcdef0123456789abcdef")
        orig = bytes(data)
        key = dx.key_create(b"DXLIBARC")
        dx.key_conv(data, 0, key)
        assert data != orig
        dx.key_conv(data, 0, key)
        assert bytes(data) == orig

    def test_key_conv_position_offset(self):
        data = bytearray(b"0123456789")
        key = dx.key_create(b"DXLIBARC")
        before = bytes(data)
        dx.key_conv(data, 5, key)
        assert bytes(data) != before
        dx.key_conv(data, 5, key)
        assert bytes(data) == before
        # a different position produces a different ciphertext
        data2 = bytearray(b"0123456789")
        dx.key_conv(data2, 0, key)
        assert bytes(data2) != bytes(data)

    def test_key_conv_empty_key_noop(self):
        data = bytearray(b"abc")
        dx.key_conv(data, 0, b"")
        assert bytes(data) == b"abc"


# ---------------------------------------------------------------- header

class TestDxaHeader:
    def _header(self, **kw):
        head = 0x5844
        version = kw.get("version", 8)
        flags = kw.get("flags", 0)
        return struct.pack("<HHIQQQQIIB15s", head, version, 0x40, 0,
                           64, 0, 0, 0, flags, 0xFF, b"")

    def test_parse(self):
        h = dx.DxaHeader(self._header())
        assert h.version == 8
        assert not h.no_key
        assert not h.no_head_press
        assert h.crypt_version == 0

    def test_bad_magic(self):
        raw = bytearray(self._header())
        raw[0:2] = b"\x41\x41"
        with pytest.raises(ValueError):
            dx.DxaHeader(bytes(raw))

    def test_unsupported_version(self):
        with pytest.raises(ValueError):
            dx.DxaHeader(self._header(version=9))

    def test_no_key_flag(self):
        h = dx.DxaHeader(self._header(flags=dx.DXA_FLAG_NO_KEY))
        assert h.no_key

    def test_crypt_version_rejected(self):
        h = dx.DxaHeader(self._header(flags=0x20000))
        assert h.crypt_version == 2


# ---------------------------------------------------------------- LZ codec

def lz_encode(data, keycode=0xFF):
    """Naive LZ77 encoder for the DXLib LZ scheme (matches lz_decode)."""
    out = bytearray()
    out += len(data).to_bytes(4, "little")
    out += b"\x00\x00\x00\x00"
    out += bytes([keycode])
    i = 0
    n = len(data)
    while i < n:
        best = None
        for length in range(min(n - i, 35), 3, -1):
            found = data.find(data[i:i + length], max(0, i - 0x10000), i)
            if found != -1:
                best = (length, i - found)
                break
        if best is not None:
            length, offset = best
            if offset <= 0xFFFF:
                code = (length - 4) << 3
                if offset > 0xFFFF:
                    code |= 0x4
                if offset <= 0xFF:
                    idx_bits = 0
                elif offset <= 0xFFFF:
                    idx_bits = 1
                else:
                    idx_bits = 2
                out.append(keycode)
                out.append(code | idx_bits)
                if idx_bits == 0:
                    out.append(offset - 1)
                elif idx_bits == 1:
                    out += (offset - 1).to_bytes(2, "little")
                else:
                    v = offset - 1
                    out += (v & 0xFFFF).to_bytes(2, "little")
                    out.append(v >> 16)
                i += length
                continue
        b = data[i]
        out += bytes([keycode, keycode]) if b == keycode else bytes([b])
        i += 1
    out[4:8] = len(out).to_bytes(4, "little")
    return bytes(out)


class TestLzDecode:
    def test_all_literals(self):
        data = b"ABCDEF"
        enc = lz_encode(data)
        assert enc[:4] == (6).to_bytes(4, "little")
        assert dx.lz_decode(enc, len(data)) == data

    def test_literal_keycode_escaped(self):
        data = b"A\xffB"
        enc = lz_encode(data)
        assert dx.lz_decode(enc, len(data)) == data

    def test_backreference(self):
        data = b"abracadabra" * 5
        enc = lz_encode(data)
        assert len(enc) < len(data)  # really compressed
        assert dx.lz_decode(enc, len(data)) == data

    def test_large_offset_index(self):
        data = b"x" * 200 + b"y" * 10 + b"x" * 150
        enc = lz_encode(data)
        assert dx.lz_decode(enc, len(data)) == data

    def test_empty(self):
        enc = lz_encode(b"")
        assert dx.lz_decode(enc, 0) == b""

    def test_too_small_block(self):
        with pytest.raises(ValueError):
            dx.lz_decode(b"\x00\x00", 4)


# ---------------------------------------------------------------- Huffman

def _build_tree(weights):
    nodes = [{"weight": w, "child": (-1, -1), "parent": -1} for w in weights]
    node_num = 256
    while len([n for n in nodes if n["parent"] == -1]) > 1:
        min1 = min2 = -1
        for idx in range(len(nodes)):
            if nodes[idx]["parent"] != -1:
                continue
            if min1 == -1 or nodes[min1]["weight"] > nodes[idx]["weight"]:
                min2, min1 = min1, idx
            elif min2 == -1 or nodes[min2]["weight"] > nodes[idx]["weight"]:
                min2 = idx
        nodes.append({"weight": nodes[min1]["weight"] + nodes[min2]["weight"],
                      "child": (min1, min2), "parent": -1})
        nodes[min1]["parent"] = node_num
        nodes[min2]["parent"] = node_num
        nodes[min1]["index"] = 0
        nodes[min2]["index"] = 1
        node_num += 1
    paths = {}
    for i in range(256):
        bits = []
        idx = i
        while nodes[idx]["parent"] != -1:
            bits.append(nodes[idx]["index"])
            idx = nodes[idx]["parent"]
        paths[i] = bits[::-1]
    return paths


class _Bits:
    """Bit writer: msb_first for the header, lsb_first for the payload."""

    def __init__(self, msb_first):
        self.bits = []
        self.msb = msb_first

    def write(self, bits):
        self.bits.extend(bits)

    def bytes(self):
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            b = 0
            for k, bit in enumerate(self.bits[i:i + 8]):
                if self.msb:
                    b |= bit << (7 - k)
                else:
                    b |= bit << k
            out.append(b)
        return bytes(out)


def huffman_encode(symbols, weights):
    """Encode `symbols` (bytes) with the DXLib Huffman scheme.

    Verified against the real decoder: header bits MSB-first, payload =
    per-symbol tree path (root-first) packed LSB-first into bytes, with
    trailing zero-padding bytes (the decoder reads one lookahead byte).
    """
    paths = _build_tree(weights)
    h = _Bits(msb_first=True)

    def msb(v, n):
        h.write([(v >> k) & 1 for k in range(n - 1, -1, -1)])

    bitnum_a = max(8, len(symbols).bit_length())
    msb(bitnum_a - 1, 6)
    msb(len(symbols), bitnum_a)
    msb(7, 6)  # bitnum_b = 8
    msb(1, 8)  # press_size (ignored by the decoder)
    for i in range(256):
        delta = weights[i] - (weights[i - 1] if i else 0)
        if delta >= 0:
            b = max(1, (delta.bit_length() + 1) // 2)
            minus = 0
        else:
            b = max(1, ((-delta).bit_length() + 1) // 2)
            minus = 1
        msb(b - 1, 3)
        msb(minus, 1)
        msb(abs(delta), b * 2)
    hdr = h.bytes()
    p = _Bits(msb_first=False)
    for s in symbols:
        p.write(paths[s])
    return hdr + p.bytes() + b"\x00\x00"


class TestHuffmanDecode:
    def test_slow_path_small_payload(self):
        # dest_size < 17: the whole payload decodes via the tree walk
        data = bytes([0, 1, 2, 3, 255])
        assert dx.huffman_decode(huffman_encode(data, [1] * 256)) == data

    def test_main_path_large_payload(self):
        import random
        random.seed(42)
        data = bytes(random.randrange(256) for _ in range(500))
        assert dx.huffman_decode(huffman_encode(data, [1] * 256)) == data

    def test_unbalanced_tree_long_codes(self):
        # weights that force codes > 9 bits (exercises the walk path)
        import random
        random.seed(7)
        weights = [random.randint(1, 500) for _ in range(256)]
        paths = _build_tree(weights)
        assert max(len(v) for v in paths.values()) > 9
        data = bytes(random.randrange(256) for _ in range(300))
        assert dx.huffman_decode(huffman_encode(data, weights)) == data

    def test_single_symbol(self):
        assert dx.huffman_decode(huffman_encode(b"\xab", [1] * 256)) == b"\xab"

    def test_empty(self):
        assert dx.huffman_decode(huffman_encode(b"", [1] * 256)) == b""


# ---------------------------------------------------------------- full archive

def make_wolf_archive(files, key_string=b"DXLIBARC", no_key=False):
    """Build a minimal valid .wolf container with `files` = [(name, bytes)].

    Header block = name table + file table + dir table (single root dir),
    Huffman+LZ compressed, keyed when not no_key.
    """
    key = dx.key_create(key_string)
    name_entries = []
    fheads = []
    file_table = bytearray()
    name_table = bytearray()
    data_start = 0
    payload = bytearray()

    for name, _content in files:
        name_b = name.encode("shift_jis")
        upper = name.upper().encode("shift_jis")
        words = (len(upper) + 3) // 4
        entry = struct.pack("<HH", words, 0) + upper + b"\x00" * (words * 4 - len(upper)) + name_b + b"\x00"
        name_entries.append(len(name_table))
        name_table += entry
    for i, (name, content) in enumerate(files):
        fheads.append(len(file_table))
        file_table += struct.pack("<Q Q QQQ Q Q Q Q",
                                  name_entries[i], 0, 0, 0, 0,
                                  data_start, len(content),
                                  0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF)
        if no_key:
            payload += content
        else:
            # per-file key: keyString + name-table bytes (uppercased name +
            # padded, then the original name) truncated at the first NUL -
            # exactly what create_key_file_string() derives
            upper = name.upper().encode("shift_jis")
            words = (len(upper) + 3) // 4
            fname = (upper + b"\x00" * (words * 4 - len(upper))
                     + name.encode("shift_jis")).split(b"\x00")[0]
            fkey = dx.key_create(key_string + fname)
            enc = bytearray(content)
            dx.key_conv(enc, len(content), fkey)
            payload += bytes(enc)
        data_start += len(content)
    dir_table = struct.pack("<QQQQ", 0, 0xFFFFFFFFFFFFFFFF,
                            len(files), 0)
    file_table_start = len(name_table)
    dir_table_start = file_table_start + len(file_table)
    head_buffer = bytes(name_table) + bytes(file_table) + dir_table

    lz = lz_encode(head_buffer)
    huff = huffman_encode(lz, [1] * 256)
    huff = bytearray(huff)
    if not no_key:
        dx.key_conv(huff, 0, key)

    data_start_file = 64 + len(huff)
    head = struct.pack("<HHIQQQQIIB15s", 0x5844, 8, 0x40, data_start_file,
                       64, file_table_start, dir_table_start, 0,
                       dx.DXA_FLAG_NO_KEY if no_key else 0, 0xFF, b"")
    return bytes(head) + bytes(huff) + bytes(payload)


class TestUnpackArchive:
    def test_plain_files(self, tmp_path):
        files = [("a.txt", b"hello world"), ("b.bin", b"\x00\x01\x02")]
        arch = tmp_path / "test.wolf"
        arch.write_bytes(make_wolf_archive(files))
        out = tmp_path / "out"
        n = dx.unpack_archive(str(arch), str(out), b"DXLIBARC")
        assert n == 2
        assert (out / "a.txt").read_bytes() == b"hello world"
        assert (out / "b.bin").read_bytes() == b"\x00\x01\x02"

    def test_custom_key(self, tmp_path):
        files = [("k.txt", b"secret")]
        arch = tmp_path / "k.wolf"
        arch.write_bytes(make_wolf_archive(files, key_string=b"custom"))
        out = tmp_path / "out"
        n = dx.unpack_archive(str(arch), str(out), b"custom")
        assert n == 1
        assert (out / "k.txt").read_bytes() == b"secret"

    def test_wrong_key_garbage_warns(self, tmp_path, caplog):
        """A wrong key yields garbage that must be reported as a ValueError.

        The broad ``(ValueError, IndexError, UnicodeDecodeError, OSError)``
        tuple this used to accept was the symptom of the decoders leaking
        IndexError / UnicodeDecodeError on a corrupt stream; the contract is
        one exception type with a message that says the block is corrupt, so
        the caller can tell a bad key from a bug in this module.
        """
        files = [("k.txt", b"secret")]
        arch = tmp_path / "k.wolf"
        arch.write_bytes(make_wolf_archive(files, key_string=b"custom"))
        out = tmp_path / "out"
        with pytest.raises(ValueError, match="Huffman|LZ block"):
            dx.unpack_archive(str(arch), str(out), b"wrong")

    def test_no_key_archive(self, tmp_path):
        files = [("plain.txt", b"data")]
        arch = tmp_path / "n.wolf"
        arch.write_bytes(make_wolf_archive(files, no_key=True))
        out = tmp_path / "out"
        n = dx.unpack_archive(str(arch), str(out), b"DXLIBARC")
        assert n == 1
        assert (out / "plain.txt").read_bytes() == b"data"

    def test_too_small_file(self, tmp_path):
        arch = tmp_path / "tiny.wolf"
        arch.write_bytes(b"\x00" * 10)
        with pytest.raises(ValueError):
            dx.unpack_archive(str(arch), str(tmp_path / "out"), b"DXLIBARC")

    def test_crypt_version_rejected(self, tmp_path):
        raw = bytearray(make_wolf_archive([("a", b"x")]))
        struct.pack_into("<I", raw, 44, 0x20000)  # flags field: cryptVersion = 2
        arch = tmp_path / "v.wolf"
        arch.write_bytes(bytes(raw))
        with pytest.raises(ValueError, match="crypt version"):
            dx.unpack_archive(str(arch), str(tmp_path / "out"), b"DXLIBARC")

    def test_protection_strip(self, tmp_path):
        content = dx.ANTI_UNPACK_DATA + b"real data"
        files = [("game.dat", content)]
        arch = tmp_path / "p.wolf"
        arch.write_bytes(make_wolf_archive(files))
        out = tmp_path / "out"
        dx.unpack_archive(str(arch), str(out), b"DXLIBARC")
        assert (out / "game.dat").read_bytes() == b"real data"

    def test_protection_strip_disabled(self, tmp_path):
        content = dx.ANTI_UNPACK_DATA + b"real data"
        files = [("game.dat", content)]
        arch = tmp_path / "p.wolf"
        arch.write_bytes(make_wolf_archive(files))
        out = tmp_path / "out"
        dx.unpack_archive(str(arch), str(out), b"DXLIBARC",
                          skip_protection_cleanup=True)
        assert (out / "game.dat").read_bytes() == content


class TestRandomRoundtrip:
    """Random content + random key strings must round-trip through the LZ,
    Huffman and key codecs (AGENTS.md task-rule 4: random sampling instead of
    a fixed spot check).  Every assert is an invariant for ANY input, so the
    fixed seeds are just for reproducibility - never flaky."""

    def test_random_lz_roundtrip(self):
        rng = random.Random(20260830)
        for _ in range(25):
            n = rng.randrange(0, 400)
            data = bytes(rng.randrange(256) for _ in range(n))
            enc = lz_encode(data)
            assert dx.lz_decode(enc, len(data)) == data, n

    def test_random_lz_repetitive_and_keycode(self):
        rng = random.Random(20260831)
        # highly compressible patterns exercise the backreference path
        for _ in range(10):
            pattern = bytes(rng.randrange(256)
                            for _ in range(rng.randrange(1, 16)))
            data = pattern * rng.randrange(1, 30)
            assert dx.lz_decode(lz_encode(data), len(data)) == data
        # keycode (0xFF) - heavy data exercises the literal-escape path
        for _ in range(10):
            data = bytes([0xFF]) * rng.randrange(0, 200)
            assert dx.lz_decode(lz_encode(data), len(data)) == data
        for _ in range(10):
            n = rng.randrange(0, 200)
            data = bytes([0xFF if rng.random() < 0.4 else rng.randrange(256)
                          for _ in range(n)])
            assert dx.lz_decode(lz_encode(data), len(data)) == data

    def test_random_huffman_roundtrip(self):
        rng = random.Random(20260832)
        for _ in range(15):
            data = bytes(rng.randrange(256)
                         for _ in range(rng.randrange(0, 400)))
            assert dx.huffman_decode(huffman_encode(data, [1] * 256)) == data

    def test_random_huffman_unbalanced(self):
        rng = random.Random(20260833)
        for _ in range(8):
            weights = [rng.randint(1, 500) for _ in range(256)]
            paths = _build_tree(weights)
            assert max(len(v) for v in paths.values()) > 0
            data = bytes(rng.randrange(256)
                         for _ in range(rng.randrange(0, 350)))
            assert dx.huffman_decode(huffman_encode(data, weights)) == data

    def test_random_key_conv_involution(self):
        rng = random.Random(20260834)
        for _ in range(25):
            n = rng.randrange(0, 200)
            data = bytearray(bytes(rng.randrange(256) for _ in range(n)))
            key = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 17)))
            orig = bytes(data)
            dx.key_conv(data, 0, key)
            dx.key_conv(data, 0, key)
            assert bytes(data) == orig

    def test_random_archive_roundtrip(self, tmp_path):
        rng = random.Random(20260835)
        for trial in range(6):
            key_str = bytes(rng.choice(b"abcdefghijklmnopqrstuvwxyz")
                            for _ in range(rng.randrange(1, 12)))
            files = []
            for i in range(rng.randrange(1, 8)):
                content = bytes(rng.randrange(256)
                                for _ in range(rng.randrange(0, 600)))
                files.append(("f%d.dat" % i, content))
            arch = tmp_path / ("rand_%d.wolf" % trial)
            arch.write_bytes(make_wolf_archive(files, key_string=key_str))
            out = tmp_path / ("out_%d" % trial)
            n = dx.unpack_archive(str(arch), str(out), key_str)
            assert n == len(files)
            for name, content in files:
                assert (out / name).read_bytes() == content

    def test_edge_empty_and_single_byte(self):
        """Empty and single-byte payloads are the codec edge cases."""
        assert dx.lz_decode(lz_encode(b""), 0) == b""
        assert dx.lz_decode(lz_encode(b"\x00"), 1) == b"\x00"
        assert dx.huffman_decode(huffman_encode(b"", [1] * 256)) == b""
        assert dx.huffman_decode(huffman_encode(b"\xab", [1] * 256)) == b"\xab"
