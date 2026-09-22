#!/usr/bin/env python3
"""Unit tests for kirikiri/xp3pack.py - the krkrz XP3 archive packer.

The produced archives are read back with the xp3tool parser (the same
self-verification xp3pack.verify performs), so the pack/unpack contract is
covered end to end with no external tooling and no game fixtures.

The container contract is fixed by the engine, not by us: krkrz's
``tTVPXP3Archive::LoadIndex`` *requires* an ``adlr`` sub-chunk (Adler-32 of
the uncompressed entry) per File chunk and throws ``TVPReadError`` without
it.  Since the old writer and the old parser agreed with each other while
both deviating from the engine, the packer's self-check was circular and
the bug only showed up on a real game ("Script exception raised / Read
error" at startup).  The negative cases below pack such archives on purpose.

Positive / negative / edge coverage:
  - positive: file collection ordering, index bytes, pack -> parse ->
    byte-for-byte extract round-trips, Adler-32 per entry, verify() success.
  - negative: empty input dir, missing / wrong 'adlr', verify() detecting
    missing / resized / unexpected entries, CLI exit code on failure.
  - edge: zero-byte files, deeply nested paths, CJK file names, binary
    payloads, many files, header / index flag layout.
"""

import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
# NOTE: the kirikiri/ dir must NOT go on sys.path: it would make a bare
# `import pipeline` / `import xp3tool` resolve to kirikiri/*.py (kirikiri has a
# pipeline.py mirroring tyrano/pipeline.py), shadowing the repo-root modules for
# every test collected afterwards.  xp3pack.verify() imports the sibling module
# by name, which works because the package import below sets up the package
# first (and kirikiri/ itself is a package).

from kirikiri import xp3pack  # noqa: E402
from kirikiri import xp3tool  # noqa: E402

MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"


def write_tree(root, files):
    """files = [(rel_path, bytes)]; creates parent directories as needed."""
    for rel, data in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def legacy_file_chunk(name, start, size, adler=None):
    """A File chunk built without 'adlr' (pre-fix xp3pack output)."""
    name_bytes = name.encode("utf-16-le")
    info = struct.pack("<IQQH", 0, size, 0, len(name)) + name_bytes
    segm = struct.pack("<IQqQ", 0, start, size, size)
    out = (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm))
           + b"info" + struct.pack("<q", len(info)) + info
           + b"segm" + struct.pack("<q", len(segm)) + segm)
    if adler is not None:
        adlr = struct.pack("<I", adler)
        out = (b"File" + struct.pack("<q", 12 + len(info) + 12 + len(segm)
                                     + 12 + len(adlr))
               + b"info" + struct.pack("<q", len(info)) + info
               + b"segm" + struct.pack("<q", len(segm)) + segm
               + b"adlr" + struct.pack("<q", len(adlr)) + adlr)
    return out


def pack_with_index(indir, out_path, index_bytes):
    """Pack indir's payload with an arbitrary hand-made index.

    Used to reproduce containers the engine rejects (missing or wrong
    'adlr'), which xp3pack.pack() itself no longer produces.
    """
    files = xp3pack.collect_files(str(indir))
    entries = []
    with open(out_path, "wb") as out:
        out.write(MAGIC)
        out.write(struct.pack("<q", 0))
        ofs = 19
        for rel, full in files:
            data = Path(full).read_bytes()
            out.write(data)
            entries.append((rel, ofs, len(data)))
            ofs += len(data)
        out.seek(11)
        out.write(struct.pack("<q", ofs))
        out.seek(0, os.SEEK_END)
        comp = zlib.compress(index_bytes)
        out.write(bytes([1]) + struct.pack("<qq", len(comp),
                                         len(index_bytes)) + comp)
    return files


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

