#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tyrano/ui_lang.py - localizing the TyranoScript engine UI.

`tyrano/lang.js` sits outside data/scenario, so a fully translated scenario
still shows Japanese in the engine's own dialogs (return-to-title confirm,
"no save data", script errors).  These tests pin the merge-by-key behaviour,
the mechanical gate and the refusal to touch anything else.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pytest  # noqa: E402

from tyrano import ui_lang as ul  # noqa: E402

# Mirrors the real file's shape: two blocks, mixed quotes, a placeholder, an
# escaped newline, a multi-line value and a `novel` filename block.
LANG_JS = """window.tyrano_lang = {
    word: {
        go_title: "\u30bf\u30a4\u30c8\u30eb\u306b\u623b\u308a\u307e\u3059\u3002\u3088\u308d\u3057\u3044\u3067\u3059\u304b\uff1f",
        not_saved: "\u307e\u3060\u3001\u4fdd\u5b58\u3055\u308c\u3066\u3044\u308b\u30c7\u30fc\u30bf\u304c\u3042\u308a\u307e\u305b\u3093\u3002",
        undefined_tag: "\u30bf\u30b0\u300c{ name }\u300d\u306f\u5b58\u5728\u3057\u307e\u305b\u3093\u3002",
        compensate_missing_quart:
            '\u4e88\u671f\u3057\u306a\u3044 "]" \u3092\u691c\u77e5\u3057\u307e\u3057\u305f\u3002\\n\\n\u4fee\u6b63\u524d: { before }',
        missing_endif: "[if] \u306e\u3042\u3068\u306b [elsif] \u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3002\u307e\u305f\u306f\u3001[if] \u5185\u306e\u30bf\u30b0\u306e\u6570\u304c\u591a\u3059\u304e\u307e\u3059\u3002",
    },

    novel: {
        file_menu_bg: "menu_bg.jpg",
    },
};
"""


def make_lang(tmp_path, text=LANG_JS):
    p = tmp_path / "tyrano"
    p.mkdir(parents=True, exist_ok=True)
    f = p / "lang.js"
    f.write_text(text, encoding="utf-8")
    return f


class TestExtract:
    def test_reads_word_block_only(self, tmp_path):
        f = make_lang(tmp_path)
        got = ul.extract(str(f))
        assert list(got) == ["go_title", "not_saved", "undefined_tag",
                             "compensate_missing_quart", "missing_endif"]
        assert "menu_bg.jpg" not in "".join(got.values())

    def test_placeholder_and_escapes_survive(self, tmp_path):
        f = make_lang(tmp_path)
        got = ul.extract(str(f))
        assert "{ name }" in got["undefined_tag"]
        assert got["compensate_missing_quart"].count("\\n") == 2

    def test_single_quoted_value(self, tmp_path):
        f = make_lang(tmp_path)
        assert ul.extract(str(f))["compensate_missing_quart"].startswith("\u4e88\u671f")

    def test_missing_block_is_an_error(self, tmp_path):
        f = make_lang(tmp_path, "window.x = {};\n")
        with pytest.raises(ValueError):
            ul.extract(str(f))

    def test_find_lang_file_accepts_build_root(self, tmp_path):
        f = make_lang(tmp_path)
        assert ul.find_lang_file(str(tmp_path)) == str(f)
        assert ul.find_lang_file(str(f)) == str(f)

    def test_find_lang_file_missing(self, tmp_path):
        assert ul.find_lang_file(str(tmp_path)) is None


class TestCheckValue:
    def test_ok(self):
        assert ul.check_value("a{ n }b", "\u7532{ n }\u4e59", "k") is None

    def test_rejects_placeholder_drift(self):
        assert "placeholder" in ul.check_value("a{ n }b", "\u7532", "k")

    def test_rejects_newline_drift(self):
        assert "newline" in ul.check_value("a\\n\\nb", "\u7532\\n\u4e59", "k")

    def test_rejects_kana(self):
        assert "kana" in ul.check_value("a", "\u7532\u3042", "k")

    def test_rejects_empty(self):
        assert "empty" in ul.check_value("a", "   ", "k")


