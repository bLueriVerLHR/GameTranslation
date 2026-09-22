#!/usr/bin/env python3
"""Tests for the v2 translation toolkit (`translation/`).

Every fixture is a synthetic MV tree: the point is to pin the *contract*
(stable ids, story order, raw-text library, the four gates) without shipping
any game's data.
"""
import json
import os
import re

import pytest

from translation import cli, codes, mvkeys, prefill, rawlib, workspace

MAP_TEXT = "\u3010\u30e6\u30ad\u3011\u304a\u306f\u3088\u3046\\c[1]\u3002\n\u4e8c\u884c\u76ee\u3067\u3059\u3002"
SECOND_TEXT = "\\nc<\u30df\u30ab>\u3084\u3042\\{\u5927\u304d\u3044\\}"
MACRO_TEXT = "\\N[1]\u306e\u51fa\u756a\u3060\u3002"


def _dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def make_game(root, plugins=True, js=True):
    """A minimal but representative MV data tree."""
    data = os.path.join(root, "data")
    _dump(os.path.join(data, "MapInfos.json"), [
        {"id": 1, "name": "Map1", "order": 1, "parentId": 0, "expanded": False},
        {"id": 2, "name": "Map2", "order": 2, "parentId": 0, "expanded": False},
    ])
    _dump(os.path.join(data, "Map001.json"), {
        "displayName": "\u8857",
        "events": [None, {"id": 1, "name": "Ev1", "pages": [{"list": [
            [101, 0, "", 0, 0],
            [401, 0, MAP_TEXT],
            [401, 0, SECOND_TEXT],
            [401, 0, MACRO_TEXT],
            [102, 0, ["\u306f\u3044", "\u3044\u3044\u3048"], 0, 0],
            [402, 0, 1, "\u306f\u3044"],
            [405, 0, "\u30b9\u30af\u30ed\u30fc\u30eb\u6587"],
            [108, 0, "\u30b3\u30e1\u30f3\u30c8\u306f\u7ffb\u3055\u306a\u3044"],
            [355, 0, "$gameVariables.setValue(1, 2)"],
            [655, 0, "\u30b9\u30af\u30ea\u30d7\u30c8\u7d9a\u304d"],
            [401, 0, "\\px[200]\u30c6\u30b9\u30c8\\c[1]\u3002"],
        ]}]}]
    })
    _dump(os.path.join(data, "Map002.json"), {"displayName": "", "events": []})
    _dump(os.path.join(data, "CommonEvents.json"), [
        {"id": 1, "name": "CE1", "list": [[401, 0, "\u5171\u901a\u30a4\u30d9\u30f3\u30c8"]]},
    ])
    _dump(os.path.join(data, "Troops.json"), [
        {"id": 1, "name": "\u30c8\u30eb\u30fc\u30d7", "pages": [{"list": [
            [401, 0, "\u6226\u95d8\u4e2d\u306e\u53f0\u8a9e"]]}]},
    ])
    _dump(os.path.join(data, "System.json"), {
        "gameTitle": "\u30c6\u30b9\u30c8\u4f5c\u54c1",
        "currencyUnit": "G",
        "terms": {"basic": ["\u30ec\u30d9\u30eb"],
                  "commands": {"fight": "\u6226\u3046"},
                  "messages": {"actorDamage": "%1\u306f%2\u3092\u53d7\u3051\u305f"}},
    })
    _dump(os.path.join(data, "Actors.json"), [
        {"id": 1, "name": "\u30e6\u30ad", "nickname": "\u30e6\u30ad\u3061\u3083\u3093"},
    ])
    _dump(os.path.join(data, "Items.json"), [
        None,
        {"id": 1, "name": "\u30dd\u30fc\u30b7\u30e7\u30f3",
         "description": "\u56de\u5fa9\u3059\u308b",
         "note": "<TE:\u30c6\u30f3\u30d7\u30ec>"},
    ])
    if plugins:
        os.makedirs(os.path.join(root, "js"), exist_ok=True)
        with open(os.path.join(root, "js", "plugins.js"), "w",
                     encoding="utf-8", newline="\n") as handle:
            handle.write("var $plugins =\n[\n")
            handle.write(json.dumps({"name": "TestPlugin", "status": True,
                                     "description": "d",
                                     "parameters": {"Label": "\u30e9\u30d9\u30eb",
                                                    "Path": "img/x.png",
                                                    "Code": "$dataSystem.x"}},
                                    ensure_ascii=False))
            handle.write("\n];\n")
    if js:
        path = os.path.join(root, "js", "rpg_windows.js")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("Window_Base.prototype.processEscapeCharacter = "
                         "function(code, text) {\n"
                         "    switch (code) {\n"
                         "    case 'C':\n"
                         "        break;\n"
                         "    case '{':\n"
                         "        break;\n"
                         "    }\n};\n")
        path = os.path.join(root, "js", "plugins", "YEP_MessageCore.js")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("/*:\n"
                         " * @help\n"
                         " * \\PX[200]  pixel offset for the text\n"
                         " * \\NC<x>   creates a name box\n"
                         " */\n"
                         "case 'PX':\n"
                         "case 'NC':\n")
    return root


@pytest.fixture()
def game(tmp_path):
    return make_game(str(tmp_path / "game"))


@pytest.fixture()
def work(tmp_path, game):
    return str(tmp_path / "work")


def by_id(work_dir):
    return {entry["id"]: entry for entry in mvkeys.load_keys(work_dir)}


# ---------------------------------------------------------------- codes

def test_parse_codes_and_keys():
    tokens = codes.parse_codes("\\c[1]\u3042\\px[200]\\{\\.\\nc<\u30e6>")
    assert tokens == ["\\c[1]", "\\px[200]", "\\{", "\\.", "\\nc<\u30e6>"]
    assert [codes.code_key(t) for t in tokens] == ["C", "PX", "{", ".", "NC"]
    assert codes.parse_codes("") == []


def test_split_keep_codes_preserves_everything():
    text = "\u3042\\c[1]\u3044\\{ok\\}"
    pieces = codes.split_keep_codes(text)
    assert "".join(piece for _, piece in pieces) == text
    assert [piece for is_code, piece in pieces if is_code] == ["\\c[1]", "\\{", "\\}"]
    assert codes.split_keep_codes("") == []


def test_scan_js_and_inventory(game):
    found = codes.scan_js(game)
    assert "C" in found and "PX" in found
    assert not any("rpg_windows.js" in site for site in found["PX"]["sites"])
    assert any("YEP_MessageCore.js" in site for site in found["PX"]["sites"]), found["PX"]
    assert any("pixel offset" in doc for doc in found["PX"]["docs"])
    merged = codes.inventory(game, {"\\px[200]": 3, "\\c[1]": 1})
    assert merged["PX"]["count"] == 3
    assert merged["PX"]["documented"] is True
    path = codes.write_markdown(str(os.path.join(game, "codes.md")), merged)
    text = open(path, encoding="utf-8").read()
    assert "`\\PX`" in text and "`\\C`" in text


# ---------------------------------------------------------------- keys

def test_extract_reads_object_shaped_commands(tmp_path):
    """Real builds can save commands as named objects instead of arrays."""
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map002.json")
    _dump(path, {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
        "pages": [{"list": [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
            {"code": 401, "indent": 0, "parameters": ["\u304a\u306f\u3088\u3046"]},
            {"code": 102, "indent": 0,
             "parameters": [["\u306f\u3044", "\u3044\u3044\u3048"], 0, 0]},
            {"code": 108, "indent": 0, "parameters": ["\u30b3\u30e1\u30f3\u30c8"]},
        ]}]}]})
    work = str(tmp_path / "work")
    stats = mvkeys.extract(root, work)
    entries = {entry["id"]: entry for entry in mvkeys.load_keys(work)
               if entry["kind"] == "map" and "Map002" in entry["id"]}
    assert entries["data/Map002.json#events[1].pages[0].list[1]"
                   ".parameters[0]"]["ja"] == "\u304a\u306f\u3088\u3046"
    assert entries["data/Map002.json#events[1].pages[0].list[2]"
                   ".parameters[0][1]"]["ja"] == "\u3044\u3044\u3048"
    assert len(entries) == 3
    assert stats["skipped"].get("malformed") is None


