#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dxarchive.py - DXArchive v8 (.wolf) container unpacker for Wolf RPG games.

Implements the DXLib DXArchive version 8 container format so that encrypted
Wolf RPG game data (.wolf files under Data/) can be unpacked into plain
directories.  The algorithm is ported from the open-source UberWolf project
(MIT) and the DXLib reference code:

  - DARC_HEAD parsing (64-byte packed header, version 8)
  - per-file key derivation: CRC32(keyString + filename + directory chain)
    split into even/odd bytes, producing a 7-byte XOR key
  - KeyConv XOR stream (position-aware, repeats the 7-byte key)
  - LZ block decode (custom scheme, same as DXLib Decode())
  - Huffman block decode (frequencies delta-coded in the bit stream header)
  - recursive directory/file table traversal with per-file keys
  - antidebug junk removal for protected database files (same 62-byte
    sentinel UberWolf strips)

Only the *standard* v8 layout is supported (cryptVersion 0 / old DXA
keying).  Wolf Pro / ChaCha20 / AES variants are detected and rejected with
a clear error - the project pipeline never touches those.
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

logger = logging.getLogger("dxarchive")

DXA_HEAD = 0x5844  # "DX" little-endian
DXA_VER = 0x0008
DXA_VER_MIN = 0x0008
DXA_KEY_BYTES = 7
DXA_BUFFERSIZE = 0x1000000

DXA_FLAG_NO_KEY = 0x00000001
DXA_FLAG_NO_HEAD_PRESS = 0x00000002

MIN_COMPRESS = 4
MAX_COPYSIZE = 0x1FFF + MIN_COMPRESS

# The 62-byte sentinel UberWolf strips from protected database files.
# "Extracting data from encrypted files violates the guidelines." (sic)
ANTI_UNPACK_DATA = bytes(
    b"Extracting data from encrypted files violates the guidelines." + b"\x00"
)
UNPACK_PROTECTION_FILES = {
    "game.dat",
    "cdatabase.dat",
    "database.dat",
    "commonevent.dat",
}

# Default key string baked into the engine (DXLIBARC).  Games encrypted with
# the Wolf RPG editor use a per-game keyString passed via --key.
DEFAULT_KEY_STRING = b"DXLIBARC"

HEAD_STRUCT = struct.Struct("<HHIQQQQIIB15s")


def _crc32(data: bytes) -> int:
    """Standard CRC32 as used by DXLib's HashCRC32 (init 0xffffffff, xor out)."""
    return zlib.crc32(data) & 0xFFFFFFFF


def key_create(source: bytes) -> bytes:
    """Derive the 7-byte archive key from a key string (DXLib KeyCreate).

    Even-indexed bytes feed one CRC32, odd-indexed bytes another; the first
    CRC fills key[0..3], the second key[4..6].
    """
    src = source
    if len(src) < 4:
        src = src + DEFAULT_KEY_STRING
    even = src[0::2]
    odd = src[1::2]
    c0 = _crc32(even)
    c1 = _crc32(odd)
    # key[0..3] = CRC32 of even bytes, key[4..6] = low 3 bytes of CRC32 of odd
    return struct.pack("<II", c0, c1)[:7]


def key_conv(data: bytearray, position: int, key: bytes) -> None:
    """XOR a buffer with the repeating key, starting at key offset position."""
    if not key:
        return
    n = len(key)
    j = position % n
    for i in range(len(data)):
        data[i] ^= key[j]
        j += 1
        if j == n:
            j = 0


class DxaHeader:
    __slots__ = (
        "head",
        "version",
        "head_size",
        "data_start",
        "name_table_start",
        "file_table_start",
        "dir_table_start",
        "char_code",
        "flags",
        "huffman_kb",
    )

    def __init__(self, data: bytes):
        (
            self.head,
            self.version,
            self.head_size,
            self.data_start,
            self.name_table_start,
            self.file_table_start,
            self.dir_table_start,
            self.char_code,
            self.flags,
            self.huffman_kb,
            _reserve,
        ) = HEAD_STRUCT.unpack_from(data, 0)
        if self.head != DXA_HEAD:
            raise ValueError("not a DXArchive file (bad header magic)")
        if self.version < DXA_VER_MIN or self.version > DXA_VER:
            raise ValueError(
                f"unsupported DXArchive version {self.version} "
                f"(only v{DXA_VER} is supported)"
            )

    @property
    def no_key(self) -> bool:
        return (self.flags & DXA_FLAG_NO_KEY) != 0

    @property
    def no_head_press(self) -> bool:
        return (self.flags & DXA_FLAG_NO_HEAD_PRESS) != 0

    @property
    def crypt_version(self) -> int:
        return self.flags >> 16


