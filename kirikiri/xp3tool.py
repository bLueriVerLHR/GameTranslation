#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""krkrz XP3 archive tool - list and extract KiriKiri game archives.

Handles the standard krkrz container: zlib-compressed or raw index blocks,
0x80 indirect index pointers, raw/zlib file segments.  Byte-level parsing
was proven against real games (see docs/kirikiri.md); keep it conservative.

Some commercial releases ship *protected* archives (entry names replaced by a
running sequence with no extension, payloads opaque).  The engine that reads
them has a matching loader, so the game runs, but unpacking yields anonymous
blobs: the tool refuses those instead of producing unusable output (see
`protected_variant_reason`).

Usage:
    python3 kirikiri/xp3tool.py list <game>.xp3
    python3 kirikiri/xp3tool.py extract <game>.xp3 <out_dir>
"""

import logging
import os
import re
import struct
import sys
import zlib
from typing import Annotated

import typer

_HERE = os.path.dirname(os.path.abspath(__file__))
# Repo root, appended (not inserted) so a same-named sibling module in
# this directory still wins; the toolkit import below only needs the package
# marker plus stdlib for cliutil/logsetup.
sys.path.append(os.path.dirname(_HERE))
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("xp3tool")

MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"

INDEX_ENCODE_MASK = 0x07
INDEX_RAW = 0
INDEX_ZLIB = 1
INDEX_CONTINUE = 0x80

CH_FILE = b"File"
CH_INFO = b"info"
CH_SEGM = b"segm"
# Adler-32 of the uncompressed entry, mandatory for krkrz's loader (see
# parse_index) and used as the per-file key of the extraction filter.
CH_ADLR = b"adlr"

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
    """Parse one index block into entries: [{"name", "segments", "adler"}].

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

        # 'adlr' sub-chunk: Adler-32 of the uncompressed entry.  krkrz's
        # loader (tTVPXP3Archive::LoadIndex) throws TVPReadError when it is
        # missing, so an archive without it never loads - the engine reports
        # that as "Script exception raised / Read error".  The value is also
        # handed to the game's extraction filter as the per-file key.
        adler = None
        try:
            adlr_start, adlr_size = find_chunk(buf, file_start, file_size,
                                              CH_ADLR)
            if adlr_size >= 4:
                adler = _u32(buf, adlr_start) & 0xFFFFFFFF
        except Xp3Error:
            log.warning("index block 0x%x: entry %r has no 'adlr' sub-chunk "
                        "(Adler-32); the krkrz loader rejects such an archive",
                        block_ofs, name)
        entries.append({"name": name, "segments": segments, "adler": adler})
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


# ---------------------------------------------------------------------------
# Usability check: protected / obfuscated variants
# ---------------------------------------------------------------------------
# Some commercial releases ship archives whose entry names carry no extension
# at all (a running sequence of private-use characters) and whose payloads are
# opaque.  The engine that reads them has a matching loader, so the *game* runs
# fine, but unpacking yields anonymous blobs: useless as a conversion input.
# Detection is two-stage on purpose - a cheap name scan, then a payload probe
# that can clear a false alarm - so archives with unusual but real names
# (Japanese file names are normal) are never refused.

_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_MIN_ENTRIES_FOR_RATIO = 20
_NAME_RATIO_FLOOR = 0.05
_PROBE_LIMIT = 8
_PROBE_MAX_BYTES = 1 << 20
_TEXT_SNIFF = 512
_MAGICS = (b"\x89PNG", b"\xff\xd8\xff", b"OggS", b"RIFF", b"BM",
           b"\x1f\x8b", b"PK\x03\x04", b"PSB", b"TJS", b"XP3")


def has_file_extension(name):
    """True when the entry name ends in a plausible file extension."""
    return bool(_EXT_RE.search(name))


def name_extension_ratio(entries):
    """Fraction of entries whose name carries a file extension."""
    if not entries:
        return 1.0
    return sum(1 for e in entries
               if has_file_extension(e["name"])) / float(len(entries))


