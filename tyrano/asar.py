#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Electron asar archive tool wrapper - extract TyranoScript/TyranoBuilder
games shipped as Electron apps.

The asar format is unpacked by the maintained @electron/asar CLI via npx
(the same "use an existing tool" policy as rewolf-trans for Wolf RPG).
This module only finds the tool and runs it; it does not re-implement
the archive format.

Usage:
    python3 -m tyrano.asar extract <app.asar> <out_dir>
    python3 -m tyrano.asar list <app.asar>
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import config, logsetup, proctools  # noqa: E402
log = logging.getLogger("tyrano.asar")

ASAR_PACKAGE = "@electron/asar"
# `npx --yes` may download the package on a cold cache, so this is generous -
# but finite: an offline or wedged npm must not hang the Tyrano build.
ASAR_TIMEOUT = 900


def find_npx():
    """Locate the npx launcher (Node.js package runner).

    Delegates to the shared application resolver so Node is probed the same
    way as every other tool (env NPX -> env_config -> probe -> PATH) instead
    of this module carrying its own PATH lookup.
    """
    npx = config.find_npx()
    if not npx:
        raise FileNotFoundError(
            "npx not found - install Node.js (nodejs.org) and re-run; the "
            "Tyrano build needs it to unpack app.asar (set NPX to override)")
    return npx


def _run(args, check=True):
    npx = find_npx()
    cmd = [npx, "--yes", ASAR_PACKAGE] + args
    return proctools.run(cmd, timeout=ASAR_TIMEOUT, label="npx @electron/asar",
                         check=check)


def list_files(asar_path):
    """Return the list of file paths inside an asar archive."""
    proc = _run(["list", asar_path])
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def extract(asar_path, out_dir):
    """Extract an asar archive into out_dir (created on demand)."""
    if not os.path.isfile(asar_path):
        raise FileNotFoundError("asar archive not found: %s" % asar_path)
    os.makedirs(out_dir, exist_ok=True)
    _run(["extract", asar_path, out_dir])
    log.info("extracted %s -> %s", asar_path, out_dir)
    return out_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="list files inside an asar")
    p_list.add_argument("asar_path")
    p_extract = sub.add_parser("extract", help="extract an asar archive")
    p_extract.add_argument("asar_path")
    p_extract.add_argument("out_dir")
    args = ap.parse_args()

    logsetup.setup(verbose=args.verbose)
    if args.command == "list":
        for p in list_files(args.asar_path):
            print(p)
    else:
        extract(args.asar_path, args.out_dir)


if __name__ == "__main__":
    main()
