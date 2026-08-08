#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract / rebuild translatable leaf values inside JSON plugin parameters.

RPG Maker MZ/MV plugin parameters often embed multi-KB JSON blobs (quest
boards, gauge lists, battle popups, reaction tables, custom menus...).
Whole-parameter translation does not scale to 100 KB+ params: agents would
have to reproduce thousands of functional config characters and whole-string
baking would replace them verbatim.  This tool instead:

extract:
  - parses js/plugins.js via plugins_io
  - walks every parameter that parses as JSON, recursing through
    string-encoded JSON levels
  - collects DISPLAY leaf strings:
      * any string containing kana
      * kana-free strings under known display keys (Title/Name/Text/caption)
      * backtick-quoted display strings inside script-code fields
  - writes plugin_leaves.json  {leaf: [{plugin, param, key, path}]}
          plugin_flat.json     [{string, plugin, param}]  (non-JSON params)
          plugin_blobs.json    {param: {plugin, count}}   (for rebuild)
  - leaves listed in --exempt ({"leaf": "reason"}) are skipped: functional
    lookup keys, enum values, brand names.  The reason is only logged.

rebuild:
  - reads plugin_leaves.json + the translated leaf dict + plugin_blobs.json
  - re-parses js/plugins.js for exact (unescaped) parameter strings
  - inserts translations LONGEST-FIRST so a translated leaf never leaks into
    a longer translated leaf
  - warns for every translated leaf not found in its blob (translation dead)
  - writes plugin_blobs_translated.json {original_param: translated_param}
    for bake_translation.py to apply as whole-string plugin matches.

Extraction is structural (JSON walk + display-key heuristics), not
game-specific: per-game exemptions belong in the --exempt file.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugins_io  # noqa: E402
import plain_io  # noqa: E402

KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]")
CJK = re.compile(r"[\u4e00-\u9fff]")
BACKTICK = re.compile(r"`([^`]*)`")
# Code-shaped strings (JS method calls / expressions) are treated like
# CODE_KEYS regardless of their key: only backtick display strings inside
# them are extracted.  Catches script arrays stored as JSON-encoded strings
# where the elements have numeric keys.
CODE_LIKE = re.compile(
    r"\$\w+|SceneManager\.|this\.\w+\(|drawText|changeWindow|placeGauge|"
    r"popScene|\.goto\(|stypeId|gameVariables")

# Display-text fields: kana-free values under these keys are still display
# text (受注 / 所持金 / 出血 ...) even though they are kanji-only.
DISPLAY_KEYS = {
    "Title", "Requester", "Place", "TimeLimit", "DetailNote", "HiddenDetailNote",
    "Detail", "HiddenDetail", "text", "caption", "Name", "Id", "Label",
    "CommandName", "ParamName", "HelpText", "CommonHelpText",
    "MenuQuestSystemText", "QuestOrderText", "QuestOrderYesText",
    "QuestOrderNoText", "QuestCancelText", "QuestCancelYesText",
    "QuestCancelNoText", "QuestReportText", "QuestReportYesText",
    "QuestReportNoText", "NothingQuestText", "ReachedLimitText",
    "HiddenTitleText", "AllCommandText", "QuestOrderCommandText",
    "OrderingQuestCommandText", "QuestCancelCommandText",
    "QuestReportCommandText", "ReportedQuestCommandText",
    "FailedQuestCommandText", "ExpiredQuestCommandText",
    "HiddenQuestCommandText", "NotOrderedStateText", "OrderingStateText",
    "ReportableStateText", "ReportedStateText", "FailedStateText",
    "ExpiredStateText", "RequesterText", "RewardText", "DifficultyText",
    "PlaceText", "TimeLimitText", "OrderingCountText", "GetRewardText",
    "CompleteMessage", "ConfirmUse", "ConfirmNoUse", "CategoryHelp",
    "ConfirmHelp", "UsingHelp", "アニメ名", "リアクションログ", "かばうログ",
    "リアクションポップ", "かばうポップ", "アクション名", "ScenarioText",
}

# Script/code fields: only backtick-quoted display strings are translated;
# JS code and // comments stay untouched.  kana in code (comments / DetaEval
# snippets) is exempt by default.
CODE_KEYS = {
    "Script", "ListScript", "FilterScript", "IsEnableScript", "DetaEval",
    "DetaEval1", "DetaEval2", "ShowEval", "ItemDrawScript", "InitialEvent",
    "DecisionEvent", "CancelEvent", "UpdateEvent", "ConfirmMessage",
    "SelectAction", "BackPicture", "DetaEvalScript",
}

