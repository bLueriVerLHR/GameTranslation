#!/usr/bin/env python3
"""Boundary-input contract for the binary format parsers (PLAN Phase 5 task 5).

The archive/image formats come from third-party games, so every parser in
this repository is reading *attacker-controlled* input.  The contract that
matters for a batch unpack is therefore not "it decodes correct files" (the
example tests cover that) but:

  * a corrupt or truncated payload raises the module's documented error, or
    a `ValueError` from the decoder - never `IndexError`, `struct.error`,
    `UnicodeDecodeError`, a silent wrong answer, or a hang;
  * the error is raised in bounded time, because a hang has no output, no
    exit code and nothing for a caller to catch.

Both halves are measured, not assumed.  Fuzzing these parsers before writing
the properties (a throwaway probe over ~3000 random buffers) found two real
defects that no example test could see, and both chose which properties to
pin:

  * `kirikiri/xp3tool.py::find_chunk` advanced with ``pos += 12 + _i64_at(..)``
    where the size is *signed*.  A declared size of exactly -12 made the
    advance a no-op, so on a magic mismatch the ``while pos + 12 <= end``
    condition stayed true forever - a hang inside `parse_index`.  Fixed by
    validating ``chunk_size <= 0`` before using it as an advance, and by
    returning that validated size.
  * `wolfrpg/dxarchive.py::huffman_decode` / `lz_decode` read past the end of
    the buffer and followed the ``-1`` node sentinel, leaking `IndexError`
    (100% of random inputs for `huffman_decode`) and `ValueError`, which the
    archive test had codified by catching a four-type tuple.

`test_find_chunk_never_hangs` is the regression test for the hang: it runs the
call in a child process, because a hang cannot be asserted from inside the
same interpreter.
"""

import os
import random
import re
import subprocess
import sys
import struct
import zlib

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from kirikiri import tlg, xp3tool  # noqa: E402
from test_dxarchive import huffman_encode  # noqa: E402 - shared test encoder
from wolfrpg import dxarchive as dx  # noqa: E402

#: Exceptions a parser is allowed to raise on hostile input.  Every parser
#: here documents one of these; anything else (IndexError, struct.error,
#: UnicodeDecodeError, MemoryError) is a defect, not a rejection.  `zlib.error`
#: is in the list because a corrupt compressed segment surfaces from the
#: standard library's decompressor.
DOCUMENTED = (ValueError, xp3tool.Xp3Error, tlg.TlgError, zlib.error)


def _random_buffers(seed, count, min_size=0, max_size=64):
    rng = random.Random(seed)
    for _ in range(count):
        yield bytes(rng.randrange(256)
                    for _ in range(rng.randrange(min_size, max_size)))


def _target(fn, *args):
    """Call `fn`, returning the exception *type* (or None) - never raising."""
    try:
        fn(*args)
    except BaseException as exc:  # noqa: BLE001 - the type is the measurement
        return type(exc)
    return None


# ---------------------------------------------------------------------------
# XP3
# ---------------------------------------------------------------------------

class TestXp3Boundaries:
    def test_find_chunk_rejects_non_positive_declared_sizes(self):
        """The exact bug: -12 and 0 cannot advance the scan.

        -12 is the value that used to hang (`parse_index` advances by the
        returned size, so 12 + (-12) == 0); 0 advances only by the header and
        can never reach the magic.
        """
        for size in (-12, -1, 0):
            buf = b"XXXX" + struct.pack("<q", size) + b"data" * 4
            with pytest.raises(xp3tool.Xp3Error, match="non-positive|chunk"):
                xp3tool.find_chunk(buf, 0, len(buf), b"info")

    def test_find_chunk_never_returns_a_size_that_cannot_advance(self):
        """A matched chunk returns the validated size, so callers may use it."""
        payload = b"PAYLOAD!"
        buf = b"info" + struct.pack("<q", len(payload)) + payload
        ofs, size = xp3tool.find_chunk(buf, 0, len(buf), b"info")
        assert size == len(payload)
        assert buf[ofs:ofs + size] == payload

    def test_find_chunk_never_hangs(self):
        """Regression: size -12 used to spin forever (child process + timeout).

        A hang cannot be observed from inside the interpreter that is hanging,
        so the call runs in a subprocess with a hard timeout.  The bounded-time
        contract is the point: a batch unpack must fail, not stall.
        """
        code = (
            "import struct, sys\n"
            f"sys.path.insert(0, {REPO_ROOT!r})\n"
            "from kirikiri import xp3tool\n"
            "buf = b'XXXX' + struct.pack('<q', -12) + b'data' * 8\n"
            "try:\n"
            "    xp3tool.find_chunk(buf, 0, len(buf), b'info')\n"
            "except xp3tool.Xp3Error:\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(3)\n")
        proc = subprocess.run([sys.executable, "-c", code], timeout=30,
                              capture_output=True, encoding="utf-8", errors="replace")
        assert proc.returncode == 0, proc.stderr

    def test_random_index_bytes_never_leak_a_foreign_exception(self):
        """`parse_index` on random bytes: documented error or partial entries."""
        leaked = []
        for raw in _random_buffers(20260918, 200, max_size=80):
            exc = _target(xp3tool.parse_index, raw, 0)
            if exc is not None and not issubclass(exc, DOCUMENTED):
                leaked.append((raw[:12], exc.__name__))
        assert leaked == [], f"undocumented exceptions: {leaked[:5]}"

    def test_declared_size_past_the_buffer_is_an_xp3_error(self):
        """A sub-chunk may not point past the index buffer (struct.error)."""
        buf = b"File" + struct.pack("<q", 1 << 20) + b"info" + b"\x00" * 8
        with pytest.raises(xp3tool.Xp3Error):
            xp3tool.parse_index(buf, 0)

    def test_negative_name_length_is_rejected(self):
        info = struct.pack("<IQQH", 0, 0, 0, 0xFFFF)  # nlen = -1 as int16
        file_chunk = (b"File" + struct.pack("<q", len(info))
                      + b"info" + struct.pack("<q", len(info)) + info)
        with pytest.raises(xp3tool.Xp3Error, match="name length|needs"):
            xp3tool.parse_index(file_chunk, 0)


