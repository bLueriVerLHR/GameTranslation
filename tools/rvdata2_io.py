#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rvdata2_io.py - Ruby Marshal 4.8 decoder for RPG Maker VX Ace rvdata2 files.

Spec: docs.ruby-lang.org "marshal" (version 4.8, header \\x04\\x08).

Implemented types: nil/true/false, fixnum (long), float, bignum, string,
symbol + symbol links, array, hash + hash links, object (with ivars),
extended object, userdef (raw bytes), user-marshal, struct, regexp, class,
module, instance-var wrapper, link refs.

Decoded values are plain Python: dicts (ordered) for objects/hashes with
string keys ("@name" style), lists, str (utf-8, lossy), int/float/bool/None.
RVGSS-specific: RPG::Table is userdef -> kept as raw bytes (data bytes).
"""
import struct

TYPE_NIL = 0x30        # '0'
TYPE_TRUE = 0x54       # 'T'
TYPE_FALSE = 0x46      # 'F'
TYPE_FIXNUM = 0x69     # 'i'
TYPE_BIGNUM = 0x6C     # 'l'
TYPE_FLOAT = 0x66      # 'f'
TYPE_STRING = 0x22     # '"'
TYPE_SYMBOL = 0x3A     # ':'
TYPE_SYMLINK = 0x3B    # ';'
TYPE_ARRAY = 0x5B      # '['
TYPE_HASH = 0x7B       # '{'
TYPE_HASHLINK = 0x7D   # '}'
TYPE_OBJECT = 0x6F     # 'o'
TYPE_EXTENDED = 0x65   # 'e'
TYPE_USERDEF = 0x75    # 'u'
TYPE_USERMARSHAL = 0x55  # 'U'
TYPE_STRUCT = 0x53     # 'S'
TYPE_REGEXP = 0x2F     # '/'
TYPE_CLASS = 0x63      # 'c'
TYPE_MODULE = 0x6D     # 'm'
TYPE_IVAR = 0x49       # 'I'
TYPE_CLASSVAR = 0x43   # 'C'
TYPE_LINK = 0x40       # '@'


class MarshalError(Exception):
    pass


def _as_signed(b, nbits):
    v = int.from_bytes(b, "little")
    if v >= (1 << (nbits - 1)):
        v -= (1 << nbits)
    return v


class Decoder(object):
    def __init__(self, data, trace=False):
        if not data.startswith(b"\x04\x08"):
            raise MarshalError("not a Ruby Marshal 4.8 stream")
        self.buf = data
        self.pos = 2
        self.symbols = []
        self.links = []
        self.trace = trace
        if trace:
            self.tokens = []

    def _log(self, what):
        if self.trace:
            self.tokens.append((self.pos, what))

    # ------------------------------------------------------------- low level
    def _byte(self):
        if self.pos >= len(self.buf):
            raise MarshalError("unexpected end of stream")
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def _bytes(self, n):
        if self.pos + n > len(self.buf):
            raise MarshalError("unexpected end of stream")
        b = self.buf[self.pos:self.pos + n]
        self.pos += n
        return b

    def read_long(self):
        """Fixnum/long encoding per the marshal spec."""
        b0 = self._byte()
        if b0 == 0x00:
            return 0
        if b0 == 0x01:
            return self._byte()
        if b0 == 0xFF:
            return _as_signed(self._bytes(1), 8)
        if b0 == 0x02:
            return int.from_bytes(self._bytes(2), "little")
        if b0 == 0xFE:
            return _as_signed(self._bytes(2), 16)
        if b0 == 0x03:
            return _as_signed(self._bytes(3), 24)
        if b0 == 0xFD:
            return _as_signed(self._bytes(3), 24)
        if b0 == 0x04:
            return int.from_bytes(self._bytes(4), "little")
        if b0 == 0xFC:
            return _as_signed(self._bytes(4), 32)
        s = struct.unpack("b", bytes([b0]))[0]
        return s - 5 if s >= 0 else s + 5

    def _read_symbol(self):
        n = self.read_long()
        name = self._bytes(n).decode("utf-8", "replace")
        self.symbols.append(name)
        return name

    # ------------------------------------------------------------- top level
    def _read_raw(self):
        t = self._byte()
        c = chr(t)
        self._log("type %s" % c)
        if c == "0":
            return None
        if c == "T":
            return True
        if c == "F":
            return False
        if c == "i":
            return self.read_long()
        if c == "l":
            v = self._read_bignum()
            self.links.append(v)
            return v
        if c == "f":
            v = self._read_float()
            self.links.append(v)
            return v
        if c == '"':
            return self._read_string(register=True)
        if c == ":":
            return self._read_symbol()
        if c == ";":
            idx = self.read_long()
            if idx < 0 or idx >= len(self.symbols):
                raise MarshalError("bad symbol link %d" % idx)
            return self.symbols[idx]
        if c == "[":
            n = self.read_long()
            arr = [None] * n
            self.links.append(arr)
            for i in range(n):
                arr[i] = self._read_raw()
            return arr
        if c == "{":
            n = self.read_long()
            d = {}
            self.links.append(d)
            for _ in range(n):
                k = self._read_raw()
                v = self._read_raw()
                d[k] = v
            return d
        if c == "}":
            idx = self.read_long()
            if idx < 0 or idx >= len(self.links):
                raise MarshalError("bad hash link %d" % idx)
            return self.links[idx]
        if c == "o":
            return self._read_object()
        if c == "e":
            mod = self._read_raw()
            obj = self._read_raw()
            return obj  # module wrapper irrelevant for text extraction
        if c == "u":
            cls = self._read_raw()
            n = self.read_long()
            raw = self._bytes(n)
            self.links.append(raw)
            return raw
        if c == "U":
            cls = self._read_raw()
            obj = self._read_raw()
            res = {"__umarshal__": cls, "data": obj}
            self.links.append(res)
            return res
        if c == "S":
            cls = self._read_raw()
            n = self.read_long()
            d = {"__struct__": cls}
            self.links.append(d)
            for _ in range(n):
                k = self._read_raw()
                v = self._read_raw()
                d[k] = v
            return d
        if c == "/":
            s = self._read_string(register=False)
            opts = self.read_long()
            res = {"__regexp__": s, "options": opts}
            self.links.append(res)
            return res
        if c == "c":
            res = {"__class__": self._read_symbol()}
            self.links.append(res)
            return res
        if c == "m":
            res = {"__module__": self._read_symbol()}
            self.links.append(res)
            return res
        if c == "I":
            obj = self._read_raw()
            n = self.read_long()
            ivars = {}
            for _ in range(n):
                k = self._read_raw()
                v = self._read_raw()
                ivars[k] = v
            # encoding-only wrapper (E: true/false or :UTF-8) -> plain value
            if isinstance(obj, (str, list, dict, int, float, bool)) or obj is None:
                return obj
            return {"__ivar__": obj, "ivars": ivars}
        if c == "C":
            sym = self._read_raw()
            val = self._read_raw()
            return val
        if c == "@":
            idx = self.read_long()
            if idx < 0 or idx >= len(self.links):
                raise MarshalError("bad object link %d" % idx)
            return self.links[idx]
        raise MarshalError("unknown marshal type %r at %d" % (c, self.pos - 1))

    def _read_string(self, register):
        n = self.read_long()
        raw = self._bytes(n)
        s = raw.decode("utf-8", "replace")
        if register:
            self.links.append(s)
        return s

    def _read_object(self):
        cls = self._read_raw()
        n = self.read_long()
        obj = {}
        self.links.append(obj)
        for _ in range(n):
            k = self._read_raw()
            v = self._read_raw()
            obj[k] = v
        if cls:
            obj["__class__"] = cls
        return obj

    def _read_float(self):
        n = self.read_long()
        s = self._bytes(n).decode("ascii", "replace")
        if s in ("inf", "-inf", "nan"):
            return float(s)
        try:
            return float(s)
        except ValueError:
            return s

    def _read_bignum(self):
        sign = self._byte()
        n = self.read_long()
        raw = self._bytes(n)
        v = int.from_bytes(raw, "little", signed=False)
        if sign == ord("-"):
            v = -v
        return v

    def load(self):
        return self._read_raw()


def load_rvdata2(path):
    with open(path, "rb") as f:
        data = f.read()
    return Decoder(data).load()
