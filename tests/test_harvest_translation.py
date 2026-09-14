#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/harvest_translation.py - harvesting a runtime
MTool/AI translation dict into an extracted template (build_translation.py)
so the values can be baked statically.

Contract under test (module docstring + docs/translation.md):
- matching is by SOURCE text: the dict is keyed on the displayed Japanese
  string (control codes stripped, speaker-name first line dropped, note text
  from "<SG説明"), so a reversed dict (Chinese key -> Japanese value) harvests
  nothing,
- values are copied verbatim once a key matches; the tool itself does not
  filter residual kana or identity entries (bake_translation.py does that),
- keys without a match go to <work_dir>/missing.json, never into the output,
- the harvest order follows the template order (story order), not the dict,
- speaker names survive: a dropped name line is re-attached, translated when
  the name itself has an entry.
"""
import json
import logging
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import harvest_translation as harvest  # noqa: E402


def write_json(path, data, encoding="utf-8"):
    with open(path, "w", encoding=encoding) as f:
        json.dump(data, f, ensure_ascii=False)


def read_json(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return json.load(f)


def make_work(tmp_path, template, kinds):
    """Minimal work dir: only template.json + kinds.json are read from it."""
    work = tmp_path / "work"
    work.mkdir()
    write_json(work / "template.json", template)
    write_json(work / "kinds.json", kinds)
    return work


def make_dict(tmp_path, d, name="mtool_dict.json"):
    path = tmp_path / name
    write_json(path, d)
    return path


def run_harvest(monkeypatch, work, dict_path, *extra):
    argv = ["harvest_translation.py", str(work), str(dict_path)]
    argv += [str(x) for x in extra]
    monkeypatch.setattr("sys.argv", argv)
    harvest.main()


class TestStripCodes:
    def test_strips_single_letter_code_with_args(self):
        assert harvest.strip_codes("\\N[1]こんにちは") == "こんにちは"

    def test_strips_code_without_args(self):
        assert harvest.strip_codes("\\EXITあと") == "あと"

    def test_strips_multi_letter_codes_completely(self):
        # the block-prefix class must not leave a residue behind
        assert harvest.strip_codes("\\FX[F]\\FFFFF[1000Sample_0004]") == ""

    def test_trims_surrounding_whitespace(self):
        assert harvest.strip_codes("  まだ  ") == "まだ"
        assert harvest.strip_codes("") == ""

    def test_keeps_plain_text(self):
        assert harvest.strip_codes("こんにちは") == "こんにちは"


class TestLeadingTrailingCodes:
    def test_leading_codes_returns_the_run(self):
        assert harvest.leading_codes("\\C[3]\\N[1]あ") == "\\C[3]\\N[1]"

    def test_leading_codes_empty_when_text_comes_first(self):
        assert harvest.leading_codes("あ\\C[3]") == ""

    def test_argument_less_code_is_not_a_leading_run(self):
        # the helper only matches the \\Name[args] form; \\EXIT has no args
        assert harvest.leading_codes("\\EXITあ") == ""

    def test_trailing_codes_returns_the_run(self):
        assert harvest.trailing_codes("あ\\C[3]\\N[1]") == "\\C[3]\\N[1]"

    def test_trailing_codes_empty_when_text_comes_last(self):
        assert harvest.trailing_codes("\\C[3]あ") == ""

    def test_codes_only_string_is_both(self):
        assert harvest.leading_codes("\\C[3]") == "\\C[3]"
        assert harvest.trailing_codes("\\C[3]") == "\\C[3]"


class TestIsNameLine:
    def test_pure_kanji_name(self):
        assert harvest.is_name_line("勇者") is True

    def test_pure_kana_name(self):
        assert harvest.is_name_line("アリス") is True

    def test_honorific_suffix_is_still_a_name(self):
        assert harvest.is_name_line("勇者さん") is True

    def test_control_codes_are_stripped_before_the_check(self):
        assert harvest.is_name_line("\\C[3]勇者") is True

    def test_corner_brackets_mark_dialogue(self):
        assert harvest.is_name_line("「こんにちは」") is False

    def test_punctuated_dialogue_is_not_a_name(self):
        assert harvest.is_name_line("こんにちは、元気ですか") is False

    def test_long_kana_line_is_not_a_name(self):
        assert harvest.is_name_line("あ" * 15) is False

    def test_ascii_line_is_not_a_name(self):
        assert harvest.is_name_line("Hero") is False

    def test_code_only_line_is_not_a_name(self):
        assert harvest.is_name_line("\\N[1]") is False

    def test_empty_line_is_not_a_name(self):
        assert harvest.is_name_line("") is False


class TestSplitBlock:
    def test_single_line_is_all_body(self):
        assert harvest.split_block("こんにちは") == (None, ["こんにちは"])

    def test_name_first_line_is_split_off(self):
        assert harvest.split_block("勇者\nこんにちは") == ("勇者", ["こんにちは"])

    def test_dialogue_first_line_stays_in_the_body(self):
        name, body = harvest.split_block("「こんにちは」\nさようなら")
        assert name is None
        assert body == ["「こんにちは」", "さようなら"]

    def test_body_keeps_every_line(self):
        name, body = harvest.split_block("勇者\na\nb\nc")
        assert name == "勇者"
        assert body == ["a", "b", "c"]


class TestMainExactMatch:
    def test_exact_key_is_harvested(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, {"こんにちは": {"where": "Map001"}},
                         {"こんにちは": "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {"こんにちは": "你好"}
        assert read_json(work / "missing.json") == {}

    def test_harvest_order_follows_the_template(self, tmp_path, monkeypatch):
        template = {"さようなら": {}, "こんにちは": {}, "おはよう": {}}
        kinds = {k: "block-line" for k in template}
        d = make_dict(tmp_path, {"おはよう": "早安", "こんにちは": "你好",
                                 "さようなら": "再见"})
        work = make_work(tmp_path, template, kinds)
        run_harvest(monkeypatch, work, d)
        assert list(read_json(work / "translated.json")) == \
            ["さようなら", "こんにちは", "おはよう"]

    def test_template_may_carry_a_bom(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, {"こんにちは": {}},
                         {"こんにちは": "block-line"})
        write_json(work / "template.json", {"こんにちは": {}},
                   encoding="utf-8-sig")
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {"こんにちは": "你好"}


class TestMainStripMatch:
    def test_leading_and_trailing_codes_are_reattached(self, tmp_path,
                                                       monkeypatch):
        key = "\\C[3]こんにちは\\C[0]"
        work = make_work(tmp_path, {key: {}}, {key: "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {
            key: "\\C[3]你好\\C[0]"}

    def test_multiline_key_does_not_get_codes_reattached(self, tmp_path,
                                                         monkeypatch):
        key = "\\C[3]「おはよう」\nさようなら"
        work = make_work(tmp_path, {key: {}}, {key: "block"})
        d = make_dict(tmp_path, {"「おはよう」\nさようなら": "「早」\n再见"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {
            key: "「早」\n再见"}


class TestMainBlockPaths:
    def test_dropped_name_line_is_reattached_translated(self, tmp_path,
                                                        monkeypatch):
        # the body is only present as a whole block, so this must go through
        # the drop-name path (the fragment path needs per-line entries)
        key = "勇者\nこんにちは\nさようなら"
        work = make_work(tmp_path, {key: {}}, {key: "block"})
        d = make_dict(tmp_path, {"勇者": "勇士",
                                 "こんにちは\nさようなら": "你好\n再见"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {
            key: "勇士\n你好\n再见"}

    def test_whole_body_block_wins_over_fragments(self, tmp_path, monkeypatch):
        # both routes are available: the joined body block is preferred
        key = "勇者\nこんにちは\nさようなら"
        work = make_work(tmp_path, {key: {}}, {key: "block"})
        d = make_dict(tmp_path, {"こんにちは\nさようなら": "你好\n再见",
                                 "こんにちは": "逐行一",
                                 "さようなら": "逐行二"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {
            key: "勇者\n你好\n再见"}

    def test_unknown_name_line_is_left_as_is(self, tmp_path, monkeypatch):
        key = "勇者\nこんにちは"
        work = make_work(tmp_path, {key: {}}, {key: "block"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {key: "勇者\n你好"}

    def test_body_lines_are_joined_from_fragments(self, tmp_path, monkeypatch):
        key = "勇者\nこんにちは\nさようなら"
        work = make_work(tmp_path, {key: {}}, {key: "block"})
        d = make_dict(tmp_path, {"こんにちは": "你好", "さようなら": "再见"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {
            key: "勇者\n你好\n再见"}

    def test_partially_covered_block_is_missing(self, tmp_path, monkeypatch):
        # only one of two body lines is in the dict: no half-translated block
        key = "勇者\nこんにちは\nさようなら"
        work = make_work(tmp_path, {key: {}}, {key: "block"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {key: ""}

    def test_dialogue_first_line_is_not_dropped_as_a_name(self, tmp_path,
                                                          monkeypatch):
        key = "「こんにちは」\nさようなら"
        work = make_work(tmp_path, {key: {}}, {key: "block"})
        d = make_dict(tmp_path, {"「こんにちは」\nさようなら": "「你好」\n再见"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {
            key: "「你好」\n再见"}


class TestMainKindSpecificPaths:
    def test_quoted_event_text_keeps_inner_control_codes(self, tmp_path,
                                                         monkeypatch):
        """The lookup matches stripped text, but the value must keep the
        style switch that lives inside the quotes - dropping it shipped a
        code-less string (and lit up as a control-code diff in QC)."""
        key = '"\\C[3]こんにちは"'
        work = make_work(tmp_path, {key: {}}, {key: "event-text"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {key: '"\\C[3]你好"'}

    def test_quoted_event_text_without_codes(self, tmp_path, monkeypatch):
        key = '"こんにちは"'
        work = make_work(tmp_path, {key: {}}, {key: "event-text"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {key: '"你好"'}

    def test_quotes_are_not_added_to_other_kinds(self, tmp_path, monkeypatch):
        key = '"こんにちは"'
        work = make_work(tmp_path, {key: {}}, {key: "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}

    def test_note_leading_codes_are_not_duplicated(self, tmp_path,
                                                   monkeypatch):
        """The prefix before the <SG説明 tag is copied into the value; the
        old code prepended its leading codes again (\\C[3]\\C[3]...)."""
        key = "\\C[3]<SG説明:あれ>"
        work = make_work(tmp_path, {key: {}}, {key: "note"})
        d = make_dict(tmp_path, {"<SG説明:あれ>": "那是"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {key: "\\C[3]那是"}

    def test_note_matches_from_the_sg_tag_onward(self, tmp_path, monkeypatch):
        key = "前置き<SG説明:あれ>"
        work = make_work(tmp_path, {key: {}}, {key: "note"})
        # the dict entry itself carries a style switch: the note lookup must
        # compare code-stripped text on both sides
        d = make_dict(tmp_path, {"\\C[3]<SG説明:あれ>": "那是"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {key: "前置き那是"}

    def test_note_without_an_sg_tag_is_missing(self, tmp_path, monkeypatch):
        key = "前置き:あれ"
        work = make_work(tmp_path, {key: {}}, {key: "note"})
        d = make_dict(tmp_path, {"あれ": "那是"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {key: ""}


class TestMissingAndEmptyInputs:
    def test_empty_dict_makes_every_key_missing(self, tmp_path, monkeypatch):
        template = {"こんにちは": {}, "さようなら": {}}
        work = make_work(tmp_path, template,
                         {k: "block-line" for k in template})
        d = make_dict(tmp_path, {})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {"こんにちは": "",
                                                    "さようなら": ""}

    def test_empty_template_writes_empty_outputs(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, {}, {})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {}

    def test_missing_json_is_written_next_to_the_template(self, tmp_path,
                                                          monkeypatch):
        work = make_work(tmp_path, {"未知": {}}, {"未知": "block-line"})
        d = make_dict(tmp_path, {})
        run_harvest(monkeypatch, work, d)
        assert (work / "missing.json").is_file()
        assert (work / "translated.json").is_file()

    def test_out_option_chooses_the_output_name(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, {"こんにちは": {}},
                         {"こんにちは": "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d, "--out", "harvested.json")
        assert read_json(work / "harvested.json") == {"こんにちは": "你好"}
        assert not (work / "translated.json").exists()

    def test_verbose_flag_still_harvests(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, {"こんにちは": {}},
                         {"こんにちは": "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d, "-v")
        assert read_json(work / "translated.json") == {"こんにちは": "你好"}

    def test_summary_is_logged(self, tmp_path, monkeypatch, caplog):
        template = {"こんにちは": {}, "未知": {}}
        work = make_work(tmp_path, template,
                         {k: "block-line" for k in template})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        with caplog.at_level(logging.INFO):
            run_harvest(monkeypatch, work, d)
        assert "harvested 1 / 2 keys" in caplog.text


class TestValueSideSafety:
    """The dict is keyed on the SOURCE text, so only source-keyed entries can
    be harvested - a reversed dict never turns a Chinese string into a
    translation.  Values themselves are copied verbatim; residual kana and
    identity entries are removed later by the bake step, not here."""

    def test_reversed_dict_harvests_nothing(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, {"こんにちは": {}},
                         {"こんにちは": "block-line"})
        d = make_dict(tmp_path, {"你好": "こんにちは"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {"こんにちは": ""}

    def test_chinese_value_is_harvested_as_the_translation(self, tmp_path,
                                                           monkeypatch):
        work = make_work(tmp_path, {"こんにちは": {}},
                         {"こんにちは": "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json")["こんにちは"] == "你好"

    def test_identity_value_is_harvested_verbatim(self, tmp_path, monkeypatch):
        # an untranslated (identity) entry is copied here and dropped by the
        # bake step's identity filter - this pins that division of labour
        work = make_work(tmp_path, {"こんにちは": {}},
                         {"こんにちは": "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "こんにちは"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {
            "こんにちは": "こんにちは"}

    def test_non_string_values_are_not_harvested(self, tmp_path, monkeypatch):
        work = make_work(tmp_path, {"こんにちは": {}, "さようなら": {}},
                         {"こんにちは": "block-line",
                          "さようなら": "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "", "さようなら": 5})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {"こんにちは": "",
                                                    "さようなら": ""}


class TestCodeOnlyKeys:
    def test_code_only_key_without_an_entry_is_missing(self, tmp_path,
                                                       monkeypatch):
        key = "\\C[3]"
        work = make_work(tmp_path, {key: {}}, {key: "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {key: ""}

    def test_code_only_dict_entry_is_not_a_strip_source(self, tmp_path,
                                                        monkeypatch):
        """A dict entry whose key strips to "" must not become the source for
        a code-only template key: that borrowed the value of an unrelated
        entry and wrapped it in the switch.  Such a note key now stays
        missing."""
        key = "\\C[3]"
        work = make_work(tmp_path, {key: {}}, {key: "block-line"})
        d = make_dict(tmp_path, {"\\N[1]": "x"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}
        assert read_json(work / "missing.json") == {key: ""}

    def test_code_only_key_is_not_matched_by_empty_key_entries(self, tmp_path,
                                                               monkeypatch):
        """Same path, explicit empty dict key: still not a match source."""
        key = "\\C[3]"
        work = make_work(tmp_path, {key: {}}, {key: "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好", "": "empty"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {}

    def test_code_bearing_value_is_not_wrapped_again(self, tmp_path,
                                                     monkeypatch):
        """A dict value that already carries its style switch must be copied
        verbatim, not wrapped in a second pair of codes."""
        key = "\\C[3]こんにちは"
        work = make_work(tmp_path, {key: {}}, {key: "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "\\C[3]你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {key: "\\C[3]你好"}

    def test_code_free_value_still_gets_the_key_codes(self, tmp_path,
                                                      monkeypatch):
        key = "\\C[3]こんにちは\\C[0]"
        work = make_work(tmp_path, {key: {}}, {key: "block-line"})
        d = make_dict(tmp_path, {"こんにちは": "你好"})
        run_harvest(monkeypatch, work, d)
        assert read_json(work / "translated.json") == {key: "\\C[3]你好\\C[0]"}
