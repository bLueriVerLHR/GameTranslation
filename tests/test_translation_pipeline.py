#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translation full-pipeline integration test (review report §3.4 / D):
build_translation -> gen_translation_shards -> (simulated agent zh.txt) ->
merge_plain_chunks -> merge_translation -> bake_translation.

The synthetic game carries dialogue, a common event, DB entries, system text
and a plugin parameter.  The "translation" is deterministic: every kana
character in a key is replaced by a Chinese stand-in (control codes,
backslashes, newlines and punctuation preserved), so the produced values are
kana-free, structurally identical and non-identity - the same properties the
agent contract QC enforces.

Assertions on the FINAL baked build:
  - the Japanese dialogue keys are replaced by their Chinese values in
    data/*.json (block join, per-line fallback, DB/displayName/system),
  - no kana residue remains in the translated display strings
    (japanese_utils.KANA over the baked values),
  - the archived translation_kv.json round-trips the dict.
"""
import json
import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import bake_translation as bake  # noqa: E402
import build_translation as bt  # noqa: E402
import gen_translation_shards as gts  # noqa: E402
import japanese_utils  # noqa: E402
import merge_plain_chunks as mpc  # noqa: E402
import merge_translation as mt  # noqa: E402
import plain_io  # noqa: E402


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def text_cmd(text, code=401):
    return {"code": code, "indent": 0, "parameters": [text]}


def page(commands):
    return {"conditions": {}, "list": commands}


def ev(ev_id, name, commands, note=""):
    return {"id": ev_id, "name": name, "note": note, "pages": [page(commands)]}


def make_game(root):
    """Minimal synthetic MZ game with dialogue + a plugin parameter."""
    data = os.path.join(root, "data")
    os.makedirs(data)
    os.makedirs(os.path.join(root, "js"))
    write_json(os.path.join(data, "MapInfos.json"),
               [{"id": 1, "name": "はじまりの村", "expanded": True}])
    write_json(os.path.join(data, "Map001.json"), {
        "@name": "Map001",
        "displayName": "はじまりの村",
        "events": [ev(1, "むらびと", [
            text_cmd("こんにちは"),
            text_cmd("きょうはいい天気だね"),
            {"code": 102, "indent": 0,
             "parameters": [["はい", "いいえ"], 0, 0, 0]},
            {"code": 101, "indent": 0,
             "parameters": ["", 0, 0, 0, "ゆうしゃ"]},
        ])],
    })
    write_json(os.path.join(data, "CommonEvents.json"),
               [{"id": 1, "name": "たいけん", "trigger": 0,
                 "list": [text_cmd("ようこそ")]}])
    write_json(os.path.join(data, "Actors.json"),
               [{"id": 1, "name": "ゆうしゃ"}])
    write_json(os.path.join(data, "Items.json"),
               [{"id": 1, "name": "やくそう",
                 "description": "HPをかいふくする", "note": ""}])
    write_json(os.path.join(data, "System.json"),
               {"terms": {"basic": ["HP", "MP"]},
                "message": ["こんにちは"], "commands": ["ニューゲーム"]})
    plugins = ('var $plugins =\n[\n  {"name": "MZ_Shop.js", "status": true,'
               ' "description": "", "parameters": {"title": "ショップ"}}\n];\n')
    with open(os.path.join(root, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write(plugins)
    return root


# ---------------------------------------------------------------------------
# deterministic translation helper (stands in for the translating subagent)
# ---------------------------------------------------------------------------

# Every character in the kana blocks (incl. ー/・ which build_translation's JA
# regex also flags) maps to a Chinese stand-in so values are never identity
# and carry no canonical-kana residue.
FULL_KANA = frozenset(
    ord(c) for lo, hi in ((0x3040, 0x30FF), (0xFF71, 0xFF9E))
    for c in map(chr, range(lo, hi + 1)))
CHINESE = "你好世界再见朋友今天天气很好清晨早安谢谢一起加油真棒生活"


def to_zh(s):
    """Deterministic kana->Chinese translation preserving everything else."""
    return "".join(CHINESE[ord(c) % len(CHINESE)] if ord(c) in FULL_KANA else c
                   for c in s)


def simulate_agent_chunks(work):
    """Write a zh.txt for every chunk: to_zh of each ja.txt line, saved with
    the same escaping (plain_io), so line counts and control codes match."""
    chunks_dir = os.path.join(work, "chunks")
    wrote = 0
    for p in sorted(os.listdir(chunks_dir)):
        if not p.startswith("chunk_") or not p.endswith(".ja.txt"):
            continue
        num = int(p[len("chunk_"):len("chunk_") + 2])
        keys = plain_io.load_lines(plain_io.ja_path(chunks_dir, num))
        plain_io.save_lines(plain_io.zh_path(chunks_dir, num),
                            [to_zh(k) for k in keys])
        wrote += 1
    return wrote


def run_tool(module, argv):
    """Run a tool's main() with a given argv (monkeypatched sys.argv)."""
    old = sys.argv
    sys.argv = argv
    try:
        module.main()
    finally:
        sys.argv = old


def run_full_pipeline(game, work, out, monkeypatch):
    """Run build -> shards -> simulated agent -> merge -> merge -> bake.
    Returns the dict of (baked Map001.json events[0] pages) for assertions."""
    # 1. build_translation.py <game> <work>
    run_tool(bt, ["build_translation.py", game, work])

    # 2. gen_translation_shards.py <work> (auto sizing)
    run_tool(gts, ["gen_translation_shards.py", work])
    n_chunks = simulate_agent_chunks(work)
    assert n_chunks >= 1, "expected at least one chunk"

    # 3. merge_plain_chunks.py <work>
    run_tool(mpc, ["merge_plain_chunks.py", work])
    assert os.path.isfile(os.path.join(work, "chunks_translated.json"))

    # 4. merge_translation.py <work> --chunks chunks_translated.json
    run_tool(mt, ["merge_translation.py", work,
                  "--chunks", "chunks_translated.json"])
    assert os.path.isfile(os.path.join(work, "translated.json"))

    # 5. bake_translation.py <game> <out> --trs translated.json
    #    (fonts no-op so the worktree never resolves machine-local fonts)
    monkeypatch.setattr(bake.config, "find_cjk_font", lambda: "")
    monkeypatch.setattr(bake.config, "find_jp_font", lambda: "")
    run_tool(bake, ["bake_translation.py", game, out, "--trs",
                    os.path.join(work, "translated.json")])


def walk_json_strings(obj):
    """Yield every leaf string in a JSON tree (display-text scan target)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_json_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_json_strings(v)


class TestFullPipeline:
    def test_build_to_bake_replaces_japanese(self, tmp_path, monkeypatch):
        game = str(tmp_path / "game")
        work = str(tmp_path / "work")
        out = str(tmp_path / "out")
        make_game(game)
        run_full_pipeline(game, work, out, monkeypatch)

        m = json.load(open(os.path.join(out, "data", "Map001.json"),
                           encoding="utf-8"))
        lines = [c["parameters"][0]
                 for c in m["events"][0]["pages"][0]["list"]
                 if c.get("parameters")]
        # block join: "こんにちは\nきょうはいい天気だね" translated as one key
        assert to_zh("こんにちは") in lines
        assert to_zh("きょうはいい天気だね") in lines
        assert "こんにちは" not in lines
        assert "きょうはいい天気だね" not in lines
        # choice options translated
        choices = [c["parameters"][0] for c in m["events"][0]["pages"][0]["list"]
                   if c["code"] == 102]
        assert choices == [[to_zh("はい"), to_zh("いいえ")]]
        # displayName + event name translated
        assert m["displayName"] == to_zh("はじまりの村")
        assert m["events"][0]["name"] == to_zh("むらびと")

    def test_db_system_and_common_events_baked(self, tmp_path, monkeypatch):
        game = str(tmp_path / "game")
        work = str(tmp_path / "work")
        out = str(tmp_path / "out")
        make_game(game)
        run_full_pipeline(game, work, out, monkeypatch)

        items = json.load(open(os.path.join(out, "data", "Items.json"),
                               encoding="utf-8"))
        assert items[0]["name"] == to_zh("やくそう")
        assert items[0]["description"] == to_zh("HPをかいふくする")
        sysj = json.load(open(os.path.join(out, "data", "System.json"),
                              encoding="utf-8"))
        assert sysj["message"] == [to_zh("こんにちは")]
        assert sysj["commands"] == [to_zh("ニューゲーム")]
        ce = json.load(open(os.path.join(out, "data", "CommonEvents.json"),
                            encoding="utf-8"))
        assert ce[0]["list"][0]["parameters"][0] == to_zh("ようこそ")

    def test_plugin_parameter_baked(self, tmp_path, monkeypatch):
        game = str(tmp_path / "game")
        work = str(tmp_path / "work")
        out = str(tmp_path / "out")
        make_game(game)
        run_full_pipeline(game, work, out, monkeypatch)
        text = open(os.path.join(out, "js", "plugins.js"),
                    encoding="utf-8").read()
        assert to_zh("ショップ") in text
        assert "ショップ" not in text

    def test_no_kana_residue_in_baked_build(self, tmp_path, monkeypatch):
        game = str(tmp_path / "game")
        work = str(tmp_path / "work")
        out = str(tmp_path / "out")
        make_game(game)
        run_full_pipeline(game, work, out, monkeypatch)
        # scan every leaf string in data/*.json for canonical kana residue
        for fn in sorted(os.listdir(os.path.join(out, "data"))):
            if not fn.endswith(".json"):
                continue
            data = json.load(open(os.path.join(out, "data", fn),
                                  encoding="utf-8"))
            for s in walk_json_strings(data):
                # keys with kana are a real residue; pure control-code /
                # ASCII (functional data) is fine
                if japanese_utils.KANA.search(s):
                    raise AssertionError(
                        "kana residue in %s: %r" % (fn, s))

    def test_translation_kv_archived(self, tmp_path, monkeypatch):
        game = str(tmp_path / "game")
        work = str(tmp_path / "work")
        out = str(tmp_path / "out")
        make_game(game)
        run_full_pipeline(game, work, out, monkeypatch)
        kv = json.load(open(os.path.join(out, "translation_kv.json"),
                            encoding="utf-8"))
        assert kv
        assert to_zh("こんにちは") in kv.values()
        # identity entries (value == key with kana) are never archived - the
        # real key keeps its kana-free value instead
        assert kv["こんにちは"] == to_zh("こんにちは")
        # the KV round-trips the bake: every kana key has a kana-free value
        for k, v in kv.items():
            if japanese_utils.KANA.search(k):
                assert not japanese_utils.KANA.search(v)

    def test_merge_qc_passes_for_all_chunks(self, tmp_path, monkeypatch):
        # the chain is only green when merge_plain_chunks finds no QC issues;
        # this asserts the produced chunks are QC-clean end to end
        game = str(tmp_path / "game")
        work = str(tmp_path / "work")
        make_game(game)
        run_tool(bt, ["build_translation.py", game, work])
        run_tool(gts, ["gen_translation_shards.py", work])
        simulate_agent_chunks(work)
        chunks_dir = os.path.join(work, "chunks")
        issues_found = []
        for p in sorted(os.listdir(chunks_dir)):
            if not p.startswith("chunk_") or not p.endswith(".ja.txt"):
                continue
            num = int(p[len("chunk_"):len("chunk_") + 2])
            keys, vals = plain_io.load_pair(chunks_dir, num)
            issues, ok = mpc.qc_pair(keys, vals, num)
            assert ok, (num, issues)
            issues_found.extend(issues)
        assert not issues_found

    def test_bake_output_passes_verify(self, tmp_path, monkeypatch,
                                      fake_tools):
        # the baked build must still be a structurally valid game
        game = str(tmp_path / "game")
        work = str(tmp_path / "work")
        out = str(tmp_path / "out")
        make_game(game)
        run_full_pipeline(game, work, out, monkeypatch)
        from rpgmaker import verify
        assert verify.verify_data_json(out) == []
