#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/rvdata2_io.py Ruby Marshal 4.8 decoder.

Streams are hand-crafted per the marshal spec (header \\x04\\x08), so the
tests pin down the decoding independently of any encoder.
"""
import struct

import pytest

from rvdata2_io import Decoder, MarshalError, load_rvdata2

HDR = b"\x04\x08"


def fixnum(n):
    """Canonical fixnum encoding the decoder understands."""
    if n == 0:
        return b"\x00"
    if 1 <= n <= 255:
        return b"\x01" + bytes([n])
    if 256 <= n <= 0xFFFF:
        return b"\x02" + struct.pack("<H", n)
    if -128 <= n <= -1:
        return b"\xff" + struct.pack("<b", n)
    if -0x8000 <= n <= -129:
        return b"\xfe" + struct.pack("<h", n)
    raise ValueError("unhandled fixnum %d" % n)


def string(s):
    return b'"' + fixnum(len(s.encode("utf-8"))) + s.encode("utf-8")


def symbol(s):
    return b":" + fixnum(len(s.encode("utf-8"))) + s.encode("utf-8")


def load(data):
    return Decoder(HDR + data).load()


class TestScalars:
    @pytest.mark.parametrize("n", [0, 1, 5, 127, 128, 255, 256, 1000, 65535,
                                   -1, -5, -128, -129, -1000, -32768])
    def test_fixnums(self, n):
        assert load(b"i" + fixnum(n)) == n

    def test_nil_true_false(self):
        assert load(b"0") is None
        assert load(b"T") is True
        assert load(b"F") is False

    def test_string(self):
        assert load(string("hello")) == "hello"

    def test_string_utf8(self):
        assert load(string("日本語")) == "日本語"

    def test_float(self):
        assert load(b"f" + fixnum(3) + b"1.5") == 1.5
        assert load(b"f" + fixnum(3) + b"inf") == float("inf")

    def test_symbol_and_link(self):
        assert load(symbol("foo")) == "foo"
        assert load(symbol("foo") + b";" + fixnum(0)) == "foo"

    def test_bignum(self):
        assert load(b"l+" + fixnum(2) + b"\x01\x00") == 1
        assert load(b"l-" + fixnum(1) + b"\x02") == -2


class TestCollections:
    def test_array(self):
        assert load(b"[" + fixnum(2) + b"i" + fixnum(1) + b"i" + fixnum(2)) == [1, 2]

    def test_array_link(self):
        # @N resolves to a previously registered object; both outer
        # elements reference the same (empty) inner array
        stream = (b"[" + fixnum(2) + b"[" + fixnum(0)
                  + b"@" + fixnum(1) + b"@" + fixnum(1))
        assert load(stream) == [[], []]

    def test_hash(self):
        assert load(b"{" + fixnum(1) + string("k") + b"i" + fixnum(1)) == {"k": 1}

    def test_object(self):
        stream = (b"o" + symbol("Game_Actor")
                  + fixnum(2) + symbol("@hp") + b"i" + fixnum(100)
                  + symbol("@mp") + b"i" + fixnum(50))
        obj = load(stream)
        assert obj["@hp"] == 100
        assert obj["__class__"] == "Game_Actor"

    def test_struct(self):
        stream = (b"S" + symbol("Point")
                  + fixnum(2) + symbol("x") + b"i" + fixnum(1)
                  + symbol("y") + b"i" + fixnum(2))
        obj = load(stream)
        assert obj == {"x": 1, "y": 2, "__struct__": "Point"}

    def test_userdef_raw_bytes(self):
        assert load(b"u" + symbol("RPG::Table") + fixnum(4) + b"\x00\x01\x02\x03") \
            == b"\x00\x01\x02\x03"

    def test_umarshal(self):
        obj = load(b"U" + symbol("Marshal::Thing") + b"[" + fixnum(0))
        assert obj["__umarshal__"] == "Marshal::Thing"

    def test_regexp(self):
        obj = load(b"/" + fixnum(4) + b"ab+c" + fixnum(0))
        assert obj["__regexp__"] == "ab+c"

    def test_class_module(self):
        assert load(b"c" + symbol("Foo")) == {"__class__": "Foo"}
        assert load(b"m" + symbol("Mod")) == {"__module__": "Mod"}

    def test_ivar_wrapper(self):
        obj = load(b"I" + string("text") + fixnum(1) + symbol("E") + b"T")
        assert obj == "text"


class TestErrors:
    def test_bad_header(self):
        with pytest.raises(MarshalError):
            Decoder(b"\x00\x00").load()

    def test_truncated(self):
        with pytest.raises(MarshalError):
            load(b"[" + fixnum(5) + b"i")

    def test_unknown_type(self):
        with pytest.raises(MarshalError):
            load(b"Z")

    def test_bad_link(self):
        with pytest.raises(MarshalError):
            load(b"@" + fixnum(99))

    def test_load_from_file(self, tmp_path):
        p = tmp_path / "Map001.rvdata2"
        p.write_bytes(HDR + b"i" + fixnum(42))
        assert load_rvdata2(str(p)) == 42
