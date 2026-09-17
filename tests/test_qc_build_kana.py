#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tools/qc_build_kana.py (post-bake kana-residue acceptance QC).

Fixtures are synthetic MZ trees - the point is to pin which residues must fail
the build and which are by design, without shipping any game's data.
"""
import io
import json
import os

import pytest

import qc_build_kana as qc

# hand-written kana, spelled with escapes so the file stays ASCII-safe
KANA_TEXT = "\u3053\u3093\u306b\u3061\u306f"          # こんにちは
KANA_LINE = "\u3053\u3093\u306b\u3061\u306f\u3002"    # こんにちは。
HALFWIDTH = "\uff71\uff72\uff73"                      # ｱｲｳ
ZH_TEXT = "\u4f60\u597d\u3002"
DASH_ONLY = "\u865a\u65e0\u4e4b\u5149\u30fc"              # translated text + ー
DOT_ONLY = "\u624b\u30fb\u817f"                      # translated text + ・


def _dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def make_build(root, system=None, animation_name="Anim", note_body="",
               plugins=None):
    """A minimal baked MZ build: data/System.json + data/Animations.json."""
    data = os.path.join(root, "data")
    _dump(os.path.join(data, "System.json"),
          system if system is not None else {"gameTitle": ZH_TEXT})
    _dump(os.path.join(data, "Animations.json"), [
        {"id": 1, "name": animation_name, "note": note_body},
    ])
    if plugins is not None:
        os.makedirs(os.path.join(root, "js"), exist_ok=True)
        with io.open(os.path.join(root, "js", "plugins.js"), "w",
                     encoding="utf-8", newline="\n") as handle:
            handle.write("var $plugins = %s;\n"
                         % json.dumps(plugins, ensure_ascii=False))
    return root


def make_map(root, commands, name="Map001.json"):
    """Write one map whose single page holds exactly ``commands``."""
    _dump(os.path.join(root, "data", name),
          {"displayName": ZH_TEXT, "events": [
              {"id": 1, "name": "Ev1", "note": "",
               "pages": [{"list": commands}]}]})
    return root


# ---------------------------------------------------------------- scanning

def test_clean_build_passes(tmp_path, capsys):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, ZH_TEXT], [101, 0, "", 0, 0, "\u5c0f\u4f1e"]])
    findings = qc.scan(build)
    assert findings["unexpected"] == []
    assert findings["files"] == 3
    assert qc.main([build]) == 0
    assert "PASS" in capsys.readouterr().out


def test_dialogue_kana_fails(tmp_path, capsys):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, KANA_LINE]])
    findings = qc.scan(build)
    assert [text for _f, _t, text, code in findings["unexpected"]] == [KANA_LINE]
    assert findings["unexpected"][0][3] == 401
    assert qc.main([build]) == 1
    out = capsys.readouterr().out
    assert "UNEXPECTED" in out and "REVIEW NEEDED" in out


def test_choice_and_display_name_kana_fail(tmp_path):
    build = make_build(str(tmp_path), system={"gameTitle": KANA_TEXT})
    make_map(build, [[102, 0, [KANA_TEXT, ZH_TEXT], 0, 0]],
             name="Map002.json")
    findings = qc.scan(build)
    where = {entry[0] for entry in findings["unexpected"]}
    assert where == {"System.json", "Map002.json"}


def test_comment_and_logic_commands_are_by_design(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [
        [108, 0, KANA_LINE],                       # comment: not displayed
        [408, 0, KANA_LINE],                       # comment continuation
        [111, 0, KANA_TEXT, 0, 0],                 # conditional branch payload
        [355, 0, KANA_LINE],                       # script
        [655, 0, KANA_LINE],                       # script continuation
        [401, 0, ZH_TEXT],
    ])
    findings = qc.scan(build)
    assert findings["unexpected"] == []
    assert len(findings["by_design"]) == 5


def test_internal_name_and_note_are_by_design(tmp_path):
    build = make_build(str(tmp_path), animation_name=KANA_TEXT,
                       note_body=KANA_LINE)
    findings = qc.scan(build)
    assert findings["unexpected"] == []
    assert {entry[2] for entry in findings["by_design"]} == {KANA_TEXT, KANA_LINE}


def test_allow_list_exempts_substring_and_regex(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with io.open(work / "allow_kana.json", "w", encoding="utf-8",
                 newline="\n") as handle:
        json.dump({"items": [{"match": KANA_TEXT},
                             {"match": "re:^\u5b87\u4f50\u7f8e"}]}, handle)
    build = str(tmp_path)
    # kana that the allow list covers: an embedded spelling and an author name
    make_map(build, [[401, 0, "x" + KANA_TEXT + "y"],
                     [401, 0, "\u5b87\u4f50\u7f8e\u30e1\u30a4"]])
    make_build(build)
    findings = qc.scan(build, work_dir=str(work))
    assert findings["unexpected"] == []
    assert len(findings["allowed"]) == 2


def test_missing_allow_list_is_not_fatal(tmp_path):
    build = make_build(str(tmp_path))
    findings = qc.scan(build, work_dir=str(tmp_path / "nope"))
    assert findings["unexpected"] == []


def test_broken_allow_list_warns_and_is_ignored(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    with io.open(work / "allow_kana.json", "w", encoding="utf-8") as handle:
        handle.write("{not json")
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, KANA_LINE]])
    findings = qc.scan(build, work_dir=str(work))
    assert len(findings["unexpected"]) == 1


# ------------------------------------------------------------- edge cases

def test_prolongation_mark_and_middle_dot_are_not_residue(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, DASH_ONLY], [401, 0, DOT_ONLY]])
    assert qc.scan(build)["unexpected"] == []


def test_halfwidth_katakana_counts(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, HALFWIDTH]])
    assert len(qc.scan(build)["unexpected"]) == 1


def test_nested_parameter_text_is_scanned(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [[357, 0, "Plugin", "cmd", {"args": [{"text": KANA_TEXT}]}]])
    findings = qc.scan(build)
    assert [entry[2] for entry in findings["unexpected"]] == [KANA_TEXT]


def test_object_shaped_commands_are_scanned(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [{"code": 401, "indent": 0, "parameters": [KANA_LINE]}])
    assert len(qc.scan(build)["unexpected"]) == 1


def test_source_without_the_file_is_tolerated(tmp_path):
    build = make_build(str(tmp_path))
    source = make_build(str(tmp_path / "src"), system={"gameTitle": KANA_TEXT})
    os.remove(os.path.join(source, "data", "Animations.json"))
    findings = qc.scan(build, source_dir=source)
    assert findings["placeholder"] == []


# ------------------------------------------------------------ %N parity

def test_placeholder_mismatch_is_reported(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, "\u4f24\u5bb3 %1"]])                  # parity ok
    make_map(build, [[401, 0, "\u4f24\u5bb3 %2"]], name="Map003.json")
    source = make_build(str(tmp_path / "src"))
    make_map(source, [[401, 0, "\u30c0\u30e1\u30fc\u30b8 %1"]])
    make_map(source, [[401, 0, "\u30c0\u30e1\u30fc\u30b8 %1"]], name="Map003.json")
    findings = qc.scan(build, source_dir=source)
    assert findings["unexpected"] == []
    assert len(findings["placeholder"]) == 1
    assert qc.main([build, "--source", source]) == 1


def test_placeholder_parity_ok_when_equal(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, "\u4f24\u5bb3 %1"]])
    source = make_build(str(tmp_path / "src"))
    make_map(source, [[401, 0, "\u30c0\u30e1\u30fc\u30b8 %1"]])
    assert qc.scan(build, source_dir=source)["placeholder"] == []


# ------------------------------------------------------- plugin inventory

def test_plugin_parameters_are_inventory_only(tmp_path, capsys):
    build = make_build(str(tmp_path), plugins=[
        {"name": "P", "parameters": {"popupMessage": KANA_TEXT,
                                     "Crack SE": "glass.ogg"}}])
    findings = qc.scan(build)
    assert findings["plugins"]["strings"] == 1
    assert findings["unexpected"] == []
    assert qc.main([build]) == 0
    assert "excluded by policy" in capsys.readouterr().out


def test_plugin_scan_can_be_skipped(tmp_path):
    build = make_build(str(tmp_path), plugins=[
        {"name": "P", "parameters": {"popupMessage": KANA_TEXT}}])
    assert "plugins" not in qc.scan(build, plugin_scan=False)


# ---------------------------------------------------------------- CLI

def test_not_a_build_fails_clearly(tmp_path, capsys):
    assert qc.main([str(tmp_path)]) == 1
    assert "data/System.json" in capsys.readouterr().err


def test_json_output_is_machine_readable(tmp_path, capsys):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, KANA_LINE]])
    assert qc.main([build, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["unexpected"][0][2] == KANA_LINE


def test_unreadable_data_file_is_reported(tmp_path, capsys):
    build = make_build(str(tmp_path))
    with io.open(os.path.join(build, "data", "Broken.json"), "w",
                 encoding="utf-8") as handle:
        handle.write("{")
    findings = qc.scan(build)
    assert findings["unreadable"]
    assert qc.main([build]) == 1
    assert "UNREADABLE" in capsys.readouterr().out


@pytest.mark.parametrize("limit, expected", [(1, "... 1 more"), (5, None)])
def test_sample_limit(tmp_path, capsys, limit, expected):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, KANA_LINE], [401, 0, KANA_TEXT + KANA_LINE]])
    qc.main([build, "--limit", str(limit)])
    out = capsys.readouterr().out
    if expected:
        assert expected in out
    else:
        assert "more" not in out
