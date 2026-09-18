#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The kana classes must agree - the ranges live in one place.

Two modules decide "is this string still Japanese?":

* ``tools/japanese_utils.py:KANA`` - the canonical class (it deliberately
  excludes the kana-block punctuation: ``ー``/``・`` appear in translated Chinese
  too), used by every QC/bake tool,
* ``translation/codes.py:KANA_LETTERS_RE`` - the v2 library's residue test.

``tools`` may import ``translation``, not the other way round, so the two are
written in two files; this test pins their agreement character by character.
The coarse ``KANA_RE`` answers a *different* question ("is this text at all?",
used for code parameters and key candidates) and must stay a superset of the
letters class.
"""
import re

from translation import codes

import japanese_utils


#: kana-block punctuation/symbols: must NOT count as residue kana
KANA_PUNCT = ["\u30a0", "\u309b", "\u309c", "\u309d", "\u309e",
              "\u30fb", "\u30fc", "\u30fd", "\u30fe", "\uff65", "\uff70",
              "\uff9f"]
#: halfwidth voicing mark: a mark, not a letter - the one intended divergence
HALFWIDTH_VOICING = "\uff9e"
#: letters: must count as residue kana
KANA_LETTERS = ["\u3041", "\u3042", "\u3093", "\u3096", "\u30a1", "\u30a2",
                "\u30f9", "\u30fa", "\u30f6", "\uff71", "\uff8c"]
NOT_KANA = ["a", "1", "\u4e2d", "\u3005", "\u30ff", "\u3040", "\uff00",
            "\u3000"]


def _differ(cls_a, cls_b, lo, hi):
    """Characters in [lo, hi) the two classes classify differently."""
    return {chr(cp) for cp in range(lo, hi)
            if bool(cls_a.search(chr(cp))) != bool(cls_b.search(chr(cp)))}


def test_letters_class_matches_the_canonical_one():
    # the only intended difference is the halfwidth voicing mark
    assert _differ(codes.KANA_LETTERS_RE, japanese_utils.KANA,
                   0x3040, 0x3100) == set()
    assert _differ(codes.KANA_LETTERS_RE, japanese_utils.KANA,
                   0xFF61, 0xFFA0) == {HALFWIDTH_VOICING}


def test_letters_class_classifies_the_known_characters():
    for char in KANA_LETTERS:
        assert codes.KANA_LETTERS_RE.search(char), repr(char)
        assert japanese_utils.KANA.search(char), repr(char)
    for char in KANA_PUNCT:
        assert not codes.KANA_LETTERS_RE.search(char), repr(char)
    for char in NOT_KANA:
        assert not codes.KANA_LETTERS_RE.search(char), repr(char)


def test_coarse_class_covers_every_letter_and_more():
    """KANA_RE answers "is this text at all?" - never narrower than letters."""
    for char in KANA_LETTERS:
        assert codes.KANA_RE.search(char), repr(char)
    # deliberately wider: the kana-block punctuation counts as "text"
    for char in ("\u309b", "\u309c", "\u30fb", "\u30fc"):
        assert codes.KANA_RE.search(char), repr(char)


def test_residue_test_keeps_its_teeth():
    """A value that is still Japanese contains a kana letter - always."""
    for text in ("こんにちは", "ドキドキ", "\uff8c\uff9e\uff75\uff9e",
                 "あ゛っ！", "よろしくー", "そ・れ・で・も"):
        assert codes.KANA_LETTERS_RE.search(text), text
    # translated Chinese that merely keeps kana-block punctuation is clean
    for text in ("啊゛！", "好・坏", "嗯——", "不要啊～～", "呼ﾞ"):
        assert not codes.KANA_LETTERS_RE.search(text), text


def test_classes_are_compiled_patterns():
    assert isinstance(codes.KANA_RE, re.Pattern)
    assert isinstance(codes.KANA_LETTERS_RE, re.Pattern)
