#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe and re-encode Vorbis audio in place.

Policy (music stays stereo at q3; voice/sfx become 32 kHz mono q2):
  channels != 1 and bitrate > 112000  -> libvorbis -q:a 3 (keep sr/ch)
  channels == 1 and bitrate >  64000  -> -ar 32000 -ac 1 libvorbis -q:a 2
Always `-map 0:a:0` so embedded album-art video streams are dropped.
Only replaces the original when the new file is smaller.
"""
import asyncio
import csv
import json
import logging
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

from . import config

log = logging.getLogger("rpgmz.audio")

DEFAULT_PROBE_WORKERS = 8
DEFAULT_ENCODE_WORKERS = 4


def probe_one(ffprobe, path, timeout=120):
    cmd = [ffprobe, "-v", "error", "-print_format", "json",
           "-show_entries",
           "format=duration,size,bit_rate,tags:stream=codec_name,codec_type,channels,sample_rate",
           path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        j = json.loads(r.stdout)
    except Exception as e:
        return {"error": str(e)}
    fmt = j.get("format", {})
    st = next((s for s in j.get("streams", [])
               if s.get("codec_type") == "audio"), None)
    tags = fmt.get("tags", {}) or {}
    return {
        "duration": fmt.get("duration"),
        "size": fmt.get("size"),
        "codec": st.get("codec_name") if st else None,
        "channels": st.get("channels") if st else None,
        "sample_rate": st.get("sample_rate") if st else None,
        "loopstart": tags.get("LOOPSTART"),
        "looplength": tags.get("LOOPLENGTH"),
    }


def bitrate_calc(fsize, duration):
    if not duration or float(duration) <= 0:
        return 0
    return int(fsize * 8 / float(duration))


def transcode_one(ffmpeg, path, info):
    """Re-encode one file. Returns (path, status, saved_bytes)."""
    try:
        dur = float(info["duration"])
        if not dur or dur <= 0:
            return path, "skip", 0
        if dur < 1.0:
            # Degenerate/short files (e.g. 0.9ms placeholder SE) get a bitrate
            # huge enough to pass the threshold, but re-encoding them produces a
            # broken Ogg with no audio packets. Leave anything under 1s alone.
            return path, "keep", 0
        fsize = int(info["size"])
        br = bitrate_calc(fsize, dur)
        ch = int(info["channels"] or 0)

        if ch == 1 and br > config.MONO_BITRATE_THRESHOLD:
            args = ["-ar", "32000", "-ac", "1", "-c:a", "libvorbis", "-q:a", "2"]
        elif ch != 1 and br > config.STEREO_BITRATE_THRESHOLD:
            args = ["-c:a", "libvorbis", "-q:a", "3"]
        else:
            return path, "keep", 0

        loopstart, looplength = info.get("loopstart"), info.get("looplength")
        if loopstart:
            args += ["-metadata:s:a:0", "LOOPSTART=%s" % loopstart,
                     "-metadata:s:a:0", "LOOPLENGTH=%s" % looplength]

        fd, tmp = tempfile.mkstemp(suffix=".ogg", dir=os.path.dirname(path))
        os.close(fd)
        cmd = [ffmpeg, "-y", "-v", "error", "-i", path, "-map", "0:a:0"] + args + [tmp]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            os.remove(tmp)
            return path, "error", 0
        newsize = os.path.getsize(tmp)
        if newsize < fsize:
            os.replace(tmp, path)
            return path, "reencoded", fsize - newsize
        os.remove(tmp)
        return path, "no-gain", 0
    except Exception as e:
        return path, "exc: %s" % e, 0


def iter_audio_files(web_root):
    for dp, _dn, fns in os.walk(os.path.join(web_root, "audio")):
        for fn in sorted(fns):
            if fn.lower().endswith((".ogg", ".m4a", ".rpgmvo")):
                yield os.path.join(dp, fn)


def probe_all(web_root, workers=DEFAULT_PROBE_WORKERS, sample=None):
    """Return {rel_path: info}. If sample is an int, probe at most that many.

    Probes run on a thread pool, awaited via asyncio: ffprobe is I/O-heavy and
    releases the GIL, so parallelism scales with worker count.
    """
    ffprobe = config.find_ffprobe()
    files = list(iter_audio_files(web_root))
    if sample:
        files = files[:sample]
    results = {}

    def work(path):
        rel = os.path.relpath(path, web_root)
        info = probe_one(ffprobe, path)
        info["fsize"] = os.path.getsize(path)
        return rel, info

    async def _run():
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            pairs = await asyncio.gather(
                *(loop.run_in_executor(ex, work, p) for p in files))
        return dict(pairs)

    results = asyncio.run(_run())
    log.info("probed %d audio files", len(results))
    return results


def reencode_all(web_root, infos, workers=DEFAULT_ENCODE_WORKERS):
    """Transcode using pre-probed info. Returns dict of counts + bytes saved.

    ffmpeg runs are heavyweight subprocesses; a modest thread pool keeps the
    CPU/disk busy without thrashing, and asyncio awaits them all at once.
    """
    ffmpeg = config.find_ffmpeg()
    counts = {}
    saved = 0
    done = 0
    total = len(infos)

    def work(item):
        rel, info = item
        path = os.path.join(web_root, rel)
        return transcode_one(ffmpeg, path, info)

    async def _run():
        nonlocal saved, done
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = await asyncio.gather(
                *(loop.run_in_executor(ex, work, item) for item in infos.items()))
        for path, status, saved_bytes in results:
            counts[status] = counts.get(status, 0) + 1
            saved += saved_bytes
            done += 1
            if done % 500 == 0 or done == total:
                log.info("...%d/%d", done, total)

    asyncio.run(_run())
    log.info("audio: %s, saved %.1f MB", dict(counts), saved / 1e6)
    return counts, saved


def write_probe_csv(infos, out_csv):
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "file", "fsize", "duration", "bitrate_calc", "codec",
            "channels", "sample_rate", "loopstart", "looplength", "error"])
        w.writeheader()
        for rel, info in infos.items():
            row = {"file": rel, "fsize": info.get("fsize", ""),
                   "duration": info.get("duration", ""),
                   "bitrate_calc": bitrate_calc(int(info.get("fsize") or 0),
                                                info.get("duration")),
                   "codec": info.get("codec", ""),
                   "channels": info.get("channels", ""),
                   "sample_rate": info.get("sample_rate", ""),
                   "loopstart": info.get("loopstart", ""),
                   "looplength": info.get("looplength", ""),
                   "error": info.get("error", "")}
            w.writerow(row)
    log.info("wrote probe report -> %s", out_csv)