def test_extract_covers_name_plates_branch_labels_and_plugin_text(tmp_path):
    """The extended extractor: 101 name plates, 402 branch labels, 357 args.

    A build that only looked at parameters[0] silently lost ~1,800 name plates
    and every plugin window label, so these paths are pinned here.
    """
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map003.json")
    _dump(path, {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
        "pages": [{"list": [
            {"code": 101, "indent": 0,
             "parameters": ["", 0, 0, 2, "\u30c6\u30f3\u30b0"]},
            {"code": 401, "indent": 0, "parameters": ["\u3064\u3044\u305f"]},
            {"code": 102, "indent": 0,
             "parameters": [["\u306f\u3044", "\u3044\u3044\u3048"], 0, 0]},
            {"code": 402, "indent": 1, "parameters": [0, "\u306f\u3044"]},
            {"code": 402, "indent": 1, "parameters": [1, "\u3044\u3044\u3048"]},
            {"code": 357, "indent": 0,
             "parameters": ["LL_VariableWindow", "hideWindow",
                            "\u30a6\u30a3\u30f3\u30c9\u30a6\u3092\u6d88\u53bb",
                            {"windowId": "1",
                             "messageText": "\u53eb\u3073\u58f0\u304c\u97ff\u304f\u2026\u2026\u3002"}]},
            {"code": 657, "indent": 0, "parameters": ["\u30a6\u30a3\u30f3\u30c9\u30a6\u756a\u53f7 = 1"]},
            {"code": 357, "indent": 0,
             "parameters": ["SomePlugin", "doThing", "hideWindow", "true"]},
            {"code": 108, "indent": 0, "parameters": ["\u30b3\u30e1\u30f3\u30c8"]},
            {"code": 408, "indent": 0, "parameters": ["\u3053\u306e\u5f8c"]},
        ]}]}]})
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    entries = {entry["id"] for entry in mvkeys.load_keys(work)
               if "Map003" in entry["id"]}

    prefix = "data/Map003.json#events[1].pages[0].list[%d]"
    assert prefix % 0 + ".parameters[4]" in entries          # name plate
    assert prefix % 3 + ".parameters[1]" in entries          # branch label
    assert prefix % 4 + ".parameters[1]" in entries
    assert prefix % 5 + ".parameters[3].messageText" in entries   # nested field
    # parameters[2] is the command's @text and 657 is the editor's echo of the
    # 357 arguments: command357 passes the plugin parameters[3] only, and no
    # engine version implements command657, so neither is ever displayed.
    assert prefix % 5 + ".parameters[2]" not in entries
    assert prefix % 6 + ".parameters[0]" not in entries
    # identifiers and comments are not text
    assert prefix % 5 + ".parameters[0]" not in entries      # plugin name
    assert prefix % 5 + ".parameters[1]" not in entries      # command name
    assert prefix % 7 + ".parameters[2]" not in entries      # 'hideWindow'
    assert prefix % 7 + ".parameters[3]" not in entries      # 'true'
    assert prefix % 8 + ".parameters[0]" not in entries      # comment
    assert prefix % 9 + ".parameters[0]" not in entries      # comment cont.


def test_extract_skips_editor_only_plugin_command_text(tmp_path):
    """357's ``@text`` and the 657 echo are editor-only - never displayed.

    ``Game_Interpreter.prototype.command357`` calls
    ``PluginManager.callCommand(this, pluginName, params[1], params[3])``: the
    @text slot (index 2) is not handed on, and an unhandled code is skipped by
    ``executeCommand``, so 657 - the editor's wrapped "argName = value" echo,
    one entry per argument - never reaches the player either.  Extracting them
    cost 26,355 of 55,811 keys (47%) in a real MZ build, and a translation of
    an argument *name* would misdirect the plugin's argument lookup.  A build
    without the @text slot (an object at index 2) still has to be scanned.
    """
    root = make_game(str(tmp_path / "game"))
    choices = "[" + json.dumps(
        json.dumps({"label": "\u3044\u3044\u3048"}, ensure_ascii=False),
        ensure_ascii=False) + "]"
    path = os.path.join(root, "data", "Map005.json")
    _dump(path, {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
        "pages": [{"list": [
            {"code": 357, "indent": 0,
             "parameters": ["LL_GalgeChoiceWindow", "showChoice",
                            "\u9078\u629e\u80a2\u306e\u8868\u793a",
                            {"messageText": "\u958b\u304f\uff1f",
                             "choices": choices}]},
            {"code": 657, "indent": 0,
             "parameters": ["\u30ad\u30e3\u30f3\u30bb\u30eb\u8a31\u53ef = true"]},
            {"code": 357, "indent": 0,
             "parameters": ["NoLabelPlugin", "doThing",
                            {"text": "\u3053\u3093\u306b\u3061\u306f"}]},
        ]}]}]})
    work = str(tmp_path / "work")
    stats = mvkeys.extract(root, work)
    ids = {entry["id"] for entry in mvkeys.load_keys(work)}

    prefix = "data/Map005.json#events[1].pages[0].list[%d]"
    assert prefix % 0 + ".parameters[3].messageText" in ids
    assert prefix % 0 + ".parameters[3].choices" in ids
    assert prefix % 0 + ".parameters[2]" not in ids          # command @text
    assert prefix % 1 + ".parameters[0]" not in ids          # 657 editor echo
    assert prefix % 2 + ".parameters[2].text" in ids         # no @text slot
    assert stats["skipped"]["plugin-continuation"] == 1


def test_extract_covers_db_battle_messages_and_profile(tmp_path):
    """Skills/Items messages and Actors.profile are displayed text."""
    root = make_game(str(tmp_path / "game"))
    _dump(os.path.join(root, "data", "Skills.json"), [None, {
        "id": 1, "name": "\u653b\u6483", "description": "",
        "message1": "%1\u306e\u653b\u6483\uff01",
        "message2": "\u30ad\u30e2\u3044\u7c98\u6db2\u304c\u5439\u304d\u304b\u304b\u308b\uff01",
        "note": "<TE:\u30c6\u30f3\u30d7\u30ec>",
    }])
    _dump(os.path.join(root, "data", "Actors.json"), [None, {
        "id": 1, "name": "\u30e6\u30ad", "nickname": "",
        "profile": "\u5929\u8cc7\u82f1\u9081\u306e\u4ed9\u4eba\u306b\u3057\u3066\u3001\u8056\u5fb3\u592a\u5b50\u2661",
    }])
    _dump(os.path.join(root, "data", "Animations.json"), [None, {
        "id": 1, "name": "\u6253\u6483/\u30a8\u30d5\u30a7\u30af\u30c8",
    }])
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    entries = {entry["id"] for entry in mvkeys.load_keys(work)}
    assert "data/Skills.json#[1].message1" in entries
    assert "data/Skills.json#[1].message2" in entries
    assert "data/Actors.json#[1].profile" in entries
    assert "data/Animations.json#[1].name" not in entries   # editor-only


