#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/fix_mojibake_names.py (CP936-misread Shift-JIS names).

The fixtures are real strings produced by the failing repack path (Shift-JIS
bytes decoded as CP936), paired with the original Japanese names they stand
for - `H岠壥壒2` really is what `H効果音2` looks like after that round trip,
so the assertions document the actual artifact instead of a made-up one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import fix_mojibake_names as fm

# (on-disk mojibake, original name)
KNOWN = [
    ("H岠壥壒2", "H効果音2"),
    ("H岠壥壒0", "H効果音0"),
    ("歜偓惡BGS", "喘ぎ声BGS"),
    ("歜偓惡SE", "喘ぎ声SE"),
    ("僺僗僩儞僞僀僾A乮擏偺傇偮偐傞壒擖傝乯乮備偭偔傝乯.ogg_",
     "ピストンタイプA（肉のぶつかる音入り）（ゆっくり）.ogg_"),
    ("庤僐僉(懥塼)俀.ogg_", "手コキ(唾液)２.ogg_"),
    ("MV梡xBCDE1.png_", "MV用xBCDE1.png_"),
]

#: A genuine Chinese name (repack promo file) - must never be "repaired".
CHINESE = "好用便宜的梯子.txt"


class TestFixName:
    @pytest.mark.parametrize("broken,fixed", KNOWN)
    def test_round_trip(self, broken, fixed):
        assert fm.fix_name(broken) == fixed

    def test_ascii_untouched(self):
        assert fm.fix_name("index.html") is None
        assert fm.fix_name("World_A1.png_") is None

    def test_already_correct_japanese_untouched(self):
        """A name whose CP936 bytes decode back to itself is not a repair."""
        assert fm.fix_name("MV用xBCDE1.png_") is None

    def test_genuine_japanese_untouched(self):
        """Hiragana/full-width katakana are not CP936-encodable, so a real
        Japanese name can never be rewritten."""
        assert fm.fix_name("喘ぎ声BGS") is None
        assert fm.fix_name("H効果音2") is None
        assert fm.fix_name("ピストンタイプ.ogg") is None

    def test_genuine_chinese_untouched(self):
        """CP936 text read as CP932 yields half-width katakana - that is the
        other direction, and it must not be renamed."""
        assert fm.fix_name(CHINESE) is None
        assert fm.fix_name("玩前必看说明.txt") is None

    def test_helpers(self):
        assert fm.has_halfwidth_kana("ｺﾃﾓ")
        assert not fm.has_halfwidth_kana("ピストン")
        assert fm.has_japanese("H効果音2")
        assert fm.has_japanese("ピストン")
        assert not fm.has_japanese("BCDE1")


class TestCandidates:
    def test_walks_nested_and_deepest_first(self, tmp_path):
        root = tmp_path / "game"
        (root / "audio" / "bgs" / "H岠壥壒2").mkdir(parents=True)
        (root / "audio" / "bgs" / "H岠壥壒2" / "晛捠偵僼僃儔1.ogg_").write_bytes(b"x")
        (root / "index.html").write_text("ok", encoding="utf-8")
        found = fm.candidates(str(root))
        rels = [os.path.relpath(p, str(root)) for p, _f in found]
        assert rels == [
            os.path.join("audio", "bgs", "H岠壥壒2", "晛捠偵僼僃儔1.ogg_"),
            os.path.join("audio", "bgs", "H岠壥壒2"),
        ], "the file must be renamed before its parent directory"
        assert [f for _p, f in found] == ["普通にフェラ1.ogg_", "H効果音2"]

    def test_chinese_promo_file_is_not_a_candidate(self, tmp_path):
        (tmp_path / CHINESE).write_text("ad", encoding="utf-8")
        assert fm.candidates(str(tmp_path)) == []


class TestApplyRenames:
    def test_dry_run_writes_nothing(self, tmp_path):
        (tmp_path / "H岠壥壒2").mkdir()
        summary = fm.apply_renames(str(tmp_path), fm.candidates(str(tmp_path)),
                                   dry_run=True)
        assert [f for _p, f in summary["renamed"]] == ["H効果音2"]
        assert (tmp_path / "H岠壥壒2").is_dir()
        assert not (tmp_path / "H効果音2").exists()

    def test_applies_nested_tree(self, tmp_path):
        nested = tmp_path / "audio" / "bgs" / "H岠壥壒2"
        nested.mkdir(parents=True)
        (nested / "幩惛壒.ogg_").write_bytes(b"audio")
        summary = fm.apply_renames(str(tmp_path), fm.candidates(str(tmp_path)),
                                   dry_run=False)
        assert len(summary["renamed"]) == 2
        out = tmp_path / "audio" / "bgs" / "H効果音2" / "射精音.ogg_"
        assert out.read_bytes() == b"audio"
        assert not nested.exists()

    def test_existing_target_is_skipped_not_overwritten(self, tmp_path):
        (tmp_path / "H岠壥壒2").mkdir()
        (tmp_path / "H効果音2").mkdir()
        summary = fm.apply_renames(str(tmp_path), fm.candidates(str(tmp_path)),
                                   dry_run=False)
        assert summary["renamed"] == []
        assert len(summary["skipped"]) == 1
        assert summary["skipped"][0][0] == "H岠壥壒2"
        assert (tmp_path / "H岠壥壒2").is_dir()

    def test_idempotent(self, tmp_path):
        (tmp_path / "H岠壥壒2").mkdir()
        fm.apply_renames(str(tmp_path), fm.candidates(str(tmp_path)),
                         dry_run=False)
        assert fm.candidates(str(tmp_path)) == []


class TestCli:
    def test_reports_and_writes_json(self, tmp_path):
        (tmp_path / "H岠壥壒2").mkdir()
        report = tmp_path / "report.json"
        code = fm.main([str(tmp_path), "--json", str(report)])
        assert code == 0
        import json
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["dry_run"] is True
        assert [f for _p, f in data["renamed"]] == ["H効果音2"]
        assert (tmp_path / "H岠壥壒2").is_dir(), "--apply is required to rename"

    def test_apply_flag(self, tmp_path):
        (tmp_path / "H岠壥壒2").mkdir()
        assert fm.main([str(tmp_path), "--apply"]) == 0
        assert (tmp_path / "H効果音2").is_dir()

    def test_missing_folder_fails(self, tmp_path):
        assert fm.main([str(tmp_path / "nope")]) == 1
