#!/usr/bin/env python3
"""
extract_text.py - Companion to translate_rpgmaker.py

Creates a key-value translation template from an RPG Maker MZ game when you
have NO translation file yet. Run it, translate the output JSON, then feed the
result back to translate_rpgmaker.py via --trs.

    python extract_text.py <game_dir> [--output translations.json]

Output JSON format (one entry per translatable text line):
    { "キャラ名": "", "俺の妻だ。": "", ... }

Fill the empty strings with your translation, keep values equal to the key for
names you do not want to change, then run:
    python translate_rpgmaker.py <game_dir> <out_dir> --trs translations.json
"""

import glob
import json
import os
import re
import sys
from typing import Annotated


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpgmaker_common  # noqa: E402
import rpgmaker_constants  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

# Same whitelist as translate_rpgmaker.py
DISPLAY_KEYS = {
    "name", "nickname", "profile", "description",
    "message1", "message2", "message3", "message4", "text",
}
EVENT_TEXT_IDX = {401: [0], 405: [0], 101: [4], 402: [1], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = rpgmaker_constants.SYSTEM_TEXT_FIELDS
SYSTEM_TEXT_ARRAYS = rpgmaker_constants.SYSTEM_TEXT_ARRAYS

# Same directive guard as translate_rpgmaker.py: comment (408) lines used as
# plugin commands are not display text and must not be extracted.
DIRECTIVE_RE = re.compile(
    r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)

SEGMENT_RE = re.compile(r"(\\\.|\n)")

# Japanese text detector: hiragana / katakana / CJK ideographs
JA_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def is_japanese(s):
    return bool(JA_RE.search(s))


def collect_segments(s, out):
    """Split a text on line-break control codes into clean lines."""
    for part in SEGMENT_RE.split(s):
        if part in ("\\", ".", "\n"):
            continue
        part = part.strip()
        if part and is_japanese(part):
            out.append(part)


def _seg_choice(params, out):
    """Code 102: every choice caption."""
    if not (params and isinstance(params[0], list)):
        return
    for x in params[0]:
        if isinstance(x, str):
            collect_segments(x, out)


def _seg_event_text(code, params, out):
    """Codes in EVENT_TEXT_IDX: the display-text operands."""
    for idx in EVENT_TEXT_IDX[code]:
        if idx < len(params) and isinstance(params[idx], str) and params[idx]:
            collect_segments(params[idx], out)


def _seg_script_operand(params, out):
    """Code 122: operands 3/4 (this pass has no JS-code exclusion)."""
    for idx in (3, 4):
        if idx < len(params) and isinstance(params[idx], str) and params[idx]:
            collect_segments(params[idx], out)


def _seg_comment(params, out):
    """Code 408: a comment line shown by choice-help plugins."""
    if params and isinstance(params[0], str) and params[0] \
            and not DIRECTIVE_RE.match(params[0]):
        collect_segments(params[0], out)


def process_commands(cmds, out):
    for cmd in cmds:
        code = cmd.get("code")
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        if code == 102:
            _seg_choice(params, out)
        elif code in EVENT_TEXT_IDX:
            _seg_event_text(code, params, out)
        elif code == 122:
            _seg_script_operand(params, out)
        elif code == 408:
            _seg_comment(params, out)


def process_db(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in DISPLAY_KEYS and isinstance(v, str):
                collect_segments(v, out)
            else:
                process_db(v, out)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, out)


def process_system(system, out):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            collect_values(system[f], out)


def collect_values(obj, out):
    if isinstance(obj, str):
        collect_segments(obj, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_values(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_values(v, out)


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
        lst = ev.get("list")
        if isinstance(lst, list):
            yield lst
        pages = ev.get("pages")
        if isinstance(pages, list):
            for pg in pages:
                if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                    yield pg["list"]


def is_event_container(data):
    return rpgmaker_common.is_event_container(data)


def cmd(game_dir: Annotated[str, cliutil.Argument(help="source game folder")],
        output: Annotated[str, cliutil.Option(
            "--output",
            help="output JSON template path (default: translations.json)"
        )] = "translations.json",
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Extract RPG Maker MZ/MV display text into a translation template."""
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("extract text", game_dir=game_dir, output=output)

    game_dir = os.path.abspath(game_dir)
    if not os.path.isdir(game_dir):
        return cliutil.fail(f"game_dir not found: {game_dir}")

    seen = []
    data_dir = os.path.join(game_dir, "data")
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if is_event_container(data):
            if isinstance(data, dict):
                dn = data.get("displayName")
                if isinstance(dn, str) and dn:
                    collect_segments(dn, seen)
            for lst in iter_command_lists(data):
                process_commands(lst, seen)
            for ev in iter_event_containers(data):
                if isinstance(ev, dict) and isinstance(ev.get("name"), str) and ev["name"]:
                    collect_segments(ev["name"], seen)
        elif os.path.basename(path) == "System.json":
            process_system(data, seen)
        else:
            process_db(data, seen)

    scenario_path = os.path.join(data_dir, "..", "scenario", "Scenario.json")
    if os.path.isfile(scenario_path):
        with open(scenario_path, encoding="utf-8") as f:
            scenario = json.load(f)
        for chunk in scenario.values() if isinstance(scenario, dict) else scenario:
            if isinstance(chunk, list):
                process_commands(chunk, seen)
            elif isinstance(chunk, str):
                collect_segments(chunk, seen)

    unique = list(dict.fromkeys(seen))
    template = dict.fromkeys(unique, "")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)

    print("extracted %d unique text entries -> %s" % (len(unique), output))
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="extract_text.py")


if __name__ == "__main__":
    raise SystemExit(main())
