#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_key_prefix.py - repair agent output where values start with the key
text ("original line + translated line", e.g. V = K + "\\n" + translation).
Strips the leading key from every affected value in a chunks dir.

Usage:
    python tools\\fix_key_prefix.py <work_dir> [--chunks chunks]
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
        out = json.load(open(tp, encoding="utf-8"))
        ch = 0
        for k, v in out.items():
            if isinstance(v, str) and v.startswith(k) and len(v) > len(k):
                rest = v[len(k):]
                rest = rest.lstrip("\n")
                if rest and rest != v:
                    out[k] = rest
                    ch += 1
        if ch:
            json.dump(out, open(tp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print("%s: stripped key-prefix in %d values"
                  % (os.path.basename(tp), ch))
            total += ch
    print("total:", total)
    return 0


app = cliutil.command_app(cmd, help=__doc__)
# argparse used the module docstring as the command description; keep that
# visible in --help (a collapsed single-command app shows the command help).
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="fix_key_prefix.py")


if __name__ == "__main__":
    raise SystemExit(main())