def payload_is_recognizable(data):
    """True for a known magic, a zlib stream, or text that is provably text."""
    if not data:
        return True                     # empty files are normal
    if any(data.startswith(m) for m in _MAGICS):
        return True
    try:
        zlib.decompress(data)
        return True
    except zlib.error:
        pass
    # Only strict UTF-8 with a healthy share of ASCII counts as text: a
    # single-byte decode is *not* usable evidence, because cp932 maps almost
    # every byte value to a printable character, so ciphertext "decodes"
    # cleanly (measured on a name-obfuscated archive whose blobs passed the
    # old cp932 sniff).
    head = data[:_TEXT_SNIFF]
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if not text:
        return False
    printable = sum(c.isprintable() or c in "\r\n\t" for c in text)
    ascii_printable = sum(1 for c in text
                          if c.isascii() and (c.isprintable()
                                              or c in "\r\n\t"))
    return (printable >= len(text) * 0.95
            and ascii_printable >= len(text) * 0.2)


def probe_payloads(path, entries, limit=_PROBE_LIMIT):
    """Extract up to `limit` small entries; return (checked, recognizable)."""
    small = sorted((e for e in entries if entry_size(e) <= _PROBE_MAX_BYTES),
                   key=entry_size)
    checked = known = 0
    with open(path, "rb") as f:
        for e in small[:limit]:
            try:
                data = b"".join(extract_segment(f, e["name"], *seg)
                                for seg in e["segments"])
            except (Xp3Error, OSError, zlib.error) as exc:
                log.debug("%s: probe of %r failed (%s)", path, e["name"], exc)
                continue
            checked += 1
            if payload_is_recognizable(data):
                known += 1
    return checked, known


def protected_variant_reason(path, entries=None):
    """Explain why the archive is unusable, or None when it looks fine."""
    if entries is None:
        entries = open_xp3(path)
    if len(entries) < _MIN_ENTRIES_FOR_RATIO:
        return None
    if name_extension_ratio(entries) >= _NAME_RATIO_FLOOR:
        return None
    checked, known = probe_payloads(path, entries)
    if known or not checked:
        return None
    nameless = sum(1 for e in entries if not has_file_extension(e["name"]))
    return ("%s: refusing to unpack - this archive looks like a protected "
            "variant: %d of %d entry names carry no file extension and none "
            "of the %d probed payloads shows a recognizable file signature or "
            "text.  Its contents are opaque, so it cannot be used as a "
            "conversion input.  Use an unencrypted copy of the game, or pass "
            "--force to inspect it anyway."
            % (path, nameless, len(entries), checked))


def cmd_list(xp3: Annotated[str, cliutil.Argument(help="xp3 archive")],
             force: Annotated[bool, typer.Option(
                 "--force",
                 help="unpack even when the archive looks protected")] = False,
             verbose: cliutil.Verbose = False,
             quiet: cliutil.Quiet = False,
             log_file: cliutil.LogFile = None) -> int:
    """List the entries of an xp3 archive."""
    cliutil.setup_logging(verbose, quiet, log_file)
    code = _gate(xp3, force)
    if code is not None:
        return code
    return _guarded(list_entries, xp3)


def cmd_extract(xp3: Annotated[str, cliutil.Argument(help="xp3 archive")],
                outdir: Annotated[str, cliutil.Argument(help="output directory")],
                force: Annotated[bool, typer.Option(
                    "--force",
                    help="unpack even when the archive looks protected")] = False,
                verbose: cliutil.Verbose = False,
                quiet: cliutil.Quiet = False,
                log_file: cliutil.LogFile = None) -> int:
    """Extract every entry of an xp3 archive."""
    cliutil.setup_logging(verbose, quiet, log_file)
    code = _gate(xp3, force)
    if code is not None:
        return code
    return _guarded(extract_all, xp3, outdir)


def _gate(xp3, force):
    """Return an exit code when this archive must not be unpacked."""
    if force or not os.path.isfile(xp3):
        return None
    try:
        reason = protected_variant_reason(xp3)
    except (Xp3Error, OSError, zlib.error) as exc:
        log.debug("%s: usability check skipped (%s)", xp3, exc)
        return None
    if reason is None:
        return None
    log.error("%s", reason)
    return 1


def _guarded(action, *action_args):
    """Run an archive operation, turning a bad archive into exit code 1."""
    try:
        action(*action_args)
    except (Xp3Error, OSError, zlib.error) as exc:
        log.error("%s", exc)
        return 1
    return 0


app = cliutil.app(help=__doc__)
app.command(name="list")(cmd_list)
app.command(name="extract")(cmd_extract)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="xp3tool.py")


if __name__ == "__main__":
    raise SystemExit(main())
