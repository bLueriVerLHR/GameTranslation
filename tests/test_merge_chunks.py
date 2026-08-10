#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/merge_plain_chunks.py chunk QC + merge."""
import json
import os

import pytest

import merge_plain_chunks as mpc
import plain_io


class TestKanaLeft:
    def test_kana_left(self):
        assert mpc.kana_left_in("まだ翻訳されてない") is True

    def test_clean_chinese(self):
        assert mpc.kana_left_in("已经翻译了") is False

    def test_ctrl_codes_exempted(self):
        assert mpc.kana_left_in("\\N[1] こんにちは") is True
        assert mpc.kana_left_in("\\N[1] 你好") is False

    def test_wolf_bgm_path(self):
        assert mpc.kana_left_in("BGM/サウンド") is False

    def test_kana_middle_dot(self):
        assert mpc.kana_left_in("A・B") is False

    def test_standalone_kana_ui(self):
        assert mpc.kana_left_in("あ") is False
        assert mpc.kana_left_in("カタカナ") is False

    def test_honorific_suffix(self):
        assert mpc.kana_left_in("小美ちゃん") is False


class TestCtrlSignature:
    def test_signature(self):
        assert mpc.ctrl_signature("\\C[27]x") == [("C", 1)]
        assert mpc.ctrl_signature("\\C[27]\\N[3]") == [("C", 1), ("N", 1)]

    def test_args_in_signature(self):
        sig = mpc.ctrl_signature("\\P[1,2]")
        assert sig == [("P", 2)]


class TestQcPair:
    def test_perfect_pair(self):
        issues, ok = mpc.qc_pair(["こんにちは", "a\nb"],
                                 ["你好", "A\nB"], 1)
        assert ok and issues == []

    def test_line_count_mismatch(self):
        issues, ok = mpc.qc_pair(["a", "b"], ["x"], 1)
        assert not ok
        assert any("line count" in i for i in issues)

    def test_kana_residue(self):
        issues, ok = mpc.qc_pair(["こんにちは"], ["こんにちは"], 1)
        assert not ok
        assert any("kana" in i for i in issues)

    def test_newline_mismatch(self):
        issues, ok = mpc.qc_pair(["a\nb"], ["x"], 1)
        assert not ok
        assert any("newline" in i for i in issues)

    def test_control_code_diff(self):
        issues, ok = mpc.qc_pair(["\\C[27]a"], ["b"], 1)
        assert not ok
        assert any("control-code" in i for i in issues)

    def test_uncertainty_marker(self):
        issues, ok = mpc.qc_pair(["a"], ["【?】b"], 1)
        assert not ok
        assert any("uncertainty" in i for i in issues)

    def test_empty_value(self):
        issues, ok = mpc.qc_pair(["a"], [""], 1)
        assert not ok
        assert any("empty" in i for i in issues)


class TestMergeFlow:
    def test_merge_writes_json(self, tmp_path, monkeypatch, capsys):
        work = tmp_path
        chunks_dir = work / "chunks"
        chunks_dir.mkdir()
        plain_io.save_lines(plain_io.ja_path(str(chunks_dir), 1),
                            ["こんにちは", "さようなら"])
        plain_io.save_lines(plain_io.zh_path(str(chunks_dir), 1),
                            ["你好", "再见"])
        monkeypatch.setattr("sys.argv", ["merge_plain_chunks.py", str(work)])
        mpc.main()
        with open(str(work / "chunks_translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"こんにちは": "你好", "さようなら": "再见"}
        assert "chunk_01: 2 keys  [OK]" in capsys.readouterr().out

    def test_strict_fails_on_issues(self, tmp_path, monkeypatch):
        work = tmp_path
        chunks_dir = work / "chunks"
        chunks_dir.mkdir()
        plain_io.save_lines(plain_io.ja_path(str(chunks_dir), 1),
                            ["こんにちは"])
        plain_io.save_lines(plain_io.zh_path(str(chunks_dir), 1),
                            ["まだ日本語"])  # kana residue -> issue
        monkeypatch.setattr("sys.argv",
                            ["merge_plain_chunks.py", str(work), "--strict"])
        with pytest.raises(SystemExit) as exc:
            mpc.main()
        assert exc.value.code == 1

    def test_missing_zh_skipped(self, tmp_path, monkeypatch, capsys):
        work = tmp_path
        chunks_dir = work / "chunks"
        chunks_dir.mkdir()
        plain_io.save_lines(plain_io.ja_path(str(chunks_dir), 3), ["k"])
        monkeypatch.setattr("sys.argv", ["merge_plain_chunks.py", str(work)])
        mpc.main()
        out = capsys.readouterr().out
        assert "zh.txt missing" in out
        assert "merged: 0 keys" in out
