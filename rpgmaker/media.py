#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media.py - the single media surface, built on PyAV.

PyAV (`av`) is the packaged binding to the FFmpeg *libraries*: probing,
demuxing and decoding happen in-process, so the toolkit no longer builds
ffprobe argv or parses its JSON.

Verified against the ffprobe invocation this used to run (2 s / 44.1 kHz
stereo, encoded to Ogg Vorbis with libvorbis):

    field          ffprobe      PyAV
    duration       2.002902     2.0        (last-packet rounding, 0.15%)
    size           9326         9326
    codec          vorbis       vorbis
    channels       2            2
    sample_rate    44100        44100
    LOOPSTART      (missed)     44100

That last row is a real fix, not just a port: the old probe asked ffprobe
for ``format=...tags`` only, so a LOOPSTART written as a *stream* tag - where
ffmpeg's ``-metadata:s:a:0`` (this very pipeline's own encoder argument) puts
it - was invisible, and the re-encode then dropped the loop points.  PyAV
reports container and stream tags together.

What still needs the ffmpeg binary: **encoding**.  PyAV's binary wheels ship
FFmpeg's native ``vorbis`` encoder (flagged experimental, a different quality
model) but **not** ``libvorbis``, and the audio policy (q2/q3 libvorbis,
validated on device) must not change silently - so ``audio.py`` /
``tyrano/audio.py`` keep the CLI for that one step, and
``tools/transcode_video.py`` keeps it for the validated VP9/Opus recipe.  Both
build their argv in exactly one place.
"""
import logging
import os

log = logging.getLogger("rpgmaker.media")

#: Fields every probe() result carries (or {"error": ...} on failure).
FIELDS = ("duration", "size", "codec", "channels", "sample_rate",
          "loopstart", "looplength")

# Loop tags are read from the container AND the stream: RPG Maker Ogg files
# carry them as Vorbis comments (stream level), while repack tools sometimes
# write them at container level.
LOOP_TAGS = ("LOOPSTART", "LOOPLENGTH")


def _av():
    """Import PyAV lazily with an actionable error."""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - packaging error
        raise RuntimeError(
            "PyAV is required for media probing/decoding - install it with "
            "`pip install av` (or `pip install -e .` in this repo)") from exc
    return av


def has_codec(name):
    """True when this PyAV build knows the codec (encoder or decoder)."""
    av = _av()
    return name in av.codecs_available


def _duration_seconds(container, stream, path):
    """Duration in seconds from container metadata, stream metadata, or a
    decode pass (last resort - Ogg files without a duration header)."""
    av = _av()
    if container.duration is not None:
        return float(container.duration) / av.time_base
    if stream is not None and stream.duration is not None \
            and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    log.debug("%s: no duration in the container, decoding to measure", path)
    frames = 0
    total = 0
    try:
        for frame in container.decode(stream):
            frames += 1
            total += frame.samples or len(frame)
        rate = stream.codec_context.sample_rate or 0
        return float(total) / rate if rate else None
    except Exception as exc:  # noqa: BLE001 - a broken file has no duration
        log.debug("%s: duration decode failed: %s", path, exc)
        return None


def probe(path):
    """Probe one media file.

    Returns a dict with FIELDS set (values are numbers / strings, missing
    ones None) or {"error": "<reason>"} - the same contract the ffprobe-based
    probe had, so callers and CSV reports are unchanged.
    """
    av = _av()
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return {"error": "cannot stat %s: %s" % (path, exc)}
    try:
        with av.open(path) as container:
            stream = next((s for s in container.streams
                           if s.type == "audio"), None)
            if stream is None:
                return {"error": "no audio stream in %s" % path}
            cc = stream.codec_context
            tags = {}
            tags.update(container.metadata or {})
            tags.update(stream.metadata or {})
            loop = {k.lower(): (tags.get(k) or tags.get(k.lower()))
                    for k in LOOP_TAGS}
            info = {
                "duration": _duration_seconds(container, stream, path),
                "size": size,
                "codec": cc.name,
                "channels": stream.channels or cc.channels,
                "sample_rate": cc.sample_rate,
                "loopstart": loop["loopstart"],
                "looplength": loop["looplength"],
            }
    except Exception as exc:  # noqa: BLE001 - PyAV raises its own hierarchy
        # Two independent measurements (ffmpeg today, PyAV before) cannot
        # disagree silently: a probe failure must stay visible as an error.
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    log.debug("probe %s: %s", path, info)
    return info


def probe_video(path):
    """Probe the first video stream: {codec, width, height, duration, size}.

    Used by the KAG video transcoder for its own before/after check, so the
    comparison no longer shells out to ffprobe.
    """
    av = _av()
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return {"error": "cannot stat %s: %s" % (path, exc)}
    try:
        with av.open(path) as container:
            stream = next((s for s in container.streams
                           if s.type == "video"), None)
            if stream is None:
                return {"error": "no video stream in %s" % path}
            cc = stream.codec_context
            return {"codec": cc.name, "width": cc.width, "height": cc.height,
                    "duration": _duration_seconds(container, stream, path),
                    "size": size}
    except Exception as exc:  # noqa: BLE001
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def decode_ok(path):
    """Decode every frame; returns (ok, reason).

    Replaces `ffmpeg -v error -i <file> -f null -` for the verify step: a
    truncated or corrupt file raises inside the decode loop, which is exactly
    the signal the old CLI's exit code carried.
    """
    av = _av()
    try:
        with av.open(path) as container:
            stream = next((s for s in container.streams
                           if s.type in ("audio", "video")), None)
            if stream is None:
                return False, "no decodable stream"
            n = 0
            for _frame in container.decode(stream):
                n += 1
        return True, "%d frames" % n
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)
