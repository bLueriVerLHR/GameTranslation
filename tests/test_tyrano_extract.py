#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tyrano/tyrano_extract.py TyranoScript .ks parsing."""
from tyrano import tyrano_extract as te

SAMPLE_BLOCK = """[tb_start_text mode=2 ]
#たろう
[font color=lightpink]はい。今日の報告です。[l][r]
他の男に裸を見せて来ました…。[l][r]
[_tb_end_text]
"""

SAMPLE_ATTR = ('[glink  color="black"  storage="Z_Shop.ks"  text="はい"  '
               'x="750"  y="500"  ]')


class TestBlockTextLines:
    def test_blocks_and_kinds(self):
        hits = list(te.block_text_lines(SAMPLE_BLOCK))
        kinds = [k for _l, k in hits]
        assert kinds == ["speaker", "text", "text"]

    def test_skip_comments_and_blanks(self):
        text = ("[tb_start_text mode=1 ]\n"
                ";コメント\n"
                "\n"
                "#\n"
                "本文です。[p]\n"
                "[_tb_end_text]\n")
        hits = list(te.block_text_lines(text))
        assert hits == [("本文です。[p]", "text")]

    def test_skip_empty_speaker_line(self):
        text = "[tb_start_text mode=2 ]\n#\n本文[l][r]\n[_tb_end_text]\n"
        kinds = [k for _l, k in te.block_text_lines(text)]
        assert kinds == ["text"]

    def test_outside_block_not_collected(self):
        text = "本文そのまま[p]\n" + SAMPLE_BLOCK
        kinds = [k for _l, k in te.block_text_lines(text)]
        assert kinds == ["speaker", "text", "text"]


class TestTextAttrLines:
    def test_glink_text(self):
        hits = list(te.text_attr_lines(SAMPLE_ATTR))
        assert hits == [(SAMPLE_ATTR, "はい")]

    def test_single_quotes(self):
        line = '[glink text=\'一重引用符\']'
        hits = list(te.text_attr_lines(line))
        assert hits == [(line, "一重引用符")]

    def test_non_text_tag_ignored(self):
        line = '[playse storage="a.mp3" volume="100" ]'
        assert list(te.text_attr_lines(line)) == []

    def test_ptext_show_collected(self):
        line = '[tb_ptext_show x="310" text="第一章" anim="false" ]'
        hits = list(te.text_attr_lines(line))
        assert hits == [(line, "第一章")]

    def test_empty_text_value_ignored(self):
        line = '[glink text="" ]'
        assert list(te.text_attr_lines(line)) == []


class TestTranslatable:
    def test_speaker_line(self):
        assert te.translatable("#たろう")

    def test_ja_body(self):
        assert te.translatable("[font color=lightpink]本文です。[l][r]")

    def test_ja_in_text_attr(self):
        assert te.translatable('[glink text="戻る" ]')

    def test_ascii_only_false(self):
        assert not te.translatable('[position left=0 top=774 ]')

    def test_unclosed_bracket_false(self):
        assert not te.translatable("本文です。[l][r")

    def test_kanji_only_counts(self):
        assert te.translatable("第一章")


class TestDisplayText:
    def test_speaker(self):
        assert te.display_text("#たろう") == "たろう"

    def test_strips_tags(self):
        assert te.display_text("[font color=lightpink]本文です。[l][r]") \
            == "本文です。"

    def test_attr_shown(self):
        out = te.display_text('[glink text="戻る" x="10" ]')
        assert "戻る" in out and "glink" not in out


class TestTagHelpers:
    def test_tag_name(self):
        assert te.tag_name("[playse  volume=\"100\"  ]") == "playse"

    def test_tag_name_unknown(self):
        assert te.tag_name("本文です。") == ""

    def test_split_tag_attrs(self):
        attrs = te.split_tag_attrs('[button name="x" visible="false" ]')
        assert attrs == [("name", "x"), ("visible", "false")]

    def test_split_unquoted_value(self):
        attrs = te.split_tag_attrs("[layopt layer=2 visible=true]")
        assert attrs == [("layer", "2"), ("visible", "true")]


class TestScenarioStorageRefs:
    def test_call_and_jump(self):
        text = ('[call storage="system/tyrano.ks"]\n'
                '[jump storage="title_screen.ks" target="*T"]\n')
        refs, has_next = te.scenario_storage_refs(text)
        assert refs == ["system/tyrano.ks", "title_screen.ks"]
        assert not has_next

    def test_next_flag(self):
        refs, has_next = te.scenario_storage_refs("[next]\n")
        assert refs == [] and has_next

    def test_bg_storage_not_tracked(self):
        text = '[bg storage="Day/01.png" time="1000" ]\n'
        refs, _h = te.scenario_storage_refs(text)
        assert refs == []

    def test_storage_omit_extension_resolved_in_caller(self):
        text = '[call storage="system/tyrano"]\n'
        refs, _h = te.scenario_storage_refs(text)
        assert refs == ["system/tyrano"]


class TestEncoding:
    def test_utf8_detection(self):
        raw = "本文です。\n".encode("utf-8")
        assert te.detect_encoding(raw) == "utf-8"

    def test_utf16le_detection(self):
        raw = "本文です。\n".encode("utf-16")
        assert te.detect_encoding(raw) == "utf-16"

    def test_load_ks_strips_bom(self, tmp_path):
        # use tmp_path so the test runs even when /tmp is read-only
        p = str(tmp_path / "t_bom.ks")
        with open(p, "wb") as f:
            f.write(b"\xef\xbb\xbf" + "本文です。".encode("utf-8"))
        text, enc = te.load_ks(p)
        assert enc == "utf-8"
        assert text == "本文です。" and not text.startswith("\ufeff")
