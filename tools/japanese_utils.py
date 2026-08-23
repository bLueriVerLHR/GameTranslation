#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared Japanese-text detection regexes.

One place to maintain the kana ranges so every tool agrees on what counts
as "still Japanese".  The canonical KANA deliberately EXCLUDES U+30FB (・),
U+30FC (ー) and U+30A0: those are punctuation that also appears in already-
translated Chinese lines (・-prefixed conditions) and would flood templates
and QC reports with false keys.  Half-width katakana (U+FF71-FF9E) counts
as kana.

KANA_BLOCKS is the coarser block-range variant (hiragana + katakana code
blocks, no half-width) used by the ADV text-resource tools; keep it distinct
so those tools keep their existing detection behavior.

KANA_BLOCKS_HW is the block-range + half-width variant (including the
half-width middle dot U+FF65) formerly inlined in the legacy JSON-chunk QC
tool (qc_translation_chunks.py); keep the character set so that tool's
detection stays unchanged.

KANA_PURE_WORD is the anchored "pure kana-ish word" matcher formerly inlined
in clean_kana_ticks.py: the canonical kana chars plus the punctuation /
spacing that co-occurs in standalone mouth-sound and author-name tokens.
Used with full-string matching; deliberately NOT equivalent to KANA (which
is a search pattern that excludes ー/・).
"""

import re

KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")

KANA_BLOCKS = re.compile(r"[\u3040-\u30ff]")

KANA_BLOCKS_HW = re.compile(r"[\u3040-\u30ff\uff65-\uff9f]")

KANA_PURE_WORD = re.compile(
    r"^[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9eー～・゛゜\s\"'()（）\-_/]+$")
