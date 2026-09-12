#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the tyrano build pipeline: tyrano/build.py (asar unpack +
save backend), tyrano/audio.py (ogg conversion + ref rewrite), tyrano/clean.py
(MTool residue removal), tyrano/verify.py and the serve command's bind host.

The asar steps monkeypatch tyrano.asar.extract so no Node.js is needed in
tests; the audio conversion uses the fake ffmpeg from conftest.
"""
import json
import os
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import pytest  # noqa: E402

from rpgmaker import config as rpg_config  # noqa: E402

from tyrano import audio as ta  # noqa: E402
from tyrano import build as tb  # noqa: E402
from tyrano import clean as tc  # noqa: E402
from tyrano import verify as tv  # noqa: E402

CONFIG = "data/system/Config.tjs"


def write_ks(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_asar_game(root):
    """Synthetic extracted TyranoScript layout (as if asar was unpacked)."""
    write_ks(os.path.join(root, "data", "scenario", "first.ks"),
             '[call storage="system/tyrano.ks"]\n'
             '[tb_start_text mode=1 ]\n#\n導入です。[p]\n[_tb_end_text]\n'
             '[playse storage="se1.mp3" ]\n')
    write_ks(os.path.join(root, "data", "system", "Config.tjs"),
             "configSave=file\n")
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><body>x</body></html>\n")
    os.makedirs(os.path.join(root, "tyrano"), exist_ok=True)
    os.makedirs(os.path.join(root, "data", "sound"), exist_ok=True)
    os.makedirs(os.path.join(root, "data", "bgm"), exist_ok=True)
    with open(os.path.join(root, "data", "sound", "se1.mp3"), "wb") as f:
        f.write(b"\xff\xfb" + b"M" * 1000)
    return root


def make_src_game(root):
    """Electron layout: resources/app.asar + runtime files at root."""
    res = os.path.join(root, "resources")
    os.makedirs(res, exist_ok=True)
    with open(os.path.join(res, "app.asar"), "wb") as f:
        f.write(b"ASAR" * 10)
    for fn in ("main.js", "package.json", "ffmpeg.dll", "icudtl.dat"):
        with open(os.path.join(root, fn), "wb") as f:
            f.write(b"x")
    return os.path.join(res, "app.asar")


class TestBuild:
    def test_find_asar(self, tmp_path):
        root = str(tmp_path)
        asar = make_src_game(root)
        # compare as Paths: the code may join with either separator
        assert Path(tb.find_asar(root)) == Path(asar)
        assert Path(tb.find_asar(root, "resources/app.asar")) == Path(asar)

    def test_find_asar_missing(self, tmp_path):
        root = str(tmp_path / "empty")
        os.makedirs(root)
        assert tb.find_asar(root) is None

    def test_unpack_strips_electron_and_calls_asar(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        asar = make_src_game(root)
        calls = {}
        def fake_extract(src, out):
            calls["src"] = src
            make_asar_game(out)
        monkeypatch.setattr("tyrano.asar.extract", fake_extract)
        work = str(tmp_path / "work")
        tb.unpack_game(root, work)
        assert calls["src"] == asar
        # electron runtime stripped
        for fn in ("main.js", "package.json", "ffmpeg.dll", "icudtl.dat"):
            assert not os.path.exists(os.path.join(work, fn)), fn
        # game files kept
        assert os.path.isfile(os.path.join(work, "index.html"))
        assert os.path.isdir(os.path.join(work, "data", "scenario"))

    def test_fix_save_backend_file_to_webstorage(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        assert tb.fix_save_backend(root)
        text = open(os.path.join(root, CONFIG), encoding="utf-8").read()
        assert "configSave=webstorage" in text
        assert "configSave=file" not in text

    def test_fix_save_backend_already_webstorage(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        write_ks(os.path.join(root, CONFIG), "configSave=webstorage\n")
        assert tb.fix_save_backend(root)

    def test_fix_save_backend_missing_config(self, tmp_path):
        root = str(tmp_path / "no-config")
        os.makedirs(root)
        assert not tb.fix_save_backend(root)

    def test_build_end_to_end(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        asar = make_src_game(root)
        def fake_extract(src, out):
            make_asar_game(out)
        monkeypatch.setattr("tyrano.asar.extract", fake_extract)
        out = str(tmp_path / "out")
        tb.build(root, out)
        assert os.path.isfile(os.path.join(out, "index.html"))
        assert "webstorage" in open(os.path.join(out, CONFIG),
                                    encoding="utf-8").read()


class TestAudio:
    def test_iter_mp3(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        files = [Path(p) for p in ta.iter_mp3(root)]
        assert files == [Path(root) / "data" / "sound" / "se1.mp3"]

    def test_convert_one_creates_ogg_and_removes_mp3(self, tmp_path, fake_tools):
        root = make_asar_game(str(tmp_path))
        mp3 = os.path.join(root, "data", "sound", "se1.mp3")
        ogg = ta.convert_one(os.environ["FFMPEG"], mp3, keep=False)
        assert ogg == os.path.join(root, "data", "sound", "se1.ogg")
        assert os.path.isfile(ogg)
        assert not os.path.isfile(mp3)

    def test_convert_one_keep(self, tmp_path, fake_tools):
        root = make_asar_game(str(tmp_path))
        mp3 = os.path.join(root, "data", "sound", "se1.mp3")
        ogg = ta.convert_one(os.environ["FFMPEG"], mp3, keep=True)
        assert os.path.isfile(ogg) and os.path.isfile(mp3)

    def test_rewrite_script_refs(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        files, refs, dangling = ta.rewrite_script_refs(root)
        assert (files, refs, dangling) == (1, 1, 0)
        text = open(os.path.join(root, "data", "scenario", "first.ks"),
                    encoding="utf-8").read()
        assert 'storage="se1.ogg"' in text
        assert "se1.mp3" not in text

    def test_rewrite_leaves_dangling_mp3_alone(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        write_ks(os.path.join(root, "data", "scenario", "extra.ks"),
                 '[playse storage="nope.mp3" ]\n')
        files, refs, dangling = ta.rewrite_script_refs(root)
        assert (files, refs, dangling) == (1, 1, 1)
        text = open(os.path.join(root, "data", "scenario", "extra.ks"),
                    encoding="utf-8").read()
        assert 'storage="nope.mp3"' in text

    def test_clickse_enterse_rewritten(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        write_ks(os.path.join(root, "data", "scenario", "btn.ks"),
                 '[Button_pluginEX clickse="se1.mp3" enterse="se1.mp3" ]\n')
        _f, refs, _d = ta.rewrite_script_refs(root)
        # btn.ks 2 refs + first.ks 1 ref (storage in make_asar_game)
        assert refs == 3
        text = open(os.path.join(root, "data", "scenario", "btn.ks"),
                    encoding="utf-8").read()
        assert "se1.ogg" in text and "se1.mp3" not in text

    def test_convert_all_counts(self, tmp_path, fake_tools):
        root = make_asar_game(str(tmp_path))
        counts = ta.convert_all(root, workers=1)
        assert counts == {"converted": 1, "failed": 0, "total": 1}
        assert os.path.isfile(os.path.join(root, "data", "sound", "se1.ogg"))

    def test_convert_all_parallel_all_files(self, tmp_path, fake_tools):
        """Every mp3 must be converted even with a wider worker pool (a
        too-small pool or an uncollected future would silently drop files)."""
        root = make_asar_game(str(tmp_path))
        for i in range(2, 8):
            with open(os.path.join(root, "data", "sound", "se%d.mp3" % i),
                      "wb") as f:
                f.write(b"\xff\xfb" + b"M" * 1000)
        counts = ta.convert_all(root, workers=4)
        assert counts == {"converted": 7, "failed": 0, "total": 7}
        oggs = [fn for _d, _s, fns in os.walk(root)
                for fn in fns if fn.endswith(".ogg")]
        assert len(oggs) == 7

    def test_convert_all_raises_when_ffmpeg_missing(self, tmp_path, monkeypatch):
        root = make_asar_game(str(tmp_path))
        monkeypatch.setattr(rpg_config, "find_ffmpeg", lambda: None)
        with pytest.raises(FileNotFoundError):
            ta.convert_all(root, workers=1)

    def test_convert_rewrites_before_conversion(self, tmp_path, fake_tools):
        """convert() must rewrite script refs BEFORE deleting mp3 files,
        otherwise every ref becomes dangling (the mp3 no longer exists
        when the rewrite checks it)."""
        root = make_asar_game(str(tmp_path))
        counts = ta.convert(root, workers=1)
        assert counts["refs"] == 1
        assert counts["converted"] == 1
        assert counts["dangling"] == 0
        text = open(os.path.join(root, "data", "scenario", "first.ks"),
                    encoding="utf-8").read()
        assert 'storage="se1.ogg"' in text and "se1.mp3" not in text

    def test_rewrite_after_conversion_idempotent(self, tmp_path, fake_tools):
        """A re-run of rewrite_script_refs after conversion still fixes
        refs whose mp3 was converted away: the .ogg existence alone is
        enough to rewrite."""
        root = make_asar_game(str(tmp_path))
        ta.convert(root, workers=1)
        # simulate a second run over an already-converted build
        files, refs, dangling = ta.rewrite_script_refs(root)
        assert (files, refs, dangling) == (0, 0, 0)
        text = open(os.path.join(root, "data", "scenario", "first.ks"),
                    encoding="utf-8").read()
        assert 'storage="se1.ogg"' in text


class TestClean:
    def test_removes_mtool_residues(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        for fn in ("winmm.dll", "MTool挂载翻译.txt", "翻译文件.json"):
            with open(os.path.join(root, fn), "w", encoding="utf-8") as f:
                f.write("residue")
        with open(os.path.join(root, "GameBase_sf.sav"), "w") as f:
            f.write("save")
        removed = tc.cleanup_all(root)
        for fn in ("winmm.dll", "MTool挂载翻译.txt", "翻译文件.json",
                   "GameBase_sf.sav"):
            assert not os.path.exists(os.path.join(root, fn)), fn
        assert len(removed) == 4

    def test_keeps_referenced_json(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        with open(os.path.join(root, "translations.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"a": 1}')
        write_ks(os.path.join(root, "data", "scenario", "ref.ks"),
                 '[tb_start_text mode=1 ]\n#\nloads translations.json here[p]\n[_tb_end_text]\n')
        # json referenced by the game is kept
        removed = tc.cleanup_all(root)
        assert os.path.isfile(os.path.join(root, "translations.json"))
        assert removed == []

    def test_unreferenced_json_removed(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        with open(os.path.join(root, "translations.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"a": 1}')
        removed = tc.cleanup_all(root)
        assert not os.path.isfile(os.path.join(root, "translations.json"))
        assert len(removed) == 1

    def test_dry_run_removes_nothing(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        with open(os.path.join(root, "winmm.dll"), "wb") as f:
            f.write(b"x")
        removed = tc.cleanup_all(root, dry_run=True)
        assert len(removed) == 1
        assert os.path.isfile(os.path.join(root, "winmm.dll"))


class TestVerify:
    def test_ok_build_passes(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        ta.rewrite_script_refs(root)
        # fake the ogg conversion: rename the mp3 to ogg (fake ffmpeg output)
        os.rename(os.path.join(root, "data", "sound", "se1.mp3"),
                  os.path.join(root, "data", "sound", "se1.ogg"))
        assert tv.verify(root) == []

    def test_missing_layout(self, tmp_path):
        root = str(tmp_path / "empty")
        os.makedirs(root)
        problems = tv.verify(root, check_png=False)
        assert any("index.html" in p for p in problems)

    def test_file_save_backend_reported(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        problems = tv.verify(root, check_png=False)
        assert any("webstorage" in p for p in problems)

    def test_mp3_ref_left_reported(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        # se1.mp3 still referenced and still on disk -> mp3 refs left
        problems = tv.verify(root, check_png=False)
        assert any("mp3 refs left" in p for p in problems)

    def test_dangling_ogg_ref_reported(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        ta.rewrite_script_refs(root)
        os.rename(os.path.join(root, "data", "sound", "se1.mp3"),
                  os.path.join(root, "data", "sound", "se1.ogg"))
        # drop the audio file: ref becomes dangling
        os.remove(os.path.join(root, "data", "sound", "se1.ogg"))
        problems = tv.verify(root, check_png=False)
        assert any("dangling" in p for p in problems)

    def test_source_downgrades_shared_missing_refs(self, tmp_path):
        """Refs missing in both build and source are source defects, not
        conversion regressions - downgraded when --source is given."""
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        ta.rewrite_script_refs(root)  # se1.mp3 -> se1.ogg (resolvable)
        # dangling ref pointing at a file missing everywhere
        write_ks(os.path.join(root, "data", "scenario", "extra.ks"),
                 '[playse storage="nope.mp3" ]\n')
        problems = tv.verify(root, check_png=False)
        assert any("mp3 refs left" in p or "dangling" in p for p in problems)
        # same layout in source: the ref is missing there too
        source = make_asar_game(str(tmp_path / "src"))
        ta.rewrite_script_refs(source)
        write_ks(os.path.join(source, "data", "scenario", "extra.ks"),
                 '[playse storage="nope.mp3" ]\n')
        problems = tv.verify(root, source=source, check_png=False)
        assert problems == []

    def test_source_keeps_conversion_regressions(self, tmp_path):
        """A ref that exists in source but is dangling in build stays a
        problem (that IS a conversion regression)."""
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        # build: rewrite refs then delete the audio file -> dangling
        ta.rewrite_script_refs(root)
        os.remove(os.path.join(root, "data", "sound", "se1.mp3"))
        # source: file present, refs not rewritten (still mp3, exists)
        source = make_asar_game(str(tmp_path / "src"))
        problems = tv.verify(root, source=source, check_png=False)
        assert any("dangling" in p or "mp3 refs left" in p for p in problems)

    def test_mp3_ref_left_reported(self, tmp_path):
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        with open(os.path.join(root, "data", "sound", "se1.mp3"), "wb") as f:
            f.write(b"x" * 10)
        problems = tv.verify(root, check_png=False)
        assert any("mp3 refs left" in p for p in problems)

    def test_png_over_limit_reported(self, tmp_path):
        from conftest import make_png_bytes
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        os.makedirs(os.path.join(root, "data", "image"), exist_ok=True)
        with open(os.path.join(root, "data", "image", "big.png"), "wb") as f:
            f.write(make_png_bytes(5000, 100))
        problems = tv.verify(root)
        assert any("5000" in p for p in problems)

    def test_png_within_limit_ok(self, tmp_path):
        from conftest import make_png_bytes
        root = make_asar_game(str(tmp_path))
        tb.fix_save_backend(root)
        os.makedirs(os.path.join(root, "data", "image"), exist_ok=True)
        with open(os.path.join(root, "data", "image", "ok.png"), "wb") as f:
            f.write(make_png_bytes(100, 100))
        problems = tv.verify(root)
        assert not any("png over 4096" in p for p in problems)