class TestCollectFiles:
    def test_sorted_rel_paths(self, tmp_path):
        write_tree(tmp_path, [("b.txt", b"b"), ("a.txt", b"a"), ("c.txt", b"c")])
        files = xp3pack.collect_files(str(tmp_path))
        assert [rel for rel, _full in files] == ["a.txt", "b.txt", "c.txt"]
        for rel, full in files:
            assert full == str(tmp_path / rel)

    def test_nested_dirs(self, tmp_path):
        # os.walk is top-down: each directory's own files come before the
        # files of its subdirectories
        write_tree(tmp_path, [("sub/deep/f.txt", b"x"), ("top.txt", b"y")])
        files = xp3pack.collect_files(str(tmp_path))
        assert [rel for rel, _full in files] == ["top.txt", "sub/deep/f.txt"]

    def test_empty_dir(self, tmp_path):
        assert xp3pack.collect_files(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# Index bytes
# ---------------------------------------------------------------------------

class TestBuildIndex:
    def test_index_parses_back_with_xp3tool(self):
        raw = xp3pack.build_index([("a.txt", 19, 5, 0x01020304),
                                   ("b/c.bin", 24, 8, 0xdeadbeef)])
        entries = xp3tool.parse_index(raw, 0)
        assert [e["name"] for e in entries] == ["a.txt", "b/c.bin"]
        assert entries[0]["segments"] == [(19, 5, 5, False)]
        assert entries[1]["segments"] == [(24, 8, 8, False)]
        # the Adler-32 sub-chunk is what the engine's loader insists on
        assert entries[0]["adler"] == 0x01020304
        assert entries[1]["adler"] == 0xdeadbeef

    def test_adlr_chunk_layout(self):
        raw = xp3pack.build_index([("f", 19, 3, 0x12345678)])
        pos = raw.index(b"adlr")
        size = struct.unpack_from("<q", raw, pos + 4)[0]
        assert size == 4
        assert struct.unpack_from("<I", raw, pos + 12)[0] == 0x12345678
        # the File chunk size must cover info + segm + adlr
        assert struct.unpack_from("<q", raw, 4)[0] == len(raw) - 12

    def test_names_stored_utf16le(self):
        raw = xp3pack.build_index([("名前.txt", 19, 4, 1)])
        assert "名前.txt".encode("utf-16-le") in raw
        assert "名前.txt".encode() not in raw

    def test_segm_record_layout(self):
        # one raw segment of size 7 at offset 1234: 28-byte record with
        # org@+12 and arc@+20 both equal to 7 (see xp3tool.parse_index)
        raw = xp3pack.build_index([("f", 1234, 7, 1)])
        pos = raw.index(b"segm")
        size = struct.unpack_from("<q", raw, pos + 4)[0]
        rec = raw[pos + 12:pos + 12 + size]
        assert len(rec) == 28
        flags, start = struct.unpack_from("<IQ", rec, 0)
        org = struct.unpack_from("<q", rec, 12)[0]
        arc = struct.unpack_from("<Q", rec, 20)[0]
        assert (flags, start, org, arc) == (0, 1234, 7, 7)

    def test_info_org_and_arc_sizes_both_set(self):
        # info = flags(u32), org size(i64), arc size(i64), name length(u16),
        # name.  A raw entry stores org == arc; writing 0 for arc (as the old
        # writer did) is what the engine reads as the archived size.
        raw = xp3pack.build_index([("f", 19, 1234, 1)])
        pos = raw.index(b"info")
        info = raw[pos + 12:]
        flags, org, arc = struct.unpack_from("<IQQ", info, 0)
        assert (flags, org, arc) == (0, 1234, 1234)


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------

class TestPack:
    def test_empty_dir_raises(self, tmp_path):
        with pytest.raises(xp3pack.Xp3PackError, match="nothing to pack"):
            xp3pack.pack(str(tmp_path), str(tmp_path / "out.xp3"))

    def test_single_file_roundtrip(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("hello.txt", b"hello world")])
        out = tmp_path / "out.xp3"
        files, payload_end = xp3pack.pack(str(indir), str(out))
        assert len(files) == 1
        assert payload_end == 19 + len(b"hello world")  # header + payload
        entries = xp3tool.open_xp3(str(out))
        assert [e["name"] for e in entries] == ["hello.txt"]
        assert xp3tool.entry_size(entries[0]) == len(b"hello world")

    def test_multiple_files_roundtrip(self, tmp_path):
        indir = tmp_path / "in"
        files_data = [("a.txt", b"alpha " * 20),
                      ("b.bin", bytes(range(256)) * 3),
                      ("sub/c.dat", b"gamma" * 40),
                      ("sub/deep/d.bin", b"\x00" * 64)]
        write_tree(indir, files_data)
        out = tmp_path / "out.xp3"
        files, _ = xp3pack.pack(str(indir), str(out))
        assert [rel for rel, _ in files] == [r for r, _c in files_data]
        ex = tmp_path / "ex"
        n, _total = xp3tool.extract_all(str(out), str(ex))
        assert n == 4
        for rel, content in files_data:
            assert (ex / rel).read_bytes() == content

    def test_unicode_names_roundtrip(self, tmp_path):
        indir = tmp_path / "in"
        files_data = [("scenario/名前.ks", "こんにちは".encode()),
                      ("台词/中文.md", "你好世界".encode())]
        write_tree(indir, files_data)
        out = tmp_path / "out.xp3"
        xp3pack.pack(str(indir), str(out))
        entries = xp3tool.open_xp3(str(out))
        assert [e["name"] for e in entries] == [r for r, _c in files_data]
        ex = tmp_path / "ex"
        xp3tool.extract_all(str(out), str(ex))
        for rel, content in files_data:
            assert (ex / rel).read_bytes() == content

    def test_binary_content(self, tmp_path):
        indir = tmp_path / "in"
        blob = bytes((i * 7) % 256 for i in range(4096)) + b"\x00\xff" * 512
        write_tree(indir, [("blob.bin", blob)])
        out = tmp_path / "out.xp3"
        xp3pack.pack(str(indir), str(out))
        ex = tmp_path / "ex"
        xp3tool.extract_all(str(out), str(ex))
        assert (ex / "blob.bin").read_bytes() == blob

    def test_zero_byte_file(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("empty.txt", b""), ("full.txt", b"data")])
        out = tmp_path / "out.xp3"
        xp3pack.pack(str(indir), str(out))
        ex = tmp_path / "ex"
        xp3tool.extract_all(str(out), str(ex))
        assert (ex / "empty.txt").read_bytes() == b""
        assert (ex / "full.txt").read_bytes() == b"data"

    def test_many_files(self, tmp_path):
        indir = tmp_path / "in"
        files_data = [("file%03d.txt" % i, ("data-%d-" % i).encode() * 5)
                      for i in range(30)]
        write_tree(indir, files_data)
        out = tmp_path / "out.xp3"
        files, _ = xp3pack.pack(str(indir), str(out))
        assert len(files) == 30
        entries = xp3tool.open_xp3(str(out))
        assert len(entries) == 30

    def test_header_layout(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"payload")])
        out = tmp_path / "out.xp3"
        xp3pack.pack(str(indir), str(out))
        data = out.read_bytes()
        assert data[:11] == MAGIC
        index_ofs = struct.unpack_from("<q", data, 11)[0]
        assert index_ofs == 19 + len(b"payload")
        # index block: 1-byte zlib flag then (csize, usize) then payload
        assert data[index_ofs] == xp3pack.INDEX_ZLIB
        csize, usize = struct.unpack_from("<qq", data, index_ofs + 1)
        expected = xp3pack.build_index(
            [("a.txt", 19, 7, zlib.adler32(b"payload"))])
        assert usize == len(expected)
        assert csize == len(data) - (index_ofs + 1 + 16)
        # the stored index must really be zlib-compressed
        assert zlib.decompress(data[index_ofs + 1 + 16:]) == expected

    def test_adler_of_uncompressed_content(self, tmp_path):
        # The engine hands this value to the per-game extraction filter, so it
        # must be the Adler-32 of the *uncompressed* bytes, for every entry.
        indir = tmp_path / "in"
        payloads = [("a.txt", b"alpha"), ("empty.bin", b""),
                    ("sub/b.dat", bytes(range(256)) * 40),
                    ("scenario/名前.ks", "こんにちは".encode())]
        write_tree(indir, payloads)
        out = tmp_path / "out.xp3"
        xp3pack.pack(str(indir), str(out))
        got = {e["name"]: e["adler"] for e in xp3tool.open_xp3(str(out))}
        for rel, content in payloads:
            assert got[rel] == zlib.adler32(content) & 0xFFFFFFFF, rel
        # an empty file hashes to the Adler-32 initial value, not to 0
        assert got["empty.bin"] == 1


