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

Parsing is in-process (`rpgmaker.jssyntax`, tree-sitter), so it needs no
Node.js and no temp file per block.  Measured against the `node --check` call
it replaced: 225/225 verdicts agreed over 58 real JS files (TyranoScript
runtime libraries, minified ones included) each tested as-is plus three
corruption modes.  Run this after `convert_kag.py`, before serve/play-testing.

Known limit: this only catches what does not PARSE.  Conversion damage that
stays syntactically valid (e.g. a leaked `setter(x){...}` that a preceding
comma turns into an ES6 method shorthand, so the accessor is silently
missing) cannot be found here - that belongs in the converter's own tests.

Usage
-----
    python3 tools/check_iscript_js.py <scenario_dir> [--limit N] [--json]

Exit codes: 0 = all blocks parse; 1 = at least one syntax error;
2 = the JS parser is unavailable (cannot check - do not report success).

Non-ASCII scenario encodings (UTF-16LE/BE, Shift-JIS, UTF-8) are detected the
same way the rest of the toolkit detects them.
"""

import glob
import json
import logging
import os
import sys
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kirikiri.ks_extract import load_ks  # noqa: E402
from rpgmaker import cliutil, jssyntax  # noqa: E402

log = logging.getLogger("check_iscript_js")

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
    """Return None when the block parses, else a one-line description."""
    errors = jssyntax.parse_errors(body)
    if not errors:
        return None
    first = errors[0]
    if len(errors) == 1:
        return first["error"]
    return "%s (and %d more)" % (first["error"], len(errors) - 1)


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


def cmd(scenario_dir: Annotated[str, cliutil.Argument(
            help="converted build's scenario dir")],
        limit: Annotated[int, cliutil.Option(
            "--limit", help="stop after N errors (0 = report all)")] = 0,
        json_out: Annotated[bool, cliutil.Option(
            "--json", help="emit a machine-readable summary")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Syntax-check the JavaScript inside converted [iscript] blocks."""
    cliutil.setup_logging(verbose, quiet, log_file)
    if not os.path.isdir(scenario_dir):
        return cliutil.fail("not a directory: %s" % scenario_dir)

    try:
        checked, problems = scan_tree(scenario_dir, limit)
    except ImportError as exc:
        log.error("the JavaScript parser is unavailable - install the toolkit "
                  "dependencies (tree-sitter, tree-sitter-javascript): %s", exc)
        return 2

    if json_out:
        print(json.dumps({"blocks": checked, "errors": problems}, indent=2))
    else:
        log.info("checked %d iscript block(s): %d with syntax errors",
                 checked, len(problems))
    return 1 if problems else 0


# --help prints the tool's full documentation: a single-command Typer app
# shows the COMMAND docstring, so the module docstring is attached to it
# (the argparse version printed the same text as its description).
cmd.__doc__ = __doc__
app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="check_iscript_js.py")


if __name__ == "__main__":
    raise SystemExit(main())
