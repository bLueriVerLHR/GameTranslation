#!/usr/bin/env python3
"""Recover a game database that a launcher packer hid inside the game .exe.

Some launcher repacks ship the MZ/MV engine and every asset on disk but *no*
`data/`: the database was packed into `<Game>.exe` by an Enigma Virtual Box
style packer, which serves those files at runtime.  Such a folder is perfectly
playable, but it is not a web root, so `build` refuses it (see detect.py).
Extracting `data/` back out is what makes the normal pipeline work again.

Container layout (verified on such packages, and what this module relies on):

* the exe carries the PE sections `.enigma1` (payload) and `.enigma2`;
* `.enigma1` starts with a plaintext UTF-16LE name table, one record per
  packed file, in ASCII-alphabetical order; each record's packed size is the
  u32 stored ``SIZE_DELTA`` bytes past the end of the name;
* after the table the payload follows: the packed files concatenated verbatim
  and uncompressed, so an MZ/MV database slices out as plaintext JSON.

Extraction therefore never parses the container: it slices the payload with
the table's own sizes and validates *every* slice by parsing it as JSON.  That
validation is both the boundary proof and the self-check the toolkit requires
of binary-format tools.  Payload items that are not JSON (repacker promo
markers, the packer's own binary tail) are reported with their offset and
skipped; running past those is safe because the following entry is only
accepted where its slice parses again.
"""
from __future__ import annotations

import json
import logging
import os
import re
import struct

from . import logsetup

log = logging.getLogger("rpgmaker.evb")

CONTAINER_SECTION = ".enigma1"
COMPANION_SECTION = ".enigma2"

# UTF-16LE runs of printable characters (the name table's strings).
NAME_UTF16_RE = re.compile(br"(?:[\x20-\x7e]\x00){3,}(?=\x00\x00)")
# Only database files are recovered; everything else in the container stays.
DATA_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.json$")
# The u32 size field sits this many bytes past the end of the name string.
SIZE_DELTA = 5
# How far to look ahead when a payload item is not a JSON document.
RESYNC_WINDOW = 8192
JSON_START = (0x5B, 0x7B)  # '[' or '{'


class EvbError(Exception):
    """Container found, but its database cannot be recovered."""


# ------------------------------------------------------------------ PE