# ---------------------------------------------------------------------------
# DXArchive (Wolf RPG)
# ---------------------------------------------------------------------------

class TestDxArchiveBoundaries:
    def test_lz_decode_rejects_a_declared_size_past_the_buffer(self):
        src = struct.pack("<IIB", 0, 1 << 20, 0xFF) + b"abc"
        with pytest.raises(ValueError, match="declares"):
            dx.lz_decode(src, 0)

    def test_lz_decode_rejects_a_back_reference_before_the_start(self):
        """A back-reference may not read before the decoded output."""
        # escape: keycode 0xFF, code byte 0 (indexsize 0 -> 1-byte index),
        # index 0 -> reads dest[-1]
        src = struct.pack("<IIB", 0, 9 + 2 + 1, 0xFF) + b"\xff\x00\x00"
        with pytest.raises(ValueError, match="back-reference"):
            dx.lz_decode(src, 4)

    def test_lz_decode_reads_all_three_index_widths(self):
        """indexsize 0/1/2 select a 1/2/3-byte index.

        Each form has its own `src[sp + 2]` / `struct.unpack_from` read, and a
        wrong width would silently decode a different back-reference.  The
        streams below are measured to raise the back-reference guard, which is
        only reachable *after* the width was parsed - so reaching it proves the
        parse happened.  (A truncated one is rejected earlier, by the
        `need` computation, which is a different statement.)
        """
        cases = (
            (0, b"\xff\x00\x04", "back-reference 5"),    # 1-byte index
            (1, b"\xff\x01\x00\x02", "back-reference 513"),  # 2-byte
            (2, b"\xff\x02\x00\x00\x02", "back-reference 131073"),
        )
        for width, payload, expected in cases:
            src = struct.pack("<IIB", 0, 9 + len(payload), 0xFF) + payload
            with pytest.raises(ValueError, match=re.escape(expected)):
                dx.lz_decode(src, 64)
            assert width in (0, 1, 2)  # documents which width each case is

    def test_lz_decode_index_width_three_needs_three_bytes(self):
        """indexsize=3 is the 3-byte width; one byte short is truncation."""
        src = struct.pack("<IIB", 0, 9 + 2, 0xFF) + b"\xff\x03"
        with pytest.raises(ValueError, match="truncated"):
            dx.lz_decode(src, 4)

    def test_lz_decode_needs_a_byte_for_the_extra_length_bits(self):
        """`code & 0x4` adds a length byte; its absence is truncation."""
        src = struct.pack("<IIB", 0, 9 + 2, 0xFF) + b"\xff\x04"
        with pytest.raises(ValueError, match="truncated"):
            dx.lz_decode(src, 4)

    def test_lz_decode_back_reference_loop_and_tail(self):
        """The overlapping copy loop, and its trailing partial copy.

        A back-reference can run past the current output (that is how LZ
        expands runs), so the loop repeats `dest[start:start+num]` while
        `conbo > num` and then copies the remainder.  A literal first, so
        `start >= 0` and the copy is legal - the measured result is the run
        `b"AAAAAAAAA"`, not an error.
        """
        payload = b"A\xff\x20\x00"
        src = struct.pack("<IIB", 0, 9 + len(payload), 0xFF) + payload
        assert dx.lz_decode(src, 9) == b"A" + b"A" * 8

    def test_lz_decode_truncated_escape_is_a_value_error(self):
        src = struct.pack("<IIB", 0, 9 + 1, 0xFF) + b"\xff"
        with pytest.raises(ValueError, match="truncated"):
            dx.lz_decode(src, 4)

    def test_huffman_truncated_header_is_a_value_error(self):
        with pytest.raises(ValueError):
            dx.huffman_decode(b"\x00")

    def test_huffman_truncation_points_are_all_reported(self):
        """The three distinct truncation sites, with measured offsets.

        A valid stream cut short must fail as a corrupt block, whichever read
        runs off the end first.  The offsets are measured against a real
        encoded stream (206 bytes for 8 symbols) rather than guessed:

        * 194 - inside the header's weight table;
        * 196 - exactly at the payload start (`payload_start >= len(src)`);
        * 197 - inside the payload (the `_at` bounds check).
        """
        encoded = huffman_encode(b"\xab" * 8, [1] * 256)
        assert len(encoded) == 206, len(encoded)
        for cut, match in ((194, "header needs more bits"),
                           (196, "payload starts past the end"),
                           (197, "truncated payload")):
            with pytest.raises(ValueError, match=match):
                dx.huffman_decode(encoded[:cut])

    def test_random_bytes_never_leak_a_foreign_exception(self):
        leaked = []
        for raw in _random_buffers(20260919, 300, max_size=64):
            for fn in (dx.huffman_decode, lambda b: dx.lz_decode(b, 0)):
                exc = _target(fn, raw)
                if exc is not None and not issubclass(exc, DOCUMENTED):
                    leaked.append((fn, raw[:8], exc.__name__))
        assert leaked == [], f"undocumented exceptions: {leaked[:5]}"

    def test_random_lz_roundtrip_and_hostile_tail(self):
        """Truncating a *valid* stream anywhere must still be a ValueError."""
        rng = random.Random(20260920)
        for size in (1, 2, 5, 17, 64, 300):
            data = bytes(rng.randrange(256) for _ in range(size))
            encoded = _lz_encode(data)
            for cut in range(len(encoded)):
                raw = encoded[:cut]
                # size is passed as an argument rather than captured: the
                # lambda must not read the loop variable (B023).
                exc = _target(lambda b, n: dx.lz_decode(b, n), raw, size)
                if exc is not None and not issubclass(exc, DOCUMENTED):
                    pytest.fail("truncation at %d leaked %s for %d bytes"
                                % (cut, exc.__name__, size))


