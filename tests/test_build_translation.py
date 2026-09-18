#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/build_translation.py - the static-translation work
package builder (template / names / structure / context / name macros).

Contract under test (AGENTS.md + docs/translation.md):
- template.json: every translatable static string; message runs become block
  keys (lines joined with "\\n"), pure-ASCII keys are dropped,
- located keys (\\x1f<loc>) for text repeated in different places; short
  name-like strings are exempt and keep a single plain key,
- kinds.json / structure.json (story order tree) / context.json (windows) /
  name_macros.json (\\N[x]/\\P[x] -> actor names),
- plugin parameter text from js/plugins.js (kind "plugin"), --no-plugins off.
"""
import json
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import build_translation as bt  # noqa: E402


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def make_game(root, maps=None, common_events=None, actors=None, items=None,
              system=None, plugins=None):
    """Minimal synthetic MZ game.  `maps` = {fname: (map_name, events)}."""
    data = os.path.join(root, "data")
    os.makedirs(data)
    os.makedirs(os.path.join(root, "js"))
    mi = []
    for i, fname in enumerate(sorted(maps or {}), start=1):
        mi.append({"id": i, "name": maps[fname][0] or ("MAP%03d" % i),
                   "expanded": True})
        write_json(os.path.join(data, fname), {
            "@name": fname.replace(".json", ""),
            "displayName": maps[fname][0],
            "events": maps[fname][1]})
    write_json(os.path.join(data, "MapInfos.json"), mi)
    write_json(os.path.join(data, "CommonEvents.json"), common_events or [])
    write_json(os.path.join(data, "Actors.json"), actors or [])
    write_json(os.path.join(data, "Items.json"), items or [])
    write_json(os.path.join(data, "System.json"), system or {})
    with open(os.path.join(root, "js", "plugins.js"), "w", encoding="utf-8") as f:
        f.write(plugins if plugins is not None else "var $plugins = [];\n")


def text_cmd(text, code=401):
    return {"code": code, "indent": 0, "parameters": [text]}


def page(commands):
    return {"conditions": {}, "list": commands}


def ev(ev_id, name, commands, note=""):
    return {"id": ev_id, "name": name, "note": note, "pages": [page(commands)]}


def run_build(root, out, *extra, monkeypatch):
    argv = ["build_translation.py", root, out] + list(extra)
    monkeypatch.setattr("sys.argv", argv)
    bt.main()


def load(out, name):
    with open(os.path.join(out, name), encoding="utf-8-sig") as f:
        return json.load(f)


class TestCollectorLocKeys:
    def test_first_occurrence_plain_key(self):
        col = bt.Collector()
        col.add("こんにちは", "block", "m", [], "Map001.json#ev0#pg0#c0")
        assert "こんにちは" in col.keys
        assert "こんにちは\x1fMap001.json#ev0#pg0#c0" not in col.keys

    def test_second_occurrence_gets_located_key(self):
        col = bt.Collector()
        # >14 chars and not a bare name line -> NOT exempt from located keys
        key = "ここにいるひととのはなしはとてもたのしい"
        col.add(key, "block", "m", [], "Map001.json#ev0#pg0#c0")
        col.add(key, "block", "m", [], "Map002.json#ev0#pg0#c0")
        assert key in col.keys
        assert key + "\x1fMap002.json#ev0#pg0#c0" in col.keys

    def test_short_name_like_stays_plain(self):
        # names / person references keep a single plain key regardless of count
        col = bt.Collector()
        col.add("むらびと", "event-name", "m", [], "Map001.json#ev0#name")
        col.add("むらびと", "event-name", "m", [], "Map002.json#ev0#name")
        assert "むらびと" in col.keys
        assert "むらびと\x1fMap002.json#ev0#name" not in col.keys


class TestNameMacros:
    def test_build_name_macros(self, tmp_path):
        data = str(tmp_path / "data")
        os.makedirs(data)
        write_json(os.path.join(data, "Actors.json"),
                   [{"id": 1, "name": "ゆうしゃ"}, {"id": 2, "name": "まほうつかい"}])
        macros = bt.build_name_macros(data)
        assert macros == {"\\N[1]": "ゆうしゃ", "\\P[1]": "ゆうしゃ",
                          "\\N[2]": "まほうつかい", "\\P[2]": "まほうつかい"}

    def test_build_name_macros_no_actors(self, tmp_path):
        data = str(tmp_path / "data")
        os.makedirs(data)
        assert bt.build_name_macros(data) == {}


class TestMainTemplate:
    def test_block_key_joins_message_lines(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={
            "Map001.json": ("はじまりの村", [ev(1, "むらびと", [
                text_cmd("こんにちは"), text_cmd("きょうはいい天気だね")])]),
        })
        run_build(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        assert "こんにちは\nきょうはいい天気だね" in template
        # individual lines of a block are NOT separate keys
        assert "こんにちは" not in template

    def test_single_line_is_own_block(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [text_cmd("おはよう")])]),
        })
        run_build(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        assert "おはよう" in template

    def test_choices_and_event_text_extracted(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [
                {"code": 102, "indent": 0,
                 "parameters": [["はい", "いいえ"], 0, 0, 0]},
                {"code": 101, "indent": 0,
                 "parameters": ["", 0, 0, 0, "ゆうしゃ"]},
            ])]),
        })
        run_build(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        kinds = load(out, "kinds.json")
        assert "はい" in template and kinds["はい"] == "choice"
        assert "いいえ" in template and kinds["いいえ"] == "choice"
        assert "ゆうしゃ" in template and kinds["ゆうしゃ"] == "event-text"
        # speaker name is also a name candidate
        names = load(out, "names.json")
        assert "ゆうしゃ" in names

    def test_db_and_system_text(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={"Map001.json": ("", [])},
                  items=[{"id": 1, "name": "やくそう",
                          "description": "HPをかいふくする", "note": ""}],
                  system={"terms": {"basic": ["HP", "MP"]},
                          "gameTitle": "こんにちは",
                          "elements": ["", "ニューゲーム"]})
        run_build(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        kinds = load(out, "kinds.json")
        assert "やくそう" in template and kinds["やくそう"] == "db-name"
        assert "HPをかいふくする" in template
        assert kinds["HPをかいふくする"] == "db-description"
        assert "こんにちは" in template and kinds["こんにちは"] == "system"
        assert "ニューゲーム" in template and kinds["ニューゲーム"] == "system"

    def test_ascii_keys_dropped(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "EV001", [text_cmd("こんにちは")])]),
        })
        run_build(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        assert "こんにちは" in template
        assert "EV001" not in template

    def test_plugin_text_extracted(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        plugins = ('var $plugins =\n[\n  {"name": "MZ_Shop.js", "status": true,'
                   ' "description": "", "parameters": {"title": "ショップ"}}\n];\n')
        make_game(root, maps={"Map001.json": ("", [])}, plugins=plugins)
        run_build(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        kinds = load(out, "kinds.json")
        ctx = load(out, "context.json")
        assert "ショップ" in template and kinds["ショップ"] == "plugin"
        assert ctx["ショップ"]["where"] == "js/plugins.js / MZ_Shop.js / title"

    def test_no_plugins_flag(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        plugins = ('var $plugins =\n[\n  {"name": "MZ_Shop.js", "status": true,'
                   ' "description": "", "parameters": {"title": "ショップ"}}\n];\n')
        make_game(root, maps={"Map001.json": ("", [])}, plugins=plugins)
        run_build(root, out, "--no-plugins", monkeypatch=monkeypatch)
        template = load(out, "template.json")
        assert "ショップ" not in template

    def test_name_macros_file(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={"Map001.json": ("", [])},
                  actors=[{"id": 1, "name": "ゆうしゃ"}])
        run_build(root, out, monkeypatch=monkeypatch)
        macros = load(out, "name_macros.json")
        assert macros == {"\\N[1]": "ゆうしゃ", "\\P[1]": "ゆうしゃ"}

    def test_context_window(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [
                text_cmd("せりふ1"), text_cmd("せりふ2"), text_cmd("せりふ3")])]),
        })
        run_build(root, out, monkeypatch=monkeypatch)
        ctx = load(out, "context.json")
        block = "せりふ1\nせりふ2\nせりふ3"
        # where = human-readable "MAP001 / EV001 むらびと" (map name / event)
        assert "MAP001" in ctx[block]["where"]
        assert "むらびと" in ctx[block]["where"]
        # the window holds neighbouring dialogue lines (here the block itself)
        assert ctx[block]["window"]  # non-empty
        # every window entry is one of the block lines (no raw command text)
        assert all(w in ("せりふ1", "せりふ2", "せりふ3")
                   for w in ctx[block]["window"])

    def test_structure_tree_story_order(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={
            "Map002.json": ("まち", [ev(1, "むらびと", [text_cmd("こんにちは")])]),
            "Map001.json": ("はじまりの村", [ev(1, "むらびと", [
                text_cmd("おはよう")])]),
        })
        run_build(root, out, monkeypatch=monkeypatch)
        structure = load(out, "structure.json")
        maps = structure["maps"]
        # map id ordering: Map001 (id=1) then Map002 (id=2)
        assert [m["id"] for m in maps] == [1, 2]
        m1 = maps[0]
        assert m1["items"][0]["items"][0]["kind"] == "block"
        assert m1["items"][0]["items"][0]["key"] == "おはよう"

    def test_common_events_in_tree(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        make_game(root, maps={"Map001.json": ("", [])},
                  common_events=[{"id": 1, "name": "たいけん", "trigger": 0,
                                  "list": [text_cmd("こんにちは")]}])
        run_build(root, out, monkeypatch=monkeypatch)
        structure = load(out, "structure.json")
        assert structure["maps"][0]["id"] == -1  # CommonEvents marker
        assert structure["maps"][0]["items"][0]["items"][0]["key"] == "こんにちは"

    def test_template_sorted_by_count_then_key(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        # single-line blocks so "よくでる" repeats as its own key across maps
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "たんじゅん", [text_cmd("よくでる")]),
                                 ev(2, "そのた", [text_cmd("たまに")])]),
            "Map002.json": ("", [ev(1, "ふくざつ", [text_cmd("よくでる")])]),
        })
        run_build(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        keys = list(template.keys())
        # "よくでる" appears in two maps (count 2) -> sorts before "たまに" (1)
        assert keys[0] == "よくでる"
        assert "たまに" in keys

    def test_missing_data_dir_exits(self, tmp_path, monkeypatch, capsys):
        """A missing data/ dir is a failure: the tool returns 1 and reports it
        on stderr (tools return their exit code instead of raising)."""
        root = str(tmp_path / "game")
        out = str(tmp_path / "work")
        os.makedirs(root)
        monkeypatch.setattr("sys.argv", ["build_translation.py", root, out])
        assert bt.main() == 1
        assert "no data/" in capsys.readouterr().err

    def test_missing_data_dir_through_argv(self, tmp_path):
        """Same failure driven through the explicit-argv entry point."""
        root = str(tmp_path / "game")
        os.makedirs(root)
        assert bt.main([root, str(tmp_path / "work")]) == 1
