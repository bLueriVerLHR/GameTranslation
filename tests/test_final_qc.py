#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tools/final_qc.py - QC of the MERGED translation dictionary.

Two levels: the pure `collect()` (finding lists, keyed by report name) and the
CLI path (argv -> stdout report), so the human-facing report cannot drift from
the findings it is supposed to show.
"""
import json
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import final_qc  # noqa: E402


def findings(p, exemptions=()):
    return final_qc.collect(p, exemptions)


def run_cli(tmp_path, monkeypatch, data, extra_argv=()):
    path = tmp_path / "merged.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["final_qc.py", str(path)] + list(extra_argv))
    final_qc.main()


class TestCollect:
    def test_clean_dictionary_reports_nothing(self):
        got = findings({"こんにちは": "你好", "\\N[1]だ": "\\N[1]啊"})
        assert all(v == [] for v in got.values())

    def test_empty_value_is_reported_by_key(self):
        got = findings({"a": "", "b": "   "})
        assert got["empty"] == ["a", "b"]

    def test_kana_residual_reports_key_and_value(self):
        got = findings({"key": "まだ日本語"})
        assert got["kana"] == [("key", "まだ日本語")]

    def test_chinese_text_is_not_a_kana_residual(self):
        assert findings({"k": "这是中文"})["kana"] == []

    def test_exemption_silences_only_matching_values(self):
        ex = [re.compile(r"^はぁ+$")]
        got = findings({"k1": "はぁ", "k2": "まだ"}, ex)
        assert [k for k, _v in got["kana"]] == ["k2"]

    def test_line_count_mismatch(self):
        got = findings({"one\ntwo": "一"})
        assert got["lines"] == [("one\ntwo", "一")]

    def test_line_count_match_is_clean(self):
        assert findings({"one\ntwo": "一\n二"})["lines"] == []

    def test_double_backslash_value(self):
        got = findings({"k": "a\\\\b"})
        assert got["dbl"] == [("k", "a\\\\b")]

    def test_uncertainty_marker(self):
        got = findings({"k": "【这是?】"})
        assert got["mark"] == [("k", "【这是?】")]

    def test_identity_value_needs_more_than_two_chars(self):
        got = findings({"ab": "ab", "abc": "abc"})
        assert got["ident"] == [("abc", "abc")]

    def test_control_code_diff_is_reported(self):
        got = findings({"\\C[1]だ": "啊"})
        assert got["code"] == [("\\C[1]だ", "啊")]

    def test_translated_ruby_args_are_not_a_control_code_diff(self):
        """`\\RB[役名,表示]` -> `\\RB[显示,名]`: arg content changes, structure
        does not - the classic false positive this check must not produce."""
        got = findings({"\\RB[役名,表示]です": "\\RB[显示,名]啊"})
        assert got["code"] == []

    def test_non_string_values_are_skipped(self):
        got = findings({"k1": None, "k2": 5, "k3": ["x"]})
        assert all(v == [] for v in got.values())

    def test_reordered_control_codes_are_not_flagged(self):
        """Deliberately order-insensitive: `sorted()` on both the tokens and
        the signature means moving a code to the other side of the line (a
        legitimate translation reorder) is not reported.  Pinned because a
        future 'stricter' change here would light up every such pair."""
        assert findings({"\\C[1]\\N[2]": "\\N[2]\\C[1]"})["code"] == []

    def test_dropped_control_code_is_flagged(self):
        got = findings({"\\C[1]\\N[2]": "\\N[2]"})
        assert got["code"] == [("\\C[1]\\N[2]", "\\N[2]")]

    def test_finding_order_follows_the_dictionary(self):
        got = findings({"k1": "まだ", "k2": "まだ", "k3": "中文"})
        assert [k for k, _v in got["kana"]] == ["k1", "k2"]

    def test_empty_dictionary(self):
        assert all(v == [] for v in findings({}).values())


class TestCli:
    def test_report_lists_every_section_in_order(self, tmp_path, monkeypatch,
                                                capsys):
        run_cli(tmp_path, monkeypatch, {"こんにちは": "你好"})
        out = capsys.readouterr().out
        labels = [label for label, _key in final_qc.REPORTS]
        positions = [out.index(label) for label in labels]
        assert positions == sorted(positions)
        assert "empty values: 0" in out
        assert "kana residual: 0" in out

    def test_counts_and_samples_are_printed(self, tmp_path, monkeypatch,
                                            capsys):
        run_cli(tmp_path, monkeypatch, {"k": "まだ"})
        out = capsys.readouterr().out
        assert "kana residual: 1" in out
        assert "'k'" in out

    def test_exempt_file_excludes_commented_and_blank_lines(self, tmp_path,
                                                            monkeypatch,
                                                            capsys):
        exempt = tmp_path / "exempt.txt"
        exempt.write_text("# comment\n\n^はぁ+$\n", encoding="utf-8")
        run_cli(tmp_path, monkeypatch, {"k": "はぁ"}, ("--exempt", str(exempt)))
        assert "kana residual: 0" in capsys.readouterr().out

    def test_exempt_file_still_reports_other_kana(self, tmp_path, monkeypatch,
                                                  capsys):
        exempt = tmp_path / "exempt.txt"
        exempt.write_text("^はぁ+$\n", encoding="utf-8")
        run_cli(tmp_path, monkeypatch, {"k": "まだ"}, ("--exempt", str(exempt)))
        assert "kana residual: 1" in capsys.readouterr().out

    def test_dash_exempt_does_not_read_stdin(self, tmp_path, monkeypatch,
                                            capsys):
        """`--exempt -` means "no exemption file": reading stdin would hang a
        pipeline, so the guard in main() must skip it."""
        run_cli(tmp_path, monkeypatch, {"k": "はぁ"}, ("--exempt", "-"))
        assert "kana residual: 1" in capsys.readouterr().out

    def test_missing_file_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["final_qc.py", str(tmp_path / "nope.json")])
        with pytest.raises(OSError):
            final_qc.main()