def test_extract_covers_switch_and_variable_names(tmp_path):
    """Variable/switch names are displayed by variable-window plugins."""
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "System.json")
    data = json.load(open(path, encoding="utf-8"))
    data["switches"] = [None, "\u30a8\u30ed\u30a4\u30d9\u30f3\u30c8\uff11"]
    data["variables"] = [None, "\u30de\u30f3\u30ba\u30ea\u306e\u56de\u6570"]
    _dump(path, data)
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    entries = {entry["id"]: entry for entry in mvkeys.load_keys(work)}
    assert entries["data/System.json#switches[1]"]["ja"] == "\u30a8\u30ed\u30a4\u30d9\u30f3\u30c8\uff11"
    assert entries["data/System.json#variables[1]"]["ja"] == "\u30de\u30f3\u30ba\u30ea\u306e\u56de\u6570"


def test_extract_covers_halfwidth_katakana_only_lines(tmp_path):
    """A line written only in halfwidth katakana is still Japanese text."""
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map004.json")
    _dump(path, {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
        "pages": [{"list": [
            {"code": 401, "indent": 0,
             "parameters": ["\uff8c\uff9e\uff80\uff8c\uff9e\uff80\u2026\u2026\u3002"]},
        ]}]}]})
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    entries = {entry["id"] for entry in mvkeys.load_keys(work) if "Map004" in entry["id"]}
    assert "data/Map004.json#events[1].pages[0].list[0].parameters[0]" in entries


def test_extract_tolerates_plugin_shaped_entries(tmp_path):
    """Real data can hold non-command entries (plugins write their own)."""
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map001.json")
    data = json.load(open(path, encoding="utf-8"))
    data["events"][1]["pages"][0]["list"] = [
        {"plugin": "wrote-this"},
        [401],
        [401, 0, "\u3042\u3044\u3046"],
    ]
    _dump(path, data)
    work = str(tmp_path / "work")
    stats = mvkeys.extract(root, work)
    keys = mvkeys.load_keys(work)
    assert [entry["ja"] for entry in keys if entry["kind"] == "map"] == ["\u3042\u3044\u3046"]
    assert stats["skipped"]["malformed"] == 2


def test_extract_story_order_and_kinds(work, game):
    stats = mvkeys.extract(game, work)
    keys = mvkeys.load_keys(work)
    assert stats["keys"] == len(keys) > 10
    assert [entry["seq"] for entry in keys] == list(range(len(keys)))
    kinds = [entry["kind"] for entry in keys]
    order = [kinds.index(kind) for kind in
             ("map", "common", "troop", "db", "plugin")]
    assert order == sorted(order), order
    assert kinds[-1] == "plugin"
    for name in ("keys.jsonl", "stats.json", "names_candidates.json",
                 "control_codes.md"):
        assert os.path.isfile(os.path.join(work, name))


def test_extract_finds_dialogue_choices_and_ui(work, game):
    mvkeys.extract(game, work)
    entries = by_id(work)
    assert entries["data/Map001.json#events[1].pages[0].list[1]"
                   ".parameters[0]"]["ja"] == MAP_TEXT
    assert entries["data/Map001.json#events[1].pages[0].list[4]"
                   ".parameters[0][1]"]["ja"] == "\u3044\u3044\u3048"
    assert entries["data/Map001.json#events[1].pages[0].list[6]"
                   ".parameters[0]"]["ja"] == "\u30b9\u30af\u30ed\u30fc\u30eb\u6587"
    assert entries["data/Map001.json#displayName"]["ja"] == "\u8857"
    assert entries["data/System.json#gameTitle"]["ja"] == "\u30c6\u30b9\u30c8\u4f5c\u54c1"
    assert entries["data/Items.json#[1].description"]["ja"] == "\u56de\u5fa9\u3059\u308b"


def test_extract_skips_functional_and_editor_text(work, game):
    mvkeys.extract(game, work)
    entries = by_id(work)
    ids = " ".join(entries)
    assert "#events[1].pages[0].list[7]" not in ids      # 108 comment
    assert "#events[1].pages[0].list[8]" not in ids      # 355 script
    assert "MapInfos" not in ids                         # editor-only names
    assert "CommonEvents.json#[0].name" not in ids
    assert "#note" not in ids                            # plugin commands
    stats = json.load(open(os.path.join(work, "stats.json"), encoding="utf-8"))
    assert stats["skipped"]
    assert entries["js/plugins.js#[0].parameters.Label"]["ja"] == "\u30e9\u30d9\u30eb"
    assert "js/plugins.js#[0].parameters.Path" not in entries
    assert "js/plugins.js#[0].parameters.Code" not in entries


def test_extract_context_and_speaker(work, game):
    mvkeys.extract(game, work)
    entries = by_id(work)
    first = entries["data/Map001.json#events[1].pages[0].list[1].parameters[0]"]
    second = entries["data/Map001.json#events[1].pages[0].list[2].parameters[0]"]
    assert first["speaker"] == "\u30e6\u30ad"
    assert second["speaker"] == "\u30df\u30ab"
    assert first["prev"] == []
    assert second["ja"] in first["next"]
    assert first["ja"] in second["prev"]


def test_speaker_follows_the_message_window(tmp_path):
    """A name box labels its whole message window, wherever it sits in it."""
    root = make_game(str(tmp_path / "game"))
    _dump(os.path.join(root, "data", "Map002.json"),
          {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
           "pages": [{"list": [
               {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
               {"code": 401, "indent": 0, "parameters": ["\u3042\u3044\u3046"]},
               {"code": 401, "indent": 0,
                "parameters": ["\u3046\u3048\u304a\\nc<\u30a2\u30eb>"]},
               {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
               {"code": 401, "indent": 0, "parameters": ["\u304b\u304d\u304f"]},
               {"code": 401, "indent": 0,
                "parameters": ["\u3051\u3053\\nc<\u30d9\u30eb>"]},
               {"code": 401, "indent": 0, "parameters": ["\u3055\u3057\u3059"]},
           ]}]}]})
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    speakers = [entry["speaker"] for entry in mvkeys.load_keys(work)
                if "Map002" in entry["id"]]
    assert speakers[0] == "\u30a2\u30eb"      # box at the end of window 1
    assert speakers[1] == "\u30a2\u30eb"      # same window
    assert speakers[2] == "\u30d9\u30eb"      # box mid-window, window 2
    assert speakers[3] == "\u30d9\u30eb"      # carried to the rest of window 2
    assert "_window" not in mvkeys.load_keys(work)[0]


def test_names_candidates_include_macros(work, game):
    mvkeys.extract(game, work)
    names = json.load(open(os.path.join(work, "names_candidates.json"),
                              encoding="utf-8"))
    assert "\u30e6\u30ad" in names
    assert "macro" in names["\u30e6\u30ad"]["sources"]
    assert "namebox" in names["\u30df\u30ab"]["sources"]


def test_ids_are_stable_across_extraction(work, game):
    mvkeys.extract(game, work)
    first = sorted(by_id(work))
    mvkeys.extract(game, work)
    assert sorted(by_id(work)) == first


def test_missing_data_dir_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        mvkeys.extract(str(tmp_path / "empty"), str(tmp_path / "work"))


def test_is_candidate_rules():
    assert mvkeys.is_candidate("\u3042\u3044\u3046", "map") is True
    # kanji-only text is real text (location banners, labels, battle messages)
    assert mvkeys.is_candidate("\u653b\u6483", "map") is True
    assert mvkeys.is_candidate("\u5834\u6240\uff1a\u8a3a\u5bdf\u5ba4", "map") is True
    assert mvkeys.is_candidate("", "db") is False
    assert mvkeys.is_candidate("img\u30c6.png", "db") is False
    assert mvkeys.is_candidate("$dataSystem.x;", "plugin") is False


# ---------------------------------------------------------------- library

