#!/usr/bin/env python3
"""Unit tests for tools/bake_translation.py - the static-bake step of the
translation pipeline.

Covers the contract documented in AGENTS.md / docs/translation.md:
- EXACT-MATCH replacement only (a string is replaced iff its full text is a
  dict key; no greedy fragment substitution),
- control codes (\\N[x], \\P[x], \\v[x]) stay verbatim,
- the low-coverage gate (< --min-coverage refuses to bake; --force overrides),
- identity entries (v == k with kana) are dropped before baking so they cannot
  shadow per-line fallbacks,
- dangling <TE:name> / <namePop:name> refs are WARNed after the bake,
- located keys (\\x1f<loc> variants) are preferred, bare keys fall back.
"""
import glob
import json
import os
import shutil
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import bake_translation as bake  # noqa: E402


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def make_game(root, maps=None, common_events=None, actors=None, items=None,
              system=None, plugins=None):
    """Minimal synthetic MZ game.  `maps` = {fname: (display_name, events)}.
    Event entries are dicts {id, name, note, pages:[{list:[...]}]}."""
    data = os.path.join(root, "data")
    os.makedirs(data)
    os.makedirs(os.path.join(root, "js"))
    mi = []
    for i, fname in enumerate(sorted(maps or {}), start=1):
        mi.append({"id": i, "name": maps[fname][0] or ("MAP%03d" % i),
                   "expanded": True})
        write_json(os.path.join(data, fname), {
            "@name": fname.replace(".json", ""), "displayName": maps[fname][0],
            "events": maps[fname][1]})
    write_json(os.path.join(data, "MapInfos.json"), mi)
    write_json(os.path.join(data, "CommonEvents.json"), common_events or [])
    write_json(os.path.join(data, "Actors.json"), actors or [])
    write_json(os.path.join(data, "Items.json"), items or [])
    write_json(os.path.join(data, "System.json"), system or {})
    with open(os.path.join(root, "js", "plugins.js"), "w", encoding="utf-8") as f:
        f.write(plugins if plugins is not None
                else "var $plugins = [];\n")
    with open(os.path.join(root, "js", "rmmz_core.js"), "w",
              encoding="utf-8") as f:
        f.write("// core\n")


def text_cmd(text, code=401):
    return {"code": code, "indent": 0, "parameters": [text]}


def page(commands):
    return {"conditions": {}, "list": commands}


def ev(ev_id, name, commands, note=""):
    return {"id": ev_id, "name": name, "note": note, "pages": [page(commands)]}


class TestExactLookup:
    def test_exact_hit(self):
        bake.STATS.update(hit=0, miss=0)
        assert bake.exact("こんにちは", {"こんにちは": "你好"}) == "你好"
        assert bake.STATS["hit"] == 1

    def test_exact_identity_returns_value(self):
        # v == k (with kana) is not a real translation: exact() does NOT count
        # a hit, but it DOES return the unchanged value - which is exactly why
        # main() must drop identity entries before baking (they would SHADOW
        # per-line fallbacks by 'succeeding' with unchanged Japanese).
        bake.STATS.update(hit=0, miss=0)
        assert bake.exact("まだ日本語", {"まだ日本語": "まだ日本語"}) == "まだ日本語"
        assert bake.STATS["hit"] == 0

    def test_exact_miss_counts_kana_string(self):
        bake.STATS.update(hit=0, miss=0)
        assert bake.exact("まだ日本語", {}) is None
        assert bake.STATS["miss"] == 1

    def test_exact_ascii_miss_not_counted(self):
        bake.STATS.update(hit=0, miss=0)
        assert bake.exact("OK", {}) is None
        assert bake.STATS["miss"] == 0

    def test_exact_none(self):
        bake.STATS.update(hit=0, miss=0)
        assert bake.exact(None, {"x": "y"}) is None
        assert bake.STATS["hit"] == 0

    def test_empty_value_never_hits(self):
        # D.get returns "" -> not truthy -> treated as no translation
        bake.STATS.update(hit=0, miss=0)
        assert bake.exact("あ", {"あ": ""}) is None