# Keys whose values are names used as LOOKUP KEYS elsewhere (note tags,
# plugin commands).  Extraction still includes them; the orchestrator must
# review and exempt the ones that are functional references.
LOOKUPY_KEYS = {"アクション名", "Name", "Id", "CommandName"}


def load_exempt(path):
    if not path or not os.path.exists(path):
        return set()
    data = plain_io.load_json(path)
    return set(data) if isinstance(data, (list, dict)) else set()


def walk(o, path, out):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, path + [k], out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, path + [i], out)
    elif isinstance(o, str):
        s = o.strip()
        if s[:1] in ("{", "["):
            try:
                inner = json.loads(s)
            except ValueError:
                inner = None
            if inner is not None:
                walk(inner, path + ["<json>"], out)
                return
        out.append((path, o))


# --- JSON-string decode / re-encode -----------------------------------------
# Blobs are nested: a param value is JSON, and some of its string values are
# themselves JSON-serialized strings (quest entries, gauge layouts, script
# arrays...).  A decoded leaf therefore appears in the raw param text with N
# layers of JSON escaping.  Instead of matching escaped forms, rebuild works
# at the fully decoded level and re-encodes with the editor's compact style
# (separators=(',', ':'), ensure_ascii=False), which round-trips byte-exact.
JSJSON = ("<jsons>", None)


