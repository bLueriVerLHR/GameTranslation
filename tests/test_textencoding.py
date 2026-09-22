#!/usr/bin/env python3
"""The shared scenario-encoding contract (PLAN Phase 5 task 5, defect C).

Two engines (.ks readers for KiriKiri and TyranoScript) decode bytes from
other people's game builds, so the heuristic is core (`rpgmaker.textencoding`)
rather than a copy in each engine.  Measured facts this file pins:

* Over 400 random buffers the detected *candidate* rejects the bytes 288
  times - so "never raise" has to be the decoder's job, not the detector's
  promise.
* A BOM-less UTF-16 stream is identified by where its null bytes sit: on the
  odd offsets for little-endian, the even offsets for big-endian.  That
  inference was **inverted** in the original implementation (every BOM-less
  UTF-16 scenario decoded to garbage); `TestByteOrder` is the regression.
"""
import codecs
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from rpgmaker import textencoding  # noqa: E402

TEXT = "本文です。\n"

#: A realistic KAG3 scenario body - long enough that the null-byte heuristic
#: fires, which a short string does not (measured: 12 bytes / 1 null is below
#: the threshold, so the short text takes the Shift-JIS path instead).
SCENARIO = ('*start\n[bg storage="bg01.png"]\n'
            "こんにちは、いい天気ですね。\n[r]\n[end]\n")

#: (label, raw bytes, expected candidate) for the shapes a real .ks carries.
#: The BOM forms are built explicitly: the `utf-16-be` codec writes no BOM, so
#: `TEXT.encode("utf-16-be")` is the *BOM-less* big-endian case, which takes the
#: null-parity path instead (`TestByteOrder`).
SHAPES = [
    ("utf-8", TEXT.encode("utf-8"), "utf-8"),
    ("utf-16 le with bom", TEXT.encode("utf-16"), "utf-16"),
    ("utf-16 be with bom",
     codecs.BOM_UTF16_BE + TEXT.encode("utf-16-be"), "utf-16-be"),
    ("shift_jis", TEXT.encode("shift_jis"), "shift_jis"),
]


class TestDetectEncoding:
    @pytest.mark.parametrize("label,raw,expected",
                             SHAPES, ids=[s[0] for s in SHAPES])
    def test_names_the_encoder(self, label, raw, expected):
        assert textencoding.detect_encoding(raw) == expected, label

    def test_empty_input_is_utf8(self):
        """The empty file is the one case with no evidence, so it must not
        fall through to the Shift-JIS last resort (a lie about zero bytes)."""
        assert textencoding.detect_encoding(b"") == "utf-8"

    def test_the_result_is_only_a_candidate(self):
        """The docstring promises a candidate, so pin the honest behaviour.

        If someone "fixes" this by making detect_encoding total, `decode_text`
        stops being the guard and the replacement policy is lost silently.
        """
        raw = b"abc\x81\x30\xff\xfe"
        enc = textencoding.detect_encoding(raw)
        with pytest.raises(UnicodeDecodeError):
            raw.decode(enc)
    def test_candidates_are_ordered_most_specific_first(self):
        """`utf-8` must be tried before the Shift-JIS fallbacks: cp932 decodes
        any byte, so a fallback first would make UTF-8 files undetectable."""
        assert textencoding.CANDIDATES[0] == "utf-8"
        assert "cp932" in textencoding.CANDIDATES

    def test_random_buffers_really_do_produce_bad_candidates(self):
        """The 288/400 measurement, re-run here so the docstring cannot rot
        into a claim about a heuristic that has since been made total."""
        import random
        rng = random.Random(7)
        bad = 0
        for _ in range(200):
            raw = bytes(rng.randrange(256) for _ in range(rng.randrange(4, 40)))
            try:
                raw.decode(textencoding.detect_encoding(raw))
            except UnicodeDecodeError:
                bad += 1
        assert bad > 40, (
            "the candidate heuristic became almost always correct (%d/200); "
            "if that is deliberate, `decode_text`'s replacement policy needs "
            "re-justifying in rpgmaker/textencoding.py" % bad)


class TestByteOrder:
    """The inverted BOM-less branch.  Real defect, found when the two engine
    copies were merged: each copy had it, so neither could correct the other.
    """

    def test_no_bom_little_endian(self):
        raw = SCENARIO.encode("utf-16-le")
        assert raw[0::2].count(b"\x00") == 0
        assert raw[1::2].count(b"\x00") > 0
        assert textencoding.detect_encoding(raw) == "utf-16"

    def test_no_bom_big_endian(self):
        raw = SCENARIO.encode("utf-16-be")
        assert raw[0::2].count(b"\x00") > 0
        assert raw[1::2].count(b"\x00") == 0
        assert textencoding.detect_encoding(raw) == "utf-16-be"

    @pytest.mark.parametrize("enc,expected", [("utf-16-le", "utf-16"),
                                              ("utf-16-be", "utf-16-be")])
    def test_a_bom_less_scenario_survives_a_round_trip(self, enc, expected):
        """The end-to-end statement: a BOM-less UTF-16 .ks must read back
        exactly, in either byte order.  Before the fix both directions produced
        undecodable garbage, which is how a translation run would import an
        empty or nonsense key table without any error."""
        raw = SCENARIO.encode(enc)
        name = textencoding.detect_encoding(raw)
        assert name == expected
        assert textencoding.decode_text(raw, name) == SCENARIO

    def test_both_byte_orders_are_distinguished(self):
        """A heuristic that answered one value for both would pass the two
        tests above separately by accident of the expected strings; this
        asserts the discrimination itself."""
        le = textencoding.detect_encoding(SCENARIO.encode("utf-16-le"))
        be = textencoding.detect_encoding(SCENARIO.encode("utf-16-be"))
        assert le != be


