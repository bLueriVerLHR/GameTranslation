#!/usr/bin/env python3
"""Fake ffmpeg for hermetic tests.

Decode mode (verify --decode): args end with `-f null -` -> exit 0 silently.
Transcode mode: find `-i <input>`; the LAST argument is the output path.
Writes a copy of the input (so "no smaller" == no-gain) unless
FAKE_SMALL_OUTPUT=1, which halves the payload (the pipeline then replaces
the original -> status "reencoded").
"""
import os
import sys


def main():
    args = sys.argv[1:]
    if "-f" in args and "null" in args:
        return 0
    inp = None
    for i, a in enumerate(args):
        if a == "-i" and i + 1 < len(args):
            inp = args[i + 1]
    out = args[-1] if args else ""
    if not out:
        print("ffmpeg: no output argument", file=sys.stderr)
        return 1
    data = b""
    if inp and os.path.isfile(inp):
        with open(inp, "rb") as f:
            data = f.read()
    if os.environ.get("FAKE_SMALL_OUTPUT") == "1" and len(data) > 8:
        data = data[: len(data) // 2]
    with open(out, "wb") as f:
        f.write(data or b"FAKE-OUTPUT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
