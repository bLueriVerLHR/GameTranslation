#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inject a translated.json ({ja: zh}) dictionary into the extracted
TyranoScript scenario tree.

Whole-line replacement: for every structure item (scenario file, line
number) the stripped original line is looked up in translated.json; on a
hit the line is rewritten in place - original indentation, line ending and
file encoding are preserved.  Keys missing from the dictionary stay
untouched and are counted (run qc_ks_kana.py afterwards to locate them).

Usage:
    python3 tools/apply_tyrano_translation.py <work_dir> \
        [--scenario-dir DIR] [--out DIR]
"""

import logging
import os
import sys
from typing import Annotated, Optional

import typer

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root: rpgmaker/, tyrano/
sys.path.insert(0, _HERE)                   # sibling tools: plain_io
import plain_io  # noqa: E402
from tyrano.tyrano_extract import load_ks  # noqa: E402

from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("apply_tyrano_translation")


def patch_line(line, trans):
    """Rewrite one line: keep indentation and line ending, replace the
    stripped middle when it is a dictionary key."""
    left = len(line) - len(line.lstrip())
    right = len(line.rstrip())
    key = line[left:right]
    if key not in trans:
        return None
    return line[:left] + trans[key] + line[right:]


def patch_file(src_path, out_path, items, trans, stats):
    """Rewrite one .ks file; returns (replaced, missing)."""
    text, enc = load_ks(src_path)
    lines = text.splitlines(True)
    replaced = missing = 0
    for item in items:
        idx = item["line"] - 1
        if idx >= len(lines):
            log.warning("%s: line %d out of range", src_path, item["line"])
            continue
        patched = patch_line(lines[idx], trans)
        if patched is None:
            missing += 1
            stats["missing"].append("%s:%d" % (src_path, item["line"]))
        else:
            lines[idx] = patched
            replaced += 1

    data = "".join(lines)
    try:
        encoded = data.encode(enc)
    except UnicodeEncodeError:
        encoded = data.encode("utf-8")
        log.warning("%s: %s cannot encode the translation, file converted "
                    "to UTF-8", src_path, enc)
    with open(out_path, "wb") as f:
        f.write(encoded)
    return replaced, missing


def apply(work_dir, scenario_dir, out_dir):
    work_dir = os.path.abspath(work_dir)
    scenario_dir = os.path.abspath(scenario_dir)
    out_dir = os.path.abspath(out_dir)

    trans = plain_io.load_json(os.path.join(work_dir, "translated.json"))
    structure = plain_io.load_json(os.path.join(work_dir, "structure.json"))
    if not os.path.isdir(scenario_dir):
        log.error("scenario dir not found: %s", scenario_dir)
        raise typer.Exit(code=1)

    stats = {"replaced": 0, "untranslated": 0, "missing": []}
    os.makedirs(out_dir, exist_ok=True)
    files_written = 0
    for m in structure.get("maps", []):
        name = m["id"]
        src_path = os.path.join(scenario_dir, name)
        if not os.path.exists(src_path):
            log.warning("%s: source missing, skipped", src_path)
            continue
        out_path = os.path.join(out_dir, name)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        replaced, missing = patch_file(src_path, out_path, m["items"],
                                       trans, stats)
        files_written += 1
        stats["replaced"] += replaced
        stats["untranslated"] += missing
        log.debug("%s: %d replaced, %d missing", name, replaced, missing)

    if stats["missing"]:
        log.warning("%d untranslated lines (samples: %s)",
                    len(stats["missing"]),
                    ", ".join(stats["missing"][:8]))
    log.info("%d files, %d lines replaced, %d untranslated -> %s",
             files_written, stats["replaced"], stats["untranslated"], out_dir)
    return stats


def cmd(work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
        scenario_dir: Annotated[Optional[str], cliutil.Option(
            "--scenario-dir", help="scenario tree to patch "
            "(default: <work>/scenario)")] = None,
        out: Annotated[Optional[str], cliutil.Option(
            "--out", help="patched tree output (default: <work>/patch)")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Write translated.json back into the TyranoScript .ks tree."""
    cliutil.setup_logging(verbose, quiet, log_file)
    work = os.path.abspath(work_dir)
    scenario = os.path.abspath(scenario_dir or os.path.join(work, "scenario"))
    out_dir = os.path.abspath(out or os.path.join(work, "patch"))
    apply(work, scenario, out_dir)
    return 0


# --help prints the tool's full documentation: a single-command Typer app
# shows the COMMAND docstring, so the module docstring is attached to it
# (the argparse version printed the same text as its description).
cmd.__doc__ = __doc__
app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="apply_tyrano_translation.py")


if __name__ == "__main__":
    raise SystemExit(main())
