#!/usr/bin/env python3
"""Batch-decode TLG images to PNG with multiprocessing (WSL-side tool).

Usage: python3 tools/batch_decode_tlg.py <in_dir> <out_dir> [--jobs N]
"""

import glob
import logging
import os
import sys
import time
from multiprocessing import Pool
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri import tlg

from rpgmaker import cliutil  # noqa: E402
from rpgmaker import runtime  # noqa: E402

log = logging.getLogger("batch_tlg")


def decode_one(args):
    src, out_dir = args
    name = os.path.basename(src)
    dst = os.path.join(out_dir, name[:-4] + ".png")
    try:
        data = open(src, "rb").read()
        tlg.decode_to_png(data, dst)
        return (name, True, "")
    except Exception as exc:
        # Broad catch on purpose: tlg.decode_to_png is a binary-format
        # parser and malformed TLG files can raise any of struct.error,
        # ValueError, zlib.error, IndexError, MemoryError etc. The worker
        # must record the failure and let the batch continue.
        return (name, False, str(exc))


def cmd(in_dir: Annotated[str, cliutil.Argument(help="directory with *.tlg")],
        out_dir: Annotated[str, cliutil.Argument(help="output directory for PNGs")],
        jobs: Annotated[int | None, cliutil.Option(
            "--jobs", help="worker processes (default: physical CPU cores)")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("decode tlg batch", in_dir=in_dir, out_dir=out_dir)
    jobs = runtime.resolve_workers("tlg", jobs, path=in_dir)
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(in_dir, "**", "*.tlg"),
                             recursive=True))
    if not files:
        log.error("%s: no *.tlg found", in_dir)
        return 1

    # warm the numba JIT once in the parent before forking workers
    if files:
        tlg.decode(open(files[0], "rb").read())
    log.info("%d tlg files -> %s (jobs=%d)", len(files), out_dir,
             jobs)
    t0 = time.perf_counter()
    with Pool(jobs) as pool:
        results = pool.map(decode_one, [(f, out_dir) for f in files],
                           chunksize=8)
    dt = time.perf_counter() - t0
    ok = sum(1 for _, s, _ in results if s)
    fail = [(n, e) for n, s, e in results if not s]
    log.info("%d/%d decoded in %.1fs (%.1f img/s)", ok, len(files), dt,
             ok / dt if dt else 0)
    for name, err in fail[:10]:
        log.warning("FAIL %s: %s", name, err)
    return 1 if fail else 0


app = cliutil.command_app(cmd, help=__doc__)
# argparse used the module docstring as the command description; keep that
# visible in --help (a collapsed single-command app shows the command help).
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="batch_decode_tlg.py")


if __name__ == "__main__":
    raise SystemExit(main())
