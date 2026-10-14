#!/usr/bin/env python3
"""`tyrano/verify.py`: image/video asset references must resolve exactly.

The regression this guards: a reference that Windows resolves case-insensitively
is a 404 on Android/JoiPlay, and `verify` used to look only at the audio
references (the ones the pipeline rewrites) - so a build whose sprite / CG /
background references were dangling or wrongly cased still passed the gate.
"""

from tyrano import verify

CONFIG = "data/system/Config.tjs"


def make_web(root, ks_body, files=(), config="configSave=webstorage\n"):
    """Minimal but complete build: layout + save backend + one scenario file.

    Written so that `verify()` returns [] for a healthy tree, which lets the
    wiring tests assert on the whole problem list instead of one substring.
    """
    scen = root / "data" / "scenario"
    scen.mkdir(parents=True, exist_ok=True)
    (scen / "a.ks").write_text(ks_body, encoding="utf-8")
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "tyrano").mkdir(parents=True, exist_ok=True)
    (root / "data" / "system").mkdir(parents=True, exist_ok=True)
    (root / CONFIG).write_text(config, encoding="utf-8")
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    return str(root)


# --------------------------------------------------------------- resolution

def test_bare_name_resolves_in_the_tag_folder(tmp_path):
    """A bare value is looked up in the tag's own asset folder, not at root."""
    web = make_web(tmp_path, '[bg storage="edo.png" ]\n',
                   files=("data/bgimage/edo.png",))
    assert verify.check_asset_refs(web) == []


def test_bare_name_is_not_accepted_from_the_wrong_folder(tmp_path):
    """The same file in another asset folder is still a missing reference."""
    web = make_web(tmp_path, '[bg storage="edo.png" ]\n',
                   files=("data/fgimage/edo.png",))
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1
    assert "dangling asset ref" in problems[0]


def test_explicit_data_path_is_used_as_written(tmp_path):
    web = make_web(tmp_path, '[bg storage="./data/image/pic.png" ]\n',
                   files=("data/image/pic.png",))
    assert verify.check_asset_refs(web) == []


def test_subdirectory_reference_resolves(tmp_path):
    web = make_web(tmp_path, '[chara_show storage="chara/1/saya1-1.png" ]\n',
                   files=("data/fgimage/chara/1/saya1-1.png",))
    assert verify.check_asset_refs(web) == []


def test_engine_glyph_resolves_from_the_engine_tree(tmp_path):
    """`[glyph line=..]` ships with Tyrano, not with the game (unquoted value)."""
    web = make_web(tmp_path, "[glyph line=nextpage.gif]\n",
                   files=("tyrano/images/system/nextpage.gif",))
    assert verify.check_asset_refs(web) == []


def test_video_reference_uses_the_video_folder(tmp_path):
    web = make_web(tmp_path, '[bgmovie storage="op.mp4" ]\n',
                   files=("data/video/op.mp4",))
    assert verify.check_asset_refs(web) == []


def test_unknown_plugin_tag_is_accepted_from_any_standard_folder(tmp_path):
    """A third-party plugin tag must not produce an invented failure."""
    web = make_web(tmp_path, '[myplugin storage="fx.png" ]\n',
                   files=("data/image/fx.png",))
    assert verify.check_asset_refs(web) == []


def test_unknown_plugin_tag_that_resolves_nowhere_is_reported(tmp_path):
    web = make_web(tmp_path, '[myplugin storage="ghost.png" ]\n')
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1
    assert "ghost.png" in problems[0]


# ----------------------------------------------------------------- case

def test_case_mismatched_file_is_reported(tmp_path):
    web = make_web(tmp_path, '[bg storage="edo.png" ]\n',
                   files=("data/bgimage/Edo.png",))
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1
    assert "case mismatch" in problems[0]
    assert "Edo.png" in problems[0]


def test_case_mismatched_directory_is_reported(tmp_path):
    web = make_web(tmp_path, '[chara_show storage="chara/x.png" ]\n',
                   files=("data/fgimage/Chara/x.png",))
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1
    assert "case mismatch" in problems[0]
    assert "Chara/x.png" in problems[0]


def test_exact_case_is_not_a_problem(tmp_path):
    web = make_web(tmp_path, '[bg storage="Edo.png" ]\n',
                   files=("data/bgimage/Edo.png",))
    assert verify.check_asset_refs(web) == []


# --------------------------------------------------------------- filtering

def test_commented_reference_is_ignored(tmp_path):
    web = make_web(tmp_path, ';[bg storage="ghost.png"]\n'
                             '[bg storage="edo.png" ]\n',
                   files=("data/bgimage/edo.png",))
    assert verify.check_asset_refs(web) == []


def test_indented_comment_is_ignored(tmp_path):
    web = make_web(tmp_path, '   ; [bg storage="ghost.png"]\n')
    assert verify.check_asset_refs(web) == []


def test_display_text_is_not_treated_as_a_reference(tmp_path):
    """Engine help strings end in asset extensions but are not lookups."""
    web = make_web(tmp_path,
                   '[tb_ptext_show text="data/image/my_image.png" ]\n'
                   '[glink text="see my_image.png" ]\n')
    assert verify.check_asset_refs(web) == []


def test_scenario_call_is_not_an_asset_reference(tmp_path):
    web = make_web(tmp_path, '[call storage="system/tyrano.ks"]\n')
    assert verify.check_asset_refs(web) == []


