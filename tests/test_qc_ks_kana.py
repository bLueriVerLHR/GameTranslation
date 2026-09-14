#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the kana-residual QC (tools/qc_ks_kana.py).

The QC is what stands between a translator and a corrupted script, so both
directions matter: it must catch untranslated display text, and it must NOT
report identifiers or code.  TyranoScript legally uses Japanese variable
names (`f.ライブファン表示`, `&f.アイテム名[0]`), so a naive kana scan
reported ~10% "residual" on a fully translated build - almost all of it
identifiers.  An agent acting on that would translate the identifiers and
break every reference.
"""
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kirikiri.ks_extract import iter_display_lines  # noqa: E402
from tools import qc_ks_kana  # noqa: E402


def write_ks(path, text, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return str(path)


def check(tmp_path, text):
    """Write one .ks file and return (translatable, residual, lines)."""
    write_ks(tmp_path / "s.ks", text)
    total = residual = 0
    found = []
    for path in [str(tmp_path / "s.ks")]:
        from kirikiri.ks_extract import (KANA, display_text, load_ks,  # noqa
                                         translatable)
        body, _enc = load_ks(path)
        for idx, line in iter_display_lines(body):
            stripped = line.strip()
            if not translatable(stripped):
                continue
            total += 1
            shown, _ok = display_text(stripped)
            if KANA.search(shown):
                residual += 1
                found.append(shown)
    return total, residual, found


# ------------------------------------------------------------------ positive

def test_catches_untranslated_dialogue(tmp_path):
    # A bare Japanese line is exactly what the QC exists to find.
    total, residual, found = check(tmp_path, "さて、ゲームが簡単に作れると聞いた\n")
    assert total == 1 and residual == 1
    assert "さて" in found[0]


def test_catches_untranslated_text_attribute(tmp_path):
    # TyranoScript UI labels live in text="..." on a tag; that is display
    # text and must still be caught even though the line is a tag.
    line = '[glink color="btn" size="25" x="530" text="スキップする" target="*s"]\n'
    total, residual, found = check(tmp_path, line)
    assert total == 1 and residual == 1
    assert "スキップする" in found[0]


def test_translated_line_is_not_reported(tmp_path):
    total, residual, _ = check(tmp_path, "那么，听说游戏很容易做，我就来看看了\n")
    assert total == 1 and residual == 0


# ------------------------------------------------------------------ negative

def test_ignores_japanese_variable_reference(tmp_path):
    # `&f.アイテム名[0]` is a reference, not text: translating it breaks the
    # script.  This was the single biggest source of false positives.
    total, residual, _ = check(tmp_path, "&f.アイテム名[0]\n")
    assert total == 0 and residual == 0


def test_ignores_japanese_assignment_statement(tmp_path):
    # TJS assignment to a Japanese-named field is code, not display text.
    total, residual, _ = check(tmp_path, "f.ほめ会話番号 = '*' + f.Kaiwa_Bangou;\n")
    assert total == 0 and residual == 0


def test_ignores_label_lines(tmp_path):
    # `*__一緒に遊ぶ` is a jump target; translating it breaks [jump].
    total, residual, _ = check(tmp_path, "*__一緒に遊ぶ\n")
    assert total == 0 and residual == 0


def test_ignores_comments(tmp_path):
    total, residual, _ = check(tmp_path, "; メニューボタン非表示\n")
    assert total == 0 and residual == 0


def test_ignores_lines_inside_code_block(tmp_path):
    text = ("[tb_start_tyrano_code]\n"
            "  if(mp.name==null)console.error('nameは必須です');\n"
            "  sf.フラグ = 1;\n"
            "[_tb_end_tyrano_code]\n"
            "こんにちは\n")
    total, residual, found = check(tmp_path, text)
    # only the trailing dialogue is checkable, and it IS residual
    assert total == 1 and residual == 1
    assert "こんにちは" in found[0]


def test_code_block_closes_and_scan_resumes(tmp_path):
    text = ("[iscript]\n"
            "  var 名前 = 'テスト';\n"
            "[endscript]\n"
            "ありがとう\n")
    total, residual, found = check(tmp_path, text)
    assert total == 1 and residual == 1
    assert "ありがとう" in found[0]


# --------------------------------------------------------------- edge cases

def test_strips_var_ref_but_keeps_real_text(tmp_path):
    # A line mixing a reference and real text must still be checked, on the
    # text part only.
    total, residual, found = check(tmp_path, "残り&f.個数個だよ\n")
    assert total == 1 and residual == 1
    assert "残り" in found[0]


def test_fully_chinese_line_with_var_ref_is_clean(tmp_path):
    total, residual, _ = check(tmp_path, "剩余&f.個数个\n")
    assert total == 1 and residual == 0


def test_code_statement_does_not_swallow_text_starting_with_if(tmp_path):
    # Guard against a regex that matches "if" inside ordinary text.
    total, residual, found = check(tmp_path, "ifの話をしよう\n")
    assert total == 1 and residual == 1, found


# ------------------------------------------------------ end-to-end on a tree

def test_scan_tree_counts_only_real_residuals(tmp_path):
    write_ks(tmp_path / "a.ks",
             "こんにちは\n"
             "&f.名前[0]\n"
             "*ラベル\n"
             "; コメント\n"
             "f.ほめ会話番号 = 1;\n")
    total, residual = qc_ks_kana.scan_tree(str(tmp_path))
    assert (total, residual) == (1, 1)


def test_scan_tree_clean_tree_reports_zero(tmp_path):
    write_ks(tmp_path / "a.ks", "你好\n那么再见\n&f.名前[0]\n")
    total, residual = qc_ks_kana.scan_tree(str(tmp_path))
    assert (total, residual) == (2, 0)


def test_scan_values_flags_kana_in_value(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"你好": "你好", "こんにちは": "你好"}),
                 encoding="utf-8")
    total, residual = qc_ks_kana.scan_values(str(p))
    assert total == 2 and residual == 0


def test_scan_values_reports_value_that_kept_kana(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"こんにちは": "你好です"}), encoding="utf-8")
    total, residual = qc_ks_kana.scan_values(str(p))
    assert total == 1 and residual == 1


def test_iter_display_lines_numbers_match_source(tmp_path):
    # file:line must point at the real line in the source file.
    text = "; c\n\n*label\nこんにちは\n"
    lines = list(iter_display_lines(text))
    assert len(lines) == 1
    assert lines[0][0] == 4
