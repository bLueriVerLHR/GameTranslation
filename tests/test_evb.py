#!/usr/bin/env python3
"""Tests for rpgmaker.evb (recovering data/ packed inside <Game>.exe)."""
import json
import struct

import pytest

from rpgmaker import evb


def make_pe(extra_sections):
    """Minimal PE32+-shaped file with the given sections.

    `extra_sections` is a list of (name, vsize, raw_ptr, raw_size); the raw
    bytes themselves are appended by the caller through `raw_ptr`.
    """
    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)  # e_lfanew
    coff = bytearray(20)
    struct.pack_into("<H", coff, 0, 0x8664)   # machine
    struct.pack_into("<H", coff, 2, len(extra_sections) + 1)
    struct.pack_into("<H", coff, 16, 0xF0)    # optional header size
    opt = bytearray(0xF0)                     # only its size matters here
    sections = bytearray()
    names = [b".text"] + [n.encode("ascii") for n, *_ in extra_sections]
    for i, name in enumerate(names):
        row = bytearray(40)
        row[0:len(name)] = name
        if i == 0:
            struct.pack_into("<IIII", row, 8, 0x100, 0x1000, 0x100, 0x400)
        else:
            _n, vsize, raw_ptr, raw_size = extra_sections[i - 1]
            struct.pack_into("<IIII", row, 8, vsize, 0x1000 + i * 0x1000, raw_size, raw_ptr)
        sections += row
    return bytes(dos) + b"PE\0\0" + bytes(coff) + bytes(opt) + bytes(sections)


def make_container(entries, payload_extra=b"", payload_gap=0, trailer=b""):
    """Build an .enigma1 region: UTF-16 name table + payload, as observed.

    `entries` is a list of (name, document-bytes); the size field written into
    the table is the document's length, exactly like the real container.
    """
    names = bytearray()
    sizes = []
    for name, doc in entries:
        names += name.encode("utf-16-le") + b"\x00\x00"
        sizes.append(len(doc))
        # records carry a little flag/counter preamble; 5 bytes after the name
        # end is where the size u32 lives
        names += b"\x02\x00\x00"
        names += struct.pack("<I", len(doc))
        names += b"\x00\x00\x00\x00"
    table = names + b"\x00" * payload_gap
    payload = bytearray()
    for i, (_name, doc) in enumerate(entries):
        if i == len(entries) - 1 and payload_extra:
            payload += payload_extra
        payload += doc
    return bytes(table) + bytes(payload) + trailer


def packed_exe(tmp_path, region, name="Game.exe", section=evb.CONTAINER_SECTION):
    """Write a synthetic packed exe and return its path."""
    raw_ptr = 0x400
    blob = bytearray(make_pe([(section, 0x1000, raw_ptr, len(region))]))
    blob += b"\x00" * (raw_ptr - len(blob))
    blob += region
    path = tmp_path / name
    path.write_bytes(bytes(blob))
    return path


def docs(*pairs):
    return [(n, json.dumps(v, ensure_ascii=False).encode("utf-8")) for n, v in pairs]


# ------------------------------------------------------------- PE parsing


def test_pe_sections_reads_the_section_table(tmp_path):
    region = b"x" * 64
    exe = packed_exe(tmp_path, region)
    sections = evb.pe_sections(exe.read_bytes())
    assert evb.CONTAINER_SECTION in sections
    vsize, raw_size, raw_ptr = sections[evb.CONTAINER_SECTION]
    assert (vsize, raw_size) == (0x1000, 64)
    assert raw_ptr == 0x400


def test_pe_sections_rejects_non_pe(tmp_path):
    plain = tmp_path / "not.exe"
    plain.write_bytes(b"just text, no MZ header")
    assert evb.pe_sections(plain.read_bytes()) is None


def test_container_region_absent_without_section(tmp_path):
    exe = tmp_path / "plain.exe"
    exe.write_bytes(make_pe([]))
    assert evb.find_container(str(exe)) is None


def test_container_region_rejects_out_of_range_section(tmp_path):
    exe = tmp_path / "broken.exe"
    blob = bytearray(make_pe([(evb.CONTAINER_SECTION, 0x1000, 0x400, 10_000)]))
    blob += b"\x00" * 16
    exe.write_bytes(bytes(blob))
    assert evb.find_container(str(exe)) is None


