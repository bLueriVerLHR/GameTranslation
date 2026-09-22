"""Tests for tools/check_coverage.py - the per-area coverage floor gate.

Why this file exists
--------------------
`tools/check_coverage.py` is the gate that stops coverage from quietly sliding
(PLAN.md Phase 5 task 4).  A gate that cannot fail is worse than no gate, so
each rule here is exercised from both sides: a clean measurement passes, a
dropped measurement fails, and the waiver path is proven to be the only way a
drop can be accepted.
"""

import json
import logging
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO_ROOT, "tools", "check_coverage.py")
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import check_coverage as cc  # noqa: E402


def _entry(statements, covered_lines, branches, covered_branches):
    return {"summary": {
        "num_statements": statements,
        "covered_lines": covered_lines,
        "num_branches": branches,
        "covered_branches": covered_branches,
    }}


def _report(files, total=None):
    files = {name: _entry(*counts) for name, counts in files.items()}
    if total is None:
        statements = sum(e["summary"]["num_statements"] for e in files.values())
        covered = sum(e["summary"]["covered_lines"] for e in files.values())
        branches = sum(e["summary"]["num_branches"] for e in files.values())
        covered_b = sum(e["summary"]["covered_branches"]
                        for e in files.values())
    else:
        statements, covered, branches, covered_b = total
    return {"files": files, "totals": {
        "num_statements": statements,
        "covered_lines": covered,
        "num_branches": branches,
        "covered_branches": covered_b,
    }}


def _paths(module_pct=80, total_pct=80):
    """A report holding one high-risk module per area at `module_pct`.

    The defaults are deliberately below 100 so a test can assert that a drop
    is detected; `total_pct` sets the aggregate independently.
    """
    covered = int(module_pct)
    files = {}
    for module in cc.HIGH_RISK:
        files[module] = (100, covered, 0, 0)
    return _report(files, total=(100, int(total_pct), 0, 0))


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

class TestMeasure:
    def test_combines_lines_and_branches(self):
        measured = cc.measure(_report({
            "rpgmaker/archive.py": (10, 8, 4, 3),      # 11/14
        }))
        assert measured["modules"]["rpgmaker/archive.py"] == 78.6
        assert measured["areas"]["rpgmaker"] == 78.6

    def test_normalises_windows_separators(self):
        measured = cc.measure(_report({
            "rpgmaker\\archive.py": (10, 10, 0, 0),
        }))
        assert "rpgmaker/archive.py" in measured["modules"]

    def test_a_module_with_no_statements_is_not_zero_covered(self):
        # An empty module is not an untested one; dividing by zero would make
        # the gate report 0% and fail on a legitimate file.
        measured = cc.measure(_report({"rpgmaker/empty.py": (0, 0, 0, 0)}))
        assert measured["modules"]["rpgmaker/empty.py"] == 100.0

    def test_area_percentage_aggregates_its_modules(self):
        measured = cc.measure(_report({
            "kirikiri/a.py": (10, 10, 0, 0),
            "kirikiri/b.py": (10, 0, 0, 0),
        }))
        assert measured["areas"]["kirikiri"] == 50.0


# ---------------------------------------------------------------------------
# baseline recording
# ---------------------------------------------------------------------------

class TestBuildBaseline:
    def test_floors_round_down_never_up(self):
        # Rounding to nearest could place the floor above what was measured,
        # so the baseline would fail the commit that recorded it.
        measured = cc.measure(_report({"rpgmaker/archive.py": (10, 9, 7, 6)}))
        for module in cc.HIGH_RISK:
            measured["modules"].setdefault(module, 88.8)
        baseline = cc.build_baseline(measured, "cmd")
        for value in list(baseline["modules"].values()) + [baseline["total"]]:
            assert value * 10 == int(value * 10)

    def test_missing_high_risk_module_is_an_error(self):
        # If a high-risk module produced no coverage entry it was renamed or
        # deleted; the gate must not silently stop watching it.
        measured = cc.measure(_report({"rpgmaker/archive.py": (10, 10, 0, 0)}))
        with pytest.raises(SystemExit) as excinfo:
            cc.build_baseline(measured, "cmd")
        assert "absent from the report" in str(excinfo.value)

    def test_every_high_risk_module_is_recorded(self):
        baseline = cc.build_baseline(cc.measure(_paths()), "cmd")
        assert set(baseline["modules"]) == set(cc.HIGH_RISK)
        assert baseline["schema"] == cc.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

