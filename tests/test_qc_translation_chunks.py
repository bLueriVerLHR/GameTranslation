#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/qc_translation_chunks.py - QC, repair and merge for
the legacy JSON-chunk work packages.

Contract under test:
- repair_file() backs off invalid JSON escapes (agents write a raw ``\\C[27]``)
  and leaves an already valid file byte-identical,
- validate() compares a translated chunk against its source chunk: missing /
  extra keys, empty values, ``\\n`` line counts, kana residue, control-code
  tokens, double backslashes and the uncertainty marker (U+3010 ? U+3011)
  while deliberately NOT flagging a translated ``\\RB[a,b]`` argument, because only
  the code structure matters there,
- patch_altered_keys() repairs keys the agent mangled (escaped or dropped
  backslash, small edit distance) and reports how many it patched,
- main() walks ``chunks/*.translated.json``, repairs offenders on disk, merges
  the entries whose key exists in the source chunk and prints one report line
  per chunk.
"""
import json

import qc_translation_chunks as qc

KEY = "\u3053\u3093\u306b\u3061\u306f"            # hiragana key
KEY_CODE = "\\C[27]" + KEY                        # key carrying a control code
KANA_RESIDUE = "Hello \u307e\u3060"               # value with kana left


def write_text(path, text):
    with open(str(path), "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path, data):
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def read_text(path):
    with open(str(path), encoding="utf-8") as f:
        return f.read()


def run_main(monkeypatch, work, *extra):
    monkeypatch.setattr("sys.argv",
                        ["qc_translation_chunks.py", str(work)] + list(extra))
    qc.main()


def chunks_dir(work):
    path = work / "chunks"
    path.mkdir()
    return path


def merged(work, name="completion.json"):
    return json.loads(read_text(work / name))


class TestRepairFile:
    def test_valid_file_is_returned_unchanged(self, tmp_path):
        path = tmp_path / "chunk_01.translated.json"
        text = '{\n "' + KEY + '": "Hello"\n}'
        write_text(path, text)
        got, fixed = qc.repair_file(str(path))
        assert got == text
        assert fixed == 0

    def test_invalid_escape_is_doubled(self, tmp_path):
        path = tmp_path / "chunk_01.translated.json"
        # On disk the agent wrote a single backslash: invalid JSON escape.
        write_text(path, '{"' + KEY + '": "\\C[27]Hello"}')
        got, fixed = qc.repair_file(str(path))
        assert fixed == 1
        assert json.loads(got) == {KEY: "\\C[27]Hello"}

    def test_each_offending_line_is_counted_once(self, tmp_path):
        path = tmp_path / "chunk_01.translated.json"
        write_text(path, '{\n "a": "\\C[27]x",\n "b": "\\N[1]y"\n}')
        got, fixed = qc.repair_file(str(path))
        assert fixed == 2
        assert json.loads(got) == {"a": "\\C[27]x", "b": "\\N[1]y"}

    def test_valid_escapes_are_not_touched(self, tmp_path):
        path = tmp_path / "chunk_01.translated.json"
        text = '{"a": "line1\\nline2 \\u0041 \\\\ \\/ end"}'
        write_text(path, text)
        got, fixed = qc.repair_file(str(path))
        assert got == text
        assert fixed == 0

    def test_unfixable_file_comes_back_as_is(self, tmp_path):
        """Repair only handles escapes: a structural error stays reported
        (main() then prints REPAIR UNABLE instead of merging garbage)."""
        path = tmp_path / "chunk_01.translated.json"
        text = '{"a": "b"'
        write_text(path, text)
        got, fixed = qc.repair_file(str(path))
        assert got == text
        assert fixed == 0


class TestValidate:
    def test_clean_pair_has_no_issues(self):
        src = {KEY: "Hello", "goodbye": "Bye"}
        assert qc.validate(src, dict(src)) == []

    def test_empty_string_key_is_accepted(self):
        assert qc.validate({"": "Hello"}, {"": "Hello"}) == []

    def test_missing_key_is_reported(self):
        issues = qc.validate({KEY: "Hello", "b": "Bye"}, {KEY: "Hello"})
        assert any("missing keys" in i for i in issues)

    def test_extra_key_is_reported(self):
        issues = qc.validate({KEY: "Hello"}, {KEY: "Hello", "b": "Bye"})
        assert any("extra keys" in i for i in issues)

    def test_empty_value_is_reported(self):
        issues = qc.validate({KEY: "Hello"}, {KEY: ""})
        assert any("empty values" in i for i in issues)

    def test_newline_count_mismatch_is_reported(self):
        key = KEY + "\n\u307e\u305f\u306d"
        issues = qc.validate({key: "Hello\nBye"}, {key: "Hello"})
        assert any("newline-count mismatch" in i for i in issues)

    def test_kana_residue_is_reported(self):
        issues = qc.validate({KEY: "Hello"}, {KEY: KANA_RESIDUE})
        assert any("kana still in values" in i for i in issues)

    def test_kana_only_inside_a_control_code_is_not_residue(self):
        """Control codes are stripped before the kana check, so a ruby
        argument does not count as untranslated text."""
        key = "\\RB[\u8868\u793a,\u8aad\u307f]"
        value = "\\RB[\u8868\u793a,\u304b\u306a]"
        assert qc.validate({key: "x"}, {key: value}) == []

    def test_translated_rb_argument_is_not_a_control_code_diff(self):
        """A ruby code with translated arguments (\u8868\u793a,\u8aad\u307f ->
        label,reading) keeps the same structure: only the argument count
        matters and no diff may be reported."""
        key = "\\RB[\u8868\u793a,\u8aad\u307f]Hello"
        value = "\\RB[label,reading]Hello"
        assert qc.validate({key: "x"}, {key: value}) == []

    def test_control_code_token_diff_is_reported(self):
        issues = qc.validate({KEY_CODE: "x"}, {KEY_CODE: "Hello"})
        assert any("control-code tokens differ" in i for i in issues)

    def test_renamed_control_code_is_reported(self):
        """Same token count, different code name: a real structural diff."""
        issues = qc.validate({KEY_CODE: "x"}, {KEY_CODE: "\\N[1]Hello"})
        assert any("control-code tokens differ" in i for i in issues)

    def test_double_backslash_is_reported(self):
        issues = qc.validate({KEY: "x"}, {KEY: "Hello \\\\ end"})
        assert any("double-backslash values" in i for i in issues)

    def test_uncertainty_marker_is_reported(self):
        issues = qc.validate({KEY: "x"}, {KEY: "\u3010?\u3011Hello"})
        assert any("uncertainty markers" in i for i in issues)

    def test_non_string_values_are_skipped(self):
        """Values that are not strings are not compared - and never crash."""
        assert qc.validate({KEY: 42}, {KEY: 42}) == []
        issues = qc.validate({KEY: None}, {KEY: None})
        # A falsy non-string only trips the empty-value rule; the per-key
        # string checks (kana / newline / control code) stay out of it.
        assert issues == ["empty values: ['" + KEY + "']"]

    def test_several_issues_are_reported_together(self):
        issues = qc.validate({"a": "Hello", "b": "Bye"}, {"b": KANA_RESIDUE})
        assert any("missing keys" in i for i in issues)
        assert any("kana still in values" in i for i in issues)


class TestLevenshtein:
    def test_identical_strings(self):
        assert qc.levenshtein(KEY, KEY) == 0

    def test_substitution_insertion_deletion(self):
        assert qc.levenshtein("abc", "abd") == 1
        assert qc.levenshtein("abc", "abcd") == 1
        assert qc.levenshtein("abcd", "abc") == 1

    def test_exact_distance_three(self):
        assert qc.levenshtein("abcd", "axyz") == 3

    def test_length_gap_gives_up(self):
        assert qc.levenshtein("ab", "abcdef") == 99

    def test_far_strings_give_up(self):
        assert qc.levenshtein("aaaaaaaa", "bbbbbbbb") == 99

    def test_empty_strings(self):
        assert qc.levenshtein("", "") == 0
        assert qc.levenshtein("", "abc") == 3


class TestPatchAlteredKeys:
    def test_escaped_backslash_in_key_is_unescaped(self):
        out = {"\\\\" + KEY_CODE: "Hello"}
        issues = []
        got = qc.patch_altered_keys({KEY_CODE: "x"}, out, issues)
        assert got == {KEY_CODE: "Hello"}
        assert any("patched 1 altered keys" in i for i in issues)

    def test_dropped_backslashes_in_key_are_restored(self):
        out = {"C[27]" + KEY: "Hello"}
        issues = []
        got = qc.patch_altered_keys({KEY_CODE: "x"}, out, issues)
        assert got == {KEY_CODE: "Hello"}
        assert any("patched 1" in i for i in issues)

    def test_close_key_is_renamed(self):
        src = {"\u3053\u3093\u306b\u3061\u306f\u3067\u3059": "x"}
        out = {"\u3053\u3093\u306b\u3061\u306f\u3067\u305a": "Hello"}
        issues = []
        got = qc.patch_altered_keys(src, out, issues)
        assert got == {"\u3053\u3093\u306b\u3061\u306f\u3067\u3059": "Hello"}
        assert any("patched 1" in i for i in issues)

    def test_far_key_is_left_alone(self):
        out = {"completely-different": "Hello"}
        issues = []
        got = qc.patch_altered_keys({KEY: "x"}, out, issues)
        assert got == out
        assert issues == []

    def test_nothing_to_patch(self):
        src = {KEY: "x"}
        issues = []
        assert qc.patch_altered_keys(src, {KEY: "Hello"}, issues) == {KEY: "Hello"}
        assert issues == []

    def test_two_missing_keys_share_one_candidate(self):
        """Only one extra key exists, so only one of the two missing keys can
        be patched - the other stays missing for validate() to report."""
        src = {"aaaa": "x", "bbbb": "y"}
        out = {"aaab": "Hello"}
        issues = []
        got = qc.patch_altered_keys(src, out, issues)
        assert got == {"aaaa": "Hello"}
        assert "bbbb" not in got
        assert any("patched 1" in i for i in issues)


class TestMain:
    def test_merges_translated_chunk(self, tmp_path, monkeypatch, capsys):
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "chunk_01.json", {KEY: "x", "goodbye": "y"})
        write_json(chunks / "chunk_01.translated.json",
                   {KEY: "Hello", "goodbye": "Bye"})
        run_main(monkeypatch, tmp_path)
        out = capsys.readouterr().out
        assert "merged: 2 entries -> completion.json" in out
        assert "chunk_01.translated.json: OK (2 keys)" in out
        assert merged(tmp_path) == {KEY: "Hello", "goodbye": "Bye"}
        # merged file stays human-readable (no \uXXXX escapes)
        assert KEY in read_text(tmp_path / "completion.json")

    def test_invalid_escapes_are_repaired_on_disk(self, tmp_path, monkeypatch,
                                                 capsys):
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "chunk_01.json", {KEY_CODE: "x"})
        write_text(chunks / "chunk_01.translated.json",
                   '{"\\C[27]' + KEY + '": "\\C[27]Hello"}')
        run_main(monkeypatch, tmp_path)
        out = capsys.readouterr().out
        assert "[escapes repaired 1]" in out
        # the repaired text was written back and now parses
        assert json.loads(read_text(chunks / "chunk_01.translated.json")) == \
            {KEY_CODE: "\\C[27]Hello"}
        assert merged(tmp_path) == {KEY_CODE: "\\C[27]Hello"}

    def test_source_missing_is_reported(self, tmp_path, monkeypatch, capsys):
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "chunk_09.translated.json", {KEY: "Hello"})
        run_main(monkeypatch, tmp_path)
        out = capsys.readouterr().out
        assert "chunk_09.translated.json: SOURCE MISSING" in out
        assert "merged: 0 entries" in out
        assert merged(tmp_path) == {}

    def test_unrepairable_chunk_is_reported_and_skipped(self, tmp_path,
                                                        monkeypatch, capsys):
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "chunk_01.json", {KEY: "x"})
        write_text(chunks / "chunk_01.translated.json", '{"a": "b"')
        run_main(monkeypatch, tmp_path)
        out = capsys.readouterr().out
        assert "REPAIR UNABLE" in out
        assert merged(tmp_path) == {}

    def test_kana_residue_is_reported_but_still_merged(self, tmp_path,
                                                       monkeypatch, capsys):
        """QC reports, it does not block: the merged file keeps the flagged
        value so a later pass can fix it."""
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "chunk_01.json", {KEY: "x"})
        write_json(chunks / "chunk_01.translated.json", {KEY: KANA_RESIDUE})
        run_main(monkeypatch, tmp_path)
        out = capsys.readouterr().out
        assert "ISSUES: kana still in values" in out
        assert merged(tmp_path) == {KEY: KANA_RESIDUE}

    def test_non_chunk_files_are_ignored(self, tmp_path, monkeypatch, capsys):
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "notes.json", {KEY: "Hello"})
        write_json(chunks / "chunk_02.json", {KEY: "x"})
        write_json(chunks / "chunk_02.translated.json", {KEY: "Hello"})
        write_text(chunks / "chunk_02.zh.txt", KEY + "\n")
        run_main(monkeypatch, tmp_path)
        out = capsys.readouterr().out
        assert "notes.json" not in out
        assert "SOURCE MISSING" not in out
        assert "merged: 1 entries" in out

    def test_altered_key_is_patched_before_merge(self, tmp_path, monkeypatch,
                                                 capsys):
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "chunk_01.json", {KEY_CODE: "x"})
        # the agent doubled the backslash in the key: still valid JSON, but
        # the key no longer matches the source chunk
        write_json(chunks / "chunk_01.translated.json",
                   {"\\\\C[27]" + KEY: "\\C[27]Hello"})
        run_main(monkeypatch, tmp_path)
        out = capsys.readouterr().out
        # The rename is reported now: it used to be computed into a list that
        # main() immediately rebound, so repaired chunks looked clean.
        assert "patched 1 altered keys" in out
        # the renamed key matches the source key again, so the value merges
        assert merged(tmp_path) == {KEY_CODE: "\\C[27]Hello"}

    def test_merge_output_name_is_configurable(self, tmp_path, monkeypatch,
                                               capsys):
        chunks = chunks_dir(tmp_path)
        write_json(chunks / "chunk_01.json", {KEY: "x"})
        write_json(chunks / "chunk_01.translated.json", {KEY: "Hello"})
        run_main(monkeypatch, tmp_path, "--merge", "completion_round2.json")
        assert "completion_round2.json" in capsys.readouterr().out
        assert merged(tmp_path, "completion_round2.json") == {KEY: "Hello"}
