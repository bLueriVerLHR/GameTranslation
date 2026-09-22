#!/usr/bin/env python3
"""Tests for unity/rmunite/extract_game.py - RPG Maker Unite text extraction.

The module must be importable WITHOUT UnityPy installed (the import is
deferred into main()), and a bundle it cannot read must be reported, never
skipped silently: a skipped bundle is untranslated story text.
"""
import json
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from unity.rmunite import extract_game as X  # noqa: E402


class _Type:
    def __init__(self, name):
        self.name = name


class _Obj:
    def __init__(self, tname, typetree=None, raise_exc=None):
        self.type = _Type(tname)
        self.path_id = 7
        self._tt = typetree
        self._raise = raise_exc

    def read_typetree(self):
        if self._raise:
            raise self._raise
        return self._tt


class _Env:
    def __init__(self, objects):
        self.objects = objects


def _fake_unitypy(monkeypatch, per_bundle):
    """Install a stub `UnityPy` module; `per_bundle(path)` -> object list."""
    mod = types.ModuleType("UnityPy")

    def load(path):
        if os.path.basename(path).startswith("bad"):
            raise ValueError("corrupt bundle")
        return _Env(per_bundle(path))

    mod.load = load
    monkeypatch.setitem(sys.modules, "UnityPy", mod)
    return mod


def _make_game(tmp_path):
    root = tmp_path / "g" / "g_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"
    root.mkdir(parents=True)
    for name in ("a.bundle", "bad.bundle"):
        (root / name).write_bytes(b"stub")
    return str(tmp_path / "g")


class TestHelpers:
    def test_is_japanese(self):
        assert X.is_japanese("こんにちは")
        assert X.is_japanese("漢字")
        assert not X.is_japanese("Hello")
        assert not X.is_japanese("")

    def test_walk_collect_collects_strings_with_paths(self):
        out = []
        X.walk_collect({"displayName": "第一章", "n": 1,
                        "nested": {"message": "セリフ"}}, "", out, "C")
        assert {r["field"] for r in out} == {".displayName", ".nested.message"}
        assert all(r["class"] == "C" for r in out)

    def test_walk_collect_skips_unity_internals(self):
        out = []
        X.walk_collect({"m_Script": "参照", "text": "本文"}, "", out, "C")
        assert [r["field"] for r in out] == [".text"]

    def test_find_bundle_root(self, tmp_path):
        game = _make_game(tmp_path)
        assert X.find_bundle_root(game).endswith("StandaloneWindows64")

    def test_find_bundle_root_without_unity_data(self, tmp_path):
        empty = tmp_path / "not_unity"
        empty.mkdir()
        assert X.find_bundle_root(str(empty)) is None

    def test_collect_bundles_is_sorted(self, tmp_path):
        root = X.find_bundle_root(_make_game(tmp_path))
        names = [os.path.basename(p) for p in X.collect_bundles(root)]
        assert names == ["a.bundle", "bad.bundle"]


class TestMain:
    def test_extracts_and_reports_unreadable_bundles(self, tmp_path, monkeypatch,
                                                     caplog):
        game = _make_game(tmp_path)
        out = str(tmp_path / "out")

        def per_bundle(_path):
            return [
                _Obj("MonoScript", {"m_ClassName": "EventSO",
                                    "m_Namespace":
                                        "RPGMaker.Codebase.CoreSystem.Helper.SO"}),
                _Obj("MonoBehaviour", {"m_Script": {"m_PathID": 7},
                                       "message": "こんにちは"}),
            ]

        _fake_unitypy(monkeypatch, per_bundle)
        rc = X.main([game, out])
        # a skipped bundle is a real finding: non-zero exit + a WARN
        assert rc == 1
        assert (tmp_path / "out" / "translated_template.json").is_file()
        tmpl = json.loads((tmp_path / "out" / "translated_template.json")
                          .read_text(encoding="utf-8"))
        assert "こんにちは" in tmpl
        warnings = " ".join(r.getMessage() for r in caplog.records
                            if r.levelname == "WARNING")
        assert "bad.bundle" in warnings and "NOT extracted" in warnings

    def test_missing_unity_data_is_an_error(self, tmp_path):
        empty = tmp_path / "plain"
        empty.mkdir()
        assert X.main([str(empty), str(tmp_path / "o")]) == 2

    def test_module_import_does_not_need_unitypy(self):
        assert "UnityPy" not in vars(X)

    def test_cli_requires_two_positional_args(self):
        # a usage error is exit code 2 (returned, not raised: tools return
        # their code so main() stays callable from tests)
        assert X.main([]) == 2