def lz_decode(src: bytes, dest_size: int) -> bytes:
    """Decompress one LZ block (DXLib Decode)."""
    if len(src) < 9:
        raise ValueError("LZ block too small")
    destsize, srcsize_full, keycode = struct.unpack_from("<IIB", src, 0)
    srcsize = srcsize_full - 9
    dest = bytearray()
    sp = 9
    while srcsize > 0:
        b0 = src[sp]
        if b0 != keycode:
            dest.append(b0)
            sp += 1
            srcsize -= 1
            continue
        if src[sp + 1] == keycode:
            dest.append(keycode)
            sp += 2
            srcsize -= 2
            continue
        code = src[sp + 1]
        if code > keycode:
            code -= 1
        sp += 2
        srcsize -= 2
        conbo = code >> 3
        if code & 0x4:
            conbo |= src[sp] << 5
            sp += 1
            srcsize -= 1
        conbo += MIN_COMPRESS
        indexsize = code & 0x3
        if indexsize == 0:
            index = src[sp]
            sp += 1
            srcsize -= 1
        elif indexsize == 1:
            index = struct.unpack_from("<H", src, sp)[0]
            sp += 2
            srcsize -= 2
        else:
            index = struct.unpack_from("<H", src, sp)[0] | (src[sp + 2] << 16)
            sp += 3
            srcsize -= 3
        index += 1
        if index < conbo:
            num = index
            while conbo > num:
                start = len(dest) - num
                dest.extend(dest[start : start + num])
                conbo -= num
                num += num
            if conbo:
                start = len(dest) - num
                dest.extend(dest[start : start + conbo])
        else:
            start = len(dest) - index
            dest.extend(dest[start : start + conbo])
    if len(dest) != destsize:
        # The reference implementation does not verify destsize; the LZ
        # stream itself is authoritative.  Only warn here.
        logger.warning(
            "LZ size mismatch: header claims %d bytes, decoded %d",
            destsize,
            len(dest),
        )
    return bytes(dest)


class _BitReader:
    """MSB-first bit stream reader mirroring DXLib BitStream_Read."""

    def __init__(self, data: bytes):
        self.data = data
        self.byte_idx = 0
        self.bit_idx = 0

    def read(self, n: int) -> int:
        result = 0
        for i in range(n):
            bit = (self.data[self.byte_idx] >> (7 - self.bit_idx)) & 1
            result |= bit << (n - 1 - i)
            self.bit_idx += 1
            if self.bit_idx == 8:
                self.byte_idx += 1
                self.bit_idx = 0
        return result

    @property
    def bytes_consumed(self) -> int:
        return self.byte_idx + (1 if self.bit_idx else 0)


