#!/usr/bin/env python3
"""Unit tests for rpgmaker/japanese.py - the single source of kana
detection regexes.

Guards the C4 convergence contract: every tool that previously inlined its
own kana pattern now shares a constant from this module, and each shared
constant keeps the exact character set it replaced (behavior unchanged).
"""
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from rpgmaker import japanese as japanese_utils  # noqa: E402


class TestKANA:
    """Canonical search pattern: hiragana + katakana + half-width katakana,
    deliberately excluding punctuation (ー U+30FC, ・ U+30FB, U+30A0)."""

    def test_matches_hiragana(self):
        assert japanese_utils.KANA.search("こんにちは")

    def test_matches_katakana(self):
        assert japanese_utils.KANA.search("テスト")

    def test_matches_halfwidth_katakana(self):
        assert japanese_utils.KANA.search("ｱｲｳ")

    def test_excludes_middle_dot(self):
        # ・-prefixed translated conditions must NOT count as residual kana.
        assert not japanese_utils.KANA.search("・条件")

    def test_excludes_long_vowel_mark(self):
        # The long-vowel mark ー alone must not be treated as kana residual;
        # surrounding katakana (コ/ラ) still matches, so use the mark alone.
        assert not japanese_utils.KANA.search("ー")
        assert not japanese_utils.KANA.search("～")

    def test_does_not_match_pure_cjk(self):
        assert not japanese_utils.KANA.search("色经验值")

    def test_does_not_match_latin(self):
        assert not japanese_utils.KANA.search("A-Z123")

    def test_pattern_unchanged(self):
        assert japanese_utils.KANA.pattern == \
            r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]"


class TestKANABLOCKS:
    """Coarse block-range variant (hiragana + katakana code blocks, no
    half-width); includes ー/・ that KANA excludes."""

    def test_matches_blocks_including_punctuation(self):
        assert japanese_utils.KANA_BLOCKS.search("ー・")

    def test_matches_hiragana(self):
        assert japanese_utils.KANA_BLOCKS.search("あ")

    def test_does_not_match_halfwidth(self):
        assert not japanese_utils.KANA_BLOCKS.search("ｱ")

    def test_pattern_unchanged(self):
        assert japanese_utils.KANA_BLOCKS.pattern == r"[\u3040-\u30ff]"


class TestKANABLOCKSHW:
    """Block-range + half-width variant (incl. half-width middle dot U+FF65),
    previously inlined in the legacy JSON-chunk QC tool."""

    def test_matches_halfwidth_middle_dot(self):
        assert japanese_utils.KANA_BLOCKS_HW.search("\uff65")

    def test_matches_halfwidth_katakana(self):
        assert japanese_utils.KANA_BLOCKS_HW.search("ｱ")

    def test_matches_block_punctuation(self):
        assert japanese_utils.KANA_BLOCKS_HW.search("ー・")

    def test_pattern_unchanged(self):
        assert japanese_utils.KANA_BLOCKS_HW.pattern == \
            r"[\u3040-\u30ff\uff65-\uff9f]"


class TestKANAPureWord:
    """Anchored full-string matcher for pure kana-ish words (clean_kana_ticks
    KANA_ALL): kana plus co-occurring punctuation/spacing."""

    def test_matches_pure_kana_word(self):
        assert japanese_utils.KANA_PURE_WORD.match("あー")

    def test_matches_kana_with_punctuation(self):
        assert japanese_utils.KANA_PURE_WORD.match("ん～")

    def test_matches_short_onomatopoeia(self):
        assert japanese_utils.KANA_PURE_WORD.match("ガーン")

    def test_rejects_kanji(self):
        # おばさん is pure hiragana and DOES match; adding a CJK ideograph
        # breaks the all-kana character class.
        assert japanese_utils.KANA_PURE_WORD.match("おばさん")
        assert not japanese_utils.KANA_PURE_WORD.match("おばさん漢字")

    def test_rejects_sentence_end_punctuation(self):
        # 。 (U+3002) is not in the class -> not a pure kana-ish word.
        assert not japanese_utils.KANA_PURE_WORD.match("あい。")

    def test_full_string_anchored(self):
        # Partial kana followed by CJK must not match (anchored ^...$).
        assert not japanese_utils.KANA_PURE_WORD.match("あ漢字")

    def test_pattern_unchanged(self):
        assert japanese_utils.KANA_PURE_WORD.pattern == \
            r"^[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9eー～・゛゜\s\"'()（）\-_/]+$"


class TestKANASetRelations:
    """Document the intended inclusion relations between the constants."""

    def test_blocks_is_wider_than_kana(self):
        for punct in ("ー", "・"):
            assert japanese_utils.KANA_BLOCKS.search(punct)
            assert not japanese_utils.KANA.search(punct)

    def test_blocks_hw_includes_halfwidth_where_blocks_does_not(self):
        assert japanese_utils.KANA_BLOCKS_HW.search("ｱ")
        assert not japanese_utils.KANA_BLOCKS.search("ｱ")

    def test_pure_word_uses_kana_charset_plus_extras(self):
        assert re.match(japanese_utils.KANA_PURE_WORD, "こんにちは")
