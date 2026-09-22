#!/usr/bin/env python3
"""Lint gate: `ruff check` with the rules pinned in pyproject.toml.

The selected set is the bug-focused one (pyflakes + syntax + bugbear +
comprehensions + return + modernisation), so a failure here means something
real: an undefined name, an unused import or variable, a redefined function (a
silently shadowed test, normally), a closure capturing a loop variable.

Two large modernisation families are exempted from the *clean* run and gated
by a static COUNT instead (`[tool.gametranslation.lint-burndown]`):

* `UP031`/`UP030` - `"%d" % n` and `"{a}".format(a=n)`; ~415 legacy sites.
  The mechanical rewrite to `f"{n:d}"` is not behaviour-identical, so it
  needs a real diff review.
* `SIM115` - `open(...)` without a context manager; ~224 sites, mostly the
  `json.load(open(...))` idiom whose handle is closed by refcount.

The budget may only go DOWN: rewriting sites leaves slack, adding one fails
the gate.  See `test_the_printf_and_open_budgets_only_shrink`.

Skipped when ruff is not installed (`pip install -e ".[dev]"`) so a plain
runtime install can still run the suite.
"""
import os
import re
import subprocess
import sys

try:
    import tomllib                 # Python 3.11+
except ImportError:               # pragma: no cover - exercised on 3.10 ci
    import tomli as tomllib        # dev extra; see pyproject.toml

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The exempted families and the pyproject section holding their budgets.
BURNDOWN_RULES = ("UP031", "UP030", "SIM115")
BURNDOWN_SECTION = ("tool", "gametranslation", "lint-burndown")
BURNDOWN_KEY = {"UP031": "up031", "UP030": "up030", "SIM115": "sim115"}


def ruff_available():
    try:
        out = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def test_ruff_check_is_clean():
    if not ruff_available():
        pytest.skip("ruff is not installed (pip install -e '.[dev]')")
    proc = subprocess.run([sys.executable, "-m", "ruff", "check", "."],
                          cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    assert proc.returncode == 0, \
        "ruff found real problems (see pyproject.toml [tool.ruff]):\n" + \
        proc.stdout + proc.stderr


def test_the_lint_config_is_actually_selected():
    """Guard against a silent config loss: with no [tool.ruff] section ruff
    falls back to its own defaults and this gate stops covering the intended
    rules.  Asserts the rules and excludes the repo pins, not just exit 0.
    """
    if not ruff_available():
        pytest.skip("ruff is not installed (pip install -e '.[dev]')")
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--show-settings",
         "pyproject.toml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    assert proc.returncode == 0, proc.stderr
    settings = proc.stdout
    # pyflakes is selected (a bare default run would only have E4/E7/E9/F,
    # so the marker is the explicit E9 we pin alongside it)
    assert "io-error (E902)" in settings
    assert "undefined-name (F821)" in settings
    assert "unused-import (F401)" in settings
    # the bad-name rule is NOT selected (style, not a defect)
    assert "ambiguous-variable-name" not in settings
    # the repo's target version and excludes were read from pyproject.toml
    assert 'unresolved_target_version = "3.10"' in settings or \
        "unresolved_target_version = 3.10" in settings
    # the pinned exclude list was read from pyproject.toml too
    assert '"docs/table"' in settings
    assert '".private"' in settings and '".asset"' in settings
    assert 'project_root = "{}"'.format(REPO_ROOT.replace("\\", "\\")) in settings


def _count_rule(rule):
    """How many findings `rule` reports repo-wide (0 when ruff is absent)."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", rule,
         "--statistics", "."],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    total = 0
    for line in proc.stdout.splitlines():
        match = re.match(r"\s*(\d+)\s+%s\b" % rule, line)
        if match:
            total += int(match.group(1))
    return total


def test_the_printf_and_open_budgets_only_shrink():
    """The two exempted modernisation families must not grow.

    They are exempted from `test_ruff_check_is_clean` because the rewrite is
    not behaviour-identical in bulk (`%d` truncates a float, `f"{v:d}"`
    raises) and because the ~224 `open()` sites need a real review, not a
    sed.  Exempting them silently would let the debt grow forever, so the
    count is pinned in pyproject.toml and may only fall.
    """
    if not ruff_available():
        pytest.skip("ruff is not installed (pip install -e '.[dev]')")
    with open(os.path.join(REPO_ROOT, "pyproject.toml"),
              encoding="utf-8") as handle:
        config = tomllib.loads(handle.read())
    budgets = config
    for part in BURNDOWN_SECTION:
        budgets = budgets.get(part, {})
    assert budgets, "the burn-down budget section disappeared from pyproject.toml"
    for rule in BURNDOWN_RULES:
        budget = budgets.get(BURNDOWN_KEY[rule])
        assert isinstance(budget, int), "no budget pinned for %s" % rule
        actual = _count_rule(rule)
        assert actual <= budget, (
            "%s grew from the pinned budget of %d to %d - rewrite a site "
            "instead of raising the budget, or lower it when you fix some "
            "(pyproject.toml [tool.gametranslation.lint-burndown])"
            % (rule, budget, actual))
        if actual < budget:
            print("%s: %d of %d budgeted (%.0f%% paid off)"
                  % (rule, actual, budget, 100.0 * (budget - actual) / budget))
