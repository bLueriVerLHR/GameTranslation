#!/usr/bin/env python3
"""`tools/bake_tyrano_dict.py`: baking an external {ja: zh} dictionary into a
TyranoScript work package.

The shapes and refusals below were each found on a real Electron-packaged
TyranoBuilder game, not invented: the title-screen buttons carry their label
in a `text="..."` attribute (a text-run-only reader leaves them Japanese), and
the first version of the rebuild dropped the attribute's closing quote.
"""

import json

import pytest
import typer

from tools import bake_tyrano_dict as bd


def bake_one(key, table):
    return bd.bake_key(key, table)


# ------------------------------------------------------------ inline shape

def test_inline_run_is_replaced_and_tags_kept():
    status, line = bake_one("[font color=#ffffff]本文[l][p]",
                            {"本文": "正文"})
    assert status == bd.OK
    assert line == "[font color=#ffffff]正文[l][p]"


def test_speaker_line_is_replaced():
    status, line = bake_one("#紗夜", {"紗夜": "纱夜"})
    assert status == bd.OK
    assert line == "#纱夜"


def test_whitespace_around_the_run_is_preserved():
    status, line = bake_one("[font] 本文 [l]", {"本文": "正文"})
    assert status == bd.OK
    assert line == "[font] 正文 [l]"


def test_ascii_run_is_not_a_unit():
    """The dictionary is keyed on rendered Japanese text; an ASCII run is not
    something it was ever keyed on."""
    status, _line = bake_one("[font]ABC[l]", {"ABC": "abc"})
    assert status == bd.NO_TEXT


def test_tag_only_line_has_no_unit():
    status, _line = bake_one("[l][r]", {"[l]": "x"})
    assert status == bd.NO_TEXT


# --------------------------------------------------------- attribute shape

def test_text_attribute_is_replaced_with_its_quotes_intact():
    key = '[glink  color="btn"  text="始めから"  x="75"  ]'
    status, line = bake_one(key, {"始めから": "从头开始"})
    assert status == bd.OK
    assert line == '[glink  color="btn"  text="从头开始"  x="75"  ]'
    # the rebuild must not add or swallow a quote: that would truncate the
    # attribute and break the tag line
    assert line.count('"') == key.count('"')


def test_text_attribute_whitespace_is_preserved():
    status, line = bake_one('[glink text=" 戻る " x="1" ]', {"戻る": "返回"})
    assert status == bd.OK
    assert line == '[glink text=" 返回 " x="1" ]'


def test_other_attributes_are_untouched():
    """Only the display-text attribute is a unit, not storage/name/..."""
    key = '[glink storage="kaisou.ks" name="btn_1" text="回想部屋" target="*k"]'
    status, line = bake_one(key, {"回想部屋": "回想房间"})
    assert status == bd.OK
    assert line == ('[glink storage="kaisou.ks" name="btn_1" text="回想房间" '
                    'target="*k"]')


# --------------------------------------------------------------- refusals

def test_missing_key_is_not_written():
    status, line = bake_one("[font]本文[l]", {"別の": "其他"})
    assert status == bd.MISSING
    assert line is None


def test_value_with_kana_is_refused():
    status, _line = bake_one("[font]本文[l]", {"本文": "正文だよ"})
    assert status == bd.KANA


def test_empty_value_is_refused():
    status, _line = bake_one("[font]本文[l]", {"本文": "   "})
    assert status == bd.EMPTY


def test_value_with_a_line_break_is_refused():
    status, _line = bake_one("[font]本文[l]", {"本文": "正文\n第二行"})
    assert status == bd.NEWLINE


def test_value_with_a_tag_cannot_add_a_tag():
    """A `[p]` inside the value would become a real tag, changing the line's
    structure (two text units instead of one)."""
    status, _line = bake_one("[font]本文[l][p]", {"本文": "正[p]文"})
    assert status in (bd.TAGS, bd.MULTI_UNIT)


def test_plain_bracket_in_text_is_harmless():
    """A lone `]` with no `[` never starts a tag, so it is not a defect:
    Tyrano renders it as literal text."""
    status, line = bake_one("[font]本文[l][p]", {"本文": "正]文"})
    assert status == bd.OK
    assert line == "[font]正]文[l][p]"


def test_unclosed_bracket_in_text_cannot_add_a_tag():
    status, _line = bake_one("[font]本文[l][p]", {"本文": "正[文"})
    assert status == bd.TAGS


def test_value_with_a_quote_cannot_break_an_attribute():
    status, _line = bake_one('[glink text="戻る" x="1" ]', {"戻る": '返"回'})
    assert status == bd.TAGS