class TestExactLocPreference:
    """Located keys (s + \\x1f + loc) are preferred; bare key is the fallback."""

    def test_located_key_wins(self):
        bake.STATS.update(hit=0, miss=0)
        D = {"こんにちは": "你好(plain)",
             "こんにちは\x1fMap001.json#ev0#pg0#c0": "你好(located)"}
        v = bake.exact_loc("こんにちは", D, "Map001.json#ev0#pg0#c0")
        assert v == "你好(located)"
        # located hit increments the hit counter once
        assert bake.STATS["hit"] == 1

    def test_bare_key_fallback(self):
        bake.STATS.update(hit=0, miss=0)
        D = {"こんにちは": "你好(plain)"}
        v = bake.exact_loc("こんにちは", D, "Map001.json#ev0#pg0#c0")
        assert v == "你好(plain)"

    def test_located_miss_no_loc(self):
        bake.STATS.update(hit=0, miss=0)
        D = {"こんにちは\x1fSomewhere": "你好"}
        assert bake.exact_loc("こんにちは", D, "") is None

    def test_located_empty_value_falls_back(self):
        bake.STATS.update(hit=0, miss=0)
        D = {"こんにちは": "你好",
             "こんにちは\x1fMap001.json#ev0#pg0#c0": ""}
        v = bake.exact_loc("こんにちは", D, "Map001.json#ev0#pg0#c0")
        assert v == "你好"

    def test_none_returns_none(self):
        assert bake.exact_loc(None, {"x": "y"}, "loc") is None


class TestNoteRefs:
    def test_translate_ref(self):
        refs = []
        out = bake._translate_note_refs("<TE:テンプレ>", {"テンプレ": "模板"}, refs)
        assert out == "<TE:模板>"
        assert refs == [("TE", "模板")]

    def test_untranslated_ref_stays_raw(self):
        refs = []
        out = bake._translate_note_refs("<namePop:むらびと>", {}, refs)
        assert out == "<namePop:むらびと>"
        assert refs == [("namePop", "むらびと")]

    def test_control_code_ref_never_translated(self):
        refs = []
        out = bake._translate_note_refs("<TE:テンプ\\v[3]>", {"テンプ\\v[3]": "模板"}, refs)
        assert out == "<TE:テンプ\\v[3]>"
        assert refs == [("TE", "テンプ\\v[3]")]

    def test_numeric_ref_skipped_entirely(self):
        refs = []
        out = bake._translate_note_refs("<TE:12>", {"12": "十二"}, refs)
        assert out == "<TE:12>"
        assert refs == []  # numeric refs never enter the dangling check

    def test_multiple_refs_in_one_note(self):
        refs = []
        out = bake._translate_note_refs("<TE:A> and <namePop:B>",
                                        {"A": "甲", "B": "乙"}, refs)
        assert out == "<TE:甲> and <namePop:乙>"
        assert refs == [("TE", "甲"), ("namePop", "乙")]


class TestProcessCommands:
    def test_block_exact_match(self):
        cmds = [text_cmd("せりふ1"), text_cmd("せりふ2")]
        D = {"せりふ1\nせりふ2": "对白1\n对白2"}
        bake.STATS.update(hit=0, miss=0)
        bake.process_commands(cmds, D, "Map001.json#ev0#pg0")
        assert cmds[0]["parameters"][0] == "对白1"
        assert cmds[1]["parameters"][0] == "对白2"

    def test_block_shorter_value_pads(self):
        cmds = [text_cmd("せりふ1"), text_cmd("せりふ2")]
        D = {"せりふ1\nせりふ2": "对白"}
        bake.process_commands(cmds, D, "Map001.json#ev0#pg0")
        # second line pads with "" so no command keeps raw Japanese
        assert cmds[1]["parameters"][0] == ""

    def test_per_line_fallback(self):
        cmds = [text_cmd("せりふ1"), text_cmd("せりふ2")]
        D = {"せりふ1": "对白1"}
        bake.process_commands(cmds, D, "Map001.json#ev0#pg0")
        assert cmds[0]["parameters"][0] == "对白1"
        assert cmds[1]["parameters"][0] == "せりふ2"  # untouched

    def test_block_exact_match_longer_value_inserts(self):
        cmds = [text_cmd("せりふ1"), text_cmd("せりふ2")]
        D = {"せりふ1\nせりふ2": "对白1\n对白2\n对白3"}
        bake.process_commands(cmds, D, "Map001.json#ev0#pg0")
        assert [c["parameters"][0] for c in cmds] == ["对白1", "对白2", "对白3"]
        assert cmds[2]["code"] == 401

    def test_choices_translated(self):
        cmds = [{"code": 102, "indent": 0, "parameters": [["はい", "いいえ"], 0, 0, 0]}]
        bake.process_commands(cmds, {"はい": "是", "いいえ": "否"}, "loc")
        assert cmds[0]["parameters"][0] == ["是", "否"]

    def test_control_codes_preserved(self):
        # \\N[1] and \\P[1] and \\v[n] are macros - never translated, and the
        # value keeps them verbatim
        cmds = [text_cmd("こんにちは、\\N[1]")]
        D = {"こんにちは、\\N[1]": "你好，\\N[1]"}
        bake.process_commands(cmds, D, "loc")
        assert cmds[0]["parameters"][0] == "你好，\\N[1]"

    def test_script_line_with_kana_quoted(self):
        cmds = [{"code": 355, "indent": 0,
                 "parameters": ["$gameMessage.add('こんにちは')"]}]
        D = {"$gameMessage.add('こんにちは')": "$gameMessage.add('你好')"}
        bake.process_commands(cmds, D, "loc")
        assert cmds[0]["parameters"][0] == "$gameMessage.add('你好')"