def _lz_encode(data):
    """Minimal LZ encoder: all literals except the keycode, which escapes.

    Only needs to be *valid* - the round-trip properties above use the real
    decoder against a stream this repository's own packer would accept.  The
    declared destination size is the true output size, so a correct stream
    produces no size-mismatch warning.
    """
    keycode = 0xFF
    payload = bytearray()
    for byte in data:
        if byte == keycode:
            payload += bytes([keycode, keycode])
        else:
            payload.append(byte)
    return bytes(struct.pack("<IIB", len(data), 9 + len(payload), keycode)
                 + bytes(payload))


# ---------------------------------------------------------------------------
# TLG images
# ---------------------------------------------------------------------------

class TestTlgBoundaries:
    @pytest.mark.parametrize("size", [0, 1, 8, 63])
    def test_short_input_is_a_tlg_error_not_a_struct_error(self, size):
        with pytest.raises(tlg.TlgError):
            tlg.parse_header(b"\x00" * size)

    @pytest.mark.parametrize("magic", [b"TLG6.0", b"TLG5.0", b"XXXYYY",
                                       b"XXXZZZ", b"JKMXE8"])
    def test_known_magic_with_garbage_body_is_documented(self, magic):
        raw = magic + b"\x00" * (64 - len(magic))
        exc = _target(tlg.parse_header, raw)
        assert exc is not None and issubclass(exc, DOCUMENTED), exc

    def test_random_bytes_never_leak_a_foreign_exception(self):
        leaked = []
        for raw in _random_buffers(20260921, 300, max_size=128):
            exc = _target(tlg.parse_header, raw)
            if exc is not None and not issubclass(exc, DOCUMENTED):
                leaked.append((raw[:8], exc.__name__))
        assert leaked == [], f"undocumented exceptions: {leaked[:5]}"

    def test_a_truncated_real_header_body_is_not_a_crash(self):
        """A plausible header whose pixel data is missing."""
        body = struct.pack("<I", 64) + struct.pack("<I", 64)
        raw = (b"TLG5.0\x00raw\x1a" + b"\x00" * 5 + bytes([3])
               + b"\x00" + body)
        exc = _target(tlg.parse_header, raw)
        assert exc is None or issubclass(exc, DOCUMENTED), exc
