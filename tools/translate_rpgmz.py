#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_rpgmz.py - Reusable tool for RPG Maker MZ games.

Does three things to a game and writes the result to an output folder:
  1. Copies the whole game tree.
  2. Decrypts encrypted assets (RPGMaker "RPGMV" 16-byte-header scheme) using the
     encryptionKey stored in data/System.json, and clears the encryption flags.
  3. Applies a key-value translation JSON (Japanese -> Chinese / any language) by
     baking the translations into the data/*.json files.

Usage:
    python translate_rpgmz.py <game_dir> <out_dir> [--trs translation.json]
                              [--skip-translate] [--plugins]

The translation JSON is auto-detected in the game root when --trs is omitted.

Decryption details (custom scheme found in this engine's rmmz_core.js):
    header      = first 16 bytes, must equal b'RPGMV\\x00\\x00\\x00\\x00\\x03\\x01\\x00\\x00\\x00\\x00\\x00'
    body        = file bytes from offset 16
    key bytes   = encryptionKey hex string split into 16 bytes
    body[0..15] ^= key bytes
    output file = original name with the trailing underscore removed
"""

import argparse
import collections
import csv
import glob
import io
import json
import os
import re
import shutil
import sys

RPGMV_HEADER = bytes.fromhex("5250474d560000000003010000000000")
SPLIT = re.compile(r"(\\\.|\n)")
# Control codes that must never be translated inside their brackets:
#  - \M[ID]      ExternMessage CSV reference (ID must stay Japanese)
#  - \V/\N/\C/\P/\I/\T[...]  engine control codes (numeric/variable args)
#  - :name[...], :face[...], :word[...], :event[...], :bg[...], :layout[...],
#    :script[...] ... ExternMessage commands (args are IDs/indices)
CTRL_SPLIT = re.compile(
    r"(\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?)", re.S
)

DISPLAY_KEYS = {
    "name", "nickname", "profile", "description",
    "message1", "message2", "message3", "message4", "text",
}
EVENT_TEXT_IDX = {401: [0], 405: [0], 101: [4], 402: [1], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = ["terms", "message", "commands", "equipTypes",
                      "weaponTypes", "armorTypes", "skillTypes", "element"]
SYSTEM_TEXT_ARRAYS = ["variables", "switches"]
# Comment (408) lines that look like plugin directives are never display text
# (e.g. "<tag>...", "//...", "#...", ">...", "PluginCmd: ..."); skip them.
DIRECTIVE_RE = re.compile(
    r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)


def log(msg):
    print(msg, flush=True)


def build_index(D):
    index = collections.defaultdict(list)
    for k in D:
        if k:
            index[k[0]].append(k)
    for c in index:
        index[c].sort(key=len, reverse=True)
    return index


def greedy(s, D, index):
    """Longest-dictionary-key-first greedy fragment replacement."""
    out = []
    i, n = 0, len(s)
    while i < n:
        cands = index.get(s[i])
        m = None
        if cands:
            for k in cands:
                if s.startswith(k, i):
                    m = k
                    break
        if m:
            out.append(D[m])
            i += len(m)
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def translate_text(s, D, index):
    """Translate a text line while protecting engine/plugin control codes.

    Control-code brackets (\\M[ID], \\V[1], :name[NAME,FACE], ...) are kept
    verbatim - their contents are IDs/indices, never display text. Only the
    plain Japanese fragments between control codes are dictionary-translated.
    Exception: the NAME part of :name[NAME,FACE] is display text, so it is
    translated while the face-set token after the comma is kept.
    """
    if not s:
        return s
    if s in D:
        return D[s]
    parts = CTRL_SPLIT.split(s)
    if len(parts) == 1:
        return _translate_plain(s, D, index)
    res = []
    for i, p in enumerate(parts):
        if i % 2 == 1:
            res.append(_translate_ctrl_token(p, D, index))
        else:
            res.append(_translate_plain(p, D, index))
    return "".join(res)


_NAME_CTRL_RE = re.compile(r"^:name\[([^,\]]*)((?:,[^\]]*)?)\]$", re.S)


def _translate_ctrl_token(token, D, index):
    """Keep a control-code token verbatim, except translate a :name display."""
    m = _NAME_CTRL_RE.match(token)
    if not m:
        return token
    name, rest = m.group(1), m.group(2)
    if not name or "\\" in name or "[" in name:
        return token
    return ":name[%s%s]" % (_translate_plain(name, D, index), rest)


def _translate_plain(s, D, index):
    if not s:
        return s
    if s in D:
        return D[s]
    parts = SPLIT.split(s)
    if len(parts) == 1:
        return greedy(s, D, index)
    res = []
    for p in parts:
        if p in ("\n", "\\."):
            res.append(p)
        else:
            res.append(_translate_plain(p, D, index))
    return "".join(res)


# ----------------------------------------------------------------------------
# Decryption
# ----------------------------------------------------------------------------
def decrypt_dir(root):
    system_path = os.path.join(root, "data", "System.json")
    enc_key = ""
    if os.path.exists(system_path):
        try:
            sys_json = json.load(open(system_path, encoding="utf-8"))
            enc_key = sys_json.get("encryptionKey") or ""
        except Exception as e:
            log("WARN: could not read encryptionKey: %s" % e)

    key_bytes = None
    if enc_key:
        try:
            key_bytes = bytes.fromhex(enc_key)
            if len(key_bytes) != 16:
                key_bytes = None
        except ValueError:
            key_bytes = None
    if not key_bytes:
        log("WARN: no usable encryptionKey; skipping decryption")
        return 0

    decrypted = 0
    skipped = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                with open(path, "rb") as f:
                    head = f.read(16)
            except Exception:
                continue
            if len(head) < 16 or head != RPGMV_HEADER:
                continue
            with open(path, "rb") as f:
                data = f.read()
            body = bytearray(data[16:])
            for i in range(min(16, len(body))):
                body[i] ^= key_bytes[i]
            new_path = path[:-1]  # drop trailing underscore
            with open(new_path, "wb") as f:
                f.write(body)
            os.remove(path)
            decrypted += 1
    log("decrypted %d encrypted files" % decrypted)
    return decrypted


def clear_encryption_flags(root):
    system_path = os.path.join(root, "data", "System.json")
    if not os.path.exists(system_path):
        return
    with open(system_path, encoding="utf-8") as f:
        sys_json = json.load(f)
    changed = False
    for flag in ("hasEncryptedImages", "hasEncryptedAudio"):
        if sys_json.get(flag):
            sys_json[flag] = False
            changed = True
    if sys_json.get("encryptionKey"):
        sys_json["encryptionKey"] = ""
        changed = True
    if changed:
        with open(system_path, "w", encoding="utf-8") as f:
            json.dump(sys_json, f, ensure_ascii=False, indent=2)
    log("cleared encryption flags in data/System.json")


# ----------------------------------------------------------------------------
# Translation baking
# ----------------------------------------------------------------------------
def process_commands(cmds, D, index):
    for cmd in cmds:
        code = cmd.get("code")
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        if code == 102 and params and isinstance(params[0], list):
            params[0] = [
                translate_text(x, D, index) if isinstance(x, str) else x
                for x in params[0]
            ]
        elif code in EVENT_TEXT_IDX:
            for idx in EVENT_TEXT_IDX[code]:
                if idx < len(params) and isinstance(params[idx], str) and params[idx]:
                    params[idx] = translate_text(params[idx], D, index)
        elif code == 122:
            # skip script operands (operandType == 4): params[4] is JS code,
            # never display text
            if len(params) > 3 and params[3] == 4:
                pass
            else:
                for idx in (3, 4):
                    if idx < len(params) and isinstance(params[idx], str) and params[idx]:
                        params[idx] = translate_text(params[idx], D, index)
        elif code == 408:
            # Comments are usually invisible, but choice-help plugins display
            # them as menu help text; translate unless directive-like.
            if (params and isinstance(params[0], str) and params[0]
                    and not DIRECTIVE_RE.match(params[0])):
                params[0] = translate_text(params[0], D, index)


def process_db(obj, D, index):
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in DISPLAY_KEYS and isinstance(v, str):
                obj[k] = translate_text(v, D, index)
            elif k == "note" and isinstance(v, str):
                if v in D:  # exact match only, to avoid touching plugin tags
                    obj[k] = D[v]
            else:
                process_db(v, D, index)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, D, index)


def process_system(system, D, index):
    fields = SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS
    for f in fields:
        if f in system:
            system[f] = translate_values(system[f], D, index)


def translate_values(obj, D, index):
    if isinstance(obj, str):
        return translate_text(obj, D, index)
    if isinstance(obj, dict):
        for k in obj:
            obj[k] = translate_values(obj[k], D, index)
        return obj
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = translate_values(obj[i], D, index)
        return obj
    return obj


def iter_event_containers(data):
    containers = []
    if isinstance(data, list):
        containers = data
    elif isinstance(data, dict):
        for key in ("events", "commonEvents"):
            arr = data.get(key)
            if isinstance(arr, list):
                containers.extend(arr)
    return containers


def iter_command_lists(data):
    for ev in iter_event_containers(data):
        if not isinstance(ev, dict):
            continue
        # common events: commands live in a top-level "list"
        lst = ev.get("list")
        if isinstance(lst, list):
            yield lst
        # map events: commands live in each page's "list"
        pages = ev.get("pages")
        if isinstance(pages, list):
            for pg in pages:
                if isinstance(pg, dict):
                    pl = pg.get("list")
                    if isinstance(pl, list):
                        yield pl


def is_event_container(data):
    if isinstance(data, dict):
        return "events" in data or "commonEvents" in data
    if isinstance(data, list):
        return any(
            isinstance(x, dict) and ("list" in x or "pages" in x) for x in data
        )
    return False


def translate_data(root, D, index, do_plugins):
    data_dir = os.path.join(root, "data")
    changed_files = 0
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        fname = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if is_event_container(data):
            # Maps keep their title in a top-level displayName (shown in the
            # in-game map-name banner); event containers skip process_db, so
            # translate it here.
            if isinstance(data, dict):
                dn = data.get("displayName")
                if isinstance(dn, str) and dn:
                    data["displayName"] = translate_text(dn, D, index)
            for lst in iter_command_lists(data):
                process_commands(lst, D, index)
            for ev in iter_event_containers(data):
                if isinstance(ev, dict) and isinstance(ev.get("name"), str) and ev["name"]:
                    ev["name"] = translate_text(ev["name"], D, index)
        elif fname == "System.json":
            process_system(data, D, index)
        else:
            process_db(data, D, index)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        changed_files += 1
    log("translated %d data files" % changed_files)

    scenario_path = os.path.join(root, "scenario", "Scenario.json")
    if os.path.exists(scenario_path):
        with open(scenario_path, encoding="utf-8") as f:
            scenario = json.load(f)
        if isinstance(scenario, dict):
            for k, v in list(scenario.items()):
                if isinstance(v, list):
                    process_commands(v, D, index)
                elif isinstance(v, str):
                    scenario[k] = translate_text(v, D, index)
        elif isinstance(scenario, list):
            for chunk in scenario:
                if isinstance(chunk, list):
                    process_commands(chunk, D, index)
        with open(scenario_path, "w", encoding="utf-8") as f:
            json.dump(scenario, f, ensure_ascii=False, indent=2)
        log("translated scenario/Scenario.json (%d chunks)" %
            (len(scenario) if isinstance(scenario, dict) else len(scenario)))

    if do_plugins:
        plugins_path = os.path.join(root, "js", "plugins.js")
        if os.path.exists(plugins_path):
            with open(plugins_path, encoding="utf-8") as f:
                text = f.read()
            for k, v in D.items():
                if not k or k == v:
                    continue
                if re.fullmatch(r"[A-Za-z0-9_ ]+", k):
                    continue  # skip symbol-like keys
                text = text.replace('"%s"' % k, '"%s"' % v)
                text = text.replace("'%s'" % k, "'%s'" % v)
            with open(plugins_path, "w", encoding="utf-8") as f:
                f.write(text)
            log("patched js/plugins.js")


def add_cjk_font_fallback(root):
    css_path = os.path.join(root, "css", "game.css")
    if not os.path.exists(css_path):
        return
    rule = (
        "\n/* CJK font fallback (added by translate_rpgmz.py) */\n"
        "#gameCanvas, .GameFont {\n"
        '    font-family: "GameFont", "Microsoft YaHei", "PingFang SC",'
        ' "Noto Sans CJK SC", "Source Han Sans SC", sans-serif;\n'
        "}\n"
    )
    with open(css_path, "a", encoding="utf-8") as f:
        f.write(rule)
    log("added CJK font fallback to css/game.css")