def huffman_decode(src: bytes) -> bytes:
    """Decompress one Huffman block (DXLib Huffman_Decode)."""
    br = _BitReader(src)
    bitnum_a = br.read(6) + 1
    original_size = br.read(bitnum_a)
    bitnum_b = br.read(6) + 1
    _press_size = br.read(bitnum_b)
    weight = [0] * 256
    b = br.read(3) + 1
    minus = br.read(1)
    save = br.read(b * 2)
    weight[0] = save
    for i in range(1, 256):
        b = br.read(3) + 1
        minus = br.read(1)
        save = br.read(b * 2)
        weight[i] = weight[i - 1] - save if minus else weight[i - 1] + save
    head_size = br.bytes_consumed

    # Build the Huffman tree (same merge rule as the encoder).
    nodes = []
    for i in range(256):
        nodes.append({"weight": weight[i], "child": (-1, -1), "parent": -1})
    node_num = 256
    data_num = 256
    while data_num > 1:
        min1 = -1
        min2 = -1
        for idx in range(len(nodes)):
            if nodes[idx]["parent"] != -1:
                continue
            if min1 == -1 or nodes[min1]["weight"] > nodes[idx]["weight"]:
                min2 = min1
                min1 = idx
            elif min2 == -1 or nodes[min2]["weight"] > nodes[idx]["weight"]:
                min2 = idx
        nodes.append(
            {
                "weight": nodes[min1]["weight"] + nodes[min2]["weight"],
                "child": (min1, min2),
                "parent": -1,
            }
        )
        nodes[min1]["parent"] = node_num
        nodes[min2]["parent"] = node_num
        nodes[min1]["index"] = 0
        nodes[min2]["index"] = 1
        node_num += 1
        data_num -= 1

    # Compute the code bit array for every node (leaves + internal).
    for i in range(256 + 254):
        node = nodes[i]
        node["bitnum"] = 0
        node["bitarray"] = 0
        idx = i
        temp = 0
        temp_count = 0
        while nodes[idx]["parent"] != -1:
            temp = (temp << 1) | nodes[idx]["index"]
            temp_count += 1
            idx = nodes[idx]["parent"]
        node["bitnum"] = temp_count
        node["bitarray"] = 0
        for bit in range(temp_count):
            node["bitarray"] |= ((temp >> bit) & 1) << bit
        node["bitarray"] &= 0xFFFF

    # Fast lookup table for codes up to 9 bits.
    node_index_table = [-1] * 512
    for i in range(512):
        for j in range(256 + 254):
            if nodes[j]["bitnum"] > 9 or nodes[j]["bitnum"] == 0:
                continue
            mask = (1 << nodes[j]["bitnum"]) - 1
            if (i & mask) == (nodes[j]["bitarray"] & mask):
                node_index_table[i] = j
                break

    # Decode payload.
    payload_start = head_size
    press_idx = 0
    bit_counter = 0
    bit_data = src[payload_start]  # reference code preloads the first byte
    dest = bytearray()
    dest_size = original_size
    while len(dest) < dest_size:
        if len(dest) >= dest_size - 17:
            node_idx = len(nodes) - 1  # root
            while node_idx > 255:
                if bit_counter == 8:
                    press_idx += 1
                    bit_data = src[payload_start + press_idx]
                    bit_counter = 0
                idx = bit_data & 1
                bit_data >>= 1
                bit_counter += 1
                node_idx = nodes[node_idx]["child"][idx]
            dest.append(node_idx)
            continue
        if bit_counter == 8:
            press_idx += 1
            bit_data = src[payload_start + press_idx]
            bit_counter = 0
        cur = bit_data | (src[payload_start + press_idx + 1] << (8 - bit_counter))
        cur &= 0x1FF
        node_idx = node_index_table[cur]
        bit_counter += nodes[node_idx]["bitnum"]
        if bit_counter >= 16:
            press_idx += 2
            bit_counter -= 16
            bit_data = src[payload_start + press_idx] >> bit_counter
        elif bit_counter >= 8:
            press_idx += 1
            bit_counter -= 8
            bit_data = src[payload_start + press_idx] >> bit_counter
        else:
            bit_data = cur >> nodes[node_idx]["bitnum"]
        while node_idx > 255:
            if bit_counter == 8:
                press_idx += 1
                bit_data = src[payload_start + press_idx]
                bit_counter = 0
            idx = bit_data & 1
            bit_data >>= 1
            bit_counter += 1
            node_idx = nodes[node_idx]["child"][idx]
        dest.append(node_idx)
    return bytes(dest)


def get_original_name(name_table: bytes, name_addr: int) -> str:
    """Decode a stored file name.

    Layout: u16 byte-length/4, u16 parity, uppercased name (len*4 bytes),
    then the original (SJIS) name.  The original name lives at
    offset 4 + len*4 inside the entry.
    """
    raw = name_table[name_addr:]
    length_words = struct.unpack_from("<H", raw, 0)[0]
    orig = raw[4 + length_words * 4 :]
    end = orig.find(b"\x00")
    if end != -1:
        orig = orig[:end]
    return orig.decode("shift_jis", errors="replace")


def create_key_file_string(
    key_string: bytes,
    name_table: bytes,
    file_table: bytes,
    dir_table: bytes,
    directory: "DxaDirectory",
    file_head: "DxaFileHead",
    char_code_format: int,
) -> bytes:
    """Build the per-file key string: key + file name + directory chain."""
    parts = bytearray(key_string)
    fname = name_table[file_head.name_addr + 4 :]
    end = fname.find(b"\x00")
    if end != -1:
        fname = fname[:end]
    parts += fname
    cur = directory
    while cur.parent_addr != 0xFFFFFFFFFFFFFFFF:
        dfile = DxaFileHead.from_bytes(file_table, cur.dir_addr)
        dname = name_table[dfile.name_addr + 4 :]
        dname_end = dname.find(b"\x00")
        if dname_end != -1:
            dname = dname[:dname_end]
        parts += dname
        cur = DxaDirectory.from_bytes(dir_table, cur.parent_addr)
    return bytes(parts)


