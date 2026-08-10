#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fake 7z for hermetic tests.

Commands the pipeline uses:
  7z a -t7z -m0=zstd -mx=N [-mmt=...] <archive> <folder>  -> create the file
  7z t <archive>                                          -> integrity test
  7z x -y <archive> -o<dest> <entry-name>                 -> extract

The archive created here is a stub (not a real 7z) - enough for the
pipeline's copy/test/extract flow.
"""
import os
import sys


def main():
    args = sys.argv[1:]
    if not args:
        print("7z: no arguments", file=sys.stderr)
        return 1
    cmd = args[0]
    if cmd == "a":
        archive = next((a for a in args[1:] if not a.startswith("-")), None)
        if not archive:
            print("7z a: no archive path", file=sys.stderr)
            return 1
        with open(archive, "wb") as f:
            f.write(b"FAKE-7Z-ARCHIVE\n")
        print("Everything is Ok")
        return 0
    if cmd == "t":
        print("Everything is Ok")
        return 0
    if cmd == "x":
        dest = None
        for a in args[1:]:
            if a.startswith("-o"):
                dest = a[2:]
        name = args[-1]
        os.makedirs(os.path.join(dest or ".", name), exist_ok=True)
        print("Everything is Ok")
        return 0
    print("7z: unknown command %s" % cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