# ------------------------------------------------------------- extraction


def test_unpack_writes_every_packed_file(tmp_path):
    entries = docs(("Actors.json", [None, {"id": 1, "name": "神子"}]),
                   ("MapInfos.json", [None, {"id": 1, "name": "テスト"}]))
    exe = packed_exe(tmp_path, make_container(entries))
    out = tmp_path / "data"
    summary = evb.unpack(str(tmp_path), str(out), exe=str(exe))

    assert summary["files"] == 2
    assert summary["entries"] == 2
    assert summary["skipped"] == []
    assert sorted(p.name for p in out.iterdir()) == ["Actors.json", "MapInfos.json"]
    assert json.loads((out / "Actors.json").read_text(encoding="utf-8"))[1]["name"] == "神子"
    assert summary["bytes"] == sum(len(d) for _n, d in entries)


def test_unpack_skips_non_json_payload_items(tmp_path):
    """A repacker promo marker sits between two packed documents."""
    files = docs(("Actors.json", [None, {"id": 1}]), ("Items.json", [None, {"id": 1}]))
    region = make_container(files, payload_extra=b"https://example.invalid/promo")
    exe = packed_exe(tmp_path, region)
    out = tmp_path / "data"
    summary = evb.unpack(str(tmp_path), str(out), exe=str(exe))

    assert summary["files"] == 2
    assert len(summary["skipped"]) == 1
    start, end = summary["skipped"][0]
    assert end - start == len(b"https://example.invalid/promo")
    assert json.loads((out / "Items.json").read_text(encoding="utf-8"))[1]["id"] == 1


def test_unpack_payload_after_gap_with_wrong_offsets(tmp_path):
    """Leading table padding must not shift the payload slice."""
    entries = docs(("Actors.json", [None, {"id": 1}]), ("Skills.json", [None, {"id": 1}]))
    exe = packed_exe(tmp_path, make_container(entries, payload_gap=64))
    out = tmp_path / "data"
    assert evb.unpack(str(tmp_path), str(out), exe=str(exe))["files"] == 2


def test_unpack_skips_promo_gap_after_the_probe_window(tmp_path):
    """The real case: the promo marker sits deep in the payload."""
    entries = docs(("Actors.json", [None, {"id": 1}]),
                   ("Animations.json", [None, {"id": 1}]),
                   ("Armors.json", [None, {"id": 1}]),
                   ("Classes.json", [None, {"id": 1}]),
                   ("Items.json", [None, {"id": 1}]))
    region = make_container(entries, payload_extra=b"https://example.invalid/promo")
    exe = packed_exe(tmp_path, region)
    out = tmp_path / "data"
    summary = evb.unpack(str(tmp_path), str(out), exe=str(exe))
    assert summary["files"] == 5
    assert len(summary["skipped"]) == 1


def test_unpack_dry_run_writes_nothing(tmp_path):
    exe = packed_exe(tmp_path, make_container(docs(("Actors.json", [None, {"id": 1}]))))
    out = tmp_path / "data"
    summary = evb.unpack(str(tmp_path), str(out), dry_run=True, exe=str(exe))
    assert summary["dry_run"] is True
    assert summary["files"] == 0
    assert not out.exists()


def test_unpack_keeps_existing_identical_file(tmp_path):
    exe = packed_exe(tmp_path, make_container(docs(("Actors.json", [None, {"id": 1}]))))
    out = tmp_path / "data"
    out.mkdir()
    (out / "Actors.json").write_bytes(json.dumps([None, {"id": 1}]).encode("utf-8"))
    before = (out / "Actors.json").stat().st_mtime_ns
    summary = evb.unpack(str(tmp_path), str(out), exe=str(exe))
    assert summary["files"] == 0  # identical content: not rewritten
    assert (out / "Actors.json").stat().st_mtime_ns == before


def test_unpack_overwrites_different_existing_file(tmp_path):
    exe = packed_exe(tmp_path, make_container(docs(("Actors.json", [None, {"id": 7}]))))
    out = tmp_path / "data"
    out.mkdir()
    (out / "Actors.json").write_text("[]", encoding="utf-8")
    assert evb.unpack(str(tmp_path), str(out), exe=str(exe))["files"] == 1
    assert json.loads((out / "Actors.json").read_text(encoding="utf-8"))[1]["id"] == 7


