#!/usr/bin/env python3
"""check_all.py - run every local gate in one command.

Why this exists (PLAN.md Phase 6 task 7)
----------------------------------------
The pre-merge checklist is written down in three places (``AGENTS.md``,
``docs/CONTRIBUTING.md``, ``README.md``) and executed by hand.  Two things go
wrong with a hand-run checklist, and both were observed in this repo:

* **a gate is forgotten.**  A commit that added a package-data file did not
  re-run the wheel test; a commit that changed ``pyproject.toml`` did not
  re-run ``uv lock``, and the next clean-environment run failed on a stale
  lockfile.  Neither was caught locally.
* **a gate silently degrades.**  A gate that needs a tool the machine does not
  have (``ruff``, ``uv``) is easy to skip "just this once" and then never
  noticed again.  This tool prints ``SKIP`` *with the missing dependency named*
  and fails when a **mandatory** gate cannot run - never a silent pass.

It is deliberately a thin runner, not a re-implementation: every gate shells
out to the exact command the documentation names, so there is one definition of
each check and the tool cannot pass while the documented command fails.

    python tools/check_all.py                 # the five mandatory gates
    python tools/check_all.py --coverage      # + serial coverage + floor gate
    python tools/check_all.py --fast          # skip the full test suite
    python tools/check_all.py --only lint --only docs
    python tools/check_all.py --list

CI remains the final authority: the runner proves a change is ready to push,
not that the remote matrix passed.  Nothing here replaces
``tests/test_repo_hygiene.py``'s scan or the coverage floors - those are gates
among the others.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Annotated

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import typer  # noqa: E402

from rpgmaker import cliutil, proctools  # noqa: E402

log = logging.getLogger("check_all")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Compile targets, in the order AGENTS.md lists them.
PACKAGES = ("rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity", "translation",
            "tools", "tests")

#: Where the coverage gate writes its report.  Under `.tmp` (gitignored) for
#: the same reason every other scratch artifact lives there.
COVERAGE_REPORT = os.path.join(".tmp", "coverage.json")

#: Per-gate subprocess timeout.  The full suite is the long one; a gate that
#: exceeds its budget is a failed gate, not a hang the operator waits out.
TIMEOUTS = {"tests": 3600, "coverage": 5400}


@dataclass(frozen=True)
class Gate:
    """One local gate: a documented command plus what it needs to run.

    ``needs`` names importable modules; a gate whose dependencies are missing
    is reported as a skip that *names* the dependency.  ``required`` is the
    AGENTS.md mandatory list - a skip there is a failure, because "I could not
    run the gate" must never read the same as "the gate passed".
    """

    name: str
    summary: str
    argv: Callable[[str], list]
    required: bool = True
    needs: tuple = ()
    #: Gates that only make sense with `--coverage`.
    coverage_only: bool = False


def _report(root: str) -> str:
    return os.path.join(root, COVERAGE_REPORT)


GATES: tuple = (
    Gate(
        "hygiene",
        "public-repo hygiene (no machine paths, usernames, secrets)",
        lambda root: [sys.executable, "-m", "pytest",
                      os.path.join("tests", "test_repo_hygiene.py"),
                      "-q", "-n", "0"],
    ),
    Gate(
        "compile",
        "every package still compiles",
        lambda root: [sys.executable, "-m", "compileall", "-q", *PACKAGES],
    ),
    Gate(
        "lint",
        "ruff, rules pinned in pyproject.toml",
        lambda root: [sys.executable, "-m", "ruff", "check", "."],
        needs=("ruff",),
    ),
    Gate(
        "docs",
        "docs tree matches the repo + documentation gates",
        lambda root: [sys.executable, os.path.join("tools", "check_docs.py")],
    ),
    Gate(
        "tests",
        "the whole unit + integration suite",
        lambda root: [sys.executable, "-m", "pytest", "tests", "-q"],
    ),
    Gate(
        "coverage",
        "serial coverage measurement piped into the recorded floors",
        lambda root: [sys.executable, "-m", "pytest", "tests", "-q", "-n", "0",
                      "-p", "no:randomly",
                      "--cov", "--cov-branch",
                      f"--cov-report=json:{_report(root)}"],
        needs=("coverage",),
        coverage_only=True,
    ),
    Gate(
        "floors",
        "coverage floors hold (tools/check_coverage.py)",
        lambda root: [sys.executable, os.path.join("tools", "check_coverage.py"),
                      _report(root)],
        coverage_only=True,
    ),
    Gate(
        "types",
        "mypy budgets: error count flat or falling, strict modules at zero",
        lambda root: [sys.executable, os.path.join("tools", "mypy_check.py")],
        needs=("mypy",),
    ),
    Gate(
        "lock",
        "uv lock is in sync with pyproject.toml",
        lambda root: [sys.executable, "-m", "uv", "lock", "--check",
                      "--no-progress"],
        required=False,
        needs=("uv",),
    ),
    Gate(
        "skips",
        "every test skip is attributed to a capability",
        lambda root: [sys.executable, os.path.join("tools", "skip_report.py"),
                      "--verbose"],
    ),
)

BY_NAME = {gate.name: gate for gate in GATES}

#: `--coverage` replaces the plain suite with the measuring pair: running the
#: suite twice would double the wall clock for the same evidence.
COVERAGE_REPLACES = ("tests",)


@dataclass
class Outcome:
    gate: Gate
    status: str          # ok | failed | skipped
    seconds: float = 0.0
    detail: str = ""
    output: str = field(default="", repr=False)


def _missing(gate: Gate) -> list:
    """Dependencies of `gate` this interpreter cannot provide."""
    return [name for name in gate.needs
            if importlib.util.find_spec(name) is None]


def _tail(text: str, limit: int = 4000) -> str:
    text = (text or "").strip()
    return text[-limit:]


def _run_one(gate: Gate, root: str) -> Outcome:
    argv = gate.argv(root)
    log.debug("gate %s: %s", gate.name, proctools.argv_text(argv))
    started = time.perf_counter()
    try:
        proc = proctools.run(argv, cwd=root, check=False,
                             timeout=TIMEOUTS.get(gate.name))
    except Exception as exc:            # noqa: BLE001 - any failure is a result
        return Outcome(gate, "failed", time.perf_counter() - started,
                       detail=f"{type(exc).__name__}: {exc}")
    elapsed = time.perf_counter() - started
    if proc.returncode == 0:
        return Outcome(gate, "ok", elapsed)
    return Outcome(gate, "failed", elapsed,
                   detail=f"exit {proc.returncode}",
                   output=_tail(proc.stdout + "\n" + proc.stderr))


def run_gates(gates: Sequence, root: str) -> list:
    """Run `gates` in order, stopping early on a failed mandatory gate.

    Stopping matters: running the 60-second suite when lint already failed
    wastes the operator's time, and the first failure is usually the cause of
    the rest.  A failed *optional* gate does not stop the run (a stale lockfile
    should not hide a test failure).
    """
    outcomes = []
    for gate in gates:
        absent = _missing(gate)
        if absent:
            # Name what is missing - a bare SKIP is how a gate rots.
            outcomes.append(Outcome(
                gate, "skipped", detail="missing: " + ", ".join(absent)))
            if gate.required:
                log.error("mandatory gate %r cannot run: %s is not installed "
                          "in this interpreter (%s)", gate.name,
                          ", ".join(absent), sys.executable)
                break
            log.warning("skipping optional gate %r: %s is not installed",
                        gate.name, ", ".join(absent))
            continue
        print(f"==> {gate.name}: {gate.summary}")
        outcome = _run_one(gate, root)
        outcomes.append(outcome)
        log.info("%s %s (%.1fs)", gate.name,
                 "passed" if outcome.status == "ok" else outcome.status,
                 outcome.seconds)
        if outcome.status == "failed":
            if outcome.output:
                print(outcome.output, file=sys.stderr)
            if gate.required:
                break
    return outcomes


def _select(only: Iterable, skip: Iterable, fast: bool,
            coverage: bool) -> list:
    """The gate list for this invocation, or ValueError when it is empty."""
    selected = list(GATES)
    if coverage:
        selected = [g for g in selected if g.name not in COVERAGE_REPLACES]
    else:
        selected = [g for g in selected if not g.coverage_only]
    if fast:
        selected = [g for g in selected
                    if g.name not in ("tests", "coverage", "floors")]
    only = set(only)
    unknown = only - set(BY_NAME)
    if unknown:
        raise ValueError("unknown gate(s): " + ", ".join(sorted(unknown)))
    if only:
        selected = [g for g in selected if g.name in only]
    skip = set(skip)
    unknown = skip - set(BY_NAME)
    if unknown:
        raise ValueError("unknown gate(s): " + ", ".join(sorted(unknown)))
    return [g for g in selected if g.name not in skip]


def _render(outcomes: Sequence) -> str:
    """One aligned table; the slowest gate is the interesting column."""
    width = max((len(o.gate.name) for o in outcomes), default=4)
    indent = " " * (width + 11)
    lines = ["", f"{'gate':<{width}}  {'result':<7}  {'time':>7}  what it checks"]
    for outcome in outcomes:
        took = "-" if outcome.status == "skipped" else f"{outcome.seconds:.1f}s"
        lines.append(f"{outcome.gate.name:<{width}}  {outcome.status.upper():<7}  "
                     f"{took:>7}  {outcome.gate.summary}")
        if outcome.detail:
            lines.append(f"{indent}{outcome.detail}")
    return "\n".join(lines)


def cmd(repo: Annotated[str, typer.Option(
        "--repo", metavar="DIR", help="checkout to test (default: this one)")]
        = REPO_ROOT,
        only: Annotated[list[str], typer.Option(
            "--only", metavar="NAME",
            help="run just these gates (repeatable)")] = None,
        skip: Annotated[list[str], typer.Option(
            "--skip", metavar="NAME",
            help="skip these gates (repeatable)")] = None,
        fast: Annotated[bool, typer.Option(
            "--fast", help="skip the full test suite (lint/docs/hygiene only)")]
        = False,
        coverage: Annotated[bool, typer.Option(
            "--coverage",
            help="measure coverage serially and enforce the recorded floors")]
        = False,
        list_: Annotated[bool, typer.Option(
            "--list", help="print the gate table and exit")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Run every local gate in one command; non-zero when any required one fails."""
    cliutil.setup_logging(verbose, quiet, log_file)
    root = os.path.abspath(repo)
    # Single gate for the one path this command touches: `--repo` is read (and
    # each gate writes its artifacts) under it.  CRITICAL cross-system rule.
    cliutil.own_paths("run the local gates", repo=root)

    if list_:
        width = max(len(gate.name) for gate in GATES)
        for gate in GATES:
            flags = []
            if not gate.required:
                flags.append("optional")
            if gate.coverage_only:
                flags.append("--coverage")
            print(f"{gate.name:<{width}}  {','.join(flags):<16} {gate.summary}")
        return 0

    if not os.path.isdir(root):
        return cliutil.fail(f"not a directory: {root}")
    try:
        selected = _select(only or (), skip or (), fast, coverage)
    except ValueError as exc:
        return cliutil.fail(str(exc))
    if not selected:
        return cliutil.fail("no gates selected")

    started = time.perf_counter()
    outcomes = run_gates(selected, root)
    print(_render(outcomes))

    failed = [o for o in outcomes if o.status == "failed"]
    skipped = [o for o in outcomes if o.status == "skipped"]
    # A skipped *mandatory* gate is a failure to check, not a pass: "I could
    # not run the check" must never read the same as "the check passed".  An
    # optional gate (a missing `uv`, say) only warns.
    blocking = [o for o in failed + skipped if o.gate.required]
    ran = [o for o in outcomes if o.status == "ok"]
    total = time.perf_counter() - started
    # "check" is one entry in the table; "ran" is the subset that actually
    # executed, so a table with skips cannot read as a full run.
    print(f"\n{len(outcomes)} gate(s) checked, {len(ran)} ran, "
          f"{len(failed)} failed, {len(skipped)} skipped in {total:.1f}s")
    for outcome in failed + skipped:
        if not outcome.gate.required:
            log.warning("optional gate %s: %s %s", outcome.gate.name,
                        outcome.status, outcome.detail)
    if blocking:
        log.error("gate(s) not satisfied: %s",
                  ", ".join(o.gate.name for o in blocking))
        print("\nCI is still the final authority: a green run here means the "
              "change is ready to push, not that the remote matrix passed.",
              file=sys.stderr)
        return 1
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="check_all.py")


if __name__ == "__main__":
    raise SystemExit(main())
