#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fake ffprobe for hermetic tests.

Behavior mirrors the real tool for the arguments the pipeline passes:
  ffprobe -v error -print_format json -show_entries
      format=duration,size,bit_rate,tags:stream=codec_name,codec_type,channels,sample_rate
      <path>

The reported bit_rate is derived from the file size so the pipeline's
bitrate_calc() reproduces it.  Set FAKE_HIGH_BITRATE=1 to force a high
bitrate (triggers re-encoding); a missing input file exits 1 like the real
ffprobe.
"""
import json
import os
import sys


def main():
    path = sys.argv[-1]
    if not os.path.isfile(path):
        print("ffprobe: no such file: %s" % path, file=sys.stderr)
        return 1
    size = os.path.getsize(path)
    # base duration makes bit_rate == exactly the mono/stereo thresholds
    # (files then "keep"); FAKE_HIGH_BITRATE shrinks the duration so the
    # recomputed bit_rate exceeds the thresholds and triggers re-encoding.
    divisor = 40000 if os.environ.get("FAKE_HIGH_BITRATE") == "1" else 8000
    duration = max(1.5, size / divisor)
    bit_rate = int(size * 8 / duration)
    base = os.path.basename(path)
    channels = 1 if "mono" in base else 2
    codec = "vorbis"
    if "m4a" in base:
        codec = "aac"
    out = {
        "format": {
            "duration": "%.3f" % duration,
            "size": str(size),
            "bit_rate": str(bit_rate),
            "tags": {},
        },
        "streams": [
            {"codec_name": codec, "codec_type": "audio",
             "channels": channels, "sample_rate": "44100"}
        ],
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
