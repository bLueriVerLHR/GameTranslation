#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe and re-encode Vorbis audio in place.

Probing goes through `rpgmaker/media.py` (PyAV, in-process): no ffprobe
subprocess, and LOOPSTART/LOOPLENGTH are read from container AND stream tags
(the old ffprobe query asked for `format=...tags` only, so a stream-level
loop tag - where this pipeline's own encoder writes it - was invisible).

The Vorbis ENCODE still runs the ffmpeg binary: PyAV's wheels ship FFmpeg's
experimental native encoder but not libvorbis, and the q2/q3 policy below is
validated on device - see media.py's docstring for the measurements.

Policy (music stays stereo at q3; voice/sfx become 32 kHz mono q2):
  channels != 1 and bitrate > 112000  -> libvorbis -q:a 3 (keep sr/ch)
  channels == 1 and bitrate >  64000  -> -ar 32000 -ac 1 libvorbis -q:a 2
Always `-map 0:a:0` so embedded album-art video streams are dropped.
Only replaces the original when the new file is smaller.

The encode policy is a STRATEGY list (review §5): MonoVoiceStrategy /
StereoMusicStrategy / KeepOriginalStrategy, selected by pick_strategy().
Adding a new codec policy (e.g. Opus) is a new strategy class, not a new
branch in transcode_one().  A strategy returns only its encoder-specific
args; the fixed prefix (`-map 0:a:0`), the loop-tag metadata and the temp
file/atomic replace live in transcode_one alone.
"""
import csv
import logging
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

from . import config, media, runtime

log = logging.getLogger("rpgmaker.audio")

FFMPEG_TIMEOUT = 900   # per-file transcode timeout (seconds)
PROBE_TIMEOUT = 120  # per-file probe timeout (seconds)


def probe_one(path, timeout=PROBE_TIMEOUT):
    """Probe one file through `rpgmaker/media.py` (PyAV, in-process).

    No ffprobe subprocess: the packaged FFmpeg bindings expose container and
    stream metadata directly, and they report LOOPSTART/LOOPLENGTH written at
    stream level (which the old `format=...tags` query missed).
    """
    return media.probe(path)


def bitrate_calc(fsize, duration):
    if not duration or float(duration) <= 0:
        return 0
    return int(fsize * 8 / float(duration))


class EncodeStrategy:
    """Base class for the audio re-encode policy (review §5 / §5.1).

    A strategy decides whether a probed file should be re-encoded and which
    ffmpeg args to use.  `applies(info)` inspects the probe result
    (duration/size/channels) and `args()` returns the encoder arguments
    (without the fixed `-map 0:a:0` prefix added by transcode_one).

    Strategies are ordered by priority in STRATEGIES; the first one whose
    applies() returns True wins.  Degenerate/placeholder files (duration
    <= 0 or < 1s) NEVER reach a strategy: transcode_one guards them first
    because re-encoding them would produce a broken Ogg (see transcode_one).
    """

    def applies(self, info):
        raise NotImplementedError

    def args(self):
        raise NotImplementedError


class MonoVoiceStrategy(EncodeStrategy):
    """Voice/SFX: a single channel above the mono threshold -> 32 kHz mono
    q2 (halves the sample rate while keeping speech quality)."""

    def applies(self, info):
        ch = int(info["channels"] or 0)
        br = bitrate_calc(int(info["size"]), float(info["duration"]))
        return ch == 1 and br > config.MONO_BITRATE_THRESHOLD

    def args(self):
        return ["-ar", "32000", "-ac", "1", "-c:a", "libvorbis", "-q:a", "2"]


class StereoMusicStrategy(EncodeStrategy):
    """Music/BGM: multi-channel above the stereo threshold -> q3 at the
    original sample rate/channels (music stays stereo)."""

    def applies(self, info):
        ch = int(info["channels"] or 0)
        br = bitrate_calc(int(info["size"]), float(info["duration"]))
        return ch != 1 and br > config.STEREO_BITRATE_THRESHOLD

    def args(self):
        return ["-c:a", "libvorbis", "-q:a", "3"]


class KeepOriginalStrategy(EncodeStrategy):
    """Keep-original terminal strategy: matches any remaining file (below
    both thresholds) and emits no encode args - transcode_one returns
    'keep'.  Placed last in STRATEGIES so the re-encode strategies win;
    kept as an explicit class so the 'keep' decision is a first-class
    strategy (review §5)."""

    def applies(self, info):
        return True

    def args(self):
        return []


# Priority order: mono voice first, then stereo music, keep-original last.
STRATEGIES = [MonoVoiceStrategy(), StereoMusicStrategy(), KeepOriginalStrategy()]


def pick_strategy(info):
    """First strategy whose applies() is True (MonoVoice -> StereoMusic ->
    KeepOriginal); returns None only if STRATEGIES were empty.  The
    KeepOriginal terminal strategy stands in for the old code's "keep the
    file as-is" fallback."""
    return next((s for s in STRATEGIES if s.applies(info)), None)


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
        strategy = pick_strategy(info)
        args = strategy.args()
        if not args:
            return path, "keep", 0
        fsize = int(info["size"])

        loopstart, looplength = info.get("loopstart"), info.get("looplength")
        if loopstart:
            args += ["-metadata:s:a:0", "LOOPSTART=%s" % loopstart,
                     "-metadata:s:a:0", "LOOPLENGTH=%s" % looplength]

        fd, tmp = tempfile.mkstemp(suffix=".ogg", dir=os.path.dirname(path))
        os.close(fd)
        cmd = [ffmpeg, "-y", "-v", "error", "-i", path, "-map", "0:a:0"] + args + [tmp]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
        if r.returncode != 0:
            os.remove(tmp)
            # Per-file failure with the reason: the aggregate counter alone
            # ("audio: {... 'error': 3}") never says WHICH file or why.
            log.error("%s: ffmpeg failed (exit %d), file left untouched: %s",
                      path, r.returncode,
                      (r.stderr or "").strip()[-300:] or "no stderr")
            return path, "error", 0
        newsize = os.path.getsize(tmp)
        if newsize < fsize:
            os.replace(tmp, path)
            return path, "reencoded", fsize - newsize
        os.remove(tmp)
        return path, "no-gain", 0
    except (KeyError, TypeError, ValueError, OSError, subprocess.TimeoutExpired) as e:
        # Per-file transcode guard: malformed probe info (KeyError/TypeError/
        # ValueError), file I/O (OSError), ffmpeg timeout (TimeoutExpired).
        # A failure is recorded as the status so the batch keeps going.
        return path, "exc: %s" % e, 0


def iter_audio_files(web_root):
    for dp, _dn, fns in os.walk(os.path.join(web_root, "audio")):
        for fn in sorted(fns):
            if fn.lower().endswith((".ogg", ".m4a", ".rpgmvo")):
                yield os.path.join(dp, fn)


def probe_all(web_root, workers=None, sample=None):
    """Return {rel_path: info}. If sample is an int, probe at most that many.

    Probing is in-process (PyAV): the thread pool still helps because both
    demuxing and the decode-based duration fallback release the GIL.
    `workers=None` auto-tunes from the machine (see runtime.py).
    """
    workers = runtime.resolve_workers("probe", workers, path=web_root)
    files = list(iter_audio_files(web_root))
    if sample:
        files = files[:sample]

    def work(path):
        rel = os.path.relpath(path, web_root)
        info = probe_one(path)
        info["fsize"] = os.path.getsize(path)
        return rel, info

    # ex.map keeps input order (which the asyncio.gather version also did),
    # so the log lines and the returned mapping are unchanged.
    with ThreadPoolExecutor(max_workers=workers) as ex:
        pairs = list(ex.map(work, files))
    results = dict(pairs)
    log.info("probed %d audio files", len(results))
    return results


def reencode_all(web_root, infos, workers=None):
    """Transcode using pre-probed info. Returns dict of counts + bytes saved.

    ffmpeg runs are heavyweight subprocesses; a modest thread pool keeps the
    CPU/disk busy without thrashing.
    `workers=None` auto-tunes from the machine (see runtime.py).
    """
    workers = runtime.resolve_workers("encode", workers, path=web_root)
    ffmpeg = config.find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError(
            "ffmpeg not found - install ffmpeg or set the FFMPEG env var")
    counts = {}
    saved = 0
    done = 0
    total = len(infos)

    def work(item):
        rel, info = item
        path = os.path.join(web_root, rel)
        return transcode_one(ffmpeg, path, info)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(work, infos.items()))
    for path, status, saved_bytes in results:
        counts[status] = counts.get(status, 0) + 1
        saved += saved_bytes
        done += 1
        if done % 500 == 0 or done == total:
            log.info("...%d/%d", done, total)

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
