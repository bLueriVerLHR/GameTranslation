#!/usr/bin/env python3
"""Tests for tools/resolve_text_keys.py (build-time ``\\T[id]`` inlining).

Fixtures are synthetic MZ trees: a text table (``csv/UI.csv``), a runtime
dictionary in the MTool term shape and a build whose display strings are keys.
The point is to pin the resolution tiers, the "display text only" rule (which
is delegated to qc_build_kana) and the write/no-write behaviour, without
shipping any game's data.
"""
import json
import os

import pytest

import resolve_text_keys as rtk

# hand-written, spelled with escapes so the file stays ASCII-safe
ZH_NEW_GAME = "\u65b0\u6e38\u620f"                  # 新游戏
ZH_CONTINUE = "\u7ee7\u7eed"                        # 继续
ZH_LUCIA = "\u9732\u897f\u5a05"                     # 露西娅
ZH_SWORD = "\u5251"                                 # 剑
JP_NEW_GAME = "\u521d\u3081\u304b\u3089"            # 初めから
JP_CONTINUE = "\u7d9a\u304d"                      # 続き
JP_LUCIA = "\u30eb\u30b7\u30a2"                     # ルシア
JP_SWORD = "\u5263"                                 # 剣
KANA_ONLY = "\u30ec\u30d9\u30eb"                    # レベル
ZH_TABLE = ZH_NEW_GAME