class TestTranslateDataParallel:
    """Review §4.2: the map-level parallel bake path must be byte-identical
    to the legacy single-threaded path (same baked files, same coverage
    totals), with correct per-worker coverage accumulation."""

    def _game(self, tmp_path, n_maps=3, lines_per=2):
        root = str(tmp_path / "game")
        maps = {}
        for i in range(1, n_maps + 1):
            evs = [ev(1, "むらびと%d" % i,
                      [text_cmd("こんにちは%d" % (i * 10 + j))
                       for j in range(lines_per)])]
            maps["Map%03d.json" % i] = ("まち%d" % i, evs)
        make_game(root, maps=maps)
        return root

    def _dict(self):
        return {"むらびと%d" % i: "村民%d" % i for i in range(1, 4)}

    def _bake_and_read(self, root, D, workers):
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=True, workers=workers)
        stats = dict(bake.STATS)
        files = {}
        for p in sorted(glob.glob(os.path.join(root, "data", "Map*.json"))):
            with open(p, encoding="utf-8") as f:
                files[os.path.basename(p)] = json.load(f)
        return stats, files

    def test_parallel_equals_single_threaded(self, tmp_path):
        root1 = self._game(tmp_path, n_maps=4, lines_per=3)
        root2 = str(tmp_path / "game2")
        shutil.copytree(root1, root2)
        D = dict(self._dict())
        D.update({"こんにちは%d" % (i * 10 + j): "你好%d" % (i * 10 + j)
                  for i in range(1, 5) for j in range(3)})
        stats1, files1 = self._bake_and_read(root1, D, workers=None)
        stats2, files2 = self._bake_and_read(root2, D, workers=4)
        assert stats1 == stats2, (stats1, stats2)
        assert set(files1) == set(files2)
        for name in files1:
            assert files1[name] == files2[name]

    def test_parallel_coverage_totals(self, tmp_path):
        root1 = self._game(tmp_path, n_maps=2, lines_per=1)
        root2 = str(tmp_path / "game2")
        shutil.copytree(root1, root2)
        # translate only one line -> coverage below 100%, identical in both
        D = {"こんにちは10": "你好10", "むらびと1": "村民1", "むらびと2": "村民2"}
        stats1, _ = self._bake_and_read(root1, D, workers=None)
        stats2, _ = self._bake_and_read(root2, D, workers=4)
        assert stats1 == stats2
        assert stats1["hit"] > 0 and stats1["miss"] > 0

    def test_parallel_coverage_scan_no_write(self, tmp_path):
        root1 = self._game(tmp_path, n_maps=2, lines_per=1)
        root2 = str(tmp_path / "game2")
        shutil.copytree(root1, root2)
        D = {"こんにちは10": "你好10"}
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root1, D, write=False, workers=4)
        cov = bake.coverage()
        # parallel read-only scan must not write any file
        for p in glob.glob(os.path.join(root2, "data", "Map*.json")):
            with open(p, encoding="utf-8") as f:
                assert "你好" not in f.read()
        assert cov is not None and 0 < cov < 1