def translate_extern_csv(root, D, index):
    """Translate the `data/ExternMessage.csv` dialogue file (ExternMessage.js).

    The CSV is UTF-16LE/BOM (some games shift_jis); rows are
    `名前(ID),本文(body),...`. The ID column is a lookup key referenced from
    events via \\M[ID] and MUST stay Japanese; only the 本文 (body) column is
    translated (control codes inside it are protected by translate_text).
    """
    csv_path = os.path.join(root, "data", "ExternMessage.csv")
    if not os.path.exists(csv_path):
        log("no data/ExternMessage.csv; skipping")
        return 0

    raw = open(csv_path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        text = raw.decode("utf-16")
        write_enc = "utf-16"
    elif raw[:3] == b"\xef\xbb\xbf":
        text = raw.decode("utf-8-sig")
        write_enc = "utf-8"
    else:
        text = raw.decode("cp932", errors="replace")
        write_enc = "cp932"

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    changed = 0
    for r in rows:
        if len(r) >= 2 and r[0].strip() and r[0].strip() != "名前":
            new_body = translate_text(r[1], D, index)
            if new_body != r[1]:
                r[1] = new_body
                changed += 1

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerows(rows)
    out_text = out.getvalue()

    if write_enc == "utf-16":
        data = "\ufeff" + out_text
        data = data.encode("utf-16-le")
    elif write_enc == "utf-8":
        data = ("\ufeff" + out_text).encode("utf-8")
    else:
        data = out_text.encode("cp932", errors="replace")

    with open(csv_path, "wb") as f:
        f.write(data)
    log("translated %d bodies in data/ExternMessage.csv" % changed)
    return changed


def detect_trs(game_dir):
    """Auto-detect a translation JSON in the game root.

    Matches, in priority order:
      1. any `<*>翻译.json` root file (AI翻译.json, A翻译.json, 机翻.json, ...)
      2. any `[aA][iI]<*>.json` root file (AI.json, AI翻译.json, AI翻訳.json, ...)
      3. a root json named exactly `<game folder name>.json`
         (e.g. `<SomeGameTitle>.json`)
      4. the single remaining root `.json` (a game whose only root json IS the
         translation still works)
    """
    cands = []
    for path in glob.glob(os.path.join(game_dir, "*.json")):
        base = os.path.basename(path).lower()
        if base in ("package.json", "npm-debug.log"):
            continue
        cands.append(path)
    if not cands:
        return None

    def first(pred):
        return next((p for p in cands if pred(os.path.basename(p))), None)

    p = first(lambda b: "翻译" in b)
    if p:
        return p
    p = first(lambda b: b.startswith("ai"))
    if p:
        return p
    folder_name = os.path.basename(os.path.normpath(game_dir)).lower()
    p = first(lambda b: b == folder_name + ".json")
    if p:
        return p
    if len(cands) == 1:
        return cands[0]
    cands.sort(key=lambda p: -os.path.getsize(p))
    return cands[0]


def add_mv_cjk_font(root, cjk_font_src):
    """Bundle a CJK font + unicode-range split for MV games.

    MV games load `fonts/gamefont.css` (there is no css/game.css), and their
    original fonts usually cover kana only - simplified-Chinese translated
    text renders as boxes. Fix: copy a CJK ttf into fonts/ and split
    gamefont.css by unicode-range so kana/ASCII keep the original font and
    hanzi use the bundled CJK font.
    """
    fonts_dir = os.path.join(root, "fonts")
    css_path = os.path.join(fonts_dir, "gamefont.css")
    if not os.path.exists(css_path):
        return
    if not cjk_font_src or not os.path.isfile(cjk_font_src):
        log("WARN: --cjk-font not given or missing; MV gamefont.css left as-is")
        return
    cjk_name = os.path.basename(cjk_font_src)
    shutil.copy2(cjk_font_src, os.path.join(fonts_dir, cjk_name))
    css = open(css_path, encoding="utf-8").read()
    font_face = re.search(
        r"@font-face\s*\{[^}]*font-family\s*:\s*([^;}]+);[^}]*src:\s*url\(([^)]+)\);\s*\}",
        css, re.S)
    if not font_face:
        log("WARN: could not parse fonts/gamefont.css; font bundled but css untouched")
        return
    family = font_face.group(1).strip()
    orig_src = font_face.group(2)
    if "unicode-range" in css:
        log("fonts/gamefont.css already has unicode-range split; font bundled")
        return
    split = (
        "@font-face {\n"
        "    font-family: %s;\n"
        "    src: url(%s);\n"
        "    unicode-range: U+0020-00FF, U+3040-30FF;\n"
        "}\n"
        "@font-face {\n"
        "    font-family: %s;\n"
        "    src: url(\"%s\");\n"
        "    unicode-range: U+3000-303F, U+4E00-9FFF, U+F900-FAFF,"
        " U+FF00-FFEF, U+20000-2FA1F;\n"
        "}\n"
    ) % (family, orig_src, family, cjk_name)
    css = re.sub(
        r"@font-face\s*\{[^}]*font-family\s*:\s*[^;}]+;[^}]*src:\s*url\([^)]+\);\s*\}",
        split, css, count=1, flags=re.S)
    with open(css_path, "w", encoding="utf-8") as f:
        f.write(css)
    log("bundled %s and split fonts/gamefont.css by unicode-range" % cjk_name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_dir", help="source game folder")
    ap.add_argument("out_dir", help="output folder (will be created)")
    ap.add_argument("--trs", default=None, help="translation kv JSON file")
    ap.add_argument("--skip-translate", action="store_true",
                    help="only copy + decrypt, do not apply translation")
    ap.add_argument("--plugins", action="store_true",
                    help="also patch js/plugins.js (risky, default off)")
    ap.add_argument("--cjk-font", default="",
                    help="CJK ttf to bundle for MV games (fonts/gamefont.css split)")
    args = ap.parse_args()

    game_dir = os.path.abspath(args.game_dir)
    out_dir = os.path.abspath(args.out_dir)
    if not os.path.isdir(game_dir):
        sys.exit("game_dir not found: %s" % game_dir)
    if os.path.abspath(out_dir) == game_dir:
        sys.exit("out_dir must differ from game_dir")

    # Translation decision flow:
    #   1. did the user ask for a translation?   -> --trs given
    #   2. no -> is there a translation file?    -> detect_trs()
    #   3. yes -> did the user forbid it?        -> --skip-translate
    #   4. not forbidden -> load and apply
    trs_path = args.trs
    if args.skip_translate:
        log("translation disabled by --skip-translate")
    elif not trs_path:
        trs_path = detect_trs(game_dir)
        if trs_path:
            log("auto-detected translation file: %s" % trs_path)
        else:
            log("no translation file detected in game root; translating skipped")
    if trs_path and not os.path.exists(trs_path):
        sys.exit("translation file not found: %s" % trs_path)

    log("copying %s -> %s" % (game_dir, out_dir))
    shutil.copytree(game_dir, out_dir, dirs_exist_ok=True)

    decrypt_dir(out_dir)
    clear_encryption_flags(out_dir)

    if not args.skip_translate and trs_path:
        D = json.load(open(trs_path, encoding="utf-8"))
        index = build_index(D)
        log("loaded %d translation entries from %s" % (len(D), trs_path))
        translate_data(out_dir, D, index, args.plugins)
        translate_extern_csv(out_dir, D, index)
        add_cjk_font_fallback(out_dir)
        add_mv_cjk_font(out_dir, args.cjk_font)
    else:
        log("translation skipped")

    log("done -> %s" % out_dir)


if __name__ == "__main__":
    main()