class TestApply:
    def test_applies_and_keeps_other_bytes(self, tmp_path):
        f = make_lang(tmp_path)
        before = f.read_text(encoding="utf-8")
        report = ul.apply_map(str(f), {
            "go_title": "\u8981\u56de\u5230\u6807\u9898\u754c\u9762\u5417\uff1f",
            "undefined_tag": "\u6807\u7b7e\u300c{ name }\u300d\u4e0d\u5b58\u5728\u3002",
        })
        after = f.read_text(encoding="utf-8")
        assert report["applied"] == ["go_title", "undefined_tag"]
        assert report["missing"] == [] and report["refused"] == []
        assert '"\u8981\u56de\u5230\u6807\u9898\u754c\u9762\u5417\uff1f"' in after
        assert "\u30bf\u30a4\u30c8\u30eb\u306b\u623b\u308a\u307e\u3059" not in after
        # untranslated entries and the novel block are byte-identical
        assert "not_saved" in after and "menu_bg.jpg" in after
        assert before.count("file_menu_bg") == after.count("file_menu_bg")

    def test_single_quote_style_is_kept_when_needed(self, tmp_path):
        """The stock file single-quotes the one sentence containing a double
        quote; the translation must not break out of the string."""
        f = make_lang(tmp_path)
        ul.apply_map(str(f), {
            "compensate_missing_quart":
                '\u68c0\u6d4b\u5230\u610f\u5916\u7684 "]" \u3002\\n\\n\u4fee\u6b63\u524d: { before }',
        })
        after = f.read_text(encoding="utf-8")
        line = [ln for ln in after.splitlines()
                if "compensate_missing_quart" in ln][0]
        assert "'string'" not in line
        assert ul.extract(str(f))["compensate_missing_quart"].startswith("\u68c0\u6d4b")

    def test_refuses_bad_entry_and_leaves_it(self, tmp_path):
        f = make_lang(tmp_path)
        report = ul.apply_map(str(f), {
            "go_title": "\u56de\u6807\u9898\u5417",              # ok
            "undefined_tag": "\u6807\u7b7e\u4e0d\u5b58\u5728",    # drops { name }
            "missing_endif": "\u7f3a\u5c11\u7ed3\u675f\u6807\u7b7e\u3042",  # kana
        })
        assert report["applied"] == ["go_title"]
        assert len(report["refused"]) == 2
        got = ul.extract(str(f))
        assert "{ name }" in got["undefined_tag"]
        assert got["missing_endif"] == ul.extract(str(make_lang(tmp_path / "r")))[
            "missing_endif"]

    def test_unknown_keys_are_reported_not_inserted(self, tmp_path):
        f = make_lang(tmp_path)
        report = ul.apply_map(str(f), {"no_such_key": "\u4e2d\u6587"})
        assert report["missing"] == ["no_such_key"]
        assert "no_such_key" not in f.read_text(encoding="utf-8")

    def test_dry_run_writes_nothing(self, tmp_path):
        f = make_lang(tmp_path)
        before = f.read_text(encoding="utf-8")
        report = ul.apply_map(str(f), {"go_title": "\u56de\u6807\u9898\u5417"},
                              dry_run=True)
        assert report["applied"] == ["go_title"]
        assert f.read_text(encoding="utf-8") == before

    def test_identical_value_is_not_rewritten(self, tmp_path):
        f = make_lang(tmp_path)
        ja = ul.extract(str(f))["go_title"]
        report = ul.apply_map(str(f), {"go_title": ja})
        assert report["applied"] == []

    def test_comment_in_block_is_refused(self, tmp_path):
        text = LANG_JS.replace('word: {', 'word: {\n        // note')
        f = make_lang(tmp_path, text)
        with pytest.raises(ValueError):
            ul.apply_map(str(f), {"go_title": "\u56de\u6807\u9898\u5417"})

