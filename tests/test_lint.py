#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lint gate: `ruff check` with the rules pinned in pyproject.toml.

The selected set is the bug-focused one (pyflakes + syntax), not style, so a
failure here means something real: an undefined name, an unused import or
variable, a redefined function (a silently shadowed test, normally).

Skipped when ruff is not installed (`pip install -e ".[dev]"`) so a plain
runtime install can still run the suite.
"""
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ruff_available():
    try:
        out = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def test_ruff_check_is_clean():
    if not ruff_available():
        pytest.skip("ruff is not installed (pip install -e '.[dev]')")
    proc = subprocess.run([sys.executable, "-m", "ruff", "check", "."],
                          cwd=REPO_ROOT, capture_output=True, text=True,
                          timeout=600)
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
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
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
    assert '"docs/table"' in settings
    assert 'project_root = "%s"' % REPO_ROOT.replace("\\", "\\") in settings