# ---------------------------------------------------------------------------
# Self-verification (re-read with the xp3tool parser)
# ---------------------------------------------------------------------------

class TestVerify:
    def test_verify_passes(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"hello"), ("b/c.bin", b"\x01\x02")])
        out = tmp_path / "out.xp3"
        files, _ = xp3pack.pack(str(indir), str(out))
        assert xp3pack.verify(str(out), files) == 2

    def test_verify_detects_missing_adlr(self, tmp_path):
        """The regression that shipped: an index without 'adlr' is rejected
        by the engine at startup, so the packer's own verification must
        reject it too."""
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"hello")])
        out = tmp_path / "out.xp3"
        files = pack_with_index(indir, out, legacy_file_chunk("a.txt", 19, 5))
        with pytest.raises(xp3pack.Xp3PackError, match="no 'adlr'"):
            xp3pack.verify(str(out), files)

    def test_verify_detects_wrong_adler(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"hello")])
        out = tmp_path / "out.xp3"
        wrong = (zlib.adler32(b"hello") + 1) & 0xFFFFFFFF
        files = pack_with_index(indir, out,
                                legacy_file_chunk("a.txt", 19, 5, wrong))
        with pytest.raises(xp3pack.Xp3PackError, match="wrong Adler-32"):
            xp3pack.verify(str(out), files)

    def test_verify_missing_file_raises(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"hello")])
        out = tmp_path / "out.xp3"
        files, _ = xp3pack.pack(str(indir), str(out))
        ghost = tmp_path / "ghost.txt"
        ghost.write_bytes(b"x")  # must exist so getsize() works
        claimed = files + [("ghost.txt", str(ghost))]
        with pytest.raises(xp3pack.Xp3PackError, match="missing"):
            xp3pack.verify(str(out), claimed)

    def test_verify_resized_file_raises(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"hello")])
        out = tmp_path / "out.xp3"
        files, _ = xp3pack.pack(str(indir), str(out))
        (indir / "a.txt").write_bytes(b"hello world")  # grew after packing
        with pytest.raises(xp3pack.Xp3PackError, match="resized"):
            xp3pack.verify(str(out), files)

    def test_verify_extra_in_archive_raises(self, tmp_path):
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"one"), ("b.txt", b"two")])
        out = tmp_path / "out.xp3"
        files, _ = xp3pack.pack(str(indir), str(out))
        # claim only one of the two packed files -> the other is "extra"
        with pytest.raises(xp3pack.Xp3PackError, match="extra"):
            xp3pack.verify(str(out), files[:1])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_pack_success(self, tmp_path, monkeypatch):
        indir = tmp_path / "in"
        write_tree(indir, [("a.txt", b"hello")])
        out = tmp_path / "out.xp3"
        monkeypatch.setattr(sys, "argv", ["xp3pack.py", str(indir), str(out)])
        xp3pack.main()  # must not raise; verify() runs inside
        assert out.exists()
        entries = xp3tool.open_xp3(str(out))
        assert [e["name"] for e in entries] == ["a.txt"]

    def test_main_empty_dir_returns_one(self, tmp_path, monkeypatch):
        """An empty input directory is a failure, reported as the exit code
        (a command returns its code instead of raising SystemExit)."""
        indir = tmp_path / "in"
        indir.mkdir()
        monkeypatch.setattr(sys, "argv",
                            ["xp3pack.py", str(indir), str(tmp_path / "o.xp3")])
        assert xp3pack.main() == 1

    def test_unknown_option_returns_two(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["xp3pack.py", "--nope"])
        assert xp3pack.main() == 2
        assert "No such option" in capsys.readouterr().err
