#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kana-residual QC for KiriKiri and TyranoScript scenario translations.

Scans a scenario tree for translatable lines whose display text still
carries kana after translation (missed lines, half-translated lines) and
reports file:line locations.  Also checks a translated.json for kana in
values.

Only display text is checked: `*` label lines, `;` comments, raw TJS/JS
code blocks and variable references (`&f.name`) are excluded, because
TyranoScript legally uses Japanese identifiers and counting those as
"residual" buries the real misses (measured: ~92% of raw kana hits on a
fully translated build were identifiers and code).

Usage:
    python3 tools/qc_ks_kana.py <scenario_dir|patch_dir>
    python3 tools/qc_ks_kana.py --values <translated.json>
"""

import glob
import json
import logging
import os
import sys
from typing import Annotated, Optional


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kirikiri.ks_extract import (KANA, display_text, iter_display_lines,  # noqa: E402
                                load_ks, translatable)

from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("qc_ks_kana")


def scan_tree(root):
    """Count translatable lines whose display text still carries kana.

    Uses `iter_display_lines` so code, comments and label lines are not
    counted (and variable references are stripped): a kana hit here means a
    real, untranslated piece of display text.
    """
    total = residual = 0
    by_file = {}
    for path in sorted(glob.glob(os.path.join(root, "**", "*.ks"),
                                 recursive=True)):
        text, _enc = load_ks(path)
        for idx, line in iter_display_lines(text):
            stripped = line.strip()
            if not translatable(stripped):
                continue
            total += 1
            shown, _ok = display_text(stripped)
            if KANA.search(shown):
                residual += 1
                by_file.setdefault(path, []).append((idx, shown[:60]))
    for path, hits in by_file.items():
        log.warning("%s: %d residual line(s)", path, len(hits))
        for idx, shown in hits[:5]:
            log.warning("  %s:%d  %s", path, idx, shown)
    return total, residual


def scan_values(translated_path):
    with open(translated_path, encoding="utf-8-sig") as f:
        trans = json.load(f)
    residual = 0
    for key, value in trans.items():
        if KANA.search(value):
            residual += 1
            log.warning("%s: kana in value -> %s", key, value[:60])
    return len(trans), residual


def cmd(values: Annotated[Optional[str], cliutil.Option(
            "--values", metavar="translated.json",
            help="check a dictionary's values instead of a tree")] = None,
        target: Annotated[Optional[str], cliutil.Argument(
            help="scenario/patch directory")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Report kana left in a scenario tree (or in a dictionary's values)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    if values:
        total, residual = scan_values(values)
        log.info("values: %d entries, %d with kana", total, residual)
        return 0
    if not target:
        return cliutil.fail("need a directory or --values")
    total, residual = scan_tree(target)
    log.info("%d translatable lines, %d kana residual (%.1f%%)",
             total, residual, 100.0 * residual / total if total else 0.0)
    if residual:
        log.info("residuals are real display text - check each one before "
                 "translating: a hit inside target=\"*...\" would break a "
                 "jump, and identifiers are never translated")
    return 0


# --help prints the tool's full documentation: a single-command Typer app
# shows the COMMAND docstring, so the module docstring is attached to it
# (the argparse version printed the same text as its description).
cmd.__doc__ = __doc__
app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="qc_ks_kana.py")


if __name__ == "__main__":
    raise SystemExit(main())
