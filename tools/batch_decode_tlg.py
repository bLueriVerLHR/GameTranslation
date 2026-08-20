#!/usr/bin/env python3
"""Batch-decode TLG images to PNG with multiprocessing (WSL-side tool).

Usage: python3 tools/batch_decode_tlg.py <in_dir> <out_dir> [--jobs N]
"""

import argparse
import glob
import logging
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri import tlg

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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("in_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    os.makedirs(args.out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(args.in_dir, "**", "*.tlg"),
                             recursive=True))
    if not files:
        log.error("%s: no *.tlg found", args.in_dir)
        return 1

    # warm the numba JIT once in the parent before forking workers
    if files:
        tlg.decode(open(files[0], "rb").read())
    log.info("%d tlg files -> %s (jobs=%d)", len(files), args.out_dir,
             args.jobs)
    t0 = time.perf_counter()
    with Pool(args.jobs) as pool:
        results = pool.map(decode_one, [(f, args.out_dir) for f in files],
                           chunksize=8)
    dt = time.perf_counter() - t0
    ok = sum(1 for _, s, _ in results if s)
    fail = [(n, e) for n, s, e in results if not s]
    log.info("%d/%d decoded in %.1fs (%.1f img/s)", ok, len(files), dt,
             ok / dt if dt else 0)
    for name, err in fail[:10]:
        log.warning("FAIL %s: %s", name, err)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
