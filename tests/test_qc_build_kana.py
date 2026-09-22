#!/usr/bin/env python3
"""Tests for tools/qc_build_kana.py (post-bake kana-residue acceptance QC).

Fixtures are synthetic MZ trees - the point is to pin which residues must fail
the build and which are by design, without shipping any game's data.
"""
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
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
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
        with open(os.path.join(root, "js", "plugins.js"), "w",
                     encoding="utf-8", newline="\n") as handle:
            handle.write(f"var $plugins = {json.dumps(plugins, ensure_ascii=False)};\n")
    return root


def make_map(root, commands, name="Map001.json", display_name=None):
    """Write one map whose single page holds exactly ``commands``."""
    _dump(os.path.join(root, "data", name),
          {"displayName": ZH_TEXT if display_name is None else display_name,
           "events": [
              {"id": 1, "name": "Ev1", "note": "",
               "pages": [{"list": commands}]}]})
    return root


# ------------------------------------------------------------ text keys

def test_runtime_text_key_in_display_text_fails(tmp_path):
    """A repack that keeps its display text in a runtime table draws the key."""
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, "\\T[SIS1036]"],
                     [101, 0, "", 0, 0, "\\T[N001]"]])
    findings = qc.scan(build)
    assert len(findings["text_keys"]) == 2
    assert qc.main([build]) == 1


def test_runtime_text_key_in_engine_fields_is_by_design(tmp_path):
    """Dispatch keys, event names, notes and asset stems keep their keys."""
    build = make_build(str(tmp_path), system={
        "gameTitle": "\\T[SIS1]",              # display -> flagged
        "title1Name": "\\T[SIS1]",             # asset stem
        "sounds": [{"name": "\\T[SIS1]"}],    # asset stem
    })
    _dump(os.path.join(build, "data", "Map001.json"), {
        "displayName": ZH_TEXT,
        "events": [{"id": 1, "name": "\\T[SIS1]", "note": "\\T[SIS1]",
                    "pages": [{"list": [
                        [132, 0, 0, "\\T[SIS1]", 90, 100, 0],
                        [357, 0, "P", "cmd", "\\T[SIS1]", {}],
                    ]}]}],
    })
    findings = qc.scan(build)
    assert [entry[0] for entry in findings["text_keys"]] == ["System.json"]
    assert findings["text_keys"][0][1] == "gameTitle"


def test_runtime_text_key_reported_in_json_output(tmp_path, capsys):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, "\\T[SIS1036]"]])
    assert qc.main([build, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["text_keys"]) == 1


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
    with open(work / "allow_kana.json", "w", encoding="utf-8",
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
    with open(work / "allow_kana.json", "w", encoding="utf-8") as handle:
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


def test_plugin_command_label_is_by_design_but_args_are_not(tmp_path):
    """357 dispatch keys and ``@text`` label are bookkeeping, args are text.

    ``PluginManager.callCommand`` builds ``key = pluginName + ":" +
    commandName`` from ``params[0]``/``params[1]``, ``command357`` passes
    ``params[3]`` on, and ``params[2]`` is the editor's ``@text`` label - so a
    kana label/dispatch key is by design, while a kana *argument* in the same
    command still fails.
    """
    build = make_build(str(tmp_path))
    make_map(build, [[357, 0, KANA_TEXT, KANA_LINE, KANA_LINE, ZH_TEXT]])
    findings = qc.scan(build)
    assert findings["unexpected"] == []
    assert len(findings["by_design"]) == 3

    build2 = make_build(str(tmp_path / "b2"))
    make_map(build2, [[357, 0, "Plugin", "cmd", ZH_TEXT, KANA_LINE]])
    assert [entry[2] for entry in qc.scan(build2)["unexpected"]] == [KANA_LINE]


def test_system_json_asset_fields_are_by_design(tmp_path):
    """Every System.json ``name`` is an audio/character stem, title*Name an
    image stem - verified on real builds by resolving them to files on disk."""
    build = make_build(str(tmp_path), system={
        "gameTitle": KANA_TEXT,                       # shown -> residue
        "title1Name": KANA_LINE,                      # img/titles1/*.png
        "sounds": [{"name": KANA_TEXT}],               # audio/se/*.ogg
        "defeatMe": {"name": KANA_LINE},               # audio/me/*.ogg
        "switches": [KANA_TEXT],                      # shown by plugins
    })
    findings = qc.scan(build)
    unexpected = {entry[1] for entry in findings["unexpected"]}
    assert unexpected == {"gameTitle", "switches[0]"}
    assert {entry[2] for entry in findings["by_design"]} == {KANA_LINE, KANA_TEXT}


def test_map_event_name_is_by_design_but_display_name_is_not(tmp_path):
    """Event names are editor labels (mvkeys skips them); displayName shows."""
    build = make_build(str(tmp_path))
    _dump(os.path.join(build, "data", "Map007.json"), {
        "displayName": KANA_TEXT,
        "events": [{"id": 1, "name": KANA_LINE, "note": "",
                    "pages": [{"list": [[401, 0, ZH_TEXT]]}]}]})
    findings = qc.scan(build)
    assert [entry[2] for entry in findings["unexpected"]] == [KANA_TEXT]
    assert [entry[2] for entry in findings["by_design"]] == [KANA_LINE]


def test_name_lookups_are_reported(tmp_path, capsys):
    """A build that looks an event up by name must be told about it."""
    build = make_build(str(tmp_path))
    make_map(build, [[108, 0, "<namePop:" + KANA_TEXT + ">"],
                     [355, 0, "this.findEventByName('" + KANA_TEXT + "');"],
                     [401, 0, ZH_TEXT]])
    findings = qc.scan(build)
    assert len(findings["name_lookups"]) == 2
    assert findings["unexpected"] == []          # comments/script: by design
    assert qc.main([build]) == 0
    out = capsys.readouterr().out
    assert "look up a map event by name" in out


def test_name_lookup_section_is_absent_when_unused(tmp_path, capsys):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, ZH_TEXT]])
    assert qc.scan(build)["name_lookups"] == []
    qc.main([build])
    assert "look up a map event by name" not in capsys.readouterr().out


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


