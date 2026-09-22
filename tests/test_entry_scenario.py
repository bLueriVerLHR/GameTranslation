#!/usr/bin/env python3
"""Root cause of two real black-screen ports: the entry scenario was dropped.

`kirikiri/kag/cli.py` used to scan only the tree root plus `scenario/`, so
scenarios living in nested folders were never converted - measured: one game's
entry is `system/gamesystem/first.ks`, another had *all* its story scripts in
`scenario/` while the entry sat one level down.  The build then booted with
"file not found: ./data/scenario/first.ks" and a black screen, and nothing
offline caught it (the asset-ref check kept reporting "no conversion gap").

These tests pin the entry resolution, the index.html wiring and the new gate.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri import pipeline  # noqa: E402
from kirikiri.kag import cli as kag_cli  # noqa: E402


class TestResolveFirstScenario:
    def test_convention_first_ks(self, caplog):
        with caplog.at_level("WARNING"):
            assert kag_cli._resolve_first_scenario(None, {"first.ks"}) == "first.ks"
        assert "black screen" not in caplog.text

    def test_explicit_name_wins(self):
        assert kag_cli._resolve_first_scenario(
            "system/gamesystem/first.ks", {"first.ks"}) == "first.ks"
        assert kag_cli._resolve_first_scenario(
            "main01.ks", {"main01.ks", "first.ks"}) == "main01.ks"

    def test_explicit_name_that_does_not_exist_is_loud(self, caplog):
        with caplog.at_level("WARNING"):
            got = kag_cli._resolve_first_scenario("ghost.ks", {"first.ks"})
        assert got == "ghost.ks"          # honour the caller, but say so
        assert "not among the game's scenarios" in caplog.text

    def test_no_first_ks_and_no_hint_is_loud(self, caplog):
        with caplog.at_level("WARNING"):
            assert kag_cli._resolve_first_scenario(None, {"01_01.ks"}) is None
        assert "no first.ks" in caplog.text
        assert "--first-scenario" in caplog.text


class TestEntryGate:
    def _build(self, tmp_path, entry_value, scenarios=()):
        build = tmp_path / "build"
        (build / "data" / "scenario").mkdir(parents=True)
        (build / "index.html").write_text(
            '<html><body><input type="hidden" id="first_scenario_file" '
            f'value="{entry_value}"></body></html>', encoding="utf-8")
        for name in scenarios:
            (build / "data" / "scenario" / name).write_text(";x\n",
                                                            encoding="utf-8")
        return build

    def test_entry_present_passes(self, tmp_path):
        build = self._build(tmp_path, "first.ks", ["first.ks", "other.ks"])
        assert pipeline.entry_scenario(str(build)) == "first.ks"
        assert pipeline.missing_entry_scenario(str(build)) is None

    def test_entry_missing_is_reported(self, tmp_path):
        build = self._build(tmp_path, "first.ks", ["other.ks"])
        assert pipeline.missing_entry_scenario(str(build)) == "first.ks"

    def test_engine_placeholder_url_is_reduced_to_a_basename(self, tmp_path):
        """The engine template ships value="http://test.com/tyrano/data/...".\""""
        build = self._build(
            tmp_path, "http://test.com/tyrano/data/scenario/first.ks",
            ["first.ks"])
        assert pipeline.entry_scenario(str(build)) == "first.ks"
        assert pipeline.missing_entry_scenario(str(build)) is None

    def test_no_element_means_the_engine_default(self, tmp_path):
        build = tmp_path / "b"
        (build / "data" / "scenario").mkdir(parents=True)
        (build / "index.html").write_text("<html></html>", encoding="utf-8")
        assert pipeline.entry_scenario(str(build)) == "first.ks"
        assert pipeline.missing_entry_scenario(str(build)) == "first.ks"

    def test_missing_entry_fails_verify(self, tmp_path):
        build = self._build(tmp_path, "first.ks", ["other.ks"])
        assert pipeline.verify_build(str(build)) == 1

    def test_present_entry_does_not_fail_verify(self, tmp_path):
        build = self._build(tmp_path, "first.ks", ["first.ks"])
        assert pipeline.verify_build(str(build)) == 0


class TestScenarioScanCoversTheWholeTree:
    def test_nested_scenarios_are_converted(self, tmp_path, monkeypatch):
        """A nested .ks (the real entry) must reach data/scenario/."""
        src = tmp_path / "src"
        for rel in ("first.ks", "scenario/main01.ks",
                    "system/gamesystem/first.ks", "system/other.ks"):
            path = src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[ch text=\"x\"]\n", encoding="utf-8")
        out = tmp_path / "out"
        engine = tmp_path / "engine"
        (engine / "tyrano").mkdir(parents=True)
        (engine / "index.html").write_text("<html><body></body></html>",
                                           encoding="utf-8")
        seen = {}

        def fake_convert(sp, unpacked, dp, macros, stats):
            seen[os.path.basename(dp)] = sp
            Path(dp).write_text(";x\n", encoding="utf-8")

        monkeypatch.setattr(kag_cli, "convert_scenario_file", fake_convert)
        monkeypatch.setattr(kag_cli, "_collect_macros", lambda _u: set())
        code = kag_cli.convert(unpacked=str(src), engine=str(engine),
                               out_dir=str(out), fonts=None)
        assert code in (0, None)
        assert set(seen) >= {"first.ks", "main01.ks", "other.ks"}

    def test_entry_value_is_written_into_index_html(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        (src / "system").mkdir(parents=True)
        (src / "system" / "first.ks").write_text("[ch text=\"x\"]\n",
                                                 encoding="utf-8")
        out = tmp_path / "out"
        engine = tmp_path / "engine"
        (engine / "tyrano").mkdir(parents=True)
        (engine / "index.html").write_text(
            '<html><body><input type="hidden" id="first_scenario_file" '
            'value="http://test.com/tyrano/data/scenario/first.ks">'
            '</body></html>', encoding="utf-8")

        def fake_convert(sp, unpacked, dp, macros, stats):
            Path(dp).write_text(";x\n", encoding="utf-8")

        monkeypatch.setattr(kag_cli, "convert_scenario_file", fake_convert)
        monkeypatch.setattr(kag_cli, "_collect_macros", lambda _u: set())
        kag_cli.convert(unpacked=str(src), engine=str(engine),
                        out_dir=str(out), fonts=None)
        html = (out / "index.html").read_text(encoding="utf-8")
        assert 'id="first_scenario_file" value="first.ks"' in html
        assert "test.com" not in html
