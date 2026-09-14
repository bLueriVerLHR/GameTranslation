#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transcode an archive's .wmv/.mpg videos to WebM (VP9 + Opus).

Why VP9 and not AV1: the target is a browser/JoiPlay build, and VP9 decode is
far more widely available on Android than AV1.  Measured on this machine,
VP9 (crf 32, cpu-used 4) runs at ~3.6x realtime and shrinks the source to
~23%, so the whole 955 MB / ~18 min set costs ~5 minutes.

Every output is verified with ffprobe (a file that fails to encode must not
silently disappear from the build), and existing outputs are skipped so the
job can be re-run.

Usage:
    transcode_video.py <xp3> <out_dir> [--crf 32] [--cpu-used 4] [--jobs 3]
"""
import argparse
import collections
import concurrent.futures
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kirikiri.xp3tool import extract_segment, open_xp3  # noqa: E402
from rpgmaker import config, proctools  # noqa: E402

VIDEO_EXT = (".wmv", ".mpg", ".mpeg", ".avi")

PROBE_TIMEOUT = 120
# A VP9 re-encode is legitimately long: no timeout, but the decode is explicit.
ENCODE_TIMEOUT = None


def probe(path):
    ffprobe = config.find_ffprobe()
    if not ffprobe:
        return None
    r = proctools.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_name,width,height:format=duration",
         "-of", "default=noprint_wrappers=1", path],
        timeout=PROBE_TIMEOUT, label="ffprobe", check=False)
    if r.returncode != 0:
        return None
    return dict(ln.split("=", 1) for ln in r.stdout.strip().splitlines()
                if "=" in ln)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xp3")
    ap.add_argument("out")
    ap.add_argument("--crf", type=int, default=32)
    ap.add_argument("--cpu-used", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    ffmpeg = config.find_ffmpeg()
    ffprobe = config.find_ffprobe()
    missing = [name for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe))
               if not path]
    if missing:
        # Single resolver (config.TOOLS), so `pipeline.py doctor` sees the same
        # answer this check does.
        print("error: %s not found - install ffmpeg/ffprobe or set the "
              "FFMPEG / FFPROBE env vars" % ", ".join(missing),
              file=sys.stderr)
        return 2

    entries = [e for e in open_xp3(args.xp3)
               if e["name"].lower().endswith(VIDEO_EXT)]
    os.makedirs(args.out, exist_ok=True)
    print("%d video file(s) in %s" % (len(entries), args.xp3), flush=True)

    stats = collections.Counter()
    lock = __import__("threading").Lock()
    t0 = time.time()

    def job(entry):
        name = os.path.splitext(os.path.basename(entry["name"]))[0]
        dest = os.path.join(args.out, name + ".webm")
        if os.path.isfile(dest) and probe(dest):
            return (name, os.path.getsize(dest), 0.0, "cached")
        tmpdir = tempfile.mkdtemp(prefix="tconv_")
        try:
            raw = os.path.join(tmpdir, "in" + os.path.splitext(entry["name"])[1])
            with open(args.xp3, "rb") as f, open(raw, "wb") as out:
                for seg in entry["segments"]:
                    out.write(extract_segment(f, entry["name"], *seg))
            before = probe(raw)
            start = time.time()
            r = proctools.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                 "-i", raw,
                 "-c:v", "libvpx-vp9", "-crf", str(args.crf), "-b:v", "0",
                 "-row-mt", "1", "-cpu-used", str(args.cpu_used),
                 "-deadline", "good",
                 "-c:a", "libopus", "-b:a", "96k", "-ac", "2",
                 "-f", "webm", dest],
                timeout=ENCODE_TIMEOUT, label="ffmpeg vp9", check=False)
            elapsed = time.time() - start
            if r.returncode != 0 or not os.path.isfile(dest):
                return (name, 0, elapsed,
                        "FAILED: %s" % (r.stderr or "")[-200:].replace("\n", " "))
            after = probe(dest)
            if not after or "codec_name" not in after:
                return (name, 0, elapsed, "FAILED: output not decodable")
            dur = float(after.get("duration") or 0)
            src_dur = float((before or {}).get("duration") or 0)
            if src_dur and dur < src_dur - 1.0:
                return (name, os.path.getsize(dest), elapsed,
                        "WARN: shorter than source (%.1fs vs %.1fs)"
                        % (dur, src_dur))
            return (name, os.path.getsize(dest), elapsed, "ok")
        except Exception as exc:                       # noqa: BLE001
            return (name, 0, 0.0, "FAILED: %s: %s" % (type(exc).__name__, exc))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for i, (name, size, elapsed, status) in enumerate(
                pool.map(job, entries), 1):
            with lock:
                stats[status.split(":")[0]] += 1
                if status.startswith("FAILED") or status.startswith("WARN"):
                    print("  %-28s %s" % (name, status), flush=True)
                elif not args.quiet and (i % 10 == 0 or i == len(entries)):
                    print("  [%d/%d] %.1fs elapsed" % (i, len(entries),
                                                       time.time() - t0),
                          flush=True)

    total = sum(os.path.getsize(os.path.join(args.out, f))
                for f in os.listdir(args.out) if f.endswith(".webm"))
    print("\ntranscoded %d file(s) in %.1fs" % (len(entries), time.time() - t0))
    print("output: %.1f MB in %s" % (total / 1048576, args.out))
    for k, v in stats.most_common():
        print("  %-8s %d" % (k, v))
    return 1 if stats.get("FAILED") else 0


if __name__ == "__main__":
    sys.exit(main())
