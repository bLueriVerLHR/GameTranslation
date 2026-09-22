#!/usr/bin/env python3
"""Unit tests for tools/extract_remaining_text.py - extraction of residual
Japanese (kana-bearing) display strings from an already-translated build, the
completion-pass entry point.

Contract under test (AGENTS.md + docs/translation.md):
- only kana-bearing strings are extracted; already-translated Chinese lines,
  pure-ASCII values and kanji-only strings are left out (that is what
  "remaining" means - kana is the canonical residual detector),
- pure control-code lines (\\M[ID] lookups, style switches) are never keys,
- plugin-tagged / JSON-blob notes and script comments are functional data,
  not display text - skipped,
- output follows STORY ORDER (MapInfos order -> map -> event -> page ->
  command -> CommonEvents -> System/DB), not filename order,
- context.json carries where/window; plugin parameter text from
  js/plugins.js (kind "plugin", --no-plugins off); name_macros.json maps
  \\N[x]/\\P[x] to actor names.
"""
import json
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import extract_remaining_text as ext  # noqa: E402


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def make_game(root, maps=None, common_events=None, actors=None, items=None,
              system=None, plugins=None, mapinfos_order=None):
    """Minimal synthetic MZ game.  `maps` = {fname: (map_name, events)}.
    `mapinfos_order` = [(map_id, map_name), ...] overrides the MapInfos.json
    id/name order (default: sorted filenames with ids 1..n) - lets a test put
    Map002 BEFORE Map001 to prove story order is taken from MapInfos."""
    data = os.path.join(root, "data")
    os.makedirs(data)
    os.makedirs(os.path.join(root, "js"))
    if mapinfos_order is None:
        mapinfos_order = [(i + 1, maps[f][0] or ("MAP%03d" % (i + 1)))
                          for i, f in enumerate(sorted(maps or {}))]
    mi = []
    for mid, mname in mapinfos_order:
        fname = "Map%03d.json" % mid
        mi.append({"id": mid, "name": mname, "expanded": True})
        write_json(os.path.join(data, fname), {
            "@name": fname.replace(".json", ""), "displayName": maps[fname][0],
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


def run_extract(root, out, *extra, monkeypatch):
    argv = ["extract_remaining_text.py", root, out] + list(extra)
    monkeypatch.setattr("sys.argv", argv)
    ext.main()


def load(out, name):
    with open(os.path.join(out, name), encoding="utf-8-sig") as f:
        return json.load(f)


class TestCollectorResidual:
    """The core 'remaining' semantic: only kana-bearing strings are keys."""

    def test_already_translated_chinese_skipped(self):
        # already-translated Chinese is not "remaining" - never re-extracted
        col = ext.Collector()
        col.add("你好", "block-line", "Map001", [])
        assert col.order == []
        assert col.kind_of == {}

    def test_pure_ascii_skipped(self):
        col = ext.Collector()
        col.add("OK", "block-line", "Map001", [])
        assert col.order == []

    def test_kanji_only_skipped(self):
        # kana is the residual detector: a kanji-only string has no kana so it
        # is not flagged as untranslated residual (matches the QC convention)
        col = ext.Collector()
        col.add("漢字", "block-line", "Map001", [])
        assert col.order == []

    def test_kana_extracted_with_context(self):
        col = ext.Collector()
        col.add("まだ日本語", "block-line", "Map001", ["前の台詞"])
        assert col.order == ["まだ日本語"]
        assert col.kind_of["まだ日本語"] == "block-line"
        assert col.context["まだ日本語"] == {"where": "Map001",
                                             "window": ["前の台詞"]}

    def test_pure_control_codes_skipped(self):
        # \M[ID] lines are ExternMessage lookup keys and MUST stay Japanese;
        # \V[n] / \C[n] style switches are not display text either
        col = ext.Collector()
        col.add("\\M[001]", "block-line", "Map001", [])
        col.add("\\V[5]", "block-line", "Map001", [])
        col.add("\\C[27]\\N[1]", "block-line", "Map001", [])
        assert col.order == []

    def test_short_text_with_control_code_kept(self):
        # a short string WITH real text besides control codes is still
        # extracted (only pure control-code lines are dropped)
        col = ext.Collector()
        col.add("あ\\N[1]", "block-line", "Map001", [])
        assert col.order == ["あ\\N[1]"]

    def test_dedup_and_story_order_preserved(self):
        col = ext.Collector()
        col.add("こんにちは", "block-line", "Map001", [])
        col.add("こんにちは", "block-line", "Map001", [])
        col.add("さようなら", "block-line", "Map001", [])
        assert col.order == ["こんにちは", "さようなら"]
        assert col.counts["block-line"] == 3

    def test_add_name_rejects_long(self):
        col = ext.Collector()
        col.add_name("むらびと")
        col.add_name("むらびとのなまえがとてもながい")  # 15 chars -> rejected
        assert col.name_cands == {"むらびと": 1}


class TestTalkLinesWindow:
    def test_talk_lines_401_405(self):
        cmds = [text_cmd("こんにちは"),
                {"code": 405, "indent": 0, "parameters": ["つづき"]}]
        tl = ext.talk_lines(cmds)
        assert [t for _, t in tl] == ["こんにちは", "つづき"]

    def test_talk_lines_101_speaker_prefix(self):
        cmds = [{"code": 101, "indent": 0,
                 "parameters": ["", 0, 0, 0, "ゆうしゃ"]}]
        assert ext.talk_lines(cmds) == [(0, "【ゆうしゃ】")]

    def test_talk_lines_102_choice_marker(self):
        cmds = [{"code": 102, "indent": 0,
                 "parameters": [["はい", "いいえ"], 0, 0, 0]}]
        assert ext.talk_lines(cmds) == [(0, "【选项】はい / いいえ")]

    def test_window_radius(self):
        cmds = [text_cmd("a"), {"code": 0, "indent": 0, "parameters": []},
                text_cmd("c")]
        tl = ext.talk_lines(cmds)
        assert ext.window_for(0, tl) == ["a", "c"]
        assert ext.window_for(2, tl) == ["a", "c"]


class TestWalkCommands:
    def test_block_line_with_window(self):
        col = ext.Collector()
        cmds = [text_cmd("こんにちは"), text_cmd("さようなら")]
        ext.walk_commands(cmds, col, "Map001 / EV001 むらびと")
        assert col.order == ["こんにちは", "さようなら"]
        assert col.context["こんにちは"]["window"] == ["こんにちは", "さようなら"]

    def test_choice_extracted(self):
        col = ext.Collector()
        cmds = [{"code": 102, "indent": 0,
                 "parameters": [["はい", "いいえ"], 0, 0, 0]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.kind_of["はい"] == "choice"
        assert col.kind_of["いいえ"] == "choice"

    def test_event_text_and_speaker_name_candidate(self):
        col = ext.Collector()
        cmds = [{"code": 101, "indent": 0,
                 "parameters": ["", 0, 0, 0, "ゆうしゃ"]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.kind_of["ゆうしゃ"] == "event-text"
        assert col.name_cands["ゆうしゃ"] == 1

    def test_script_line_quoted_kana_extracted(self):
        col = ext.Collector()
        cmds = [{"code": 355, "indent": 0,
                 "parameters": ["$gameMessage.add('こんにちは')"]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.kind_of["$gameMessage.add('こんにちは')"] == "script"

    def test_script_line_comment_not_extracted(self):
        # comments / identifiers without a quoted kana literal are never
        # display text
        col = ext.Collector()
        cmds = [{"code": 355, "indent": 0, "parameters": ["// ダメージ計算"]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.order == []

    def test_122_string_operand_extracted(self):
        # operandType == 4 stores a string literal in a variable, shown later
        # via \V[n] - the literal is display text
        col = ext.Collector()
        cmds = [{"code": 122, "indent": 0,
                 "parameters": [1, 1, 0, 4, "'こんにちは、ようこそ'"]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.kind_of["'こんにちは、ようこそ'"] == "script-var"

    def test_122_non_literal_operand_event_text(self):
        # operandType != 4 (not a string literal): the operand text is still a
        # display string and extracted when it carries kana
        col = ext.Collector()
        cmds = [{"code": 122, "indent": 0, "parameters": [1, 1, 0, 0, "ゆうしゃ"]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.kind_of["ゆうしゃ"] == "event-text"

    def test_357_arg_values_but_not_command_name(self):
        # params[2] is the Japanese command NAME (a functional lookup key the
        # plugin code matches) and is never extracted; kana-bearing VALUES in
        # the args dict are display text
        col = ext.Collector()
        cmds = [{"code": 357, "indent": 0,
                 "parameters": [0, 0, "文章表示", {"text": "こんにちは"}]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.kind_of.get("こんにちは") == "plugin-arg"
        assert "文章表示" not in col.order

    def test_408_help_extracted_directive_skipped(self):
        col = ext.Collector()
        cmds = [{"code": 408, "indent": 0,
                 "parameters": ["この文章は表示されない"]},
                {"code": 408, "indent": 0, "parameters": ["// コメント"]}]
        ext.walk_commands(cmds, col, "loc")
        assert col.kind_of.get("この文章は表示されない") == "help"
        assert "// コメント" not in col.order


class TestProcessDb:
    def test_display_fields(self):
        col = ext.Collector()
        ext.process_db({"name": "やくそう", "description": "HPをかいふくする",
                        "note": ""}, col, "Items.json")
        assert col.kind_of["やくそう"] == "db-name"
        assert col.kind_of["HPをかいふくする"] == "db-description"

    def test_note_plugin_tag_skipped(self):
        # plugin-parsed notes (<recipe> ...) are functional plugin data, not
        # display text - kept raw
        col = ext.Collector()
        ext.process_db({"note": "<recipe> 錬金レシピ </recipe>"}, col, "Items.json")
        assert col.order == []

    def test_note_plain_extracted(self):
        col = ext.Collector()
        ext.process_db({"note": "このアイテムの説明は日本語です"}, col, "Items.json")
        assert col.kind_of["このアイテムの説明は日本語です"] == "note"

    def test_note_long_json_blob_skipped(self):
        # embedded JSON material lists are functional, not display text
        col = ext.Collector()
        blob = '{"material": "' + "あ" * 90 + '"}'
        ext.process_db({"note": blob}, col, "Items.json")
        assert col.order == []

    def test_battle_event_list_processed(self):
        # battle-event command lists inside DB files (Troops pages) carry
        # display strings and must be walked like event lists
        col = ext.Collector()
        troop = {"id": 1, "pages": [{"conditions": {},
                                     "list": [text_cmd("こんにちは")]}]}
        ext.process_db(troop, col, "Troops.json")
        assert col.kind_of["こんにちは"] == "block-line"


class TestPluginAndMacros:
    def test_plugin_text_extracted(self, tmp_path):
        root = str(tmp_path / "game")
        plugins = ('var $plugins =\n[\n  {"name": "MZ_Shop.js", "status": true,'
                   ' "description": "", "parameters": {"title": "ショップ"}}\n];\n')
        make_game(root, plugins=plugins)
        col = ext.Collector()
        n = ext.extract_plugin_text(root, col)
        assert n == 1
        assert col.kind_of["ショップ"] == "plugin"
        assert col.context["ショップ"]["where"] == \
            "js/plugins.js / MZ_Shop.js / title"

    def test_plugin_text_no_file(self, tmp_path):
        root = str(tmp_path / "game")
        os.makedirs(root)
        assert ext.extract_plugin_text(root, ext.Collector()) == 0

    def test_build_name_macros(self, tmp_path):
        data = str(tmp_path / "data")
        os.makedirs(data)
        write_json(os.path.join(data, "Actors.json"),
                   [{"id": 1, "name": "ゆうしゃ"}, {"id": 2, "name": "まほうつかい"}])
        assert ext.build_name_macros(data) == {
            "\\N[1]": "ゆうしゃ", "\\P[1]": "ゆうしゃ",
            "\\N[2]": "まほうつかい", "\\P[2]": "まほうつかい"}

    def test_build_name_macros_missing_actors(self, tmp_path):
        data = str(tmp_path / "data")
        os.makedirs(data)
        assert ext.build_name_macros(data) == {}


class TestMain:
    def test_residual_extraction_story_order(self, tmp_path, monkeypatch):
        # Already-translated build: Chinese lines are NOT re-extracted, residual
        # Japanese lines are.  Story order follows MapInfos (Map002 listed
        # first), not filename sort.
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("はじまりの村", [ev(1, "むらびと", [
                text_cmd("你好"),                      # translated -> skip
                text_cmd("まだ翻訳されてない")])]),      # residual -> extract
            "Map002.json": ("まち", [ev(1, "しょうてん", [text_cmd("ようこそ")])]),
        }, mapinfos_order=[(2, "まち"), (1, "はじまりの村")])
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        kinds = load(out, "kinds.json")
        assert "まだ翻訳されてない" in template
        assert "ようこそ" in template
        assert "你好" not in template  # translated text never re-extracted
        assert kinds["まだ翻訳されてない"] == "block-line"
        # displayName + event names are extracted too
        assert "はじまりの村" in template and kinds["はじまりの村"] == "displayName"
        assert "まち" in template and kinds["まち"] == "displayName"
        assert "むらびと" in template and kinds["むらびと"] == "event-name"
        assert "しょうてん" in template and kinds["しょうてん"] == "event-name"
        # story order from MapInfos: Map002 (listed first) before Map001
        keys = list(template.keys())
        assert keys.index("ようこそ") < keys.index("まだ翻訳されてない")

    def test_context_window_and_where(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("はじまりの村", [ev(1, "むらびと", [
                text_cmd("せりふ1"), text_cmd("せりふ2"), text_cmd("せりふ3")])]),
        })
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        ctx = load(out, "context.json")
        # where = "<map name> / EV001 <event name>"
        assert "はじまりの村 / EV001 むらびと" in ctx["せりふ1"]["where"]
        # window = neighbouring dialogue lines (including the line itself)
        assert ctx["せりふ1"]["window"] == ["せりふ1", "せりふ2", "せりふ3"]
        assert ctx["せりふ2"]["window"] == ["せりふ1", "せりふ2", "せりふ3"]

    def test_common_events_extracted(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [])},
                  common_events=[{"id": 1, "name": "たいけん", "trigger": 0,
                                  "list": [text_cmd("こんにちは")]}])
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        ctx = load(out, "context.json")
        assert "こんにちは" in template
        assert "CommonEvents" in ctx["こんにちは"]["where"]

    def test_system_text_extracted(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [])},
                  system={"terms": {"basic": ["HP", "MP"]},
                          "gameTitle": "こんにちは",
                          "elements": ["", "ニューゲーム"],
                          "variables": ["スイッチA"]})
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        assert "こんにちは" in template
        assert "ニューゲーム" in template
        assert "スイッチA" in template
        assert "HP" not in template  # pure-ASCII system text is not residual

    def test_plugin_text_in_main(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        plugins = ('var $plugins =\n[\n  {"name": "MZ_Shop.js", "status": true,'
                   ' "description": "", "parameters": {"title": "ショップ"}}\n];\n')
        make_game(root, maps={"Map001.json": ("", [])}, plugins=plugins)
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        assert "ショップ" in template
        assert load(out, "kinds.json")["ショップ"] == "plugin"

    def test_no_plugins_flag(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        plugins = ('var $plugins =\n[\n  {"name": "MZ_Shop.js", "status": true,'
                   ' "description": "", "parameters": {"title": "ショップ"}}\n];\n')
        make_game(root, maps={"Map001.json": ("", [])}, plugins=plugins)
        out = str(tmp_path / "out")
        run_extract(root, out, "--no-plugins", monkeypatch=monkeypatch)
        assert "ショップ" not in load(out, "template.json")

    def test_name_macros_file(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [])},
                  actors=[{"id": 1, "name": "ゆうしゃ"}])
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        assert load(out, "name_macros.json") == {"\\N[1]": "ゆうしゃ",
                                                 "\\P[1]": "ゆうしゃ"}

    def test_names_output(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [
                text_cmd("こんにちは、げんきですか"),
                {"code": 101, "indent": 0,
                 "parameters": ["", 0, 0, 0, "ゆうしゃ"]}])]),
        }, actors=[{"id": 1, "name": "ゆうしゃ"}])
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        names = load(out, "names.json")
        assert "ゆうしゃ" in names       # from Actors.json + 101 speaker
        assert "こんにちは、げんきですか" not in names  # not name-like

    def test_maps_not_in_mapinfos_defensive(self, tmp_path, monkeypatch):
        # MapInfos.json exists but lists no maps -> the defensive pass still
        # walks the map files found on disk
        root = str(tmp_path / "game")
        data = os.path.join(root, "data")
        os.makedirs(data)
        os.makedirs(os.path.join(root, "js"))
        write_json(os.path.join(data, "MapInfos.json"), [])
        write_json(os.path.join(data, "Map002.json"),
                   {"@name": "Map002", "displayName": "まち",
                    "events": [ev(1, "しょうてん", [text_cmd("ようこそ")])]})
        write_json(os.path.join(data, "CommonEvents.json"), [])
        write_json(os.path.join(data, "Actors.json"), [])
        write_json(os.path.join(data, "System.json"), {})
        write_json(os.path.join(data, "Items.json"), [])
        with open(os.path.join(root, "js", "plugins.js"), "w",
                  encoding="utf-8") as f:
            f.write("var $plugins = [];\n")
        out = str(tmp_path / "out")
        run_extract(root, out, monkeypatch=monkeypatch)
        template = load(out, "template.json")
        assert "ようこそ" in template
        assert "まち" not in template  # defensive pass skips displayName
