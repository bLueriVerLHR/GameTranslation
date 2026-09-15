#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a krkrz XP3 archive (e.g. patch.xp3) from a directory tree.

Packs every file under <in_dir> (relative paths, forward slashes) into a
single-index XP3 with raw (uncompressed) segments and a zlib-compressed
index.  This is the standard delivery of a KiriKiri translation: drop the
resulting patch.xp3 next to the game executable - the engine overlays
patch archives on top of the base ones, so the original data.xp3 is never
touched.

The archive is verified by re-reading it with the xp3tool parser and
comparing file names and sizes.

Usage:
    python3 kirikiri/xp3pack.py <in_dir> <out.xp3>
"""

import logging
import os
import struct
import sys
import zlib
from typing import Annotated


_HERE = os.path.dirname(os.path.abspath(__file__))
# Repo root, appended (not inserted) so a same-named sibling module in
# this directory still wins.
sys.path.append(os.path.dirname(_HERE))
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("xp3pack")

MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"
INDEX_ZLIB = 0x01

HEADER_SIZE = 11
PTR_SIZE = 8


class Xp3PackError(Exception):
    pass


def collect_files(in_dir):
    """All files under in_dir as (rel_path, abs_path) pairs, sorted."""
    files = []
    for root, dirs, names in os.walk(in_dir):
        dirs.sort()
        for fn in sorted(names):
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, in_dir).replace(os.sep, "/")
            files.append((rel, full))
    return files


def build_index(entries):
    """Index block bytes for [(name, start, size)]; one raw segment each."""
    out = bytearray()
    for name, start, size in entries:
        name_bytes = name.encode("utf-16-le")
        info = struct.pack("<IQQH", 0, size, 0, len(name)) + name_bytes
        segm = struct.pack("<IQqQ", 0, start, size, size)
        file_chunk = (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm))
                      + b"info" + struct.pack("<q", len(info)) + info
                      + b"segm" + struct.pack("<q", len(segm)) + segm)
        out += file_chunk
    return bytes(out)


def pack(in_dir, out_path, zlib_level=9):
    files = collect_files(in_dir)
    if not files:
        raise Xp3PackError("nothing to pack in %s" % in_dir)

    entries = []
    with open(out_path, "wb") as out:
        out.write(MAGIC)
        out.write(struct.pack("<q", 0))  # index pointer, patched below
        ofs = HEADER_SIZE + PTR_SIZE
        for rel, full in files:
            size = os.path.getsize(full)
            with open(full, "rb") as src:
                out.write(src.read())
            entries.append((rel, ofs, size))
            ofs += size

        index_ofs = ofs
        out.seek(HEADER_SIZE)
        out.write(struct.pack("<q", index_ofs))
        out.seek(0, os.SEEK_END)

        raw_index = build_index(entries)
        compressed = zlib.compress(raw_index, zlib_level)
        out.write(bytes([INDEX_ZLIB]))
        out.write(struct.pack("<qq", len(compressed), len(raw_index)))
        out.write(compressed)
    return files, ofs


def verify(out_path, files):
    """Self-check: re-read the archive with the xp3tool parser."""
    # Import the sibling module through the package so this works both as
    # `kirikiri.xp3pack` and as a script; a bare `from xp3tool import ...` only
    # worked when kirikiri/ itself was on sys.path, which shadowed the repo-root
    # modules (kirikiri/ has pipeline.py) for everything imported afterwards.
    try:
        from kirikiri.xp3tool import entry_size, open_xp3
    except ImportError:                # run directly: python kirikiri/xp3pack.py
        from xp3tool import entry_size, open_xp3

    parsed = {e["name"]: entry_size(e) for e in open_xp3(out_path)}
    expected = {rel: os.path.getsize(full) for rel, full in files}
    if parsed != expected:
        missing = sorted(set(expected) - set(parsed))
        extra = sorted(set(parsed) - set(expected))
        resized = sorted(n for n in set(parsed) & set(expected)
                         if parsed[n] != expected[n])
        raise Xp3PackError("verify failed: missing=%r extra=%r resized=%r"
                           % (missing[:5], extra[:5], resized[:5]))
    log.info("%s: verified %d entries, %d bytes",
             out_path, len(parsed), sum(parsed.values()))
    return len(parsed)


def cmd(in_dir: Annotated[str, cliutil.Argument(help="directory to pack")],
        out_xp3: Annotated[str, cliutil.Argument(help="output .xp3 archive")],
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Pack a directory into an xp3 archive (self-verified after writing)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    try:
        files, total = pack(in_dir, out_xp3)
        log.info("%s: packed %d files, %d bytes payload",
                 out_xp3, len(files), total)
        verify(out_xp3, files)
    except (Xp3PackError, OSError, zlib.error) as exc:
        log.error("%s", exc)
        return 1
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="xp3pack.py")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main())
