#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for unity/rmunite/prefill.py - series prefill of each game's
translated.json from a previous game's base dict.

Contract under test:
- importing the module must NOT execute anything (arg parsing moved into
  main(); no file writes, no SystemExit on empty argv),
- the CLI keeps its behavior: exact base hits first, then 【Name】 prefix
  replacement, unresolved keys listed and written out.
"""
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from unity.rmunite import prefill  # noqa: E402


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def make_work(work, key, base, meta):
    """A prefill workspace: series base translated.json + per-game meta keys."""
    write_json(os.path.join(work, "translated.json"), base)
    write_json(os.path.join(work, key, "keys_target_meta.json"), meta)
    return work


def run_prefill(work, key, *extra, monkeypatch):
    argv = ["prefill.py", work, key] + list(extra)
    monkeypatch.setattr("sys.argv", argv)
    return prefill.main()


class TestImportIsSideEffectFree:
    def test_import_without_argv_does_not_execute(self):
        # Module-level execution (old code) would call parse_args() with an
        # empty argv and exit(2).  A clean import must succeed and expose main.
        code = ("import sys; sys.path.insert(0, %r); "
                "from unity.rmunite import prefill; "
                "assert hasattr(prefill, 'main'); print('OK')" % REPO_ROOT)
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "OK" in r.stdout


class TestTranslateLine:
    def test_exact_base_hit(self):
        base = {"こんにちは": "你好"}
        assert prefill.translate_line("こんにちは", base, {}) == "你好"

    def test_name_prefix_replacement(self):
        base = {"こんにちは": "你好"}
        names = {"名前": "名字"}
        assert prefill.translate_line("【名前】こんにちは", base, names) \
            == "【名字】你好"

    def test_name_prefix_unknown_name_keeps_japanese_body(self):
        # Body not in base: base.get(rest, rest) keeps it verbatim (半翻译
        # warning class documented in AGENTS.md).
        base = {}
        names = {"名前": "名字"}
        assert prefill.translate_line("【名前】不明な文", base, names) \
            == "【名字】不明な文"

    def test_untranslatable_returns_none(self):
        assert prefill.translate_line("ただの文", {}, {}) is None


class TestCli:
    def test_full_run(self, tmp_path, monkeypatch):
        work = str(tmp_path / "work")
        key = "game_a"
        make_work(work, key,
                  base={"こんにちは": "你好", "さようなら": "再见"},
                  meta=["こんにちは", "【名前】こんにちは", "未訳の行"])
        names = str(tmp_path / "names.json")
        write_json(names, {key: {"名前": "名字"}})
        run_prefill(work, key, "--names", names, monkeypatch=monkeypatch)

        with open(os.path.join(work, key, "translated_prefill.json"),
                  encoding="utf-8") as f:
            prefill_out = json.load(f)
        assert prefill_out == {
            "こんにちは": "你好",
            "【名前】こんにちは": "【名字】你好",
        }
        with open(os.path.join(work, key, "unresolved.txt"),
                  encoding="utf-8") as f:
            assert f.read() == "未訳の行\n"

    def test_run_without_names_keeps_prefix(self, tmp_path, monkeypatch):
        work = str(tmp_path / "work")
        key = "game_b"
        make_work(work, key,
                  base={"こんにちは": "你好"},
                  meta=["【名前】こんにちは"])
        run_prefill(work, key, monkeypatch=monkeypatch)
        with open(os.path.join(work, key, "translated_prefill.json"),
                  encoding="utf-8") as f:
            prefill_out = json.load(f)
        # No --names table: the name is unknown, so the line cannot be
        # resolved and is left untouched (listed as unresolved).
        assert prefill_out == {}
        with open(os.path.join(work, key, "unresolved.txt"),
                  encoding="utf-8") as f:
            assert f.read() == "【名前】こんにちは\n"

    def test_missing_base_file_raises(self, tmp_path, monkeypatch):
        work = str(tmp_path / "empty")
        os.makedirs(os.path.join(work, "game_c"), exist_ok=True)
        with pytest.raises(OSError):
            run_prefill(work, "game_c", monkeypatch=monkeypatch)
