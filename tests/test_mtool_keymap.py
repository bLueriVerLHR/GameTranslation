"""Tests for tools/mtool_keymap.py - runtime-dictionary reuse with real context.

The tool's job is mechanical: map every key of a game's runtime dictionary onto
the static field it came from, hand out context-rich translation batches, and
refuse to store anything that would break the game (control codes, newline
counts, kana residue).
"""

import json
import re
from pathlib import Path

import pytest

from tools import mtool_keymap as mk

PATCH = """\
> REWOLF TRANS PATCH FILE VERSION 1.0

> BEGIN STRING
さーにゃ＠裏垢
> CONTEXT [NEW] DB:CDataBase/[32]つぶやきプロフィール/[0]紗愛/[0]名前

> END STRING

> BEGIN STRING
「おはよう、今日もいい天気だね」
> CONTEXT [NEW] MPS:TestMap/1/0/[54]Message/0

> END STRING

> BEGIN STRING
1〇歳\\r
フォロワー10000人目指して\\r
ます☆☆☆\\r
\\r
たくさんフォローして\\r
くれると嬉しいな\\\\i[403]\\r
\\r
> CONTEXT [NEW] DB:CDataBase/[32]つぶやきプロフィール/[0]紗愛/[2]紹介文

> END STRING

> BEGIN STRING
選択してください
> CONTEXT [NEW] COMMONEVENT:1105/cmd/[2]Message/0

> END STRING
"""


def write_patch(root, name="map.txt", text=PATCH, danger=False):
    folder = root / ("d" if danger else "s")
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "_Danger.txt" if danger else ".txt"
    path = folder / (name.replace(".txt", suffix))
    path.write_text(text, encoding="utf-8")
    return path


def make_dict():
    return {
        "さーにゃ＠裏垢": "纱爱@小号",
        "「おはよう、今日もいい天気だね」": "「早上好，今天天气也不错呢」",
        "1〇歳\\r\nフォロワー10000人目指して\\r\nます☆☆☆\\r\n\\r\nたくさんフォローして\\r\nくれると嬉しいな\\\\i[403]\\r\n\\r": "旧译",
        "選択してください": "请选择",
        "フォロワー": "粉丝",
        "engine only": "no kana",
    }


def test_parse_patch_text_reads_entries_and_context(tmp_path):
    path = write_patch(tmp_path)
    entries = list(mk.parse_patch_text(path.read_text(encoding="utf-8")))
    assert len(entries) == 4
    assert entries[0][0] == "さーにゃ＠裏垢"
    assert entries[0][1].startswith("[NEW] DB:CDataBase")
    assert entries[1][0] == "「おはよう、今日もいい天気だね」"


@pytest.mark.parametrize("ctx,expected", [
    ("[NEW] DB:CDataBase/[32]/[0]", "DB"),
    ("[NEW] COMMONEVENT:1105/cmd/[2]Message/0", "COMMONEVENT"),
    ("[NEW] MPS:TestMap/1/0/[54]Message/0", "MPS"),
    ("something else", "OTHER"),
])
def test_bucket_classification(ctx, expected):
    assert mk.bucket_of(ctx) == expected


def test_scene_comes_from_the_context():
    assert mk.scene_of("[NEW] MPS:TestMap/1/0/[54]Message/0") == "TestMap"
    assert mk.scene_of("[NEW] COMMONEVENT:1105/cmd/[2]Message/0") == "1105"
    assert mk.scene_of("nonsense") == ""


def test_key_id_is_stable_and_distinct():
    assert mk.key_id("同じ") == mk.key_id("同じ")
    assert mk.key_id("a") != mk.key_id("b")


def test_validate_fragment_accepts_a_clean_translation():
    assert mk.validate_fragment("こんにちは。", "你好。") == []


def test_validate_fragment_keeps_the_code_multiset():
    ja = "やっ\\\\i[403]た"
    assert mk.validate_fragment(ja, "做\\\\i[403]了") == []
    problems = mk.validate_fragment(ja, "做了")
    assert any("control codes" in item for item in problems)
    problems = mk.validate_fragment(ja, "做\\\\i[404]了")
    assert any("control codes" in item for item in problems)


