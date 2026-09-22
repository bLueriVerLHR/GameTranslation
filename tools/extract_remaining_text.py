#!/usr/bin/env python3
"""Extract remaining Japanese (kana-bearing) display strings from an
already-translated build, in STORY ORDER (MapInfos order -> map -> event ->
page -> command), with a context WINDOW of neighbouring dialogue lines for
each key. Used for the subagent completion workflow.

Keys are per-line / per-field EXACT strings, matching bake_translation.py's
exact lookup (block keys are avoided on purpose: a block may contain already
translated Chinese lines that must not be retranslated).

Also extracts:
- plugin-command arguments (357 arg dict values: DTextPicture text,
  log-window lines, shop names...; the Japanese command NAME is functional
  and never extracted),
- 122 script operands (string literals stored in variables and shown via
  \\V[n] control codes),
- 355/655 script lines whose quoted string literal contains kana
  (BattleManager._logWindow.addText('...') style display lines),

and JA-bearing js/plugins.js plugin parameter strings (kind "plugin",
--no-plugins to skip) and writes name_macros.json (\\N[x] actor-name
macros - control codes are substitution references, never translated; the
referenced name is translated in the DB).
"""
import collections
import json
import os
import re
import sys
from typing import Annotated


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctrl_codes  # noqa: E402
from rpgmaker import japanese as japanese_utils  # noqa: E402
import plain_io  # noqa: E402
from rpgmaker import plugins_io  # noqa: E402
import rpgmaker_common  # noqa: E402
import rpgmaker_constants  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

# A line that is ONLY control codes (e.g. \M[お], \V[5], \C[27]) is a lookup
# reference or style switch, never display text - ExternMessage \M[ID] keys
# MUST stay Japanese (the CSV bodies they reference are translated instead).
CTRL_ONLY = re.compile(r"^(?:\\[A-Za-z]+\[[^\]]*\]|:[a-z]+(?:\[[^\]]*\])?)+[\s\u3000]*$")
# Kana detection: EXCLUDE U+30FB (・) / U+30FC (ー) / U+30A0 - punctuation that
# appears in already-translated Chinese lines (・ prefixed conditions) and
# floods the template with false keys. Canonical form shared via japanese_utils.
KANA = japanese_utils.KANA
# A script line (355/655, or a 122 script operand) qualifies as display text
# only when kana appears INSIDE a quoted string literal - comments and
# identifiers (// ダメージ計算, variable names) are never display text.
QUOTED = re.compile(r"['\"`][^'\"`]*[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e][^'\"`]*['\"`]")
NAME_LINE = re.compile(r"^(?:[\u3040-\u30ff\u4e00-\u9fff]|・)+[さんちゃん君様先生嬢ぽ]?$")
DIRECTIVE = re.compile(r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)
# Plugin-tagged notes (e.g. AlchemySystem `<recipe> {"material": ...}`) are
# functional plugin data, never display text - keep them raw. A note is also
# skipped when it is pure JSON (recipe material lists embedded as objects).
NOTE_TAG = re.compile(r"<[A-Za-z_@][^>]*>")
NOTE_JSON = re.compile(r"^\s*[{\[\"]")
WINDOW = 2

DISPLAY_KEYS = {"name", "nickname", "profile", "description",
                "message1", "message2", "message3", "message4", "text"}