class TestTranslateDataEndToEnd:
    def test_exact_match_bake(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("はじまりの村", [ev(1, "むらびと",
                                               [text_cmd("こんにちは")])]),
        })
        D = {"こんにちは": "你好", "むらびと": "村民", "はじまりの村": "起始之村"}
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=True)
        m = json.load(open(os.path.join(root, "data", "Map001.json"),
                           encoding="utf-8"))
        assert m["displayName"] == "起始之村"
        assert m["events"][0]["name"] == "村民"
        assert m["events"][0]["pages"][0]["list"][0]["parameters"][0] == "你好"

    def test_control_codes_kept_verbatim(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [
                text_cmd("こんにちは、\\N[1]"),
                text_cmd("どうしたの？\\P[1]")])]),
        })
        D = {"こんにちは、\\N[1]": "你好，\\N[1]",
             "どうしたの？\\P[1]": "怎么了？\\P[1]"}
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=True)
        m = json.load(open(os.path.join(root, "data", "Map001.json"),
                           encoding="utf-8"))
        lines = [c["parameters"][0]
                 for c in m["events"][0]["pages"][0]["list"]]
        assert lines == ["你好，\\N[1]", "怎么了？\\P[1]"]

    def test_located_key_preferred_over_plain(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [text_cmd("こんにちは")])]),
        })
        D = {"こんにちは": "你好(plain)",
             "こんにちは\x1fMap001.json#ev0#pg0#c0": "你好(located)"}
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=True)
        m = json.load(open(os.path.join(root, "data", "Map001.json"),
                           encoding="utf-8"))
        line = m["events"][0]["pages"][0]["list"][0]["parameters"][0]
        assert line == "你好(located)"

    def test_located_key_with_map_first_file(self, tmp_path):
        # Regression: located keys must resolve even when the map file sorts
        # first among data/*.json (fname must be bound before use).
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [text_cmd("こんにちは")])]),
        })
        D = {"こんにちは\x1fMap001.json#ev0#pg0#c0": "你好(located)"}
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=True)
        m = json.load(open(os.path.join(root, "data", "Map001.json"),
                           encoding="utf-8"))
        line = m["events"][0]["pages"][0]["list"][0]["parameters"][0]
        assert line == "你好(located)"

    def test_display_name_located_key(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("はじまりの村", []),
        })
        D = {"はじまりの村\x1fMap001.json#displayName": "起始之村"}
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=True)
        m = json.load(open(os.path.join(root, "data", "Map001.json"),
                           encoding="utf-8"))
        assert m["displayName"] == "起始之村"

    def test_system_and_db_bake(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [])},
                  items=[{"id": 1, "name": "やくそう",
                          "description": "HPをかいふくする", "note": ""}],
                  system={"terms": {"basic": ["HP", "MP"]},
                          "gameTitle": "ドラゴン",
                          "elements": ["", "ほのお"]})
        D = {"やくそう": "药草", "HPをかいふくする": "恢复HP",
             "ドラゴン": "龙", "ほのお": "火焰"}
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=True)
        items = json.load(open(os.path.join(root, "data", "Items.json"),
                               encoding="utf-8"))
        sysj = json.load(open(os.path.join(root, "data", "System.json"),
                              encoding="utf-8"))
        assert items[0]["name"] == "药草"
        assert items[0]["description"] == "恢复HP"
        # real System.json display fields (``message`` was a VX-Ace-only name;
        # MZ/MV keep their message terms inside ``terms``)
        assert sysj["gameTitle"] == "龙"
        assert sysj["elements"] == ["", "火焰"]

    def test_plugins_js_exact_match(self, tmp_path):
        root = str(tmp_path / "game")
        plugins = ('var $plugins =\n[\n  {"name": "MZ_Shop.js", "status": true,'
                   ' "description": "shop", "parameters": {"title": "ショップ"}}\n];\n')
        make_game(root, maps={"Map001.json": ("", [])}, plugins=plugins)
        D = {"ショップ": "商店"}
        bake.STATS.update(hit=0, miss=0)
        n = bake.translate_plugins(root, D, write=True)
        assert n == 1
        text = open(os.path.join(root, "js", "plugins.js"), encoding="utf-8").read()
        assert "商店" in text
        assert "ショップ" not in text

    def test_plugin_fragment_not_replaced(self, tmp_path):
        # Only a WHOLE-string exact match is replaced - never a fragment
        root = str(tmp_path / "game")
        plugins = ('var $plugins =\n[\n  {"name": "X.js", "status": true,'
                   ' "description": "", "parameters": {"a": "ショップあります"}}\n];\n')
        make_game(root, maps={"Map001.json": ("", [])}, plugins=plugins)
        D = {"ショップ": "商店"}
        bake.STATS.update(hit=0, miss=0)
        n = bake.translate_plugins(root, D, write=True)
        assert n == 0
        text = open(os.path.join(root, "js", "plugins.js"), encoding="utf-8").read()
        assert "ショップあります" in text

    def test_note_refs_translated_and_check(self, tmp_path, caplog):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "テンプレート", [], note="<TE:テンプレート>")]),
        })
        D = {"テンプレート": "模板"}
        bake.STATS.update(hit=0, miss=0)
        with caplog.at_level("WARNING", logger="bake"):
            bake.translate_data(root, D, write=True)
        m = json.load(open(os.path.join(root, "data", "Map001.json"),
                           encoding="utf-8"))
        # the note ref must be translated so it keeps matching the translated
        # event name; the ref resolves to an event name -> no dangling WARN
        assert m["events"][0]["note"] == "<TE:模板>"
        assert not any("dangling" in r.message.lower() for r in caplog.records)


