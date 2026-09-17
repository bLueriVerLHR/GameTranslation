#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tools/plugin_json_leaves.py (extract / rebuild / apply).

The subject is the contract: functional *keys* and identifier values inside a
plugin JSON blob stay byte-identical, only display leaves change, and a
rebuilt blob is always re-parseable.
"""
import io
import json
import os

import plain_io
import plugin_json_leaves as pjl

KANA = "\u30c6\u30b9\u30c8"                 # テスト
KANA_MORE = "\u30c6\u30b9\u30c8\u30b7\u30b7"  # テストシシ
ZH = "\u6d4b\u8bd5"


def _write(path, payload):
    """Write a data file (JSON dict or raw text) with LF newlines."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        if isinstance(payload, str):
            handle.write(payload)
        else:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))


def make_game(root, blob=None, flat_name=KANA, code_field=None,
              extra_params=None):
    """A game whose js/plugins.js holds one blob param and one flat param."""
    if blob is None:
        blob = {"title": KANA, "\u30d1\u30c3\u30af\u540d": "d1",
                "list": [{"text": KANA_MORE}]}
    params = {"blob": json.dumps(blob, ensure_ascii=False, separators=(",", ":")),
              "single": flat_name}
    if code_field is not None:
        params["Script"] = code_field
    params.update(extra_params or {})
    plugins = [{"name": "P", "status": True, "description": "", "parameters": params}]
    body = "var $plugins =\n%s;\n" % json.dumps(plugins, ensure_ascii=False)
    _write(os.path.join(root, "js", "plugins.js"), body)
    return root


# ---------------------------------------------------------------- extract

def test_extract_collects_display_leaves(tmp_path):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    assert pjl.cmd_extract(game, work) == 0
    leaves = plain_io.load_json(os.path.join(work, "plugin_leaves.json"))
    assert sorted(leaves) == sorted([KANA, KANA_MORE])
    assert leaves[KANA][0]["param"] == "blob"
    flat = plain_io.load_json(os.path.join(work, "plugin_flat.json"))
    assert [item["string"] for item in flat] == [KANA]
    blobs = plain_io.load_json(os.path.join(work, "plugin_blobs.json"))
    assert len(blobs) == 1


def test_extract_takes_kanji_only_values_under_display_keys(tmp_path):
    game = make_game(str(tmp_path), blob={"Title": "\u653b\u6483"})
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    leaves = plain_io.load_json(os.path.join(work, "plugin_leaves.json"))
    assert list(leaves) == ["\u653b\u6483"]


def test_extract_takes_capital_text_in_nested_window_list(tmp_path):
    """ExtraWindow style: a window label sits in a JSON-in-JSON ``Text``.

    The value is kanji-only Japanese (``\u5f15\u63db\u5238\u6240\u6301\u6570``), so a
    kana-only rule would skip a label the player reads on the HUD - that is the
    real miss this key was added for.
    """
    label = "\u5f15\u63db\u5238\u6240\u6301\u6570\\V[12]"
    inner = json.dumps({"Text": label}, ensure_ascii=False)
    blob = {"WindowList": json.dumps([inner], ensure_ascii=False)}
    game = make_game(str(tmp_path), blob=blob)
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    leaves = plain_io.load_json(os.path.join(work, "plugin_leaves.json"))
    assert label in leaves
    assert list(leaves) == [label]


def test_extract_skips_kanji_only_values_outside_display_keys(tmp_path):
    """Over-extraction guard: same value under a functional key stays out."""
    game = make_game(str(tmp_path), blob={"styleId": "\u8cfc\u8cb7"})
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    assert plain_io.load_json(os.path.join(work, "plugin_leaves.json")) == {}


def test_extract_uses_backticks_in_code_fields(tmp_path):
    """A code field *inside a blob*: only backtick display text is a leaf."""
    blob = {"Script": "return `%s`\u3068 this.x" % KANA}
    game = make_game(str(tmp_path), blob=blob, flat_name="\u653b\u6483")
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    leaves = plain_io.load_json(os.path.join(work, "plugin_leaves.json"))
    assert list(leaves) == [KANA]


def test_extract_keeps_top_level_code_params_flat(tmp_path):
    """A code param that is not JSON has no leaf structure: it stays flat."""
    game = make_game(str(tmp_path), blob={}, flat_name="\u653b\u6483",
                     code_field="return `%s`" % KANA)
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    assert plain_io.load_json(os.path.join(work, "plugin_leaves.json")) == {}
    flat = plain_io.load_json(os.path.join(work, "plugin_flat.json"))
    assert [item["param"] for item in flat] == ["Script"]


def test_extract_honours_exempt(tmp_path, capsys):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    exempt = tmp_path / "exempt.json"
    plain_io.save_json(str(exempt), {KANA: "functional lookup"})
    assert pjl.cmd_extract(game, work, exempt=str(exempt)) == 0
    leaves = plain_io.load_json(os.path.join(work, "plugin_leaves.json"))
    assert KANA not in leaves and KANA_MORE in leaves


def test_extract_ignores_kanji_only_flat_params(tmp_path):
    game = make_game(str(tmp_path), flat_name="\u653b\u6483")
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    assert plain_io.load_json(os.path.join(work, "plugin_flat.json")) == []


# ---------------------------------------------------------------- rebuild

