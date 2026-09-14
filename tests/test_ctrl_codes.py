#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tools/ctrl_codes.py - the single source of control-code helpers.

The point of the module is that extraction, chunk QC and merging agree on
what a control code is, so the cases below pin the behaviour that used to be
duplicated in five files (and check the shapes those copies relied on).
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import ctrl_codes  # noqa: E402


class TestCtrlSignature:
    def test_single_code_counts_one_arg(self):
        assert ctrl_codes.ctrl_signature("\\C[27]x") == [("C", 1)]

    def test_order_is_preserved(self):
        assert ctrl_codes.ctrl_signature("\\C[27]\\N[3]") == [("C", 1), ("N", 1)]

    def test_comma_separated_args_are_counted(self):
        assert ctrl_codes.ctrl_signature("\\P[1,2]") == [("P", 2)]

    def test_translated_args_do_not_change_the_signature(self):
        """The whole point: `\\RB[显示,名]` must match `\\RB[役名,表示]`."""
        ja = "\\RB[役名,表示]です"
        zh = "\\RB[显示,名]啊"
        assert ctrl_codes.ctrl_signature(ja) == ctrl_codes.ctrl_signature(zh)
        assert ctrl_codes.ctrl_signature(ja) == [("RB", 2)]

    def test_empty_args_still_count_as_one(self):
        assert ctrl_codes.ctrl_signature("\\C[]") == [("C", 1)]

    def test_no_codes_is_empty(self):
        assert ctrl_codes.ctrl_signature("ふつうの文") == []
        assert ctrl_codes.ctrl_signature("") == []

    def test_wolf_style_code_is_not_part_of_the_signature(self):
        """`CTRL_ARGS` covers the RPG Maker form; the Wolf `:name[..]` form is
        handled by CTRL_TOKEN (see the strip tests).  Pinned so a future
        'unification' does not silently start reporting them."""
        assert ctrl_codes.ctrl_signature(":name[勇士]と") == []

    def test_multiple_args_with_spaces(self):
        assert ctrl_codes.ctrl_signature("\\RB[表示, 名前]") == [("RB", 2)]


class TestStripCtrl:
    @pytest.mark.parametrize("text,expected", [
        ("\\C[27]あ\\N[1]い", "あい"),
        (":name[勇士]だ", "だ"),
        ("\\AF[3]:face[2]x", "x"),
        ("no codes here", "no codes here"),
        ("", ""),
    ])
    def test_codes_are_removed_but_text_survives(self, text, expected):
        assert ctrl_codes.strip_ctrl(text) == expected

    def test_unknown_backslash_is_left_alone(self):
        """Unknown escapes (`\\x`, a bare backslash) are not control codes and
        must not be swallowed - they are real text content."""
        assert ctrl_codes.strip_ctrl("C:\\tmp\\x") == "C:\\tmp\\x"

    def test_strip_exposes_residual_kana(self):
        import japanese_utils

        assert japanese_utils.KANA.search(
            ctrl_codes.strip_ctrl("\\N[1]の\\C[2]です")) is not None


class TestConsistency:
    def test_signature_ignores_what_strip_removes(self):
        """Anything counted by the signature is removed by strip_ctrl: the two
        helpers must describe the same escape set."""
        sample = "\\C[27]\\N[1]:name[勇士]\\RB[表示,名]端"
        for match in ctrl_codes.CTRL_ARGS.finditer(sample):
            assert match.group(0) not in ctrl_codes.strip_ctrl(sample)
        assert "端" in ctrl_codes.strip_ctrl(sample)

    def test_no_duplicated_implementation_is_left(self):
        """Guard the dedup: the regexes these helpers replaced must not come
        back into the tools that now import them."""
        tools = ["final_qc.py", "merge_plain_chunks.py",
                 "qc_translation_chunks.py", "build_translation.py",
                 "extract_remaining_text.py", "extract_rvdata2.py"]
        for name in tools:
            path = os.path.join(REPO_ROOT, "tools", name)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            assert "CTRL_NORM = re.compile" not in text, name
            assert "CTRL_TOK = re.compile" not in text, name
            assert "CTRL = re.compile" not in text, name
            assert "def ctrl_signature" not in text, name