def test_library_roundtrip_last_wins(tmp_path):
    path = str(tmp_path / "lib.txt")
    rawlib.append_block(path, "a", "\u4e00\u884c\u76ee\n\u4e8c\u884c\u76ee")
    rawlib.append_block(path, "b", "\\c[1]\u4e09\u884c\u76ee")
    rawlib.append_block(path, "a", "\u6539\u6210\u8fd9\u4e2a")
    values = rawlib.read_library(path)
    assert values["b"] == "\\c[1]\u4e09\u884c\u76ee"
    assert values["a"] == "\u6539\u6210\u8fd9\u4e2a"
    rawlib.write_library(path, values)
    assert rawlib.read_library(path) == values


def test_library_rejects_text_before_header(tmp_path):
    path = str(tmp_path / "lib.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\u6ca1\u6709\u5934\u884c\n")
    with pytest.raises(ValueError):
        rawlib.read_library(path)


def test_library_keeps_trailing_newlines(tmp_path):
    """A trailing newline in a value is a character, not padding.

    MZ data has text that ends with a newline (item descriptions), and the
    line-break gate compares newline counts - if the reader ate the newline,
    such a key could never be given a matching value (10 keys of one real MZ
    build were unappendable, which blocked the coverage gate as well).
    """
    path = str(tmp_path / "lib.txt")
    cases = {"one": "\u4e00\u884c\u76ee\n", "two": "\u4e00\u884c\u76ee\n\u4e8c\u884c\u76ee\n",
             "none": "\u65e0\u6362\u884c", "blank": "\u5c3e\u90e8\u7a7a\u884c\n\n"}
    for key, text in cases.items():
        rawlib.append_block(path, key, text)
    values = rawlib.read_library(path)
    assert values == cases
    # the rewrite path (rewrites.jsonl application) must round-trip too
    rawlib.write_library(path, values)
    assert rawlib.read_library(path) == cases


def test_append_accepts_a_source_that_ends_with_a_newline(work, game):
    """Regression: the line-break gate used to reject this value forever."""
    mvkeys.extract(game, work)
    keys_path = os.path.join(work, "keys.jsonl")
    rows = [json.loads(line) for line
            in open(keys_path, encoding="utf-8") if line.strip()]
    rows[0]["ja"] = rows[0]["ja"] + "\n"
    with open(keys_path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    batch = os.path.join(work, "tail.batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n{}\n".format(rows[0]["id"], rows[0]["ja"]))
    report = rawlib.append_batch(work, batch)
    assert report["problems"] == []
    assert report["added"] == 1
    values = rawlib.read_library(os.path.join(work, rawlib.LIBRARY_NAME))
    assert values[rows[0]["id"]] == rows[0]["ja"]


def test_append_block_rejects_at_signs(tmp_path):
    with pytest.raises(ValueError):
        rawlib.append_block(str(tmp_path / "lib.txt"), "a@@@b", "x")


def _fill_library(work_dir, transform=None):
    keys = mvkeys.load_keys(work_dir)
    path = os.path.join(work_dir, rawlib.LIBRARY_NAME)
    for entry in keys:
        text = entry["ja"]
        if transform:
            text = transform(entry, text)
        rawlib.append_block(path, entry["id"], text)
    return keys


def _neutral(entry, text):
    """Keep every control code, drop every kana (a gate-clean translation).

    Text inside a code parameter is displayed (a name box), so a gate-clean
    value has to translate that too - numeric arguments stay untouched.
    """
    out = []
    for is_code, piece in codes.split_keep_codes(text):
        if not is_code:
            out.append(codes.KANA_RE.sub("\u597d", piece))
        elif codes.has_text_parameter(piece):
            parameter = codes.parameter_of(piece)
            out.append(piece.replace(parameter,
                                     codes.KANA_RE.sub("\u597d", parameter)))
        else:
            out.append(piece)
    return "".join(out)


def _keep_namebox(entry, text):
    """Neutral text but the original code parameters (a Japanese name box)."""
    return "".join(piece if is_code else codes.KANA_RE.sub("\u597d", piece)
                   for is_code, piece in codes.split_keep_codes(text))


def test_to_json_escapes_and_reports_conflicts(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, lambda entry, text: "\u8bd1\u6587" + text)
    report = rawlib.to_json(work)
    assert report["translated"] == report["keys"]
    data = json.load(open(os.path.join(work, "translated.json"),
                             encoding="utf-8"))
    assert data[MAP_TEXT] == "\u8bd1\u6587" + MAP_TEXT
    assert "\n" in data[MAP_TEXT]            # real newline survived as JSON
    ids = json.load(open(os.path.join(work, "translated_ids.json"),
                            encoding="utf-8"))
    assert len(ids) == report["keys"]
    # same source, different translation -> reported, first one kept
    entry = mvkeys.load_keys(work)[0]
    rawlib.append_block(os.path.join(work, rawlib.LIBRARY_NAME), entry["id"],
                        "\u5176\u4ed6\u8bd1\u6cd5")
    assert rawlib.to_json(work)["conflicts"] == []


def test_safe_replace_is_idempotent_when_old_sits_inside_new():
    """The doubling guard: ``old`` occurring inside ``new`` must not re-apply."""
    assert rawlib.safe_replace("\u6742\u9c7c", "\u6742\u9c7c", "\u6742\u9c7c\u5251") == "\u6742\u9c7c\u5251"
    assert rawlib.safe_replace("\u6742\u9c7c\u5251", "\u6742\u9c7c", "\u6742\u9c7c\u5251") == "\u6742\u9c7c\u5251"
    # only the names still in the old form are converted
    assert (rawlib.safe_replace("\u6742\u9c7c\u5251\u548c\u6742\u9c7c", "\u6742\u9c7c", "\u6742\u9c7c\u5251")
            == "\u6742\u9c7c\u5251\u548c\u6742\u9c7c\u5251")
    # ``new`` inside ``old`` stays a plain replacement, else the rule could
    # never shrink a value (and the old form no longer matches once converted)
    assert rawlib.safe_replace("\u5ae9\u7a74\u6479\u672c", "\u5ae9\u7a74\u6479\u672c", "\u5ae9\u7a74") == "\u5ae9\u7a74"
    assert rawlib.safe_replace("x", "a", "a") == "x"


def test_structure_problems_guards_nested_json_parameters():
    """A JSON-valued plugin parameter may only change its strings.

    LL_GalgeChoiceWindow-style choice lists are a JSON array whose items are
    JSON objects serialised as strings (``["{\\"label\\":...}"]``).  A
    translation that drops a bracket makes the plugin's ``JSON.parse`` throw and
    the event stops there - the player never sees the choice window.  Numbers,
    keys and nesting have to survive; only the string leaves may change.
    """
    def wrap(inner):
        return json.dumps([json.dumps(inner, ensure_ascii=False)],
                          ensure_ascii=False)

    source = wrap({"label": "\u6226\u3046", "switchId": "0"})
    good = wrap({"label": "\u6218\u6597", "switchId": "0"})
    assert rawlib.structure_problems(source, good) == []
    # a lost bracket, a renamed key and a retyped value are all caught
    assert rawlib.structure_problems(source, good[:-1]) != []
    assert rawlib.structure_problems(
        source, wrap({"label": "\u6218\u6597", "switchID": "0"})) != []
    assert rawlib.structure_problems(
        source, wrap({"label": "\u6218\u6597", "switchId": 0})) != []
    # prose is never judged, and text that merely starts with a bracket but is
    # not JSON stays out of this gate as well
    assert rawlib.structure_problems("\u3053\u3093\u306b\u3061\u306f", "\u4f60\u597d") == []
    assert rawlib.structure_problems("[\u6ce8\u610f]\u3053\u3093\u306b\u3061\u306f",
                                     "[\u6ce8\u610f]\u4f60\u597d") == []
    assert rawlib.structure_problems("123", "123") == []


def test_prefill_harvests_only_exact_matches(tmp_path):
    """A runtime dictionary seeds the library by exact match, never by fragment.

    MTool dictionaries key on displayed text: control codes are gone and the
    entries include bare fragments.  Harvesting a fragment into a longer line is
    the documented way to destroy sentences, so only (a) the exact key and
    (b) the key with its outer codes stripped are accepted - and the value is
    re-wrapped in those codes so the control-code gate still passes.
    """
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map007.json")
    _dump(path, {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
        "pages": [{"list": [
            {"code": 401, "indent": 0, "parameters": ["\u304a\u306f\u3088\u3046"]},
            {"code": 401, "indent": 0,
             "parameters": ["\\C[27]\u3042\u3063\\C[0]"]},
            {"code": 401, "indent": 0,
             "parameters": ["\u3068\u3066\u3082\u9577\u3044\u53f0\u8a5e\u3067\u3059"]},
        ]}]}]})
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    mine = {entry["id"] for entry in mvkeys.load_keys(work)
            if "Map007" in entry["id"]}
    dictionary = tmp_path / "runtime.json"
    body = json.dumps({
        "\u304a\u306f\u3088\u3046": "\u65e9\u4e0a\u597d",
        "\u3042\u3063": "\u554a\u554a",
        "\u53f0\u8a5e": "\u53f0\u8bcd",
    }, ensure_ascii=False, indent=1).split("\n")[1:-1]
    with open(dictionary, "w", encoding="utf-8", newline="\n") as handle:
        # MTool dictionaries carry leading ``//`` comments - not valid JSON
        handle.write("{\n// a repacker's comment line\n" + "\n".join(body) + "\n}\n")

    values, report = prefill.harvest(work, str(dictionary), allow_ids=mine)
    by_id = {entry["id"]: entry["ja"] for entry in mvkeys.load_keys(work)}
    got = {by_id[key_id]: text for key_id, text in values.items()}
    assert got["\u304a\u306f\u3088\u3046"] == "\u65e9\u4e0a\u597d"
    assert got["\\C[27]\u3042\u3063\\C[0]"] == "\\C[27]\u554a\u554a\\C[0]"
    # the fragment entry must NOT be spliced into the longer line
    assert "\u3068\u3066\u3082\u9577\u3044\u53f0\u8a5e\u3067\u3059" not in got
    assert report["harvested"] == 2 and report["missed"] == 1
    assert report["lookup"]["stripped"] == 1

    batch = prefill.write_batch(os.path.join(work, "prefill.batch.txt"), values)
    assert rawlib.append_batch(work, batch)["added"] == 2


