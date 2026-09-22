#!/usr/bin/env python3
"""Unit tests for kirikiri/pipeline.py - the generic KAG3 port pipeline.

The archive builders come from test_xp3tool.py (byte-level, hermetic), so no
game data is needed.  Coverage:

  positive: archive priority order, profile path resolution, probe on a healthy
            archive, layered unpack (later archive overrides), verify on a clean
            build, ref resolution with and without file extensions.
  negative: protected archive is refused (and leaves no tree), unreadable
            archive is reported, missing index.html / no scenarios / bad iscript
            fail, unknown CLI argument exits 2.
  edge: numeric patch revisions sort numerically, explicit archive order
            override, kana residue is a warning unless --strict, dynamic
            storage refs are ignored, unpack is skipped when src/ exists.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_xp3tool import junk, make_archive, obfuscated_names  # noqa: E402

from kirikiri import pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_source(root, spec):
    """root/<name>.xp3 for each name -> [(file, content)] in `spec`."""
    src = root / "game"
    src.mkdir(parents=True, exist_ok=True)
    for name, files in spec.items():
        (src / name).write_bytes(make_archive(files))
    return src


def write_profile(slot, source, archives="auto", **convert):
    slot.mkdir(parents=True, exist_ok=True)
    data = {
        "code": slot.name,
        "source": str(source).replace("\\", "/"),
        "archives": archives,
        "engine": "eng",
        "src": "src",
        "out": "out",
        "convert": convert,
    }
    path = slot / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def make_build(root, scenario_body, extra=()):
    build = root / "build"
    (build / "data" / "scenario").mkdir(parents=True, exist_ok=True)
    (build / "index.html").write_text("<html></html>", encoding="utf-8")
    (build / "data" / "scenario" / "first.ks").write_text(
        scenario_body, encoding="utf-8")
    for rel in extra:
        path = build / "data" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    return build


# ---------------------------------------------------------------------------
# archive order
# ---------------------------------------------------------------------------

class TestArchiveOrder:
    def test_engine_priority_order(self):
        names = ["voice.xp3", "patch_append2.xp3", "data.xp3",
                 "patch@r1071.xp3", "char.xp3", "patch.xp3",
                 "patch_append10.xp3", "patch@r940.xp3"]
        assert pipeline.order_archives(names) == [
            "data.xp3", "patch.xp3",
            "patch@r940.xp3", "patch@r1071.xp3",
            "patch_append2.xp3", "patch_append10.xp3",
            "char.xp3", "voice.xp3"]

    def test_patch_revisions_sort_numerically(self):
        """patch@r1071 must come after patch@r940 (not lexicographically)."""
        assert (pipeline.archive_sort_key("patch@r940.xp3")
                < pipeline.archive_sort_key("patch@r1071.xp3"))
        assert (pipeline.archive_sort_key("patch_append2.xp3")
                < pipeline.archive_sort_key("patch_append10.xp3"))

    def test_case_insensitive_and_unknown_last(self):
        assert pipeline.archive_sort_key("DATA.XP3")[0] == 0
        assert pipeline.archive_sort_key("zzz.xp3")[0] == 4
        assert pipeline.order_archives(["zzz.xp3", "data.xp3"])[0] == "data.xp3"

    def test_list_archives_filters_and_reports_missing_dir(self, tmp_path):
        (tmp_path / "a.xp3").write_bytes(b"x")
        (tmp_path / "b.txt").write_bytes(b"x")
        assert pipeline.list_archives(str(tmp_path)) == ["a.xp3"]
        with pytest.raises(FileNotFoundError):
            pipeline.list_archives(str(tmp_path / "nope"))


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------

class TestProfile:
    def test_slot_and_repo_relative_paths(self, tmp_path):
        slot = tmp_path / "slots" / "gg"
        path = write_profile(slot, "E:/Games/x", video_dir="media/webm",
                             state_overrides="state/g.json")
        prof = pipeline.load_profile(path)
        # src/out are relative to the profile's own directory (the slot)
        assert prof["_src"] == str(slot / "src")
        assert prof["_out"] == str(slot / "out")
        # repo-ish inputs are relative to the repository root
        assert prof["_engine"] == os.path.join(pipeline.REPO_ROOT, "eng")
        assert prof["_convert"]["video_dir"] == os.path.join(
            pipeline.REPO_ROOT, "media", "webm")
        assert prof["_convert"]["state_overrides"] == os.path.join(
            pipeline.REPO_ROOT, "state", "g.json")

    def test_absolute_paths_are_kept(self, tmp_path):
        slot = tmp_path / "s"
        prof = pipeline.load_profile(write_profile(slot, str(tmp_path / "g")))
        assert os.path.normpath(prof["_source"]) == os.path.normpath(
            str(tmp_path / "g"))
        assert prof["_archives"] == "auto"
        assert prof["_convert"]["title_jump"] is None

    def test_archives_override_is_kept(self, tmp_path):
        slot = tmp_path / "s"
        prof = pipeline.load_profile(
            write_profile(slot, "E:/Games/x", archives=["data.xp3"]))
        assert prof["_archives"] == ["data.xp3"]

    def test_missing_profile_exits_two(self, tmp_path, capsys):
        assert pipeline.main(["unpack", str(tmp_path / "nope.json")]) == 2
        assert "no such profile" in capsys.readouterr().err

    def test_bad_json_exits_two(self, tmp_path, capsys):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        assert pipeline.main(["unpack", str(p)]) == 2
        assert "bad profile" in capsys.readouterr().err

    def test_bom_profile_is_accepted(self, tmp_path):
        """Windows tools write BOMs; a profile with one must still load.

        The assertion is about the load, not about how `E:/Games/x` resolves:
        that spelling is absolute on Windows (kept) and repo-relative on POSIX
        (joined to `REPO_ROOT`), and the previous 
        ``normpath(...) == normpath("E:/Games/x")`` spelling only held on the
        platform it was written on, so the Linux coverage job failed with
        ``'/home/runner/.../E:/Games/x' == 'E:/Games/x'``.
        """
        p = tmp_path / "p.json"
        p.write_text(json.dumps({"source": "E:/Games/x"}),
                     encoding="utf-8-sig")
        prof = pipeline.load_profile(str(p))
        assert prof["_source"], "a BOM must not stop the profile from loading"
        assert prof["_source"].replace("\\", "/").endswith("E:/Games/x")
        assert prof["_slot"] == str(tmp_path)


class TestDefaultFonts:
    def test_picks_a_font(self, tmp_path, monkeypatch):
        """The font directory is local private data, so the positive case
        supplies its own fixture instead of reading the machine.

        (Asserting on the real registered-font directory made the default
        suite fail on any clean checkout or CI runner.)
        """
        font_dir = tmp_path / "fonts"
        font_dir.mkdir()
        (font_dir / "Common.otf").write_bytes(b"OTTO")
        monkeypatch.setattr(pipeline, "FONT_DIR", str(font_dir))
        fonts = pipeline.default_fonts()
        assert fonts and fonts[0].endswith((".otf", ".ttf"))
        assert os.path.basename(fonts[0]) == "Common.otf"

    def test_missing_font_dir_warns(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(pipeline, "FONT_DIR", str(tmp_path / "empty"))
        with caplog.at_level("WARNING"):
            assert pipeline.default_fonts() is None
        assert "unified-font policy is NOT applied" in caplog.text


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

class TestProbe:
    def test_healthy_archive(self, tmp_path):
        src = make_source(tmp_path, {"data.xp3": [
            ("data/scenario/first.ks", b"*start\r\n")] + [
            ("bgimage/cg%02d.png" % i, junk(64, i)) for i in range(24)]})
        info = pipeline.probe_archive(str(src / "data.xp3"))
        assert info["verdict"] == "ok"
        assert info["entries"] == 25
        assert info["ext_ratio"] == 1.0

    def test_protected_archive_is_flagged(self, tmp_path):
        src = make_source(tmp_path, {"data.xp3": [
            (n, junk(96, i)) for i, n in enumerate(obfuscated_names(24))]})
        info = pipeline.probe_archive(str(src / "data.xp3"))
        assert info["verdict"] == "protected"
        assert "protected variant" in info["detail"]

    def test_unreadable_archive_reports_the_error(self, tmp_path):
        src = tmp_path / "game"
        src.mkdir()
        (src / "data.xp3").write_bytes(b"garbage-data")
        info = pipeline.probe_archive(str(src / "data.xp3"))
        assert info["verdict"] == "error"
        assert "bad magic" in info["detail"]

    def test_usable_archives_splits_ok_and_refusals(self, tmp_path):
        src = make_source(tmp_path, {
            "data.xp3": [("data/scenario/first.ks", b"*start\r\n")] + [
                ("bgimage/cg%02d.png" % i, junk(64, i)) for i in range(24)],
            "patch.xp3": [(n, junk(96, i))
                          for i, n in enumerate(obfuscated_names(24))]})
        usable, refusals = pipeline.usable_archives(str(src))
        assert usable == ["data.xp3"]
        assert [r[0] for r in refusals] == ["patch.xp3"]

    def test_cli_json_output(self, tmp_path, capsys):
        src = make_source(tmp_path, {"data.xp3": [
            ("a.png", b"x")]})
        assert pipeline.main(["probe", str(src), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["archives"][0]["verdict"] == "ok"

    def test_cli_missing_folder_exits_two(self, tmp_path, capsys):
        assert pipeline.main(["probe", str(tmp_path / "nope")]) == 2
        assert "not a folder" in capsys.readouterr().err

    def test_cli_no_archives_exits_one(self, tmp_path):
        (tmp_path / "empty").mkdir()
        assert pipeline.main(["probe", str(tmp_path / "empty")]) == 1

    def test_write_profile_skeleton(self, tmp_path):
        src = make_source(tmp_path, {"data.xp3": [("a.png", b"x")]})
        out = tmp_path / "profile.json"
        assert pipeline.main(
            ["probe", str(src), "--write-profile", str(out), "--quiet"]) == 0
        skeleton = json.loads(out.read_text(encoding="utf-8"))
        assert skeleton["archives"] == "auto"
        assert skeleton["src"] == "src"
        assert skeleton["convert"]["video_fit"] == "box"


# ---------------------------------------------------------------------------
# unpack
# ---------------------------------------------------------------------------

class TestUnpack:
    def test_layered_unpack_overrides_and_records(self, tmp_path):
        src = make_source(tmp_path, {
            "data.xp3": [("data/scenario/first.ks", b"JAPANESE"),
                         ("bgimage/a.png", b"orig")],
            "patch.xp3": [("data/scenario/first.ks", b"CHINESE")]})
        slot = tmp_path / "slot"
        prof = pipeline.load_profile(write_profile(slot, src))
        assert pipeline.unpack(prof) is not None
        assert (slot / "src" / "data" / "scenario" / "first.ks").read_bytes() \
            == b"CHINESE"                     # patch wins
        assert (slot / "src" / "bgimage" / "a.png").read_bytes() == b"orig"
        index = (slot / pipeline.INDEX_FILE).read_text(encoding="utf-8")
        assert "data.xp3" in index and "patch.xp3" in index

    def test_skip_when_tree_exists(self, tmp_path, caplog):
        src = make_source(tmp_path, {"data.xp3": [("a.txt", b"keep")]})
        slot = tmp_path / "slot"
        prof = pipeline.load_profile(write_profile(slot, src))
        pipeline.unpack(prof)
        (slot / "src" / "a.txt").write_bytes(b"edited")
        with caplog.at_level("INFO"):
            pipeline.unpack(prof)
        assert (slot / "src" / "a.txt").read_bytes() == b"edited"
        assert "already unpacked" in caplog.text
        # --force re-extracts and restores the archive content
        pipeline.unpack(prof, force=True)
        assert (slot / "src" / "a.txt").read_bytes() == b"keep"

    def test_protected_archive_refuses_and_leaves_no_tree(self, tmp_path, caplog):
        src = make_source(tmp_path, {"data.xp3": [
            (n, junk(96, i)) for i, n in enumerate(obfuscated_names(24))]})
        slot = tmp_path / "slot"
        prof = pipeline.load_profile(write_profile(slot, src))
        with caplog.at_level("ERROR"):
            assert pipeline.unpack(prof) is None
        assert "protected variant" in caplog.text
        assert not (slot / "src").exists()

    def test_no_archives_reports_failure(self, tmp_path, caplog):
        src = tmp_path / "game"
        src.mkdir()
        slot = tmp_path / "slot"
        prof = pipeline.load_profile(write_profile(slot, src))
        with caplog.at_level("ERROR"):
            assert pipeline.unpack(prof) is None
        assert "no *.xp3 archive found" in caplog.text

    def test_explicit_archive_order_is_honoured(self, tmp_path):
        src = make_source(tmp_path, {
            "data.xp3": [("a.txt", b"data")],
            "patch.xp3": [("a.txt", b"patch")]})
        slot = tmp_path / "slot"
        prof = pipeline.load_profile(write_profile(
            slot, src, archives=["patch.xp3", "data.xp3"]))
        pipeline.unpack(prof)
        assert (slot / "src" / "a.txt").read_bytes() == b"data"


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

class TestStorageRefs:
    def test_resolves_with_and_without_extension(self, tmp_path):
        build = make_build(
            tmp_path,
            '[bg storage="bgimage/a"]\r\n[bg storage="bgimage/b.png"]\r\n'
            '[playbgm storage="bgm/c"]\r\n',
            extra=["bgimage/a.png", "bgimage/b.png", "bgm/c.ogg"])
        assert pipeline.missing_refs(build)[0] == []

    def test_reports_missing_and_ignores_dynamic(self, tmp_path):
        build = make_build(
            tmp_path,
            '[bg storage="bgimage/gone"]\r\n[bg storage="&f.bg"]\r\n'
            '[bg storage="%bg%"]\r\n[bg storage=""]\r\n')
        missing, gaps = pipeline.missing_refs(build)
        assert [m["ref"] for m in missing] == ["bgimage/gone"]
        assert gaps == []
        assert missing[0]["where"] == ["data/scenario/first.ks:1"]

    def test_source_split_marks_conversion_gaps(self, tmp_path):
        build = make_build(tmp_path, '[bg storage="bgimage/gone"]\r\n')
        source = tmp_path / "src"
        (source / "bgimage").mkdir(parents=True)
        (source / "bgimage" / "gone.png").write_bytes(b"x")
        missing, gaps = pipeline.missing_refs(build, str(source))
        assert len(missing) == 1 and gaps == ["bgimage/gone"]

    def test_file_attribute_is_checked_too(self, tmp_path):
        """The @-tag dialect names assets with file=, not storage=."""
        build = make_build(
            tmp_path,
            '[cg file="bgimage/a"]\r\n[playbgm file="bgm/c"]\r\n',
            extra=["bgimage/a.png", "bgm/c.ogg"])
        assert pipeline.missing_refs(build)[0] == []

    def test_unquoted_values_are_checked(self, tmp_path):
        """`[cg file=BG11a02 zoom=32]` - bare value, stops at space/]/,"""
        build = make_build(tmp_path, '[cg file=bgimage/gone zoom=32]\r\n')
        missing, _gaps = pipeline.missing_refs(build)
        assert [m["ref"] for m in missing] == ["bgimage/gone"]

    def test_bare_id_resolves_by_basename_anywhere(self, tmp_path):
        """Ids are mapped to folders by the game's own tables, so a build
        check may only look for a file of that name somewhere in the tree."""
        build = make_build(tmp_path, '[cg file=BG11a02]\r\n',
                           extra=["bg/BG11a02.png"])
        assert pipeline.missing_refs(build)[0] == []

    def test_bare_id_that_exists_nowhere_is_reported(self, tmp_path):
        build = make_build(tmp_path, '[cg file=NOTHERE]\r\n')
        assert [m["ref"] for m in pipeline.missing_refs(build)[0]] == ["NOTHERE"]


class TestVerifyBuild:
    def test_clean_build_passes(self, tmp_path):
        build = make_build(tmp_path, '[ch text="你好"]\r\n',
                           extra=["bgimage/a.png"])
        assert pipeline.verify_build(str(build)) == 0

    def test_missing_index_html_fails(self, tmp_path):
        build = make_build(tmp_path, '[ch text="你好"]\r\n')
        (build / "index.html").unlink()
        assert pipeline.verify_build(str(build)) == 1

    def test_no_scenarios_fails(self, tmp_path):
        build = make_build(tmp_path, '[ch text="x"]\r\n')
        (build / "data" / "scenario" / "first.ks").unlink()
        assert pipeline.verify_build(str(build)) == 1

    def test_broken_iscript_fails(self, tmp_path):
        build = make_build(tmp_path, '[iscript]\r\nvar a = ;\r\n[endscript]\r\n')
        assert pipeline.verify_build(str(build)) == 1

    def test_kana_is_a_warning_unless_strict(self, tmp_path):
        build = make_build(tmp_path, '[ch text="こんにちは"]\r\n')
        assert pipeline.verify_build(str(build)) == 0
        assert pipeline.verify_build(str(build), strict=True) == 1

    def test_missing_ref_is_a_warning_unless_strict(self, tmp_path):
        build = make_build(tmp_path, '[bg storage="bgimage/gone"]\r\n')
        assert pipeline.verify_build(str(build)) == 0
        assert pipeline.verify_build(str(build), strict=True) == 1

    def test_cli_verify_not_a_folder_exits_two(self, tmp_path, capsys):
        assert pipeline.main(["verify", str(tmp_path / "nope")]) == 2
        assert "not a folder" in capsys.readouterr().err


class TestCliSurface:
    def test_unknown_subcommand_exits_two(self, capsys):
        assert pipeline.main(["nope"]) == 2
        assert "No such command" in capsys.readouterr().err

    def test_convert_requires_an_unpacked_tree(self, tmp_path, capsys):
        slot = tmp_path / "slot"
        path = write_profile(slot, "E:/Games/x")
        assert pipeline.main(["convert", path]) == 1
        assert "not unpacked yet" in capsys.readouterr().err
