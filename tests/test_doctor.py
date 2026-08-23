#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/doctor.py environment self-check.

The report is driven entirely by config resolvers (config.find_* / win_* /
games_dir / archives_dir / temp_dir) and config.LOCAL_ENV_FILE, so every
check can be monkeypatched into a hermetic pass/fail matrix: positive
(everything available -> all OK, exit 0), negative (each resolver returns
None -> that line is [MISS], exit 1) and edge cases (unreadable/missing
env_config.json, missing deliverable dir).
"""
import json
import sys

import pytest

from rpgmaker import config, doctor

TOOL_CHECKS = [
    ("ffmpeg", "find_ffmpeg"),
    ("ffprobe", "find_ffprobe"),
    ("7z", "find_7z"),
    ("rg", "find_rg"),
    ("git", "find_git"),
    ("npx", "find_npx"),
]
WIN_CHECKS = [
    ("win_7z", "win_7z"),
    ("win_ffmpeg", "win_ffmpeg"),
    ("win_rg", "win_rg"),
]
DIR_CHECKS = [
    ("games_dir", "games_dir"),
    ("archives_dir", "archives_dir"),
    ("temp_dir", "temp_dir"),
]
# tools + win tools + env_config + deliverable dirs
TOTAL_CHECKS = len(TOOL_CHECKS) + len(WIN_CHECKS) + 1 + len(DIR_CHECKS)


@pytest.fixture
def healthy(monkeypatch, tmp_path):
    """Every resolver returns an existing path; env_config.json present and
    readable; every deliverable dir exists -> all checks must be OK."""
    exe = tmp_path / "tool.bin"
    exe.write_bytes(b"x")
    for _label, fname in TOOL_CHECKS + WIN_CHECKS:
        monkeypatch.setattr(config, fname, lambda _p=exe: str(_p))
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

    @pytest.mark.parametrize("label,fname", TOOL_CHECKS)
    def test_each_tool_missing(self, monkeypatch, healthy, label, fname):
        monkeypatch.setattr(config, fname, lambda: None)
        checks = doctor.collect_checks()
        by = _by_label(checks)
        assert not by[label].ok
        assert by[label].detail == "(not found)"
        assert by[label].hint
        assert all(c.ok for lbl, c in by.items() if lbl != label)

    @pytest.mark.parametrize("label,fname", WIN_CHECKS)
    def test_each_win_tool_not_configured(self, monkeypatch, healthy,
                                          label, fname):
        monkeypatch.setattr(config, fname, lambda: None)
        checks = doctor.collect_checks()
        by = _by_label(checks)
        assert not by[label].ok
        assert by[label].detail == "(not configured)"

    def test_env_config_missing(self, monkeypatch, healthy, tmp_path):
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", tmp_path / "no-such.json")
        checks = doctor.collect_checks()
        by = _by_label(checks)
        assert not by["env_config.json"].ok
        assert "(missing)" in by["env_config.json"].detail

    def test_env_config_unreadable(self, monkeypatch, healthy, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{ not valid json", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        checks = doctor.collect_checks()
        by = _by_label(checks)
        assert not by["env_config.json"].ok
        assert "(unreadable)" in by["env_config.json"].detail

    def test_env_config_non_dict_root(self, monkeypatch, healthy, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("[1, 2]", encoding="utf-8")
        monkeypatch.setattr(config, "LOCAL_ENV_FILE", cfg)
        checks = doctor.collect_checks()
        assert not _by_label(checks)["env_config.json"].ok

    @pytest.mark.parametrize("label,fname", DIR_CHECKS)
    def test_each_dir_missing(self, monkeypatch, healthy, tmp_path,
                              label, fname):
        (tmp_path / fname).rmdir()  # remove the dir created by the fixture
        checks = doctor.collect_checks()
        by = _by_label(checks)
        assert not by[label].ok


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
    def test_pipeline_doctor_exits_with_code(self, monkeypatch, healthy):
        import pipeline as pipeline_mod
        calls = {}

        def fake_run(argv=None):
            calls["argv"] = argv
            return 1

        monkeypatch.setattr(pipeline_mod.doctor, "run", fake_run)
        with pytest.raises(SystemExit) as e:
            pipeline_mod.main(["doctor"])
        assert e.value.code == 1
        assert calls["argv"] is None

    def test_pipeline_help_lists_doctor(self, capsys):
        import pipeline as pipeline_mod
        with pytest.raises(SystemExit) as e:
            pipeline_mod.main(["--help"])
        assert e.value.code == 0
        assert "doctor" in capsys.readouterr().out
