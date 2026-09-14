#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for kirikiri/xp3tool.py - the krkrz XP3 archive unpacker.

All archives are built from scratch at the byte level so the suite is fully
hermetic: no external XP3 tooling and no game fixtures are required.  The
builders mirror the exact on-disk layout xp3tool parses (11-byte magic, an
index pointer table, raw/zlib index blocks, File/info/segm sub-chunks),
which was cross-checked against the packer in kirikiri/xp3pack.py.

Positive / negative / edge coverage:
  - positive: raw and zlib segments, multi-segment entries, UTF-16LE
    filenames, raw and zlib index blocks, multi-block (0x80 continue) and
    0x80 indirect indexes, full extract round-trips.
  - negative: bad magic, truncated files, unknown encode/segment methods,
    decompressed-size mismatches.
  - edge: zero-byte files, nested paths, backslash name normalization,
    undecodable names (skipped with a warning).
"""

import logging
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kirikiri import xp3tool  # noqa: E402

MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"


# ---------------------------------------------------------------------------
# Byte-level builders (mirror xp3pack.build_index + pack layout)
# ---------------------------------------------------------------------------

def build_file_chunk(name, segments):
    """One File sub-chunk. segments = [(start, org, arc, compressed)]."""
    name_bytes = name.encode("utf-16-le")
    total = sum(org for _start, org, _arc, _comp in segments)
    info = struct.pack("<IQQH", 0, total, 0, len(name)) + name_bytes
    segm = b"".join(
        struct.pack("<IQqQ", 1 if comp else 0, start, org, arc)
        for start, org, arc, comp in segments)
    return (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm))
            + b"info" + struct.pack("<q", len(info)) + info
            + b"segm" + struct.pack("<q", len(segm)) + segm)


def build_index(entries, compress=True, continue_flag=False, raw=False):
    """Index block bytes. entries = [(name, segments)]."""
    raw_bytes = b"".join(build_file_chunk(n, s) for n, s in entries)
    flag = 0x80 if continue_flag else 0
    if raw:
        return bytes([flag]) + struct.pack("<q", len(raw_bytes)) + raw_bytes
    comp = zlib.compress(raw_bytes)
    return (bytes([flag | 0x01])
            + struct.pack("<qq", len(comp), len(raw_bytes)) + comp)


def make_archive(files, zlib_segments=(), index_compress=True, index_raw=False):
    """Single-index archive. files = [(name, content)].  zlib_segments is a
    set of names whose payload is stored zlib-compressed."""
    payload = bytearray()
    entries = []
    ofs = 19  # 11-byte magic + 8-byte index pointer
    for name, content in files:
        if name in zlib_segments:
            stored = zlib.compress(content)
            seg = (ofs, len(content), len(stored), True)
        else:
            stored = content
            seg = (ofs, len(content), len(content), False)
        payload += stored
        entries.append((name, [seg]))
        ofs += len(stored)
    block = build_index(entries, compress=index_compress, raw=index_raw)
    return MAGIC + struct.pack("<q", ofs) + bytes(payload) + block


def make_named_archive(name, content):
    """Single-entry archive with an arbitrary (raw) file name."""
    seg = (19, len(content), len(content), False)
    raw = build_file_chunk(name, [seg])
    comp = zlib.compress(raw)
    block = bytes([0x01]) + struct.pack("<qq", len(comp), len(raw)) + comp
    return MAGIC + struct.pack("<q", 19 + len(content)) + content + block


def make_broken_index_archive(flag_byte, csize, usize, data):
    """Archive whose single index block has the given flag and (csize, usize)."""
    block = bytes([flag_byte]) + struct.pack("<qq", csize, usize) + data
    return MAGIC + struct.pack("<q", 19) + block


def make_multi_block_archive(files, nblocks=2):
    """files split across nblocks index blocks; all but the last carry the
    0x80 continue flag (the krkrz layout for an index too large for one
    block)."""
    payload = bytearray()
    entries = []
    ofs = 11 + 8 * nblocks  # pointer table region
    for name, content in files:
        payload += content
        entries.append((name, [(ofs, len(content), len(content), False)]))
        ofs += len(content)
    per = (len(entries) + nblocks - 1) // nblocks
    chunks = [entries[i * per:(i + 1) * per] for i in range(nblocks)]
    chunks = [c for c in chunks if c]
    blocks = [build_index(c, continue_flag=(i != len(chunks) - 1))
              for i, c in enumerate(chunks)]
    ptrs = []
    body = bytearray()
    cursor = ofs
    for b in blocks:
        ptrs.append(cursor)
        body += b
        cursor += len(b)
    ptr_tab = struct.pack("<" + "q" * len(ptrs), *ptrs)
    return MAGIC + ptr_tab + bytes(payload) + bytes(body)


def make_indirect_archive(files):
    """Index pointer targets a 0x80 indirect stub; the real block pointer
    lives at stub+9 (krkrz large-index indirection)."""
    payload = bytearray()
    entries = []
    ofs = 19
    for name, content in files:
        payload += content
        entries.append((name, [(ofs, len(content), len(content), False)]))
        ofs += len(content)
    stub_ofs = ofs
    real_ofs = stub_ofs + 17  # 4 marker + 5 pad + 8-byte pointer
    stub = b"\x80\x00\x00\x00" + b"\x00" * 5 + struct.pack("<q", real_ofs)
    block = build_index(entries)
    return MAGIC + struct.pack("<q", stub_ofs) + bytes(payload) + stub + block


def make_multi_segment_archive(parts):
    """Single entry 'multi.bin' split into several segments.
    parts = [(content, compressed)]."""
    payload = bytearray()
    segs = []
    ofs = 19
    for content, compressed in parts:
        stored = zlib.compress(content) if compressed else content
        segs.append((ofs, len(content), len(stored), compressed))
        payload += stored
        ofs += len(stored)
    block = build_index([("multi.bin", segs)])
    return MAGIC + struct.pack("<q", ofs) + bytes(payload) + block


def make_zlib_segment_mismatch_archive(name, content, fake_org):
    """Zlib segment whose declared original size (org@+12) is wrong."""
    comp = zlib.compress(content)
    info = struct.pack("<IQQH", 0, fake_org, 0, len(name)) + name.encode("utf-16-le")
    segm = struct.pack("<IQqQ", 1, 19, fake_org, len(comp))
    file_chunk = (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm))
                  + b"info" + struct.pack("<q", len(info)) + info
                  + b"segm" + struct.pack("<q", len(segm)) + segm)
    raw = file_chunk
    comp_idx = zlib.compress(raw)
    block = bytes([0x01]) + struct.pack("<qq", len(comp_idx), len(raw)) + comp_idx
    return MAGIC + struct.pack("<q", 19 + len(comp)) + comp + block


def make_unknown_segment_method_archive(name="u.bin", content=b"data"):
    """Segment whose method bits (flag & 0x07) are unsupported (0x02)."""
    info = struct.pack("<IQQH", 0, len(content), 0, len(name)) + name.encode("utf-16-le")
    segm = struct.pack("<IQqQ", 2, 19, len(content), len(content))
    file_chunk = (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm))
                  + b"info" + struct.pack("<q", len(info)) + info
                  + b"segm" + struct.pack("<q", len(segm)) + segm)
    raw = file_chunk
    comp = zlib.compress(raw)
    block = bytes([0x01]) + struct.pack("<qq", len(comp), len(raw)) + comp
    return MAGIC + struct.pack("<q", 19 + len(content)) + content + block


# ---------------------------------------------------------------------------
# Header / magic / structural rejection (negative)
# ---------------------------------------------------------------------------

class TestHeaderRejection:
    def test_bad_magic_rejected(self, tmp_path):
        p = tmp_path / "bad.xp3"
        p.write_bytes(b"NOTANXP3" + b"\x00" * 32)
        with pytest.raises(xp3tool.Xp3Error, match="bad magic"):
            xp3tool.open_xp3(str(p))

    def test_empty_file_rejected(self, tmp_path):
        p = tmp_path / "empty.xp3"
        p.write_bytes(b"")
        with pytest.raises(xp3tool.Xp3Error, match="bad magic"):
            xp3tool.open_xp3(str(p))

    def test_truncated_pointer_rejected(self, tmp_path):
        # magic is valid but the 8-byte index pointer is cut short
        p = tmp_path / "trunc.xp3"
        p.write_bytes(MAGIC + b"\x00\x00")
        with pytest.raises(struct.error):
            xp3tool.open_xp3(str(p))

    def test_unknown_index_method_rejected(self, tmp_path):
        p = tmp_path / "unk.xp3"
        p.write_bytes(make_broken_index_archive(0x02, 0, 0, b""))
        with pytest.raises(xp3tool.Xp3Error, match="unknown encode method"):
            xp3tool.open_xp3(str(p))

    def test_index_zlib_size_mismatch_rejected(self, tmp_path):
        data = b"index-data"
        comp = zlib.compress(data)
        p = tmp_path / "mm.xp3"
        p.write_bytes(make_broken_index_archive(0x01, len(comp), len(data) + 5, comp))
        with pytest.raises(xp3tool.Xp3Error, match="decompressed"):
            xp3tool.open_xp3(str(p))

    def test_index_compressed_data_truncated_rejected(self, tmp_path):
        data = b"index-data" * 3
        comp = zlib.compress(data)
        p = tmp_path / "tr.xp3"
        p.write_bytes(make_broken_index_archive(0x01, len(comp) - 4, len(data),
                                                comp[:len(comp) - 4]))
        with pytest.raises((zlib.error, xp3tool.Xp3Error)):
            xp3tool.open_xp3(str(p))


# ---------------------------------------------------------------------------
# Index block reading
# ---------------------------------------------------------------------------

class TestIndexBlocks:
    def test_zlib_index_block(self, tmp_path):
        data = b"idx-data" * 3
        comp = zlib.compress(data)
        p = tmp_path / "i.bin"
        p.write_bytes(bytes([0x01]) + struct.pack("<qq", len(comp), len(data)) + comp)
        with p.open("rb") as f:
            flag, buf = xp3tool.read_index_block(f, 0)
        assert flag == 0x01
        assert buf == data

    def test_raw_index_block(self, tmp_path):
        data = b"raw-index-bytes"
        p = tmp_path / "i.bin"
        p.write_bytes(bytes([0x00]) + struct.pack("<q", len(data)) + data)
        with p.open("rb") as f:
            flag, buf = xp3tool.read_index_block(f, 0)
        assert flag == 0x00
        assert buf == data

    def test_raw_index_archive_parses(self, tmp_path):
        p = tmp_path / "raw.xp3"
        p.write_bytes(make_archive([("a.txt", b"hello"), ("b.bin", b"\x01\x02")],
                                   index_compress=False, index_raw=True))
        entries = xp3tool.open_xp3(str(p))
        assert [e["name"] for e in entries] == ["a.txt", "b.bin"]

    def test_read_index_block_unknown_method(self, tmp_path):
        p = tmp_path / "i.bin"
        p.write_bytes(bytes([0x02]))
        with p.open("rb") as f:
            with pytest.raises(xp3tool.Xp3Error, match="unknown encode method"):
                xp3tool.read_index_block(f, 0)

    def test_read_index_block_zlib_size_mismatch(self, tmp_path):
        data = b"data"
        comp = zlib.compress(data)
        p = tmp_path / "i.bin"
        p.write_bytes(bytes([0x01]) + struct.pack("<qq", len(comp), len(data) + 3) + comp)
        with p.open("rb") as f:
            with pytest.raises(xp3tool.Xp3Error, match="decompressed"):
                xp3tool.read_index_block(f, 0)


# ---------------------------------------------------------------------------
# 0x80 indirect / multi-block indexes
# ---------------------------------------------------------------------------

class TestZeroX80Indexes:
    def test_resolve_index_offset_marker(self, tmp_path):
        # pointer target starts with \x80\x00\x00\x00 -> follow +9
        p = tmp_path / "s.bin"
        p.write_bytes(b"\x80\x00\x00\x00" + b"\x00" * 5 + struct.pack("<q", 777))
        with p.open("rb") as f:
            assert xp3tool.resolve_index_offset(f, 0) == 777

    def test_resolve_index_offset_no_marker(self, tmp_path):
        p = tmp_path / "s.bin"
        p.write_bytes(b"ABCD")
        with p.open("rb") as f:
            assert xp3tool.resolve_index_offset(f, 0) == 0

    def test_indirect_index_archive(self, tmp_path):
        p = tmp_path / "ind.xp3"
        p.write_bytes(make_indirect_archive([("i.txt", b"indirect-data")]))
        entries = xp3tool.open_xp3(str(p))
        assert [e["name"] for e in entries] == ["i.txt"]
        out = tmp_path / "out"
        xp3tool.extract_all(str(p), str(out))
        assert (out / "i.txt").read_bytes() == b"indirect-data"

    def test_multi_block_continue(self, tmp_path):
        files = [("f%d.txt" % i, ("payload-%d-" % i).encode() * 10)
                 for i in range(6)]
        p = tmp_path / "multi.xp3"
        p.write_bytes(make_multi_block_archive(files, nblocks=3))
        entries = xp3tool.open_xp3(str(p))
        assert [e["name"] for e in entries] == [n for n, _ in files]
        out = tmp_path / "out"
        xp3tool.extract_all(str(p), str(out))
        for name, content in files:
            assert (out / name).read_bytes() == content

    def test_multi_block_single_file_per_block(self, tmp_path):
        # 3 blocks where the middle trailing split could be empty
        files = [("a.txt", b"aaa"), ("b.txt", b"bbb"), ("c.txt", b"ccc")]
        p = tmp_path / "multi.xp3"
        p.write_bytes(make_multi_block_archive(files, nblocks=3))
        entries = xp3tool.open_xp3(str(p))
        assert [e["name"] for e in entries] == ["a.txt", "b.txt", "c.txt"]


# ---------------------------------------------------------------------------
# Entry names (UTF-16LE, CJK, normalization, undecodable)
# ---------------------------------------------------------------------------

class TestEntryNames:
    def test_utf16le_unicode_names(self, tmp_path):
        files = [("scenario/名前.txt", b"a"),
                 ("台词/中文.md", b"b"),
                 ("ひらがな/かな.txt", b"c")]
        p = tmp_path / "u.xp3"
        p.write_bytes(make_archive(files))
        entries = xp3tool.open_xp3(str(p))
        assert [e["name"] for e in entries] == [n for n, _ in files]

    def test_backslash_paths_normalized(self, tmp_path):
        # some writers emit Windows-style separators in the name
        p = tmp_path / "bs.xp3"
        p.write_bytes(make_named_archive("dir\\file.txt", b"data"))
        entries = xp3tool.open_xp3(str(p))
        assert entries[0]["name"] == "dir/file.txt"

    def test_undecodable_name_skipped_with_warning(self, tmp_path, caplog):
        # a lone UTF-16 high surrogate cannot be decoded; the entry must be
        # skipped and the event surfaced as a WARNING, not a crash
        name_bytes = b"\x00\xd8"  # U+D800 lone surrogate
        info = struct.pack("<IQQH", 0, 3, 0, 1) + name_bytes
        segm = struct.pack("<IQqQ", 0, 19, 3, 3)
        file_chunk = (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm))
                      + b"info" + struct.pack("<q", len(info)) + info
                      + b"segm" + struct.pack("<q", len(segm)) + segm)
        raw = file_chunk
        comp = zlib.compress(raw)
        block = bytes([0x01]) + struct.pack("<qq", len(comp), len(raw)) + comp
        p = tmp_path / "badname.xp3"
        p.write_bytes(MAGIC + struct.pack("<q", 19 + 3) + b"abc" + block)
        with caplog.at_level(logging.WARNING, logger="xp3tool"):
            entries = xp3tool.open_xp3(str(p))
        assert entries == []
        assert any("undecodable entry name" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Segments: raw / zlib / multi-segment / mismatch rejection
# ---------------------------------------------------------------------------

class TestSegments:
    def test_raw_segment_roundtrip(self, tmp_path):
        files = [("a.txt", b"raw payload " * 4),
                 ("b.bin", bytes(range(256)) * 2)]
        p = tmp_path / "r.xp3"
        p.write_bytes(make_archive(files))
        entries = xp3tool.open_xp3(str(p))
        for e in entries:
            assert all(not comp for _s, _o, _a, comp in e["segments"])
        out = tmp_path / "out"
        n, _total = xp3tool.extract_all(str(p), str(out))
        assert n == 2
        for name, content in files:
            assert (out / name).read_bytes() == content

    def test_zlib_segment_roundtrip(self, tmp_path):
        files = [("c.txt", b"compressible " * 200),
                 ("d.bin", bytes(range(256)) * 8)]
        p = tmp_path / "z.xp3"
        p.write_bytes(make_archive(files, zlib_segments={"c.txt", "d.bin"}))
        entries = xp3tool.open_xp3(str(p))
        # the stored size (arc) must be smaller than the original for the
        # compressible payload, proving the zlib path was really taken
        for e in entries:
            assert len(e["segments"]) == 1
            _start, arc, org, comp = e["segments"][0]
            assert comp and arc < org
        out = tmp_path / "out"
        xp3tool.extract_all(str(p), str(out))
        for name, content in files:
            assert (out / name).read_bytes() == content

    def test_mixed_raw_and_zlib(self, tmp_path):
        files = [("raw.bin", b"\x00" * 100),
                 ("z.txt", b"hello " * 300)]
        p = tmp_path / "m.xp3"
        p.write_bytes(make_archive(files, zlib_segments={"z.txt"}))
        out = tmp_path / "out"
        xp3tool.extract_all(str(p), str(out))
        for name, content in files:
            assert (out / name).read_bytes() == content

    def test_multi_segment_entry_concatenated(self, tmp_path):
        parts = [(b"part1-" * 10, False),
                 (b"part2-" * 20, True),
                 (b"part3", False)]
        p = tmp_path / "multi.xp3"
        p.write_bytes(make_multi_segment_archive(parts))
        entries = xp3tool.open_xp3(str(p))
        assert len(entries) == 1
        assert len(entries[0]["segments"]) == 3
        assert xp3tool.entry_size(entries[0]) == sum(len(c) for c, _ in parts)
        out = tmp_path / "out"
        xp3tool.extract_all(str(p), str(out))
        expected = b"".join(c for c, _ in parts)
        assert (out / "multi.bin").read_bytes() == expected

    def test_extract_segment_raw_and_zlib(self, tmp_path):
        content = b"segment-data-" * 10
        comp = zlib.compress(content)
        raw_file = tmp_path / "raw.bin"
        raw_file.write_bytes(content)
        z_file = tmp_path / "z.bin"
        z_file.write_bytes(comp)
        with raw_file.open("rb") as f:
            got = xp3tool.extract_segment(f, "e", 0, len(content), len(content), False)
        assert got == content
        with z_file.open("rb") as f:
            got = xp3tool.extract_segment(f, "e", 0, len(comp), len(content), True)
        assert got == content

    def test_zlib_segment_size_mismatch_rejected(self, tmp_path):
        # open_xp3 only parses the index (no decompression), so the size
        # mismatch surfaces during extraction, not on open
        content = b"actual content " * 10
        p = tmp_path / "mm.xp3"
        p.write_bytes(make_zlib_segment_mismatch_archive("m.bin", content,
                                                         len(content) + 7))
        with pytest.raises(xp3tool.Xp3Error, match="size mismatch"):
            xp3tool.extract_all(str(p), str(tmp_path / "out"))

    def test_unknown_segment_method_rejected(self, tmp_path):
        p = tmp_path / "unk.xp3"
        p.write_bytes(make_unknown_segment_method_archive())
        with pytest.raises(xp3tool.Xp3Error, match="unknown segment method"):
            xp3tool.open_xp3(str(p))


# ---------------------------------------------------------------------------
# Extraction, sizes, listing, sub-chunk helpers, edge cases
# ---------------------------------------------------------------------------

class TestExtractAll:
    def test_extract_all_nested_paths(self, tmp_path):
        files = [("a.txt", b"root"),
                 ("sub/b.txt", b"one"),
                 ("sub/deep/c.bin", b"\x00\x01\x02")]
        p = tmp_path / "e.xp3"
        p.write_bytes(make_archive(files))
        out = tmp_path / "out"
        n, total = xp3tool.extract_all(str(p), str(out))
        assert n == 3
        assert total == len(b"root") + len(b"one") + 3
        for name, content in files:
            assert (out / name).read_bytes() == content

    def test_zero_byte_file(self, tmp_path):
        p = tmp_path / "e.xp3"
        p.write_bytes(make_archive([("empty.txt", b""), ("full.txt", b"x")]))
        out = tmp_path / "out"
        xp3tool.extract_all(str(p), str(out))
        assert (out / "empty.txt").read_bytes() == b""
        assert (out / "full.txt").read_bytes() == b"x"


class TestEntrySize:
    def test_single_segment(self):
        entry = {"name": "a", "segments": [(0, 5, 5, False)]}
        assert xp3tool.entry_size(entry) == 5

    def test_multi_segment(self):
        entry = {"name": "a", "segments": [(0, 5, 5, False),
                                           (10, 7, 7, True),
                                           (20, 9, 9, False)]}
        assert xp3tool.entry_size(entry) == 5 + 7 + 9


class TestSubChunkHelpers:
    def test_find_chunk(self):
        # sub-chunks are scanned inside the parent File chunk's data region
        # (offset 12), matching how parse_index calls find_chunk
        info_chunk = b"info" + struct.pack("<q", 4) + b"DATA"
        file_chunk = b"File" + struct.pack("<q", len(info_chunk)) + info_chunk
        ofs, size = xp3tool.find_chunk(file_chunk, 12, len(file_chunk) - 12, b"info")
        assert file_chunk[ofs:ofs + size] == b"DATA"

    def test_find_chunk_missing(self):
        buf = b"XXXX" + struct.pack("<q", 4) + b"data"
        with pytest.raises(xp3tool.Xp3Error, match="chunk"):
            xp3tool.find_chunk(buf, 0, len(buf), b"info")

    def test_parse_index_entries(self):
        raw = build_index([("a.txt", [(19, 5, 5, False)]),
                           ("b/c.bin", [(24, 8, 8, False)])],
                          compress=False, raw=True)
        # strip the 1-byte flag + 8-byte size header
        entries = xp3tool.parse_index(raw[9:], 0)
        assert [e["name"] for e in entries] == ["a.txt", "b/c.bin"]
        assert entries[0]["segments"] == [(19, 5, 5, False)]


class TestListEntries:
    def test_returns_counts(self, tmp_path, capsys):
        p = tmp_path / "l.xp3"
        p.write_bytes(make_archive([("a.txt", b"x" * 10),
                                    ("b/c.txt", b"y" * 20)]))
        n, total = xp3tool.list_entries(str(p))
        assert n == 2
        assert total == 30


class TestMain:
    def test_main_list(self, tmp_path, monkeypatch):
        p = tmp_path / "a.xp3"
        p.write_bytes(make_archive([("x.txt", b"hello")]))
        monkeypatch.setattr(sys, "argv", ["xp3tool.py", "list", str(p)])
        xp3tool.main()  # must not raise

    def test_main_extract(self, tmp_path, monkeypatch):
        p = tmp_path / "a.xp3"
        p.write_bytes(make_archive([("x.txt", b"hello")]))
        out = tmp_path / "out"
        monkeypatch.setattr(sys, "argv", ["xp3tool.py", "extract", str(p), str(out)])
        xp3tool.main()
        assert (out / "x.txt").read_bytes() == b"hello"

    def test_main_bad_magic_returns_one(self, tmp_path, monkeypatch):
        """A bad archive is a failure, reported as the exit code (tools return
        their code; the framework no longer raises SystemExit from inside)."""
        p = tmp_path / "bad.xp3"
        p.write_bytes(b"garbage-data")
        monkeypatch.setattr(sys, "argv", ["xp3tool.py", "list", str(p)])
        assert xp3tool.main() == 1

    def test_unknown_subcommand_returns_two(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["xp3tool.py", "nope"])
        assert xp3tool.main() == 2
        assert "No such command" in capsys.readouterr().err