EVENT_TEXT_IDX = {101: [4], 402: [0], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = rpgmaker_constants.SYSTEM_TEXT_FIELDS
SYSTEM_TEXT_ARRAYS = rpgmaker_constants.SYSTEM_TEXT_ARRAYS
TALK_CODES = (401, 405, 101, 102)


def log(msg):
    print(msg, flush=True)


def ev_containers(data):
    return rpgmaker_common.ev_containers(data)


def is_event_container(data):
    return rpgmaker_common.is_event_container(data)


def talk_lines(lst):
    """[(index, raw_text_or_None)] for all talk-ish commands in a list."""
    out = []
    for idx, cmd in enumerate(lst):
        code = cmd.get("code")
        params = cmd.get("parameters") or []
        if code in (401, 405):
            out.append((idx, params[0] if params and isinstance(params[0], str) else None))
        elif code == 101 and len(params) >= 5 and isinstance(params[4], str):
            out.append((idx, f"【{params[4]}】"))
        elif code == 102 and params and isinstance(params[0], list):
            out.append((idx, "【选项】{}".format(" / ".join(str(x) for x in params[0] if isinstance(x, str)))))
        else:
            out.append((idx, None))
    return out


def window_for(idx, tl, radius=WINDOW):
    pos = [i for i, (ci, _) in enumerate(tl) if ci == idx]
    if not pos:
        return []
    p = pos[0]
    return [t for _, t in tl[max(0, p - radius):p + radius + 1] if t is not None]


def _dict_kana_values(obj):
    """Kana-bearing string values in a plugin-command arg dict/list (nested).
    Keys are never extracted - only values (they may be display text)."""
    out = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(_dict_kana_values(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_dict_kana_values(v))
    elif isinstance(obj, str) and KANA.search(obj):
        out.append(obj)
    return out


def _code_block_line(params, col, where, idx, tl):
    """Codes 401/405: a message box line, plus a short speaker-name line."""
    if not (params and isinstance(params[0], str) and params[0]):
        return
    col.add(params[0], "block-line", where, window_for(idx, tl))
    if (len(params[0]) <= 14
            and not ctrl_codes.CTRL_TOKEN.search(params[0])
            and NAME_LINE.match(params[0].strip())):
        col.add_name(params[0].strip())


def _code_choice(params, col, where, idx, tl):
    """Code 102: the choice captions (a list of display strings)."""
    if not (params and isinstance(params[0], list)):
        return
    for x in params[0]:
        if isinstance(x, str) and x:
            col.add(x, "choice", where, window_for(idx, tl))


def _code_event_text(code, params, col, where, idx, tl):
    """Codes in EVENT_TEXT_IDX: text operands, indexed per code."""
    for pidx in EVENT_TEXT_IDX[code]:
        if pidx < len(params) and isinstance(params[pidx], str) and params[pidx]:
            if code == 101 and len(params) >= 5:
                col.add_name(params[4])
            col.add(params[pidx], "event-text", where, window_for(idx, tl))


def _code_script_operand(params, col, where, idx, tl):
    r"""Code 122: display strings held in script operands.

    ``operandType == 4`` stores a DISPLAY string in a variable (shown later via
    ``\V[n]``), so those are keys.  Only string-LITERAL operands (leading
    quote) qualify - any other script expression is functional.
    """
    if len(params) > 3 and params[3] == 4:
        if len(params) > 4 and isinstance(params[4], str) and params[4] \
                and params[4][0] in "'\"" and QUOTED.search(params[4]):
            col.add(params[4], "script-var", where, window_for(idx, tl))
        return
    for pidx in (3, 4):
        if pidx < len(params) and isinstance(params[pidx], str) and params[pidx]:
            col.add(params[pidx], "event-text", where, window_for(idx, tl))


def _code_script_line(params, col, where, idx, tl):
    """Codes 355/655: a script line whose quoted literal carries kana."""
    if params and isinstance(params[0], str) and params[0] \
            and QUOTED.search(params[0]):
        col.add(params[0], "script", where, window_for(idx, tl))


def _code_plugin_arg(params, col, where, idx, tl):
    """Code 357: kana-bearing string VALUES in a plugin command's arg dict.

    ``params[2]`` is the Japanese command NAME - a functional lookup key the
    plugin code matches - and is never extracted.
    """
    if len(params) > 3 and isinstance(params[3], dict):
        for v in _dict_kana_values(params[3]):
            col.add(v, "plugin-arg", where, window_for(idx, tl))


def _code_comment(params, col, where, idx, tl):
    """Code 408: a comment, unless it is a directive the engine parses."""
    if params and isinstance(params[0], str) and params[0] \
            and not DIRECTIVE.match(params[0]):
        col.add(params[0], "help", where, window_for(idx, tl))


def walk_commands(cmds, col, where):
    """Collect the display strings of one command list, in order.

    Dispatch is by command code; every handler shares the ``(params, col,
    where, idx, tl)`` shape and is silent when its operands do not match, so
    the chain reads as a table rather than 40 nested branches.
    """
    tl = talk_lines(cmds)
    for idx, cmd in enumerate(cmds):
        code = cmd.get("code")
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        args = (params, col, where, idx, tl)
        if code in (401, 405):
            _code_block_line(*args)
        elif code == 102:
            _code_choice(*args)
        elif code in EVENT_TEXT_IDX:
            _code_event_text(code, *args)
        elif code == 122:
            _code_script_operand(*args)
        elif code in (355, 655):
            _code_script_line(*args)
        elif code == 357:
            _code_plugin_arg(*args)
        elif code == 408:
            _code_comment(*args)


def process_db(obj, col, where=""):
    if isinstance(obj, dict):
        # battle-event command lists inside DB files (Troops.json pages):
        # display strings there (355 addText lines, 401 messages...) must be
        # extracted too, not just DB text fields.
        lst = obj.get("list")
        if isinstance(lst, list) and lst and isinstance(lst[0], dict) \
                and "code" in lst[0]:
            walk_commands(lst, col, where)
            return
        for k, v in list(obj.items()):
            if k in DISPLAY_KEYS and isinstance(v, str):
                col.add(v, "db-" + k, where, [])
            elif k == "note" and isinstance(v, str):
                if v and NOTE_TAG.search(v):
                    continue  # plugin-parsed note (recipe/config) - keep raw
                if v and NOTE_JSON.match(v) and len(v) > 80:
                    continue  # embedded JSON blob - functional, not display text
                col.add(v, "note", where, [])
            else:
                process_db(v, col, where)
    elif isinstance(obj, list):
        for v in obj:
            process_db(v, col, where)


def process_system(system, col):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            collect_values(system[f], col)


def collect_values(obj, col):
    if isinstance(obj, str):
        col.add(obj, "system", "System.json", [])
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_values(v, col)
    elif isinstance(obj, list):
        for v in obj:
            collect_values(v, col)


class Collector:
    def __init__(self):
        self.order = []                    # keys in story order
        self.kind_of = {}
        self.context = {}
        self.counts = collections.Counter()
        self.name_cands = collections.Counter()
        self._seen = set()

    def add(self, s, kind, where="", window=None):
        if not s or not KANA.search(s):
            return
        if CTRL_ONLY.match(s):
            return  # pure control-code line (\M[ID] lookup / style switch)
        if kind != "block-line" and ctrl_codes.CTRL_TOKEN.search(s) and len(s) < 6:
            return
        if s not in self._seen:
            self._seen.add(s)
            self.order.append(s)
            self.kind_of[s] = kind
            self.context[s] = {"where": where, "window": window or []}
        self.counts[kind] += 1

    def add_name(self, s):
        if (s and len(s) <= 14 and not ctrl_codes.CTRL_TOKEN.search(s)
                and NAME_LINE.match(s)):
            self.name_cands[s] += 1


def extract_plugin_text(game_dir, col):
    """JA-bearing strings in js/plugins.js plugin parameters (kind 'plugin')."""
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.exists(path):
        return 0
    try:
        plugins = plugins_io.parse_plugins_js(
            open(path, encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        # Intentional catch-all: parse_plugins_js() is a heuristic JS parser;
        # on any failure (ValueError/IndexError/TypeError/KeyError from
        # malformed plugin params) we skip plugin text rather than abort.
        log(f"WARN: plugins.js parse failed ({e}) - plugin text skipped")
        return 0
    n = 0
    for where, val in plugins_io.iter_plugin_strings(plugins, KANA):
        col.add(val, "plugin", where, [])
        n += 1
    return n


def build_name_macros(data_dir):
    """\\N[x] / \\P[x] -> actor name (macro table, never translated itself)."""
    macros = {}
    actors_path = os.path.join(data_dir, "Actors.json")
    if not os.path.exists(actors_path):
        return macros
    for a in plain_io.load_json(actors_path):
        if not a or not a.get("name"):
            continue
        for code in ("N", "P"):
            macros["\\%s[%d]" % (code, a.get("id", 0))] = a["name"]
    return macros


def _collect_mapinfos_order(data_dir):
    """`[(id, name)]` from MapInfos.json in story order (empty when absent)."""
    mi_path = os.path.join(data_dir, "MapInfos.json")
    if not os.path.exists(mi_path):
        return []
    return [(x["id"], x.get("name", "")) for x in plain_io.load_json(mi_path) if x]


def _map_events(data):
    """`[(ev, [command_list, ...])]` for one map's events, in id order.

    One entry per event (not per command list) so the caller can add the event
    name exactly once before walking its pages, as the pre-split code did.
    """
    out = []
    for ev in sorted(ev_containers(data), key=lambda e: e.get("id", 0)):
        lists = [ev["list"]] if isinstance(ev.get("list"), list) else []
        lists.extend(pg["list"] for pg in ev.get("pages") or []
                     if isinstance(pg, dict) and isinstance(pg.get("list"), list))
        out.append((ev, lists))
    return out


def _collect_maps_in_order(data_dir, map_order, col):
    """Walk every map in MapInfos order (the story order)."""
    for mid, mname in map_order:
        path = os.path.join(data_dir, "Map%03d.json" % mid)
        if not os.path.exists(path):
            path = os.path.join(data_dir, "Map%d.json" % mid)
        if not os.path.exists(path):
            continue
        data = plain_io.load_json(path)
        if not isinstance(data, dict):
            continue
        disp = data.get("displayName") or ""
        if disp:
            col.add(disp, "displayName", mname, [])
        for ev, lists in _map_events(data):
            where = "%s / EV%03d %s" % (mname or path, ev.get("id", 0),
                                        ev.get("name") or "")
            if ev.get("name"):
                col.add(ev["name"], "event-name", mname, [])
            for lst in lists:
                walk_commands(lst, col, where)


def _collect_maps_not_in_mapinfos(data_dir, map_order, col):
    """Walk map files MapInfos does not list (defensive)."""
    known = {mid for mid, _ in map_order}
    for fname in sorted(os.listdir(data_dir)):
        m = re.match(r"Map(\d+)\.json", fname)
        if not m or int(m.group(1)) in known:
            continue
        data = plain_io.load_json(os.path.join(data_dir, fname))
        if not isinstance(data, dict):
            continue
        for ev, lists in _map_events(data):
            where = "{} / {}".format(fname, ev.get("name") or "")
            if ev.get("name"):
                col.add(ev["name"], "event-name", fname, [])
            for lst in lists:
                walk_commands(lst, col, where)


def _collect_common_events(data_dir, col):
    """Walk CommonEvents.json (shared story text)."""
    ce_path = os.path.join(data_dir, "CommonEvents.json")
    if not os.path.exists(ce_path):
        return
    data = plain_io.load_json(ce_path)
    for ev in sorted(ev_containers(data), key=lambda e: e.get("id", 0)):
        where = "CommonEvents / EV%03d %s" % (ev.get("id", 0),
                                             ev.get("name") or "")
        if ev.get("name"):
            col.add(ev["name"], "event-name", "CommonEvents", [])
        if isinstance(ev.get("list"), list):
            walk_commands(ev["list"], col, where)


def _collect_system_and_db(data_dir, col):
    """Walk System.json and every remaining database JSON (UI text)."""
    sys_path = os.path.join(data_dir, "System.json")
    if os.path.exists(sys_path):
        process_system(plain_io.load_json(sys_path), col)
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".json") or fname == "System.json" \
                or re.match(r"Map\d+\.json", fname) or fname == "MapInfos.json" \
                or fname == "CommonEvents.json":
            continue
        process_db(plain_io.load_json(os.path.join(data_dir, fname)), col, fname)


def _collect_names(data_dir, col):
    """Speaker-name candidates: every actor name plus the message boxes."""
    names = {}
    actors_path = os.path.join(data_dir, "Actors.json")
    if os.path.exists(actors_path):
        for a in plain_io.load_json(actors_path) or []:
            if a and a.get("name"):
                names[a["name"]] = [""]
    for cand, _count in col.name_cands.most_common(80):
        names.setdefault(cand, [""])
    return names


def _write_package(out_dir, col, names, name_macros):
    """Write the translation package (template/kinds/context/names)."""
    payloads = {
        "template.json": dict.fromkeys(col.order, ""),
        "kinds.json": {k: col.kind_of[k] for k in col.order},
        "context.json": {k: col.context[k] for k in col.order},
        "names.json": names,
        "name_macros.json": name_macros,
    }
    for fname, payload in payloads.items():
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)


def cmd(game_dir: Annotated[str, cliutil.Argument(help="source game folder")],
        out_dir: Annotated[str, cliutil.Argument(
            help="work folder to write the translation package into")],
        no_plugins: Annotated[bool, cliutil.Option(
            "--no-plugins",
            help="skip js/plugins.js parameter text extraction")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Extract the remaining (untranslated) kana strings in story order."""
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("extract remaining text", game_dir=game_dir, out_dir=out_dir)

    game_dir = os.path.abspath(game_dir)
    out_dir = os.path.abspath(out_dir)
    data_dir = os.path.join(game_dir, "data")
    os.makedirs(out_dir, exist_ok=True)

    col = Collector()
    map_order = _collect_mapinfos_order(data_dir)

    # 1) maps in story order, 2) leftovers, 3) CommonEvents, 4) System + DB
    _collect_maps_in_order(data_dir, map_order, col)
    _collect_maps_not_in_mapinfos(data_dir, map_order, col)
    _collect_common_events(data_dir, col)
    _collect_system_and_db(data_dir, col)

    if not no_plugins:
        n = extract_plugin_text(game_dir, col)
        if n:
            log("plugin parameter text: %d strings" % n)

    _write_package(out_dir, col, _collect_names(data_dir, col),
                   build_name_macros(data_dir))

    log("template keys: %d" % len(col.order))
    log(f"by kind: {dict(col.counts.most_common())}")
    log(f"order sample: {col.order[:8]}")
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="extract_remaining_text.py")


if __name__ == "__main__":
    raise SystemExit(main())
