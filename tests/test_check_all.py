#!/usr/bin/env python3
"""Tests for tools/check_all.py - the local pre-merge gate runner.

Why this file exists
--------------------
The checklist that must be green before a merge lives in `AGENTS.md`, and it
was executed by hand.  Two failure modes were observed in this repository:

* a gate was forgotten (a `pyproject.toml` change without re-running
  `uv lock`, a new package-data file without re-running the wheel test);
* a gate was skipped because a tool was missing, which reads exactly like a
  pass.

`tools/check_all.py` exists to make both impossible, so the tests here are
mostly about the *report*: a mandatory gate that cannot run must fail, an
optional one must warn without hiding the run, and the selected set must be
printable before anything heavy starts.

The runner shells out to the documented commands, so the gate table itself is
asserted against those commands rather than against a copy of them - a
renamed tool or a dropped flag has to fail here.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import check_all as ca  # noqa: E402


def _gate(name, code="print('ran')", required=True, needs=(), coverage_only=False):
    """A Gate whose "command" is a tiny interpreter snippet.

    Using the real gates here would run the 60-second suite; the runner's job
    is argv/exit handling and reporting, which a synthetic command exercises
    with none of the cost.
    """
    return ca.Gate(name, f"synthetic {name}",
                   lambda root: [sys.executable, "-c", code],
                   required=required, needs=needs,
                   coverage_only=coverage_only)


@pytest.fixture
def table(monkeypatch):
    """Replace the gate table so nothing heavy runs."""
    def install(gates):
        monkeypatch.setattr(ca, "GATES", tuple(gates))
        monkeypatch.setattr(ca, "BY_NAME", {g.name: g for g in gates})
    return install


# ---------------------------------------------------------------------------
# the gate table itself
# ---------------------------------------------------------------------------

class TestTheGateTable:
    def test_every_mandatory_agents_gate_is_present(self):
        """AGENTS.md lists five pre-merge checks; all of them must be wired.

        The names are not decoration: they are what the operator types with
        `--only`, and what the summary table prints.
        """
        names = {gate.name for gate in ca.GATES}
        assert {"hygiene", "compile", "lint", "docs", "tests"} <= names

    def test_every_gate_names_a_real_command(self):
        for gate in ca.GATES:
            argv = gate.argv(REPO_ROOT)
            assert argv and all(isinstance(part, str) for part in argv), gate
            assert gate.summary, gate.name

    def test_the_mandatory_gates_are_not_optional(self):
        mandatory = {gate.name for gate in ca.GATES if gate.required}
        assert {"hygiene", "compile", "lint", "docs", "tests"} <= mandatory

    def test_lock_is_optional_and_dependency_gated(self):
        """`uv` is a convenience: a machine without it must not fail the run."""
        gate = ca.BY_NAME["lock"]
        assert not gate.required
        assert gate.needs == ("uv",)

    def test_the_coverage_gates_are_behind_the_flag(self):
        """Measuring coverage doubles the wall clock, so it is opt-in."""
        assert {g.name for g in ca.GATES if g.coverage_only} == {"coverage",
                                                                 "floors"}


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

class TestSelect:
    def test_the_default_is_every_gate_that_does_not_measure_coverage(self):
        names = [gate.name for gate in ca._select((), (), False, False)]
        assert names == ["hygiene", "compile", "lint", "docs", "tests",
                         "types", "lock", "skips"]

    def test_coverage_replaces_the_plain_suite(self):
        """Running the suite twice for the same evidence is a waste."""
        names = [gate.name for gate in ca._select((), (), False, True)]
        assert "tests" not in names
        assert "coverage" in names and "floors" in names

    def test_fast_drops_only_the_suites(self):
        """The cheap gates stay: they are what catches a mistake early."""
        names = [gate.name for gate in ca._select((), (), True, False)]
        assert names == ["hygiene", "compile", "lint", "docs", "types",
                         "lock", "skips"]

    def test_fast_with_coverage_still_drops_the_measurement(self):
        names = [gate.name for gate in ca._select((), (), True, True)]
        assert "coverage" not in names and "floors" not in names

    def test_only_narrows_to_the_named_gates(self):
        names = [g.name for g in ca._select(("lint", "docs"), (), False, False)]
        assert names == ["lint", "docs"]

    def test_only_keeps_the_table_order_not_the_argument_order(self):
        """The order is the dependency order (cheap, then expensive)."""
        names = [g.name for g in ca._select(("docs", "lint"), (), False, False)]
        assert names == ["lint", "docs"]

    def test_skip_removes_a_gate(self):
        names = [g.name for g in ca._select((), ("tests",), False, False)]
        assert names == ["hygiene", "compile", "lint", "docs", "types",
                         "lock", "skips"]

    def test_an_unknown_name_is_an_error_not_a_silent_noop(self):
        with pytest.raises(ValueError, match="unknown gate"):
            ca._select(("nope",), (), False, False)
        with pytest.raises(ValueError, match="unknown gate"):
            ca._select((), ("nope",), False, False)


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------

class TestRunGates:
    def test_a_passing_gate_is_reported_ok(self):
        outcomes = ca.run_gates([_gate("a")], REPO_ROOT)
        assert [o.status for o in outcomes] == ["ok"]

    def test_a_failing_mandatory_gate_stops_the_run(self):
        gates = [_gate("first", code="raise SystemExit(1)"), _gate("second")]
        outcomes = ca.run_gates(gates, REPO_ROOT)
        assert [o.status for o in outcomes] == ["failed"]
        assert outcomes[0].detail == "exit 1"

    def test_a_failing_optional_gate_does_not_stop_the_run(self):
        """A stale lockfile must not hide a test failure."""
        gates = [_gate("opt", code="raise SystemExit(1)", required=False),
                 _gate("main")]
        outcomes = ca.run_gates(gates, REPO_ROOT)
        assert [o.status for o in outcomes] == ["failed", "ok"]

    def test_a_missing_dependency_skips_and_names_it(self):
        gates = [_gate("needs", needs=("no_such_module_xyz",)), _gate("later")]
        outcomes = ca.run_gates(gates, REPO_ROOT)
        assert outcomes[0].status == "skipped"
        assert "no_such_module_xyz" in outcomes[0].detail
        assert [o.status for o in outcomes] == ["skipped"]

    def test_a_missing_optional_dependency_does_not_stop_the_run(self):
        gates = [_gate("opt", required=False, needs=("no_such_module_xyz",)),
                 _gate("later")]
        outcomes = ca.run_gates(gates, REPO_ROOT)
        assert [o.status for o in outcomes] == ["skipped", "ok"]

    def test_the_failure_output_is_kept_for_the_reader(self):
        gates = [_gate("loud",
                       code="import sys; sys.stderr.write('boom'); "
                            "raise SystemExit(3)")]
        outcomes = ca.run_gates(gates, REPO_ROOT)
        assert "boom" in outcomes[0].output
        assert outcomes[0].detail == "exit 3"

    def test_a_broken_command_is_a_failure_not_a_crash(self):
        """A gate whose command cannot start must still report a result."""
        gate = ca.Gate("broken", "never runs",
                       lambda root: [os.path.join(root, "no-such-program")])
        outcomes = ca.run_gates([gate], REPO_ROOT)
        assert outcomes[0].status == "failed"
        assert "Error" in outcomes[0].detail or "error" in outcomes[0].detail


# ---------------------------------------------------------------------------
# the CLI contract
# ---------------------------------------------------------------------------

class TestCli:
    def test_list_prints_every_gate_and_exits_zero(self, capsys):
        assert ca.main(["--list"]) == 0
        out = capsys.readouterr().out
        for gate in ca.GATES:
            assert gate.name in out

    def test_an_unknown_gate_name_fails_loudly(self, capsys):
        assert ca.main(["--only", "nope"]) == 1
        assert "unknown gate" in capsys.readouterr().err

    def test_a_missing_repo_directory_fails(self, tmp_path, capsys):
        assert ca.main(["--repo", str(tmp_path / "absent")]) == 1
        assert "not a directory" in capsys.readouterr().err

    def test_a_failing_gate_makes_the_run_fail(self, table, capsys):
        table([_gate("bad", code="raise SystemExit(1)")])
        assert ca.main([]) == 1
        assert "gate(s) not satisfied" in capsys.readouterr().err

    def test_a_skipped_mandatory_gate_is_a_failure(self, table, capsys):
        """The whole point of the runner: "could not check" != "checked"."""
        table([_gate("needs", needs=("no_such_module_xyz",))])
        assert ca.main([]) == 1
        captured = capsys.readouterr()
        assert "no_such_module_xyz" in captured.err
        assert "SKIPPED" in captured.out

    def test_a_skipped_optional_gate_only_warns(self, table, capsys, caplog):
        table([_gate("opt", required=False, needs=("no_such_module_xyz",)),
               _gate("ok")])
        assert ca.main([]) == 0
        out = capsys.readouterr().out
        assert "SKIPPED" in out and "OK" in out
        assert "optional gate opt" in caplog.text

    def test_the_summary_counts_every_gate(self, table, capsys):
        table([_gate("a"), _gate("b")])
        assert ca.main([]) == 0
        out = capsys.readouterr().out
        assert "2 gate(s) checked, 2 ran, 0 failed, 0 skipped" in out

    def test_the_final_report_keeps_ci_as_the_authority(self, table, capsys):
        """A local green run must never be read as remote-matrix evidence."""
        table([_gate("bad", code="raise SystemExit(1)")])
        assert ca.main([]) == 1
        assert "CI is still the final authority" in capsys.readouterr().err

    def test_skip_prevents_the_gate_from_running(self, table, capsys):
        table([_gate("a"), _gate("b")])
        assert ca.main(["--skip", "a"]) == 0
        assert "1 gate(s) checked, 1 ran" in capsys.readouterr().out

    def test_a_failure_is_counted_in_the_summary(self, table, capsys):
        table([_gate("a"), _gate("b", code="raise SystemExit(1)")])
        assert ca.main([]) == 1
        assert "2 gate(s) checked, 1 ran, 1 failed" in capsys.readouterr().out

    def test_help_renders(self, capsys):
        assert ca.main(["--help"]) == 0
        assert "--coverage" in capsys.readouterr().out