def test_validate_fragment_keeps_the_newline_count():
    ja = "一\\r\n二"
    assert mk.validate_fragment(ja, "一\\r\n二了") == []
    assert any("newline" in item for item in mk.validate_fragment(ja, "一二"))


def test_validate_fragment_rejects_kana_residue_but_allows_paths():
    assert any("kana" in item for item in mk.validate_fragment("こんにちは", "你好 こんにちは"))
    assert mk.validate_fragment("Picture/a.png", "Picture/あ.png") == []


def test_validate_fragment_rejects_empty_values():
    assert mk.validate_fragment("こんにちは", "   ") == ["empty"]
    assert mk.validate_fragment("こんにちは", "") == ["empty"]


def test_scan_containers_flags_risky_files(tmp_path):
    write_patch(tmp_path, name="safe.txt")
    write_patch(tmp_path, name="risky.txt", danger=True)
    write_patch(tmp_path, name="ctx_Context.txt", text="> CONTEXT only.txt")
    containers = mk.scan_containers(tmp_path)
    assert len(containers) == 8  # four entries in each of the two files
    assert any(item["risky_file"] for item in containers)
    assert all(item["source"].strip() for item in containers)


def test_build_keymap_classifies_whole_field_line_and_sub_line(tmp_path):
    write_patch(tmp_path)
    containers = mk.scan_containers(tmp_path)
    result = mk.build_keymap(make_dict(), containers)
    keys = result["keys"]
    assert keys["さーにゃ＠裏垢"]["kind"] == "whole-field"
    assert keys["選択してください"]["kind"] == "whole-field"
    assert keys["フォロワー"]["kind"] == "sub-line"
    assert keys["フォロワー"]["container"] == keys[
        "1〇歳\\r\nフォロワー10000人目指して\\r\nます☆☆☆\\r\n\\r\nたくさんフォローして\\r\n"
        "くれると嬉しいな\\\\i[403]\\r\n\\r"]["container"]
    # keys without kana are not part of the dictionary-rebuild surface
    assert "engine only" not in keys


def fake_translation(ja):
    """Gate-safe stand-in translation: text becomes 译, codes/newlines stay."""
    pieces = []
    for token in re.split("(" + mk.CODE_RE.pattern + ")", ja or ""):
        if token and mk.CODE_RE.fullmatch(token):
            pieces.append(token)
        else:
            pieces.append(re.sub(r"[^\r\n]", "译", token or ""))
    return "".join(pieces)


def test_build_keymap_without_containers_maps_nothing(tmp_path):
    result = mk.build_keymap(make_dict(), [])
    assert result["keys"] == {}
    assert result["total_keys"] > 0


