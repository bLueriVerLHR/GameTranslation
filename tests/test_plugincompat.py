#!/usr/bin/env python3
"""Unit tests for rpgmaker/plugincompat.py.

The fixtures reproduce the real-world failure shape (the exact line forms, the
tab-indented `require('fs')` block, CRLF, Shift-JIS) without naming a game.
"""
import json
import logging
import os

import pytest
from conftest import make_game

from rpgmaker import cli, jssyntax, plugincompat, verify

# Mirrors the load-time code of the SRD "Super Tools Engine" plugin: two
# module-scope NW.js reads (one inside an `if`, one as a value), an indented
# `require('fs')` block that is only reachable in playtest, and a guarded
# `process.mainModule` read inside a function.
STE_BROKEN = """/*:
 * @plugindesc test fixture
 */
function WindowManager() {
    throw new Error('Great job. WindowManager is a static class!');
}

// Fix the flag check for 1.6 editor and 1.5 or below project
if(process.versions['node-webkit'] >= "0.13.0" && Utils.RPGMAKER_VERSION < "1.6.0") {

Utils.isOptionValid = function(name) {
    if (location.search.slice(1).split('&').contains(name)) {return 1;};
    return 0;
};

}

var _ = {};
_.isPlaytest = Utils.isOptionValid('test') && Utils.isNwjs();
_.isNewNWjs = process.versions['node-webkit'] >= "0.13.0";

if(_.isPlaytest && _.isNewNWjs) {
\tif(!require('fs').existsSync("supertoolsengine.html")) require('fs').writeFileSync("supertoolsengine.html", "x");
}

FileManager.filePath = function(location) {
\tif(!Utils.isNwjs()) return '';
\tconst base = path.dirname(process.mainModule.filename);
\treturn base;
};
"""

GUARDED = "if(typeof process !== \"undefined\" && process.versions && process.versions['node-webkit'] >= \"0.13.0\") {"

# The Steam-build boot gate: an MV Steam release checks ownership inside the
# splash scene and throws right before the title screen.  In a browser/WebView
# build (no NW.js runtime, no Steam) the check is a stub that only ever answers
# false, so the build never reaches the title screen.  The call site sits INSIDE
# a function - a module-scope-only repair would never see it.
STEAM_GATE = """(function() {
    Scene_Splash.prototype.gotoTitleOrTest = function() {
        Scene_Base.prototype.start.call(this);
\t\tif (!OrangeGreenworks.isSubscribedApp(3331050)) {
            throw new Error('Steam failed to initialize.');
\t\t\treturn;
\t\t}
        SoundManager.preloadImportantSounds();
    };
})();
"""


def make_web(tmp_path, plugins, files, name="build"):
    """Minimal MV-shaped web root with the given plugins.js entries.

    `plugins` entries use the MV bare-name style; `files` maps a plugin file
    name to `str` (UTF-8) or `bytes` (written verbatim).
    """
    root = tmp_path / name
    (root / "js" / "plugins").mkdir(parents=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "System.json").write_text("{}", encoding="utf-8")
    (root / "index.html").write_text("<!DOCTYPE html>", encoding="utf-8")
    body = ",\n".join(json.dumps(p) for p in plugins)
    (root / "js" / "plugins.js").write_text(
        "var $plugins =\n[\n" + body + "];\n", encoding="utf-8")
    for file_name, content in files.items():
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        (root / "js" / "plugins" / file_name).write_bytes(data)
    return str(root)


def plugin_text(web, name="SRD_SuperToolsEngine.js"):
    with open(os.path.join(web, "js", "plugins", name), encoding="utf-8") as f:
        return f.read()


def ste_web(tmp_path, status=True, text=STE_BROKEN):
    return make_web(tmp_path,
                    [{"name": "SRD_SuperToolsEngine", "status": status}],
                    {"SRD_SuperToolsEngine.js": text})


