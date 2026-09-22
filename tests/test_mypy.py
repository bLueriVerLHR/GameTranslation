"""Tests for the mypy budget gate (``tools/mypy_check.py``).

The gate exists because a type checker is the one quality tool whose *failure
modes look like success*: ``mypy`` can abort on a config or dependency problem
and still exit non-zero, which is indistinguishable from "there is debt".  So
these tests are mostly about the REPORT and about the two properties that make
a burndown real rather than decorative:

* the recorded error budget may only shrink - raising it is how a burndown
  silently becomes a waiver list;
* a module listed in the strict tier is held at ZERO errors, so cleaning a
  module cannot be undone by the next change while the global count absorbs
  the slack.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import mypy_check  # noqa: E402


class TestTheBudgetsComeFromPyproject:
    """One source of truth: the numbers live in pyproject, not in the tool."""

    def test_the_error_budget_is_recorded(self):
        assert mypy_check.error_budget() == 188

    def test_the_strict_tier_is_not_empty(self):
        modules = mypy_check.strict_list()
        # A tier with no members would make `check_strict` pass vacuously.
        assert len(modules) >= 15

    def test_every_strict_module_exists_on_disk(self):
        missing = [m for m in mypy_check.strict_list()
                   if not os.path.isfile(os.path.join(ROOT, m))]
        assert missing == [], (
            "a strict-tier module that no longer exists silently shrinks the "
            "guarded surface:\n  " + "\n  ".join(missing))

    def test_the_strict_tier_is_sorted_and_deduplicated(self):
        modules = list(mypy_check.strict_list())
        assert modules == sorted(modules)
        assert len(modules) == len(set(modules))

    def test_the_strict_modules_are_real_python_paths(self):
        for module in mypy_check.strict_list():
            assert module.endswith(".py")
            assert "/" in module, f"{module} should be a repo-relative path"

    def test_every_target_package_is_checked(self):
        for package in ("rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity",
                        "translation", "tools"):
            assert package in mypy_check.TARGETS

    def test_the_config_targets_python_310(self):
        """The repo supports 3.10, so the checker must judge 3.10."""
        config = mypy_check._config()["tool"]["mypy"]
        assert config["python_version"] == "3.10"

    def test_the_config_ignores_site_packages(self):
        """Load-bearing: numpy's 3.12-only stubs make mypy abort on 3.10."""
        config = mypy_check._config()["tool"]["mypy"]
        assert config["no_site_packages"] is True

    def test_the_config_pins_one_platform(self):
        """The budget must not depend on which runner measures it.

        Unpinned, mypy types the standard library for the host OS, so
        ``ctypes.windll`` is an error on Linux CI and fine on Windows and the
        same commit measures 189 there against 188 here (CI: ``mypy: 189
        error(s), budget 188``).  A budget that moves with the runner cannot
        be enforced, so the platform is pinned explicitly.
        """
        config = mypy_check._config()["tool"]["mypy"]
        assert config["platform"], "an unset platform makes the count host-dependent"
        assert config["platform"] == "linux", (
            "CI runs the gate on both runners; the pinned platform must be the "
            "one the recorded budget was measured on")


class TestParseErrors:
    """Counting is the metric, so the counting must be exact."""

    def test_counts_a_plain_error_line(self):
        assert mypy_check.parse_errors(
            'rpgmaker/cli.py:12: error: bad thing  [assignment]') == 1

    def test_counts_errors_in_the_windows_spelling(self):
        assert mypy_check.parse_errors(
            r'rpgmaker\cli.py:12: error: bad thing  [assignment]') == 1

    def test_ignores_notes(self):
        text = ("rpgmaker/cli.py:12: error: bad  [assignment]\n"
                "rpgmaker/cli.py:12: note: see the docs")
        assert mypy_check.parse_errors(text) == 1

    def test_ignores_an_error_word_inside_a_message(self):
        """A message quoting 'error:' is not itself an error."""
        text = ("rpgmaker/cli.py:12: error: expected 'error: ...' here"
                "  [misc]")
        assert mypy_check.parse_errors(text) == 1

    def test_ignores_files_outside_the_targets(self):
        """With no_site_packages there should be none; one means the config
        regressed, and counting it would inflate a budget nobody can fix."""
        assert mypy_check.parse_errors(
            '/somewhere/site-packages/numpy/__init__.pyi:7: error: nope'
            '  [syntax]') == 0

    def test_ignores_output_that_is_not_a_finding(self):
        assert mypy_check.parse_errors("Found 3 errors in 2 files\n") == 0

    def test_handles_empty_output(self):
        assert mypy_check.parse_errors("") == 0
        assert mypy_check.parse_errors(None) == 0

    def test_counts_several(self):
        text = "\n".join([
            "rpgmaker/b.py:1: error: one  [arg-type]",
            "rpgmaker/b.py:2: error: two  [arg-type]",
            "tools/c.py:9: error: three  [misc]",
        ])
        assert mypy_check.parse_errors(text) == 3

    def test_a_path_outside_the_targets_is_not_counted(self):
        """The filter is by package, so an invented top-level dir is ignored.

        This is the same rule that keeps a site-packages error (which no
        contributor can fix) out of the budget.
        """
        assert mypy_check.parse_errors(
            "somewhere/else.py:1: error: not ours  [misc]") == 0