def test_prefill_rejects_candidates_that_break_a_gate(tmp_path):
    """A harvested value that fails a gate is dropped, not pushed into the batch.

    A dictionary is machine output: some entries leave kana behind, and a
    mid-line control code cannot be re-wrapped at all.  Both are filtered here
    (so a 25,000-entry harvest does not fail as one all-or-nothing batch) and
    reported for the translator to pick up.
    """
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map008.json")
    _dump(path, {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
        "pages": [{"list": [
            {"code": 401, "indent": 0, "parameters": ["\u3053\u3093\u306b\u3061\u306f"]},
            {"code": 401, "indent": 0,
             "parameters": ["\u3055\u3088\u3046\u306a\u3089\\C[1]\u307e\u305f\u306d"]},
        ]}]}]})
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    mine = {entry["id"] for entry in mvkeys.load_keys(work)
            if "Map008" in entry["id"]}
    values, report = prefill.harvest(
        work, str(_write_dict(tmp_path, {
            "\u3053\u3093\u306b\u3061\u306f": "\u3053\u3093\u306b\u3061\u306f\u3067\u3059",
            "\u3055\u3088\u3046\u306a\u3089\u307e\u305f\u306d": "\u518d\u89c1",
        })), allow_ids=mine)
    assert "\u3053\u3093\u306b\u3061\u306f" not in values        # kana residue
    assert report["rejected_by"]["kana residue"] == 1
    assert report["missed"] == 1                             # mid-line code


def _write_dict(directory, payload):
    """A runtime dictionary file (UTF-8, flat ``{source: translation}``)."""
    path = os.path.join(str(directory), "dict.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return path


def test_slice_todo_skips_translated_keys(tmp_path):
    """``--todo`` returns the next *untranslated* keys, count applied after."""
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map009.json")
    lines = [{"code": 401, "indent": 0, "parameters": [text]}
             for text in ("\u3042\u3044\u3046", "\u304b\u304d\u304f",
                          "\u3055\u3057\u3059", "\u305f\u3061\u3064")]
    _dump(path, {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
        "pages": [{"list": lines}]}]})
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    entries = [entry for entry in mvkeys.load_keys(work)
               if "Map009" in entry["id"]]
    assert len(entries) == 4
    rawlib.append_block(os.path.join(work, rawlib.LIBRARY_NAME), entries[0]["id"],
                        "\u554a")
    rawlib.append_block(os.path.join(work, rawlib.LIBRARY_NAME), entries[2]["id"],
                        "\u55ef")

    done = set(rawlib.read_library(os.path.join(work, rawlib.LIBRARY_NAME)))
    mine = {entry["id"] for entry in entries}
    others = {entry["id"] for entry in mvkeys.load_keys(work)
              if entry["id"] not in mine}
    todo = mvkeys.slice_keys(work, count=2, skip_ids=done | others)
    assert [entry["ja"] for entry in todo] == ["\u304b\u304d\u304f", "\u305f\u3061\u3064"]
    # count applies to the filtered list, not to the raw position
    assert [entry["ja"] for entry in
            mvkeys.slice_keys(work, count=2, skip_ids=others)] == \
        ["\u3042\u3044\u3046", "\u304b\u304d\u304f"]

    out = os.path.join(work, "slice.jsonl")
    assert cli.main(["slice", work, "--count", "2", "--lean", "--todo",
                     "--out", out]) == 0
    sliced = [json.loads(line) for line in open(out, encoding="utf-8")]
    assert len(sliced) == 2
    assert not [entry for entry in sliced if entry["id"] in done]
    assert all(set(entry) == {"id", "ja", "speaker", "where"}
               for entry in sliced)


def test_append_batch_rejects_a_broken_json_value(tmp_path):
    """The library cannot receive a structurally broken parameter value."""
    root = make_game(str(tmp_path / "game"))
    inner = json.dumps({"label": "\u3044\u3044\u3048", "switchId": "0"},
                       ensure_ascii=False)
    choices = json.dumps([inner], ensure_ascii=False)
    _dump(os.path.join(root, "data", "Map006.json"),
          {"displayName": "", "events": [None, {"id": 1, "name": "Ev",
              "pages": [{"list": [
                  {"code": 357, "indent": 0,
                   "parameters": ["LL_GalgeChoiceWindow", "showChoice",
                                  "\u9078\u629e\u80a2\u306e\u8868\u793a",
                                  {"messageText": "\u958b\u304f\uff1f",
                                   "choices": choices}]},
              ]}]}]})
    work = str(tmp_path / "work")
    mvkeys.extract(root, work)
    entry = next(e for e in mvkeys.load_keys(work)
                 if e["id"].endswith(".choices"))

    batch = os.path.join(work, "_batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n{}\n".format(entry["id"], choices[:-1]))
    report = rawlib.append_batch(work, batch)
    assert report["added"] == 0
    assert any("JSON structure" in problem for _, problem in report["problems"])
    library = os.path.join(work, rawlib.LIBRARY_NAME)
    assert not os.path.isfile(library) or rawlib.read_library(library) == {}

    # the same value with only the label rewritten is accepted
    fixed = choices.replace("\u3044\u3044\u3048", "\u4e0d\u8981")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n{}\n".format(entry["id"], fixed))
    assert rawlib.append_batch(work, batch)["added"] == 1


