#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Note-tag payload translation (`prepare --note-tags` + `bake`).

``note`` fields are functional data - plugin tags, embedded JSON, lookup keys -
so the extractor skips them.  A few tags render their payload verbatim and are
therefore player-visible text, and one class is worse than untranslated text:
a category label that the plugin matches against a *plugin parameter*.  A real
build shipped the parameter translated while 46 items still carried the
Japanese tag, and ``Window_ItemList.includes`` then matched nothing - the items
disappeared from the menu altogether.

These tests pin the contract:
  * extraction is opt-in per tag (default: no note keys at all),
  * the key holds the payload only (the tag name is not translatable),
  * bake rewrites exactly one occurrence and leaves every other byte alone,
  * a payload that would break the tag syntax is refused, not written.
"""
import io
import json
import os

import pytest

from translation import bake as bake_mod
from translation import mvkeys


def _dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def make_game(root):
    data = os.path.join(root, "data")
    _dump(os.path.join(data, "Items.json"), [
        None,
        {"id": 1, "name": "\u707c\u71b1\u306e\u69cc",
         "description": "\u653b\u6483\u3059\u308b",
         "note": "<\u62e1\u5f35\u8aac\u660e:\u30c0\u30e1\u30fc\u30b8\u304c\u901a\u3089\u306a\u3044>"
                 "<MNKR_SwitchSell>"},
        {"id": 2, "name": "\u5947\u5999\u306a\u7c98\u6db2",
         "description": "\u63db\u91d1\u7528",
         "note": "<itemCategory:\u63db\u91d1\u30a2\u30a4\u30c6\u30e0>"},
        {"id": 3, "name": "\u9023\u7d9a\u6ce8\u6587",
         "description": "\u4e8c\u56de\u66f8\u304f",
         "note": "<itemCategory:\u63db\u91d1\u30a2\u30a4\u30c6\u30e0>"
                 "<itemCategory:\u63db\u91d1\u30a2\u30a4\u30c6\u30e0>"},
        {"id": 4, "name": "\u6570\u5024\u3060\u3051", "description": "\u306a\u3057",
         "note": "<Coord:760,650>"},
    ])
    _dump(os.path.join(data, "Armors.json"), [
        None,
        {"id": 1, "name": "\u76fe", "description": "\u5b88\u308b",
         "note": "<\u62e1\u5f35\u8aac\u660e:\u88c5\u5099\u3059\u308b\u3068\u91cd\u304f\u306a\u308b>"},
    ])
    _dump(os.path.join(data, "System.json"), {"gameTitle": "\u30c6\u30b9\u30c8"})
    _dump(os.path.join(data, "MapInfos.json"), [None, {"id": 1, "name": "Map001"}])
    return root


@pytest.fixture()
def game(tmp_path):
    return make_game(str(tmp_path / "game"))


def by_id(work_dir):
    return {entry["id"]: entry for entry in mvkeys.load_keys(work_dir)}


# ------------------------------------------------------------- extraction

def test_notes_are_skipped_by_default(game, tmp_path):
    """Without --note-tags no note payload is extracted (functional data)."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work)
    ids = " ".join(by_id(work))
    assert ".note#" not in ids


def test_note_payloads_are_extracted_for_allowlisted_tags(game, tmp_path):
    work = str(tmp_path / "work")
    stats = mvkeys.extract(game, work, note_tags=["\u62e1\u5f35\u8aac\u660e"])
    entries = by_id(work)
    assert "data/Items.json#[1].note#\u62e1\u5f35\u8aac\u660e[0]" in entries
    item = entries["data/Items.json#[1].note#\u62e1\u5f35\u8aac\u660e[0]"]
    # the payload only - the tag name is a plugin lookup key, never translated
    assert item["ja"] == "\u30c0\u30e1\u30fc\u30b8\u304c\u901a\u3089\u306a\u3044"
    assert "<" not in item["ja"]
    assert stats["note_tags"] == ["\u62e1\u5f35\u8aac\u660e"]
    # the non-allowlisted tag in the same note stays out
    assert not any("MNKR" in i for i in entries)
    assert "data/Armors.json#[1].note#\u62e1\u5f35\u8aac\u660e[0]" in entries


