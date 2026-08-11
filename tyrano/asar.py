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
import shutil
import subprocess
import sys

log = logging.getLogger("tyrano.asar")

ASAR_PACKAGE = "@electron/asar"


def find_npx():
    """Locate the npx launcher (nodejs package runner)."""
    npx = shutil.which("npx")
    if not npx and sys.platform == "win32":
        npx = shutil.which("npx.cmd")
    if not npx:
        raise FileNotFoundError(
            "npx not found on PATH - install Node.js (nodejs.org) and "
            "re-run; the Tyrano build needs it to unpack app.asar")
    return npx


def _run(args, check=True):
    npx = find_npx()
    cmd = [npx, "--yes", ASAR_PACKAGE] + args
    log.debug("running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError("asar command failed (%d): %s\n%s"
                           % (proc.returncode, " ".join(cmd),
                              (proc.stderr or proc.stdout)[-2000:]))
    return proc


def list_files(asar_path):
    """Return the list of file paths inside an asar archive."""
    proc = _run(["list", asar_path])
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def extract(asar_path, out_dir):
    """Extract an asar archive into out_dir (created on demand)."""
    if not os.path.isfile(asar_path):
        raise FileNotFoundError("asar archive not found: %s" % asar_path)
    os.makedirs(out_dir, exist_ok=True)
    proc = _run(["extract", asar_path, out_dir])
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

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    if args.command == "list":
        for p in list_files(args.asar_path):
            print(p)
    else:
        extract(args.asar_path, args.out_dir)


if __name__ == "__main__":
    main()