def test_apply_rewrites_rerun_is_a_no_op(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, lambda entry, text: "\u6742\u9c7c")
    rawlib.append_jsonl(os.path.join(work, "rewrites.jsonl"),
                        {"old": "\u6742\u9c7c", "new": "\u6742\u9c7c\u5251",
                         "reason": "test"})
    first = rawlib.apply_rewrites(work)
    values = rawlib.read_library(os.path.join(work, rawlib.LIBRARY_NAME))
    assert set(values.values()) == {"\u6742\u9c7c\u5251"}
    assert first["applied"][0]["affected"] == len(values)
    assert first["applied"][0]["already_up_to_date"] == 0

    second = rawlib.apply_rewrites(work)
    values = rawlib.read_library(os.path.join(work, rawlib.LIBRARY_NAME))
    assert "\u6742\u9c7c\u5251\u5251" not in set(values.values())
    assert set(values.values()) == {"\u6742\u9c7c\u5251"}
    assert second["applied"][0]["affected"] == 0
    assert second["applied"][0]["already_up_to_date"] == len(values)


def test_apply_rewrites_scope_and_report(work, game):
    mvkeys.extract(game, work)
    target_id = "data/Map001.json#events[1].pages[0].list[1].parameters[0]"
    _fill_library(work, lambda entry, text: text.replace("\u304a", "\u55e8!"))
    rawlib.append_jsonl(os.path.join(work, "rewrites.jsonl"),
                        {"old": "\u55e8!", "new": "X", "reason": "test"})
    report = rawlib.apply_rewrites(work)
    assert report["rules"] == 1 and report["changed_keys"] >= 1
    values = rawlib.read_library(os.path.join(work, rawlib.LIBRARY_NAME))
    assert "X" in values[target_id]
    rawlib.append_jsonl(os.path.join(work, "rewrites.jsonl"),
                        {"old": "X", "new": "Y", "ids": [target_id]})
    report = rawlib.apply_rewrites(work)
    assert report["applied"][-1]["scope"] == "ids"
    assert report["applied"][-1]["affected"] == 1
    assert os.path.isfile(os.path.join(work, "rewrite_report.json"))


# ---------------------------------------------------------------- gates

def test_fix_leading_codes_restores_only_a_safe_prefix():
    assert rawlib.leading_codes("\\{\\{\\{\u7ed3\u5c40") == "\\{\\{\\{"
    assert rawlib.leading_codes("\u7ed3\u5c40") == ""
    assert rawlib.fix_leading_codes("\\px[200]\u3042\u3044", "\u8bd1\u6587") \
        == "\\px[200]\u8bd1\u6587"
    assert rawlib.fix_leading_codes("\\px[200]\u3042\u3044",
                                    "\\px[200]\u8bd1\u6587") \
        == "\\px[200]\u8bd1\u6587"
    assert rawlib.fix_leading_codes("\\px[200]\u3042\u3044", "\\px[100]\u8bd1\u6587") \
        == "\\px[100]\u8bd1\u6587"      # a wrong code is validation's business
    assert rawlib.fix_leading_codes("\u3042\u3044", "\u8bd1\u6587") == "\u8bd1\u6587"
    # a name box is display text: copying it back would restore Japanese
    assert rawlib.fix_leading_codes("\\nc<\u30df\u30ab>\u3084\u3042", "\u55e8") \
        == "\u55e8"


def test_append_batch_fix_leading(work, game):
    mvkeys.extract(game, work)
    entry = [e for e in mvkeys.load_keys(work)
             if e["ja"].startswith("\\px[200]")][0]
    batch = os.path.join(work, "_wip_batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n\u8bd1\u6587\\c[1]\u3002\n".format(entry["id"]))
    report = rawlib.append_batch(work, batch, fix_leading=True)
    assert report == {"added": 1, "fixed": 1, "problems": []}
    values = rawlib.read_library(os.path.join(work, rawlib.LIBRARY_NAME))
    assert values[entry["id"]] == "\\px[200]\u8bd1\u6587\\c[1]\u3002"
    assert rawlib.append_batch(work, batch, fix_leading=False)["added"] == 0


def test_gate_pending_survives_a_broken_line(work, game):
    """A hand-written bad line must fail the gate, not crash the tool."""
    mvkeys.extract(game, work)
    _fill_library(work, _neutral)
    path = os.path.join(work, "pending.jsonl")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"id": "a", "status": "resolved"}\n')
        handle.write('{"id": "b", "why": "bad \\px[200] escape"}\n')
    records, errors = rawlib.read_jsonl_report(path)
    assert len(records) == 1 and len(errors) == 1
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert gate["ok"] is False and gate["unparsable"] == 1
    assert "unparsable" in rawlib.gate_markdown(rawlib.run_gates(work))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"id": "a", "status": "resolved"}\n')
    assert {g["name"]: g for g in rawlib.run_gates(work)["gates"]}[
        "pending"]["ok"] is True


def test_cli_decide_closes_open_entries(work, game, capsys):
    assert cli.main(["prepare", game, work]) == 0
    for key in ("a", "b"):
        assert cli.main(["pending", work, "--id", key,
                         "--why", "\u53e3\u5f84\u5907\u9009"]) == 0
    assert cli.main(["decide", work]) != 0            # needs --all-open
    assert cli.main(["decide", work, "--all-open", "--dry-run",
                     "--reason", "x"]) == 0
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert gate["open"] == 2                         # dry run writes nothing
    assert cli.main(["decide", work, "--all-open", "--reason",
                     "\u6309\u73b0\u6848\u88c1\u5b9a\uff0cowner \u53ef\u56de\u6539"]) == 0
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert gate["ok"] is True and gate["open"] == 0
    records, errors = rawlib.read_jsonl_report(os.path.join(work, "pending.jsonl"))
    assert errors == [] and len(records) == 4         # history preserved
    assert records[-1]["status"] == "decided"
    assert cli.main(["decide", work, "--id", "nope", "--reason", "x"]) != 0
    capsys.readouterr()


def test_cli_pending_escapes_text(work, game, capsys):
    assert cli.main(["prepare", game, work]) == 0
    assert cli.main(["pending", work, "--id", "x", "--why",
                     'has a \\px[200] code and a \\" quote']) == 0
    assert cli.main(["pending", work, "--id", "x", "--status", "resolved",
                     "--why", "decided by owner"]) == 0
    records, errors = rawlib.read_jsonl_report(
        os.path.join(work, "pending.jsonl"))
    assert errors == [] and len(records) == 2
    assert "\\px[200]" in records[0]["why"]
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert gate["open"] == 0 and gate["entries"] == 2
    capsys.readouterr()


def test_status_and_pending_gate_agree(work, game):
    """``pending_open`` must match the gate: last entry per id wins."""
    mvkeys.extract(game, work)
    _fill_library(work, _neutral)
    path = os.path.join(work, "pending.jsonl")
    rawlib.append_jsonl(path, {"id": "x", "why": "\u6b67\u4e49", "status": "open"})
    rawlib.append_jsonl(path, {"id": "x", "why": "\u6b67\u4e49", "status": "resolved"})
    summary = workspace.status_summary(work)
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert summary["pending"] == gate["entries"] == 2       # history kept
    assert summary["pending_open"] == gate["open"] == 0     # but closed once

    rawlib.append_jsonl(path, {"id": "y", "why": "\u65b0\u95ee\u9898"})
    summary = workspace.status_summary(work)
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert summary["pending_open"] == gate["open"] == 1
    assert summary["pending"] == gate["entries"] == 3

    latest, entries, errors = rawlib.read_pending(work)
    assert (entries, errors) == (3, [])
    assert rawlib.pending_open(latest) == list(latest.values())[-1:] != []