class DxaFileHead:
    __slots__ = (
        "name_addr",
        "attributes",
        "create",
        "last_access",
        "last_write",
        "data_addr",
        "data_size",
        "press_size",
        "huff_press_size",
    )
    _SIZE = 9 * 8  # 9 u64 fields
    _STRUCT = struct.Struct("<Q Q QQQ Q Q Q Q")

    def __init__(
        self,
        name_addr,
        attributes,
        create,
        last_access,
        last_write,
        data_addr,
        data_size,
        press_size,
        huff_press_size,
    ):
        self.name_addr = name_addr
        self.attributes = attributes
        self.create = create
        self.last_access = last_access
        self.last_write = last_write
        self.data_addr = data_addr
        self.data_size = data_size
        self.press_size = press_size
        self.huff_press_size = huff_press_size

    @classmethod
    def from_bytes(cls, table: bytes, offset: int) -> "DxaFileHead":
        return cls(*cls._STRUCT.unpack_from(table, offset))

    @property
    def is_dir(self) -> bool:
        return (self.attributes & 0x10) != 0  # FILE_ATTRIBUTE_DIRECTORY

    @property
    def is_compressed(self) -> bool:
        return self.press_size != 0xFFFFFFFFFFFFFFFF

    @property
    def is_huffman(self) -> bool:
        return self.huff_press_size != 0xFFFFFFFFFFFFFFFF


class DxaDirectory:
    __slots__ = ("dir_addr", "parent_addr", "file_num", "file_head_addr")
    _STRUCT = struct.Struct("<QQQQ")

    def __init__(self, dir_addr, parent_addr, file_num, file_head_addr):
        self.dir_addr = dir_addr
        self.parent_addr = parent_addr
        self.file_num = file_num
        self.file_head_addr = file_head_addr

    @classmethod
    def from_bytes(cls, table: bytes, offset: int) -> "DxaDirectory":
        return cls(*cls._STRUCT.unpack_from(table, offset))


