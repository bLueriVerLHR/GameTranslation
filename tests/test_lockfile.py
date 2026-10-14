#!/usr/bin/env python3
"""Lockfile gate: `uv.lock` must match `pyproject.toml`.

`uv.lock` is committed (PLAN Phase 1) so that a clean environment resolves the
same dependency set the tests were verified against.  Nothing enforced that
until this test: the lock was verified green in Phase 1, then Phase 4 added
`hypothesis>=6` to `[project.optional-dependencies].dev` and the lock silently
went stale. CI now consumes that lock for regression jobs, and the contract
below rejects floating installs and mismatched Python baselines.

Skipped when `uv` is not installed (`pip install uv`), matching the ruff gate in
`tests/test_lint.py`: a plain runtime install can still run the suite.
"""
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

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


def _assert_locked_install(job):
    """Reject a floating install even if a comment mentions the lock."""
    runs = [step["run"] for step in job["steps"] if "run" in step]
    syncs = [text for text in runs if "uv sync" in text]
    assert len(syncs) == 1, "each regression job must consume uv.lock once"
    sync = syncs[0]
    assert "--locked" in sync
    assert "--python 3.14" in sync
    for extra in ("images", "fonts", "dev"):
        assert f"--extra {extra}" in sync
    assert not any('pip install -e' in text for text in runs)
    checks = [text for text in runs if "python -m pytest" in text]
    for text in checks:
        assert "uv run --no-sync python" in text


def test_regression_jobs_install_and_run_locked_dependencies():
    workflow = yaml.safe_load(Path(REPO_ROOT, ".github/workflows/ci.yml")
                              .read_text(encoding="utf-8"))
    for name in ("test", "coverage", "audit", "nightly"):
        _assert_locked_install(workflow["jobs"][name])


@pytest.mark.parametrize("install", [
    'python -m pip install -e ".[images,fonts,dev]"',
    "uv sync --python 3.14 --extra images --extra fonts --extra dev",
    "uv sync --locked --python 3.12 --extra images --extra fonts --extra dev",
    "uv sync --locked --python 3.14 --extra images --extra dev",
])
def test_locked_install_contract_rejects_drift(install):
    with pytest.raises(AssertionError):
        _assert_locked_install({"steps": [{"run": install}]})


def test_locked_install_contract_rejects_a_resyncing_test_command():
    with pytest.raises(AssertionError):
        _assert_locked_install({"steps": [
            {"run": "uv sync --locked --python 3.14 --extra images --extra fonts --extra dev"},
            {"run": "uv run python -m pytest tests"},
        ]})


def test_python_baseline_is_shared_by_packaging_lint_types_and_ci():
    root = Path(REPO_ROOT)
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["requires-python"] == ">=3.14"
    assert config["tool"]["ruff"]["target-version"] == "py314"
    assert config["tool"]["mypy"]["python_version"] == "3.14"
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml")
                              .read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert jobs["test"]["strategy"]["matrix"]["python"] == ["3.14"]
    for job in jobs.values():
        setup = [step for step in job["steps"]
                 if step.get("uses", "").startswith("actions/setup-python@")]
        assert len(setup) == 1
        version = setup[0]["with"]["python-version"]
        assert version in ("3.14", "${{ matrix.python }}")
