#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Syntax-check the JavaScript inside converted `[iscript]` blocks.

Why this exists
---------------
The TJS2 -> JavaScript conversion inside `[iscript]` blocks can leave invalid
JavaScript behind (an unconverted construct, a greedy regex that swallowed a
brace, a stray keyword).  At runtime such a block produces **no error message
at all** - the scenario simply stops advancing, which looks exactly like a
hang: the last HTTP request is the file that contains the bad block, CPU is
idle and a black screen is all you see.

`node --check` turns that into a filename and a line number in seconds.
Measured on a real build: the broken file reported

    SyntaxError: Unexpected identifier 'setter'

and after the conversion fix the whole build reported 0 errors over 84
blocks.  Run this after `convert_kag.py`, before serve/play-testing.

Known limit: this only catches what does not PARSE.  Conversion damage that
stays syntactically valid (e.g. a leaked `setter(x){...}` that a preceding
comma turns into an ES6 method shorthand, so the accessor is silently
missing) cannot be found here - that belongs in the converter's own tests.

Usage
-----
    python3 tools/check_iscript_js.py <scenario_dir> [--limit N] [--json]

Exit codes: 0 = all blocks parse; 1 = at least one syntax error;
2 = node is unavailable (cannot check - do not report success).

Non-ASCII scenario encodings (UTF-16LE/BE, Shift-JIS, UTF-8) are detected the
same way the rest of the toolkit detects them.
"""

import argparse
import glob
import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kirikiri.ks_extract import load_ks  # noqa: E402
from rpgmaker import proctools  # noqa: E402
from rpgmaker.config import find_node  # noqa: E402

from rpgmaker import logsetup  # noqa: E402

log = logging.getLogger("check_iscript_js")

NODE_TIMEOUT = 120

OPEN_TAG = "[iscript"
CLOSE_TAG = "[endscript]"


def iter_iscript_blocks(text):
    """Yield (char_offset, body) for every `[iscript]...[endscript]` block."""
    pos = 0
    while True:
        start = text.find(OPEN_TAG, pos)
        if start < 0:
            return
        brace = text.find("]", start)
        end = text.find(CLOSE_TAG, brace)
        if brace < 0 or end < 0:
            return                      # unclosed block: nothing more to check
        body = text[brace + 1:end]
        pos = end + len(CLOSE_TAG)
        if body.strip():
            yield start, body


def check_block(body):
    """Return None when the block parses, else the SyntaxError line."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(body)
            tmp = fh.name
        node = find_node()
        if not node:
            raise FileNotFoundError("node")
        proc = proctools.run([node, "--check", tmp], timeout=NODE_TIMEOUT,
                             label="node --check", check=False)
        if proc.returncode == 0:
            return None
        lines = (proc.stderr or "").strip().splitlines()
        return next((ln.strip() for ln in lines if "SyntaxError" in ln),
                    lines[-1].strip() if lines else "unknown syntax error")
    except FileNotFoundError:
        raise
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def scan_tree(root, limit=0):
    """Check every scenario under `root`; returns (blocks, errors) lists."""
    checked = 0
    problems = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.ks"),
                                 recursive=True)):
        try:
            text, _enc = load_ks(path)
        except OSError as exc:
            # locate the failure instead of swallowing it
            log.warning("%s: unreadable (%s)", path, exc)
            continue
        for offset, body in iter_iscript_blocks(text):
            checked += 1
            problem = check_block(body)
            if problem:
                problems.append({"file": path, "offset": offset,
                                 "error": problem})
                log.error("%s: iscript block at char %d does not parse: %s",
                          os.path.relpath(path, root), offset, problem)
                if limit and len(problems) >= limit:
                    log.info("stopping after %d error(s) as requested",
                             limit)
                    return checked, problems
    return checked, problems


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario_dir", help="converted build's scenario dir")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N errors (0 = report all)")
    ap.add_argument("--json", action="store_true",
                    help="emit a machine-readable summary")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logsetup.setup(verbose=args.verbose)
    if not os.path.isdir(args.scenario_dir):
        print("error: not a directory: %s" % args.scenario_dir,
              file=sys.stderr)
        return 1

    try:
        checked, problems = scan_tree(args.scenario_dir, args.limit)
    except FileNotFoundError:
        log.error("`node` not found - install Node.js to syntax-check "
                  "iscript blocks (result would be meaningless otherwise)")
        return 2

    if args.json:
        print(json.dumps({"blocks": checked, "errors": problems}, indent=2))
    else:
        log.info("checked %d iscript block(s): %d with syntax errors",
                 checked, len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
