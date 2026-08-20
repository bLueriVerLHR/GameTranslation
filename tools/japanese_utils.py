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
"""

import re

KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")

KANA_BLOCKS = re.compile(r"[\u3040-\u30ff]")
