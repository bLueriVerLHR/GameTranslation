#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""krkrz XP3 archive tool - list and extract KiriKiri game archives.

Handles the standard krkrz container: zlib-compressed or raw index blocks,
0x80 indirect index pointers, raw/zlib file segments.  Byte-level parsing
was proven against real games (see docs/kirikiri.md); keep it conservative.

Usage:
    python3 kirikiri/xp3tool.py list <game>.xp3
    python3 kirikiri/xp3tool.py extract <game>.xp3 <out_dir>
"""

import argparse
import logging
import os
import struct
import zlib

log = logging.getLogger("xp3tool")

MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"

INDEX_ENCODE_MASK = 0x07
INDEX_RAW = 0
INDEX_ZLIB = 1
INDEX_CONTINUE = 0x80

CH_FILE = b"File"
CH_INFO = b"info"
CH_SEGM = b"segm"

SEGM_ENCODE_MASK = 0x07
SEGM_RAW = 0
SEGM_ZLIB = 1


class Xp3Error(Exception):
    """Raised on structural problems; message always locates the offset."""


def _i64(f):
    return struct.unpack("<q", f.read(8))[0]


def _u32(buf, pos):
    return struct.unpack("<I", buf[pos : pos + 4])[0]


def _i64_at(buf, pos):
    return struct.unpack("<q", buf[pos : pos + 8])[0]


def _i16(buf, pos):
    return struct.unpack("<h", buf[pos : pos + 2])[0]


def resolve_index_offset(f, index_ofs):
    """0x80 blocks are indirect: the first 4 bytes are a marker and the
    real pointer lives at +9."""
    f.seek(index_ofs)
    if f.read(4) == b"\x80\x00\x00\x00":
        old = index_ofs
        f.seek(old + 9)
        index_ofs = _i64(f)
        log.debug("index 0x%x redirected to 0x%x", old, index_ofs)
    return index_ofs


def read_index_block(f, index_ofs):
    """Return (flag, raw index bytes)."""
    f.seek(index_ofs)
    flag = f.read(1)[0]
    method = flag & INDEX_ENCODE_MASK
    if method == INDEX_ZLIB:
        csize = _i64(f)
        usize = _i64(f)
        data = zlib.decompress(f.read(csize))
        if len(data) != usize:
            raise Xp3Error("index 0x%x: decompressed %d != declared %d"
                           % (index_ofs, len(data), usize))
        return flag, data
    if method == INDEX_RAW:
        usize = _i64(f)
        return flag, f.read(usize)
    raise Xp3Error("index 0x%x: unknown encode method 0x%02x"
                   % (index_ofs, method))


def find_chunk(buf, start, size, magic):
    """Locate a sub-chunk inside an index chunk; returns (data_ofs, size)."""
    pos = start
    end = start + size
    while pos + 12 <= end:
        if buf[pos : pos + 4] == magic:
            return pos + 12, _i64_at(buf, pos + 4)
        pos += 12 + _i64_at(buf, pos + 4)
    raise Xp3Error("chunk %r not found between 0x%x..0x%x"
                   % (magic, start, end))


def parse_index(buf, block_ofs):
    """Parse one index block into entries: [{"name", "segments"}].

    segments: list of (start, arc, org, compressed) tuples.
    """
    entries = []
    pos = 0
    while pos < len(buf):
        file_start, file_size = find_chunk(buf, pos, len(buf) - pos, CH_FILE)
        info_start, _ = find_chunk(buf, file_start, file_size, CH_INFO)
        nlen = _i16(buf, info_start + 20)
        name = buf[info_start + 22 : info_start + 22 + nlen * 2]
        try:
            name = name.decode("utf-16-le").replace("\\", "/")
        except UnicodeDecodeError as exc:
            log.warning("block 0x%x: undecodable entry name, skipped (%s)",
                        block_ofs, exc)
            pos = file_start + file_size
            continue
        segm_start, segm_size = find_chunk(buf, file_start, file_size, CH_SEGM)
        segments = []
        for i in range(segm_size // 28):
            base = segm_start + i * 28
            sflags = _u32(buf, base)
            start = _i64_at(buf, base + 4)
            org = _i64_at(buf, base + 12)
            arc = _i64_at(buf, base + 20)
            method = sflags & SEGM_ENCODE_MASK
            if method == SEGM_RAW:
                compressed = False
            elif method == SEGM_ZLIB:
                compressed = True
            else:
                raise Xp3Error("entry %r: unknown segment method 0x%02x"
                               % (name, method))
            segments.append((start, arc, org, compressed))
        entries.append({"name": name, "segments": segments})
        pos = file_start + file_size
    return entries


def open_xp3(path):
    """Open an archive and return all entries in index order."""
    entries = []
    with open(path, "rb") as f:
        if f.read(11) != MAGIC:
            raise Xp3Error("%s: not a krkrz XP3 archive (bad magic)"
                           % path)
        pointer = 11
        block = 0
        while True:
            f.seek(pointer)
            index_ofs = _i64(f)
            pointer += 8
            index_ofs = resolve_index_offset(f, index_ofs)
            log.debug("%s: index block %d at 0x%x", path, block, index_ofs)
            flag, buf = read_index_block(f, index_ofs)
            entries.extend(parse_index(buf, index_ofs))
            block += 1
            if not (flag & INDEX_CONTINUE):
                break
    return entries


def entry_size(entry):
    return sum(s[2] for s in entry["segments"])


def list_entries(path):
    entries = open_xp3(path)
    total = 0
    for e in entries:
        size = entry_size(e)
        total += size
        print("%14d  %s" % (size, e["name"]))
    log.info("%s: %d entries, %d bytes", path, len(entries), total)
    return len(entries), total


def extract_segment(f, name, start, arc, org, compressed):
    f.seek(start)
    data = f.read(arc)
    if compressed:
        data = zlib.decompress(data)
        if len(data) != org:
            raise Xp3Error("entry %r: size mismatch after decompression "
                           "(%d != %d)" % (name, len(data), org))
    return data


def extract_all(path, outdir):
    entries = open_xp3(path)
    os.makedirs(outdir, exist_ok=True)
    written = 0
    total = 0
    with open(path, "rb") as f:
        for e in entries:
            dest = os.path.join(outdir, *e["name"].split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as out:
                for start, arc, org, compressed in e["segments"]:
                    out.write(extract_segment(f, e["name"],
                                              start, arc, org, compressed))
            written += 1
            total += entry_size(e)
            log.debug("extracted %s", e["name"])
    log.info("%s: extracted %d files, %d bytes into %s",
             path, written, total, outdir)
    return written, total


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("xp3")
    p_extract = sub.add_parser("extract")
    p_extract.add_argument("xp3")
    p_extract.add_argument("outdir")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.cmd == "list":
            list_entries(args.xp3)
        else:
            extract_all(args.xp3, args.outdir)
    except (Xp3Error, OSError, zlib.error) as exc:
        log.error("%s", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