def test_repeated_tag_gets_one_key_per_occurrence(game, tmp_path):
    """Two tags with the same name must not collapse into one id."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["itemCategory"])
    entries = by_id(work)
    assert "data/Items.json#[3].note#itemCategory[0]" in entries
    assert "data/Items.json#[3].note#itemCategory[1]" in entries
    assert "data/Items.json#[2].note#itemCategory[0]" in entries


def test_allowlisted_tag_without_display_text_is_not_a_key(game, tmp_path):
    """A numeric payload is configuration, not prose - nothing to translate."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["Coord"])
    assert ".note#" not in " ".join(by_id(work))


def test_multiple_tags_can_be_allowlisted_together(game, tmp_path):
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["\u62e1\u5f35\u8aac\u660e", "itemCategory"])
    entries = by_id(work)
    assert "data/Items.json#[1].note#\u62e1\u5f35\u8aac\u660e[0]" in entries
    assert "data/Items.json#[2].note#itemCategory[0]" in entries


def test_note_payload_helper_ignores_unknown_and_malformed_tags():
    note = "<a:\u3042><b:\u3044><c><d:><a:\u3046>"
    assert mvkeys.note_payloads(note, ["a"]) == [("a", 0, "\u3042"),
                                                 ("a", 1, "\u3046")]
    assert mvkeys.note_payloads(note, []) == []
    assert mvkeys.note_payloads(None, ["a"]) == []


# --------------------------------------------------------------- writing

def _map_with_event(root, note):
    """A one-event map whose event carries the given note."""
    _dump(os.path.join(root, "data", "Map001.json"), {
        "displayName": "Map001",
        "events": [None, {"id": 1, "name": "EV001", "note": note,
                          "pages": []}],
    })


def test_event_note_payloads_are_extracted_too(game, tmp_path):
    """A map event label is drawn above the event - displayed text, not a key."""
    _map_with_event(game, "<LB:\u30de\u30ea\u30fc\u306e\u7814\u7a76\u5ba4><other:x>")
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["LB"])
    entries = by_id(work)
    assert "data/Map001.json#events[1].note#LB[0]" in entries
    assert entries["data/Map001.json#events[1].note#LB[0]"]["ja"] == \
        "\u30de\u30ea\u30fc\u306e\u7814\u7a76\u5ba4"
    assert not any("other" in i for i in entries)


def test_event_note_is_skipped_by_default(game, tmp_path):
    _map_with_event(game, "<LB:\u30de\u30ea\u30fc>")
    work = str(tmp_path / "work")
    mvkeys.extract(game, work)
    assert ".note#" not in " ".join(by_id(work))


