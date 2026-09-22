"""Type-check the repo with the mypy configuration, in two tiers.

Phase 6 task 2 (PLAN.md).  The plan forbids maintaining mypy *and* pyright at
the same time, so mypy is the one checker; this module is the gate around it.

Why a wrapper instead of a bare ``mypy`` invocation:

1. **Two tiers are needed.**  ~1163 functions in this repo have no annotation,
   so demanding all of them in one commit would be unreviewable.  Instead the
   whole tree is checked with ``check_untyped_defs`` (bodies are still
   analysed) and the outstanding error *count* is budgeted in
   ``[tool.gametranslation.mypy-burndown]``.  On top of that,
   ``[tool.gametranslation.mypy-strict]`` lists modules held at **zero**
   errors, so a module that has been cleaned cannot silently regress while the
   global budget absorbs the slack.  A budget without a floor is how debt grows
   back.

2. **mypy's failure modes are indistinguishable from success.**  It can abort
   on a config or dependency problem and still print a non-zero exit, so a bare
   ``mypy`` in a gate can report "the tree is broken" when the real problem is
   that nothing was checked at all.  This wrapper distinguishes "mypy could not
   run" (exit 2, reported as an UNKNOWN status) from "mypy ran and found
   errors".

3. **The count is the metric.**  A gate that only fails on the *first* error
   cannot be burndown-managed; parsing the count is what lets the budget fall
   monotonically.

The ``no_site_packages`` setting in ``[tool.mypy]`` is load-bearing for the
same reason: this repo targets 3.10 while the dev venv runs 3.12, and numpy's
bundled stub uses ``type`` statements (3.12-only syntax).  Following it into
site-packages made mypy abort with ``Type statement is only supported in Python
3.12 and greater`` - checking nothing, exit non-zero.  Third-party packages are
typed ``Any`` here on purpose.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Annotated

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import typer  # noqa: E402

from rpgmaker import cliutil, proctools  # noqa: E402

# Every package a documented entry point imports.  The same list the other
# gates compile, so a module cannot be "checked" by one and skipped by another.
TARGETS = ("rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity", "translation",
           "tools")

# `path:line: error: message  [code]` - the code is optional (mypy omits it for
# some notes) which is why the group is not anchored at the end.
_ERROR = re.compile(r"^(?P<path>[^:]+):\d+: (?P<kind>error|warning):")

# mypy exit codes: 0 clean, 1 errors found, 2 "could not run" (bad config, bad
# invocation, internal error).  The distinction matters: 2 means the gate
# measured nothing, and reporting that as a normal failure would hide a broken
# gate behind a routine "there is debt" message.
COULD_NOT_RUN = 2

UNKNOWN = "UNKNOWN"


def parse_errors(output: str) -> int:
    """Count ``error:`` lines that belong to this repo.

    Two filters matter:

    * ``error:`` appearing inside a *message* (a test fixture, a docstring
      quoting a failure) must not count, so only lines whose prefix really is
      ``path:line:`` are matched.
    * Errors attributed to files outside the targets are dropped.  With
      ``no_site_packages`` there should be none; if one appears it means the
      configuration regressed, and silently counting it would inflate the
      budget with something no contributor can fix.
    """
    count = 0
    for line in (output or "").splitlines():
        match = _ERROR.match(line.strip())
        if not match or match.group("kind") != "error":
            continue
        path = match.group("path").replace("\\", "/")
        if path.split("/")[0] in TARGETS:
            count += 1
    return count


def run_mypy(targets=TARGETS, extra=()) -> tuple[int, int, str]:
    """Run mypy once and return ``(exit_code, error_count, output)``."""
    argv = [sys.executable, "-m", "mypy", *extra, *targets]
    try:
        proc = proctools.run(argv, cwd=_ROOT, check=False)
    except Exception as exc:                       # noqa: BLE001 - reported
        return COULD_NOT_RUN, 0, f"could not start mypy: {exc}"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, parse_errors(output), output


def strict_list() -> tuple[str, ...]:
    """The modules held at zero errors, from pyproject (single source)."""
    return tuple(_config()["tool"]["gametranslation"]["mypy-strict"]["modules"])


def error_budget() -> int:
    """The recorded error budget, from pyproject (single source)."""
    return int(_config()["tool"]["gametranslation"]["mypy-burndown"]["errors"])


def _config() -> dict:
    try:
        import tomllib  # 3.11+
    except ImportError:  # pragma: no cover - exercised on 3.10 ci
        import tomli as tomllib
    with open(os.path.join(_ROOT, "pyproject.toml"), "rb") as handle:
        return tomllib.load(handle)


def check_strict(modules=None) -> list[str]:
    """Return one line per strict-tier module that is not clean.

    Missing files are reported too: a listed module that no longer exists would
    otherwise shrink the guarded surface without anyone noticing.
    """
    modules = strict_list() if modules is None else modules
    missing = [m for m in modules if not os.path.isfile(os.path.join(_ROOT, m))]
    present = [m for m in modules if m not in missing]
    problems = [f"{m}: listed in the strict tier but the file does not exist"
                for m in missing]
    if present:
        code, _, output = run_mypy(tuple(present))
        if code == COULD_NOT_RUN:
            problems.append("mypy could not run: "
                            + output.strip()[-proctools.OUTPUT_TAIL:])
        else:
            errors = [line.strip() for line in output.splitlines()
                      if _ERROR.match(line.strip())
                      and ": error:" in line]
            problems.extend(errors)
    return problems


def cmd(as_json: Annotated[bool, typer.Option(
            "--json", help="machine-readable structured output")] = False,
        update: Annotated[bool, typer.Option(
            "--update",
            help="lower the recorded budget to the measured count "
                 "(never raises it)")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Check the mypy budgets: the whole-tree count must not rise and every
    module in the strict tier must stay at zero errors.

    Use ``--update`` to re-record a *lower* count after annotating code; it
    refuses to raise the budget, because that is how a burndown turns into a
    waiver list.
    """
    import json
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("type-check the repository", repo=_ROOT)

    code, count, output = run_mypy()
    budget = error_budget()
    if code == COULD_NOT_RUN:
        proctools_tail = output.strip()[-proctools.OUTPUT_TAIL:]
        return cliutil.fail(
            "mypy could not run, so nothing was measured (this is not a "
            "normal 'errors found' failure): " + proctools_tail)

    if update:
        if count > budget:
            return cliutil.fail(
                f"refusing to raise the error budget from {budget} to {count}:"
                " annotate the code instead, or lower the number")
        if count < budget:
            _write_budget(count)
        return 0

    strict = check_strict()
    ok = count <= budget and not strict
    report = {
        "errors": count,
        "budget": budget,
        "strict_modules": len(strict_list()),
        "strict_problems": strict,
        "ok": ok,
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _render(report)
    if not ok:
        return 1
    return 0


def _write_budget(count: int) -> None:
    """Lower the recorded budget in pyproject.toml, preserving comments.

    A regex edit rather than a TOML round-trip precisely because the file is
    mostly explanatory comment; re-serialising it would delete the reasoning
    that makes the numbers auditable.
    """
    path = os.path.join(_ROOT, "pyproject.toml")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    pattern = re.compile(r"(?m)^(\s*errors\s*=\s*)\d+\s*$")
    new_text, replaced = pattern.subn(rf"\g<1>{count}", text)
    if replaced != 1:
        raise SystemExit(
            f"expected exactly one `errors = N` line under mypy-burndown, "
            f"found {replaced}; fix pyproject.toml by hand")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(new_text)


def _render(report: dict) -> None:
    print(f"mypy: {report['errors']} error(s), budget {report['budget']}")
    for problem in report["strict_problems"]:
        print("  strict: " + problem)
    if report["ok"]:
        print("mypy budgets hold (no rise, strict tier clean)")
    else:
        print("mypy budgets exceeded")


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="mypy_check.py")


if __name__ == "__main__":
    raise SystemExit(main())
