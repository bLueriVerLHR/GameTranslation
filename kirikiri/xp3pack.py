#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a krkrz XP3 archive (e.g. patch.xp3) from a directory tree.

Packs every file under <in_dir> (relative paths, forward slashes) into a
single-index XP3 with raw (uncompressed) segments and a zlib-compressed
index.  This is the standard delivery of a KiriKiri translation: drop the
resulting patch.xp3 next to the game executable - the engine overlays
patch archives on top of the base ones, so the original data.xp3 is never
touched.

Container details that the engine actually enforces (verified against
krkrz's tTVPXP3Archive::LoadIndex and against a real game):

  * every File chunk needs an 'info', a 'segm' AND an 'adlr' sub-chunk;
    'adlr' holds the Adler-32 of the uncompressed content.  Without it the
    loader throws TVPReadError, which KAG shows as "Script exception
    raised / Read error" before a single script runs.
  * patch entries are looked up by *name*, so an archive whose payload sits
    at the root is what the engine finds by default (folder structure
    inside a patch archive is ignored unless a patch-supplied Config.tjs
    registers it).

The archive is verified by re-reading it with the xp3tool parser and
comparing file names, sizes and Adler-32 hashes.

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

# Every File chunk must carry an 'adlr' sub-chunk holding the Adler-32 of the
# entry's *uncompressed* content.  krkrz's loader requires it unconditionally
# (tTVPXP3Archive::LoadIndex throws TVPReadError without it) and hands the
# value to the game's extraction filter as the per-file key.  A patch archive
# written without it makes the engine fail at startup with "Script exception
# raised / Read error" - the game never even gets to load a script.
CH_ADLR = b"adlr"

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


def adler32_stream(path, chunk_size=1 << 20):
    """Adler-32 of a file's whole content, read in chunks."""
    adler = 1
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            adler = zlib.adler32(chunk, adler)
    return adler & 0xFFFFFFFF


def build_index(entries):
    """Index block bytes for [(name, start, size, adler)]; one raw segment each.

    Each File chunk holds 'info' (flags, org size, arc size, UTF-16LE name),
    'segm' (one raw segment) and 'adlr' (the Adler-32) - in that order, which
    is what real games' archives carry.
    """
    out = bytearray()
    for name, start, size, adler in entries:
        name_bytes = name.encode("utf-16-le")
        info = struct.pack("<IQQH", 0, size, size, len(name)) + name_bytes
        segm = struct.pack("<IQqQ", 0, start, size, size)
        adlr = struct.pack("<I", adler & 0xFFFFFFFF)
        file_chunk = (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm)
                                            + 12 + len(adlr))
                      + b"info" + struct.pack("<q", len(info)) + info
                      + b"segm" + struct.pack("<q", len(segm)) + segm
                      + CH_ADLR + struct.pack("<q", len(adlr)) + adlr)
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
            adler = 1
            with open(full, "rb") as src:
                # streamed so a large payload is never held in memory, and
                # the Adler-32 is computed while copying (adler32 is
                # incremental, so chunked == whole-file)
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    adler = zlib.adler32(chunk, adler)
            entries.append((rel, ofs, size, adler & 0xFFFFFFFF))
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
    """Self-check: re-read the archive with the xp3tool parser.

    Beyond names and sizes this also checks the Adler-32 of every entry
    against the source file, because a missing or wrong 'adlr' sub-chunk is
    a hard load failure on the engine side while being invisible to a size
    comparison alone.
    """
    # Import the sibling module through the package so this works both as
    # `kirikiri.xp3pack` and as a script; a bare `from xp3tool import ...` only
    # worked when kirikiri/ itself was on sys.path, which shadowed the repo-root
    # modules (kirikiri/ has pipeline.py) for everything imported afterwards.
    try:
        from kirikiri.xp3tool import entry_size, open_xp3
    except ImportError:                # run directly: python kirikiri/xp3pack.py
        from xp3tool import entry_size, open_xp3

    entries = open_xp3(out_path)
    parsed = {e["name"]: entry_size(e) for e in entries}
    expected = {rel: os.path.getsize(full) for rel, full in files}
    if parsed != expected:
        missing = sorted(set(expected) - set(parsed))
        extra = sorted(set(parsed) - set(expected))
        resized = sorted(n for n in set(parsed) & set(expected)
                         if parsed[n] != expected[n])
        raise Xp3PackError("verify failed: missing=%r extra=%r resized=%r"
                           % (missing[:5], extra[:5], resized[:5]))

    want = {rel: adler32_stream(full) for rel, full in files}
    got = {e["name"]: e.get("adler") for e in entries}
    no_hash = sorted(n for n in got if got[n] is None)
    bad_hash = sorted(n for n in got
                      if got[n] is not None and got[n] != want[n])
    if no_hash or bad_hash:
        raise Xp3PackError(
            "verify failed: no 'adlr' sub-chunk for %r, wrong Adler-32 for %r "
            "(krkrz refuses to load such an archive)"
            % (no_hash[:5], bad_hash[:5]))

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
