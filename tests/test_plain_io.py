#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/plain_io.py two-file chunk escaping/IO."""
import os

import pytest

import plain_io


class TestEscapeRoundTrip:
    @pytest.mark.parametrize("s", [
        "plain text",
        "line1\nline2",
        "backslash \\ and more",
        "control \\C[27] code",
        "literal \\n text",          # backslash + n must survive as such
        "carriage\rreturn",
        "mixed \\n real\n and \\\\ backslashes",
        "full-width space \u3000 kana \u3042",
        "\\N[1] name macro",
        "",
    ])
    def test_roundtrip(self, s):
        assert plain_io.unescape_line(plain_io.escape_line(s)) == s

    def test_escape_mapping(self):
        assert plain_io.escape_line("a\nb\\c") == "a\\nb\\\\c"
        assert plain_io.escape_line("\r") == "\\r"

    def test_unescape_passthrough(self):
        # lone backslashes before non-special chars stay as-is
        assert plain_io.unescape_line("a\\x") == "a\\x"


class TestLineIO:
    def test_save_load_roundtrip(self, tmp_path):
        p = str(tmp_path / "chunk_01.ja.txt")
        lines = ["first", "with \\n escape", "with real\nnewline", "\\N[1]"]
        plain_io.save_lines(p, lines)
        assert plain_io.load_lines(p) == lines

    def test_load_crlf_and_bom(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_bytes(b"\xef\xbb\xbfline1\r\nline2\r\n")
        assert plain_io.load_lines(str(p)) == ["line1", "line2"]

    def test_load_empty(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_bytes(b"")
        assert plain_io.load_lines(str(p)) == []

    def test_load_json_bom(self, tmp_path):
        p = tmp_path / "j.json"
        p.write_bytes(b"\xef\xbb\xbf{\"a\": 1}")
        assert plain_io.load_json(str(p)) == {"a": 1}

    def test_save_json_stable(self, tmp_path):
        p = tmp_path / "j.json"
        plain_io.save_json(str(p), {"中文": "值", "b": [1, 2]})
        with open(p, encoding="utf-8") as f:
            assert "中文" in f.read()

    def test_chunk_paths(self, tmp_path):
        d = str(tmp_path)
        assert plain_io.ja_path(d, 1) == os.path.join(d, "chunk_01.ja.txt")
        assert plain_io.zh_path(d, 1) == os.path.join(d, "chunk_01.zh.txt")

    def test_load_pair(self, tmp_path):
        d = str(tmp_path)
        plain_io.save_lines(plain_io.ja_path(d, 1), ["k1"])
        plain_io.save_lines(plain_io.zh_path(d, 1), ["v1"])
        assert plain_io.load_pair(d, 1) == (["k1"], ["v1"])
        assert plain_io.load_pair(d, 2) == (None, None)