class TestEnabledPlugins:
    def test_bare_mv_name_gets_js_suffix(self, tmp_path):
        web = ste_web(tmp_path)
        assert plugincompat.enabled_plugins(web) == ["SRD_SuperToolsEngine.js"]

    def test_mz_name_with_suffix_is_not_doubled(self, tmp_path):
        web = make_web(tmp_path, [{"name": "MZ_Shop.js", "status": True}],
                       {"MZ_Shop.js": "var a = 1;\n"})
        assert plugincompat.enabled_plugins(web) == ["MZ_Shop.js"]

    def test_disabled_entry_is_skipped(self, tmp_path):
        web = make_web(tmp_path,
                       [{"name": "Off.js", "status": False},
                        {"name": "On.js", "status": True}],
                       {"Off.js": "var a = 1;\n", "On.js": "var b = 1;\n"})
        assert plugincompat.enabled_plugins(web) == ["On.js"]

    def test_missing_plugins_js_warns_and_returns_empty(self, tmp_path, caplog):
        (tmp_path / "build").mkdir()
        with caplog.at_level(logging.WARNING):
            assert plugincompat.enabled_plugins(str(tmp_path / "build")) == []
        assert "no js/plugins.js" in caplog.text

    def test_minified_plugins_js_is_parsed(self, tmp_path):
        root = tmp_path / "build"
        (root / "js" / "plugins").mkdir(parents=True)
        (root / "js" / "plugins.js").write_text(
            "var $plugins=[{\"name\":\"Min.js\",\"status\":true}];\n",
            encoding="utf-8")
        assert plugincompat.enabled_plugins(str(root)) == ["Min.js"]


class TestScan:
    def test_finds_both_load_time_nwjs_reads(self, tmp_path):
        web = ste_web(tmp_path)
        findings = plugincompat.scan(web)
        assert [f.kind for f in findings] == ["nwjs-version", "nwjs-version"]
        assert all(f.plugin == "SRD_SuperToolsEngine.js" for f in findings)
        lines = [f.text for f in findings]
        assert lines[0].startswith("if(process.versions['node-webkit']")
        assert lines[1].startswith("_.isNewNWjs = process.versions['node-webkit']")

    def test_indented_require_is_out_of_scope(self, tmp_path):
        web = ste_web(tmp_path)
        assert not any("existsSync" in f.text for f in plugincompat.scan(web))

    def test_comment_mentions_are_ignored(self, tmp_path):
        text = ("// process ZMap decoration\n"
                "/* process parameters\n"
                "   process more\n"
                "*/\n"
                "/* global Game_Interpreter, $gameMessage, process, PluginManager */\n"
                "var code = 1; // process trailing comment\n")
        web = make_web(tmp_path, [{"name": "Commenty.js", "status": True}],
                       {"Commenty.js": text})
        assert plugincompat.scan(web) == []

    def test_string_literal_is_not_a_reference(self, tmp_path):
        web = make_web(tmp_path, [{"name": "Strings.js", "status": True}],
                       {"Strings.js": 'var label = "process";\n'
                                      "var other = 'require(fs)';\n"})
        assert plugincompat.scan(web) == []

    def test_plain_module_scope_process_is_reported(self, tmp_path):
        web = make_web(tmp_path, [{"name": "Reader.js", "status": True}],
                       {"Reader.js": "var base = process.platform;\n"})
        findings = plugincompat.scan(web)
        assert [f.kind for f in findings] == ["load-time-process"]

    def test_module_scope_require_is_reported(self, tmp_path):
        web = make_web(tmp_path, [{"name": "Loader.js", "status": True}],
                       {"Loader.js": "var gui = require('nw.gui');\n"})
        assert [f.kind for f in plugincompat.scan(web)] == ["load-time-require"]

    def test_disabled_plugin_is_not_scanned(self, tmp_path):
        web = ste_web(tmp_path, status=False)
        assert plugincompat.scan(web) == []

    def test_plugin_file_absent_from_plugins_js_is_skipped(self, tmp_path):
        web = make_web(tmp_path, [{"name": "Enabled.js", "status": True}],
                       {"Enabled.js": "var a = 1;\n",
                        "SRD_SuperToolsEngine.js": STE_BROKEN})
        assert plugincompat.scan(web) == []

    def test_enabled_but_missing_file_warns(self, tmp_path, caplog):
        web = make_web(tmp_path, [{"name": "Ghost.js", "status": True}], {})
        with caplog.at_level(logging.WARNING):
            assert plugincompat.scan(web) == []
        assert "Ghost.js is enabled" in caplog.text

    def test_already_guarded_line_is_not_reported(self, tmp_path):
        web = ste_web(tmp_path, text=GUARDED + "\n")
        assert plugincompat.scan(web) == []


