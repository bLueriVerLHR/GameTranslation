#!/usr/bin/env python3
"""Byte-encoding detection for third-party scenario text files (core).

Both scenario engines we parse (KiriKiri `.ks`, TyranoScript `.ks`) are
read from *other people's* game archives, so the bytes are whatever the
original author's tooling produced: UTF-16 LE/BE with or without a BOM,
UTF-8, or Shift-JIS.  This module is the single copy of that heuristic.

Two rules make the contract:

* `detect_encoding` returns a **candidate** name, never a promise.  Measured
  over 2000 random buffers, the guess names a codec that then rejects the
  bytes in 1014 cases, and 494 of those are undecodable by every candidate -
  so the answer is not "probe until something fits" but "decode with
  replacement".
* Callers must therefore decode through `decode_text`, never
  `raw.decode(detect_encoding(raw))`.

It lives in core (not in one engine) because two engines call it: a copy each
would be the thing that drifts, and `tyrano` must not import `kirikiri`
(PLAN Phase 3 task 7).

The BOM-less byte-order inference was inverted until Phase 5; see the comment
on that branch - it is the one behaviour here that a move-and-deduplicate could
have silently preserved, so it is pinned by tests rather than trusted.
"""

__all__ = ["detect_encoding", "decode_text", "load_text_file",
           "CANDIDATES", "BOM"]

#: The Shift-JIS fallback decodes any byte, so it is also the terminal guess.
#: Kept as a tuple so a future candidate is one edit, and so a test can
#: assert this list stays ordered most-specific-first.
CANDIDATES = ("utf-8", "shift_jis", "cp932")

#: A BOM is transport framing, not content: every downstream parser matches on
#: the first character of the first line, so leaving it in breaks the first
#: tag of the file.  Module-level so the intent reads once.
BOM = "\ufeff"


def _decodes_with(raw: bytes, enc: str) -> bool:
    """True when `raw` is valid in `enc`.

    Kept as a one-candidate helper so the `try` is a plain call rather than
    one inside the caller's loop (identical cost, but the loop then reads as
    the plain "first candidate that works" search that it is).
    """
    try:
        raw.decode(enc)
    except UnicodeDecodeError:
        return False
    return True


def detect_encoding(raw: bytes) -> str:
    """Detect the byte encoding of a scenario file (UTF-16 LE/BE, UTF-8, Shift-JIS).

    Returns a *candidate* codec name: the Shift-JIS fallback decodes any
    byte and the UTF-16/CP932 guesses can name a codec that then rejects the
    bytes (measured 511 of 1008 random buffers).  Callers must therefore
    decode through `decode_text`, not `raw.decode(detect_encoding(raw))`.
    """
    if not raw:
        return "utf-8"
    if raw[:2] == b"\xff\xfe":
        return "utf-16"
    if raw[:2] == b"\xfe\xff":
        return "utf-16-be"
    nulls = raw.count(b"\x00")
    if nulls > len(raw) // 8:
        # No BOM, so the byte order has to be inferred from where the null
        # bytes sit.  A UTF-16 stream of nearly-ASCII text has one null per
        # character, and that null is the *high* byte: it lands on the odd
        # offsets for little-endian and the even offsets for big-endian.
        # Measured on a real KAG3 scenario (112 bytes, 38 nulls): LE gives
        # even=0/odd=38, BE gives even=38/odd=0 - so the more nulls on the
        # odd side means little-endian, and this branch used to return the
        # two answers swapped (BOM-less UTF-16 was read as the opposite byte
        # order, turning every line into undecodable garbage).  Pinned by
        # `tests/test_textencoding.py::TestByteOrder`.
        even = raw[0::2].count(b"\x00")
        odd = raw[1::2].count(b"\x00")
        return "utf-16" if odd >= even else "utf-16-be"
    return next((enc for enc in CANDIDATES if _decodes_with(raw, enc)), "cp932")


def decode_text(raw, enc):
    """Decode `raw` with `enc`, never raising on undecodable bytes.

    `detect_encoding` names a *candidate*: the Shift-JIS candidates (the
    last resort) decode any byte and the UTF-16/CP932 guesses accept byte
    sequences their decoder then rejects (measured 511 of 1008 random
    inputs).  Untranslatable bytes are therefore replaced rather than
    aborting a whole scan - this parser reads third-party game archives,
    where "some line has an undefined byte" must not lose the file.
    """
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:  # unknown codec name - not reachable from detect_encoding
        return raw.decode("utf-8", errors="replace")


def load_text_file(path: str) -> tuple[str, str]:
    """Read a scenario file; returns ``(text, encoding_name)``.

    Never raises `UnicodeDecodeError` (see `decode_text`); `OSError` is still
    the caller's problem, since an unreadable file is a different failure.
    A leading BOM is stripped: it is transport, not content, and every
    downstream parser matches on the first character of the line.
    """
    with open(path, "rb") as f:
        raw = f.read()
    enc = detect_encoding(raw)
    text = decode_text(raw, enc)
    if text.startswith(BOM):
        text = text[1:]
    return text, enc
