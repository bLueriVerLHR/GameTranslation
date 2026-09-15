"""Display-text extraction from KAG3 scenario lines.

Why these cases matter: the extractor used to accept only the literal
``text="..."`` attribute, so a game macro's own parameter names were invisible
and those lines were never translated.  Measured on a real title: choice labels
(``[SELECT_CENTER text="..." sel_1="..."]``) shipped in Japanese while the
surrounding dialogue was Chinese, and speaker names (``[NAME_M n="..."]``) kept
104 kana occurrences.  The fix is generic (any attribute can hold display text),
but it must not start translating expressions or reference names, which would
break comparisons and jumps.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri.ks_extract import display_text, tag_text_attrs, translatable  # noqa: E402


def test_custom_macro_display_attributes_are_extracted():
    # A game macro's visible strings live in its own parameter names.
    assert translatable('[NAME_M n="キモオヤジ"]') is True
    assert translatable('[title name="このソフトウェアについて"]') is True
    assert translatable(
        '[SELECT_CENTER text="自身の忍法は――" file_1="newgame.ks" '
        'tag_1="*S008b" sel_1="俺の忍法は炎を操る！"]') is True
    # The window tag that used to be the only recognised form still works.
    assert translatable('[wm2 text="セーブしますか？"]') is True
    # Bare dialogue, unchanged.
    assert translatable('達郎「ここで待っていてくれ」[l][r]') is True


def test_expression_and_reference_attributes_are_not_extracted():
    # A string literal inside an expression must never be translated.
    assert translatable("[eval exp=\"f.sel1_label='―３日目マップ移動選択―'\"]") is False
    assert translatable("[if exp=\"f.name=='ゆき'\"]") is False
    # Reference names legitimately contain Japanese: a Japanese file name or a
    # label is a jump target, and translating one breaks the jump.
    assert translatable('[call storage="シナリオ.ks" target="*選択"]') is False
    assert translatable('[playbgm storage="bgm_オープニング"]') is False
    assert translatable('[link2 file_1="ルート.ks" tag_1="*別れ"]') is False
    # Nothing Japanese at all.
    assert translatable('[playbgm storage="bgm001"]') is False
    # Unbalanced lines stay out.
    assert translatable('[NAME_M n="キモオヤジ"') is False
    # NOTE: label ("*..") and comment (";..") lines carry Japanese but are a
    # caller-level exclusion (build_ks_translation.py drops them) - `translatable`
    # only judges the line's own content, so it is not asserted here.


def test_tag_text_attrs_skips_code_and_reference_names():
    segments = [('tag', '[SELECT_CENTER text="プロンプト" file_1="a.ks" '
                        'tag_1="*分岐" sel_1="選択肢" exp="f.x=1"]')]
    assert tag_text_attrs(segments) == ['プロンプト', '選択肢']


def test_display_text_surfaces_macro_parameter_values():
    # Context windows must be readable: a choice line shows its labels, not an
    # empty string (the old behaviour, which made chunk context useless here).
    text, balanced = display_text('[SELECT_CENTER text="どれ？" sel_1="炎" sel_2="風"]')
    assert balanced is True
    assert 'どれ？' in text and '炎' in text and '風' in text
