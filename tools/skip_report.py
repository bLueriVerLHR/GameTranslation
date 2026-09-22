#!/usr/bin/env python3
"""Print why every test skip happens, and fail on an unexplained one.

PLAN Phase 5 task 9 (skip budget).  `tests/test_test_layers.py` already fails
the build when a *new* skip site appears (`SKIP_BUDGET`) and when a reason
names no known layer, but a green suite still hides the shape of the hole:
"2 skipped" tells the reader nothing about WHAT is missing, so a skip can grow
from a legitimate capability gap into a permanently dark code path without
anyone noticing.  This tool prints the inventory, and exits non-zero when a
site cannot be attributed - so CI has to answer the question every run.

Reasons are classified exactly the way the gate does, by importing the gate
itself: a second copy of the tables would be the thing that drifts.

Exit codes: 0 = every skip attributed; 1 = at least one is not.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import typer  # noqa: E402

from rpgmaker import cliutil  # noqa: E402

# The gate owns the tables and the AST scanner; importing it keeps one
# definition.  It needs `tests/` importable, exactly as pytest has it.
_TESTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tests")
sys.path.insert(0, _TESTS)

import test_test_layers as layers  # noqa: E402

#: A skip that names a capability gets the layer that supplies it; these are
#: the honest non-layer classifications (see the gate's GUARD_SKIP_REASONS).
GUARD = "guard"
UNKNOWN = "unknown"


def classify(reason, arg, name):
    """Return (bucket, detail) for one skip site.

    `bucket` is a marker name, ``GUARD`` for a documented environment guard, or
    ``UNKNOWN`` when nothing explains it.  The gate is the authority on what may
    be called a guard; this only reports.
    """
    if name == "importorskip":
        pkg = arg.strip("'\"")
        if pkg in layers.OPTIONAL_IMPORTS:
            return "optional-import", pkg
        return UNKNOWN, pkg
    text = layers._reason_text(reason)
    if any(pattern in text for pattern, _why in layers.GUARD_SKIP_REASONS):
        return GUARD, text
    needed = set()
    for marker, needles in layers.SKIP_REASON_LAYERS.items():
        if any(needle in text for needle in needles):
            needed.add(marker)
    if len(needed) == 1:
        return next(iter(needed)), text
    if not needed:
        return UNKNOWN, text
    return "+".join(sorted(needed)), text


def collect():
    """[(rel, lineno, name, arg, bucket, detail)] for every skip site."""
    rows = []
    for rel in layers._test_files():
        tree = layers.ast.parse(layers._parse(rel))
        for lineno, name, reason, arg in layers._skip_sites(tree):
            bucket, detail = classify(reason, arg, name)
            rows.append((rel, lineno, name, arg, bucket, detail))
    return rows


def cmd(as_json: bool = typer.Option(False, "--json",
                                     help="machine-readable output"),
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None):
    """Report the skip inventory; non-zero when a skip is unexplained."""
    cliutil.setup_logging(verbose=verbose, quiet=quiet, log_file=log_file)
    rows = collect()
    counts = collections.Counter(row[4] for row in rows)
    unknown = [row for row in rows if row[4] == UNKNOWN]

    if as_json:
        import json
        print(json.dumps({
            "total": len(rows),
            "budget": layers.SKIP_BUDGET,
            "by_capability": dict(sorted(counts.items())),
            "unknown": [{"file": r[0], "line": r[1], "call": r[2],
                         "reason": r[5]} for r in unknown],
            "sites": [{"file": r[0], "line": r[1], "call": r[2],
                       "capability": r[4], "reason": r[5]} for r in rows],
        }, ensure_ascii=False, indent=1))
        return 1 if unknown else 0

    print("skip inventory: %d site(s), budget %d" % (len(rows),
                                                     layers.SKIP_BUDGET))
    for bucket, count in sorted(counts.items(), key=lambda kv: (-kv[1],
                                                               kv[0])):
        print("  %-16s %2d" % (bucket, count))
    if verbose:
        print()
        for rel, lineno, name, _arg, bucket, detail in rows:
            print("  %-16s %s:%d  %s(%s)" % (bucket, rel, lineno, name,
                                             detail[:70]))
    if unknown:
        print("\nunexplained skip(s):")
        for rel, lineno, _name, _arg, _bucket, detail in unknown:
            print("  %s:%d  %r" % (rel, lineno, detail))
        print("\neither name the capability in the reason, or add it to "
              "SKIP_REASON_LAYERS / GUARD_SKIP_REASONS in "
              "tests/test_test_layers.py")
        return 1
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