def test_bake_writes_an_event_note_payload(game, tmp_path):
    _map_with_event(game, "<LB:\u30de\u30ea\u30fc\u306e\u7814\u7a76\u5ba4>")
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["LB"])
    with io.open(os.path.join(work, "translations.raw.txt"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("@@@data/Map001.json#events[1].note#LB[0]@@@\n"
                     "\u739b\u4e3d\u7684\u7814\u7a76\u5ba4\n")
    rawlib = __import__("translation.rawlib", fromlist=["rawlib"])
    rawlib.to_json(work)
    bake_mod.bake(game, work, apply_unified_font=False)
    out = json.load(io.open(os.path.join(game, "data", "Map001.json"),
                            encoding="utf-8"))
    assert out["events"][1]["note"] == "<LB:\u739b\u4e3d\u7684\u7814\u7a76\u5ba4>"


def test_parse_note_id_round_trip():
    base, tag, index = bake_mod.parse_note_id("[12].note#itemCategory[3]")
    assert (base, tag, index) == ("[12].note", "itemCategory", 3)
    with pytest.raises(bake_mod.BakeError):
        bake_mod.parse_note_id("[12].note#itemCategory")
    with pytest.raises(bake_mod.BakeError):
        bake_mod.parse_note_id("[12].note")


def test_set_note_payload_replaces_only_that_occurrence():
    root = [None, {"note": "<itemCategory:\u63db\u91d1>"
                           "<itemCategory:\u63db\u91d1>"}]
    assert bake_mod.set_note_payload(root, "[1].note#itemCategory[1]",
                                     "\u6362\u91d1") is True
    assert root[1]["note"] == ("<itemCategory:\u63db\u91d1>"
                               "<itemCategory:\u6362\u91d1>")


def test_set_note_payload_keeps_other_tags_and_text():
    root = [None, {"note": "\u5148\u982d<MNKR_SwitchSell>"
                           "<\u62e1\u5f35\u8aac\u660e:\u3042\u3068\u3067>"
                           "<other:x>"}]
    bake_mod.set_note_payload(root, "[1].note#\u62e1\u5f35\u8aac\u660e[0]",
                              "\u8ffd\u52a0\u8bf4\u660e")
    assert root[1]["note"] == ("\u5148\u982d<MNKR_SwitchSell>"
                               "<\u62e1\u5f35\u8aac\u660e:\u8ffd\u52a0\u8bf4\u660e>"
                               "<other:x>")


def test_set_note_payload_refuses_tag_breaking_text():
    root = [None, {"note": "<itemCategory:\u63db\u91d1>"}]
    assert bake_mod.set_note_payload(root, "[1].note#itemCategory[0]",
                                     "\u6362>") is False
    assert root[1]["note"] == "<itemCategory:\u63db\u91d1>"


def test_set_note_payload_reports_missing_path():
    root = [None, {"note": "<itemCategory:\u63db\u91d1>"}]
    assert bake_mod.set_note_payload(root, "[9].note#itemCategory[0]", "x") is False
    assert bake_mod.set_note_payload(root, "[1].note#other[0]", "x") is False
    assert bake_mod.set_note_payload(root, "[1].note#itemCategory[5]", "x") is False


def test_bake_writes_note_payloads_end_to_end(game, tmp_path):
    """prepare --note-tags -> library -> to-json -> bake, like the real run."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["\u62e1\u5f35\u8aac\u660e"])
    ids = [k["id"] for k in mvkeys.load_keys(work)
           if ".note#" in k["id"]]
    assert len(ids) == 2
    lines = ["@@@%s@@@" % key_id for key_id in ids]
    values = ["\u4f24\u5bb3\u65e0\u6cd5\u901a\u8fc7\u7684\u5bf9\u624b\u4e5f\u5b58\u5728\uff0c\u8bf7\u6ce8\u610f",
              "\u88c5\u5907\u540e\u4f1a\u53d8\u91cd"]
    with io.open(os.path.join(work, "translations.raw.txt"), "w",
                 encoding="utf-8", newline="\n") as handle:
        for key_id, value in zip(lines, values):
            handle.write(key_id + "\n" + value + "\n")
    rawlib = __import__("translation.rawlib", fromlist=["rawlib"])
    rawlib.to_json(work)
    bake_mod.bake(game, work, apply_unified_font=False)

    items = json.load(io.open(os.path.join(game, "data", "Items.json"),
                              encoding="utf-8"))
    assert items[1]["note"] == ("<\u62e1\u5f35\u8aac\u660e:"
                                "\u4f24\u5bb3\u65e0\u6cd5\u901a\u8fc7\u7684\u5bf9\u624b"
                                "\u4e5f\u5b58\u5728\uff0c\u8bf7\u6ce8\u610f>"
                                "<MNKR_SwitchSell>")
    armors = json.load(io.open(os.path.join(game, "data", "Armors.json"),
                               encoding="utf-8"))
    assert "\u88c5\u5907\u540e\u4f1a\u53d8\u91cd" in armors[1]["note"]
    # untouched notes stay byte-identical
    assert items[2]["note"] == "<itemCategory:\u63db\u91d1\u30a2\u30a4\u30c6\u30e0>"


def test_bake_note_write_is_idempotent(game, tmp_path):
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["itemCategory"])
    key_id = "data/Items.json#[2].note#itemCategory[0]"
    with io.open(os.path.join(work, "translations.raw.txt"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("@@@%s@@@\n\u6362\u91d1\u7269\u54c1\n" % key_id)
    rawlib = __import__("translation.rawlib", fromlist=["rawlib"])
    rawlib.to_json(work)
    bake_mod.bake(game, work, apply_unified_font=False)
    first = json.load(io.open(os.path.join(game, "data", "Items.json"),
                              encoding="utf-8"))
    bake_mod.bake(game, work, apply_unified_font=False)
    second = json.load(io.open(os.path.join(game, "data", "Items.json"),
                               encoding="utf-8"))
    assert first == second
    assert second[2]["note"] == "<itemCategory:\u6362\u91d1\u7269\u54c1>"


def test_bake_reports_a_note_tag_that_is_gone(game, tmp_path):
    """Id drift must be a reported skip, never a silent wrong write."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["itemCategory"])
    key_id = "data/Items.json#[3].note#itemCategory[1]"
    with io.open(os.path.join(work, "translations.raw.txt"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("@@@%s@@@\n\u6362\u91d1\u7269\u54c1\n" % key_id)
    rawlib = __import__("translation.rawlib", fromlist=["rawlib"])
    rawlib.to_json(work)
    report = bake_mod.bake(game, work, apply_unified_font=False)
    assert report["applied"] == 1
    items = json.load(io.open(os.path.join(game, "data", "Items.json"),
                              encoding="utf-8"))
    assert items[3]["note"] == ("<itemCategory:\u63db\u91d1\u30a2\u30a4\u30c6\u30e0>"
                                "<itemCategory:\u6362\u91d1\u7269\u54c1>")


def test_bake_skips_note_id_when_the_tag_is_gone(game, tmp_path):
    """A note id whose tag vanished from the data is reported, not guessed."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["itemCategory"])
    key_id = "data/Items.json#[2].note#itemCategory[0]"
    with io.open(os.path.join(work, "translations.raw.txt"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("@@@%s@@@\n\u6362\u91d1\u7269\u54c1\n" % key_id)
    rawlib = __import__("translation.rawlib", fromlist=["rawlib"])
    rawlib.to_json(work)
    items = json.load(io.open(os.path.join(game, "data", "Items.json"),
                              encoding="utf-8"))
    items[2]["note"] = "<other:x>"
    _dump(os.path.join(game, "data", "Items.json"), items)
    report = bake_mod.bake(game, work, apply_unified_font=False)
    assert report["skipped"] >= 1
    assert not report["applied"]
    items = json.load(io.open(os.path.join(game, "data", "Items.json"),
                             encoding="utf-8"))
    assert items[2]["note"] == "<other:x>"


def test_bake_overwrites_a_changed_payload_at_the_same_id(game, tmp_path):
    """The id addresses a *position*: like every other key it wins."""
    work = str(tmp_path / "work")
    mvkeys.extract(game, work, note_tags=["itemCategory"])
    key_id = "data/Items.json#[2].note#itemCategory[0]"
    with io.open(os.path.join(work, "translations.raw.txt"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("@@@%s@@@\n\u6362\u91d1\u7269\u54c1\n" % key_id)
    rawlib = __import__("translation.rawlib", fromlist=["rawlib"])
    rawlib.to_json(work)
    items = json.load(io.open(os.path.join(game, "data", "Items.json"),
                              encoding="utf-8"))
    items[2]["note"] = "<itemCategory:\u5225\u306e\u3082\u306e>"
    _dump(os.path.join(game, "data", "Items.json"), items)
    bake_mod.bake(game, work, apply_unified_font=False)
    items = json.load(io.open(os.path.join(game, "data", "Items.json"),
                              encoding="utf-8"))
    assert items[2]["note"] == "<itemCategory:\u6362\u91d1\u7269\u54c1>"