class TestMainCoverageGate:
    def _game_with_lines(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [
                text_cmd("こんにちは"), text_cmd("さようなら"),
                text_cmd("おはよう")])]),
        })
        return root

    def _run_main(self, root, out, trs, *extra, monkeypatch):
        # Hermetic: never resolve a machine-local CJK/JP font (a clean checkout
        # has no registered fonts); font policy must no-op in these tests.
        monkeypatch.setattr(bake.assets, "find_cjk_font", lambda: "")
        monkeypatch.setattr(bake.assets, "find_jp_font", lambda: "")
        argv = ["bake_translation.py", root, out, "--trs", trs] + list(extra)
        monkeypatch.setattr("sys.argv", argv)
        return bake.main()

    def test_low_coverage_refused(self, tmp_path, monkeypatch, capsys):
        root = self._game_with_lines(tmp_path)
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        # only 1 of 3 kana display lines covered -> 33% < 50%
        write_json(trs, {"こんにちは": "你好"})
        code = self._run_main(root, out, trs, monkeypatch=monkeypatch)
        assert code == 1
        assert "REFUSING to bake" in capsys.readouterr().err
        assert not os.path.exists(out)

    def test_min_coverage_adjustable(self, tmp_path, monkeypatch):
        root = self._game_with_lines(tmp_path)
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"こんにちは": "你好", "さようなら": "再见"})
        # 2/3 = 66% passes a 0.5 threshold but fails 0.8
        assert self._run_main(root, out, trs, "--min-coverage", "0.8",
                              monkeypatch=monkeypatch) == 1
        assert not os.path.exists(out)

    def test_force_overrides_refusal(self, tmp_path, monkeypatch):
        root = self._game_with_lines(tmp_path)
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"こんにちは": "你好"})
        self._run_main(root, out, trs, "--force", monkeypatch=monkeypatch)
        assert os.path.isdir(out)
        m = json.load(open(os.path.join(out, "data", "Map001.json"),
                           encoding="utf-8"))
        lines = [c["parameters"][0]
                 for c in m["events"][0]["pages"][0]["list"]]
        assert lines[0] == "你好"
        assert lines[1] == "さようなら"  # uncovered line stays raw

    def test_full_coverage_bakes(self, tmp_path, monkeypatch):
        root = self._game_with_lines(tmp_path)
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"こんにちは": "你好", "さようなら": "再见",
                         "おはよう": "早上好", "むらびと": "村民"})
        self._run_main(root, out, trs, monkeypatch=monkeypatch)
        m = json.load(open(os.path.join(out, "data", "Map001.json"),
                           encoding="utf-8"))
        lines = [c["parameters"][0]
                 for c in m["events"][0]["pages"][0]["list"]]
        assert lines == ["你好", "再见", "早上好"]
        # translation KV archived into out_dir by default
        kv = json.load(open(os.path.join(out, "translation_kv.json"),
                            encoding="utf-8"))
        assert kv == {"こんにちは": "你好", "さようなら": "再见",
                      "おはよう": "早上好", "むらびと": "村民"}

    def test_no_kv_skips_archive(self, tmp_path, monkeypatch):
        root = self._game_with_lines(tmp_path)
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"こんにちは": "你好", "さようなら": "再见",
                         "おはよう": "早上好"})
        self._run_main(root, out, trs, "--no-kv", monkeypatch=monkeypatch)
        assert not os.path.exists(os.path.join(out, "translation_kv.json"))

    def test_identity_entries_dropped(self, tmp_path, monkeypatch):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [
                text_cmd("まだ日本語"), text_cmd("こんにちは"),
                text_cmd("さようなら")])]),
        })
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        # "まだ日本語" is v == k with kana -> identity, must be dropped.  The
        # remaining entries give enough coverage to pass the gate.
        write_json(trs, {"まだ日本語": "まだ日本語", "むらびと": "村民",
                         "こんにちは": "你好", "さようなら": "再见"})
        # --force: the dropped identity line drags measured coverage down, but
        # this test targets identity removal + KV archive, not the gate.
        self._run_main(root, out, trs, "--force", monkeypatch=monkeypatch)
        m = json.load(open(os.path.join(out, "data", "Map001.json"),
                           encoding="utf-8"))
        lines = [c["parameters"][0]
                 for c in m["events"][0]["pages"][0]["list"]]
        # identity entry dropped -> its line stays raw (never shadowed), but
        # real translations still apply; event name still baked
        assert lines == ["まだ日本語", "你好", "再见"]
        assert m["events"][0]["name"] == "村民"
        kv = json.load(open(os.path.join(out, "translation_kv.json"),
                            encoding="utf-8"))
        assert "まだ日本語" not in kv

    def test_identity_does_not_shadow_per_line_fallback(self, tmp_path,
                                                        monkeypatch):
        # A block lookup would 'succeed' with the unchanged Japanese text if
        # the identity block entry survived; dropping it lets per-line
        # fallbacks hit each line.
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [
                text_cmd("せりふ1"), text_cmd("せりふ2"),
                text_cmd("おはよう")])]),
        })
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"せりふ1\nせりふ2": "せりふ1\nせりふ2",  # identity block
                         "せりふ1": "对白1", "せりふ2": "对白2",
                         "おはよう": "早上好", "むらびと": "村民"})
        self._run_main(root, out, trs, monkeypatch=monkeypatch)
        m = json.load(open(os.path.join(out, "data", "Map001.json"),
                           encoding="utf-8"))
        lines = [c["parameters"][0]
                 for c in m["events"][0]["pages"][0]["list"]]
        assert lines == ["对白1", "对白2", "早上好"]

    def test_dangling_te_ref_warns(self, tmp_path, monkeypatch, caplog):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "むらびと", [], note="<TE:テンプレート>")]),
        })
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        # "テンプレート" is not an event name anywhere -> dangling ref
        write_json(trs, {"むらびと": "村民"})
        # --force: the dangling ref is counted as a coverage miss; the point of
        # this test is the dangling WARN, not the gate.
        with caplog.at_level("WARNING", logger="bake"):
            self._run_main(root, out, trs, "--force", monkeypatch=monkeypatch)
        warns = [r.message for r in caplog.records if r.levelno >= 30]
        assert any("dangling name refs" in w for w in warns)
        assert any("<TE:テンプレート>" in w for w in warns)

    def test_no_dangling_warn_when_resolved(self, tmp_path, monkeypatch,
                                            caplog):
        root = str(tmp_path / "game")
        make_game(root, maps={
            "Map001.json": ("", [ev(1, "テンプレート", [], note="<TE:テンプレート>")]),
        })
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"テンプレート": "模板"})
        with caplog.at_level("WARNING", logger="bake"):
            self._run_main(root, out, trs, monkeypatch=monkeypatch)
        warns = [r.message for r in caplog.records if r.levelno >= 30]
        assert not any("dangling name refs" in w for w in warns)

    def test_out_dir_must_differ(self, tmp_path, monkeypatch, capsys):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [])})
        trs = str(tmp_path / "trs.json")
        write_json(trs, {})
        monkeypatch.setattr("sys.argv",
                            ["bake_translation.py", root, root, "--trs", trs])
        assert bake.main() == 1
        assert "must differ" in capsys.readouterr().err

    def test_gate_ignores_strings_outside_the_key_list(self, tmp_path,
                                                       monkeypatch):
        """Regression: kana strings the key list never owns must not gate.

        bake's traversal also looks up the joined block keys it tries before
        the per-line ones, plus every field mvkeys deliberately skips (here:
        animation names and the event name).  Counting those as misses made a
        completely translated build measure a few percent - one real MZ build
        reported 7.3% while 80% of its key list was translated - so the gate
        refused every bake of a finished translation.
        """
        root = self._game_with_lines(tmp_path)
        write_json(os.path.join(root, "data", "Animations.json"),
                   [None] + [{"id": i, "name": "アニメ%d" % i, "frames": []}
                             for i in range(1, 11)])
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"こんにちは": "你好", "さようなら": "再见",
                         "おはよう": "早上好"})
        assert self._run_main(root, out, trs, monkeypatch=monkeypatch) == 0
        assert os.path.isdir(out)
        keys = [e["ja"] for e in bake.mvkeys.keys_of(root)]
        assert keys == ["こんにちは", "さようなら", "おはよう"]
        assert "アニメ1" not in keys and "むらびと" not in keys
        # the metric this replaced (raw traversal lookups, including the block
        # join and the non-key names) would have refused this very bake
        D = json.load(open(trs, encoding="utf-8"))
        bake.STATS.update(hit=0, miss=0)
        bake.translate_data(root, D, write=False)
        assert bake.coverage() < 0.5

    def test_gate_refuses_when_only_non_key_strings_are_translated(
            self, tmp_path, monkeypatch, capsys):
        root = self._game_with_lines(tmp_path)
        write_json(os.path.join(root, "data", "Animations.json"),
                   [None, {"id": 1, "name": "アニメ1", "frames": []}])
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {"アニメ1": "动画1"})
        assert self._run_main(root, out, trs, monkeypatch=monkeypatch) == 1
        assert "REFUSING to bake" in capsys.readouterr().err
        assert not os.path.exists(out)

    def test_gate_skipped_without_data_dir(self, tmp_path, monkeypatch):
        root = os.path.join(str(tmp_path), "game")
        os.makedirs(os.path.join(root, "js"))
        with open(os.path.join(root, "js", "plugins.js"), "w",
                  encoding="utf-8") as handle:
            handle.write("var $plugins = [];\n")
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {})
        assert self._run_main(root, out, trs, monkeypatch=monkeypatch) == 0
        assert os.path.isdir(out)

    def test_system_display_fields_are_baked(self, tmp_path, monkeypatch):
        """Regression: gameTitle / elements / currencyUnit used to be skipped.

        They were extracted as keys, translated, gated and counted as covered,
        but the bake's System.json field list spelled ``element`` (singular)
        and had no ``gameTitle``/``currencyUnit``, so a finished build kept a
        Japanese title screen and Japanese element names at "100% coverage".
        """
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [])}, system={
            "gameTitle": "\u30c9\u30e9\u30b4\u30f3\u30c7\u30a3\u30a2",
            "currencyUnit": "\u30b4\u30fc\u30eb\u30c9",
            "elements": ["", "\u7269\u7406", "\u30c9\u30e9\u30b4\u30f3"],
            "switches": [None, "\u30dc\u30b9\u5165\u308a\u53e3"],
            "terms": {"basic": ["\u30ec\u30d9\u30eb", "\u7d4c\u9a13\u5024"]},
        })
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {
            "\u30c9\u30e9\u30b4\u30f3\u30c7\u30a3\u30a2": "\u9f99\u4e4b\u8fea\u4e9a",
            "\u30b4\u30fc\u30eb\u30c9": "\u91d1\u5e01",
            "\u7269\u7406": "\u7269\u7406",
            "\u30c9\u30e9\u30b4\u30f3": "\u9f99",
            "\u30dc\u30b9\u5165\u308a\u53e3": "Boss\u5165\u53e3",
            "\u30ec\u30d9\u30eb": "\u7b49\u7ea7",
            "\u7d4c\u9a13\u5024": "\u7ecf\u9a8c\u503c",
        })
        assert self._run_main(root, out, trs, monkeypatch=monkeypatch) == 0
        baked = json.load(open(os.path.join(out, "data", "System.json"),
                              encoding="utf-8"))
        assert baked["gameTitle"] == "\u9f99\u4e4b\u8fea\u4e9a"
        assert baked["currencyUnit"] == "\u91d1\u5e01"
        assert baked["elements"][2] == "\u9f99"
        assert baked["switches"][1] == "Boss\u5165\u53e3"
        assert baked["terms"]["basic"] == ["\u7b49\u7ea7", "\u7ecf\u9a8c\u503c"]