class TestDecodeText:
    def test_a_named_codec_that_rejects_the_bytes_is_replaced(self):
        # Measured: cp932 rejects `\x81 0x30` as an illegal multibyte
        # sequence, so the decoder must replace rather than raise.
        raw = b"abc\x810def"
        with pytest.raises(UnicodeDecodeError):
            raw.decode("cp932")
        assert textencoding.decode_text(raw, "cp932") == "abc\ufffd0def"

    def test_an_unknown_codec_name_does_not_escape_as_lookup_error(self):
        """`LookupError` is not a decode failure the caller expects, and a
        manifest-driven codec name can be anything, so it must be handled."""
        assert textencoding.decode_text(b"abc", "not-a-codec") == "abc"

    @pytest.mark.parametrize("enc", ["utf-8", "shift_jis", "cp932", "utf-16",
                                     "utf-16-be", "ascii", "latin-1"])
    def test_never_raises_for_any_named_codec(self, enc):
        for raw in (b"", b"\x00", b"\xff\xfe\x00", b"\x81", bytes(range(256))):
            textencoding.decode_text(raw, enc)   # must not raise


class TestLoadTextFile:
    def test_round_trip_for_every_shape(self, tmp_path):
        for label, raw, _enc in SHAPES:
            path = tmp_path / ("{}.ks".format(label.replace(" ", "_")))
            path.write_bytes(raw)
            text, enc = textencoding.load_text_file(str(path))
            assert text == TEXT, label
            assert enc, label

    def test_the_bom_is_stripped(self, tmp_path):
        """Every downstream parser matches on the first character of the first
        line, so a surviving BOM breaks the file's first tag."""
        path = tmp_path / "bom.ks"
        path.write_bytes(TEXT.encode("utf-8-sig"))
        text, _enc = textencoding.load_text_file(str(path))
        assert not text.startswith("\ufeff")
        assert text == TEXT

    def test_a_utf16_file_keeps_its_bom_out_of_the_text(self, tmp_path):
        path = tmp_path / "u16.ks"
        path.write_bytes(TEXT.encode("utf-16"))
        text, _enc = textencoding.load_text_file(str(path))
        assert text == TEXT

    def test_a_bom_less_utf16_file_keeps_its_tags(self, tmp_path):
        """The practical stake of the byte-order bug: a mangled first line
        loses the *label or tag the scenario jumps to."""
        path = tmp_path / "nobom.ks"
        path.write_bytes(SCENARIO.encode("utf-16-le"))
        text, _enc = textencoding.load_text_file(str(path))
        assert text == SCENARIO
        assert text.startswith("*start")

    def test_an_unreadable_file_raises_oserror(self, tmp_path):
        """A missing file is a different failure from an undecodable byte, and
        collapsing them would hide a path bug behind a replacement char."""
        with pytest.raises(OSError):
            textencoding.load_text_file(str(tmp_path / "absent.ks"))


class TestBothEnginesShareOneImplementation:
    """PLAN Phase 3 task 7: an engine may import core, never another engine.

    The first version of the shared decode lived in `kirikiri.ks_extract` with
    `tyrano.tyrano_extract` importing it, which is a cross-engine edge.  These
    pins catch a re-copy, which is how the two engines drifted apart (and how
    the byte-order bug survived in both).
    """

    def test_kirikiri_reexports_the_core_functions(self):
        from kirikiri import ks_extract
        assert ks_extract.detect_encoding is textencoding.detect_encoding
        assert ks_extract.decode_text is textencoding.decode_text

    def test_tyrano_reexports_the_core_functions(self):
        from tyrano import tyrano_extract
        assert tyrano_extract.detect_encoding is textencoding.detect_encoding
        assert tyrano_extract.decode_text is textencoding.decode_text

    def test_tyrano_does_not_import_the_kirikiri_engine(self):
        """Read the source, not the runtime: an import that only fires inside a
        function body is still a boundary violation, and this asserts the
        specific defect that was fixed here."""
        path = os.path.join(REPO_ROOT, "tyrano", "tyrano_extract.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        assert "kirikiri" not in source, (
            "tyrano/tyrano_extract.py imports the KiriKiri engine again; the "
            "shared encoding helper lives in rpgmaker/textencoding.py")

    def test_the_engines_agree_on_every_shape(self):
        from kirikiri import ks_extract
        from tyrano import tyrano_extract
        for label, raw, _enc in SHAPES:
            assert (ks_extract.detect_encoding(raw)
                    == tyrano_extract.detect_encoding(raw)), label
        no_bom = SCENARIO.encode("utf-16-le")
        assert (ks_extract.detect_encoding(no_bom)
                == tyrano_extract.detect_encoding(no_bom))

    def test_both_engines_read_a_bom_less_scenario_the_same_way(self, tmp_path):
        """The behaviour the deduplication buys: one answer for one file."""
        from kirikiri import ks_extract
        from tyrano import tyrano_extract
        path = tmp_path / "shared.ks"
        path.write_bytes(SCENARIO.encode("utf-16-be"))
        assert (ks_extract.load_ks(str(path))
                == tyrano_extract.load_ks(str(path))
                == (SCENARIO, "utf-16-be"))