def write_text(path, text, newline="\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)
    return path


def dump_json(path, payload):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def make_table(root, rows=None, header="id,who,tw,cn,en"):
    """``csv/UI.csv``: id, category, japanese, chinese, english."""
    rows = rows if rows is not None else [
        ["SIS1", "コマンド", JP_NEW_GAME, ZH_NEW_GAME, "New game"],
        ["SIS2", "コマンド", JP_CONTINUE, ZH_CONTINUE, "Continue"],
        ["N001", "名前", JP_LUCIA, ZH_LUCIA, "Lucia"],
        ["W001", "名前", JP_SWORD, "",          "Sword"],    # cn empty
        ["W002", "名前", JP_SWORD, "",          ""],         # cn+en empty
        ["K001", "",       KANA_ONLY, "",       ""],         # nothing but ja
        ["X001", "",       "",        "",       ""],         # no text at all
    ]
    body = [header] + [",".join(row) for row in rows]
    return write_text(os.path.join(root, "csv", "UI.csv"), "\n".join(body) + "\n")


def make_dict(root, name="\u7ffb\u8bd1\u6587\u4ef6.json"):
    """Runtime dictionary: plain JP->ZH pairs plus MTool term rows."""
    payload = {
        JP_SWORD: ZH_SWORD,                       # plain pair (tier dict.jp)
        "SIS9,コマンド,つづき,接着,Continue": "SIS9,指令,接着,Continue",
        # Korean/JA noise rows must not create ids
        "0,\u63b2\u793a\u677f\u672a\u78ba\u8a8d": "0,\u672a\u786e\u8ba4\u516c\u544a\u677f",
    }
    return dump_json(os.path.join(root, name), payload)


def make_build(root, table=True, dictionary=True, plugins=None):
    """A minimal MZ build whose display strings are text keys."""
    dump_json(os.path.join(root, "data", "System.json"), {
        "gameTitle": ZH_TABLE,
        "title1Name": "\\T[SIS1]",                    # asset stem: never rewritten
        "terms": {"commands": ["\\T[SIS1]", "\\T[SIS2]", None]},
        "sounds": [{"name": "\\T[SIS1]", "volume": 90}],
    })
    dump_json(os.path.join(root, "data", "Items.json"), [
        None,
        {"id": 1, "name": "\\T[N001]", "description": "\\T[W001]",
         "note": "\\T[SIS1]"},                        # note: never rewritten
        {"id": 2, "name": "\\T[SIS9]", "description": "", "note": ""},
    ])
    dump_json(os.path.join(root, "data", "Map001.json"), {
        "displayName": "\u8857",
        "events": [
            {"id": 1, "name": "\\T[N001]",            # event name: never rewritten
             "note": "",
             "pages": [{"list": [
                 {"code": 401, "indent": 0, "parameters": ["\\T[SIS1]\U0001f600"]},
                 {"code": 132, "indent": 0, "parameters": [0, "\\T[SIS1]"]},
                 {"code": 357, "indent": 0, "parameters": [
                     "SomePlugin", "someCommand", "\\T[SIS1]",
                     {"text": "\\T[SIS2]", "flag": True}]},
                 {"code": 101, "indent": 0, "parameters": [
                     "", 0, 0, 2, "\\T[N001]"]},
             ]}]},
        ],
    })
    if table:
        make_table(root)
    if dictionary:
        make_dict(root)
    if plugins is not None:
        os.makedirs(os.path.join(root, "js"), exist_ok=True)
        with open(os.path.join(root, "js", "plugins.js"), "w",
                     encoding="utf-8", newline="\n") as handle:
            handle.write(f"var $plugins =\n{json.dumps(plugins, ensure_ascii=False, indent=4)};\n")
    return root


def load(path):
    with open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


# ------------------------------------------------------------------ parsing

def test_read_text_table_basic(tmp_path):
    path = make_table(str(tmp_path))
    table = rtk.read_text_table(path)
    assert table["SIS1"]["cn"] == ZH_NEW_GAME
    assert table["SIS1"]["tw"] == JP_NEW_GAME
    assert table["W001"]["cn"] == ""


def test_read_text_table_skips_empty_ids_and_pads_short_rows(tmp_path):
    path = write_text(os.path.join(str(tmp_path), "csv", "T.csv"),
                      "id,who,tw,cn,en\n"
                      ",x,y,z,w\n"
                      "A001,who,ja,zh\n")            # missing en
    table = rtk.read_text_table(path)
    assert list(table) == ["A001"]
    assert table["A001"]["en"] == ""


def test_read_text_table_rejects_foreign_header(tmp_path, caplog):
    path = write_text(os.path.join(str(tmp_path), "csv", "N.csv"),
                      "key,value\na,b\n")
    assert rtk.read_text_table(path) == {}
    assert "no 'id' column" in caplog.text


def test_read_text_table_keeps_quoted_cells(tmp_path):
    """Excel-exported cells hold commas and newlines inside quotes."""
    path = write_text(os.path.join(str(tmp_path), "csv", "Q.csv"),
                      'id,who,tw,cn,en\n'
                      'Q1,"cat","line1\nline2","a,b","x"\n')
    table = rtk.read_text_table(path)
    assert table["Q1"]["cn"] == "a,b"
    assert table["Q1"]["tw"] == "line1\nline2"


def test_chinese_field_shapes():
    assert rtk.chinese_field("SIS1,コマンド,{},{},{}".format(JP_NEW_GAME, ZH_NEW_GAME, "New game")) \
        == ZH_NEW_GAME
    assert rtk.chinese_field(f"N001,{JP_LUCIA},{ZH_LUCIA}") == ZH_LUCIA
    # kana-only cells are skipped, an ASCII tail is skipped, id is skipped
    assert rtk.chinese_field("{},{}".format(JP_SWORD, "Sword")) is None
    assert rtk.chinese_field(f"ID,{KANA_ONLY}") is None
    # last CJK-no-kana cell wins when a category is translated too
    assert rtk.chinese_field("SIS1,基本状态,等级,Level") == "\u7b49\u7ea7"


def test_japanese_field_picks_last_kana_cell():
    assert rtk.japanese_field(f"SIS1,コマンド,{JP_NEW_GAME},{ZH_NEW_GAME},New game") == JP_NEW_GAME
    assert rtk.japanese_field(f"SIS1,{ZH_NEW_GAME}") is None


def test_read_term_dict_splits_pairs_and_terms(tmp_path):
    path = make_dict(str(tmp_path))
    pairs, by_id, ja_by_id = rtk.read_term_dict(path)
    assert pairs[JP_SWORD] == ZH_SWORD
    assert by_id["SIS9"] == "\u63a5\u7740"
    assert ja_by_id["SIS9"] == "\u3064\u3065\u304d"
    assert "SIS9,コマンド,つづき,接着,Continue" not in pairs


def test_read_term_dict_tolerates_comment_lines(tmp_path):
    path = write_text(os.path.join(str(tmp_path), "d.json"),
                      '// repack dictionary\n{"a": "b"}\n')
    pairs, _by_id, _ja = rtk.read_term_dict(path)
    assert pairs == {"a": "b"}


# ----------------------------------------------------------------- resolver

def resolver_of(root, **kwargs):
    tables = [rtk.read_text_table(make_table(root))]
    resolver = rtk.Resolver(tables, kwargs.pop("lang", rtk.DEFAULT_LANG))
    pairs, by_id, ja_by_id = rtk.read_term_dict(make_dict(root))
    resolver.add_dict(pairs, by_id, ja_by_id)
    return resolver


def new_stats():
    return rtk.new_stats()


def test_resolver_tier_order(tmp_path):
    resolver = resolver_of(str(tmp_path))
    assert resolver.resolve("SIS1") == (ZH_NEW_GAME, "csv.cn")
    assert resolver.resolve("SIS9") == ("\u63a5\u7740", "dict.id")
    assert resolver.resolve("W001") == (ZH_SWORD, "dict.jp")     # csv ja -> pair
    assert resolver.resolve("K001") == (KANA_ONLY, "csv.tw")     # ja only
    assert resolver.resolve("X001") == (None, "unresolved")


def test_resolver_lang_column(tmp_path):
    resolver = resolver_of(str(tmp_path), lang="en")
    assert resolver.resolve("SIS1") == ("New game", "csv.en")
    assert resolver.resolve("W001") == ("Sword", "csv.en")
    assert resolver.resolve("W002") == (ZH_SWORD, "dict.jp")
    assert resolver.resolve("K001") == (KANA_ONLY, "csv.tw")


def test_resolve_value_keeps_control_codes(tmp_path):
    resolver = resolver_of(str(tmp_path))
    stats = new_stats()
    text = "\\T[SIS1]\\i[177]\\c[17]\\T[N001]\\c[0]"
    assert rtk.resolve_value(text, resolver, stats) \
        == ZH_NEW_GAME + "\\i[177]\\c[17]" + ZH_LUCIA + "\\c[0]"
    assert stats["occurrences"] == 2
    assert stats["tiers"]["csv.cn"] == 2


def test_resolve_value_nested_key(tmp_path):
    """A table cell that holds another key resolves on the following pass."""
    root = str(tmp_path)
    write_text(os.path.join(root, "csv", "UI.csv"),
               "id,who,tw,cn,en\n"
               "A1,,ja,\\T[A2],x\n"
               f"A2,,ja,{ZH_NEW_GAME},y\n")
    resolver = rtk.Resolver([rtk.read_text_table(os.path.join(root, "csv", "UI.csv"))])
    stats = new_stats()
    assert rtk.resolve_value("\\T[A1]", resolver, stats) == ZH_NEW_GAME


def test_resolve_value_terminates_on_self_reference(tmp_path):
    root = str(tmp_path)
    write_text(os.path.join(root, "csv", "UI.csv"),
               "id,who,tw,cn,en\nA1,,ja,\\T[A1],x\n")
    resolver = rtk.Resolver([rtk.read_text_table(os.path.join(root, "csv", "UI.csv"))])
    stats = new_stats()
    assert rtk.resolve_value("\\T[A1]", resolver, stats) == "\\T[A1]"


def test_resolve_value_leaves_unknown_key_verbatim(tmp_path):
    resolver = resolver_of(str(tmp_path))
    stats = new_stats()
    assert rtk.resolve_value("\\T[NOPE]", resolver, stats) == "\\T[NOPE]"
    assert stats["unresolved"]["NOPE"] == 1
    assert stats["tiers"]["unresolved"] == 1


# -------------------------------------------------------------- whole build

def test_resolve_build_rewrites_display_text_only(tmp_path):
    build = make_build(str(tmp_path))
    stats = rtk.resolve_build(build)
    system = load(os.path.join(build, "data", "System.json"))
    items = load(os.path.join(build, "data", "Items.json"))
    map1 = load(os.path.join(build, "data", "Map001.json"))
    commands = map1["events"][0]["pages"][0]["list"]

    assert system["terms"]["commands"][:2] == [ZH_NEW_GAME, ZH_CONTINUE]
    assert items[1]["name"] == ZH_LUCIA
    assert items[1]["description"] == ZH_SWORD          # tier dict.jp
    # engine-read fields stay byte-identical
    assert system["title1Name"] == "\\T[SIS1]"
    assert system["sounds"][0]["name"] == "\\T[SIS1]"
    assert items[1]["note"] == "\\T[SIS1]"
    assert map1["events"][0]["name"] == "\\T[N001]"
    assert commands[1]["parameters"][1] == "\\T[SIS1]"          # 132 BGM name
    assert commands[2]["parameters"][0] == "SomePlugin"          # 357 dispatch
    assert commands[2]["parameters"][1] == "someCommand"
    assert commands[2]["parameters"][2] == "\\T[SIS1]"           # editor label
    assert commands[2]["parameters"][3]["text"] == ZH_CONTINUE   # rendered arg
    # dialogue line keeps its trailing emoji
    assert commands[0]["parameters"][0] == ZH_NEW_GAME + "\U0001f600"
    assert commands[3]["parameters"][4] == ZH_LUCIA              # 101 face name?
    assert stats["skipped_non_display"] > 0
    assert stats["unresolved"] == {}
    # every rewritten display field is free of keys; the asset fields keep them
    assert rtk.TEXT_KEY.search(json.dumps(system["terms"], ensure_ascii=False)) \
        is None


def test_resolve_build_supports_both_command_shapes(tmp_path):
    """MV writes ``[401, 0, "text"]``; the walker must write back in place."""
    build = make_build(str(tmp_path), table=True, dictionary=True)
    dump_json(os.path.join(build, "data", "Map002.json"), {
        "events": [{"id": 1, "name": "E", "note": "",
                    "pages": [{"list": [[401, 0, "\\T[SIS2]"]]}]}],
    })
    rtk.resolve_build(build)
    map2 = load(os.path.join(build, "data", "Map002.json"))
    assert map2["events"][0]["pages"][0]["list"][0][2] == ZH_CONTINUE


def test_resolve_build_rewrites_plugin_parameters(tmp_path):
    build = make_build(str(tmp_path), plugins=[
        {"name": "QuestSystem.js", "status": True, "parameters": {
            "title": "\\T[SIS1]",
            "blob": json.dumps({"label": "\\T[N001]", "size": 3}),
            "flag": True,
        }},
    ])
    rtk.resolve_build(build)
    with open(os.path.join(build, "js", "plugins.js"), encoding="utf-8") as fh:
        text = fh.read()
    plugins = json.loads(text[text.index("["):text.rindex("]") + 1])
    params = plugins[0]["parameters"]
    assert params["title"] == ZH_NEW_GAME
    blob = json.loads(params["blob"])           # JSON-in-JSON stays valid
    assert blob["label"] == ZH_LUCIA
    assert blob["size"] == 3


def test_resolve_build_dry_run_writes_nothing(tmp_path):
    build = make_build(str(tmp_path), plugins=[
        {"name": "P.js", "status": True, "parameters": {"a": "\\T[SIS1]"}}])
    before = {}
    for rel in ("data/System.json", "data/Items.json", "js/plugins.js"):
        with open(os.path.join(build, rel), encoding="utf-8") as fh:
            before[rel] = fh.read()
    stats = rtk.resolve_build(build, write=False)
    assert sum(stats["tiers"].values()) > 0
    for rel, text in before.items():
        with open(os.path.join(build, rel), encoding="utf-8") as fh:
            assert fh.read() == text


def test_resolve_build_is_idempotent(tmp_path):
    build = make_build(str(tmp_path))
    first = rtk.resolve_build(build)
    assert first["occurrences"] > 0
    second = rtk.resolve_build(build)
    assert second["occurrences"] == 0
    assert second["changed_files"] == []
    assert sum(second["tiers"].values()) == 0


def test_resolve_build_reports_sources_and_changed_files(tmp_path):
    build = make_build(str(tmp_path))
    stats = rtk.resolve_build(build)
    assert stats["sources"]["UI.csv"] == 7
    assert stats["sources"]["\u7ffb\u8bd1\u6587\u4ef6.json"] > 0
    assert "System.json" in stats["changed_files"]
    assert "Items.json" in stats["changed_files"]


def test_resolve_build_without_tables_keeps_keys(tmp_path, caplog):
    build = make_build(str(tmp_path), table=False, dictionary=False)
    stats = rtk.resolve_build(build)
    assert stats["occurrences"] == 0
    assert stats["tiers"]["unresolved"] > 0
    assert stats["unresolved"]
    assert "nothing to resolve" in caplog.text


def test_resolve_build_without_data_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        rtk.resolve_build(str(tmp_path))


def test_find_dict_autodetects_root_dictionary(tmp_path):
    build = make_build(str(tmp_path))
    assert os.path.basename(rtk.find_dict(build)) \
        == "\u7ffb\u8bd1\u6587\u4ef6.json"


def test_find_tables_lists_csv_dir(tmp_path):
    build = make_build(str(tmp_path))
    assert [os.path.basename(p) for p in rtk.find_tables(build)] == ["UI.csv"]


def test_format_report_mentions_tiers_and_unresolved(tmp_path):
    build = make_build(str(tmp_path))
    stats = rtk.resolve_build(build)
    stats["unresolved"]["ZZZ9"] += 3
    text = "\n".join(rtk.format_report(stats))
    assert "csv.cn" in text and "dict.id" in text
    assert "ZZZ9" in text


def test_resolver_pattern_is_the_shared_codes_pattern():
    """The inliner and the QC gate must agree byte-for-byte."""
    from translation import codes as tcodes
    assert rtk.TEXT_KEY is tcodes.TEXT_KEY_RE


def test_escape_for_round_trips_through_json_levels():
    text = 'a "b" \\ c\n d'
    assert rtk.escape_for(text, 0) == text
    assert json.loads(f'"{rtk.escape_for(text, 1)}"') == text
    once = json.loads(f'"{rtk.escape_for(text, 2)}"')
    assert json.loads(f'"{once}"') == text


def test_nested_json_parameter_keeps_parsing(tmp_path):
    """A key two JSON levels deep must be inlined at its own escaping level.

    Real case: QuestSystem's ``QuestDatas`` holds a JSON list of JSON strings
    (``\\T[id]`` after the first parse), and a naive replacement left
    ``"Title":"\\药草采集"`` - invalid escape, the game died at boot with
    ``SyntaxError: ... is not valid JSON``.
    """
    root = str(tmp_path)
    write_text(os.path.join(root, "csv", "UI.csv"),
               'id,who,tw,cn,en\nQ1,,,"line1\nline2",x\n')
    inner = json.dumps({"Title": "\\T[Q1]"}, ensure_ascii=False)
    make_build(root, table=False, dictionary=False, plugins=[
        {"name": "QuestSystem.js", "status": True,
         "parameters": {"QuestDatas": json.dumps([inner], ensure_ascii=False)}},
    ])
    rtk.resolve_build(root)
    with open(os.path.join(root, "js", "plugins.js"), encoding="utf-8") as fh:
        text = fh.read()
    params = json.loads(text[text.index("["):text.rindex("]") + 1])[0]["parameters"]
    outer = json.loads(params["QuestDatas"])          # the plugin's first parse
    title = json.loads(outer[0])["Title"]              # ... and the second
    assert title == "line1\nline2"                      # newline survived


def test_resolved_build_passes_the_acceptance_scan(tmp_path):
    """Cross-tool: after inlining, qc_build_kana must find no text keys."""
    import qc_build_kana as qc
    build = make_build(str(tmp_path))
    rtk.resolve_build(build)
    findings = qc.scan(build)
    assert findings["text_keys"] == []
    assert qc.main([build]) == 0


# --------------------------------------------------------------------- CLI

def test_main_writes_and_reports(tmp_path, capsys):
    build = make_build(str(tmp_path))
    report = os.path.join(str(tmp_path), "report.json")
    assert rtk.main([build, "--report", report]) == 0
    payload = load(report)
    assert payload["tiers"]["csv.cn"] > 0
    assert payload["changed_files"]
    assert payload["unresolved"] == {}


def test_main_dry_run_keeps_keys(tmp_path):
    build = make_build(str(tmp_path))
    assert rtk.main([build, "--dry-run"]) == 0
    assert "\\T[SIS1]" in json.dumps(load(os.path.join(build, "data", "System.json")),
                                     ensure_ascii=False)


def test_main_strict_fails_on_unresolved(tmp_path):
    build = make_build(str(tmp_path))
    dump_json(os.path.join(build, "data", "Extra.json"),
              [{"name": "\\T[ZZZ9]", "description": ""}])
    assert rtk.main([build]) == 0                  # default: report only
    # the unresolved key is still on disk -> --strict refuses
    assert rtk.main([build, "--strict"]) == 1
    assert rtk.main([build, "--dry-run", "--strict"]) == 1


def test_main_fails_on_non_build(tmp_path):
    assert rtk.main([str(tmp_path)]) == 1


def test_main_honours_explicit_csv_and_dict(tmp_path):
    build = make_build(str(tmp_path), table=False, dictionary=False)
    table = make_table(str(tmp_path))
    dictionary = make_dict(str(tmp_path))
    assert rtk.main([build, "--csv", table, "--dict", dictionary]) == 0
    system = load(os.path.join(build, "data", "System.json"))
    assert system["terms"]["commands"][0] == ZH_NEW_GAME