class TestRepair:
    def test_patches_both_sites_and_keeps_js_valid(self, tmp_path):
        web = ste_web(tmp_path)
        report = plugincompat.repair(web)
        assert len(report.edits) == 2
        assert report.files_changed == ["SRD_SuperToolsEngine.js"]
        text = plugin_text(web)
        assert ('if(typeof process !== "undefined" && process.versions && '
                "process.versions['node-webkit'] >= \"0.13.0\" && ") in text
        assert ('_.isNewNWjs = ((typeof process !== "undefined" && '
                "process.versions) ? process.versions['node-webkit'] >= "
                '"0.13.0" : false);') in text
        assert jssyntax.is_valid(text), jssyntax.parse_errors(text)
        # nothing is left for a human
        assert report.findings == []

    def test_idempotent_second_run_writes_nothing(self, tmp_path):
        web = ste_web(tmp_path)
        plugincompat.repair(web)
        first = plugin_text(web)
        report = plugincompat.repair(web)
        assert report.edits == []
        assert plugin_text(web) == first

    def test_dry_run_reports_without_writing(self, tmp_path):
        web = ste_web(tmp_path)
        report = plugincompat.repair(web, dry_run=True)
        assert len(report.edits) == 2
        assert plugin_text(web) == STE_BROKEN

    def test_crlf_and_bom_are_preserved(self, tmp_path):
        raw = b"\xef\xbb\xbf" + STE_BROKEN.replace("\n", "\r\n").encode("utf-8")
        web = make_web(tmp_path, [{"name": "SRD_SuperToolsEngine", "status": True}],
                       {"SRD_SuperToolsEngine.js": raw})
        plugincompat.repair(web)
        with open(os.path.join(web, "js", "plugins",
                               "SRD_SuperToolsEngine.js"), "rb") as f:
            out = f.read()
        assert out.startswith(b"\xef\xbb\xbf")
        assert out.count(b"\r\n") == out.count(b"\n")
        assert b'typeof process !== "undefined"' in out

    def test_no_bom_is_not_added(self, tmp_path):
        raw = STE_BROKEN.encode("utf-8")
        web = make_web(tmp_path, [{"name": "SRD_SuperToolsEngine", "status": True}],
                       {"SRD_SuperToolsEngine.js": raw})
        plugincompat.repair(web)
        with open(os.path.join(web, "js", "plugins",
                               "SRD_SuperToolsEngine.js"), "rb") as f:
            out = f.read()
        assert not out.startswith(b"\xef\xbb\xbf")
        assert b'typeof process !== "undefined"' in out
        assert out.decode("utf-8") != STE_BROKEN          # it did change

    def test_shift_jis_file_survives_byte_for_byte(self, tmp_path):
        text = STE_BROKEN.replace("@plugindesc test fixture",
                                  "@plugindesc テスト用プラグイン")
        web = make_web(tmp_path, [{"name": "SRD_SuperToolsEngine", "status": True}],
                       {"SRD_SuperToolsEngine.js": text.encode("cp932")})
        report = plugincompat.repair(web)
        assert len(report.edits) == 2
        with open(os.path.join(web, "js", "plugins",
                               "SRD_SuperToolsEngine.js"), "rb") as f:
            out = f.read()
        decoded = out.decode("cp932")
        assert "テスト用プラグイン" in decoded
        assert 'typeof process !== "undefined"' in decoded

    def test_undecodable_file_is_skipped_with_a_reason(self, tmp_path, caplog):
        web = make_web(tmp_path, [{"name": "SRD_SuperToolsEngine", "status": True}],
                       {"SRD_SuperToolsEngine.js": b"var x = 1;\n\x81\x30\n"})
        with caplog.at_level(logging.WARNING):
            report = plugincompat.repair(web)
        assert report.edits == []
        assert report.skipped == [("SRD_SuperToolsEngine.js",
                                   "neither UTF-8 nor CP932")]
        assert "left untouched" in caplog.text

    def test_uncovered_variant_is_reported_not_rewritten(self, tmp_path):
        text = "_.isNewNWjs = process.versions['node-webkit'];\n"
        web = make_web(tmp_path, [{"name": "SRD_SuperToolsEngine", "status": True}],
                       {"SRD_SuperToolsEngine.js": text})
        report = plugincompat.repair(web)
        assert report.edits == []
        assert [f.kind for f in report.findings] == ["nwjs-version"]
        assert plugin_text(web) == text

    def test_other_plugin_with_load_time_process_is_left_alone(self, tmp_path):
        text = "var base = process.mainModule.filename;\n"
        web = make_web(tmp_path,
                       [{"name": "SRD_SuperToolsEngine", "status": True},
                        {"name": "Reader.js", "status": True}],
                       {"SRD_SuperToolsEngine.js": STE_BROKEN,
                        "Reader.js": text})
        report = plugincompat.repair(web)
        assert len(report.edits) == 2
        assert plugin_text(web, "Reader.js") == text
        assert [f.plugin for f in report.findings] == ["Reader.js"]


