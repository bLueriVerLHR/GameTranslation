#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/scenario_common.py - the shared glue of the
scenario-file translation chain builders (build_ks_translation /
build_tyrano_translation).

Covers the minimal template-method convergence (review §5): the duplicated,
low-risk helpers shared by both builders must behave exactly as the
per-file code they replaced - scenario dir discovery, storage-name
resolution, work-package writing (template/kinds/structure/context + engine
meta + scenario copy) - and a full build_ks_translation smoke run must
produce the documented outputs.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, ".."))  # repo root for kirikiri pkg

import scenario_common as sc  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestFindScenarioDir:
    def test_explicit_wins(self, tmp_path):
        root = tmp_path / "g"
        (root / "scenario").mkdir(parents=True)
        (root / "System" / "Scenario").mkdir(parents=True)
        # explicit path must be returned even when a candidate also exists
        got = sc.find_scenario_dir(str(root), "System/Scenario",
                                   ("scenario",))
        assert Path(got) == root / "System" / "Scenario"

    def test_candidates_order(self, tmp_path):
        root = tmp_path / "g"
        (root / "scenario").mkdir(parents=True)
        assert sc.find_scenario_dir(str(root), None,
                                    ("scenario", "System/Scenario")) == str(root / "scenario")

    def test_missing_returns_none(self, tmp_path):
        root = tmp_path / "g"
        root.mkdir()
        assert sc.find_scenario_dir(str(root), None, ("scenario",)) is None
        assert sc.find_scenario_dir(str(root), "nope", ("scenario",)) is None


class TestResolveStorage:
    def test_adds_extension(self):
        assert sc.resolve_storage("foo") == "foo.ks"

    def test_keeps_extension(self):
        assert sc.resolve_storage("foo.ks") == "foo.ks"
        assert sc.resolve_storage("Foo.KS") == "Foo.KS"


class TestSaveJson:
    def test_writes_file(self, tmp_path):
        sc.save_json(str(tmp_path), "x.json", {"a": "你好"})
        data = json.load(open(str(tmp_path / "x.json"), encoding="utf-8"))
        assert data == {"a": "你好"}


class TestWriteWorkPackage:
    def _package(self, tmp_path):
        work = tmp_path / "w"
        src = tmp_path / "g" / "scenario"
        write(str(src / "a.ks"), "*a\nこんにちは。\n")
        n = sc.write_work_package(str(work), {"k1": ""}, {"k1": "story"},
                                  [{"id": "a.ks", "items": []}],
                                  {"k1": {"where": "a.ks:2"}},
                                  "ks_meta.json",
                                  {"game_dir": str(tmp_path / "g")}, str(src))
        return work, n

    def test_all_outputs(self, tmp_path):
        work, n = self._package(tmp_path)
        assert n == 1
        for name in ("template.json", "kinds.json", "structure.json",
                     "context.json", "ks_meta.json"):
            assert (work / name).is_file(), name
        tpl = json.load(open(str(work / "template.json"), encoding="utf-8"))
        assert tpl == {"k1": ""}
        struct = json.load(open(str(work / "structure.json"), encoding="utf-8"))
        assert struct == {"maps": [{"id": "a.ks", "items": []}]}
        # scenario copied for later patching
        assert (work / "scenario" / "a.ks").is_file()

    def test_replaces_existing_scenario(self, tmp_path):
        work = tmp_path / "w"
        src = tmp_path / "g" / "scenario"
        write(str(src / "a.ks"), "こんにちは\n")
        # stale scenario dir with junk must be replaced
        write(str(work / "scenario" / "stale.ks"), "old")
        n = sc.write_work_package(str(work), {"k": ""}, {"k": "story"},
                                  [], {}, "m.json", {}, str(src))
        assert n == 1
        assert not (work / "scenario" / "stale.ks").exists()
        assert (work / "scenario" / "a.ks").exists()


class TestBuildKsSmoke:
    """build_ks_translation.py had no dedicated tests; a smoke run over a
    minimal scenario tree protects the refactor onto scenario_common."""

    def test_build_produces_work_package(self, tmp_path):
        import build_ks_translation as ks
        root = tmp_path / "g"
        sc_dir = root / "scenario"
        write(str(sc_dir / "start.ks"),
              "*start\nこんにちは、世界。[l]\n[jump storage=\"next.ks\"]\n")
        write(str(sc_dir / "next.ks"), "*next\nまた会おう。[l]\n")
        work = tmp_path / "w"
        n = ks.build(str(root), str(work), None, None)
        assert n == 2
        tpl = json.load(open(str(work / "template.json"), encoding="utf-8"))
        assert "こんにちは、世界。[l]" in tpl
        assert "また会おう。[l]" in tpl
        struct = json.load(open(str(work / "structure.json"), encoding="utf-8"))
        order = [m["id"] for m in struct["maps"]]
        assert order.index("start.ks") < order.index("next.ks")
        meta = json.load(open(str(work / "ks_meta.json"), encoding="utf-8"))
        assert meta["scenario_dir"] == str(sc_dir)
        assert (work / "scenario" / "start.ks").is_file()

    def test_no_scenario_dir_raises(self, tmp_path):
        import typer
        import build_ks_translation as ks
        root = tmp_path / "g"
        root.mkdir()
        # A missing scenario dir is a failure raised from the builder: the
        # CLI turns it into exit code 1 (tools return codes now, so the
        # helper signals it the way the framework does).
        with pytest.raises(typer.Exit) as exc:
            ks.build(str(root), str(tmp_path / "w"), None, None)
        assert exc.value.exit_code == 1

    def test_code_block_bodies_never_become_keys(self, tmp_path):
        import build_ks_translation as ks
        root = tmp_path / "g"
        sc_dir = root / "scenario"
        # Both dialects in one file, plus the line numbers of the surviving
        # lines (the write-back step keys on them, so they must stay true to
        # the source even when lines are dropped).
        write(str(sc_dir / "start.ks"),
              "*start\n"              # 1
              "ようこそ。[l]\n"        # 2
              "[iscript]\n"            # 3
              "var x = 1;\t// 本文ではない\n"   # 4
              "// コメント\n"           # 5
              "[endscript]\n"          # 6
              "@iscript\n"             # 7
              "var y = 2;\t// @ 方言のコード\n"  # 8
              "@endscript\n"           # 9
              "本文の続き。[l]\n")     # 10
        work = tmp_path / "w"
        n = ks.build(str(root), str(work), None, None)
        assert n == 2
        tpl = json.load(open(str(work / "template.json"), encoding="utf-8"))
        assert "ようこそ。[l]" in tpl and "本文の続き。[l]" in tpl
        assert not [k for k in tpl if "var " in k or k.startswith("//")]
        struct = json.load(open(str(work / "structure.json"), encoding="utf-8"))
        items = [i for m in struct["maps"] for i in m["items"]
                 if i["key"] == "本文の続き。[l]"]
        assert items and items[0]["line"] == 10
