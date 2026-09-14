#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tools/clean_kana_ticks.py - the final tick/mouth-sound cleanup.

Rule tables are only applied to text that mixes kana with something else; a
line that is pure kana (standalone onomatopoeia / author name, e.g. "んっ") is
deliberately kept, because rewriting it would destroy the sound the author
wrote.  `\\RB[]` ruby codes, `<tags>` and Wolf `:name[..]` codes are split out
and preserved verbatim.  Both behaviours are pinned below.

Test data uses "A" as a neutral non-kana prefix: a value like "Aッ" is not a
pure-kana line, so the rule tables apply, which is what most cases exercise.
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import clean_kana_ticks as ckt  # noqa: E402


@pytest.fixture
def no_author_names(monkeypatch):
    """Isolate the module-global author/name set main() fills from --exempt."""
    monkeypatch.setattr(ckt, "AUTHOR_NAMES", set())
    return ckt.AUTHOR_NAMES


class TestIsAuthorish:
    def test_plain_kana_value_is_authorish(self):
        assert ckt.is_authorish("k", "はぁ") is True

    def test_kana_with_kanji_is_not_authorish(self):
        assert ckt.is_authorish("k", "まだ日本語") is False

    def test_chinese_value_is_not_authorish(self):
        assert ckt.is_authorish("k", "你好") is False

    def test_kana_with_latin_is_not_authorish(self):
        assert ckt.is_authorish("k", "Aはぁ") is False

    def test_boundary_length_is_authorish(self):
        assert ckt.is_authorish("k", "あ" * 40) is True

    def test_over_boundary_length_is_not_authorish(self):
        assert ckt.is_authorish("k", "あ" * 41) is False

    def test_exact_exempt_name(self, monkeypatch):
        monkeypatch.setattr(ckt, "AUTHOR_NAMES", {"作家名ッ"})
        assert ckt.is_authorish("k", "作家名ッ") is True

    def test_exempt_name_does_not_leak_to_longer_values(self, monkeypatch):
        """Exemption is an exact value match, not a prefix/substring rule."""
        monkeypatch.setattr(ckt, "AUTHOR_NAMES", {"作家名ッ"})
        assert ckt.is_authorish("k", "作家名ッです") is False

    def test_no_names_are_hardcoded(self):
        """Game-specific names must arrive via --exempt, never from source."""
        assert ckt.AUTHOR_NAMES == set()

    def test_empty_value_is_not_authorish(self):
        assert ckt.is_authorish("k", "") is False


class TestPureKanaLinesAreKept:
    @pytest.mark.parametrize("text", ["あッ", "あっ", "あん", "あぁ", "んっ",
                                      "はぁぁ", "んッ"])
    def test_short_pure_kana_line_is_untouched(self, text):
        assert ckt.clean_plain(text) == text

    def test_pure_kana_line_inside_a_longer_segment_is_kept(self):
        assert ckt.clean_plain("Aッ\nんっ") == "A!\nんっ"


class TestCleanPlainRules:
    def test_tail_rule_single_small_tsu(self):
        assert ckt.clean_plain("Aッ") == "A!"

    def test_tail_rule_double_small_tsu(self):
        assert ckt.clean_plain("Aッッ") == "A!!"

    def test_tail_rule_long_run(self):
        assert ckt.clean_plain("Aッッッ") == "A!!!"

    def test_tail_rule_hiragana_tsu_is_dropped(self):
        assert ckt.clean_plain("Aっ") == "A"

    def test_mid_rule_applies_when_not_at_the_tail(self):
        assert ckt.clean_plain("Aだっだ") == "Aだだ"

    def test_mid_rule_before_punctuation(self):
        assert ckt.clean_plain("Aッ。") == "A!。"

    @pytest.mark.parametrize("text,expected", [
        ("Aぁ", "A啊"), ("Aぁぁ", "A啊——"), ("Aぁぁぁ", "A啊——"),
        ("Aぉ", "A哦"), ("Aぅ", "A呜"), ("Aぃ", "A咿"), ("Aぇ", "A诶"),
        ("Aん", "A嗯"), ("Aんん", "A嗯嗯"),
    ])
    def test_hiragana_tail_rules(self, text, expected):
        assert ckt.clean_plain(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("Aォ", "A哦"), ("Aィ", "A咿"), ("Aゥ", "A呜"),
        ("Aャ", "A呀"), ("Aュ", "A哟"), ("Aョ", "A哟"), ("Aヮ", "A哇"),
        ("Aン", "A嗯"), ("Aンン", "A嗯嗯"),
    ])
    def test_katakana_tail_rules(self, text, expected):
        assert ckt.clean_plain(text) == expected

    def test_voiced_marks_are_stripped(self):
        assert ckt.clean_plain("A゛B゜") == "AB"

    def test_mixed_line_gets_rules_applied(self):
        assert ckt.clean_plain("中文あッ") == "中文あ!"

    def test_segment_without_ticks_is_unchanged(self):
        assert ckt.clean_plain("A plain line.") == "A plain line."

    def test_empty_segment(self):
        assert ckt.clean_plain("") == ""


