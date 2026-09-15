#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the KAG source-folder -> Tyrano data-folder mapping.

Why this exists: the mapping used to be a hardcoded list of one game's folders
(`bgimage`, `fgimage`, `image`, `bgm`, `sound`, `video`, `rule`), so any game
that named its folders differently had those assets silently dropped - measured
on a real port: 1010 MiB of source produced a 166 MiB build (84% lost).  The
mapping is now a dialect table plus "keep what you do not know under its own
name", and it is overridable per game from the profile.

Coverage:
  positive: known dialect names map to their Tyrano folder; root-level assets
            are placed by extension; a profile override wins.
  negative: junk folders (plugin/patch/mtool/directx/savedata) never become
            assets; the converter's own system files are not overwritten.
  edge: unknown folder kept as-is with a warning, TLG/BMP renamed to .png with
        the right job kind, root config files skipped, nested dirs preserved.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri.kag import assets  # noqa: E402


def build_tree(root, spec, files=()):
    """spec = {dir: {name: b"..."}}, files = [(relpath, b"...")]."""
    for sub, entries in spec.items():
        for name, content in entries.items():
            path = root / sub / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    for rel, content in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def collect(tmp_path, spec, files=(), asset_dirs=None):
    src = tmp_path / "src"
    out = tmp_path / "out_data"
    build_tree(src, spec, files)
    jobs = assets._collect_asset_jobs(str(src), str(out), asset_dirs=asset_dirs)
    # {(dest dir, dest name): kind}
    return {(os.path.relpath(os.path.dirname(d), str(out)).replace(os.sep, "/"),
             os.path.basename(d)): kind for kind, _s, d in jobs}


class TestKnownDialectNames:
    def test_dialect_folders_map_to_tyrano_folders(self, tmp_path):
        got = collect(tmp_path, {
            "bg": {"a.jpg": b"x"},
            "se": {"s.ogg": b"x"},
            "face": {"f.png": b"x"},
            "thumb": {"t.jpg": b"x"},
            "movie": {"m.wmv": b"x"},
            "bgm": {"b.ogg": b"x"},
            "fgimage": {"g.png": b"x"},
        })
        assert set(got) == {
            ("bgimage", "a.jpg"), ("sound", "s.ogg"), ("fgimage", "f.png"),
            ("image", "t.jpg"), ("video", "m.wmv"), ("bgm", "b.ogg"),
            ("fgimage", "g.png")}

    def test_tlg_and_bmp_become_png(self, tmp_path):
        got = collect(tmp_path, {"face": {"f.tlg": b"x", "g.bmp": b"x"}})
        assert ("fgimage", "f.png") in got and got[("fgimage", "f.png")] == "tlg"
        assert ("fgimage", "g.png") in got and got[("fgimage", "g.png")] == "bmp"

    def test_nested_dirs_are_preserved(self, tmp_path):
        got = collect(tmp_path, {"bg": {"sub/deep/a.png": b"x"}})
        assert ("bgimage/sub/deep", "a.png") in got


class TestUnknownAndSkipped:
    def test_unknown_folder_is_kept_under_its_own_name(self, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            got = collect(tmp_path, {"weirdart": {"a.png": b"x"}})
        assert ("weirdart", "a.png") in got
        assert "not in the known layout" in caplog.text

    def test_never_asset_folders_are_skipped(self, tmp_path):
        got = collect(tmp_path, {
            "plugin": {"krmovie.dll": b"x"},
            "patch": {"p.xp3": b"x"},
            "directx": {"d.dll": b"x"},
            "savedata": {"s.sav": b"x"},
            "MTool": {"m.exe": b"x"},
        })
        assert got == {}

    def test_converter_system_files_are_not_overwritten(self, tmp_path):
        got = collect(tmp_path, {"system": {
            "charData.csv": b"x", "Config.tjs": b"x", "KeyConfig.js": b"x"}})
        assert ("system", "charData.csv") in got
        assert ("system", "Config.tjs") not in got
        assert ("system", "KeyConfig.js") not in got


class TestRootLevelAssets:
    def test_root_assets_placed_by_extension(self, tmp_path):
        got = collect(tmp_path, {}, files=[
            ("a0001.ogg", b"x"), ("a0001.ogg.sli", b"x"),
            ("v01.mpg", b"x"), ("cg01.jpg", b"x"), ("bg11.tlg", b"x")])
        assert ("sound", "a0001.ogg") in got
        assert ("sound", "a0001.ogg.sli") in got
        assert ("video", "v01.mpg") in got
        assert ("image", "cg01.jpg") in got
        assert ("image", "bg11.png") in got and got[("image", "bg11.png")] == "tlg"

    def test_root_config_files_are_skipped(self, tmp_path):
        got = collect(tmp_path, {}, files=[
            ("Config.tjs", b"x"), ("Menus.tjs", b"x"), ("macro.ks", b"x"),
            ("charData.csv", b"x"), ("thing.ams", b"x")])
        assert got == {}


class TestOverride:
    def test_profile_override_wins(self, tmp_path):
        got = collect(tmp_path, {"bg": {"a.jpg": b"x"}},
                      asset_dirs={"bg": "image"})
        assert ("image", "a.jpg") in got

    def test_override_is_case_insensitive_on_the_source_name(self, tmp_path):
        got = collect(tmp_path, {"BG": {"a.jpg": b"x"}},
                      asset_dirs={"bg": "image"})
        assert ("image", "a.jpg") in got

    def test_override_can_add_a_folder_for_an_otherwise_unknown_name(
            self, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            got = collect(tmp_path, {"promo": {"a.jpg": b"x"}},
                          asset_dirs={"promo": "image"})
        assert ("image", "a.jpg") in got
        assert "not in the known layout" not in caplog.text


class TestTableSanity:
    def test_every_destination_is_a_tyrano_folder(self):
        allowed = {"bgimage", "fgimage", "image", "bgm", "sound", "video",
                   "system", "font"}
        assert set(assets.DEFAULT_ASSET_DIRS.values()) <= allowed

    def test_root_extension_table_covers_the_media_kinds(self):
        assert set(assets.ROOT_ASSET_EXTS) == {"image", "sound", "video"}
        for exts in assets.ROOT_ASSET_EXTS.values():
            assert all(e.startswith(".") for e in exts)

    def test_no_folder_is_both_known_and_skipped(self):
        overlap = set(assets.DEFAULT_ASSET_DIRS) & set(assets.NON_ASSET_DIRS)
        assert overlap == set(), overlap
