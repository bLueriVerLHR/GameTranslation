#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fake Windows PowerShell for wsl_capture tests.

Parses the arguments the capture wrapper passes (-OutDir / -Out), creates the
output PNG and prints its Windows-form path.  FAKE_PS_FAIL simulates a failing
capture (target window not found); FAKE_PS_EXIT overrides the exit code.

Written in Python (not bash) so the same fake works on Windows and POSIX: the
test harness wraps it in a platform-appropriate launcher.
"""
import os
import sys

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def main(argv):
    outdir = ""
    out = ""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "-OutDir" and i + 1 < len(argv):
            outdir = argv[i + 1]
            i += 2
        elif a == "-Out" and i + 1 < len(argv):
            out = argv[i + 1]
            i += 2
        else:
            i += 1
    if os.environ.get("FAKE_PS_FAIL"):
        print("fake powershell failure: %s" % os.environ["FAKE_PS_FAIL"],
              file=sys.stderr)
        return int(os.environ.get("FAKE_PS_EXIT", "1"))
    outdir = outdir or "."
    out = out or "fake.png"
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, out), "wb") as f:
        f.write(PNG_MAGIC)
    print("%s/%s" % (outdir, out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
