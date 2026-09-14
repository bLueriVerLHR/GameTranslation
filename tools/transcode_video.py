#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transcode an archive's .wmv/.mpg videos to WebM (VP9 + Opus).

Why VP9 and not AV1: the target is a browser/JoiPlay build, and VP9 decode is
far more widely available on Android than AV1.  Measured on this machine,
VP9 (crf 32, cpu-used 4) runs at ~3.6x realtime and shrinks the source to
~23%, so a whole 955 MB / ~18 min set costs a few minutes.

Encoding is **in-process** (PyAV ships libvpx-vp9 and libopus), so this tool
needs no ffmpeg binary: `rpgmaker.media.transcode_to_webm` owns the recipe and
documents the measured parity with the ffmpeg CLI it replaced (identical
frame count, timestamps and audio sample count, PSNR within +-0.3 dB; the
video bitstream comes out ~6% larger at the same settings).

Once extracted to a temp file and encoded, every output is verified in-process
as well (probe + full decode), so a file that fails to encode cannot silently
disappear from the build; existing outputs are skipped so the job can be
re-run.

Usage:
    transcode_video.py <xp3> <out_dir> [--crf 32] [--cpu-used 4] [--jobs 3]
"""
import collections
import concurrent.futures
import logging
import os
import shutil
import sys
import tempfile
import time
from typing import Annotated, Optional


_HERE = os.path.dirname(os.path.abspath(__file__))
# Repo root for the packages, tools dir for the sibling helpers.
sys.path.append(os.path.dirname(_HERE))
from kirikiri.xp3tool import extract_segment, open_xp3  # noqa: E402
from rpgmaker import cliutil, media, runtime  # noqa: E402

log = logging.getLogger("transcode_video")

VIDEO_EXT = (".wmv", ".mpg", ".mpeg", ".avi")


def transcode_one(entry, xp3, out_dir, crf, cpu_used):
    """Extract one archive entry and encode it; returns (name, size, s, status).

    Status is "ok" / "cached" / "WARN: ..." / "FAILED: ..." - the caller only
    has to look at the prefix, and a failure always carries its reason.
    """
    name = os.path.splitext(os.path.basename(entry["name"]))[0]
    dest = os.path.join(out_dir, name + ".webm")
    if os.path.isfile(dest) and "error" not in media.probe_video(dest):
        return (name, os.path.getsize(dest), 0.0, "cached")

    tmpdir = tempfile.mkdtemp(prefix="tconv_")
    try:
        raw = os.path.join(tmpdir, "in" + os.path.splitext(entry["name"])[1])
        with open(xp3, "rb") as f, open(raw, "wb") as out:
            for seg in entry["segments"]:
                out.write(extract_segment(f, entry["name"], *seg))
        before = media.probe_video(raw)
        start = time.time()
        try:
            media.transcode_to_webm(raw, dest, crf=crf, cpu_used=cpu_used)
        except Exception as exc:                       # noqa: BLE001
            return (name, 0, time.time() - start,
                    "FAILED: %s: %s" % (type(exc).__name__, exc))
        elapsed = time.time() - start

        after = media.probe_video(dest)
        if "error" in after:
            return (name, 0, elapsed,
                    "FAILED: output not decodable: %s" % after["error"])
        ok, reason = media.decode_ok(dest)
        if not ok:
            return (name, 0, elapsed, "FAILED: incomplete output: %s" % reason)
        src_dur = float(before.get("duration") or 0)
        dur = float(after.get("duration") or 0)
        if src_dur and dur < src_dur - 1.0:
            return (name, os.path.getsize(dest), elapsed,
                    "WARN: shorter than source (%.1fs vs %.1fs)"
                    % (dur, src_dur))
        return (name, os.path.getsize(dest), elapsed, "ok")
    except OSError as exc:
        return (name, 0, 0.0, "FAILED: %s" % exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cmd(xp3: Annotated[str, cliutil.Argument(help="xp3 archive holding the movies")],
        out: Annotated[str, cliutil.Argument(help="directory for the .webm files")],
        crf: Annotated[int, cliutil.Option(
            "--crf", help="VP9 constant-quality level (lower = better/bigger)")] = 32,
        cpu_used: Annotated[int, cliutil.Option(
            "--cpu-used", help="VP9 speed 0-8 (lower = slower/smaller)")] = 4,
        jobs: Annotated[Optional[int], cliutil.Option(
            "--jobs", help="videos encoded in parallel (default: half the "
                    "physical cores, because each VP9 encoder is itself "
                    "multi-threaded)")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)
    jobs = runtime.resolve_workers("video", jobs, path=out)

    entries = [e for e in open_xp3(xp3) if e["name"].lower().endswith(VIDEO_EXT)]
    os.makedirs(out, exist_ok=True)
    print("%d video file(s) in %s" % (len(entries), xp3), flush=True)

    stats = collections.Counter()
    lock = __import__("threading").Lock()
    started = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        results = pool.map(
            lambda e: transcode_one(e, xp3, out, crf, cpu_used), entries)
        for i, (name, _size, _elapsed, status) in enumerate(results, 1):
            with lock:
                stats[status.split(":")[0]] += 1
                if status.startswith(("FAILED", "WARN")):
                    print("  %-28s %s" % (name, status), flush=True)
                elif not quiet and (i % 10 == 0 or i == len(entries)):
                    print("  [%d/%d] %.1fs elapsed"
                          % (i, len(entries), time.time() - started),
                          flush=True)

    total = sum(os.path.getsize(os.path.join(out, f))
                for f in os.listdir(out) if f.endswith(".webm"))
    print("\ntranscoded %d file(s) in %.1fs" % (len(entries),
                                                time.time() - started))
    print("output: %.1f MB in %s" % (total / 1048576, out))
    for key, count in stats.most_common():
        print("  %-8s %d" % (key, count))
    return 1 if stats.get("FAILED") else 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="transcode_video.py")


if __name__ == "__main__":
    raise SystemExit(main())
