#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_literal_nl.py - repair real newlines back to literal \\n text in values
whose keys are single-line with literal backslash-n (agent wrote physical
lines for what is actually inline \\n control text).

fix_dbl_nl.py (sister tool) does the opposite: converts literal \\n back to
real newlines when the KEY has a real newline.

Usage:
    python tools\\fix_literal_nl.py <work_dir> [--chunks chunks]
"""
import glob
import json
import os
import sys
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402


def cmd(work_dir: Annotated[str, cliutil.Argument(
            help="translation work dir (contains chunks/)")],
        chunks: Annotated[str, cliutil.Option(
            "--chunks", help="chunks subdirectory name")] = "chunks") -> int:
    W = os.path.join(os.path.abspath(work_dir), chunks)
    total = 0
    for tp in sorted(glob.glob(os.path.join(W, "*.translated.json"))):
        src_path = tp.replace(".translated.json", ".json")
        if not os.path.exists(src_path):
            continue
        out = json.load(open(tp, encoding="utf-8"))
        ch = 0
        for k, v in out.items():
            if "\n" not in v:
                continue
            if k.count("\n") == 0 and "\\n" in k:
                out[k] = v.replace("\n", "\\n")
                ch += 1
        if ch:
            json.dump(out, open(tp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("%s: %d literal-\\n repairs" % (os.path.basename(tp), ch))
            total += ch
    print("total:", total)
    return 0


app = cliutil.command_app(cmd, help=__doc__)
# argparse used the module docstring as the command description; keep that
# visible in --help (a collapsed single-command app shows the command help).
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="fix_literal_nl.py")


if __name__ == "__main__":
    raise SystemExit(main())
