#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the TyranoScript translation work package tools:
build_tyrano_translation.py (extract) and apply_tyrano_translation.py
(write-back)."""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import pytest  # noqa: E402

import build_tyrano_translation as bt  # noqa: E402
import apply_tyrano_translation as at  # noqa: E402

SCENARIO = "scenario"


def make_scenario(root, files):
    """files: {name: text}.  Returns the scenario dir path."""
    d = os.path.join(root, SCENARIO)
    for name in files:
        os.makedirs(os.path.dirname(os.path.join(d, name)), exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(text)
    return d


FIRST = """[call storage="system/tyrano.ks"]
[tb_start_text mode=1 ]
#
～　一日目　導入　～[p]
[_tb_end_text]
[tb_start_text mode=2 ]
#たろう
[font color=lightpink]はじめまして。[l][r]
[_tb_end_text]
[jump storage="Day01_play.ks"]
"""

DAY01 = """[tb_start_text mode=2 ]
#たろう
[font color=lightpink]こんにちは。[l][r]
[_tb_end_text]
[glink  color="black"  text="はい"  ]
[glink  color="black"  text="いいえ"  ]
[position left=0 top=774 ]
"""

SYSTEM = """[tb_start_text mode=1 ]
#
[font color=lightblue]システム。[p]
[_tb_end_text]
"""


class TestBuildWorkPackage:
    def test_build_extracts_blocks_and_attrs(self, tmp_path):
        root = str(tmp_path / "g")
        make_scenario(root, {"first.ks": FIRST, "Day01_play.ks": DAY01,
                             "system/tyrano.ks": SYSTEM})
        work = str(tmp_path / "w")
        bt.build(root, work, None, None)
        tpl = json.load(open(os.path.join(work, "template.json"), encoding="utf-8"))
        assert "～　一日目　導入　～[p]" in tpl
        assert "はじめまして。[l][r]" not in tpl  # kept with its tag line
        assert "[font color=lightpink]はじめまして。[l][r]" in tpl
        assert "#たろう" in tpl
        assert '[glink  color="black"  text="はい"  ]' in tpl
        # comment/blank/unbalanced lines never extracted
        assert not any(";" in k for k in tpl)
        # position line has no text attr -> not extracted
        assert not any(k.startswith("[position") for k in tpl)

    def test_story_order_follows_refs(self, tmp_path):
        root = str(tmp_path / "g")
        make_scenario(root, {"first.ks": FIRST, "Day01_play.ks": DAY01,
                             "Z_orphan.ks": DAY01})
        work = str(tmp_path / "w")
        bt.build(root, work, None, None)
        structure = json.load(open(os.path.join(work, "structure.json"),
                                   encoding="utf-8"))
        order = [m["id"] for m in structure["maps"]]
        assert order.index("first.ks") < order.index("Day01_play.ks")
        assert "Z_orphan.ks" in order  # appended in sorted order

    def test_line_numbers_are_real(self, tmp_path):
        root = str(tmp_path / "g")
        text = (";コメント行\n\n" + FIRST)
        make_scenario(root, {"first.ks": text})
        work = str(tmp_path / "w")
        bt.build(root, work, None, None)
        structure = json.load(open(os.path.join(work, "structure.json"),
                                   encoding="utf-8"))
        items = structure["maps"][0]["items"]
        ctx = json.load(open(os.path.join(work, "context.json"),
                             encoding="utf-8"))
        first = items[0]
        # line 4 in the file (comment=1, blank=2, call=3, tb_start=4... )
        assert first["line"] >= 5
        assert ctx[first["key"]]["where"] == "first.ks:%d" % first["line"]

    def test_speaker_keys_shared_across_files(self, tmp_path):
        root = str(tmp_path / "g")
        make_scenario(root, {"first.ks": FIRST, "Day01_play.ks": DAY01,
                             "system/tyrano.ks": SYSTEM})
        work = str(tmp_path / "w")
        bt.build(root, work, None, None)
        tpl = json.load(open(os.path.join(work, "template.json"), encoding="utf-8"))
        assert "#たろう" in tpl

    def test_no_scenario_dir_fails(self, tmp_path):
        import typer
        root = str(tmp_path / "g")
        os.makedirs(root)
        # The builder raises the framework's exit signal; the CLI returns 1.
        with pytest.raises(typer.Exit) as exc:
            bt.build(root, str(tmp_path / "w"), None, None)
        assert exc.value.exit_code == 1


class TestApplyWorkPackage:
    def _build_package(self, tmp_path):
        root = str(tmp_path / "g")
        make_scenario(root, {"first.ks": FIRST, "Day01_play.ks": DAY01,
                             "system/tyrano.ks": SYSTEM})
        work = str(tmp_path / "w")
        bt.build(root, work, None, None)
        return work

    def test_apply_replaces_all_hits(self, tmp_path):
        work = self._build_package(tmp_path)
        structure = json.load(open(os.path.join(work, "structure.json"),
                                   encoding="utf-8"))
        total_hits = sum(len(m["items"]) for m in structure["maps"])
        tpl = json.load(open(os.path.join(work, "template.json"), encoding="utf-8"))
        # keep tags: translation replaces only the Japanese fragments
        def translate(key):
            head = ""
            if key.startswith("["):
                head = key[:key.index("]") + 1]
            return head + "译文"
        trans = {k: translate(k) for k in tpl}
        json.dump(trans, open(os.path.join(work, "translated.json"), "w",
                              encoding="utf-8"), ensure_ascii=False)
        stats = at.apply(work, os.path.join(work, "scenario"),
                         os.path.join(work, "patch"))
        assert stats["replaced"] == total_hits
        assert stats["untranslated"] == 0
        patched = open(os.path.join(work, "patch", "first.ks"), encoding="utf-8").read()
        assert "たろう" not in patched
        assert "译文" in patched
        # tags preserved: [font color=lightpink] still present
        assert "[font color=lightpink]" in patched
        # speaker line translated
        assert "#たろう" not in patched

    def test_apply_partial_dict_counts_missing(self, tmp_path):
        work = self._build_package(tmp_path)
        structure = json.load(open(os.path.join(work, "structure.json"),
                                   encoding="utf-8"))
        total_hits = sum(len(m["items"]) for m in structure["maps"])
        tpl = json.load(open(os.path.join(work, "template.json"), encoding="utf-8"))
        keys = list(tpl)
        trans = {keys[0]: "第一个"}
        json.dump(trans, open(os.path.join(work, "translated.json"), "w",
                              encoding="utf-8"), ensure_ascii=False)
        stats = at.apply(work, os.path.join(work, "scenario"),
                         os.path.join(work, "patch"))
        assert stats["replaced"] == 1
        assert stats["untranslated"] == total_hits - 1
        assert len(stats["missing"]) == stats["untranslated"]

    def test_apply_preserves_indentation(self, tmp_path):
        root = str(tmp_path / "g")
        text = ("[tb_start_text mode=2 ]\n"
                "    #たろう\n"
                "    [font color=lightpink]インデント本文。[l][r]\n"
                "[_tb_end_text]\n")
        make_scenario(root, {"first.ks": text})
        work = str(tmp_path / "w")
        bt.build(root, work, None, None)
        tpl = json.load(open(os.path.join(work, "template.json"), encoding="utf-8"))
        trans = {k: "译%s" % i for i, k in enumerate(tpl)}
        json.dump(trans, open(os.path.join(work, "translated.json"), "w",
                              encoding="utf-8"), ensure_ascii=False)
        at.apply(work, os.path.join(work, "scenario"), os.path.join(work, "patch"))
        lines = open(os.path.join(work, "patch", "first.ks"),
                     encoding="utf-8").read().splitlines()
        assert lines[1].startswith("    ")
        assert lines[2].startswith("    ")

    def test_apply_cli_end_to_end(self, tmp_path):
        """CLI level: build + apply as subprocesses."""
        root = str(tmp_path / "g")
        make_scenario(root, {"first.ks": FIRST})
        work = str(tmp_path / "w")
        r = subprocess.run([sys.executable, os.path.join(REPO, "tools",
                                                         "build_tyrano_translation.py"),
                            root, work], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        tpl = json.load(open(os.path.join(work, "template.json"), encoding="utf-8"))
        trans = {k: "CLI译%d" % i for i, k in enumerate(tpl)}
        json.dump(trans, open(os.path.join(work, "translated.json"), "w",
                              encoding="utf-8"), ensure_ascii=False)
        r = subprocess.run([sys.executable, os.path.join(REPO, "tools",
                                                         "apply_tyrano_translation.py"),
                            work], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "CLI译" in open(os.path.join(work, "patch", "first.ks"),
                               encoding="utf-8").read()
