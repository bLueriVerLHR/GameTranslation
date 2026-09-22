#!/usr/bin/env python3
"""Unit tests for rpgmaker/doctor.py environment self-check.

The report is driven by the declarative rpgmaker.tool_registry.TOOLS table plus the
deliverable/dir resolvers, so every check can be monkeypatched into a
hermetic pass/fail matrix: positive (everything available -> all OK, exit 0),
negative (each resolver returns None -> that line is [MISS], exit 1) and edge
cases (corrupt env_config.json, absent env_config.json, deliverable folder
that cannot be created).
"""
import json

import pytest

from rpgmaker import deliverables, doctor, platform, settings, tool_registry

TOOL_KEYS = [t.key for t in tool_registry.TOOLS]
NATIVE_TOOLS = [t for t in tool_registry.TOOLS if t.side == "native"]
WIN_TOOLS = [t for t in tool_registry.TOOLS if t.side == "win32"]
DIR_CHECKS = [("games_dir", "games_dir"), ("archives_dir", "archives_dir"),
              ("temp_dir", "temp_dir")]
# One row per tool, plus the machine config, the three deliverable folders,
# the workspace root and one row per logical private location.
TOTAL_CHECKS = (len(TOOL_KEYS) + 1 + len(DIR_CHECKS) + 1
                + len(settings.PRIVATE_PATHS))