class TestShippedMapping:
    """`tyrano/ui_lang_zh.json` is the reusable engine UI mapping that ships
    with the toolkit (TyranoScript 6.00 `word` block).  It is engine text,
    not game text, so it lives in the repo and is meant to be passed to other
    TyranoScript games."""

    PATH = os.path.join(REPO, "tyrano", "ui_lang_zh.json")

    def _table(self):
        with open(self.PATH, encoding="utf-8") as f:
            return json.load(f)

    def test_mapping_is_valid_and_kana_free(self):
        table = self._table()
        assert len(table) >= 40, "engine UI set looks truncated"
        for key, value in table.items():
            assert key.isascii() and key.replace("_", "").isalnum(), key
            assert value.strip(), key
            assert "\r" not in value, key
            assert not ul.KANA_RE.search(value), (key, value)

    def test_reuse_on_a_different_lang_js_invents_nothing(self, tmp_path):
        """Applied to another game's lang.js the mapping must only touch the
        keys that file actually has, report the rest as missing, and refuse
        an entry whose placeholder/newline shape differs from that file -
        never insert engine keys a build does not carry."""
        f = make_lang(tmp_path)
        report = ul.apply_map(str(f), self._table())
        assert set(report["applied"]).issubset(set(ul.extract(str(f))))
        assert "go_title" in report["applied"]
        assert report["missing"], "a 5-key fixture must leave the rest missing"
        after = f.read_text(encoding="utf-8")
        assert "menu_bg.jpg" in after and "not_saved" in after
        # no entry was added or removed: the key set is the file's own
        fresh = make_lang(tmp_path / "fresh")
        assert set(ul.extract(str(f))) == set(ul.extract(str(fresh)))

        # the fixture is a trimmed lang.js: the one shipped entry whose
        # shape differs (extra `{ after }`, third \n) is refused, and the
        # file keeps that entry's original bytes
        refused_keys = [item.split(":", 1)[0] for item in report["refused"]]
        assert refused_keys, "the shape gate must catch the trimmed entry"
        for key in refused_keys:
            assert ul.extract(str(f))[key] == ul.extract(str(fresh))[key], key


class TestCliWiring:
    """The `localize-ui` command is the only supported way to reach the
    engine UI; a wiring slip here would again be invisible to the unit
    tests above (see TestAudioCommandWiring for the same lesson)."""

    def test_command_dumps_and_applies(self, tmp_path):
        from rpgmaker import cli
        f = make_lang(tmp_path)
        dumped = tmp_path / "ui.json"
        cli.cmd_tyrano_localize_ui(str(tmp_path), mapping=None,
                                   dump=str(dumped), dry_run=False)
        assert json.loads(dumped.read_text(encoding="utf-8"))["go_title"]

        mapping = tmp_path / "map.json"
        mapping.write_text(json.dumps({
            "go_title": "\u8981\u56de\u5230\u6807\u9898\u754c\u9762\u5417\uff1f"},
            ensure_ascii=False), encoding="utf-8")
        cli.cmd_tyrano_localize_ui(str(tmp_path), mapping=str(mapping),
                                   dump=None, dry_run=False)
        assert "\u8981\u56de\u5230\u6807\u9898\u754c\u9762\u5417\uff1f" in f.read_text(
            encoding="utf-8")

    def test_command_without_lang_file_exits(self, tmp_path):
        from rpgmaker import cli
        import typer
        with pytest.raises(typer.Exit):
            cli.cmd_tyrano_localize_ui(str(tmp_path), mapping=None,
                                       dump=None, dry_run=False)

    def test_command_refuses_bad_mapping(self, tmp_path):
        from rpgmaker import cli
        import typer
        make_lang(tmp_path)
        mapping = tmp_path / "map.json"
        mapping.write_text(json.dumps({"undefined_tag": "\u4e2d\u6587"},
                                      ensure_ascii=False), encoding="utf-8")
        with pytest.raises(typer.Exit):
            cli.cmd_tyrano_localize_ui(str(tmp_path), mapping=str(mapping),
                                       dump=None, dry_run=False)

    def test_command_dry_run_keeps_file(self, tmp_path):
        from rpgmaker import cli
        f = make_lang(tmp_path)
        before = f.read_text(encoding="utf-8")
        mapping = tmp_path / "map.json"
        mapping.write_text(json.dumps({"go_title": "\u56de\u6807\u9898\u5417"},
                                      ensure_ascii=False), encoding="utf-8")
        cli.cmd_tyrano_localize_ui(str(tmp_path), mapping=str(mapping),
                                   dump=None, dry_run=True)
        assert f.read_text(encoding="utf-8") == before

    def test_mapping_file_roundtrip(self, tmp_path):
        """A mapping built from `dump` JSON applies cleanly."""
        f = make_lang(tmp_path)
        strings = ul.extract(str(f))
        mapping = {k: "\u6d4b\u8bd5" + ("\\n" * v.count("\\n"))
                   + "".join(ul._PLACEHOLDER_RE.findall(v))
                   for k, v in strings.items()}
        report = ul.apply_map(str(f), mapping)
        assert report["refused"] == []
        assert json.loads(json.dumps(mapping, ensure_ascii=False)) == mapping
