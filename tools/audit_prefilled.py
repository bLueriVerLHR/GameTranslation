#!/usr/bin/env python3
"""audit_prefilled.py - Audit an MTool-exact-hit prefilled file BEFORE merging:
flag values that still contain kana lines (multi-line block keys where one
line missed the dict), so leftover lines are hand-translated early instead of
polluting the bake.

Consolidated from the long-run session audit_prefilled.py (docs/translation.md).

Usage:
    python -m tools.audit_prefilled <prefilled.json> [--out <fixed.json>]
"""
import json
from typing import Annotated

from rpgmaker import cliutil
from rpgmaker import japanese as japanese_utils

KANA = japanese_utils.KANA


def cmd(prefilled: Annotated[str, cliutil.Argument(
            help="prefilled MTool-exact-hit JSON to audit")],
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    p = json.load(open(prefilled, encoding="utf-8"))
    residual = []
    for k, v in p.items():
        kl = k.split("\n")
        vl = v.split("\n")
        if len(vl) != len(kl):
            residual.append((k, v, "line-count mismatch"))
            continue
        for i, (kk, vv) in enumerate(zip(kl, vl, strict=True)):
            if KANA.search(vv) and not KANA.search(kk):
                residual.append((k, v, "line %d: %s" % (i, vv[:40])))
                break

    print("values with residual kana / mismatched lines: %d / %d"
          % (len(residual), len(p)))
    for k, v, why in residual[:20]:
        print("  K:", repr(k)[:70])
        print("  V:", repr(v)[:70], "|", why)
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="audit_prefilled.py")


if __name__ == "__main__":
    raise SystemExit(main())