class TestCleanValue:
    def test_rb_ruby_code_is_preserved_verbatim(self):
        v = "\\RB[まだ,ま]"
        assert ckt.clean_value("k", v) == v

    def test_text_outside_rb_is_cleaned(self):
        """Ruby args are kana on purpose (readings); the code is not touched."""
        v = "Aッ\\RB[まだ,ま]"
        assert ckt.clean_value("k", v) == "A!\\RB[まだ,ま]"

    def test_tag_is_preserved(self):
        assert ckt.clean_value("k", "<まだ>Aッ") == "<まだ>A!"

    def test_wolf_name_code_is_preserved(self):
        assert ckt.clean_value("k", ":name[勇士]Aッ") == ":name[勇士]A!"

    def test_several_codes_split_the_value(self):
        v = "Aッ\\RB[だ,だ]Bッ<た>Cッ"
        assert ckt.clean_value("k", v) == "A!\\RB[だ,だ]B!<た>C!"

    def test_authorish_value_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(ckt, "AUTHOR_NAMES", {"作家名ッ"})
        assert ckt.clean_value("k", "作家名ッ") == "作家名ッ"

    def test_pure_kana_value_is_left_alone(self):
        assert ckt.clean_value("k", "あッ") == "あッ"

    def test_rb_content_keeps_its_kana(self):
        out = ckt.clean_value("k", "Aッ\\RB[あっ,あっ]")
        assert out == "A!\\RB[あっ,あっ]"


class TestCli:
    def test_rewrites_values_and_reports_counts(self, tmp_path, monkeypatch,
                                                capsys, no_author_names):
        path = tmp_path / "merged.json"
        path.write_text(json.dumps({"k1": "Aッ", "k2": "你好"},
                                   ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["clean_kana_ticks.py", str(path)])
        ckt.main()
        out = capsys.readouterr().out
        assert "cleaned values: 1" in out
        assert "kana outside exempt classes: 0" in out
        assert json.loads(path.read_text(encoding="utf-8")) == \
            {"k1": "A!", "k2": "你好"}

    def test_untouched_file_reports_zero_changes(self, tmp_path, monkeypatch,
                                                 capsys, no_author_names):
        path = tmp_path / "merged.json"
        path.write_text(json.dumps({"k": "你好"}, ensure_ascii=False),
                        encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["clean_kana_ticks.py", str(path)])
        ckt.main()
        assert "cleaned values: 0" in capsys.readouterr().out

    def test_residual_kana_is_listed_with_key_and_value(self, tmp_path,
                                                       monkeypatch, capsys,
                                                       no_author_names):
        path = tmp_path / "merged.json"
        path.write_text(json.dumps({"k": "まだです"}, ensure_ascii=False),
                        encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["clean_kana_ticks.py", str(path)])
        ckt.main()
        out = capsys.readouterr().out
        assert "kana outside exempt classes: 1" in out
        assert "K: 'k'" in out
        assert "V:" in out

    def test_rb_ruby_kana_is_not_counted_as_residual(self, tmp_path,
                                                     monkeypatch, capsys,
                                                     no_author_names):
        path = tmp_path / "merged.json"
        path.write_text(json.dumps({"k": "\\RB[まだ,ま]"}, ensure_ascii=False),
                        encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["clean_kana_ticks.py", str(path)])
        ckt.main()
        assert "kana outside exempt classes: 0" in capsys.readouterr().out

    def test_exempt_file_values_are_not_cleaned(self, tmp_path, monkeypatch,
                                               capsys, no_author_names):
        path = tmp_path / "merged.json"
        path.write_text(json.dumps({"k": "作家名ッ"}, ensure_ascii=False),
                        encoding="utf-8")
        exempt = tmp_path / "exempt.txt"
        exempt.write_text("作家名ッ\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv",
                            ["clean_kana_ticks.py", str(path),
                             "--exempt", str(exempt)])
        ckt.main()
        assert "cleaned values: 0" in capsys.readouterr().out
        assert json.loads(path.read_text(encoding="utf-8")) == {"k": "作家名ッ"}

    def test_output_is_written_with_stable_formatting(self, tmp_path,
                                                      monkeypatch,
                                                      no_author_names):
        path = tmp_path / "merged.json"
        path.write_text(json.dumps({"k": "Aッ"}, ensure_ascii=False),
                        encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["clean_kana_ticks.py", str(path)])
        ckt.main()
        raw = path.read_text(encoding="utf-8")
        assert "A!" in raw                     # not \uXXXX escaped
        assert '\\n "k"' in raw or '"k"' in raw  # indent=1 layout
        assert not raw.endswith("\n")
