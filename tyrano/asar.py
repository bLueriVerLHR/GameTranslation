#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Electron asar archive tool - extract TyranoScript/TyranoBuilder games
shipped as Electron apps.

Archive access goes through the maintained ``asar`` package (PyPI ``asar``,
MIT, pure Python).  It replaced the ``npx @electron/asar`` subprocess: the
official tool needs Node.js **and** may download the package on a cold npx
cache, which is a hard dependency for a build that otherwise needs none.
Equivalence was measured, not assumed - an archive packed by the *official*
Node tool (including an ``--unpack`` entry) extracts byte-identically through
the package, and the file list matches too (the Node CLI even prints
backslash-separated paths on Windows; the package returns plain ones).

Usage:
    python3 -m tyrano.asar extract <app.asar> <out_dir>
    python3 -m tyrano.asar list <app.asar>
"""

import logging
import os
import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("tyrano.asar")


def _open(asar_path, mode="r"):
    """Open an asar archive with the packaged implementation.

    Imported lazily and reported with an actionable message: the toolkit must
    stay importable (and its tests runnable) without the optional dependency.
    """
    try:
        from asar import AsarArchive
    except ImportError as exc:                 # pragma: no cover - install hint
        raise ImportError(
            "the 'asar' package is missing - install the toolkit dependencies "
            "(pip install -e .) to unpack app.asar archives") from exc
    return AsarArchive(Path(asar_path), mode)


def list_files(asar_path):
    """Return the list of file paths inside an asar archive."""
    if not os.path.isfile(asar_path):
        raise FileNotFoundError("asar archive not found: %s" % asar_path)
    with _open(asar_path) as archive:
        return [str(p).replace("\\", "/") for p in archive.list()]


def extract(asar_path, out_dir):
    """Extract an asar archive into out_dir (created on demand)."""
    if not os.path.isfile(asar_path):
        raise FileNotFoundError("asar archive not found: %s" % asar_path)
    os.makedirs(out_dir, exist_ok=True)
    with _open(asar_path) as archive:
        archive.extract(Path(out_dir))
    log.info("extracted %s -> %s", asar_path, out_dir)
    return out_dir


def cmd_list(asar_path: Annotated[str, cliutil.Argument(
            help="path to the app.asar archive")],
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """list files inside an asar"""
    cliutil.setup_logging(verbose, quiet, log_file)
    for p in list_files(asar_path):
        print(p)
    return 0


def cmd_extract(asar_path: Annotated[str, cliutil.Argument(
            help="path to the app.asar archive")],
        out_dir: Annotated[str, cliutil.Argument(
            help="directory to extract into")],
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """extract an asar archive"""
    cliutil.setup_logging(verbose, quiet, log_file)
    extract(asar_path, out_dir)
    return 0


app = cliutil.app(help=__doc__)
app.command(name="list", help="list files inside an asar")(cmd_list)
app.command(name="extract", help="extract an asar archive")(cmd_extract)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="asar.py")


if __name__ == "__main__":
    raise SystemExit(main())