class TestCompare:
    def _baseline(self, floor=90.0):
        modules = dict.fromkeys(cc.HIGH_RISK, floor)
        return {"areas": {"rpgmaker": floor}, "modules": modules,
                "total": floor, "waivers": {}}

    def test_hold_earns_no_regression(self):
        baseline = self._baseline(50.0)
        regressions, _gains = cc.compare(baseline, cc.measure(_paths()))
        assert regressions == []

    def test_drop_is_a_regression_naming_the_target(self):
        baseline = self._baseline(99.9)
        regressions, _gains = cc.compare(baseline, cc.measure(_paths()))
        assert any("total" in line for line in regressions)
        assert any("module rpgmaker/archive.py" in line for line in regressions)

    def test_perfect_measurement_never_regresses(self):
        baseline = self._baseline(99.9)
        measured = cc.measure(_paths(module_pct=100, total_pct=100))
        regressions, _gains = cc.compare(baseline, measured)
        assert regressions == []

    def test_gain_is_reported_but_not_a_failure(self):
        baseline = self._baseline(10.0)
        regressions, gains = cc.compare(baseline, cc.measure(_paths()))
        assert regressions == []
        assert gains

    def test_unmeasured_module_is_a_regression(self):
        baseline = self._baseline(50.0)
        measured = cc.measure(_report({"rpgmaker/archive.py": (10, 10, 0, 0)}))
        regressions, _gains = cc.compare(baseline, measured)
        assert any("no longer measured" in line for line in regressions)

    def test_waiver_is_the_only_way_to_accept_a_drop(self):
        baseline = self._baseline(99.9)
        baseline["waivers"] = {"rpgmaker/archive.py": "probe"}
        regressions, _gains = cc.compare(baseline, cc.measure(_paths()))
        assert not any("rpgmaker/archive.py" in line for line in regressions)
        assert any("total" in line for line in regressions)


class TestUnknownAreas:
    def test_new_area_must_be_recorded(self):
        baseline = {"areas": {"rpgmaker": 90.0}, "modules": {}, "total": 90.0}
        measured = cc.measure(_report({
            "rpgmaker/a.py": (10, 10, 0, 0),
            "brandnew/b.py": (10, 10, 0, 0),
        }))
        assert cc.unknown_areas(baseline, measured) == ["brandnew"]


# ---------------------------------------------------------------------------
# CLI behaviour (the contract a caller depends on)
# ---------------------------------------------------------------------------

