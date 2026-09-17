#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comment-command payload translation (`prepare --note-tags` + `bake`).

Some plugins read a menu entry's *displayed* text out of comment commands
rather than out of a `note` field: a VisuMZ-style common-event menu takes

    <Name: 港町アストレア>          (inline payload)
    <Help Description>              (block open)
    ヘルプ本文
    </Help Description>             (block close)

and draws those payloads in the menu.  Comments (108/408) are otherwise never
extracted, so this class of player-visible Japanese used to survive every gate
while the build still showed Japanese menu entries.

These tests pin the contract:
  * opt-in per tag, like note payloads; nothing is extracted by default,
  * the payload only (tag lines stay byte-identical - the tag name is the
    plugin's lookup key),
  * only comments: a tag written in a script, a message or a plugin command is
    not text the plugin reads, and must never become a key,
  * an unterminated block is skipped, not guessed at,
  * bake rewrites exactly the payload lines and refuses a payload whose line
    count no longer matches the source block.
"""
import io
import json
import os

import pytest

from translation import bake as bake_mod
from translation import mvkeys
from translation import rawlib


def _dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _obj(code, *params):
    return {"code": code, "indent": 0, "parameters": list(params)}


def _arr(code, *params):
    return [code, 0, *params]


def make_game(root):
    data = os.path.join(root, "data")
    _dump(os.path.join(data, "System.json"), {"gameTitle": "テスト"})
    _dump(os.path.join(data, "MapInfos.json"), [None, {"id": 1, "name": "Map001"}])
    _dump(os.path.join(data, "CommonEvents.json"), [
        None,
        # 1: inline + block, both shapes of a command
        {"id": 1, "name": "0001", "list": [
            _obj(108, "<Name: 港町アストレア>"),
            _obj(108, "<Help Description>"),
            _arr(408, "ヘルプの一行目"),
            _obj(108, "ヘルプの二行目"),
            _obj(408, "</Help Description>"),
            _obj(108, "<Subtext Description>"),
            _arr(408, ""),
            _obj(408, "</Subtext Description>"),
        ]},
        # 2: the same tag inside a script and a message - never payload text
        {"id": 2, "name": "0002", "list": [
            _obj(355, "var s = '<Name: スクリプト>';"),
            _arr(401, "<Help Description>"),
            _obj(356, ["Plugin", "cmd", "説明", {"text": "<Subtext Description>"}]),
        ]},
        # 3: unterminated block
        {"id": 3, "name": "0003", "list": [
            _obj(108, "<Help Description>"),
            _obj(408, "閉じない本文"),
            _obj(401, "こんにちは"),
        ]},
    ])
    _dump(os.path.join(data, "Map001.json"), {
        "displayName": "町",
        "events": [{"id": 1, "name": "EV001", "note": "", "pages": [{"list": [
            _obj(108, "<Name: 酒場>"),
            _obj(108, "<Help Description>"),
            _obj(408, "酒場の説明"),
            _obj(408, "</Help Description>"),
        ]}]}],
    })
    return root


@pytest.fixture()
def game(tmp_path):
    return make_game(str(tmp_path / "game"))


def by_id(work_dir):
    return {entry["id"]: entry for entry in mvkeys.load_keys(work_dir)}


def _text(command):
    """The text of a command of either shape (object or editor array)."""
    if isinstance(command, dict):
        return command["parameters"][0]
    return command[2]


# ------------------------------------------------------------- helper unit

def test_comment_payloads_reads_both_forms():
    commands = [
        _obj(108, "<Name: 港町>"),
        _obj(108, "<Help Description>"),
        _obj(408, "一行目"),
        _obj(408, "二行目"),
        _obj(108, "</Help Description>"),
    ]
    payloads = mvkeys.comment_payloads(commands, ["Name", "Help Description"])
    assert payloads[0][:3] == ("Name", 0, "港町")
    assert payloads[0][3] == 0
    assert payloads[1][:3] == ("Help Description", 0, "一行目\n二行目")
    assert payloads[1][4] == [2, 3]


def test_comment_payloads_ignores_non_comments_and_unknown_tags():
    commands = [
        _obj(355, "<Name: スクリプト>"),
        _obj(401, "<Name: メッセージ>"),
        _obj(108, "<Other: 対象外>"),
    ]
    assert mvkeys.comment_payloads(commands, ["Name"]) == []
    assert mvkeys.comment_payloads(commands, ["Other"]) == [("Other", 0, "対象外", 2, [])]
    assert mvkeys.comment_payloads(commands, []) == []


def test_comment_payloads_skips_unterminated_block():
    commands = [_obj(108, "<Help Description>"), _obj(408, "閉じない")]
    assert mvkeys.comment_payloads(commands, ["Help Description"]) == []


def test_comment_payloads_counts_repeats_per_list():
    commands = [
        _obj(108, "<Name: 一つ目>"),
        _obj(108, "<Name: 二つ目>"),
    ]
    payloads = mvkeys.comment_payloads(commands, ["Name"])
    assert [p[1] for p in payloads] == [0, 1]
    assert [p[3] for p in payloads] == [0, 1]


def test_comment_payloads_handles_empty_and_malformed_entries():
    commands = [None, "junk", _obj(108, "<Name: 値>"), _obj(108, 5)]
    payloads = mvkeys.comment_payloads(commands, ["Name"])
    assert payloads == [("Name", 0, "値", 2, [])]


# ------------------------------------------------------------- extraction

def test_comment_payloads_are_skipped_by_default(game, tmp_path):
    work = str(tmp_path / "work")
    mvkeys.extract(game, work)
    assert "comment<" not in " ".join(
        entry["where"] for entry in mvkeys.load_keys(work))


def test_comment_payloads_are_extracted_for_allowlisted_tags(game, tmp_path):
    work = str(tmp_path / "work")
    stats = mvkeys.extract(game, work, note_tags=["Name", "Help Description",
                                                  "Subtext Description"])
    entries = by_id(work)
    inline = entries["data/CommonEvents.json#[1].list[0]#Name[0]"]
    assert inline["ja"] == "港町アストレア"
    block = entries["data/CommonEvents.json#[1].list[1]#Help Description[0]"]
    assert block["ja"] == "ヘルプの一行目\nヘルプの二行目"
    assert "Help Description" not in block["ja"]
    # an empty payload block is configuration, not text: no key
    assert "data/CommonEvents.json#[1].list[5]#Subtext Description[0]" not in entries
    assert "data/Map001.json#events[0].pages[0].list[1]#Help Description[0]" in entries
    assert "data/Map001.json#events[0].pages[0].list[0]#Name[0]" in entries
    assert stats["note_tags"] == ["Name", "Help Description",
                                 "Subtext Description"]


def test_script_and_message_tags_stay_out(game, tmp_path):
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["Name", "Help Description",
                                          "Subtext Description"])
    comment_ids = [entry["id"] for entry in mvkeys.load_keys(work)
                   if "comment<" in entry["where"]]
    assert comment_ids
    assert not [i for i in comment_ids if "#[2].list" in i or "#[3].list" in i]


# ----------------------------------------------------------------- bake

def test_set_comment_payload_rewrites_only_the_payload():
    root = [None, {"id": 1, "list": [
        _obj(108, "<Name: 港町アストレア>"),
        _obj(108, "<Help Description>"),
        _obj(408, "一行目"),
        _obj(408, "二行目"),
        _obj(408, "</Help Description>"),
        _obj(401, "こんにちは"),
    ]}]
    commands = root[1]["list"]
    assert bake_mod.set_comment_payload(
        root, "[1].list[1]#Help Description[0]", "一\n二") is True
    assert commands[1]["parameters"][0] == "<Help Description>"
    assert commands[4]["parameters"][0] == "</Help Description>"
    assert [commands[i]["parameters"][0] for i in (2, 3)] == ["一", "二"]
    assert commands[5]["parameters"][0] == "こんにちは"
    assert commands[0]["parameters"][0] == "<Name: 港町アストレア>"


def test_set_comment_payload_rewrites_inline_payload():
    root = [None, {"id": 1, "list": [_obj(108, "<Name: 港町アストレア>")]}]
    assert bake_mod.set_comment_payload(
        root, "[1].list[0]#Name[0]", "港镇") is True
    assert root[1]["list"][0]["parameters"][0] == "<Name: 港镇>"


def test_set_comment_payload_refuses_line_count_mismatch():
    root = [None, {"id": 1, "list": [
        _obj(108, "<Help Description>"),
        _obj(408, "一行目"),
        _obj(408, "二行目"),
        _obj(408, "</Help Description>"),
    ]}]
    assert bake_mod.set_comment_payload(
        root, "[1].list[0]#Help Description[0]", "一行中文") is False
    assert root[1]["list"][1]["parameters"][0] == "一行目"


def test_set_comment_payload_accepts_the_array_command_shape():
    root = [None, {"id": 1, "list": [_arr(108, "<Name: 港町>")]}]
    assert bake_mod.set_comment_payload(
        root, "[1].list[0]#Name[0]", "港镇") is True
    assert root[1]["list"][0] == [108, 0, "<Name: 港镇>"]


def test_set_comment_payload_reports_missing_or_mismatched_paths():
    root = [None, {"id": 1, "list": [_obj(108, "<Name: 港町>")]}]
    assert bake_mod.set_comment_payload(root, "[9].list[0]#Name[0]", "x") is False
    assert bake_mod.set_comment_payload(root, "[1].list[0]#Other[0]", "x") is False
    assert bake_mod.set_comment_payload(root, "[1].list[3]#Name[0]", "x") is False
    assert bake_mod.set_comment_payload(root, "[1].list[0]#Name[3]", "x") is False
    with pytest.raises(bake_mod.BakeError):
        bake_mod.parse_comment_id("[1].list#Name[0]")
    assert bake_mod.parse_comment_id("[1].list[4]#Name[2]") == (
        "[1].list", 4, "Name", 2)


def test_extract_to_bake_round_trip(game, tmp_path):
    """prepare --note-tags -> library -> to-json -> bake, like the real run."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["Name", "Help Description"])
    targets = [entry for entry in mvkeys.load_keys(work)
               if "comment<" in entry["where"]]
    assert len(targets) == 4
    replacements = {"港町アストレア": "港镇", "酒場": "酒馆",
                    "ヘルプの一行目": "帮助第一行", "ヘルプの二行目": "帮助第二行",
                    "酒場の説明": "酒馆的说明"}
    with io.open(os.path.join(work, rawlib.LIBRARY_NAME), "w",
                 encoding="utf-8", newline="\n") as handle:
        for entry in targets:
            value = entry["ja"]
            for old, new in sorted(replacements.items(),
                                   key=lambda item: -len(item[0])):
                value = value.replace(old, new)
            handle.write("@@@%s@@@\n%s\n" % (entry["id"], value))
    rawlib.to_json(work)
    report = bake_mod.bake(game, work, apply_unified_font=False)
    assert report["skipped"] == 0
    assert report["skipped_detail"] == []
    assert report["applied"] == len(targets)
    assert sorted(report["files"]) == ["data/CommonEvents.json", "data/Map001.json"]

    events = json.load(io.open(os.path.join(game, "data", "CommonEvents.json"),
                               encoding="utf-8"))
    cmds = events[1]["list"]
    assert _text(cmds[0]) == "<Name: 港镇>"
    assert _text(cmds[1]) == "<Help Description>"
    assert _text(cmds[2]) == "帮助第一行"
    assert _text(cmds[3]) == "帮助第二行"
    assert _text(cmds[4]) == "</Help Description>"
    # script and message lines keep their Japanese tag text verbatim
    assert _text(events[2]["list"][0]) == "var s = '<Name: スクリプト>';"
    mapp = json.load(io.open(os.path.join(game, "data", "Map001.json"),
                             encoding="utf-8"))
    lst = mapp["events"][0]["pages"][0]["list"]
    assert _text(lst[0]) == "<Name: 酒馆>"
    assert _text(lst[2]) == "酒馆的说明"
    assert _text(lst[3]) == "</Help Description>"


def test_bake_comment_write_is_idempotent(game, tmp_path):
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["Name"])
    key_id = "data/CommonEvents.json#[1].list[0]#Name[0]"
    with io.open(os.path.join(work, rawlib.LIBRARY_NAME), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("@@@%s@@@\n港镇\n" % key_id)
    rawlib.to_json(work)
    bake_mod.bake(game, work, apply_unified_font=False)
    first = json.load(io.open(os.path.join(game, "data", "CommonEvents.json"),
                              encoding="utf-8"))
    bake_mod.bake(game, work, apply_unified_font=False)
    second = json.load(io.open(os.path.join(game, "data", "CommonEvents.json"),
                               encoding="utf-8"))
    assert first == second
    assert _text(second[1]["list"][0]) == "<Name: 港镇>"