def test_rebuild_without_translations_yields_no_pairs(tmp_path):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    plain_io.save_json(os.path.join(work, "translated.json"), {})
    assert pjl.cmd_rebuild(game, work) == 0
    pairs = plain_io.load_json(os.path.join(work,
                                            "plugin_blobs_translated.json"))
    assert pairs == {}


def test_rebuild_replaces_only_translated_leaves(tmp_path):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    plain_io.save_json(os.path.join(work, "translated.json"),
                       {KANA: ZH, KANA_MORE: ZH + ZH})
    assert pjl.cmd_rebuild(game, work) == 0
    pairs = plain_io.load_json(os.path.join(work,
                                            "plugin_blobs_translated.json"))
    assert len(pairs) == 1
    original, rebuilt = next(iter(pairs.items()))
    assert KANA in original and ZH in rebuilt
    # functional keys and identifier values survive untouched
    assert json.loads(original)["\u30d1\u30c3\u30af\u540d"] == "d1"
    assert json.loads(rebuilt)["\u30d1\u30c3\u30af\u540d"] == "d1"
    assert KANA_MORE not in rebuilt
    assert json.loads(rebuilt)["list"][0]["text"] == ZH + ZH


def test_rebuild_keeps_identity_translations(tmp_path):
    """A leaf translated to itself must not count as a change."""
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    plain_io.save_json(os.path.join(work, "translated.json"), {KANA: KANA})
    pjl.cmd_rebuild(game, work)
    assert plain_io.load_json(os.path.join(work,
                                           "plugin_blobs_translated.json")) == {}


def test_rebuild_reports_dead_translation(tmp_path, capsys):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    plain_io.save_json(os.path.join(work, "translated.json"),
                       {KANA: ZH, "\u5b58\u5728\u3057\u306a\u3044": ZH})
    pjl.cmd_rebuild(game, work)
    assert "dead" in capsys.readouterr().out


def test_decode_encode_round_trips(tmp_path):
    inner = json.dumps({"b": KANA}, ensure_ascii=False, separators=(",", ":"))
    blob = {"a": inner}
    param = json.dumps(blob, ensure_ascii=False, separators=(",", ":"))
    assert pjl.round_trip(param) == param


# ------------------------------------------------------------------ apply

def test_apply_writes_pairs_and_backs_up(tmp_path):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    plain_io.save_json(os.path.join(work, "translated.json"), {KANA: ZH})
    pjl.cmd_rebuild(game, work)
    assert pjl.cmd_apply(game, work) == 0
    text = io.open(os.path.join(game, "js", "plugins.js"),
                   encoding="utf-8").read()
    assert ZH in text and KANA_MORE in text
    assert os.path.exists(os.path.join(game, "js", "plugins.js.bak"))
    # the patched file still parses as a plugin array
    assert json.loads(text[text.index("["):text.rindex("]") + 1])[0]["name"] == "P"


def test_apply_refuses_when_a_pair_matches_nothing(tmp_path, capsys):
    game = make_game(str(tmp_path))
    work = tmp_path / "work"
    work.mkdir()
    plain_io.save_json(str(work / "plugin_blobs_translated.json"),
                       {"original that is absent": "whatever"})
    before = io.open(os.path.join(game, "js", "plugins.js"),
                     encoding="utf-8").read()
    assert pjl.cmd_apply(game, str(work)) == 1
    assert "REFUSING" in capsys.readouterr().out
    after = io.open(os.path.join(game, "js", "plugins.js"),
                    encoding="utf-8").read()
    assert before == after


def test_apply_dry_run_writes_nothing(tmp_path, capsys):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    plain_io.save_json(os.path.join(work, "translated.json"), {KANA: ZH})
    pjl.cmd_rebuild(game, work)
    before = io.open(os.path.join(game, "js", "plugins.js"),
                     encoding="utf-8").read()
    assert pjl.cmd_apply(game, work, dry_run=True) == 0
    assert "dry run" in capsys.readouterr().out
    assert io.open(os.path.join(game, "js", "plugins.js"),
                   encoding="utf-8").read() == before


def test_apply_is_idempotent(tmp_path):
    game = make_game(str(tmp_path))
    work = str(tmp_path / "work")
    pjl.cmd_extract(game, work)
    plain_io.save_json(os.path.join(work, "translated.json"), {KANA: ZH})
    pjl.cmd_rebuild(game, work)
    assert pjl.cmd_apply(game, work) == 0
    after_first = io.open(os.path.join(game, "js", "plugins.js"),
                          encoding="utf-8").read()
    # re-running finds no matching original again -> refuses, changes nothing
    assert pjl.cmd_apply(game, work) == 1
    assert io.open(os.path.join(game, "js", "plugins.js"),
                   encoding="utf-8").read() == after_first


def test_apply_missing_pairs_file_fails(tmp_path, capsys):
    game = make_game(str(tmp_path))
    work = tmp_path / "work"
    work.mkdir()
    assert pjl.cmd_apply(game, str(work)) == 1
    assert "not found" in capsys.readouterr().err


def test_apply_rejects_empty_pairs(tmp_path, capsys):
    game = make_game(str(tmp_path))
    work = tmp_path / "work"
    work.mkdir()
    plain_io.save_json(str(work / "plugin_blobs_translated.json"), {})
    assert pjl.cmd_apply(game, str(work)) == 1
    assert "no {original" in capsys.readouterr().err