def test_pending_status_summary_reports_parse_errors(work, game):
    mvkeys.extract(game, work)
    workspace.scaffold(work)
    with open(os.path.join(work, "pending.jsonl"), "w", encoding="utf-8",
                 newline="\n") as handle:
        handle.write("{not json}\n")
    summary = workspace.status_summary(work)
    assert summary["ready"] is True


def test_gates_all_green(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, _neutral)
    report = rawlib.run_gates(work)
    assert report["ok"] is True, report
    assert all(gate["ok"] for gate in report["gates"])
    assert "ALL PASS" in rawlib.gate_markdown(report)


def test_gate_coverage_fails(work, game):
    mvkeys.extract(game, work)
    keys = mvkeys.load_keys(work)
    rawlib.append_block(os.path.join(work, rawlib.LIBRARY_NAME),
                        keys[0]["id"], "\u53ea\u7ffb\u4e00\u6761")
    report = rawlib.run_gates(work)
    assert report["ok"] is False
    coverage = report["gates"][0]
    assert coverage["name"] == "coverage" and coverage["missing"] == len(keys) - 1
    assert rawlib.run_gates(work)["gates"][0]["detail"]


def test_gate_control_codes_fails(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, lambda entry, text: text.replace("\\c[1]", ""))
    report = rawlib.run_gates(work)
    gate = {g["name"]: g for g in report["gates"]}["control_codes"]
    assert report["ok"] is False and gate["mismatched"] >= 1
    assert gate["detail"][0]["source"] == ["\\c[1]"]
    # The gate's OWN verdict, not only the aggregate: the library here also
    # leaves kana behind, so `report["ok"] is False` is satisfied by the kana
    # gate even when this gate is broken.  Mutation testing found exactly that
    # (`"ok": not mismatch` -> `True` survived test_gate_control_codes_fails
    # while test_gate_coverage_fails killed the same edit on its own gate).
    assert gate["ok"] is False


def test_parameter_helpers():
    assert codes.parameter_of("\\px[200]") == "200"
    assert codes.parameter_of("\\nc<\u30c1\u30f3\u30d4\u30e9>") == "\u30c1\u30f3\u30d4\u30e9"
    assert codes.parameter_of("\\{") is None
    assert codes.has_text_parameter("\\nc<\u30c1\u30f3\u30d4\u30e9>") is True
    assert codes.has_text_parameter("\\nc<\u6df7\u6df7>") is True
    assert codes.has_text_parameter("\\px[200]") is False
    assert codes.has_text_parameter("\\N[1]") is False


def test_gate_allows_translated_name_box_parameter(work, game):
    """A name box shows its parameter, so translating it must not fail."""
    mvkeys.extract(game, work)

    def rename(entry, text):
        return text.replace("\\nc<\u30df\u30ab>", "\\nc<\u7f8e\u9999>")

    _fill_library(work, rename)
    report = rawlib.run_gates(work)
    gate = {g["name"]: g for g in report["gates"]}["control_codes"]
    assert gate["ok"] is True and gate["translated_parameters"] == 1


def test_gate_rejects_changed_numeric_parameter(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, lambda entry, text: text.replace("\\c[1]", "\\c[2]"))
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}[
        "control_codes"]
    assert gate["ok"] is False and gate["mismatched"] >= 1
    assert gate["detail"][0]["reason"] == "code parameter"


