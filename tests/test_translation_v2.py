#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the v2 translation toolkit (`translation/`).

Every fixture is a synthetic MV tree: the point is to pin the *contract*
(stable ids, story order, raw-text library, the four gates) without shipping
any game's data.
"""
import io
import json
import os

import pytest

from translation import cli, codes, mvkeys, rawlib, workspace

MAP_TEXT = "\u3010\u30e6\u30ad\u3011\u304a\u306f\u3088\u3046\\c[1]\u3002\n\u4e8c\u884c\u76ee\u3067\u3059\u3002"
SECOND_TEXT = "\\nc<\u30df\u30ab>\u3084\u3042\\{\u5927\u304d\u3044\\}"
MACRO_TEXT = "\\N[1]\u306e\u51fa\u756a\u3060\u3002"


def _dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
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
        with io.open(os.path.join(root, "js", "plugins.js"), "w",
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
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
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
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
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
    text = "\u3042\\c[1]\u3044\\{ok\}"
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
    text = io.open(path, encoding="utf-8").read()
    assert "`\\PX`" in text and "`\\C`" in text


# ---------------------------------------------------------------- keys

def test_extract_tolerates_plugin_shaped_entries(tmp_path):
    """Real data can hold non-command entries (plugins write their own)."""
    root = make_game(str(tmp_path / "game"))
    path = os.path.join(root, "data", "Map001.json")
    data = json.load(io.open(path, encoding="utf-8"))
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
    assert stats["skipped"]["malformed"] == 1


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
    stats = json.load(io.open(os.path.join(work, "stats.json"), encoding="utf-8"))
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


def test_names_candidates_include_macros(work, game):
    mvkeys.extract(game, work)
    names = json.load(io.open(os.path.join(work, "names_candidates.json"),
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
    assert mvkeys.is_candidate("\u653b\u6483", "map") is False
    assert mvkeys.is_candidate("\u653b\u6483", "db") is True
    assert mvkeys.is_candidate("", "db") is False
    assert mvkeys.is_candidate("img\\u30c6.png", "db") is False


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
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write("\u6ca1\u6709\u5934\u884c\n")
    with pytest.raises(ValueError):
        rawlib.read_library(path)


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

    Kana inside a code parameter (``\\nc<name>``) is part of the code, so the
    substitution is applied to the text segments only.
    """
    return "".join(piece if is_code else codes.KANA_RE.sub("\u597d", piece)
                   for is_code, piece in codes.split_keep_codes(text))


def test_to_json_escapes_and_reports_conflicts(work, game):
    mvkeys.extract(game, work)
    _fill_library(work, lambda entry, text: "\u8bd1\u6587" + text)
    report = rawlib.to_json(work)
    assert report["translated"] == report["keys"]
    data = json.load(io.open(os.path.join(work, "translated.json"),
                             encoding="utf-8"))
    assert data[MAP_TEXT] == "\u8bd1\u6587" + MAP_TEXT
    assert "\n" in data[MAP_TEXT]            # real newline survived as JSON
    ids = json.load(io.open(os.path.join(work, "translated_ids.json"),
                            encoding="utf-8"))
    assert len(ids) == report["keys"]
    # same source, different translation -> reported, first one kept
    entry = mvkeys.load_keys(work)[0]
    rawlib.append_block(os.path.join(work, rawlib.LIBRARY_NAME), entry["id"],
                        "\u5176\u4ed6\u8bd1\u6cd5")
    assert rawlib.to_json(work)["conflicts"] == []


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
    mission = io.open(os.path.join(work, "MISSION.md"), encoding="utf-8").read()
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


def test_cli_reports_missing_work_dir(tmp_path, capsys):
    assert cli.main(["gates", str(tmp_path / "nope")]) != 0
    capsys.readouterr()