def ids_of(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [fragment["key_id"] for unit in payload["units"] for fragment in unit["fragments"]]


def add_extra_containers(patch_root, count=4):
    """More DB entries *with keys in the dictionary*, so slices have distinct work."""
    text = ""
    extra = {}
    for index in range(count):
        ja = f"おまけ項目その{index}"
        extra[ja] = f"附赠项目{index}"
        text += (f"> BEGIN STRING\n{ja}\n> CONTEXT [NEW] DB:CDataBase/[1]追加/[0]行{index}\n\n"
                 f"> END STRING\n\n")
    (patch_root / "extra.txt").write_text(text, encoding="utf-8")
    return extra


def run(*args):
    return mk.main([str(item) for item in args])


def test_end_to_end_slice_apply_gates_export(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0

    assert run("slice", work, "--buckets", "DB,COMMONEVENT", "--units", "5") == 0
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    assert batch["units"]
    for unit in batch["units"]:
        for fragment in unit["fragments"]:
            fragment["zh"] = fake_translation(fragment["ja"])
    batch_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")

    assert run("apply", work, batch_path) == 0
    assert run("gates", work) == 0

    out_dict = tmp_path / "out.json"
    assert run("export", work, dict_path, out_dict, "--allow-partial") == 0
    exported = json.loads(out_dict.read_text(encoding="utf-8"))
    assert set(exported) == set(make_dict())
    assert exported["さーにゃ＠裏垢"].startswith("译")
    assert exported["engine only"] == "no kana"

def test_apply_is_all_or_nothing(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB,COMMONEVENT", "--units", "5")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    first = batch["units"][0]["fragments"][0]
    first["zh"] = fake_translation(first["ja"])
    bad = batch["units"][-1]["fragments"][0]
    bad["zh"] = "こんにちは"  # kana residue, no path extension
    batch_path.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    assert run("apply", work, batch_path) == 1
    assert not (work / "translated.jsonl").exists()


def test_gates_fail_when_nothing_is_in_scope(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    assert run("gates", work) == 1


def test_skip_resolves_pending_keys(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB,COMMONEVENT", "--units", "5")
    assert run("gates", work) == 1
    assert run("skip", work, "--where", "選択") == 0
    assert run("skip", work, "--where", "選択") == 1  # nothing left to skip
    assert run("gates", work) == 1  # the other keys are still pending


def test_answer_positional_uses_batch_order_and_checks_the_count(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "2")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    values = [fake_translation(fragment["ja"])
              for unit in payload["units"] for fragment in unit["fragments"]]
    # a JSON array carries multi-line values without any escaping ambiguity
    answers = tmp_path / "positional.json"
    answers.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    assert run("answer", work, batch_path, answers, "--positional") == 0
    stored = [json.loads(line) for line in
              (work / "translated.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["zh"] for row in stored] == values


def test_answer_positional_rejects_a_wrong_count(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "2")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    short = tmp_path / "short.json"
    short.write_text(json.dumps(["译"], ensure_ascii=False), encoding="utf-8")
    assert run("answer", work, batch_path, short, "--positional") == 1
    plain = tmp_path / "wrong-json.json"
    plain.write_text("[1, 2]", encoding="utf-8")
    assert run("answer", work, batch_path, plain, "--positional") == 1
    assert not (work / "translated.jsonl").exists()


def test_terms_flags_drift_and_collapsed_values(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "5")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    rows = [json.dumps({"id": fragment["key_id"], "zh": fake_translation(fragment["ja"])},
                       ensure_ascii=False)
            for unit in payload["units"] for fragment in unit["fragments"]]
    answers = tmp_path / "answers.jsonl"
    answers.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run("answer", work, batch_path, answers) == 0

    glossary = tmp_path / "glossary.json"
    glossary.write_text(json.dumps({"characters": {"さーにゃ＠裏垢": "纱喵@小号"}},
                                   ensure_ascii=False), encoding="utf-8")
    # the stand-in translation does not use the decided rendering -> drift
    assert run("terms", work, glossary) == 1
    glossary.write_text(json.dumps({"characters": {}}, ensure_ascii=False), encoding="utf-8")
    assert run("terms", work, glossary) == 0


def test_terms_reports_a_short_value_reused_across_sources(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB,COMMONEVENT", "--units", "5")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    # write the state file directly: this test is about the *checker*, and a
    # one-character value would be rejected by the per-fragment gates
    rows = [{"key_id": fragment["key_id"], "zh": "好", "unit_id": unit["unit_id"]}
            for unit in payload["units"] for fragment in unit["fragments"]]
    (work / "translated.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    glossary = tmp_path / "glossary.json"
    glossary.write_text(json.dumps({"characters": {}}, ensure_ascii=False), encoding="utf-8")
    assert run("terms", work, glossary) == 1  # one value, many sources


def test_revise_replaces_a_stored_value_and_keeps_the_audit_trail(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "2")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    rows = [json.dumps({"id": fragment["key_id"], "zh": fake_translation(fragment["ja"])},
                       ensure_ascii=False)
            for unit in payload["units"] for fragment in unit["fragments"]]
    answers = tmp_path / "answers.jsonl"
    answers.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run("answer", work, batch_path, answers) == 0

    first = payload["units"][0]["fragments"][0]
    better = fake_translation(first["ja"]).replace("译", "甲")
    fix = tmp_path / "fix.jsonl"
    fix.write_text(json.dumps({"id": first["key_id"], "zh": better},
                              ensure_ascii=False) + "\n", encoding="utf-8")
    assert run("revise", work, fix) == 0
    stored = [json.loads(line) for line in
              (work / "translated.jsonl").read_text(encoding="utf-8").splitlines()]
    revised = [row for row in stored if row["key_id"] == first["key_id"]]
    assert revised[0]["zh"] == better
    assert "revised_from" in revised[0]
    # an unknown id or a value that would break the string is refused
    assert run("revise", work, fix) == 0            # idempotent no-op
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"id": "nope", "zh": "译"}, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    assert run("revise", work, bad) == 1
    breaking = tmp_path / "breaking.jsonl"
    breaking.write_text(json.dumps({"id": first["key_id"], "zh": "こんにちは"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
    assert run("revise", work, breaking) == 1


def test_slice_reserves_keys_so_two_batches_never_overlap(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    dictionary = dict(make_dict(), **add_extra_containers(patch_root))
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(dictionary, ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "2", "--out", tmp_path / "b1.json")
    run("slice", work, "--buckets", "DB", "--units", "2", "--out", tmp_path / "b2.json")
    first = ids_of(tmp_path / "b1.json")
    second = ids_of(tmp_path / "b2.json")
    assert first and second
    assert not (set(first) & set(second)), "a second slice must not re-emit reserved keys"
    # releasing the first batch makes its keys sliceable again
    assert run("release", work, "--batch", tmp_path / "b1.json") == 0
    run("slice", work, "--buckets", "DB", "--units", "2", "--out", tmp_path / "b3.json")
    assert set(first) & set(ids_of(tmp_path / "b3.json"))
    assert run("release", work) == 0          # list what is in flight
    assert run("release", work, "--batch", tmp_path / "nope.json") == 1


def test_answering_a_batch_clears_its_reservation(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    dictionary = dict(make_dict(), **add_extra_containers(patch_root))
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(dictionary, ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "2", "--out", tmp_path / "b1.json")
    payload = json.loads((tmp_path / "b1.json").read_text(encoding="utf-8"))
    values = [fake_translation(fragment["ja"])
              for unit in payload["units"] for fragment in unit["fragments"]]
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    assert run("answer", work, tmp_path / "b1.json", answers, "--positional") == 0
    state = json.loads((work / "state.json").read_text(encoding="utf-8"))
    assert not state.get("in_flight")


def test_terms_checks_only_the_longest_matching_term(tmp_path):
    """`カフェ` (cafe) must not be checked inside `カフェイン値` (caffeine)."""
    work = tmp_path / "work"
    work.mkdir()
    key = "カフェイン値"
    (work / "keymap.jsonl").write_text(
        json.dumps({"key": key, "key_id": "k1", "bucket": "DB",
                    "kind": "whole-field"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (work / "state.json").write_text(
        json.dumps({"scope_buckets": ["DB"], "scope_kinds": ["whole-field"]}),
        encoding="utf-8")
    glossary = tmp_path / "glossary.json"
    glossary.write_text(json.dumps({"game_terms": {"カフェ": "咖啡店",
                                                    "カフェイン値": "咖啡因值"}},
                                   ensure_ascii=False), encoding="utf-8")
    (work / "translated.jsonl").write_text(
        json.dumps({"key_id": "k1", "zh": "咖啡因值+1"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    assert run("terms", work, glossary) == 0
    # a value that ignores the *longest* term is still reported
    (work / "translated.jsonl").write_text(
        json.dumps({"key_id": "k1", "zh": "咖啡店+1"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    assert run("terms", work, glossary) == 1


def test_terms_treats_spelling_variants_as_one_source(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    ids = ["k1", "k2", "k3"]
    sources = ["基本ピクチャ番号", "基本ﾋﾟｸﾁｬ番号", "基本ピク番"]
    (work / "keymap.jsonl").write_text("".join(
        json.dumps({"key": src, "key_id": key, "bucket": "DB", "kind": "whole-field"},
                   ensure_ascii=False) + "\n"
        for key, src in zip(ids, sources, strict=True)), encoding="utf-8")
    (work / "state.json").write_text(
        json.dumps({"scope_buckets": ["DB"], "scope_kinds": ["whole-field"]}),
        encoding="utf-8")
    (work / "translated.jsonl").write_text("".join(
        json.dumps({"key_id": key, "zh": "基本图片编号"}, ensure_ascii=False) + "\n"
        for key in ids), encoding="utf-8")
    glossary = tmp_path / "glossary.json"
    glossary.write_text(json.dumps({"ui": {}}, ensure_ascii=False), encoding="utf-8")
    # three spellings of one term sharing one translation is correct, not collapse
    assert run("terms", work, glossary) == 0
    # unrelated sources sharing one short value is still reported
    unrelated = ["おはよう", "こんばんは", "ありがとう"]
    (work / "keymap.jsonl").write_text("".join(
        json.dumps({"key": src, "key_id": key, "bucket": "DB", "kind": "whole-field"},
                   ensure_ascii=False) + "\n"
        for key, src in zip(ids, unrelated, strict=True)), encoding="utf-8")
    (work / "translated.jsonl").write_text("".join(
        json.dumps({"key_id": key, "zh": "好"}, ensure_ascii=False) + "\n"
        for key in ids), encoding="utf-8")
    assert run("terms", work, glossary) == 1


def test_terms_accepts_a_declared_false_positive(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "keymap.jsonl").write_text(
        json.dumps({"key": "学校の体育館には行ってみたかしら？", "key_id": "k1",
                    "bucket": "DB", "kind": "whole-field"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (work / "state.json").write_text(
        json.dumps({"scope_buckets": ["DB"], "scope_kinds": ["whole-field"]}),
        encoding="utf-8")
    (work / "translated.jsonl").write_text(
        json.dumps({"key_id": "k1", "zh": "学校的体育馆你去过了吗？"},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    glossary = tmp_path / "glossary.json"
    glossary.write_text(json.dumps({"characters": {"たかし": "隆"}},
                                   ensure_ascii=False), encoding="utf-8")
    assert run("terms", work, glossary) == 1          # the name collides with かしら
    accepted = tmp_path / "ignore.jsonl"
    accepted.write_text(json.dumps({"term": "たかし", "key_id": "k1",
                                    "reason": "普通語の一部"}, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    assert run("terms", work, glossary, "--ignore", accepted) == 0
    # an ignore entry for another id does not silence this one
    other = tmp_path / "other.jsonl"
    other.write_text(json.dumps({"term": "たかし", "key_id": "k9"},
                                ensure_ascii=False) + "\n", encoding="utf-8")
    assert run("terms", work, glossary, "--ignore", other) == 1


def test_answer_fix_newlines_restores_only_edge_breaks(tmp_path):
    assert mk._restore_line_breaks("「おはよう」\n", "「早上好」") == "「早上好」\n"
    assert mk._restore_line_breaks("\n「おはよう」", "「早上好」") == "\n「早上好」"
    # interior structure differs -> untouched, so the gate still rejects it
    assert mk._restore_line_breaks("一\n二\n", "一二\n") == "一二\n"
    assert mk._restore_line_breaks("一\n二", "一\n二") == "一\n二"


def test_normalize_replaces_only_the_listed_symbols(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "translated.jsonl").write_text(
        json.dumps({"key_id": "k1", "zh": "★你好★ ♪～"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    table = tmp_path / "symbols.json"
    table.write_text(json.dumps({"★": "◆", "♪": "〜"}, ensure_ascii=False),
                     encoding="utf-8")
    assert run("normalize", work, table) == 0
    stored = json.loads((work / "translated.jsonl").read_text(encoding="utf-8"))
    assert stored["zh"] == "◆你好◆ 〜～"
    assert stored["symbol_normalized"] is True
    assert run("normalize", work, table) == 0      # idempotent
    bad = tmp_path / "bad.json"
    bad.write_text('["not", "a", "map"]', encoding="utf-8")
    assert run("normalize", work, bad) == 1


def test_gates_report_characters_the_font_cannot_draw(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "keymap.jsonl").write_text(
        json.dumps({"key": "テスト", "key_id": "k1", "bucket": "DB",
                    "kind": "whole-field"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (work / "state.json").write_text(
        json.dumps({"scope_buckets": ["DB"], "scope_kinds": ["whole-field"]}),
        encoding="utf-8")
    (work / "translated.jsonl").write_text(
        json.dumps({"key_id": "k1", "zh": "測試"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    font = Path("C:/Windows/Fonts/arial.ttf")
    if not font.is_file():
        return                                       # no font on this machine
    assert run("gates", work, "--font", font) == 1    # traditional glyphs absent


def test_align_backslash_runs_splices_by_position(tmp_path):
    # the value uses the engine's single backslash; the source has it doubled
    ja = "紗愛\\r\n「あっ…\\\\i[403]んっ…\\\\i[403]」"
    zh = "纱爱\\r\n「啊…\\i[403]嗯…\\i[403]」"
    fixed = mk._align_backslash_runs(ja, zh)
    assert mk.collect_codes(fixed) == mk.collect_codes(ja)
    assert fixed.startswith("纱爱") and fixed.endswith("」")
    # a different code name is not "aligned away"
    assert mk._align_backslash_runs("\\f[30]あ", "\\i[402]啊") == "\\i[402]啊"


def test_revise_upsert_inserts_derived_values(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    key = "おはよう"
    (work / "keymap.jsonl").write_text(
        json.dumps({"key": key, "key_id": "k1", "bucket": "MPS",
                    "kind": "whole-field"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (work / "state.json").write_text(
        json.dumps({"scope_buckets": ["MPS"], "scope_kinds": ["whole-field"]}),
        encoding="utf-8")
    (work / "translated.jsonl").write_text("", encoding="utf-8")
    answers = tmp_path / "derived.jsonl"
    answers.write_text(json.dumps({"id": "k1", "zh": "早上好"}, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    assert run("revise", work, answers) == 1                  # not stored yet
    assert run("revise", work, answers, "--upsert") == 0       # explicit insert
    stored = json.loads((work / "translated.jsonl").read_text(encoding="utf-8"))
    assert stored["zh"] == "早上好" and stored["derived"] is True
    assert run("gates", work) == 0


def test_kana_inside_codes_only_is_narrow(tmp_path):
    assert mk.kana_inside_codes_only("\\r[汉字,かんじ]")
    assert not mk.kana_inside_codes_only("汉字かんじ")
    assert not mk.kana_inside_codes_only("汉字")


def test_slice_chunks_runtime_keys_into_units(tmp_path):
    """Runtime keys have no hosting field: a batch chunks them, never one blob."""
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dictionary = make_dict()
    for index in range(30):
        dictionary[f"マップ名{index}"] = "地图名"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(dictionary, ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0
    assert run("import-keys", work, dict_path) == 0
    out = tmp_path / "rt.json"
    assert run("slice", work, "--buckets", "RUNTIME", "--kinds", "runtime",
               "--units", "10", "--out", str(out)) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    sizes = [len(unit["fragments"]) for unit in payload["units"]]
    assert sum(sizes) == 10                      # the fragment cap holds
    assert all(0 < size <= 10 for size in sizes)
    assert all(unit["ctx"] == "[RUNTIME]" for unit in payload["units"])
    # every runtime key carries its own id, so answers can be matched back
    ids = [fragment["key_id"] for unit in payload["units"] for fragment in unit["fragments"]]
    assert len(set(ids)) == len(ids)


PATH_PATCH = """\
> BEGIN STRING
SE/ドア.mp3
> CONTEXT [NEW] COMMONEVENT:1105/cmd/[9]Sound/0

> END STRING

> BEGIN STRING
トイレドア
> CONTEXT [NEW] COMMONEVENT:1106/cmd/[9]Sound/0

> END STRING
"""


def test_skip_by_host_field_covers_every_piece_of_a_resource_path(tmp_path):
    """A sub-line piece of `SE/x.mp3` carries no extension but is still a file."""
    patch_root = tmp_path / "patch"
    write_patch(patch_root, name="res.txt", text=PATH_PATCH)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps({"SE/ドア.mp3": "SE/ドア.mp3",
                                     "ドア": "门",
                                     "トイレドア": "厕所门"},
                                    ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0
    # a slice fixes the scope; skip only ever touches keys inside it
    assert run("slice", work, "--buckets", "COMMONEVENT",
               "--kinds", "whole-field,line-aligned,sub-line",
               "--units", "10", "--out", str(tmp_path / "batch.json")) == 0
    assert run("skip", work, "--host-regex", r"\.mp3$", "--reason", "resource path") == 0
    skipped = [json.loads(line) for line
               in (work / "skipped.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {row["key"] for row in skipped} == {"SE/ドア.mp3", "ドア"}
    assert all(row["reason"] == "resource path" for row in skipped)
    # and a ctx selector can name a command instead of a field
    assert run("skip", work, "--ctx-regex", r"\]Sound/", "--reason", "sound file name") == 0
    rows = [json.loads(line) for line
            in (work / "skipped.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row["key"] == "トイレドア" and row["reason"] == "sound file name" for row in rows)
    # nothing left in scope means the command fails loudly rather than no-op
    assert run("skip", work, "--ctx-regex", r"\]Sound/", "--reason", "again") == 1


def test_answer_ignores_a_key_decided_skip_after_slicing(tmp_path):
    """The batch may already be out when the decision to skip is taken."""
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0
    out = tmp_path / "batch.json"
    assert run("slice", work, "--buckets", "DB,COMMONEVENT,MPS", "--units", "10",
               "--out", str(out)) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    frags = [fragment for unit in payload["units"] for fragment in unit["fragments"]]
    assert len(frags) > 1
    first = frags[0]
    assert run("skip", work, "--where", re.escape(first["ja"]), "--reason", "late decision") == 0
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(["\u4e0d\u7ba1\u4e5d\u4e8c\u4e03\u4e00"]
                                  + [fake_translation(f["ja"]) for f in frags[1:]],
                                  ensure_ascii=False), encoding="utf-8")
    assert run("answer", work, out, answers, "--positional") == 0
    stored = {json.loads(line)["key_id"] for line
              in (work / "translated.jsonl").read_text(encoding="utf-8").splitlines()}
    assert first["key_id"] not in stored          # the skip is honoured
    assert {f["key_id"] for f in frags[1:]} <= stored


def test_resolve_keeps_one_value_and_reports_the_other(tmp_path):
    """The dictionary is keyed by source text, so it can hold only one value."""
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0
    out = tmp_path / "batch.json"
    assert run("slice", work, "--buckets", "MPS", "--units", "10", "--out", str(out)) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    fragment = payload["units"][0]["fragments"][0]
    # two writers stored two values for the same source text
    rows = [
        {"key_id": fragment["key_id"], "zh": "（括号冗余）", "key": fragment["ja"]},
        {"key_id": fragment["key_id"], "zh": "字符", "key": fragment["ja"]},
    ]
    (work / "translated.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    report = tmp_path / "losers.jsonl"
    assert run("resolve", work, "--report", str(report)) == 0
    kept = [json.loads(line) for line
            in (work / "translated.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(kept) == 1
    assert kept[0]["zh"] == "字符"          # the source has no brackets of its own
    dropped = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    assert len(dropped) == 1 and dropped[0]["dropped"] == "（括号冗余）"


def test_import_keys_can_adopt_labels_without_kana(tmp_path):
    """A kanji-only key still reached the dictionary because the game drew it."""
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dictionary = make_dict()
    dictionary["\u5009\u5eab"] = "\u4ed3\u5e93"        # kanji only, no kana
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(dictionary, ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0
    before = (work / "keymap.jsonl").read_text(encoding="utf-8")
    assert "\u5009\u5eab" not in before             # kana-only mapping skips it
    assert run("import-keys", work, dict_path, "--all") == 0
    after = (work / "keymap.jsonl").read_text(encoding="utf-8")
    adopted = [json.loads(line) for line in after.splitlines()]
    assert any(record["key"] == "\u5009\u5eab" and record["kind"] == "runtime"
               for record in adopted)


def test_gates_treats_a_recorded_kana_in_code_row_as_an_exception(tmp_path):
    """An exception that was opted in per row must not read as an unhandled failure."""
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0
    out = tmp_path / "batch.json"
    assert run("slice", work, "--buckets", "DB,COMMONEVENT,MPS", "--units", "10",
               "--out", str(out)) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    frags = [fragment for unit in payload["units"] for fragment in unit["fragments"]]
    first, rest = frags[0], frags[1:]
    (work / "translated.jsonl").write_text(json.dumps(
        {"key_id": first["key_id"], "zh": "\\r[译名,かな]", "kana_in_code": True},
        ensure_ascii=False) + "\n", encoding="utf-8")
    (work / "skipped.jsonl").write_text("\n".join(
        json.dumps({"key_id": fragment["key_id"], "key": fragment["ja"],
                    "reason": "test"}, ensure_ascii=False) for fragment in rest) + "\n",
        encoding="utf-8")
    assert run("gates", work, "--json", str(tmp_path / "report.json")) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["kana_in_code"] == [first["key_id"]]
    assert report["invalid"] == []


def test_export_ships_decided_skips_but_refuses_undecided_keys(tmp_path):
    """"We decided not to" and "nobody looked at it" must not read the same."""
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dictionary = make_dict()
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(dictionary, ensure_ascii=False), encoding="utf-8")
    assert run("build", dict_path, patch_root, work) == 0
    out = tmp_path / "batch.json"
    assert run("slice", work, "--buckets", "DB,COMMONEVENT,MPS", "--units", "10",
               "--out", str(out)) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    frags = [fragment for unit in payload["units"] for fragment in unit["fragments"]]
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps([fake_translation(f["ja"]) for f in frags],
                                  ensure_ascii=False), encoding="utf-8")
    assert run("answer", work, out, answers, "--positional") == 0
    target = tmp_path / "dict-out.json"
    # a dictionary key nobody decided anything about still blocks the export
    assert run("export", work, dict_path, target) == 1
    rows = [{"key_id": mk.key_id(key), "key": key, "reason": "test decision"}
            for key in dictionary]
    (work / "skipped.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    assert run("export", work, dict_path, target) == 0
    shipped = json.loads(target.read_text(encoding="utf-8"))
    assert list(shipped) == list(dictionary)      # decided skips keep the original


def test_export_refuses_a_partial_dictionary_without_the_flag(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    assert run("export", work, dict_path, tmp_path / "out.json") == 1


def test_answer_fills_and_stores_one_batch(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "2")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    rows = [json.dumps({"id": fragment["key_id"],
                        "zh": fake_translation(fragment["ja"])}, ensure_ascii=False)
            for unit in payload["units"] for fragment in unit["fragments"]]
    answers = tmp_path / "answers.jsonl"
    answers.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run("answer", work, batch_path, answers, "--note", "sample") == 0
    stored = [json.loads(line) for line in
              (work / "translated.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(stored) == len(rows)
    assert all(row["note"] == "sample" for row in stored)
    # a multi-line value survives the JSONL path (a TSV cannot carry one)
    multiline = [row for row in stored if "\n" in row["zh"]]
    assert multiline, "expected at least one multi-line fragment in this batch"


def test_answer_refuses_a_partial_or_unknown_tsv(tmp_path):
    patch_root = tmp_path / "patch"
    write_patch(patch_root)
    work = tmp_path / "work"
    dict_path = tmp_path / "dict.json"
    dict_path.write_text(json.dumps(make_dict(), ensure_ascii=False), encoding="utf-8")
    run("build", dict_path, patch_root, work)
    run("slice", work, "--buckets", "DB", "--units", "3")
    batch_path = sorted((work / "batches").glob("*.json"))[-1]
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    first = payload["units"][0]["fragments"][0]
    short = tmp_path / "short.tsv"
    short.write_text(f"{first['key_id']}\t{fake_translation(first['ja'])}\n", encoding="utf-8")
    assert run("answer", work, batch_path, short) == 1          # incomplete batch
    wrong = tmp_path / "wrong.tsv"
    wrong.write_text("deadbeef\t译\n", encoding="utf-8")
    assert run("answer", work, batch_path, wrong) == 1          # unknown id
    bad_line = tmp_path / "bad.tsv"
    bad_line.write_text("no-tab-here\n", encoding="utf-8")
    assert run("answer", work, batch_path, bad_line) == 1       # malformed row
    assert not (work / "translated.jsonl").exists()
