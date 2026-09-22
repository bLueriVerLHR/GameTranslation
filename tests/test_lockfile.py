#!/usr/bin/env python3
"""Lockfile gate: `uv.lock` must match `pyproject.toml`.

`uv.lock` is committed (PLAN Phase 1) so that a clean environment resolves the
same dependency set the tests were verified against.  Nothing enforced that
until this test: the lock was verified green in Phase 1, then Phase 4 added
`hypothesis>=6` to `[project.optional-dependencies].dev` and the lock silently
went stale.  No other gate could notice, because every CI job installs with pip
from `pyproject.toml` and never reads the lock - so the drift only surfaces to
whoever runs `uv lock --check` by hand.

Skipped when `uv` is not installed (`pip install uv`), matching the ruff gate in
`tests/test_lint.py`: a plain runtime install can still run the suite.
"""
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def uv_available():
    try:
        out = subprocess.run([sys.executable, "-m", "uv", "--version"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def test_uv_lock_is_in_sync_with_pyproject():
    if not uv_available():
        pytest.skip("uv is not installed (pip install uv)")
    proc = subprocess.run(
        [sys.executable, "-m", "uv", "lock", "--check", "--no-progress"],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600)
    assert proc.returncode == 0, (
        "uv.lock is stale - run `uv lock` and commit the result.  A stale "
        "lock makes `uv sync` resolve a different dev toolchain than the one "
        "tested here:\n" + proc.stdout + proc.stderr)


def test_the_lockfile_is_committed():
    """The gate above is meaningless if uv.lock is not tracked."""
    proc = subprocess.run(["git", "ls-files", "--error-unmatch", "uv.lock"],
                          cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, \
        "uv.lock is not tracked by git:\n" + proc.stdout + proc.stderr