def test_gate_flags_kana_in_name_box(work, game):
    """An untranslated name inside a code parameter is residue, not invisible."""
    mvkeys.extract(game, work)
    _fill_library(work, _keep_namebox)
    already = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["kana"]
    assert already["ok"] is False and already["residue"] == 1
    _dump(os.path.join(work, "allow_kana.json"),
          {"items": [{"match": "re:[\u30a2-\u30f4]{2,}", "reason": "\u56fa\u6709\u540d\u8bcd"}]})
    assert {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["kana"]["ok"] is True


def test_gate_kana_residue_and_allowlist(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, lambda entry, text: text + "\u30c9\u30ad\u30c9\u30ad")
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["kana"]
    assert gate["ok"] is False and gate["residue"] >= 1
    _dump(os.path.join(work, "allow_kana.json"),
          {"items": [{"match": "\u30c9\u30ad\u30c9\u30ad", "reason": "\u62df\u58f0\u8bcd"}]})
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["kana"]
    assert gate["ok"] is True and gate["allowed"] >= 1
    _dump(os.path.join(work, "allow_kana.json"),
          {"items": [{"match": "re:[\u30c9\u30ad]{2,}", "reason": "\u62df\u58f0\u8bcd"}]})
    assert {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["kana"]["ok"] is True


def test_kana_gate_accepts_chinese_with_kana_punctuation(work, game):
    """Kana-block *punctuation* in a translated value is not residue.

    A moan line translates to Chinese that keeps the voice mark ``\u309b``
    (``\u300c\u3042\u309b\u3063\uff01`` -> ``\u300c\u554a\u309b\uff01``); ``\u30fb`` and
    ``\u30fc`` appear in Chinese text too.  Counting them as residue rejected
    534 finished values in one real MV harvest (873 hits on ``\u309b`` alone),
    each of them needing a pointless ``allow_kana.json`` entry.
    """
    mvkeys.extract(game, work)
    _dump(os.path.join(work, "allow_kana.json"), {"items": []})
    _fill_library(work, lambda entry, text: "\u554a\u309b\uff01\u597d\u30fb\u574f\u2014\u2014\uff5e\uff5e")
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["kana"]
    assert gate["ok"] is True and gate["residue"] == 0


def test_kana_gate_still_flags_a_kana_letter(work, game):
    """The relaxed punctuation rule must not weaken the gate itself."""
    mvkeys.extract(game, work)
    _dump(os.path.join(work, "allow_kana.json"), {"items": []})
    _fill_library(work, lambda entry, text: "\u554a\u309b\uff01\u3063")
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["kana"]
    assert gate["ok"] is False and gate["residue"] >= 1


def test_gate_line_breaks_fails_on_truncated_multiline(work, game):
    """A value that drops one of the source's lines is a gate failure.

    Real defect this pins down: 42 skill descriptions shipped with only their
    first line, invisible to both the kana gate (line 1 was translated) and the
    control-code gate.
    """
    mvkeys.extract(game, work)
    _fill_library(work, lambda entry, text:
                  text.split("\n")[0] if "\n" in text else text)
    report = rawlib.run_gates(work)
    gate = {g["name"]: g for g in report["gates"]}["line_breaks"]
    assert report["ok"] is False
    assert gate["ok"] is False and gate["mismatched"] >= 1
    assert "line breaks" in gate["detail"][0]["reason"]
    assert "line count" in rawlib.gate_markdown(report)


def test_append_rejects_truncated_multiline_batch(work, game):
    """The append gate refuses a truncated value before it reaches the library."""
    mvkeys.extract(game, work)
    entry = next(e for e in mvkeys.load_keys(work) if "\n" in e["ja"])
    batch = os.path.join(work, "batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n{}\n".format(entry["id"], entry["ja"].split("\n")[0]))
    report = rawlib.append_batch(work, batch)
    assert report["added"] == 0
    assert any("line breaks" in problem for _id, problem in report["problems"])


def test_append_accepts_matching_line_breaks(work, game):
    mvkeys.extract(game, work)
    entry = next(e for e in mvkeys.load_keys(work) if "\n" in e["ja"])
    kana = re.compile(r"[\u3040-\u30ff]")
    value = "\n".join(kana.sub("\u4e2d", line) for line in entry["ja"].split("\n"))
    batch = os.path.join(work, "batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n{}\n".format(entry["id"], value))
    report = rawlib.append_batch(work, batch)
    assert report["problems"] == [] and report["added"] == 1


def test_gate_pending_until_resolved(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, _neutral)
    rawlib.append_jsonl(os.path.join(work, "pending.jsonl"),
                        {"id": "x", "why": "\u4e8c\u4e49", "status": "open"})
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert gate["ok"] is False and gate["open"] == 1
    rawlib.append_jsonl(os.path.join(work, "pending.jsonl"),
                        {"id": "x", "why": "\u4e8c\u4e49", "status": "resolved"})
    gate = {g["name"]: g for g in rawlib.run_gates(work)["gates"]}["pending"]
    assert gate["ok"] is True and gate["entries"] == 2


# ---------------------------------------------------------------- workspace

def test_scaffold_is_idempotent_and_writes_mission(work, game):
    stats = mvkeys.extract(game, work)
    created = workspace.scaffold(work, stats)
    assert "MISSION.md(rewritten)" in created
    library = os.path.join(work, rawlib.LIBRARY_NAME)
    rawlib.append_block(library, "keep-me", "\u4e0d\u8981\u88ab\u8986\u76d6")
    mission = open(os.path.join(work, "MISSION.md"), encoding="utf-8").read()
    assert str(stats["keys"]) in mission and "@@@@" not in mission
    assert "translations.raw.txt" in mission and "MISSION" not in created[0]
    again = workspace.scaffold(work, stats)
    assert again == ["MISSION.md(rewritten)"]
    assert rawlib.read_library(library)["keep-me"] == "\u4e0d\u8981\u88ab\u8986\u76d6"


def test_status_summary_counts(work, game):
    mvkeys.extract(game, work)
    workspace.scaffold(work)
    keys = mvkeys.load_keys(work)
    rawlib.append_block(os.path.join(work, rawlib.LIBRARY_NAME), keys[0]["id"],
                        "\u8bd1\u6587")
    rawlib.append_block(os.path.join(work, rawlib.LIBRARY_NAME), "ghost", "x")
    summary = workspace.status_summary(work)
    assert summary["ready"] is True
    assert summary["translated"] == 1 and summary["unknown_ids"] == 1
    assert summary["percent"] > 0


def test_cli_prepare_gates_status(work, game, capsys):
    assert cli.main(["prepare", game, work]) == 0
    assert os.path.isfile(os.path.join(work, "MISSION.md"))
    assert cli.main(["status", work]) == 0
    assert cli.main(["gates", work]) == 1        # nothing translated yet
    _fill_library(work, _neutral)
    assert cli.main(["to-json", work]) == 0
    assert cli.main(["gates", work]) == 0
    assert cli.main(["rewrite", work]) == 0
    assert cli.main(["codes", work]) == 0
    assert cli.main(["scaffold", work]) == 0
    capsys.readouterr()


def test_slice_keys_streams_in_order(work, game):
    mvkeys.extract(game, work)
    entries = mvkeys.slice_keys(work, start=2, count=3)
    assert [entry["seq"] for entry in entries] == [2, 3, 4]
    assert mvkeys.slice_keys(work, start=0, count=99)[-1]["seq"] == \
        len(mvkeys.load_keys(work)) - 1
    only_db = mvkeys.slice_keys(work, count=None, kind="db")
    assert only_db and all(entry["kind"] == "db" for entry in only_db)
    assert mvkeys.slice_keys(work, start=9999, count=5) == []


def test_cli_slice_writes_a_workable_slice(work, game, tmp_path, capsys):
    assert cli.main(["prepare", game, work]) == 0
    out = str(tmp_path / "slice.jsonl")
    assert cli.main(["slice", work, "--start", "0", "--count", "5",
                     "--out", out]) == 0
    lines = [json.loads(line) for line in
             open(out, encoding="utf-8").read().splitlines()]
    assert len(lines) == 5 and "ja" in lines[0]
    assert cli.main(["slice", work, "--start", "9999"]) != 0
    capsys.readouterr()


def test_append_batch_validates_before_writing(work, game):
    """A batch is all-or-nothing: a bad batch must not touch the library."""
    mvkeys.extract(game, work)
    entries = mvkeys.load_keys(work)
    batch = os.path.join(work, "_wip_batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n\u8bd1\u6587\n".format(entries[0]["id"]))
    report = rawlib.append_batch(work, batch)
    assert report["problems"] == [] and report["added"] == 1
    library = os.path.join(work, rawlib.LIBRARY_NAME)
    assert rawlib.read_library(library)[entries[0]["id"]] == "\u8bd1\u6587"
    # a batch with an unknown id, an empty value and a broken code sequence
    codes_entry = [entry for entry in entries if "\\c[1]" in entry["ja"]][0]
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@ghost@@@\n\u8bd1\u6587\n")
        handle.write("@@@{}@@@\n\n".format(entries[1]["id"]))
        handle.write("@@@{}@@@\n{}\n".format(codes_entry["id"],
                        codes_entry["ja"].replace("\\c[1]", "")))
    before = rawlib.read_library(library)
    report = rawlib.append_batch(work, batch)
    assert report["added"] == 0 and len(report["problems"]) == 3
    assert rawlib.read_library(library) == before
    assert "ghost" not in rawlib.read_library(library)


def test_append_batch_rejects_kana_residue(work, game):
    mvkeys.extract(game, work)
    entry = [e for e in mvkeys.load_keys(work) if e["kind"] == "db"][0]
    batch = os.path.join(work, "_wip_batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n{}\n".format(entry["id"], entry["ja"]))
    report = rawlib.append_batch(work, batch)
    assert report["added"] == 0
    assert "kana residue" in report["problems"][0][1]
    _dump(os.path.join(work, "allow_kana.json"),
          {"items": [{"match": entry["ja"], "reason": "\u56fa\u6709\u540d\u8bcd"}]})
    assert rawlib.append_batch(work, batch)["added"] == 1


def test_cli_append_reports_problems(work, game, tmp_path, capsys):
    assert cli.main(["prepare", game, work]) == 0
    batch = str(tmp_path / "batch.txt")
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@ghost@@@\n\u8bd1\u6587\n")
    assert cli.main(["append", work, "--batch", batch]) != 0
    entries = mvkeys.load_keys(work)
    with open(batch, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@{}@@@\n\u8bd1\u6587\n".format(entries[0]["id"]))
    assert cli.main(["append", work, "--batch", batch,
                     "--note", "\u7b2c\u4e00\u6279"]) == 0
    assert rawlib.read_jsonl(os.path.join(work, "progress.jsonl"))[0]["added"] == 1
    assert cli.main(["append", work, "--batch", str(tmp_path / "nope.txt")]) != 0
    capsys.readouterr()


def test_cli_slice_compact_drops_heavy_fields(work, game, tmp_path, capsys):
    assert cli.main(["prepare", game, work]) == 0
    out = str(tmp_path / "compact.jsonl")
    assert cli.main(["slice", work, "--count", "3", "--compact",
                     "--out", out]) == 0
    rows = [json.loads(line) for line in
            open(out, encoding="utf-8").read().splitlines()]
    assert set(rows[0]) == {"id", "ja", "speaker", "prev", "next"}
    lean_out = str(tmp_path / "lean.jsonl")
    assert cli.main(["slice", work, "--count", "3", "--lean",
                     "--out", lean_out]) == 0
    lean = [json.loads(line) for line in
            open(lean_out, encoding="utf-8").read().splitlines()]
    assert set(lean[0]) == {"id", "ja", "speaker", "where"}
    assert len(open(lean_out, encoding="utf-8").read()) < \
        len(open(out, encoding="utf-8").read())
    capsys.readouterr()


def test_cli_reports_missing_work_dir(tmp_path, capsys):
    assert cli.main(["gates", str(tmp_path / "nope")]) != 0
    capsys.readouterr()
