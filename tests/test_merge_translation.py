#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/merge_translation.py - the final merge step that
combines agent chunk output + prefilled (MTool exact hits) + terminology sweep
into translated.json.

Contract under test (AGENTS.md / docs/translation.md):
- chunks + prefilled merge into translated.json; prefilled keys OVERRIDE chunk
  keys on collision,
- sweep rules are applied IN ORDER, longest-first (a target that is the prefix
  of another rule must not be re-hit later - the 'substring bomb'),
- template.json drives missing/extra reporting,
- legacy mode globs chunks/*.translated.json when --chunks is omitted.
"""
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys  # noqa: E402
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import merge_translation as mt  # noqa: E402


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def make_work(work, template, chunks=None, prefilled=None):
    """Write a merge workspace: template.json always, plus optional chunks and
    prefilled files."""
    os.makedirs(work, exist_ok=True)
    write_json(os.path.join(work, "template.json"), template)
    if chunks is not None:
        write_json(os.path.join(work, "chunks_translated.json"), chunks)
    if prefilled is not None:
        write_json(os.path.join(work, "prefilled.json"), prefilled)


def run_merge(work, *args, monkeypatch):
    argv = ["merge_translation.py", work] + list(args)
    monkeypatch.setattr("sys.argv", argv)
    return mt.main()


class TestLoadSweeps:
    def test_list_of_pairs_sorted_longest_first(self, tmp_path):
        p = str(tmp_path / "sweep.json")
        write_json(p, [["短い", "x"], ["とても長いターゲット", "y"]])
        rules = mt.load_sweeps(p)
        assert rules == [["とても長いターゲット", "y"], ["短い", "x"]]

    def test_dict_form(self, tmp_path):
        p = str(tmp_path / "sweep.json")
        write_json(p, {"a": "b", "長いキーですね": "c"})
        rules = mt.load_sweeps(p)
        assert rules == [("長いキーですね", "c"), ("a", "b")]


class TestMergeFlow:
    def test_chunks_only(self, tmp_path, monkeypatch, capsys):
        work = str(tmp_path / "work")
        make_work(work, {"こんにちは": "", "さようなら": ""},
                  chunks={"こんにちは": "你好", "さようなら": "再见"})
        run_merge(work, "--chunks", "chunks_translated.json",
                  monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"こんにちは": "你好", "さようなら": "再见"}
        assert "chunks merged: 2 keys" in capsys.readouterr().out

    def test_prefilled_overrides_chunks(self, tmp_path, monkeypatch):
        work = str(tmp_path / "work")
        make_work(work, {"こんにちは": ""},
                  chunks={"こんにちは": "你好(agent)"},
                  prefilled={"こんにちは": "你好(prefilled)"})
        run_merge(work, "--chunks", "chunks_translated.json",
                  "--prefilled", os.path.join(work, "prefilled.json"),
                  monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"こんにちは": "你好(prefilled)"}

    def test_prefilled_adds_new_keys(self, tmp_path, monkeypatch):
        work = str(tmp_path / "work")
        make_work(work, {"a": "", "b": ""},
                  chunks={"a": "A"},
                  prefilled={"b": "B"})
        run_merge(work, "--chunks", "chunks_translated.json",
                  "--prefilled", os.path.join(work, "prefilled.json"),
                  monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"a": "A", "b": "B"}

    def test_prefilled_and_sweep_relative_to_work_dir(self, tmp_path,
                                                      monkeypatch):
        # C1 contract: every file arg (--chunks/--prefilled/--sweep/--out)
        # resolves RELATIVE TO work_dir, so a bare name works regardless of
        # the current directory.
        work = str(tmp_path / "work")
        make_work(work, {"力": ""}, chunks={"力": "色"},
                  prefilled={"力": "色"})
        write_json(os.path.join(work, "sweep.json"), [["色", "色色"]])
        run_merge(work, "--chunks", "chunks_translated.json",
                  "--prefilled", "prefilled.json",
                  "--sweep", "sweep.json", monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"力": "色色"}

    def test_sweep_applied_to_chunks(self, tmp_path, monkeypatch):
        work = str(tmp_path / "work")
        make_work(work, {"力": ""}, chunks={"力": "色"})
        sweep = str(tmp_path / "sweep.json")
        write_json(sweep, [["色", "色色"]])
        run_merge(work, "--chunks", "chunks_translated.json",
                  "--sweep", sweep, monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"力": "色色"}

    def test_sweep_applied_to_prefilled(self, tmp_path, monkeypatch, capsys):
        work = str(tmp_path / "work")
        make_work(work, {"力": ""}, chunks={}, prefilled={"力": "色"})
        sweep = str(tmp_path / "sweep.json")
        write_json(sweep, [["色", "色色"]])
        run_merge(work, "--chunks", "chunks_translated.json",
                  "--prefilled", os.path.join(work, "prefilled.json"),
                  "--sweep", sweep, monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"力": "色色"}
        assert "prefilled merged: 1 keys (1 swept)" in capsys.readouterr().out

    def test_sweep_order_longest_first(self, tmp_path, monkeypatch):
        # Substring bomb (docs/translation.md §4.2): a rule whose target is the
        # prefix of a later target must be applied longest-first, otherwise the
        # later rule is re-hit on the already-swept text.
        work = str(tmp_path / "work")
        make_work(work, {"x": ""}, chunks={"x": "色"})
        sweep = str(tmp_path / "sweep.json")
        write_json(sweep, [["色", "色色"], ["色色経験値", "色欲経験値"]])
        run_merge(work, "--chunks", "chunks_translated.json",
                  "--sweep", sweep, monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        # "色" -> "色色"; the longer rule target no longer appears
        assert merged == {"x": "色色"}

    def test_template_missing_extra_reporting(self, tmp_path, monkeypatch,
                                              capsys):
        work = str(tmp_path / "work")
        make_work(work, {"a": "", "b": ""},
                  chunks={"a": "A", "extra": "X"})
        run_merge(work, "--chunks", "chunks_translated.json",
                  monkeypatch=monkeypatch)
        out = capsys.readouterr().out
        assert "missing: 1" in out  # "b" not translated
        assert "extra: 1" in out    # "extra" not in template

    def test_custom_out_name(self, tmp_path, monkeypatch):
        work = str(tmp_path / "work")
        make_work(work, {"a": ""}, chunks={"a": "A"})
        run_merge(work, "--chunks", "chunks_translated.json",
                  "--out", "final.json", monkeypatch=monkeypatch)
        assert os.path.exists(os.path.join(work, "final.json"))
        assert not os.path.exists(os.path.join(work, "translated.json"))

    def test_legacy_glob_chunks(self, tmp_path, monkeypatch):
        work = str(tmp_path / "work")
        chunks_dir = os.path.join(work, "chunks")
        os.makedirs(chunks_dir)
        write_json(os.path.join(chunks_dir, "chunk_01.translated.json"),
                   {"こんにちは": "你好"})
        write_json(os.path.join(chunks_dir, "chunk_02.translated.json"),
                   {"さようなら": "再见"})
        make_work(work, {"こんにちは": "", "さようなら": ""})
        run_merge(work, monkeypatch=monkeypatch)
        with open(os.path.join(work, "translated.json"), encoding="utf-8") as f:
            merged = json.load(f)
        assert merged == {"こんにちは": "你好", "さようなら": "再见"}

    def test_missing_template_exits(self, tmp_path, monkeypatch):
        # template.json is required to report missing/extra; a missing one
        # propagates the file error
        work = str(tmp_path / "work")
        os.makedirs(work)
        write_json(os.path.join(work, "chunks_translated.json"), {"a": "A"})
        monkeypatch.setattr("sys.argv",
                            ["merge_translation.py", work, "--chunks",
                             "chunks_translated.json"])
        with pytest.raises(OSError):
            mt.main()