class TestKeyCoverage:
    """The gate's metric: one key entry = one vote."""

    def test_counts_each_key_entry(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [ev(1, "むらびと", [
            text_cmd("こんにちは"), text_cmd("こんにちは"),
            text_cmd("こんにちは"), text_cmd("さようなら")])])})
        covered, total, missing = bake.key_coverage(root,
                                                   {"こんにちは": "你好"})
        # a repeated translated line must not mask an untranslated one
        assert (covered, total) == (3, 4)
        assert missing == ["さようなら"]

    def test_identity_value_is_not_coverage(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [ev(1, "ev", [
            text_cmd("おはよう")])])})
        # an empty value is 'no translation' as far as the dict is concerned
        assert bake.key_coverage(root, {"おはよう": ""})[0] == 0

    def test_game_without_keys_is_zero_total(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, maps={"Map001.json": ("", [])})
        assert bake.key_coverage(root, {}) == (0, 0, [])

    def test_missing_data_dir_raises(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            bake.key_coverage(str(tmp_path / "nope"), {})


class TestTextKeyInlining:
    """Repacks that keep display text in a runtime table (MTool "mount
    translation", a csv text database read through Node's ``fs``) carry
    ``\\T[id]`` keys in data/ instead of text.  The bake inlines them from
    the shipped table + dictionary: without it the build draws the key."""

    def _game(self, tmp_path):
        root = str(tmp_path / "game")
        make_game(root, system={"terms": {"commands": ["\\T[SIS1]",
                                                       "\\T[SIS2]"]}},
                  items=[None, {"id": 1, "name": "\\T[N001]",
                                "description": "\\T[W001]", "note": ""}])
        os.makedirs(os.path.join(root, "csv"), exist_ok=True)
        with open(os.path.join(root, "csv", "UI.csv"), "w",
                  encoding="utf-8") as f:
            f.write("id,who,tw,cn,en\n"
                    "SIS1,コマンド,初めから,新游戏,New game\n"
                    "SIS2,コマンド,つづき,继续,Continue\n"
                    "W001,名前,剣,,Sword\n")
        write_json(os.path.join(root, "翻译文件.json"), {
            "剣": "剑",
            "N001,名前,ルシア,露西娅,Lucia": "N001,姓名,露西娅,Lucia",
        })
        return root

    def _run(self, root, out, trs, *extra, monkeypatch):
        monkeypatch.setattr(bake.assets, "find_cjk_font", lambda: "")
        monkeypatch.setattr(bake.assets, "find_jp_font", lambda: "")
        argv = ["bake_translation.py", root, out, "--trs", trs] + list(extra)
        monkeypatch.setattr("sys.argv", argv)
        return bake.main()

    def test_bake_inlines_keys(self, tmp_path, monkeypatch):
        root = self._game(tmp_path)
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {})
        assert self._run(root, out, trs, monkeypatch=monkeypatch) == 0
        system = json.load(open(os.path.join(out, "data", "System.json"),
                                encoding="utf-8"))
        assert system["terms"]["commands"] == ["新游戏", "继续"]
        items = json.load(open(os.path.join(out, "data", "Items.json"),
                              encoding="utf-8"))
        assert items[1]["name"] == "露西娅"          # table 'cn' column
        assert items[1]["description"] == "剑"        # japanese -> dict pair

    def test_no_text_keys_flag_keeps_them(self, tmp_path, monkeypatch):
        root = self._game(tmp_path)
        out = str(tmp_path / "out")
        trs = str(tmp_path / "trs.json")
        write_json(trs, {})
        assert self._run(root, out, trs, "--no-text-keys",
                         monkeypatch=monkeypatch) == 0
        system = json.load(open(os.path.join(out, "data", "System.json"),
                                encoding="utf-8"))
        assert system["terms"]["commands"] == ["\\T[SIS1]", "\\T[SIS2]"]
