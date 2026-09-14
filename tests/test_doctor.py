#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/doctor.py environment self-check.

The report is driven by the declarative rpgmaker.config.TOOLS table plus the
deliverable/dir resolvers, so every check can be monkeypatched into a
hermetic pass/fail matrix: positive (everything available -> all OK, exit 0),
negative (each resolver returns None -> that line is [MISS], exit 1) and edge
cases (corrupt env_config.json, absent env_config.json, deliverable folder
that cannot be created).
"""
import json

import pytest

from rpgmaker import config, doctor

TOOL_KEYS = [t.key for t in config.TOOLS]
NATIVE_TOOLS = [t for t in config.TOOLS if t.side == "native"]
WIN_TOOLS = [t for t in config.TOOLS if t.side == "win32"]
DIR_CHECKS = [("games_dir", "games_dir"), ("archives_dir", "archives_dir"),
              ("temp_dir", "temp_dir")]
TOTAL_CHECKS = len(TOOL_KEYS) + 1 + len(DIR_CHECKS)


@pytest.fixture
def healthy(monkeypatch, tmp_path):
    """Every resolver returns an existing path; env_config.json present and
    readable; every deliverable dir exists -> all checks must be OK."""
    exe = tmp_path / "tool.bin"
    exe.write_bytes(b"x")
    for tool in config.TOOLS:
        monkeypatch.setattr(config, tool.resolver, lambda _p=exe: str(_p))
    cfg = tmp_path / "env_config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
    for _label, fname in DIR_CHECKS:
        d = tmp_path / fname
        d.mkdir()
        monkeypatch.setattr(config, fname, lambda _d=d: str(_d))
    return tmp_path


def _by_label(checks):
    return {c.label: c for c in checks}


class TestCollectChecks:
    def test_healthy_all_ok(self, healthy):
        checks = doctor.collect_checks()
        assert len(checks) == TOTAL_CHECKS
        assert all(c.ok for c in checks)
        assert all(c.hint for c in checks)

    def test_labels_follow_the_registry(self, healthy):
        # adding a TOOLS entry must show up here without touching doctor.py
        labels = [c.label for c in doctor.collect_checks()]
        assert labels[:len(TOOL_KEYS)] == TOOL_KEYS

    @pytest.mark.parametrize("key", TOOL_KEYS)
    def test_each_tool_missing(self, monkeypatch, healthy, key):
        tool = config.TOOLS_BY_KEY[key]
        monkeypatch.setattr(config, tool.resolver, lambda: None)
        by = _by_label(doctor.collect_checks())
        assert not by[key].ok
        expected = "(not configured)" if tool.side == "win32" else "(not found)"
        assert by[key].detail == expected
        assert by[key].hint
        assert all(c.ok for lbl, c in by.items() if lbl != key)

    def test_registry_covers_every_tool_resolver(self):
        names = {t.resolver for t in config.TOOLS}
        assert len(names) == len(config.TOOLS)
        for name in names:
            assert callable(getattr(config, name))

    def test_native_and_win_split(self):
        assert {t.key for t in NATIVE_TOOLS}.isdisjoint(
            {t.key for t in WIN_TOOLS})
        assert "win7z" in {t.key for t in WIN_TOOLS}

    def test_env_config_absent_is_ok(self, monkeypatch, healthy, tmp_path):
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", tmp_path / "no-such.json")
        by = _by_label(doctor.collect_checks())
        assert by["env_config.json"].ok
        assert "(absent)" in by["env_config.json"].detail

    def test_env_config_unreadable(self, monkeypatch, healthy, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{ not valid json", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        by = _by_label(doctor.collect_checks())
        assert not by["env_config.json"].ok
        assert "(unreadable)" in by["env_config.json"].detail

    def test_env_config_non_dict_root(self, monkeypatch, healthy, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("[1, 2]", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        assert not _by_label(doctor.collect_checks())["env_config.json"].ok

    @pytest.mark.parametrize("label,fname", DIR_CHECKS)
    def test_each_dir_missing_when_uncreatable(self, monkeypatch, healthy,
                                               tmp_path, label, fname):
        # a path under a *file* can never be created on demand
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        ghost = str(blocker / label)
        monkeypatch.setattr(config, fname, lambda _d=ghost: _d)
        assert not _by_label(doctor.collect_checks())[label].ok

    @pytest.mark.parametrize("label,fname", DIR_CHECKS)
    def test_each_dir_absent_but_creatable_is_ok(self, monkeypatch, healthy,
                                                 tmp_path, label, fname):
        (tmp_path / fname).rmdir()
        by = _by_label(doctor.collect_checks())
        assert by[label].ok
        assert "created on demand" in by[label].detail

    def test_source_is_reported_for_resolved_tools(self, healthy):
        by = _by_label(doctor.collect_checks())
        # the resolver was monkeypatched, so the registry lookup reports no
        # source; the report must still be a plain string for every row
        assert all(isinstance(c.source, str) for c in by.values())


class TestRender:
    def test_render_ok_lines(self, healthy):
        lines = doctor.render(doctor.collect_checks())
        assert all(l.startswith("[OK]") for l in lines[:-1])
        assert lines[-1] == "%d/%d checks OK" % (TOTAL_CHECKS, TOTAL_CHECKS)

    def test_render_miss_has_hint(self, monkeypatch, healthy):
        monkeypatch.setattr(config, "find_7z", lambda: None)
        lines = doctor.render(doctor.collect_checks())
        miss = next(l for l in lines if l.startswith("[MISS]"))
        assert "->" in miss
        assert "7z" in miss


class TestJsonReport:
    def test_json_is_machine_readable(self, healthy, capsys):
        assert doctor.run(["--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert [c["label"] for c in payload["checks"]][:len(TOOL_KEYS)] == \
            TOOL_KEYS
        assert {t["key"] for t in payload["tools"]} == set(TOOL_KEYS)

    def test_json_reports_failure(self, monkeypatch, healthy, capsys):
        monkeypatch.setattr(config, "win_7z", lambda: None)
        assert doctor.run(["--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False


class TestRun:
    def test_run_exit_zero_when_all_ok(self, healthy, capsys):
        assert doctor.run() == 0
        out = capsys.readouterr().out
        assert "[MISS]" not in out
        assert "%d/%d checks OK" % (TOTAL_CHECKS, TOTAL_CHECKS) in out

    def test_run_exit_one_when_missing(self, monkeypatch, healthy, capsys):
        monkeypatch.setattr(config, "find_rg", lambda: None)
        assert doctor.run() == 1
        out = capsys.readouterr().out
        assert "[MISS] rg" in out
        assert "%d/%d checks OK" % (TOTAL_CHECKS - 1, TOTAL_CHECKS) in out


class TestPipelineWiring:
    """The CLI is a Typer app in rpgmaker/cli.py; pipeline.py is a wrapper.

    Exit convention: a failing run raises SystemExit with its code, a
    successful one returns normally (see rpgmaker.cli._run).
    """

    @staticmethod
    def _patch_doctor(monkeypatch, code, calls):
        from rpgmaker import doctor as doctor_mod

        def fake_run(argv=None):
            calls["argv"] = argv
            return code
        monkeypatch.setattr(doctor_mod, "run", fake_run)

    def test_pipeline_doctor_exits_with_code(self, monkeypatch, healthy):
        import pipeline as pipeline_mod
        calls = {}
        self._patch_doctor(monkeypatch, 1, calls)
        with pytest.raises(SystemExit) as e:
            pipeline_mod.main(["doctor"])
        assert e.value.code == 1
        assert calls["argv"] == []

    def test_pipeline_doctor_json_flag(self, monkeypatch, healthy):
        import pipeline as pipeline_mod
        calls = {}
        self._patch_doctor(monkeypatch, 0, calls)
        assert pipeline_mod.main(["doctor", "--json"]) is None
        assert calls["argv"] == ["--json"]

    def test_pipeline_help_lists_doctor(self, capsys):
        import pipeline as pipeline_mod
        assert pipeline_mod.main(["--help"]) is None
        assert "doctor" in capsys.readouterr().out

    def test_tyrano_wrapper_lists_its_own_commands(self, capsys):
        import tyrano.pipeline as tyrano_mod
        assert tyrano_mod.tyrano_main(["--help"]) is None
        out = capsys.readouterr().out
        assert "fix-autoplay" in out and "deliver" in out