def test_audio_references_are_left_to_the_audio_check(tmp_path):
    """Audio is not reported twice: `check_audio_refs` owns it (it knows about
    the mp3 -> ogg rewrite and the source downgrade)."""
    web = make_web(tmp_path, '[playse storage="ghost.ogg" ]\n')
    assert verify.check_asset_refs(web) == []
    assert verify.check_audio_refs(web) != []


def test_extension_match_is_case_insensitive(tmp_path):
    web = make_web(tmp_path, '[bg storage="ghost.PNG" ]\n')
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1
    assert "ghost.PNG" in problems[0]


def test_extensionless_value_is_not_checked(tmp_path):
    """Nothing to resolve: the engine appends its own default extension."""
    web = make_web(tmp_path, '[bg storage="edo" ]\n')
    assert verify.check_asset_refs(web) == []


def test_missing_scenario_tree_is_not_a_crash(tmp_path):
    root = str(tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert verify.check_asset_refs(root) == []


def test_non_ks_file_in_the_scenario_tree_is_skipped(tmp_path):
    """Only .ks files are scanned, and the scenario tree has other files."""
    web = make_web(tmp_path, "; no references here\n")
    (tmp_path / "data" / "scenario" / "notes.txt").write_text(
        '[bg storage="ghost.png" ]\n', encoding="utf-8")
    assert verify.check_asset_refs(web) == []


def test_path_component_that_is_a_file_is_missing_not_a_crash(tmp_path):
    """`[bg storage="edo.png/x.png"]`: a nonsense reference must be reported,
    not raise (listing a file as if it were a directory raises OSError)."""
    web = make_web(tmp_path, '[bg storage="edo.png/x.png" ]\n',
                   files=("data/bgimage/edo.png",))
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1
    assert "dangling asset ref" in problems[0]


def test_directory_instead_of_file_is_missing(tmp_path):
    """A directory named like the reference is not the asset."""
    web = make_web(tmp_path, '[bg storage="chara.png" ]\n')
    (tmp_path / "data" / "bgimage" / "chara.png").mkdir(parents=True)
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1
    assert "chara.png" in problems[0]


def test_degenerate_path_guard(tmp_path):
    """The resolver's own guard for an empty path (never reached from a .ks
    value, since extensionless values are skipped)."""
    assert verify._resolve_ref(str(tmp_path), "./") == ("missing", "./")


# ------------------------------------------------------------- reporting

def test_shared_reference_is_reported_once(tmp_path):
    """A speaker/model reference repeated in every scene is one problem."""
    web = make_web(tmp_path, '[bg storage="ghost.png" ]\n',
                   files=("data/bgimage/ok.png",))
    (tmp_path / "data" / "scenario" / "b.ks").write_text(
        '[bg storage="ghost.png" ]\n[bg storage="ghost.png" ]\n',
        encoding="utf-8")
    problems = verify.check_asset_refs(web)
    assert len(problems) == 1


def test_many_problems_are_capped(tmp_path):
    body = "".join(f'[bg storage="ghost{i}.png" ]\n' for i in range(14))
    web = make_web(tmp_path, body)
    problems = verify.check_asset_refs(web)
    assert len(problems) == 11
    assert problems[-1].startswith("...and")


# ------------------------------------------------------- source awareness

def make_source(root, files=()):
    return make_web(root, '[bg storage="ghost.png" ]\n', files=files)


def test_source_defect_is_not_a_conversion_regression(tmp_path):
    build = make_web(tmp_path / "build", '[bg storage="ghost.png" ]\n')
    source = make_source(tmp_path / "src")
    assert verify.check_asset_refs(build, source=source) == []


def test_source_keeps_real_regressions(tmp_path):
    """The file exists in the original: the build lost it."""
    build = make_web(tmp_path / "build", '[bg storage="edo.png" ]\n')
    source = make_source(tmp_path / "src", files=("data/bgimage/edo.png",))
    problems = verify.check_asset_refs(build, source=source)
    assert len(problems) == 1
    assert "edo.png" in problems[0]


def test_source_downgrades_a_case_defect_it_also_has(tmp_path):
    """A case mismatch the original already had is not our regression."""
    build = make_web(tmp_path / "build", '[bg storage="edo.png" ]\n',
                     files=("data/bgimage/Edo.png",))
    source = make_source(tmp_path / "src", files=("data/bgimage/Edo.png",))
    assert verify.check_asset_refs(build, source=source) == []


# ------------------------------------------------------------------ wiring

def test_verify_reports_asset_problems(tmp_path):
    web = make_web(tmp_path, '[bg storage="ghost.png" ]\n')
    problems = verify.verify(web, check_png=False)
    assert any("ghost.png" in p for p in problems)


def test_verify_can_skip_the_asset_check(tmp_path):
    web = make_web(tmp_path, '[bg storage="ghost.png" ]\n')
    assert verify.verify(web, check_png=False, check_assets=False) == []


def test_healthy_build_has_no_problems(tmp_path):
    web = make_web(tmp_path, '[bg storage="edo.png" ]\n'
                             '[chara_show storage="chara/x.png" ]\n',
                   files=("data/bgimage/edo.png", "data/fgimage/chara/x.png"))
    assert verify.verify(web) == []