class TestMypyCannotRunIsNotAFinding:
    """The failure mode the whole wrapper exists for."""

    def test_the_exit_code_for_could_not_run_is_two(self):
        assert mypy_check.COULD_NOT_RUN == 2

    def test_an_unstartable_mypy_is_reported_not_counted(self, monkeypatch):
        def explode(*_a, **_k):
            raise OSError("no such binary")
        monkeypatch.setattr(mypy_check.proctools, "run", explode)
        code, count, output = mypy_check.run_mypy(("rpgmaker",))
        assert code == mypy_check.COULD_NOT_RUN
        assert count == 0
        assert "could not start mypy" in output

    def test_a_bad_config_is_distinguished_from_debt(self, tmp_path, monkeypatch):
        """The real incident: a BOM broke the config, mypy aborted, and a
        sweep reported everything as passing."""
        class Proc:
            returncode = 2
            stdout = ""
            stderr = ("mypy-strict-probe.ini: File contains no section "
                      "headers\n")
        monkeypatch.setattr(mypy_check.proctools, "run",
                            lambda *_a, **_k: Proc())
        code, _count, output = mypy_check.run_mypy(("rpgmaker",))
        assert code == mypy_check.COULD_NOT_RUN
        assert "no section headers" in output


class TestStrictTierRefusals:
    def test_a_missing_module_is_reported(self, tmp_path):
        problems = mypy_check.check_strict(("rpgmaker/does_not_exist.py",))
        assert len(problems) == 1
        assert "does not exist" in problems[0]

    def test_a_clean_module_reports_nothing(self, monkeypatch):
        monkeypatch.setattr(mypy_check, "run_mypy",
                            lambda *a, **k: (0, 0, ""))
        assert mypy_check.check_strict(("rpgmaker/platform.py",)) == []

    def test_a_dirty_module_is_reported(self, monkeypatch):
        monkeypatch.setattr(
            mypy_check, "run_mypy",
            lambda *a, **k: (1, 1,
                             "rpgmaker/platform.py:5: error: nope  [misc]"))
        problems = mypy_check.check_strict(("rpgmaker/platform.py",))
        assert len(problems) == 1 and "nope" in problems[0]

    def test_a_could_not_run_is_reported_inside_the_strict_tier(
            self, monkeypatch):
        monkeypatch.setattr(mypy_check, "run_mypy",
                            lambda *a, **k: (mypy_check.COULD_NOT_RUN, 0,
                                             "boom"))
        problems = mypy_check.check_strict(("rpgmaker/platform.py",))
        assert len(problems) == 1 and "could not run" in problems[0]