def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _run(*argv):
    return subprocess.run(
        [sys.executable, TOOL, *argv],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")


class TestCli:
    def test_update_then_check_round_trips(self, tmp_path):
        report = _write(tmp_path, "cov.json", _paths())
        baseline = str(tmp_path / "floor.json")
        first = _run(report, "--baseline", baseline, "--update")
        assert first.returncode == 0, first.stderr
        recorded = json.loads(open(baseline, encoding="utf-8").read())
        assert recorded["waivers"] == {}
        assert set(recorded["modules"]) == set(cc.HIGH_RISK)
        assert recorded["total"] == 80.0
        second = _run(report, "--baseline", baseline)
        assert second.returncode == 0, second.stderr

    def test_update_preserves_waivers_and_records_new_floors(self, tmp_path):
        report = _write(tmp_path, "cov.json", _paths(module_pct=50,
                                                     total_pct=50))
        baseline = str(tmp_path / "floor.json")
        assert _run(report, "--baseline", baseline, "--update").returncode == 0
        recorded = json.loads(open(baseline, encoding="utf-8").read())
        recorded["waivers"] = {"rpgmaker/archive.py": "probe"}
        with open(baseline, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(recorded, handle)
        better = _write(tmp_path, "better.json", _paths(module_pct=90,
                                                        total_pct=90))
        assert _run(better, "--baseline", baseline, "--update").returncode == 0
        after = json.loads(open(baseline, encoding="utf-8").read())
        assert after["total"] == 90.0
        assert after["waivers"] == {"rpgmaker/archive.py": "probe"}

    def test_update_refuses_to_lower_a_module_floor_without_a_waiver(
            self, tmp_path):
        report = _write(tmp_path, "cov.json", _paths(module_pct=90,
                                                     total_pct=90))
        baseline = str(tmp_path / "floor.json")
        assert _run(report, "--baseline", baseline, "--update").returncode == 0
        worse = _write(tmp_path, "worse.json", _paths(module_pct=10,
                                                      total_pct=90))
        result = _run(worse, "--baseline", baseline, "--update")
        assert result.returncode == 1
        assert "refusing to lower" in result.stderr
        assert "rpgmaker/archive.py" in result.stderr

    def test_check_without_a_baseline_fails_loudly(self, tmp_path):
        report = _write(tmp_path, "cov.json", _paths())
        result = _run(report, "--baseline", str(tmp_path / "absent.json"))
        assert result.returncode == 1
        assert "baseline missing" in result.stderr

    def test_a_regression_exits_nonzero(self, tmp_path):
        report = _write(tmp_path, "cov.json", _paths())
        baseline = str(tmp_path / "floor.json")
        assert _run(report, "--baseline", baseline, "--update").returncode == 0
        recorded = json.loads(open(baseline, encoding="utf-8").read())
        recorded["total"] = 99.9
        with open(baseline, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(recorded, handle)
        result = _run(report, "--baseline", baseline)
        assert result.returncode == 1
        assert "coverage regression" in result.stderr

    def test_a_baseline_with_a_bom_still_loads(self, tmp_path):
        # Windows editors add a BOM; the gate must not report a corrupt
        # baseline for an encoding detail.
        report = _write(tmp_path, "cov.json", _paths())
        baseline = str(tmp_path / "floor.json")
        assert _run(report, "--baseline", baseline, "--update").returncode == 0
        text = open(baseline, encoding="utf-8").read()
        with open(baseline, "w", encoding="utf-8-sig", newline="\n") as handle:
            handle.write(text)
        assert _run(report, "--baseline", baseline).returncode == 0

    def test_update_refuses_to_lower_a_floor_without_a_waiver(self, tmp_path):
        report = _write(tmp_path, "cov.json", _paths(module_pct=100,
                                                     total_pct=100))
        baseline = str(tmp_path / "floor.json")
        assert _run(report, "--baseline", baseline, "--update").returncode == 0
        worse = _write(tmp_path, "worse.json", _paths(module_pct=50,
                                                      total_pct=50))
        result = _run(worse, "--baseline", baseline, "--update")
        assert result.returncode == 1
        assert "refusing to lower" in result.stderr

    def test_help_renders(self):
        result = _run("--help")
        assert result.returncode == 0
        assert "coverage" in result.stdout.lower()


# ---------------------------------------------------------------------------
# in-process command coverage
# ---------------------------------------------------------------------------

class TestCommandBodyInProcess:
    """Drive `cmd()` in this interpreter, not through a child process.

    The subprocess tests above exercise the real CLI contract (argv parsing,
    exit code, stderr), but coverage.py cannot see into a child process unless
    it is started through `coverage run`, so the entire body of `cmd()` was
    invisible to the coverage gate - the tool that *enforces* the gate was the
    one line the gate could not measure.  These tests close that hole by
    calling `main()` directly; the argv-shape proof stays with `TestCli`.
    """

    def test_update_then_gate_through_main(self, tmp_path, capsys):
        report = _write(tmp_path, "cov.json", _paths())
        baseline = str(tmp_path / "floor.json")
        assert cc.main([report, "--baseline", baseline, "--update"]) == 0
        assert cc.main([report, "--baseline", baseline]) == 0
        out = capsys.readouterr().out
        assert "coverage floors (flat or rising)" in out
        assert "total" in out

    def test_a_regression_reports_and_returns_one(self, tmp_path, capsys):
        report = _write(tmp_path, "cov.json", _paths())
        baseline = str(tmp_path / "floor.json")
        assert cc.main([report, "--baseline", baseline, "--update"]) == 0
        recorded = json.loads(open(baseline, encoding="utf-8").read())
        recorded["total"] = 99.9
        with open(baseline, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(recorded, handle)
        capsys.readouterr()
        assert cc.main([report, "--baseline", baseline]) == 1
        assert "coverage regression" in capsys.readouterr().err

    def test_an_unrecorded_area_is_reported(self, tmp_path, caplog):
        """A brand-new package directory must not be invisible to the gate."""
        report = _write(tmp_path, "cov.json", _paths())
        baseline = str(tmp_path / "floor.json")
        assert cc.main([report, "--baseline", baseline, "--update"]) == 0
        recorded = json.loads(open(baseline, encoding="utf-8").read())
        recorded["areas"].pop("rpgmaker", None)
        with open(baseline, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(recorded, handle)
        with caplog.at_level(logging.ERROR):
            assert cc.main([report, "--baseline", baseline]) == 1
        assert "unrecorded coverage areas" in caplog.text

    def test_a_missing_baseline_is_a_loud_failure(self, tmp_path, caplog):
        report = _write(tmp_path, "cov.json", _paths())
        with caplog.at_level(logging.ERROR):
            assert cc.main([report, "--baseline",
                            str(tmp_path / "absent.json")]) == 1
        assert "no baseline at" in caplog.text
        assert "run with --update" in caplog.text

    def test_update_refuses_a_silent_drop_through_main(self, tmp_path, caplog):
        better = _write(tmp_path, "better.json", _paths(module_pct=90,
                                                         total_pct=90))
        baseline = str(tmp_path / "floor.json")
        assert cc.main([better, "--baseline", baseline, "--update"]) == 0
        worse = _write(tmp_path, "worse.json", _paths(module_pct=10,
                                                       total_pct=90))
        with caplog.at_level(logging.ERROR):
            assert cc.main([worse, "--baseline", baseline, "--update"]) == 1
        assert "refusing to lower" in caplog.text

    def test_a_waiver_accepts_a_documented_drop(self, tmp_path, caplog):
        """The waiver is the one documented way past a regression.

        A floor may only be beaten down in writing: the whole point of the
        record is that the next reader sees *why* a package is allowed to sit
        below its recorded level.
        """
        better = _write(tmp_path, "better.json", _paths(module_pct=90,
                                                         total_pct=90))
        baseline = str(tmp_path / "floor.json")
        assert cc.main([better, "--baseline", baseline, "--update"]) == 0
        worse = _write(tmp_path, "worse.json", _paths(module_pct=10,
                                                       total_pct=10))
        recorded = json.loads(open(baseline, encoding="utf-8").read())
        recorded["waivers"] = {"rpgmaker/archive.py": "renamed upstream",
                               "total": "area under repair"}
        for name in recorded["areas"]:
            recorded["waivers"][name] = "area under repair"
        with open(baseline, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(recorded, handle)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert cc.main([worse, "--baseline", baseline]) == 1
        # The two waived entries are suppressed; what still fails is every
        # *other* high-risk module, which is exactly the intended contract.
        assert "waived: module rpgmaker/archive.py" in caplog.text
        assert "waived: total" in caplog.text
        assert "waived: module rpgmaker/assets.py" not in caplog.text
        assert "rpgmaker/assets.py:" in caplog.text
