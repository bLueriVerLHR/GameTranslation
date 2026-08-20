#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/merge_plain_chunks.py chunk QC + merge."""
import json
import os
import random

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


class TestRandomSampleQc:
    """Randomly generated ja/zh line pairs must satisfy the QC invariants
    (AGENTS.md task-rule 4: random sampling instead of a fixed spot check).

    A "good" value is derived from its key by replacing every kana character
    with a Chinese equivalent and preserving control codes / newlines /
    backslashes exactly - for ANY such pair qc_pair must pass.  Each injected
    violation (kana left, dropped newline, dropped control code, empty value,
    uncertainty marker, stray backslash, line-count mismatch) must be caught
    by its own rule.  All asserts are invariants, so the fixed seeds only
    make the run reproducible - never flaky.
    """

    # Exactly the kana ranges mpc.KANA flags (hiragana/katakana/halfwidth).
    KANA = frozenset(
        ord(c) for lo, hi in ((0x3041, 0x3096), (0x30A1, 0x30FA),
                              (0xFF71, 0xFF9E))
        for c in map(chr, range(lo, hi + 1)))
    CHINESE = "你好世界再见朋友今天天气很好清晨早安谢谢"
    CTRLS = ["\\C[10]", "\\C[27]", "\\C[31]", "\\N[1]", "\\N[3]",
             "\\P[1,2]", "\\P[3,1]", "\\V[5]"]
    TEXT = ([chr(c) for c in range(0x3041, 0x3097)]
            + [chr(c) for c in range(0x30A1, 0x30FB)]
            + list("日本語花火山川田犬猫友達先生学校天気今日明日"))
    PUNCT = list("、。！？…・")

    @classmethod
    def _zh(cls, c):
        """Deterministic Chinese stand-in for one char: kana maps into the
        Chinese pool, everything else (kanji/ctrl/newline/backslash) is
        preserved verbatim."""
        if ord(c) in cls.KANA:
            return cls.CHINESE[ord(c) % len(cls.CHINESE)]
        return c

    @classmethod
    def _random_key(cls):
        """Random Japanese dialogue-ish key: optional control codes, mixed
        kana/kanji text, optional embedded newline (multi-window-line).

        Uses the module-level random stream - each caller seeds it first
        (random.seed), so the runs stay deterministic while the source shows
        random.choice / random.randrange directly."""
        parts = [random.choice(cls.CTRLS)
                 for _ in range(random.randrange(0, 3))]
        text = "".join(random.choice(cls.TEXT + cls.PUNCT)
                       for _ in range(random.randrange(1, 12)))
        parts.append(text)
        if random.random() < 0.35:
            parts.append("\n" + "".join(random.choice(cls.TEXT)
                                        for _ in range(random.randrange(1, 8))))
        return "".join(parts)

    def test_random_good_pairs_pass(self):
        """A kana-free, structure-preserving value must always pass QC."""
        random.seed(20260840)
        for _ in range(30):
            keys = [self._random_key()
                    for _ in range(random.randrange(1, 15))]
            vals = ["".join(self._zh(c) for c in k) for k in keys]
            issues, ok = mpc.qc_pair(keys, vals, 1)
            assert ok, (keys, vals, issues)
            assert issues == []

    def test_random_violations_detected(self):
        """Each injected violation must be caught by its own rule name."""
        random.seed(20260841)
        builders = {
            "kana": lambda: (
                "こんにちは",
                "".join(self._zh(c) for c in "こんにちは") + "あ"),
            "newline": lambda: ("こんにちは\nまた会おう", "你好"),
            "control-code": lambda: ("\\C[27]こんにちは", "你好"),
            "empty": lambda: ("こんにちは", ""),
            "uncertainty": lambda: ("こんにちは", "【?】你好"),
            "double-backslash": lambda: ("こんにちは", "你好\\X"),
        }
        for _ in range(40):
            kind, builder = random.choice(list(builders.items()))
            key, val = builder()
            issues, ok = mpc.qc_pair([key], [val], 1)
            assert not ok, (kind, key, val)
            assert any(kind in i for i in issues), (kind, key, val, issues)

    def test_random_line_count_mismatch(self):
        random.seed(20260842)
        for _ in range(20):
            n = random.randrange(2, 12)
            keys = [self._random_key() for _ in range(n)]
            vals = keys[:-1]  # one line dropped -> line-count issue
            issues, ok = mpc.qc_pair(keys, vals, 1)
            assert not ok
            assert any("line count" in i for i in issues)

    def test_random_edge_values_kept(self):
        """Edge values QC intends to keep must always pass: a standalone
        kana teaching-UI line, an honorific suffix, a fully-Chinese line and
        a kana middle dot."""
        random.seed(20260843)
        pool = ("あ", "カタカナ", "小美ちゃん", "已经翻译了", "A・B")
        for _ in range(10):
            val = random.choice(pool)
            issues, ok = mpc.qc_pair(["key"], [val], 1)
            assert ok, (val, issues)
            assert issues == []