class TestTheCli:
    def test_a_count_within_budget_is_a_pass(self, monkeypatch):
        monkeypatch.setattr(mypy_check, "run_mypy",
                            lambda *a, **k: (1, mypy_check.error_budget(), ""))
        monkeypatch.setattr(mypy_check, "check_strict", lambda *_a: [])
        assert mypy_check.main([]) == 0

    def test_a_rising_count_fails(self, monkeypatch):
        monkeypatch.setattr(
            mypy_check, "run_mypy",
            lambda *a, **k: (1, mypy_check.error_budget() + 1, ""))
        monkeypatch.setattr(mypy_check, "check_strict", lambda *_a: [])
        assert mypy_check.main([]) == 1

    def test_a_strict_regression_fails_even_under_budget(self, monkeypatch):
        """The floor is the point: budget slack must not hide a regression."""
        monkeypatch.setattr(mypy_check, "run_mypy",
                            lambda *a, **k: (0, 0, ""))
        monkeypatch.setattr(mypy_check, "check_strict",
                            lambda *_a: ["rpgmaker/platform.py:5: error: x"])
        assert mypy_check.main([]) == 1

    def test_json_reports_both_numbers(self, monkeypatch, capsys):
        monkeypatch.setattr(mypy_check, "run_mypy",
                            lambda *a, **k: (1, 10, ""))
        monkeypatch.setattr(mypy_check, "check_strict", lambda *_a: [])
        monkeypatch.setattr(mypy_check, "error_budget", lambda: 20)
        assert mypy_check.main(["--json"]) == 0
        out = capsys.readouterr().out
        assert '"errors": 10' in out and '"budget": 20' in out

    def test_could_not_run_is_a_loud_failure(self, monkeypatch, capsys):
        monkeypatch.setattr(
            mypy_check, "run_mypy",
            lambda *a, **k: (mypy_check.COULD_NOT_RUN, 0, "config is broken"))
        code = mypy_check.main([])
        captured = capsys.readouterr()
        assert code == 1
        assert "nothing was measured" in captured.err
        assert "config is broken" in captured.err

    def test_update_refuses_to_raise_the_budget(self, monkeypatch, capsys):
        monkeypatch.setattr(
            mypy_check, "run_mypy",
            lambda *a, **k: (1, mypy_check.error_budget() + 5, ""))
        assert mypy_check.main(["--update"]) == 1
        assert "refusing to raise" in capsys.readouterr().err

    def test_update_lowers_the_budget(self, monkeypatch, tmp_path):
        target = tmp_path / "pyproject.toml"
        target.write_text("[a]\n\nerrors = 188\n", encoding="utf-8")
        monkeypatch.setattr(mypy_check, "_ROOT", str(tmp_path))
        monkeypatch.setattr(mypy_check, "run_mypy", lambda *a, **k: (1, 5, ""))
        monkeypatch.setattr(mypy_check, "error_budget", lambda: 188)
        assert mypy_check.cmd(update=True) == 0
        assert "errors = 5" in target.read_text(encoding="utf-8")

    def test_write_budget_refuses_an_ambiguous_file(self, tmp_path,
                                                    monkeypatch):
        target = tmp_path / "pyproject.toml"
        target.write_text("errors = 1\nerrors = 2\n", encoding="utf-8")
        monkeypatch.setattr(mypy_check, "_ROOT", str(tmp_path))
        with pytest.raises(SystemExit):
            mypy_check._write_budget(7)

    def test_the_budget_line_edit_keeps_every_comment(self, tmp_path,
                                                      monkeypatch):
        """A TOML round-trip would delete the reasoning; a regex must not."""
        target = tmp_path / "pyproject.toml"
        target.write_text("# why the number is 188\nerrors = 188\n# trailing\n",
                          encoding="utf-8")
        monkeypatch.setattr(mypy_check, "_ROOT", str(tmp_path))
        mypy_check._write_budget(12)
        text = target.read_text(encoding="utf-8")
        assert "# why the number is 188" in text
        assert "# trailing" in text
        assert "errors = 12" in text

    def test_help_renders(self, capsys):
        """`cliutil.run` swallows the help SystemExit, so assert on the exit
        code it returns and on the rendered text - not on a raise."""
        assert mypy_check.main(["--help"]) == 0
        out = capsys.readouterr().out
        assert "budget" in out
        assert "--update" in out


class TestTheGateIsWiredIntoTheLocalRunner:
    """A gate nobody runs is documentation."""

    def test_check_all_includes_the_type_gate(self):
        from tools import check_all
        names = [gate.name for gate in check_all.GATES]
        assert "types" in names

    def test_the_type_gate_needs_mypy(self):
        from tools import check_all
        gate = check_all.BY_NAME["types"]
        assert gate.needs == ("mypy",)
        assert gate.required is True

    def test_the_type_gate_is_not_coverage_only(self):
        from tools import check_all
        assert check_all.BY_NAME["types"].coverage_only is False
        names = [g.name for g in check_all._select((), (), False, False)]
        assert "types" in names


def test_mypy_is_installed_for_the_gate_to_do_anything():
    """If mypy is absent the gate skips, and a skip is not a pass."""
    assert importlib.util.find_spec("mypy") is not None, (
        "mypy is not installed in this environment; tools/mypy_check.py will "
        "report SKIPPED rather than measuring anything")
