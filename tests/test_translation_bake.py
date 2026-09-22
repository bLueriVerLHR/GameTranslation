#!/usr/bin/env python3
"""Tests for `translation.bake` - writing the library back into a game.

The point of these tests is the *shape* duality (editor arrays vs named
objects) and reversibility: a bake must be exact, re-runnable, and it must back
up whatever it touches.
"""
import json
import os

import pytest

from translation import bake as bake_mod
from translation import cli, mvkeys, rawlib


def _dump(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def make_game(root, array_commands=False):
    """A tiny MV tree with one dialogue line in each command shape."""
    data = os.path.join(root, "data")
    _dump(os.path.join(data, "MapInfos.json"),
          [{"id": 1, "name": "M", "order": 1, "parentId": 0}])
    line = [401, 0, "\u3042\u3044\u3046"] if array_commands else \
        {"code": 401, "indent": 0, "parameters": ["\u3042\u3044\u3046"]}
    _dump(os.path.join(data, "Map001.json"), {
        "displayName": "\u8857",
        "events": [None, {"id": 1, "name": "Ev", "pages": [{"list": [line]}]}],
    })
    _dump(os.path.join(data, "System.json"), {
        "gameTitle": "\u30c6\u30b9\u30c8",
        "terms": {"commands": {"fight": "\u6226\u3046"}},
    })
    os.makedirs(os.path.join(root, "js"), exist_ok=True)
    with open(os.path.join(root, "js", "plugins.js"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("var $plugins =\n[\n" + json.dumps(
            {"name": "P", "parameters": {"Label": "\u30e9\u30d9\u30eb"}},
            ensure_ascii=False) + "\n];\n")
    os.makedirs(os.path.join(root, "fonts"), exist_ok=True)
    with open(os.path.join(root, "fonts", "gamefont.css"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write('@font-face {\n    font-family: GameFont;\n'
                     '    src: url("mplus-1m-regular.ttf");\n}\n')
    return root


def prepare_work(tmp_path, game, values):
    work = str(tmp_path / "work")
    mvkeys.extract(game, work)
    with open(os.path.join(work, "translated_ids.json"), "w",
                 encoding="utf-8", newline="\n") as handle:
        json.dump(values, handle, ensure_ascii=False)
    return work


def test_parse_path_and_set_by_path_shapes():
    tokens = bake_mod.parse_path(
        "events[2].pages[0].list[0].parameters[0]")
    assert tokens == [("events", None), (None, 2), ("pages", None), (None, 0),
                      ("list", None), (None, 0), ("parameters", None),
                      (None, 0)]
    # object shape
    data = {"events": [None, None, {"pages": [{"list": [
        {"code": 401, "indent": 0, "parameters": ["old"]}]}]}]}
    assert bake_mod.set_by_path(data, tokens, "new") is True
    assert data["events"][2]["pages"][0]["list"][0]["parameters"][0] == "new"
    # array shape: the same path must land on index 2
    data = {"events": [None, None, {"pages": [{"list": [[401, 0, "old"]]}]}]}
    assert bake_mod.set_by_path(data, tokens, "new") is True
    assert data["events"][2]["pages"][0]["list"][0] == [401, 0, "new"]
    assert bake_mod.set_by_path({}, tokens, "x") is False


def test_parse_path_accepts_non_ascii_and_spaced_names():
    """MZ plugin parameters are often named in Japanese, or hold spaces.

    Both shapes reach `bake` as real keys (a shipped game had
    `[21].parameters.フォント登録リスト` and `[24].parameters.Choice Help Commands`),
    and the plugin branch calls `parse_path` outside its try/except, so a
    rejected name took the whole bake down instead of being reported.
    """
    assert bake_mod.parse_path("[21].parameters.\u30d5\u30a9\u30f3\u30c8\u767b\u9332\u30ea\u30b9\u30c8") == [
        (None, 21), ("parameters", None), ("\u30d5\u30a9\u30f3\u30c8\u767b\u9332\u30ea\u30b9\u30c8", None)]
    assert bake_mod.parse_path("[24].parameters.Choice Help Commands") == [
        (None, 24), ("parameters", None), ("Choice Help Commands", None)]
    # nested names still split on the separators, not on punctuation inside them
    assert bake_mod.parse_path("a.b_c.d-1") == [
        ("a", None), ("b_c", None), ("d-1", None)]
    # a bracketed non-index is still a hard error
    with pytest.raises(bake_mod.BakeError):
        bake_mod.parse_path("events[a].pages[0]")
    with pytest.raises(bake_mod.BakeError):
        bake_mod.parse_path("events[2].pages[0]x[0]")


def test_bake_writes_a_japanese_named_plugin_parameter(tmp_path):
    """The end-to-end guard: a non-ASCII plugin param must not crash the bake."""
    game = make_game(str(tmp_path / "game"))
    plugins_path = os.path.join(game, "js", "plugins.js")
    with open(plugins_path, encoding="utf-8") as handle:
        source = handle.read()
    source = source.replace(
        '"parameters": {"Label": "\u30e9\u30d9\u30eb"}',
        '"parameters": {"\u30d5\u30a9\u30f3\u30c8\u767b\u9332\u30ea\u30b9\u30c8": "\u65e5\u672c\u8a9e"}')
    with open(plugins_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    key = "js/plugins.js#[0].parameters.\u30d5\u30a9\u30f3\u30c8\u767b\u9332\u30ea\u30b9\u30c8"
    work = prepare_work(tmp_path, game, {key: "\u65e5\u672c\u8a9e"})
    report = bake_mod.bake(game, work, apply_unified_font=False)
    assert report["applied"] == 1 and report["skipped"] == 0
    assert "\u30d5\u30a9\u30f3\u30c8\u767b\u9332\u30ea\u30b9\u30c8" in open(
        plugins_path, encoding="utf-8").read()


def test_bake_writes_object_shaped_data_and_backs_up(tmp_path):
    game = make_game(str(tmp_path / "game"))
    key = ("data/Map001.json#events[1].pages[0].list[0].parameters[0]")
    work = prepare_work(tmp_path, game, {key: "\u554f\u5019"})
    report = bake_mod.bake(game, work, apply_unified_font=False)
    assert report["applied"] == 1 and report["skipped"] == 0
    assert _load(os.path.join(game, "data", "Map001.json"))["events"][1][
        "pages"][0]["list"][0]["parameters"][0] == "\u554f\u5019"
    backup = os.path.join(work, "backup", "data", "Map001.json")
    assert _load(backup)["events"][1]["pages"][0]["list"][0][
        "parameters"][0] == "\u3042\u3044\u3046"


def test_bake_writes_array_shaped_data(tmp_path):
    game = make_game(str(tmp_path / "game"), array_commands=True)
    key = ("data/Map001.json#events[1].pages[0].list[0].parameters[0]")
    work = prepare_work(tmp_path, game, {key: "\u554f\u5019"})
    assert bake_mod.bake(game, work, apply_unified_font=False)["applied"] == 1
    assert _load(os.path.join(game, "data", "Map001.json"))["events"][1][
        "pages"][0]["list"][0] == [401, 0, "\u554f\u5019"]


def test_bake_is_idempotent_and_runnable_twice(tmp_path):
    game = make_game(str(tmp_path / "game"))
    key = ("data/Map001.json#events[1].pages[0].list[0].parameters[0]")
    work = prepare_work(tmp_path, game, {key: "\u554f\u5019"})
    first = bake_mod.bake(game, work, apply_unified_font=False)
    second = bake_mod.bake(game, work, apply_unified_font=False)
    assert first["applied"] == second["applied"] == 1
    assert _load(os.path.join(work, "backup", "data",
                              "Map001.json"))["events"][1]["pages"][0][
        "list"][0]["parameters"][0] == "\u3042\u3044\u3046"


def test_bake_writes_plugins_and_system(tmp_path):
    game = make_game(str(tmp_path / "game"))
    values = {"js/plugins.js#[0].parameters.Label": "\u6807\u7b7e",
              "data/System.json#terms.commands.fight": "\u6218\u6597"}
    work = prepare_work(tmp_path, game, values)
    report = bake_mod.bake(game, work, apply_unified_font=False)
    assert report["applied"] == 2 and report["skipped"] == 0
    with open(os.path.join(game, "js", "plugins.js"), encoding="utf-8") as h:
        source = h.read()
    assert source.startswith("var $plugins =") and "\u6807\u7b7e" in source
    assert _load(os.path.join(game, "data", "System.json"))["terms"][
        "commands"]["fight"] == "\u6218\u6597"


def test_bake_reports_unknown_paths_instead_of_crashing(tmp_path):
    game = make_game(str(tmp_path / "game"))
    work = prepare_work(tmp_path, game, {
        "data/Map001.json#events[9].pages[0].list[0].parameters[0]": "\u554f",
        "data/Nope.json#a": "\u554f"})
    report = bake_mod.bake(game, work, apply_unified_font=False)
    assert report["applied"] == 0 and report["skipped"] == 2
    assert {why for _, why in report["skipped_detail"]} == {"path not found",
                                                            "file missing"}


def test_bake_requires_to_json(tmp_path):
    game = make_game(str(tmp_path / "game"))
    work = str(tmp_path / "work")
    mvkeys.extract(game, work)
    with pytest.raises(bake_mod.BakeError):
        bake_mod.bake(game, work)


def test_bake_dry_run_changes_nothing(tmp_path):
    game = make_game(str(tmp_path / "game"))
    key = ("data/Map001.json#events[1].pages[0].list[0].parameters[0]")
    work = prepare_work(tmp_path, game, {key: "\u554f\u5019"})
    before = open(os.path.join(game, "data", "Map001.json"),
                     encoding="utf-8").read()
    report = bake_mod.bake(game, work, dry_run=True)
    assert report["applied"] == 1
    assert open(os.path.join(game, "data", "Map001.json"),
                   encoding="utf-8").read() == before
    assert not os.path.isdir(os.path.join(game, "fonts", "x"))
    assert not os.path.isfile(os.path.join(work, "backup", "data",
                                           "Map001.json"))


def test_bake_ships_the_translation_kv(tmp_path):
    """House rule: the dictionary travels with the build."""
    game = make_game(str(tmp_path / "game"))
    key = ("data/Map001.json#events[1].pages[0].list[0].parameters[0]")
    work = prepare_work(tmp_path, game, {key: "\u554f\u5019"})
    with open(os.path.join(work, "translated.json"), "w",
                 encoding="utf-8", newline="\n") as handle:
        json.dump({"\u3042\u3044\u3046": "\u554f\u5019"}, handle,
                  ensure_ascii=False)
    report = bake_mod.bake(game, work, apply_unified_font=False)
    kv = os.path.join(game, "translation_kv.json")
    assert report["translation_kv"] == kv and os.path.isfile(kv)
    assert _load(kv) == {"\u3042\u3044\u3046": "\u554f\u5019"}
    without = bake_mod.bake(game, work, apply_unified_font=False,
                            write_kv=False)
    assert without["translation_kv"] is None


def test_unify_plugin_fonts_fixes_language_faces_and_js(tmp_path):
    """A Chinese face in a plugin parameter is what makes a build look mixed."""
    game = make_game(str(tmp_path / "game"))
    plugins_path = os.path.join(game, "js", "plugins.js")
    with open(plugins_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("var $plugins =\n[\n" + json.dumps({
            "name": "MsgCore", "parameters": {
                "Font Name": "GameFont",
                "Font Name CH": "SimHei, Heiti TC, sans-serif",
                "Font Name KR": "Dotum, AppleGothic, sans-serif",
                "Font Size": "28",
                "Outline": "true"}}, ensure_ascii=False) + "\n];\n")
    os.makedirs(os.path.join(game, "js", "plugins"), exist_ok=True)
    hud = os.path.join(game, "js", "plugins", "SRD_HUDMaker.js")
    with open(hud, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("return `table {\n    font-family: \"Trebuchet MS\", Arial;\n}\n`;\n"
                     "// font-family: GameFont;\n")
    changed, js_files, details = bake_mod.unify_plugin_fonts(
        game, backup_dir=str(tmp_path / "backup"))
    params = json.loads(open(plugins_path, encoding="utf-8").read()
                        .split("[", 1)[1].rsplit("]", 1)[0])["parameters"]
    assert params["Font Name CH"] == "GameFont"
    assert params["Font Name KR"] == "GameFont"
    assert params["Font Size"] == "28"          # not a font
    assert params["Outline"] == "true"
    assert changed == 2 and details
    assert js_files == ["js/plugins/SRD_HUDMaker.js"]
    patched = open(hud, encoding="utf-8").read()
    assert 'font-family: GameFont;' in patched
    assert "Trebuchet" not in patched
    assert os.path.isfile(os.path.join(str(tmp_path / "backup"),
                                       "js", "plugins", "SRD_HUDMaker.js"))
    assert not os.path.isfile(hud + ".prefont")   # never inside the game dir
    # idempotent
    # idempotent: nothing left to change, and it says so
    assert bake_mod.unify_plugin_fonts(
        game, backup_dir=str(tmp_path / "backup")) == (0, [], [])


def test_bake_font_only_skips_key_writing(tmp_path):
    game = make_game(str(tmp_path / "game"))
    work = str(tmp_path / "work")
    os.makedirs(work, exist_ok=True)
    asset = tmp_path / bake_mod.UNIFIED_FONT
    asset.write_bytes(b"fake")
    report = bake_mod.bake(game, work, font_only=True, font_path=str(asset),
                          font_policy="required")
    assert report["applied"] == 0 and report["keys"] == 0
    assert bake_mod.FONT_CSS in report["font_files"]
    assert _load(os.path.join(game, "data", "Map001.json"))["displayName"] \
        == "\u8857"                                # data untouched


def test_the_library_default_font_policy_writes_nothing(tmp_path):
    """A caller that says nothing must not have files rewritten under it.

    The CLI passes ``required`` for a delivery; the library default is the
    report-only ``auto``, so forgetting the argument keeps the game's font
    rather than silently installing one.
    """
    game = make_game(str(tmp_path / "game"))
    work = str(tmp_path / "work")
    os.makedirs(work, exist_ok=True)
    asset = tmp_path / bake_mod.UNIFIED_FONT
    asset.write_bytes(b"fake")
    report = bake_mod.bake(game, work, font_only=True, font_path=str(asset))
    assert report["font_files"] == []
    assert report["font_report"]["applied"] is False
    assert report["font_report"]["policy"] == "auto"
    assert report["font_warnings"], "auto must say what it did not apply"
    assert not os.path.isfile(os.path.join(game, "fonts", bake_mod.UNIFIED_FONT))


def test_required_without_a_usable_font_is_a_bake_error(tmp_path):
    """A required font that cannot be applied stops the bake, not just warns."""
    game = make_game(str(tmp_path / "game"))
    work = str(tmp_path / "work")
    os.makedirs(work, exist_ok=True)
    with pytest.raises(bake_mod.BakeError, match="cannot be satisfied"):
        bake_mod.bake(game, work, font_only=True, font_policy="required",
                      repo_root=str(tmp_path / "no-such-repo"))


def test_apply_font_switches_single_face(tmp_path):
    game = make_game(str(tmp_path / "game"))
    asset = tmp_path / bake_mod.UNIFIED_FONT
    asset.write_bytes(b"fake-font-bytes")
    files, warnings = bake_mod.apply_font(game, font_path=str(asset))
    assert warnings == []
    assert bake_mod.FONT_CSS in files
    css = open(os.path.join(game, "fonts", "gamefont.css"),
                  encoding="utf-8").read()
    assert bake_mod.UNIFIED_FONT in css
    assert "mplus-1m-regular.ttf" not in css
    assert os.path.isfile(os.path.join(game, "fonts", bake_mod.UNIFIED_FONT))
    # a second run is a no-op
    assert bake_mod.apply_font(game, font_path=str(asset)) == ([], [])


def test_apply_font_mz_splits_faces_and_clears_main_filename(tmp_path):
    game = make_mz_game(str(tmp_path / "game"))
    sc, jp = make_font_assets(tmp_path)
    files, warnings = bake_mod.apply_font_mz(game, font_path=sc, jp_path=jp)

    assert warnings == []
    assert "css/game.css" in files and "data/System.json" in files
    css = open(os.path.join(game, "css", "game.css"),
                  encoding="utf-8").read()
    assert bake_mod.MZ_MARKER in css
    for family in bake_mod.MZ_FAMILIES:
        assert f"font-family: {family}" in css
    assert f"../fonts/{bake_mod.UNIFIED_FONT}" in css     # prefix kept
    assert f"../fonts/{bake_mod.UNIFIED_FONT_JP}" in css
    assert bake_mod.MZ_KANA_RANGE in css                    # kana -> JP face
    assert os.path.isfile(os.path.join(game, "fonts", bake_mod.UNIFIED_FONT))
    assert os.path.isfile(os.path.join(game, "fonts", bake_mod.UNIFIED_FONT_JP))
    advanced = _load(os.path.join(game, "data", "System.json"))["advanced"]
    assert advanced["mainFontFilename"] == ""               # engine face off
    assert advanced["numberFontFilename"] == "mplus-2p-bold-sub.woff"
    assert os.path.isfile(os.path.join(game, "fonts",
                                       "mplus-1m-regular.woff"))  # kept
    # re-running changes nothing
    assert bake_mod.apply_font_mz(game, font_path=sc, jp_path=jp) == ([], [])


def test_apply_font_dispatches_to_mz_without_gamefont_css(tmp_path):
    game = make_mz_game(str(tmp_path / "game"))
    sc, jp = make_font_assets(tmp_path)
    files, warnings = bake_mod.apply_font(game, font_path=sc, repo_root=None)
    # JP asset is resolved from the repo root, so pass it through the MZ entry
    assert "data/System.json" in files
    assert not any("not an MV build" in w for w in warnings)


def test_apply_font_mz_honours_font_switch_plugin(tmp_path):
    game = make_mz_game(str(tmp_path / "game"), plugin="Keke_AnyTimeFontChange")
    sc, jp = make_font_assets(tmp_path)
    files, warnings = bake_mod.apply_font_mz(game, font_path=sc, jp_path=jp)

    css = open(os.path.join(game, "css", "game.css"),
                  encoding="utf-8").read()
    assert bake_mod.MZ_MARKER not in css                    # CSS untouched
    advanced = _load(os.path.join(game, "data", "System.json"))["advanced"]
    assert advanced["mainFontFilename"] == bake_mod.UNIFIED_FONT
    assert any("font-switch plugin" in w for w in warnings)


def test_apply_font_mz_warns_when_asset_missing(tmp_path):
    game = make_mz_game(str(tmp_path / "game"))
    files, warnings = bake_mod.apply_font_mz(
        game, font_path=str(tmp_path / "nope.otf"))
    assert files == [] and warnings and "missing" in warnings[0]
    advanced = _load(os.path.join(game, "data", "System.json"))["advanced"]
    assert advanced["mainFontFilename"] == "mplus-1m-regular.woff"


def test_apply_font_mz_without_jp_font_declares_han_face_only(tmp_path):
    game = make_mz_game(str(tmp_path / "game"))
    sc, _jp = make_font_assets(tmp_path)
    files, warnings = bake_mod.apply_font_mz(
        game, font_path=sc, jp_path=str(tmp_path / "missing-jp.otf"))
    css = open(os.path.join(game, "css", "game.css"),
                  encoding="utf-8").read()
    assert f"../fonts/{bake_mod.UNIFIED_FONT}" in css
    assert bake_mod.UNIFIED_FONT_JP not in css
    assert any("JP fallback font missing" in w for w in warnings)


def test_apply_font_mz_ignores_a_disabled_font_switch_plugin(tmp_path):
    """Status decides: a *disabled* font changer must not block the CSS split.

    The old check was a text search over ``js/plugins.js``, so a build whose
    font-switch plugin ships at ``status: false`` was treated as if it
    re-registered the family at runtime: the unicode-range split was skipped and
    the kana face was never declared.  That is what this pins down.
    """
    game = make_mz_game(str(tmp_path / "game"),
                        plugin="Keke_AnyTimeFontChange", plugin_status=False)
    sc, jp = make_font_assets(tmp_path)
    files, warnings = bake_mod.apply_font_mz(game, font_path=sc, jp_path=jp)

    css = open(os.path.join(game, "css", "game.css"),
                  encoding="utf-8").read()
    assert bake_mod.MZ_MARKER in css
    assert bake_mod.UNIFIED_FONT in css and bake_mod.UNIFIED_FONT_JP in css
    advanced = _load(os.path.join(game, "data", "System.json"))["advanced"]
    assert advanced["mainFontFilename"] == ""
    assert not any("font-switch plugin" in w for w in warnings)
    assert not bake_mod.font_switch_plugin(game)


def test_font_switch_plugin_ignores_disabled_and_reads_status(tmp_path):
    game = make_mz_game(str(tmp_path / "game"), plugin="Keke_AnyTimeFontChange",
                        plugin_status=False)
    assert bake_mod.font_switch_plugin(game) is False
    make_mz_game(str(tmp_path / "on"), plugin="Keke_AnyTimeFontChange",
                 plugin_status=True)
    assert bake_mod.font_switch_plugin(str(tmp_path / "on")) is True
    # an unparseable plugins.js stays conservative
    broken = tmp_path / "broken"
    os.makedirs(str(broken / "js"))
    with open(str(broken / "js" / "plugins.js"), "w", encoding="utf-8",
                 newline="\n") as handle:
        handle.write("var $plugins = [ {oops, ")
    assert bake_mod.font_switch_plugin(str(broken)) is False


def test_apply_font_warns_when_asset_missing(tmp_path):
    game = make_game(str(tmp_path / "game"))
    files, warnings = bake_mod.apply_font(game, font_path=str(tmp_path / "no.otf"))
    assert files == [] and warnings and "missing" in warnings[0]
    css = open(os.path.join(game, "fonts", "gamefont.css"),
                  encoding="utf-8").read()
    assert "mplus-1m-regular.ttf" in css          # left untouched


def make_font_assets(tmp_path):
    """Fake SC + JP font assets; returns (sc_path, jp_path)."""
    sc = tmp_path / bake_mod.UNIFIED_FONT
    sc.write_bytes(b"fake-sc-font")
    jp = tmp_path / bake_mod.UNIFIED_FONT_JP
    jp.write_bytes(b"fake-jp-font")
    return str(sc), str(jp)


def make_mz_game(root, main_font="mplus-1m-regular.woff", plugin="P",
                 plugin_params=None, plugin_status=True):
    """An MZ-shaped tree: data/System.json + css/game.css, no gamefont.css."""
    data = os.path.join(root, "data")
    _dump(os.path.join(data, "System.json"), {
        "gameTitle": "\u30c6\u30b9\u30c8",
        "advanced": {"mainFontFilename": main_font,
                     "numberFontFilename": "mplus-2p-bold-sub.woff",
                     "fallbackFonts": "Verdana, sans-serif"},
    })
    os.makedirs(os.path.join(root, "css"), exist_ok=True)
    with open(os.path.join(root, "css", "game.css"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("#errorPrinter { color: #fff; }\n")
    os.makedirs(os.path.join(root, "fonts"), exist_ok=True)
    with open(os.path.join(root, "fonts", main_font), "wb") as handle:
        handle.write(b"original-font")
    os.makedirs(os.path.join(root, "js"), exist_ok=True)
    with open(os.path.join(root, "js", "plugins.js"), "w",
                 encoding="utf-8", newline="\n") as handle:
        handle.write("var $plugins =\n[\n" + json.dumps(
            {"name": plugin, "status": plugin_status,
             "parameters": plugin_params or {"Label": "\u30e9\u30d9\u30eb"}},
            ensure_ascii=False) + "\n];\n")
    return root


def test_cli_bake_end_to_end(tmp_path, capsys):
    """The whole parent half: prepare -> to-json -> bake, on a synthetic tree."""
    game = make_game(str(tmp_path / "game"))
    work = str(tmp_path / "work")
    assert cli.main(["prepare", game, work]) == 0
    keys = mvkeys.load_keys(work)
    with open(os.path.join(work, rawlib.LIBRARY_NAME), "a",
                 encoding="utf-8", newline="\n") as handle:
        for entry in keys:
            handle.write("@@@{}@@@\n\u8bd1\u6587\n".format(entry["id"]))
    assert cli.main(["to-json", work]) == 0
    assert cli.main(["bake", game, work, "--no-font"]) == 0
    assert "\u8bd1\u6587" in open(os.path.join(game, "data", "Map001.json"),
                                     encoding="utf-8").read()
    assert cli.main(["bake", game, work, "--dry-run"]) == 0
    capsys.readouterr()