def steam_web(tmp_path, status=True, text=STEAM_GATE, file_name="Splash.js"):
    """A build whose splash plugin carries the Steam boot gate."""
    return make_web(tmp_path, [{"name": file_name, "status": status}],
                    {file_name: text})


class TestSteamBootGate:
    """The gate lives inside a function, so it needs the any-line scope."""

    def test_gate_inside_a_function_is_guarded(self, tmp_path):
        web = steam_web(tmp_path)
        report = plugincompat.repair(web)
        assert len(report.edits) == 1
        edit = report.edits[0]
        assert edit.rule_id == "steam-ownership-gate"
        text = plugin_text(web, "Splash.js")
        assert ("if (OrangeGreenworks.isSteamRunning && "
                "OrangeGreenworks.isSteamRunning() && "
                "!OrangeGreenworks.isSubscribedApp(3331050)) {") in text
        # indentation (two tabs) and the following lines survive
        assert "\t\tif (OrangeGreenworks.isSteamRunning" in text
        assert "throw new Error('Steam failed to initialize.');" in text
        assert jssyntax.is_valid(text), jssyntax.parse_errors(text)

    def test_no_game_specific_ids_are_baked_in(self, tmp_path):
        web = steam_web(tmp_path, text=STEAM_GATE.replace("3331050", "998877"))
        plugincompat.repair(web)
        assert "isSubscribedApp(998877)" in plugin_text(web, "Splash.js")

    def test_idempotent_second_run_writes_nothing(self, tmp_path):
        web = steam_web(tmp_path)
        plugincompat.repair(web)
        first = plugin_text(web, "Splash.js")
        report = plugincompat.repair(web)
        assert report.edits == []
        assert plugin_text(web, "Splash.js") == first

    def test_dry_run_reports_without_writing(self, tmp_path):
        web = steam_web(tmp_path)
        report = plugincompat.repair(web, dry_run=True)
        assert [e.rule_id for e in report.edits] == ["steam-ownership-gate"]
        assert plugin_text(web, "Splash.js") == STEAM_GATE

    def test_disabled_plugin_is_not_touched(self, tmp_path):
        web = steam_web(tmp_path, status=False)
        assert plugincompat.repair(web).edits == []
        assert plugin_text(web, "Splash.js") == STEAM_GATE

    def test_call_used_as_a_value_is_left_alone(self, tmp_path):
        text = "var owned = OrangeGreenworks.isSubscribedApp(3331050);\n"
        web = steam_web(tmp_path, text=text)
        assert plugincompat.repair(web).edits == []
        assert plugin_text(web, "Splash.js") == text

    def test_positive_test_without_negation_is_left_alone(self, tmp_path):
        text = "if (OrangeGreenworks.isSubscribedApp(3331050)) { load(); }\n"
        web = steam_web(tmp_path, text=text)
        assert plugincompat.repair(web).edits == []
        assert plugin_text(web, "Splash.js") == text

    def test_no_space_form_is_guarded_too(self, tmp_path):
        text = "if(!Steam_.isSubscribedApp(12)){ throw new Error('x'); }\n"
        web = steam_web(tmp_path, text=text)
        assert len(plugincompat.repair(web).edits) == 1
        assert ("if (Steam_.isSteamRunning && Steam_.isSteamRunning() && "
                "!Steam_.isSubscribedApp(12)){ throw new Error('x'); }"
                ) in plugin_text(web, "Splash.js")

    def test_every_enabled_plugin_is_checked(self, tmp_path):
        # the rule is plugin-agnostic: two enabled files, both gates, one pass
        web = make_web(
            tmp_path,
            [{"name": "A.js", "status": True}, {"name": "B.js", "status": True}],
            {"A.js": STEAM_GATE.replace("3331050", "11"),
             "B.js": STEAM_GATE.replace("3331050", "22")})
        report = plugincompat.repair(web)
        assert [e.plugin for e in report.edits] == ["A.js", "B.js"]

    def test_crlf_and_tabs_are_preserved(self, tmp_path):
        raw = STEAM_GATE.replace("\n", "\r\n").encode("utf-8")
        web = steam_web(tmp_path, text=raw)
        plugincompat.repair(web)
        with open(os.path.join(web, "js", "plugins", "Splash.js"), "rb") as f:
            out = f.read()
        assert out.count(b"\r\n") == out.count(b"\n")
        assert b"\t\tif (OrangeGreenworks.isSteamRunning" in out

    def test_steam_gate_does_not_break_the_scan(self, tmp_path):
        # the guard introduces no process/require reference for verify to warn on
        web = steam_web(tmp_path)
        assert plugincompat.repair(web).findings == []

    def test_compat_cli_applies_it_and_strict_stays_green(self, tmp_path):
        web = steam_web(tmp_path)
        assert cli.main(["compat", web, "--strict"]) is None
        assert "isSteamRunning()" in plugin_text(web, "Splash.js")