def unpack_archive(
    archive_path: str,
    out_dir: str,
    key_string: bytes,
    skip_protection_cleanup: bool = False,
) -> int:
    """Unpack one .wolf archive into out_dir.  Returns the file count."""
    os.makedirs(out_dir, exist_ok=True)
    with open(archive_path, "rb") as f:
        raw = f.read()

    if len(raw) < 64:
        raise ValueError("file too small to be a DXArchive")
    head = DxaHeader(raw[:64])
    if head.crypt_version:
        raise ValueError(
            f"unsupported Wolf crypt version 0x{head.crypt_version:x} "
            "(only legacy v8 DXA is supported)"
        )

    global_key = key_create(key_string)

    if head.no_head_press:
        raise ValueError("uncompressed-header archives not implemented yet")

    # The whole (Huffman+LZ compressed) header block sits at the END of the
    # file, starting at FileNameTableStartAddress.
    huff_head = bytearray(raw[head.name_table_start :])
    key_conv(huff_head, 0, None if head.no_key else global_key)
    lz_head = huffman_decode(bytes(huff_head))
    head_buffer = _lz_decode_with_size(lz_head)

    name_table = head_buffer
    file_table = head_buffer[head.file_table_start :]
    dir_table = head_buffer[head.dir_table_start :]

    def decode_one(file: DxaFileHead, directory: DxaDirectory, fout) -> None:
        if file.data_size == 0:
            return
        # Per-file key: derived from keyString + name chain.
        fkey = None
        if not head.no_key:
            ks = create_key_file_string(
                key_string, name_table, file_table, dir_table, directory,
                file, head.char_code,
            )
            fkey = key_create(ks)
        data_start = head.data_start + file.data_addr
        if file.is_compressed:
            # LZ-compressed block (possibly with Huffman front/back windows).
            if file.is_huffman:
                # Read the encrypted Huffman payload, decrypt, decode.
                huff = bytearray(raw[data_start : data_start + file.huff_press_size])
                key_conv(huff, file.data_size, fkey)
                huff_data = huffman_decode(bytes(huff))
                if (
                    head.huffman_kb != 0xFF
                    and file.press_size > head.huffman_kb * 2048
                ):
                    # Huffman covers only the first/last KB windows; the
                    # middle is stored raw.  huff_data layout:
                    # [front window][back window].
                    move = head.huffman_kb * 1024
                    lz_full = bytearray(file.press_size)
                    lz_full[0:move] = huff_data[0:move]
                    lz_full[file.press_size - move :] = huff_data[
                        move : 2 * move
                    ]
                    mid_start = data_start + file.huff_press_size
                    mid_size = file.press_size - move * 2
                    mid = bytearray(raw[mid_start : mid_start + mid_size])
                    key_conv(
                        mid,
                        file.data_size + file.huff_press_size,
                        fkey,
                    )
                    lz_full[move : move + mid_size] = mid
                else:
                    lz_full = huff_data
                out_data = lz_decode(bytes(lz_full), file.data_size)
            else:
                temp = bytearray(raw[data_start : data_start + file.press_size])
                key_conv(temp, file.data_size, fkey)
                out_data = lz_decode(bytes(temp), file.data_size)
        else:
            # Uncompressed data (possibly with Huffman front/back windows).
            if file.is_huffman:
                huff = bytearray(raw[data_start : data_start + file.huff_press_size])
                key_conv(huff, file.data_size, fkey)
                huff_data = huffman_decode(bytes(huff))
                if (
                    head.huffman_kb != 0xFF
                    and file.data_size > head.huffman_kb * 2048
                ):
                    move = head.huffman_kb * 1024
                    full = bytearray(file.data_size)
                    full[0:move] = huff_data[0:move]
                    full[file.data_size - move :] = huff_data[
                        move : 2 * move
                    ]
                    mid_start = data_start + file.huff_press_size
                    mid_size = file.data_size - move * 2
                    mid = bytearray(raw[mid_start : mid_start + mid_size])
                    key_conv(
                        mid,
                        file.data_size + file.huff_press_size,
                        fkey,
                    )
                    full[move : move + mid_size] = mid
                    out_data = bytes(full)
                else:
                    out_data = huff_data
            else:
                out_data = bytearray(
                    raw[data_start : data_start + file.data_size]
                )
                key_conv(out_data, file.data_size, fkey)
                out_data = bytes(out_data)
        fout.write(out_data)

    file_count = 0

    def walk(directory: DxaDirectory, rel_dir: str) -> None:
        nonlocal file_count
        base = out_dir if rel_dir == "" else os.path.join(out_dir, rel_dir)
        if rel_dir:
            os.makedirs(base, exist_ok=True)
        for i in range(directory.file_num):
            fh = DxaFileHead.from_bytes(
                file_table, directory.file_head_addr + i * DxaFileHead._SIZE
            )
            name = get_original_name(name_table, fh.name_addr)
            if fh.is_dir:
                walk(DxaDirectory.from_bytes(dir_table, fh.data_addr), name)
            else:
                dest_path = os.path.join(base, name)
                with open(dest_path, "wb") as fout:
                    decode_one(fh, directory, fout)
                if not skip_protection_cleanup and (
                    os.path.basename(dest_path).lower() in UNPACK_PROTECTION_FILES
                ):
                    _strip_protection(dest_path)
                file_count += 1

    walk(DxaDirectory.from_bytes(dir_table, 0), "")
    return file_count


def _lz_decode_with_size(lz_head: bytes) -> bytes:
    """LZ-decode the header block using the destsize embedded in the data."""
    if len(lz_head) < 4:
        raise ValueError("LZ header block too small")
    destsize = struct.unpack_from("<I", lz_head, 0)[0]
    return lz_decode(lz_head, destsize)


def _strip_protection(path: str) -> None:
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(ANTI_UNPACK_DATA):
        with open(path, "wb") as f:
            f.write(data[len(ANTI_UNPACK_DATA) :])


def cmd(archive: Annotated[str, cliutil.Argument(help="path to the .wolf file")],
        out_dir: Annotated[str, cliutil.Argument(help="output directory")],
        key: Annotated[str, cliutil.Option(
            "--key", help="game key string (per-game; defaults to the engine "
            "default). Passed explicitly: the key is game data, never "
            "hardcoded here.")] = None,
        no_protection_cleanup: Annotated[bool, cliutil.Option(
            "--no-protection-cleanup", help="keep the 62-byte "
            "unpack-protection sentinel in database files")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    key_bytes = key.encode("ascii") if key else DEFAULT_KEY_STRING
    try:
        n = unpack_archive(archive, out_dir, key_bytes, no_protection_cleanup)
    except (ValueError, OSError) as e:
        return cliutil.fail(str(e))
    print(f"unpacked {n} files from {archive}")
    return 0


# argparse showed the module docstring as the description; a single-command
# Typer app renders the command's docstring, so point it at the same text
# instead of keeping a second copy in sync.
cmd.__doc__ = __doc__

app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="dxarchive.py")


if __name__ == "__main__":
    sys.exit(main())