def test_unpack_finds_the_executable_by_itself(tmp_path):
    exe = packed_exe(tmp_path, make_container(docs(("Actors.json", [None, {"id": 1}]))))
    other = tmp_path / "helper.exe"
    other.write_bytes(b"not packed at all")
    assert evb.unpack(str(tmp_path), str(tmp_path / "data"))["exe"] == str(exe)


# ------------------------------------------------------------------ errors


def test_unpack_rejects_folder_without_packed_exe(tmp_path):
    (tmp_path / "game.exe").write_bytes(b"MZ" + b"\x00" * 100)
    with pytest.raises(evb.EvbError, match="no .enigma1 section"):
        evb.unpack(str(tmp_path), str(tmp_path / "data"))


def test_unpack_rejects_folder_without_exe(tmp_path):
    with pytest.raises(evb.EvbError, match="no .exe"):
        evb.unpack(str(tmp_path), str(tmp_path / "data"))


def test_unpack_rejects_encrypted_payload(tmp_path):
    """Compressed/encrypted containers keep the table but no plaintext JSON."""
    names = ("Actors.json".encode("utf-16-le") + b"\x00\x00" + b"\x02\x00\x00"
             + struct.pack("<I", 4096) + b"\x00\x00\x00\x00")
    region = names + b"\x00" * 64 + b"\x5b\x7b" + bytes(range(256)) * 16
    exe = packed_exe(tmp_path, region)
    with pytest.raises(evb.EvbError, match="no plaintext JSON payload"):
        evb.unpack(str(tmp_path), str(tmp_path / "data"), exe=str(exe))


def test_unpack_rejects_truncated_payload(tmp_path):
    entries = docs(("Actors.json", [None, {"id": 1}]), ("Items.json", [None, {"id": 1}]))
    region = make_container(entries)
    exe = packed_exe(tmp_path, region[:-8])  # last document is cut short
    with pytest.raises(evb.EvbError, match="does not parse as JSON|no plaintext JSON payload"):
        evb.unpack(str(tmp_path), str(tmp_path / "data"), exe=str(exe))


def test_unpack_rejects_container_without_json_entries(tmp_path):
    names = ("readme.txt".encode("utf-16-le") + b"\x00\x00" + b"\x02\x00\x00"
             + struct.pack("<I", 4) + b"\x00\x00\x00\x00")
    region = names + b"\x00" * 64 + b"[[]]" + b"\x00" * 32
    exe = packed_exe(tmp_path, region)
    with pytest.raises(evb.EvbError, match="no plaintext JSON payload|packs no database"):
        evb.unpack(str(tmp_path), str(tmp_path / "data"), exe=str(exe))


# ------------------------------------------------------------- self-check


def test_self_check_warns_about_missing_maps(tmp_path):
    entries = docs(("MapInfos.json", [None, {"id": 1, "name": "one"}, {"id": 2, "name": "two"}]),
                   ("Map001.json", {"events": []}))
    exe = packed_exe(tmp_path, make_container(entries))
    summary = evb.unpack(str(tmp_path), str(tmp_path / "data"), exe=str(exe))
    assert any("Map002.json" in w for w in summary["warnings"])


def test_self_check_clean_when_maps_are_complete(tmp_path):
    entries = docs(("MapInfos.json", [None, {"id": 1, "name": "one"}]),
                   ("Map001.json", {"events": []}),
                   ("System.json", {"hasEncryptedImages": True, "encryptionKey": "00" * 16}))
    exe = packed_exe(tmp_path, make_container(entries))
    summary = evb.unpack(str(tmp_path), str(tmp_path / "data"), exe=str(exe))
    assert summary["warnings"] == []
    assert summary["files"] == 3


def test_name_records_reads_sizes_after_the_name():
    region = make_container(docs(("Actors.json", [None, {"id": 1}])))
    records = evb.name_records(region)
    assert records and records[0][1] == "Actors.json"
    assert records[0][2] == len(json.dumps([None, {"id": 1}]).encode("utf-8"))