def pe_sections(blob):
    """Parse the PE section table -> {name: (vsize, raw_size, raw_ptr)} or None."""
    if len(blob) < 0x40 or blob[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return None
    nsec, = struct.unpack_from("<H", blob, e_lfanew + 6)
    opt_size, = struct.unpack_from("<H", blob, e_lfanew + 20)
    start = e_lfanew + 24 + opt_size
    out = {}
    for i in range(nsec):
        off = start + i * 40
        if off + 40 > len(blob):
            return None
        name = blob[off:off + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, _va, raw_size, raw_ptr = struct.unpack_from("<IIII", blob, off + 8)
        out[name] = (vsize, raw_size, raw_ptr)
    return out


def container_region(blob):
    """Return (region, section) for the packed payload, or None if absent.

    The packed payload lives in a section whose raw size dwarfs its virtual
    size (the packer never maps it): that ratio is the cheap sanity check.
    """
    sections = pe_sections(blob)
    if not sections:
        return None
    entry = sections.get(CONTAINER_SECTION)
    if entry is None:
        return None
    vsize, raw_size, raw_ptr = entry
    if raw_ptr + raw_size > len(blob):
        log.warning("evb: section %s claims %d bytes at %d, beyond EOF (%d)",
                    CONTAINER_SECTION, raw_size, raw_ptr, len(blob))
        return None
    if raw_size <= vsize:
        log.debug("evb: %s raw=%d vsize=%d (no unmapped payload?)",
                  CONTAINER_SECTION, raw_size, vsize)
    return blob[raw_ptr:raw_ptr + raw_size], CONTAINER_SECTION


def find_container(exe_path):
    """Locate the packed payload in `exe_path` -> (region, section) or None."""
    try:
        with open(exe_path, "rb") as f:
            blob = f.read()
    except OSError as exc:
        log.warning("evb: cannot read %s (%s)", exe_path, exc)
        return None
    return container_region(blob)


# ------------------------------------------------------------- name table


def name_records(region):
    """Parse the container name table -> [(offset, name, size)], table order."""
    records = []
    for m in NAME_UTF16_RE.finditer(region):
        name = m.group().decode("utf-16-le")
        size_at = m.end() + SIZE_DELTA
        if size_at + 4 > len(region):
            continue
        size = struct.unpack_from("<I", region, size_at)[0]
        records.append((m.start(), name, size))
    return records


def data_entries(records, payload_start):
    """The `*.json` records before the payload (the game database, in order)."""
    return [(off, name, size) for off, name, size in records
            if off < payload_start and DATA_NAME_RE.match(name)]


def _slice_parses(region, off, size):
    """True when region[off:off+size] is a complete JSON document."""
    if size <= 0 or off + size > len(region):
        return False
    try:
        json.loads(region[off:off + size].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return True


def _probe_slices(region, entries, start):
    """Offsets of the first entries when the whole probe set parses at `start`."""
    offsets = []
    pos = start
    for _off, _name, size in entries:
        offsets.append(pos)
        pos += size
    return offsets


def find_payload_start(region, entries, probes=(4, 2, 1), max_attempts=5000):
    """First offset where the table's own sizes reproduce parseable JSON.

    Scanning for a `[`/`{` that follows a NUL gap finds the end of the name
    table; validating the first few slices is what proves it is the payload and
    not an unrelated byte pattern inside the table itself.  Shrinking probe
    counts keep this working when a non-JSON payload item (repacker promo
    marker) sits within the first few entries - the walk resyncs there anyway.
    """
    if not entries:
        return None
    table_end = min(off for off, _n, _s in entries)
    for probe in probes:
        sample = entries[:probe] if len(entries) >= probe else entries
        wanted = [size for _o, _n, size in sample]
        attempts = 0
        for cand in range(max(0, table_end), len(region) - 1):
            if region[cand] not in JSON_START or b"\x00" not in region[cand - 24:cand]:
                continue
            attempts += 1
            if attempts > max_attempts:
                log.warning("evb: payload start search gave up after %d candidates", max_attempts)
                return None
            pos = cand
            for size in wanted:
                if not _slice_parses(region, pos, size):
                    break
                pos += size
            else:
                return cand
    return None


# ------------------------------------------------------------- extraction


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _packed_executable(game_dir):
    """The game .exe that carries the container (warns when several do)."""
    if not os.path.isdir(game_dir):
        raise EvbError(f"not a folder: {game_dir}")
    candidates = sorted(os.path.join(game_dir, fn) for fn in os.listdir(game_dir)
                        if fn.lower().endswith(".exe"))
    if not candidates:
        raise EvbError(f"no .exe in {game_dir}")
    packed = [p for p in candidates if container_region(_read(p))]
    if not packed:
        raise EvbError("no {} section in {} - not a launcher-packed game".format(CONTAINER_SECTION, ", ".join(os.path.basename(p) for p in candidates)))
    if len(packed) > 1:
        log.warning("evb: %d packed executables found, using %s",
                    len(packed), os.path.basename(packed[0]))
    return packed[0]


def unpack(game_dir, out_dir=None, dry_run=False, exe=None):
    """Recover the packed database of `game_dir` into `out_dir`.

    Returns a summary dict; raises EvbError when a container is present but the
    payload is not plaintext JSON (compressed/encrypted containers).
    """
    if exe is None:
        exe = _packed_executable(game_dir)
    located = container_region(_read(exe))
    if located is None:
        raise EvbError(f"no {CONTAINER_SECTION} section in {exe} - not a launcher-packed game")
    region, section = located

    records = name_records(region)
    if not records:
        raise EvbError(f"{os.path.basename(exe)}: no name table in {section}")
    start = find_payload_start(region, data_entries(records, len(region)))
    if start is None:
        raise EvbError(
            f"{os.path.basename(exe)}: {section} has a name table but no plaintext JSON payload "
            "(compressed/encrypted container - unsupported)")
    entries = data_entries(records, start)
    if not entries:
        raise EvbError(f"{os.path.basename(exe)}: {section} packs no database .json files")
    log.info("evb: %s %s: %d packed files, payload at 0x%x",
             os.path.basename(exe), section, len(entries), start)

    with logsetup.phase("evb unpack", log):
        files, skipped = _slice_files(region, section, start, entries)
    summary = _write_files(files, out_dir, dry_run=dry_run)
    summary["exe"] = exe
    summary["section"] = section
    summary["entries"] = len(entries)
    summary["skipped"] = skipped
    summary["warnings"] = _self_check(files)
    return summary


def _slice_files(region, section, start, entries):
    """Slice every entry out of the payload -> ({name: bytes}, [skipped ranges])."""
    files = {}
    skipped = []
    pos = start
    for _off, name, size in entries:
        if not _slice_parses(region, pos, size):
            nxt = next((cand for cand in range(pos + 1, min(len(region) - size, pos + RESYNC_WINDOW) + 1)
                        if _slice_parses(region, cand, size)), None)
            if nxt is None:
                raise EvbError(
                    f"{section}+0x{pos:x}: {name} does not parse as JSON - payload is not plaintext JSON "
                    "(compressed/encrypted container?)")
            skipped.append((pos, nxt))
            log.warning("evb: %s+0x%x..0x%x: skipped %d non-JSON payload bytes before %s (%r)",
                        section, pos, nxt, nxt - pos, name, region[pos:pos + 32])
            pos = nxt
        files[name] = region[pos:pos + size]
        pos += size
    return files, skipped


def _write_files(files, out_dir, dry_run=False):
    """Write the recovered documents; identical existing files are left alone."""
    total = sum(len(chunk) for chunk in files.values())
    if dry_run:
        log.info("evb: dry run - would write %d files (%d bytes) to %s",
                 len(files), total, out_dir)
        return {"files": 0, "bytes": 0, "dry_run": True}
    if out_dir is None:
        raise EvbError("no output directory given")
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    for name, chunk in files.items():
        path = os.path.join(out_dir, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                if f.read() == chunk:
                    log.info("evb: %s already up to date", name)
                    continue
            log.warning("evb: overwriting existing %s", os.path.join(os.path.basename(out_dir), name))
        with open(path, "wb") as f:
            f.write(chunk)
        written += 1
    log.info("evb: wrote %d files (%d bytes) to %s", written, total, out_dir)
    return {"files": written, "bytes": total, "dry_run": False}


def _self_check(files):
    """Domain sanity checks on the recovered database -> list of warnings."""
    warnings = []
    for name, chunk in sorted(files.items()):
        if set(chunk) <= {0x30, 0x0A, 0x0D, 0x20}:  # only "0", CR/LF, spaces
            warnings.append(f"{name} looks like filler, not a database file")

    def load(n):
        try:
            return json.loads(files[n].decode("utf-8")) if n in files else None
        except (ValueError, UnicodeDecodeError):
            return None

    infos = load("MapInfos.json")
    if infos is not None:
        missing = [f"Map{m['id']:03d}.json" for m in infos
                   if m and f"Map{m['id']:03d}.json" not in files]
        if missing:
            warnings.append("MapInfos.json references %d map file(s) that are not packed: %s"
                            % (len(missing), ", ".join(missing[:5])))
    system = load("System.json")
    if isinstance(system, dict):
        log.info("evb: System.json: gameTitle=%r hasEncryptedImages=%s hasEncryptedAudio=%s key=%s",
                 system.get("gameTitle"), system.get("hasEncryptedImages"),
                 system.get("hasEncryptedAudio"), bool(system.get("encryptionKey")))
        if system.get("hasEncryptedImages") or system.get("hasEncryptedAudio"):
            log.info("evb: assets are engine-encrypted - run `decrypt` after `build`")
    for warning in warnings:
        log.warning("evb: %s", warning)
    return warnings