@pytest.fixture
def healthy(monkeypatch, tmp_path):
    """Every resolver returns an existing path; env_config.json present and
    readable; every deliverable dir exists -> all checks must be OK."""
    exe = tmp_path / "tool.bin"
    exe.write_bytes(b"x")
    for tool in tool_registry.TOOLS:
        # doctor resolves each tool through the registry module, so that is
        # where a test must patch it
        monkeypatch.setattr(tool_registry, tool.resolver, lambda _p=exe: str(_p))
    cfg = tmp_path / "env_config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
    for _label, fname in DIR_CHECKS:
        d = tmp_path / fname
        d.mkdir()
        monkeypatch.setattr(deliverables, fname, lambda _d=d: str(_d))
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
        tool = tool_registry.TOOLS_BY_KEY[key]
        monkeypatch.setattr(tool_registry, tool.resolver, lambda: None)
        by = _by_label(doctor.collect_checks())
        assert not by[key].ok
        expected = "(not configured)" if tool.side == "win32" else "(not found)"
        assert by[key].detail == expected
        assert by[key].hint
        assert all(c.ok for lbl, c in by.items() if lbl != key)

    @pytest.mark.parametrize("key", TOOL_KEYS)
    def test_only_required_tools_block_a_build(self, monkeypatch, healthy,
                                               key):
        """A missing tool is a MISS only when a build cannot proceed without
        it; everything else is a WARN (PLAN Phase 4 task 8)."""
        tool = tool_registry.TOOLS_BY_KEY[key]
        monkeypatch.setattr(tool_registry, tool.resolver, lambda: None)
        expected = doctor._is_fatal(key)
        assert expected is tool.status.missing_is_fatal or \
            tool.status is tool_registry.ToolStatus.WINDOWS_BRIDGE

    def test_a_missing_optional_tool_does_not_fail_the_report(
            self, monkeypatch, healthy):
        monkeypatch.setattr(tool_registry, "find_node", lambda: None)
        lines = doctor.render(doctor.collect_checks())
        assert "[WARN] node" in "\n".join(lines)
        assert not any(l.startswith("[MISS] node") for l in lines)

    def test_a_missing_window_tool_warns_on_windows_only(
            self, monkeypatch, healthy):
        """The PowerShell bridge exists to reach the Windows side FROM WSL,
        so its absence is only a problem there."""
        monkeypatch.setattr(tool_registry, "find_powershell", lambda: None)
        monkeypatch.setattr(platform, "is_wsl", lambda: False)
        assert not doctor._is_fatal("powershell")
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert doctor._is_fatal("powershell")

    def test_non_tool_checks_are_always_fatal(self):
        for label in ("machine config", "games_dir", "archives_dir",
                      "temp_dir", "workspace root"):
            assert doctor._is_fatal(label), label

    def test_registry_covers_every_tool_resolver(self):
        names = {t.resolver for t in tool_registry.TOOLS}
        assert len(names) == len(tool_registry.TOOLS)
        for name in names:
            assert callable(getattr(tool_registry, name))

    def test_native_and_win_split(self):
        assert {t.key for t in NATIVE_TOOLS}.isdisjoint(
            {t.key for t in WIN_TOOLS})
        assert "win7z" in {t.key for t in WIN_TOOLS}

    def test_env_config_absent_is_ok(self, monkeypatch, healthy, tmp_path):
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", tmp_path / "no-such.json")
        by = _by_label(doctor.collect_checks())
        assert by["machine config"].ok
        assert "(absent)" in by["machine config"].detail

    def test_env_config_unreadable(self, monkeypatch, healthy, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{ not valid json", encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
        by = _by_label(doctor.collect_checks())
        assert not by["machine config"].ok
        assert "(invalid)" in by["machine config"].detail

    def test_env_config_non_dict_root(self, monkeypatch, healthy, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("[1, 2]", encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
        by = _by_label(doctor.collect_checks())
        assert not by["machine config"].ok
        assert "(invalid)" in by["machine config"].detail

    @pytest.mark.parametrize("label,fname", DIR_CHECKS)
    def test_each_dir_missing_when_uncreatable(self, monkeypatch, healthy,
                                               tmp_path, label, fname):
        # a path under a *file* can never be created on demand
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        ghost = str(blocker / label)
        monkeypatch.setattr(deliverables, fname, lambda _d=ghost: _d)
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
        # ffmpeg is `required`, so its absence is a MISS (with a hint)
        monkeypatch.setattr(tool_registry, "find_ffmpeg", lambda: None)
        lines = doctor.render(doctor.collect_checks())
        miss = next(l for l in lines if l.startswith("[MISS]"))
        assert "->" in miss
        assert "ffmpeg" in miss


class TestJsonReport:
    """`doctor --json` is a stable interface other tooling reads, so its shape
    is pinned here."""

    def test_json_is_machine_readable(self, healthy, capsys):
        assert doctor.run(["--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"ok", "checks", "tools", "private",
                                "warnings"}
        assert payload["ok"] is True
        assert payload["warnings"] == []
        assert [c["label"] for c in payload["checks"]][:len(TOOL_KEYS)] == \
            TOOL_KEYS
        assert {t["key"] for t in payload["tools"]} == set(TOOL_KEYS)

    def test_json_reports_failure(self, monkeypatch, healthy, capsys):
        monkeypatch.setattr(tool_registry, "win_7z", lambda: None)
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert doctor.run(["--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False

    def test_json_keeps_warnings_out_of_ok(self, monkeypatch, healthy,
                                           capsys):
        monkeypatch.setattr(tool_registry, "find_node", lambda: None)
        assert doctor.run(["--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["warnings"] == ["node"]

    def test_every_check_row_has_the_pinned_shape(self, healthy, capsys):
        doctor.run(["--json"])
        payload = json.loads(capsys.readouterr().out)
        for row in payload["checks"]:
            assert set(row) == {"label", "ok", "detail", "hint", "source"}
            assert isinstance(row["label"], str) and row["label"]
            assert isinstance(row["ok"], bool)
            assert isinstance(row["detail"], str)
            assert isinstance(row["hint"], str)
            assert isinstance(row["source"], str)

    def test_every_tool_row_reports_its_status(self, healthy, capsys):
        """A missing tool must be reported with its role, so 'required' and
        'test-only' are not treated alike by the reader."""
        doctor.run(["--json"])
        payload = json.loads(capsys.readouterr().out)
        known = {s.value for s in tool_registry.ToolStatus}
        for row in payload["tools"]:
            assert set(row) >= {"key", "path", "source", "side", "purpose",
                                "hint", "status"}
            assert row["status"] in known, row

    def test_private_section_reports_the_migration_state(self, healthy,
                                                        capsys):
        doctor.run(["--json"])
        payload = json.loads(capsys.readouterr().out)
        rows = payload["private"]
        assert {r["key"] for r in rows} == set(settings.PRIVATE_PATHS)
        for row in rows:
            assert set(row) == {"key", "path", "source",
                                "legacy_available"}
            assert row["source"] in ("current", "legacy", "missing")

    def test_each_private_location_has_a_check_row(self, healthy, capsys):
        doctor.run(["--json"])
        payload = json.loads(capsys.readouterr().out)
        labels = {c["label"] for c in payload["checks"]}
        for key in settings.PRIVATE_PATHS:
            assert f"private:{key}" in labels
        assert "workspace root" in labels


class TestRun:
    def test_run_exit_zero_when_all_ok(self, healthy, capsys):
        assert doctor.run() == 0
        out = capsys.readouterr().out
        assert "[MISS]" not in out
        assert "[WARN]" not in out
        assert "%d/%d checks OK" % (TOTAL_CHECKS, TOTAL_CHECKS) in out

    def test_run_exit_one_when_a_required_tool_is_missing(
            self, monkeypatch, healthy, capsys):
        monkeypatch.setattr(tool_registry, "find_ffmpeg", lambda: None)
        assert doctor.run() == 1
        out = capsys.readouterr().out
        assert "[MISS] ffmpeg" in out
        assert "%d/%d checks OK" % (TOTAL_CHECKS - 1, TOTAL_CHECKS) in out

    def test_run_exit_zero_when_only_optional_tools_are_missing(
            self, monkeypatch, healthy, capsys):
        """A machine without node/git still builds games; doctor must say so
        instead of exiting 1 as though the environment were broken."""
        monkeypatch.setattr(tool_registry, "find_node", lambda: None)
        monkeypatch.setattr(tool_registry, "find_git", lambda: None)
        assert doctor.run() == 0
        out = capsys.readouterr().out
        assert "[WARN] node" in out and "[WARN] git" in out
        assert "not required for a build here" in out


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
