#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/augment_adv_resources.py - ADV text-resource
extraction (walk_resources -> augment) and in-place baking for RPG Maker
MZ games with a custom TextResource plugin (data/resources/<lang>/*.json).
"""
import json
import os

import pytest

import augment_adv_resources as aug

JA1 = "こんにちは"
JA2 = "さようなら"
JA3 = "また会いましょう"
ZH1 = "你好"
ZH2 = "再见"
KANJI_ONLY = "雪風"       # CJK kanji only: never kana-bearing
ASCII = "hello world"
META = "メタデータ"


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def write_work(work_dir, tpl=None, kinds=None, struct=None, ctx=None):
    write_json(os.path.join(work_dir, "template.json"),
               tpl if tpl is not None else {})
    write_json(os.path.join(work_dir, "kinds.json"),
               kinds if kinds is not None else {})
    write_json(os.path.join(work_dir, "structure.json"),
               struct if struct is not None else {"maps": []})
    write_json(os.path.join(work_dir, "context.json"),
               ctx if ctx is not None else {})


def make_resource(game_dir, lang, stem, data):
    write_json(os.path.join(game_dir, "data", "resources", lang,
                            stem + ".json"), data)


# ------------------------------------------------------------ walk_resources

class TestWalkResources:
    def test_story_order_and_filters(self, tmp_path):
        make_resource(tmp_path, "ja-JP", "A",
                      {"a": JA1, "b": ASCII, "metadata": META})
        make_resource(tmp_path, "ja-JP", "B", {"c": JA2})
        items = aug.walk_resources(tmp_path, ["ja-JP"], [], ["B", "A"])
        assert items == [("ja-JP/B", JA2), ("ja-JP/A", JA1)]

    def test_dedup_keep_first(self, tmp_path):
        make_resource(tmp_path, "ja-JP", "A", {"a": JA1, "b": JA1})
        items = aug.walk_resources(tmp_path, ["ja-JP"], [], ["A"])
        assert items == [("ja-JP/A", JA1)]

    def test_tweet_flatten_document_order(self, tmp_path):
        write_json(tmp_path / "data" / "resources" / "tweets.json",
                   {"meta": {"x": "meta-label"},
                    "list": [{"name": "n1", "msg": JA1},
                             [{"msg": JA2}],
                             JA3]})
        items = aug.walk_resources(tmp_path, [], ["tweets.json"], ["dummy"])
        assert items == [("tweets/tweets.json", JA1),
                         ("tweets/tweets.json", JA2),
                         ("tweets/tweets.json", JA3)]

    def test_tweet_duplicates_kept(self, tmp_path):
        write_json(tmp_path / "data" / "resources" / "tweets.json",
                   {"list": [JA1, JA1]})
        items = aug.walk_resources(tmp_path, [], ["tweets.json"], ["dummy"])
        assert items == [("tweets/tweets.json", JA1),
                         ("tweets/tweets.json", JA1)]

    def test_missing_dir_skipped(self, tmp_path):
        assert aug.walk_resources(tmp_path, ["ja-JP"], [], ["A"]) == []

    def test_missing_file_skipped(self, tmp_path):
        make_resource(tmp_path, "ja-JP", "A", {"a": JA1})
        items = aug.walk_resources(tmp_path, ["ja-JP"], [], ["A", "B"])
        assert items == [("ja-JP/A", JA1)]

    def test_non_dict_resource_skipped(self, tmp_path):
        make_resource(tmp_path, "ja-JP", "A", ["list", "not", "object"])
        assert aug.walk_resources(tmp_path, ["ja-JP"], [], ["A"]) == []

    def test_empty_order_raises(self, tmp_path):
        make_resource(tmp_path, "ja-JP", "A", {"a": JA1})
        with pytest.raises(SystemExit):
            aug.walk_resources(tmp_path, ["ja-JP"], [], [])

    def test_multiple_lang_dirs(self, tmp_path):
        make_resource(tmp_path, "ja-JP", "A", {"a": JA1})
        make_resource(tmp_path, "en-US", "A", {"a": "hello"})
        items = aug.walk_resources(tmp_path, ["ja-JP", "en-US"], [], ["A"])
        assert items == [("ja-JP/A", JA1)]


# ----------------------------------------------------------- ordered strings

class TestOrderedKanaStrings:
    def test_document_order_nested(self):
        obj = {"b": {"d": JA2}, "a": [JA1, {"e": JA3}], "c": ASCII}
        assert aug.ordered_kana_strings(obj) == [JA2, JA1, JA3]

    def test_non_kana_ignored(self):
        assert aug.ordered_kana_strings([ASCII, KANJI_ONLY, 42, None]) == []

    def test_empty_object(self):
        assert aug.ordered_kana_strings({}) == []
        assert aug.ordered_kana_strings([]) == []


# ---------------------------------------------------------------- augment

class TestAugment:
    def test_adds_keys_groups_and_context(self, tmp_path):
        work = tmp_path / "work"
        old = "既存のテキスト"
        write_work(work, tpl={old: ""}, kinds={old: "story"},
                   struct={"maps": [{"id": "Map001",
                                     "items": [{"key": old}]}]},
                   ctx={old: {"where": "Map001", "window": []}})
        items = [("ja-JP/A", JA1), ("ja-JP/B", JA2), ("ja-JP/A", JA3)]
        aug.augment(work, items, window=2)

        tpl = json.load(open(work / "template.json", encoding="utf-8"))
        kinds = json.load(open(work / "kinds.json", encoding="utf-8"))
        struct = json.load(open(work / "structure.json", encoding="utf-8"))
        ctx = json.load(open(work / "context.json", encoding="utf-8"))

        assert tpl == {old: "", JA1: "", JA2: "", JA3: ""}
        assert kinds == {old: "story", JA1: "story", JA2: "story",
                         JA3: "story"}
        ids = [m["id"] for m in struct["maps"]]
        assert ids == ["Map001", "ja-JP/A", "ja-JP/B"]
        ja_a = next(m for m in struct["maps"] if m["id"] == "ja-JP/A")
        assert ja_a["items"] == [{"kind": "story", "key": JA1},
                                 {"kind": "story", "key": JA3}]
        assert ctx[JA1]["where"] == "data/resources/ja-JP/A"
        assert ctx[JA1]["window"] == [JA3]          # group neighbour
        assert ctx[JA3]["window"] == [JA1]
        assert ctx[JA2]["window"] == []             # solo group

    def test_existing_key_not_duplicated(self, tmp_path):
        work = tmp_path / "work"
        write_work(work, tpl={JA1: ""}, kinds={JA1: "story"},
                   struct={"maps": [{"id": "Map001",
                                     "items": [{"key": JA1}]}]},
                   ctx={JA1: {"where": "Map001", "window": []}})
        aug.augment(work, [("ja-JP/A", JA1), ("ja-JP/A", JA2)], window=2)
        struct = json.load(open(work / "structure.json", encoding="utf-8"))
        maps = {m["id"]: m for m in struct["maps"]}
        assert len(maps["ja-JP/A"]["items"]) == 1
        assert maps["ja-JP/A"]["items"][0]["key"] == JA2

    def test_window_truncated_and_radius(self, tmp_path):
        work = tmp_path / "work"
        long_key = JA1 + "あ" * 60
        short_key = JA2
        write_work(work)
        aug.augment(work, [("ja-JP/A", long_key),
                          ("ja-JP/A", short_key)], window=2)
        ctx = json.load(open(work / "context.json", encoding="utf-8"))
        assert len(ctx[short_key]["window"][0]) == 45
        assert ctx[short_key]["window"] == [long_key[:45]]

    def test_single_key_group_empty_window(self, tmp_path):
        work = tmp_path / "work"
        write_work(work)
        aug.augment(work, [("ja-JP/A", JA1)], window=2)
        ctx = json.load(open(work / "context.json", encoding="utf-8"))
        assert ctx[JA1]["window"] == []


# ------------------------------------------------------------------ bake

class TestBakeResources:
    def _bake(self, tmp_path, data, trs, min_cov=0.5, force=False,
              lang_dirs=("ja-JP",), tweet_files=()):
        make_resource(tmp_path, "ja-JP", "A", data)
        trs_path = tmp_path / "trs.json"
        write_json(trs_path, trs)
        aug.bake_resources(tmp_path, str(trs_path), min_cov, force,
                           list(lang_dirs), list(tweet_files))
        return json.load(open(tmp_path / "data" / "resources" / "ja-JP"
                              / "A.json", encoding="utf-8"))

    def test_translates_in_place(self, tmp_path):
        out = self._bake(tmp_path, {"a": JA1, "b": {"c": JA2},
                                    "list": [JA3, ASCII],
                                    "metadata": META},
                         {JA1: ZH1, JA2: ZH2, JA3: "回头见"})
        assert out == {"a": ZH1, "b": {"c": ZH2},
                       "list": ["回头见", ASCII], "metadata": META}

    def test_kana_miss_kept_original(self, tmp_path):
        out = self._bake(tmp_path, {"a": JA1, "list": [JA2]},
                         {JA1: ZH1})
        assert out == {"a": ZH1, "list": [JA2]}

    def test_coverage_gate_blocks(self, tmp_path):
        with pytest.raises(SystemExit):
            self._bake(tmp_path, {"a": JA1, "b": JA2, "c": JA3},
                       {JA1: ZH1})   # 1 hit / 3 kana = 33% < 50%

    def test_coverage_gate_force_bypasses(self, tmp_path):
        out = self._bake(tmp_path, {"a": JA1, "b": JA2, "c": JA3},
                         {JA1: ZH1}, force=True)
        assert out == {"a": ZH1, "b": JA2, "c": JA3}

    def test_full_coverage_passes(self, tmp_path):
        out = self._bake(tmp_path, {"a": JA1}, {JA1: ZH1})
        assert out == {"a": ZH1}

    def test_no_kana_coverage_is_full(self, tmp_path):
        out = self._bake(tmp_path, {"a": ASCII, "b": KANJI_ONLY}, {})
        assert out == {"a": ASCII, "b": KANJI_ONLY}

    def test_dict_miss_counts_towards_coverage(self, tmp_path):
        # 1 hit + 1 dict miss = 50%: passes the default 0.5 gate exactly
        out = self._bake(tmp_path, {"a": JA1, "b": JA2}, {JA1: ZH1})
        assert out == {"a": ZH1, "b": JA2}

    def test_tweet_file_baked(self, tmp_path):
        write_json(tmp_path / "data" / "resources" / "tweets.json",
                   {"list": [JA1, JA2]})
        trs_path = tmp_path / "trs.json"
        write_json(trs_path, {JA1: ZH1, JA2: ZH2})
        aug.bake_resources(tmp_path, str(trs_path), 0.5, False,
                           ["ja-JP"], ["tweets.json"])
        out = json.load(open(tmp_path / "data" / "resources"
                             / "tweets.json", encoding="utf-8"))
        assert out == {"list": [ZH1, ZH2]}
