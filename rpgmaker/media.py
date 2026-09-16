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

What still needs the ffmpeg binary: **audio encoding**.  PyAV's binary wheels
ship FFmpeg's native ``vorbis`` encoder (flagged experimental, a different
quality model) but **not** ``libvorbis``, and the audio policy (q2/q3
libvorbis, validated on device) must not change silently - so ``audio.py`` /
``tyrano/audio.py`` keep the CLI for that one step, with the argv built in
exactly one place.  **Video** (VP9 + Opus, the mobile recipe) is in-process
here: PyAV does ship libvpx-vp9 and libopus, so ``transcode_to_webm()`` below
replaced the ffmpeg CLI call.
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

# PyAV container-open options.  `metadata_errors="replace"` matters on real
# doujin games: some Japanese tools write Vorbis comments in Shift-JIS, which
# makes PyAV raise UnicodeDecodeError while decoding the tag values - a
# perfectly valid audio file looked broken (the probe returned an error and
# `verify --decode` reported it as corrupt).  Tags are only read for
# LOOPSTART/LOOPLENGTH (ASCII), so replacing undecodable tag bytes is safe.
OPEN_OPTS = {"metadata_errors": "replace"}


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
        with av.open(path, **OPEN_OPTS) as container:
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
        with av.open(path, **OPEN_OPTS) as container:
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
        with av.open(path, **OPEN_OPTS) as container:
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


#: Video preset for the WebM/VP9 mobile build (the ffmpeg CLI recipe).
VIDEO_PRESET = {"b:v": "0", "row-mt": "1", "deadline": "good"}
OPUS_RATE = 48000
OPUS_BITRATE = 96000


def transcode_to_webm(src_path, dst_path, crf=32, cpu_used=4,
                      audio_rate=OPUS_RATE, audio_bitrate=OPUS_BITRATE):
    """Re-encode `src_path` into a VP9 + Opus WebM at `dst_path`, in-process.

    Replaces the ffmpeg CLI invocation (``-c:v libvpx-vp9 -crf N -b:v 0
    -row-mt 1 -cpu-used N -deadline good -c:a libopus -b:a 96k -ac 2 -f
    webm``): PyAV ships libvpx-vp9 and libopus, so no external process is
    involved.  Measured on the project's own .wmv samples against the CLI
    output at the same settings:

        sample        frames / last ts    audio samples   luma PSNR vs source
        100 MB/106 s  3188 / 106.340 s    identical       cli 40.6 / pyav 40.9 dB
        7.8 MB/7.9 s  224  / 7.441 s      identical       cli 42.0 / pyav 41.9 dB
        10.5 MB/10 s  300  / 9.977 s      identical       cli 42.7 / pyav 42.4 dB

    Identical frame count, identical last timestamp, identical audio sample
    count, PSNR within +-0.3 dB.  Known trade-off: the **video bitstream is
    ~6% larger** than the CLI's at the same settings (1651 kB vs 1560 kB on
    the 7.9 s sample; every libvpx option combination that was tried lands
    there).  ``cpu_used=0`` is the only variant that came out smaller than
    the CLI (~3x the encode time), so pass a lower `cpu_used` or a higher
    `crf` when size matters more than encoding time.
    """
    av = _av()
    with av.open(str(src_path), **OPEN_OPTS) as src, \
            av.open(str(dst_path), "w", format="webm") as dst:
        vsrc = next((s for s in src.streams if s.type == "video"), None)
        if vsrc is None:
            raise ValueError("no video stream in %s" % src_path)
        asrc = next((s for s in src.streams if s.type == "audio"), None)

        vout = dst.add_stream("libvpx-vp9", rate=vsrc.average_rate or 30)
        vout.width = vsrc.codec_context.width
        vout.height = vsrc.codec_context.height
        vout.pix_fmt = "yuv420p"
        options = dict(VIDEO_PRESET)
        options["crf"] = str(crf)
        options["cpu-used"] = str(cpu_used)
        vout.options = options

        aout = resampler = None
        if asrc is not None:
            aout = dst.add_stream("libopus", rate=audio_rate)
            aout.bit_rate = audio_bitrate
            aout.layout = "stereo"
            resampler = av.AudioResampler(format="s16", layout="stereo",
                                          rate=audio_rate)

        for packet in src.demux():
            if packet.stream is vsrc:
                for frame in packet.decode():
                    for out_packet in vout.encode(frame):
                        dst.mux(out_packet)
            elif aout is not None and packet.stream is asrc:
                for frame in packet.decode():
                    for resampled in resampler.resample(frame):
                        # Resampled frames still carry the SOURCE time base:
                        # let the encoder number them (the CLI does the same
                        # when it inserts its own audio fifo).
                        resampled.pts = None
                        for out_packet in aout.encode(resampled):
                            dst.mux(out_packet)
        for out_packet in vout.encode(None):
            dst.mux(out_packet)
        if aout is not None:
            for resampled in resampler.resample(None):
                resampled.pts = None
                for out_packet in aout.encode(resampled):
                    dst.mux(out_packet)
            for out_packet in aout.encode(None):
                dst.mux(out_packet)
    log.info("transcoded %s -> %s (crf=%s, cpu-used=%s)",
             os.path.basename(src_path), os.path.basename(dst_path), crf,
             cpu_used)
    return dst_path