def test_two_inline_runs_are_refused_not_guessed():
    status, _line = bake_one("[font]本文[l]あと[p]", {"本文あと": "正文之后"})
    assert status == bd.MULTI_UNIT


def test_inline_run_plus_attribute_is_ambiguous():
    status, _line = bake_one('[glink text="戻る" ]本文[l]',
                             {"戻る": "返回", "本文": "正文"})
    assert status == bd.MULTI_UNIT


def test_translation_without_any_japanese_is_accepted():
    """`っっ！？` -> `！！？`: no Japanese left, which is the point."""
    status, line = bake_one("っっ！？[p]", {"っっ！？": "！！？"})
    assert status == bd.OK
    assert line == "！！？[p]"


# ------------------------------------------------------ dictionary hygiene

def test_identity_entries_are_dropped():
    """v == k *with kana* shadows the real text with the Japanese original.
    A kanji-only line that is identical in Chinese is kept (it is a no-op, not
    a defect) - same rule as the RPG Maker bake."""
    table, dropped = bd.clean_dictionary({"さくら": "さくら",
                                        "信次": "信次",
                                        "本文": "正文"})
    assert "さくら" not in table
    assert "信次" in table
    assert dropped["identity"] == 1


def test_empty_dictionary_values_are_dropped():
    table, dropped = bd.clean_dictionary({"本文": "", "あと": "之后"})
    assert table == {"あと": "之后"}
    assert dropped["empty"] == 1


def test_non_string_values_are_ignored():
    table, _dropped = bd.clean_dictionary({"本文": 3, "あと": "之后"})
    assert table == {"あと": "之后"}


# ------------------------------------------------------------- the bake run

def make_work(tmp_path, keys):
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "template.json").write_text(
        json.dumps(dict.fromkeys(keys, ""), ensure_ascii=False),
        encoding="utf-8")
    return work


def write_dict(tmp_path, table):
    path = tmp_path / "dict.json"
    path.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_bake_writes_translated_json(tmp_path):
    work = make_work(tmp_path, ["[font]本文[l]", "#紗夜"])
    out = tmp_path / "work" / "translated.json"
    stats = bd.bake(str(work), write_dict(tmp_path, {"本文": "正文",
                                                    "紗夜": "纱夜"}),
                    str(out), 0.5, False)
    assert stats["coverage"] == 1.0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "[font]本文[l]": "[font]正文[l]", "#紗夜": "#纱夜"}


def test_low_coverage_refuses_to_write(tmp_path):
    """A half-translated bake poisons every later completion pass."""
    work = make_work(tmp_path, ["[font]本文[l]", "[font]あと[l]",
                               "[font]さらに[l]"])
    out = tmp_path / "work" / "translated.json"
    with pytest.raises(typer.Exit) as exc:
        bd.bake(str(work), write_dict(tmp_path, {"本文": "正文"}), str(out),
                0.5, False)
    assert exc.value.exit_code == 1
    assert not out.exists()


def test_force_writes_below_the_gate(tmp_path):
    work = make_work(tmp_path, ["[font]本文[l]", "[font]あと[l]"])
    out = tmp_path / "work" / "translated.json"
    stats = bd.bake(str(work), write_dict(tmp_path, {"本文": "正文"}), str(out),
                    0.9, True)
    assert stats["coverage"] == 0.5
    assert out.exists()


def test_report_counts_every_status(tmp_path):
    work = make_work(tmp_path, ["[font]本文[l]", "[font]あと[l]", "[l][r]"])
    out = tmp_path / "work" / "translated.json"
    stats = bd.bake(str(work), write_dict(tmp_path, {"本文": "正文だ"}), str(out),
                    0.5, True)
    assert stats["counts"] == {bd.KANA: 1, bd.MISSING: 1, bd.NO_TEXT: 1}
    assert stats["coverage"] == 0.0


def test_empty_package_does_not_divide_by_zero(tmp_path):
    work = make_work(tmp_path, [])
    out = tmp_path / "work" / "translated.json"
    stats = bd.bake(str(work), write_dict(tmp_path, {}), str(out), 0.5, False)
    assert stats["coverage"] == 0.0
    assert json.loads(out.read_text(encoding="utf-8")) == {}


def test_out_path_can_be_omitted(tmp_path):
    """`out=None` computes and reports without writing."""
    work = make_work(tmp_path, ["[font]本文[l]"])
    stats = bd.bake(str(work), write_dict(tmp_path, {"本文": "正文"}), None,
                    0.5, False)
    assert stats["coverage"] == 1.0