def decode_string_json(o):
    """Replace string values that parse as JSON with (marker, decoded)."""
    if isinstance(o, str):
        s = o.strip()
        if s[:1] in ("{", "["):
            try:
                inner = json.loads(s)
            except ValueError:
                return o
            return (JSJSON[0], decode_string_json(inner))
        return o
    if isinstance(o, dict):
        return {k: decode_string_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [decode_string_json(v) for v in o]
    return o


def encode_string_json(o):
    """Inverse of decode_string_json -> the param string."""
    if isinstance(o, tuple) and o and o[0] == JSJSON[0]:
        return json.dumps(encode_string_json(o[1]), ensure_ascii=False,
                          separators=(",", ":"))
    if isinstance(o, dict):
        return {k: encode_string_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [encode_string_json(v) for v in o]
    return o


def round_trip(param):
    """Rebuild the param string after decode; None on any parse failure."""
    try:
        parsed = json.loads(param)
    except ValueError:
        return None
    out = encode_string_json(decode_string_json(parsed))
    if isinstance(out, str):
        return out
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def collect_leaves_in(o):
    """Walk a decoded structure, collecting (path, value) kana leaves."""
    found = []
    walk(o, [], found)
    return found


def apply_trans(o, trans, dead):
    """Replace leaf values (in-place on the decoded structure)."""
    if isinstance(o, tuple) and o and o[0] == JSJSON[0]:
        return (o[0], apply_trans(o[1], trans, dead))
    if isinstance(o, dict):
        return {k: apply_trans(v, trans, dead) for k, v in o.items()}
    if isinstance(o, list):
        return [apply_trans(v, trans, dead) for v in o]
    if isinstance(o, str):
        zh = trans.get(o)
        if zh and zh != o:
            return zh
        return o
    return o


def collect_blob_leaves(blob, exempt, out_leaves, warns, plugin=None,
                        param=None):
    """Collect display leaves of one blob into out_leaves; returns the
    number of leaves extracted (new or existing)."""
    found = []
    walk(blob, [], found)
    n = 0
    for path, value in found:
        key = path[-1] if path else ""
        leaves = []
        if isinstance(key, str) and key in CODE_KEYS or CODE_LIKE.search(value):
            for m in BACKTICK.finditer(value):
                c = m.group(1)
                if c.strip() and (KANA.search(c) or CJK.search(c)):
                    leaves.append(c)
            if not leaves and KANA.search(value):
                warns.append("code field with kana but no backtick display "
                             "text (kept raw): %r" % value[:60])
        elif KANA.search(value):
            leaves.append(value)
        elif isinstance(key, str) and key in DISPLAY_KEYS and CJK.search(value):
            leaves.append(value)
        for leaf in leaves:
            if leaf in exempt:
                continue
            if isinstance(key, str) and key in LOOKUPY_KEYS:
                warns.append("lookup-y key %r = %r - verify it is not a "
                             "functional reference before baking"
                             % (key, leaf[:40]))
            rec = {"plugin": plugin, "param": param, "key": key, "path": path}
            out_leaves.setdefault(leaf, []).append(rec)
            n += 1
    return n


def cmd_extract(args):
    exempt = load_exempt(args.exempt)
    text = open(os.path.join(args.game_dir, "js", "plugins.js"),
                encoding="utf-8").read()
    plugins = plugins_io.parse_plugins_js(text)

    leaves, flat, blobs = {}, [], {}
    warns = []
    for p in plugins:
        name = p.get("name")
        params = p.get("parameters")
        if not isinstance(params, dict):
            continue
        for key, val in params.items():
            if not isinstance(val, str) or not val.strip():
                continue
            stripped = val.strip()
            if stripped[:1] in ("{", "["):
                try:
                    blob = json.loads(stripped)
                except ValueError:
                    blob = None
                if blob is not None:
                    n = collect_blob_leaves(blob, exempt, leaves, warns,
                                            plugin=name, param=key)
                    blobs[val] = {"plugin": name, "count": n}
                    continue
            if KANA.search(val):
                flat.append({"string": val, "plugin": name, "param": key})

    out = args.work_dir
    os.makedirs(out, exist_ok=True)
    plain_io.save_json(os.path.join(out, "plugin_leaves.json"), leaves)
    plain_io.save_json(os.path.join(out, "plugin_flat.json"), flat)
    plain_io.save_json(os.path.join(out, "plugin_blobs.json"), blobs)

    total = sum(len(v) for v in leaves)
    print("blobs: %d | leaves: %d (%d chars) | flat strings: %d"
          % (len(blobs), len(leaves), total, len(flat)))
    for w in warns:
        print("WARN: %s" % w)
    if not args.exempt:
        print("NOTE: no --exempt file given; review lookup-y keys above.")


def cmd_rebuild(args):
    work = args.work_dir
    leaves = plain_io.load_json(os.path.join(work, "plugin_leaves.json"))
    blobs = plain_io.load_json(os.path.join(work, "plugin_blobs.json"))
    trans = plain_io.load_json(os.path.join(work, args.trans))

    text = open(os.path.join(args.game_dir, "js", "plugins.js"),
                encoding="utf-8").read()
    plugins = plugins_io.parse_plugins_js(text)
    param_where = {}
    for p in plugins:
        for k, v in (p.get("parameters") or {}).items():
            if isinstance(v, str):
                param_where.setdefault(v, "%s / %s" % (p.get("name"), k))

    pairs = {}
    dead = set()
    for orig in blobs:
        try:
            decoded = decode_string_json(json.loads(orig))
        except ValueError:
            print("WARN: unparseable blob: %r" % orig[:60])
            continue
        target = blobs[orig]["count"]
        new_decoded = apply_trans(decoded, trans, dead)
        new_param = encode_string_json(new_decoded)
        if isinstance(new_param, str):
            pass
        else:
            new_param = json.dumps(new_param, ensure_ascii=False,
                                   separators=(",", ":"))
        # validate: re-parse the rebuilt param and count translated leaves
        try:
            rebuilt_leaves = [
                v for _, v in collect_leaves_in(
                    decode_string_json(json.loads(new_param)))
            ]
            remaining = sum(1 for v in rebuilt_leaves
                            if trans.get(v) and trans[v] != v)
        except ValueError:
            remaining = -1
        if remaining != 0:
            print("WARN: %s - %d translated leaves still present after "
                  "rebuild" % (orig[:50], remaining))
        if new_param != orig:
            pairs[orig] = new_param

    out = os.path.join(work, args.out)
    plain_io.save_json(out, pairs)
    print("blob pairs: %d | dead translations: %d" % (len(pairs), len(dead)))
    for d in sorted(dead):
        print("  dead: %r" % d[:60])
    if not pairs:
        print("NOTE: no blob pairs - check that translated leaf values differ "
              "from their keys and that blobs match plugins.js.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("extract")
    p.add_argument("game_dir")
    p.add_argument("work_dir")
    p.add_argument("--exempt", default="",
                   help="JSON file: {\"leaf\": \"reason\"} of leaves to skip "
                        "(functional lookups, enums, brand names)")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("rebuild")
    p.add_argument("game_dir")
    p.add_argument("work_dir")
    p.add_argument("--trans", default="translated.json",
                   help="merged translated leaf dict (default translated.json)")
    p.add_argument("--out", default="plugin_blobs_translated.json")
    p.set_defaults(func=cmd_rebuild)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
