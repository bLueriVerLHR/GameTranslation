"""check_coverage.py - enforce per-area and per-module coverage floors.

Why this exists (PLAN.md Phase 5 task 4)
---------------------------------------
A single global coverage number hides exactly the modules that need attention:
a well-covered `translation` package can carry a 0%-covered binary decoder and
the total still looks healthy.  This gate therefore compares three granularities
against a recorded baseline:

* every coverage *area* (one directory under `[tool.coverage.run].source`);
* a curated list of high-risk *modules* (core primitives, binary format
  parsers, the translation gates);
* the total, only as a coarse backstop.

The baseline is recorded from a real measurement, never invented, and the rule is
**flat or rising**: a floor may be raised at any time, and lowering one is a
deliberate act that this tool refuses unless the module is moved to `waivers`
with a reason.  That is what makes "higher bars for core and format parsers"
mechanical instead of aspirational.

Usage
-----
    # Record / raise the baseline from a fresh measurement.
    python tools/check_coverage.py coverage.json --update

    # Gate (exit 1 on any regression).
    python tools/check_coverage.py coverage.json

`coverage.json` is produced by `python -m coverage json -o coverage.json`
(or `pytest --cov --cov-report=json:coverage.json`); the reader also accepts a
`pytest-cov` report, which has the same shape.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Annotated

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import typer  # noqa: E402

from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("check_coverage")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASELINE = os.path.join(REPO_ROOT, "tests", "coverage_floor.json")

SCHEMA_VERSION = 1

# Modules whose failure is not contained by a package-level average.  Two
# groups, and the reason each is here rather than left to the area floor:
#
#   core      - every engine depends on these; a regression is felt everywhere
#   format    - a binary parser bug corrupts output rather than raising
#   gates     - these enforce the contracts the project cannot silently lose
HIGH_RISK_GROUPS = {
    "core": (
        "rpgmaker/archive.py",
        "rpgmaker/assets.py",
        "rpgmaker/cliutil.py",
        "rpgmaker/deliver.py",
        "rpgmaker/deliverables.py",
        "rpgmaker/fontpolicy.py",
        "rpgmaker/inventory.py",
        "rpgmaker/japanese.py",
        "rpgmaker/jssyntax.py",
        "rpgmaker/logsetup.py",
        "rpgmaker/media.py",
        "rpgmaker/platform.py",
        "rpgmaker/plugins_io.py",
        "rpgmaker/proctools.py",
        "rpgmaker/runtime.py",
        "rpgmaker/settings.py",
        "rpgmaker/tool_registry.py",
        "rpgmaker/workspace.py",
    ),
    "format": (
        "kirikiri/tlg.py",
        "kirikiri/xp3pack.py",
        "kirikiri/xp3tool.py",
        "translation/rawlib.py",
        "tyrano/asar.py",
        "wolfrpg/dxarchive.py",
    ),
    "gates": (
        "translation/bake.py",
        "translation/codes.py",
        "translation/mvkeys.py",
    ),
}

HIGH_RISK = tuple(
    module for group in HIGH_RISK_GROUPS.values() for module in group)


def _normalise(path):
    return path.replace("\\", "/").lstrip("./")


def _percent(entry):
    """Combined line+branch percentage from a coverage.py/JSON summary."""
    summary = entry.get("summary") or {}
    covered = summary.get("covered_lines", 0) + summary.get("covered_branches", 0)
    total = summary.get("num_statements", 0) + summary.get("num_branches", 0)
    if not total:
        return 100.0
    return round(100.0 * covered / total, 1)


def _floor(value):
    """The recorded value, rounded down to one decimal.

    Down, not nearest: a floor must never sit above what was actually measured,
    or the gate would fail on the very commit that recorded it.
    """
    return int(value * 10) / 10.0


def measure(report):
    """Turn a coverage JSON report into {areas, modules, total} percentages."""
    files = report.get("files") or {}
    areas = {}
    modules = {}
    for path, entry in files.items():
        rel = _normalise(path)
        pct = _percent(entry)
        area = rel.split("/")[0]
        totals = areas.setdefault(area, [0, 0])
        summary = entry.get("summary") or {}
        totals[0] += (summary.get("covered_lines", 0)
                      + summary.get("covered_branches", 0))
        totals[1] += (summary.get("num_statements", 0)
                      + summary.get("num_branches", 0))
        modules[rel] = pct
    area_pct = {name: (round(100.0 * c / t, 1) if t else 100.0)
                for name, (c, t) in areas.items()}
    return {"areas": area_pct, "modules": modules,
            "total": _percent({"summary": (report.get("totals") or {})})}


def build_baseline(measured, command, waivers=None):
    missing = [m for m in HIGH_RISK if m not in measured["modules"]]
    if missing:
        # A high-risk module that produced no coverage data is not "covered":
        # it means the file was renamed or deleted, and the list must follow.
        raise SystemExit(
            "high-risk modules absent from the report: {}\n"
            "update HIGH_RISK_GROUPS (a renamed file must not silently leave "
            "the gate)".format(", ".join(missing)))
    return {
        "schema": SCHEMA_VERSION,
        "command": command,
        "areas": {name: _floor(pct)
                  for name, pct in sorted(measured["areas"].items())},
        "modules": {name: _floor(measured["modules"][name])
                    for name in HIGH_RISK},
        "total": _floor(measured["total"]),
        # A waiver is a recorded decision, not a measurement: regenerating the
        # baseline must not silently erase one.
        "waivers": dict(waivers or {}),
    }


def compare(baseline, measured):
    """(regressions, gains) as lists of human-readable lines.

    ``key`` is the bare name used to look up a ``waivers`` entry, so a
    regression can be waived by the thing that actually regressed (a module
    path, an area name, or ``total``).
    """
    regressions = []
    gains = []
    checks = [("total", "total", baseline.get("total"), measured["total"])]
    checks += [(f"area {name}", name, value,
                measured["areas"].get(name))
               for name, value in sorted(baseline.get("areas", {}).items())]
    checks += [(f"module {name}", name, value,
                measured["modules"].get(name))
               for name, value in sorted(baseline.get("modules", {}).items())]
    waivers = baseline.get("waivers") or {}
    for label, key, floor, actual in checks:
        if floor is None:
            continue
        if actual is None:
            regressions.append(
                f"{label}: no longer measured (was {floor:.1f}%); a renamed or deleted "
                "file must be reflected in the baseline")
            continue
        if actual < floor:
            if key in waivers:
                log.warning("waived: %s at %.1f%% < %.1f%% - %s",
                            label, actual, floor, waivers[key])
                continue
            regressions.append(
                f"{label}: {actual:.1f}% < floor {floor:.1f}% (drop {floor - actual:.1f})")
        elif actual > floor:
            gains.append(f"{label}: {actual:.1f}% > floor {floor:.1f}%")
    return regressions, gains


def unknown_areas(baseline, measured):
    """Areas present in the measurement but missing from the baseline.

    A new package must be recorded, otherwise adding code in a brand-new
    directory would be invisible to the gate.
    """
    return sorted(set(measured["areas"]) - set(baseline.get("areas", {})))


def render(baseline, measured):
    lines = []
    lines.append("coverage floors (flat or rising)")
    for label, floor, actual in (
            [("total", baseline.get("total"), measured["total"])]
            + [(f"area {n}", v, measured["areas"].get(n))
               for n, v in sorted(baseline.get("areas", {}).items())]
            + [(f"module {n}", v, measured["modules"].get(n))
               for n, v in sorted(baseline.get("modules", {}).items())]):
        if floor is None or actual is None:
            continue
        delta = actual - floor
        lines.append("  %-34s %6.1f%%  (floor %5.1f, %+.1f)"
                     % (label, actual, floor, delta))
    return "\n".join(lines)


def _load(path):
    """Read a JSON document, tolerating a UTF-8 BOM.

    The baseline is meant to be hand-edited (a `waivers` entry is a deliberate
    act), and editing it on Windows is the normal case - an editor that writes
    a BOM must not make the gate fail with `JSONDecodeError: Unexpected UTF-8
    BOM`, which reads like a corrupt baseline rather than an encoding detail.
    `utf-8-sig` strips the BOM when present and is a no-op otherwise.
    """
    with open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def cmd(
    report: Annotated[str, typer.Argument(
        help="coverage JSON report (coverage json / --cov-report=json)")],
    baseline: Annotated[str, typer.Option(
        "--baseline", help="recorded floors")] = DEFAULT_BASELINE,
    update: Annotated[bool, typer.Option(
        "--update", help="record the measured values as the new floors")] = False,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Enforce per-area and per-module coverage floors against the baseline."""
    measured = measure(_load(report))
    recorded = _load(baseline) if os.path.exists(baseline) else None

    if update:
        previous = recorded or {}
        candidate = build_baseline(
            measured,
            "python -m pytest tests -q -n 0 --cov --cov-branch "
            "--cov-report=json:coverage.json",
            waivers=previous.get("waivers"))
        # Raising a floor is the point; nothing else may move silently.  Each
        # entry carries the bare key so a waiver can be looked up by the thing
        # that actually regressed (module path, area name, or `total`).
        lowered = [
            (f"{name}", f"{kind} {name}: {previous[kind][name]:.1f} -> {value:.1f}")
            for kind in ("areas", "modules")
            for name, value in candidate[kind].items()
            if previous.get(kind, {}).get(name) is not None
            and value < previous[kind][name]
        ]
        if previous.get("total") is not None \
                and candidate["total"] < previous["total"]:
            lowered.append(("total", "total: {:.1f} -> {:.1f}".format(previous["total"], candidate["total"])))
        if lowered:
            # Allow it only when a waiver documents why, so the drop is a
            # recorded decision rather than an accident of regenerating.
            waivers = candidate.get("waivers") or {}
            unexplained = [line for key, line in lowered if key not in waivers]
            if unexplained:
                log.error("refusing to lower these floors without a waiver:\n%s",
                          "\n".join("  " + line for line in unexplained))
                log.error("add the module to `waivers` with a reason, or the "
                          "loss is a regression to fix")
                return cliutil.fail("coverage floors would drop")
        with open(baseline, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(candidate, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        log.info("recorded %d area floors, %d module floors (total %.1f%%)",
                 len(candidate["areas"]), len(candidate["modules"]),
                 candidate["total"])
        return 0

    if recorded is None:
        log.error("no baseline at %s - run with --update once to record it",
                  baseline)
        return cliutil.fail("coverage baseline missing")

    problems = []
    new_areas = unknown_areas(recorded, measured)
    if new_areas:
        problems.append(
            "unrecorded coverage areas: {} (add them to the baseline with "
            "--update)".format(", ".join(new_areas)))
    regressions, gains = compare(recorded, measured)
    problems += regressions

    print(render(recorded, measured))
    for line in gains:
        log.debug("gain: %s", line)
    if problems:
        for line in problems:
            log.error("%s", line)
        return cliutil.fail("%d coverage regression(s)" % len(problems))
    log.info("coverage floors hold (%d areas, %d modules)",
             len(recorded["areas"]), len(recorded["modules"]))
    return 0


def main(argv=None) -> int:
    return cliutil.run(app, argv)


app = cliutil.command_app(cmd)


if __name__ == "__main__":
    sys.exit(main())