def test_identical_kanji_only_values_are_review_only(tmp_path, capsys):
    """A kanji-only Japanese word survives every kana check - review it."""
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, "\u8cfc\u8cb7"], [401, 0, "\u4f24\u5bb3 %1"]],
             name="Map004.json", display_name="\u7b2c\u4e00\u8a71")
    source = make_build(str(tmp_path / "src"), system={"gameTitle": "\u539f\u984c"})
    make_map(source, [[401, 0, "\u8cfc\u8cb7"],
                      [401, 0, "\u30c0\u30e1\u30fc\u30b8 %1"]], name="Map004.json",
             display_name="\u8857")
    findings = qc.scan(build, source_dir=source)
    assert [entry[2] for entry in findings["identical"]] == ["\u8cfc\u8cb7"]
    # never a failure: shared-form names are legitimately identical
    assert qc.main([build, "--source", source]) == 0
    assert "review only" in capsys.readouterr().out


def test_identical_ignores_ascii_labelled_branch_names(tmp_path):
    build = make_build(str(tmp_path))
    text = "en(v[12]>=1)\u6839\u5cb8\u91cc\u7f8e\u3000if(!s[222])"
    make_map(build, [[402, 0, 1, text]], name="Map005.json")
    source = make_build(str(tmp_path / "src"), system={"gameTitle": "\u539f\u984c"})
    make_map(source, [[402, 0, 1, text]], name="Map005.json", display_name="\u8857")
    assert qc.scan(build, source_dir=source)["identical"] == []


def test_identical_not_reported_without_source(tmp_path):
    build = make_build(str(tmp_path))
    make_map(build, [[401, 0, "\u8cfc\u8cb7"]], name="Map006.json")
    assert qc.scan(build)["identical"] == []


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


def test_plugin_scan_reviews_kana_free_cjk_labels(tmp_path, capsys):
    """A kanji-only Japanese plugin label is listed for review, not assumed ok.

    ``\u5712\u7530\u6674\u9999`` contains no kana at all, so every kana gate is blind
    to it; the inventory must still show it (review only, never a failure).
    """
    build = make_build(str(tmp_path), plugins=[
        {"name": "ExtraWindow",
         "parameters": {"WindowList": json.dumps(
             [json.dumps({"Text": "\u5712\u7530\u6674\u9999"}, ensure_ascii=False)],
             ensure_ascii=False)}}])
    findings = qc.scan(build)
    review = [text for _where, text in findings["plugins"]["review"]]
    assert review == ["\u5712\u7530\u6674\u9999"]
    assert findings["plugins"]["strings"] == 0
    assert findings["unexpected"] == []
    assert qc.main([build]) == 0
    assert "kana-free CJK" in capsys.readouterr().out


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
    with open(os.path.join(build, "data", "Broken.json"), "w",
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
