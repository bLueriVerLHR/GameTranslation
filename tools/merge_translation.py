#!/usr/bin/env python3
"""merge_translation.py - Final merge of prefilled (MTool exact hits) + agent
chunks into translated.json, with an optional terminology sweep.

Consolidated from the long-run session merge script. Sweep rules come from a
JSON list [[from, to], ...] or {"from": "to"} file, applied IN ORDER.

WARNING (substring bomb, docs/translation.md §4.2): a sweep target
that itself contains the prefix of another rule (色经验值->色色经验值) will be
re-hit if applied later. Order rules longest-first, and afterwards re-scan
the output for any malformed target strings.

All file arguments (--chunks / --prefilled / --sweep / --out) resolve
RELATIVE TO work_dir, so the whole merge stays inside the work package no
matter what the current directory is.

Usage:
    python tools\\merge_translation.py <work_dir> --chunks chunks_translated.json \\
        --prefilled <prefilled.json> [--sweep <sweep_rules.json>] [--out translated.json]

  --chunks    the merge_plain_chunks.py output (agent chunks).  Omitted for
              legacy: globs chunks/*.translated.json.
"""
import glob
import json
import os
import sys
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402


def load_sweeps(path):
    rules = plain_io.load_json(path)
    if isinstance(rules, dict):
        rules = list(rules.items())
    # longest-first so longer targets apply before their own prefixes
    rules.sort(key=lambda r: len(r[0]), reverse=True)
    return rules


def cmd(work_dir: Annotated[str, cliutil.Argument(
            help="translation work dir")],
        chunks: Annotated[str, cliutil.Option(
            "--chunks", help="merge_plain_chunks.py output, relative to "
            "work_dir (default: glob legacy chunks/*.translated.json)")] = "",
        prefilled: Annotated[str, cliutil.Option(
            "--prefilled", help="prefilled.json (MTool exact hits), relative "
            "to work_dir; optional")] = "",
        sweep: Annotated[str, cliutil.Option(
            "--sweep", help="terminology sweep rules JSON (list of pairs), "
            "relative to work_dir")] = "",
        out: Annotated[str, cliutil.Option(
            "--out", help="output file name, relative to work_dir")] = \
        "translated.json",
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    work = os.path.abspath(work_dir)
    sweeps = load_sweeps(os.path.join(work, sweep)) if sweep else []

    def sweep(v):
        for a, b in sweeps:
            v = v.replace(a, b)
        return v

    merged = {}
    if chunks:
        d = plain_io.load_json(os.path.join(work, chunks))
        for k, v in d.items():
            merged[k] = sweep(v)
        print("chunks merged: %d keys (from %s)" % (len(merged), chunks))
    else:
        for p in sorted(glob.glob(os.path.join(work, "chunks", "*.translated.json"))):
            d = plain_io.load_json(p)
            for k, v in d.items():
                merged[k] = sweep(v)
        print("chunks merged: %d keys" % len(merged))

    if prefilled:
        pref = plain_io.load_json(os.path.join(work, prefilled))
        pref_swept = 0
        for k, v in pref.items():
            nv = sweep(v)
            if nv != v:
                pref_swept += 1
            merged[k] = nv
        print("prefilled merged: %d keys (%d swept)" % (len(pref), pref_swept))
    print("sweep rules applied: %d" % len(sweeps))

    tpl = plain_io.load_json(os.path.join(work, "template.json"))
    missing = [k for k in tpl if k not in merged]
    extra = [k for k in merged if k not in tpl]
    print("merged keys: %d | template keys: %d | missing: %d | extra: %d"
          % (len(merged), len(tpl), len(missing), len(extra)))

    out_path = os.path.join(work, out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    print("wrote %s with %d keys" % (out_path, len(merged)))
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="merge_translation.py")


if __name__ == "__main__":
    raise SystemExit(main())