class TestReport:
    def test_run_logs_what_it_guarded(self, tmp_path, caplog):
        web = ste_web(tmp_path)
        with caplog.at_level(logging.INFO):
            report = plugincompat.run(web)
        assert len(report.edits) == 2
        assert "guarded 2 NW.js-only site(s)" in caplog.text

    def test_run_logs_clean_state(self, tmp_path, caplog):
        web = make_web(tmp_path, [], {})
        with caplog.at_level(logging.INFO):
            plugincompat.run(web)
        assert "no known browser/JoiPlay plugin breakage" in caplog.text

    def test_run_warns_for_remaining_findings(self, tmp_path, caplog):
        web = make_web(tmp_path, [{"name": "Reader.js", "status": True}],
                       {"Reader.js": "var base = process.platform;\n"})
        with caplog.at_level(logging.WARNING):
            report = plugincompat.run(web)
        assert len(report.findings) == 1
        assert "review it by hand" in caplog.text


class TestCli:
    def test_compat_repairs_the_build(self, tmp_path):
        web = ste_web(tmp_path)
        assert cli.main(["compat", web]) is None
        assert 'typeof process !== "undefined"' in plugin_text(web)

    def test_dry_run_leaves_the_file_alone(self, tmp_path):
        web = ste_web(tmp_path)
        cli.main(["compat", web, "--dry-run"])
        assert plugin_text(web) == STE_BROKEN

    def test_strict_exits_non_zero_when_something_is_left(self, tmp_path):
        web = make_web(tmp_path, [{"name": "Reader.js", "status": True}],
                       {"Reader.js": "var base = process.platform;\n"})
        with pytest.raises(SystemExit) as exc:
            cli.main(["compat", web, "--strict"])
        assert exc.value.code == 1

    def test_strict_is_green_when_everything_is_handled(self, tmp_path):
        web = ste_web(tmp_path)
        assert cli.main(["compat", web, "--strict"]) is None


class TestVerifyIntegration:
    def test_verify_warns_but_still_passes(self, tmp_path, caplog):
        web = make_game(str(tmp_path / "g"))
        plugins_dir = os.path.join(web, "js", "plugins")
        os.makedirs(plugins_dir, exist_ok=True)
        with open(os.path.join(web, "js", "plugins.js"), "w",
                  encoding="utf-8") as f:
            f.write('var $plugins =\n[\n  {"name": "Reader", "status": true}\n];\n')
        with open(os.path.join(plugins_dir, "Reader.js"), "w",
                  encoding="utf-8") as f:
            f.write("var base = process.mainModule.filename;\n")

        with caplog.at_level(logging.WARNING):
            issues = verify.verify_all(web)
        assert issues == []                     # advisory, never a failure
        assert "plugin compat" in caplog.text
        assert "Reader.js" in caplog.text

    def test_verify_quiet_when_no_findings(self, tmp_path, caplog):
        web = make_game(str(tmp_path / "g"))
        with caplog.at_level(logging.INFO):
            assert verify.verify_all(web) == []
        assert "no module-scope NW.js references" in caplog.text
