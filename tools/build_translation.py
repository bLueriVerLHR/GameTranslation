#!/usr/bin/env python3
r"""
build_translation.py - Build a static-translation work package from an RPG
Maker MZ game (replaces the old extract_text.py for the new workflow).

Produces five files in <out_dir>:
  template.json    merged {key: ""} of every translatable static string
  names.json       candidate character names -> proposed translations ("" = TBD)
  structure.json   scene tree: maps (story order) -> events -> ordered text
                   items (message blocks, choice labels, names, help texts)
  context.json     key -> {"where": location, "window": neighbouring dialogue
                   lines} - CONTEXT ONLY, nothing here is translated.  Shard
                   generators inject this into each chunk's context.md.
  name_macros.json {"\\N[1]": "<zh-name>"} - CONTROL-CODE NAME MACROS: like C++ /
                   LaTeX macros, the code is a substitution reference, NOT
                   translatable text.  \N[x] / \P[x] resolve to the actor's
                   name in Actors.json, which IS translated normally (DB).
                   Shard generators print this table in context.md so agents
                   understand a macro as "this is character X's name" and
                   leave the code itself untouched.

Why blocks: dialogue is stored one 401 command per line, but a message is a
run of consecutive 401 commands.  Keys for such runs are the lines joined
with "\n", so the translator sees and translates whole messages with context.
Baking (bake_translation.py) joins the same runs and looks the key up
exactly - no greedy fragment replacement, so no cross-branch pollution.

Plugin menu text: every JA-bearing string in js/plugins.js plugin parameters
is extracted too (kind "plugin") so plugin UI/menus can be localized; the
baker writes them back (see bake_translation.py).  Disable with --no-plugins.

Usage:
    python build_translation.py <game_dir> <out_dir> [--no-plugins]
"""

import collections
import json
import os
import re
import sys
from typing import Annotated


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctrl_codes  # noqa: E402
import plain_io  # noqa: E402
from rpgmaker import plugins_io  # noqa: E402
import rpgmaker_common  # noqa: E402
import rpgmaker_constants  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

SPLIT = re.compile(r"\n")
JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
NAME_LINE = re.compile(r"^(?:[\u3040-\u30ff\u4e00-\u9fff]|・)+[さんちゃん君様先生嬢ぽ]?$")
DIRECTIVE = re.compile(r"^\s*(?:<|>|//|#|\[|`)|<[A-Za-z_@][^>]*>", re.S)
WINDOW = 2

# Parsed plugin list cache (review §4.2: "single read, cached per file").
# js/plugins.js is read and parsed exactly once per build even when
# extract_plugin_text() is invoked repeatedly (each build loops over every
# data/*.json first, then collects plugin text once).  The key includes
# mtime + size so a modified file invalidates the entry and re-parses.
_plugin_cache = {}

DISPLAY_KEYS = {"name", "nickname", "profile", "description",
                "message1", "message2", "message3", "message4", "text"}
EVENT_TEXT_IDX = {101: [4], 402: [0], 320: [1], 324: [1], 325: [1]}
SYSTEM_TEXT_FIELDS = rpgmaker_constants.SYSTEM_TEXT_FIELDS
SYSTEM_TEXT_ARRAYS = rpgmaker_constants.SYSTEM_TEXT_ARRAYS


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Walkers
# ---------------------------------------------------------------------------
def ev_containers(data):
    return rpgmaker_common.ev_containers(data)


def command_lists(data):
    for ev in ev_containers(data):
        if isinstance(ev.get("list"), list):
            yield ev["list"]
        for pg in ev.get("pages") or []:
            if isinstance(pg, dict) and isinstance(pg.get("list"), list):
                yield pg["list"]


def is_event_container(data):
    return rpgmaker_common.is_event_container(data)


def talk_lines(lst):
    """[(index, raw_text_or_None)] for all talk-ish commands in a list."""
    out = []
    for idx, cmd in enumerate(lst):
        code = cmd.get("code")
        params = cmd.get("parameters") or []
        if code in (401, 405):
            out.append((idx, params[0] if params and isinstance(params[0], str)
                        else None))
        elif code == 101 and len(params) >= 5 and isinstance(params[4], str):
            out.append((idx, f"【{params[4]}】"))
        elif code == 102 and params and isinstance(params[0], list):
            out.append((idx, "【选项】{}".format(" / ".join(
                str(x) for x in params[0] if isinstance(x, str)))))
        else:
            out.append((idx, None))
    return out


def pos_map(tl):
    """command index -> position in the talk list.  Building this once per
    command list turns window_for() from a per-call O(m) linear scan into an
    O(1) lookup, so the whole build is O(n) instead of O(n x m) (review
    §4.2: group windows per (map, event) command list, then look up).
    setdefault keeps the FIRST occurrence like the legacy window_for()."""
    pos = {}
    for i, (ci, _) in enumerate(tl):
        pos.setdefault(ci, i)
    return pos


def window_for(idx, tl, radius=WINDOW, pos=None):
    if pos is None:
        pos = pos_map(tl)
    p = pos.get(idx)
    if p is None:
        return []
    return [t for _, t in tl[max(0, p - radius):p + radius + 1] if t is not None]


# ---------------------------------------------------------------------------
# Key collectors
# ---------------------------------------------------------------------------
# Location suffix separator: a key that appears in more than one place keeps
# its first occurrence as the plain key (backward-compatible fallback) and
# gets a "\x1f<loc>" variant key per further occurrence.  loc is a stable
# traversal path rebuildable by bake_translation.py (file#container#cmd or
# file#key-path), so each occurrence can carry its own context-aware
# translation.  \x1f (UNIT SEPARATOR) cannot appear in game text.
LOC_SEP = "\x1f"


def loc_key(base, loc):
    return base + LOC_SEP + loc


class Collector:
    def __init__(self):
        self.keys = set()            # all keys (plain + located)
        self.kind_of = {}            # key -> kind
        self.context = {}            # key -> {"where": ..., "window": [...]}
        self.count = collections.Counter()
        self.name_cands = collections.Counter()
        self._seen = {}              # base text -> occurrence count

    def add(self, key, kind, where="", window=None, loc=""):
        if not key:
            return
        n = self._seen.get(key, 0) + 1
        self._seen[key] = n
        # Names / person references (short, no control codes, NAME_LINE-ish)
        # are glossary-mapped, not context-sensitive text: keep a single
        # plain key regardless of how many places reference them.
        if n > 1 and loc and not (
                len(key) <= 14 and not ctrl_codes.CTRL_TOKEN.search(key)
                and NAME_LINE.match(key.strip())):
            fk = loc_key(key, loc)
        else:
            fk = key
        self.keys.add(fk)
        self.kind_of.setdefault(fk, kind)
        self.context.setdefault(fk, {"where": where, "window": window or []})
        self.count[fk] += 1

    def add_name(self, s):
        if (s and len(s) <= 14 and not ctrl_codes.CTRL_TOKEN.search(s)
                and NAME_LINE.match(s)):
            self.name_cands[s] += 1


def build_name_macros(data_dir):
    """\\N[x] / \\P[x] -> actor name, from Actors.json.  These are macros
    (like C++/LaTeX): the code itself is never translated, the referenced
    actor name is translated in the DB.  The table helps agents understand
    what a code means when they see it in a key."""
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


def iter_message_blocks(cmds, collector, kind="block", where="", loc="",
                        tl=None, pos=None):
    """Yield (block_key, [line, ...]) for runs of consecutive 401/405 cmds.
    `tl`/`pos` are the shared talk list + position map (computed once per
    command list by the caller); both callers reuse them so talk_lines() is
    not recomputed and window_for() stays O(1) (review §4.2)."""
    if tl is None:
        tl = talk_lines(cmds)
    if pos is None:
        pos = pos_map(tl)
    i, n = 0, len(cmds)
    while i < n:
        code = cmds[i].get("code")
        if code not in (401, 405):
            i += 1
            continue
        j = i
        lines = []
        while j < n and cmds[j].get("code") == code:
            params = cmds[j].get("parameters") or []
            lines.append(params[0] if params and isinstance(params[0], str)
                         else "")
            j += 1
        key = "\n".join(lines)
        collector.add(key, kind, where, window_for(i, tl, pos=pos),
                      loc + "#c%d" % i)
        yield key, lines
        if len(lines) == 1 and key and not ctrl_codes.CTRL_TOKEN.search(key) \
                and NAME_LINE.match(key.strip()) and len(key.strip()) <= 14:
            collector.name_cands[key.strip()] += 1
        # line keys are redundant for in-block lines: a standalone line is
        # already its own 1-line block key.
        i = j


def _collect_choice(params, collector, where, idx, tl, pos, cloc):
    """Code 102: every choice caption carrying kana."""
    if not (params and isinstance(params[0], list)):
        return
    for x in params[0]:
        if isinstance(x, str) and JA.search(x):
            collector.add(x, "choice", where, window_for(idx, tl, pos=pos), cloc)


def _collect_event_text(code, params, collector, where, idx, tl, pos, cloc):
    """Codes in EVENT_TEXT_IDX: the display-text operands."""
    for i2 in EVENT_TEXT_IDX[code]:
        if i2 < len(params) and isinstance(params[i2], str) and params[i2]:
            if code == 101 and len(params) >= 5:
                collector.add_name(params[4])
            collector.add(params[i2], "event-text", where,
                          window_for(idx, tl, pos=pos), cloc)


def _collect_script_operand(params, collector, where, idx, tl, pos, cloc):
    """Code 122: script operands, skipping JS code (operandType == 4)."""
    if len(params) > 3 and params[3] == 4:
        return
    for i2 in (3, 4):
        if i2 < len(params) and isinstance(params[i2], str) and params[i2]:
            collector.add(params[i2], "event-text", where,
                          window_for(idx, tl, pos=pos), cloc)


def _collect_comment(params, collector, where, idx, tl, pos, cloc):
    """Code 408: a comment line shown by choice-help plugins."""
    if params and isinstance(params[0], str) and params[0] \
            and not DIRECTIVE.match(params[0]):
        collector.add(params[0], "help", where,
                      window_for(idx, tl, pos=pos), cloc)


def process_commands(cmds, collector, where="", loc="", tl=None, pos=None):
    """`tl`/`pos` are the shared talk list + position map computed once per
    command list by the caller (see iter_message_blocks); window_for() uses
    them so the per-key window lookup is O(1), not a linear re-scan."""
    if tl is None:
        tl = talk_lines(cmds)
    if pos is None:
        pos = pos_map(tl)
    for idx, cmd in enumerate(cmds):
        code = cmd.get("code")
        params = cmd.get("parameters")
        if not isinstance(params, list):
            continue
        cloc = loc + "#c%d" % idx
        if code == 102:
            _collect_choice(params, collector, where, idx, tl, pos, cloc)
        elif code in EVENT_TEXT_IDX:
            _collect_event_text(code, params, collector, where, idx, tl, pos, cloc)
        elif code == 122:
            _collect_script_operand(params, collector, where, idx, tl, pos, cloc)
        elif code == 408:
            _collect_comment(params, collector, where, idx, tl, pos, cloc)


def process_db(obj, collector, where="", loc=""):
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            kloc = loc + f"#{k}"
            if k in DISPLAY_KEYS and isinstance(v, str) and JA.search(v):
                collector.add(v, "db-" + k, where, [], kloc)
            elif k == "note" and isinstance(v, str) and JA.search(v):
                collector.add(v, "note", where, [], kloc)
            else:
                process_db(v, collector, where, kloc)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            process_db(v, collector, where, loc + "[%d]" % i)


def process_system(system, collector):
    for f in SYSTEM_TEXT_FIELDS + SYSTEM_TEXT_ARRAYS:
        if f in system:
            collect_values(system[f], collector, "System.json",
                           f"System.json#{f}")


def collect_values(obj, collector, where="", loc=""):
    if isinstance(obj, str):
        if JA.search(obj):
            collector.add(obj, "system", where, [], loc)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            collect_values(v, collector, where, loc + f"#{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            collect_values(v, collector, where, loc + "[%d]" % i)


def extract_plugin_text(game_dir, collector):
    """JA-bearing strings in js/plugins.js plugin parameters (kind 'plugin').
    The file is read and parsed at most once per build via _plugin_cache
    (keyed by mtime+size); repeated calls reuse the parsed plugin list."""
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.exists(path):
        return 0
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        key = (path,)
    plugins = _plugin_cache.get(key)
    if plugins is None:
        try:
            plugins = plugins_io.parse_plugins_js(
                open(path, encoding="utf-8-sig").read())
        except Exception as e:  # noqa: BLE001 - keep the build going
            # Intentional catch-all: parse_plugins_js() is a heuristic JS
            # parser; on any failure (ValueError/IndexError/TypeError/KeyError
            # from malformed plugin params) we skip plugin text rather than
            # abort.  A failed parse is NOT cached, so a later fix re-parses.
            log(f"WARN: plugins.js parse failed ({e}) - plugin text skipped")
            return 0
        _plugin_cache[key] = plugins
    n = 0
    for where, val in plugins_io.iter_plugin_strings(plugins, JA):
        collector.add(val, "plugin", where, [])
        n += 1
    return n


# ---------------------------------------------------------------------------
# Scene tree
# ---------------------------------------------------------------------------
def build_tree(data, map_id, map_name, display_name, collector, fname=""):
    """Return the ordered text items of a map/event file for structure.json."""
    items = []
    for evi, ev in enumerate(ev_containers(data)):
        ev_items = {"id": ev.get("id"), "name": ev.get("name"),
                    "items": []}
        where = "%s / EV%03d %s" % (map_name or "?", ev.get("id", 0),
                                    ev.get("name") or "")
        eloc = "%s#ev%d" % (fname, evi)
        if ev.get("name"):
            collector.add(ev["name"], "event-name", where, [], eloc + "#name")
        lists = [ev["list"]] if isinstance(ev.get("list"), list) else []
        lists.extend(pg["list"] for pg in ev.get("pages") or []
                     if isinstance(pg, dict) and isinstance(pg.get("list"), list))
        for li, lst in enumerate(lists):
            ploc = eloc + "#pg%d" % li
            # One shared talk list + position map per command list: both
            # walkers reuse it, so the per-key window lookup is O(1) (the
            # old code recomputed talk_lines() and linearly re-scanned it
            # for every command -> O(n x m) per list, review §4.2).
            tl = talk_lines(lst)
            pos = pos_map(tl)
            process_commands(lst, collector, where, ploc, tl=tl, pos=pos)
            for block_key, _lines in iter_message_blocks(lst, collector,
                                                        where=where,
                                                        loc=ploc, tl=tl,
                                                        pos=pos):
                ev_items["items"].append({"kind": "block", "key": block_key})
            for c in lst:
                params = c.get("parameters") or []
                if c.get("code") == 102 and params and isinstance(params[0], list):
                    for x in params[0]:
                        if isinstance(x, str) and x in collector.keys:
                            ev_items["items"].append({"kind": "choice", "key": x})
        items.append(ev_items)
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _load_map_names(data_dir):
    """`{id: name}` from MapInfos.json, for labelling a map's tree node.

    (The pre-split code also built a `map_order` list here; it was never read,
    so only the lookup survives.)
    """
    mapinfos_path = os.path.join(data_dir, "MapInfos.json")
    map_names = {}
    if os.path.exists(mapinfos_path):
        for x in plain_io.load_json(mapinfos_path):
            if x:
                map_names[x["id"]] = x.get("name", "")
    return map_names


def _collect_data_files(data_dir, map_names, col):
    """Walk data/*.json once: per-file collection + the structure tree."""
    tree = []
    for path in sorted(os.listdir(data_dir)):
        if not path.endswith(".json"):
            continue
        fname = os.path.basename(path)
        with open(os.path.join(data_dir, path), encoding="utf-8-sig") as f:
            data = json.load(f)
        if is_event_container(data):
            map_id = None
            m = re.match(r"Map(\d+)\.json", fname)
            if m:
                map_id = int(m.group(1))
            disp = data.get("displayName") or "" if isinstance(data, dict) else ""
            if disp:
                col.add(disp, "displayName", fname, [], fname + "#displayName")
            if map_id is not None:
                tree.append({"id": map_id, "events": []})
                tree[-1]["items"] = build_tree(data, map_id,
                                               map_names.get(map_id, fname),
                                               disp, col, fname)
            elif fname == "CommonEvents.json":
                tree.append({"id": -1, "events": []})
                tree[-1]["items"] = build_tree(data, None, "CommonEvents",
                                               disp, col, fname)
            else:
                build_tree(data, None, fname, disp, col, fname)
        elif fname == "System.json":
            process_system(data, col)
        else:
            process_db(data, col, fname, fname)
    return tree


def _collect_actor_names(data_dir, col):
    """Speaker-name candidates: actor names plus frequent standalone lines."""
    names = {}
    actors_path = os.path.join(data_dir, "Actors.json")
    if os.path.exists(actors_path):
        for a in plain_io.load_json(actors_path):
            if a and a.get("name"):
                names[a["name"]] = [""]
    for cand, _count in col.name_cands.most_common(120):
        names.setdefault(cand, [""])
    return names


def _write_translation_package(out_dir, template, col, tree, names,
                               name_macros):
    """Write template/names/kinds/structure/context/name_macros."""
    payloads = {
        "template.json": template,
        "names.json": names,
        "kinds.json": col.kind_of,
        "structure.json": {"maps": tree},
        "context.json": col.context,
        "name_macros.json": name_macros,
    }
    for fname, payload in payloads.items():
        with open(os.path.join(out_dir, fname), "w",
                  encoding="utf-8-sig") as f:
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
    """Extract the MZ template/context/structure/kinds/names/name macros."""
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("build translation package", game_dir=game_dir, out_dir=out_dir)

    game_dir = os.path.abspath(game_dir)
    out_dir = os.path.abspath(out_dir)
    data_dir = os.path.join(game_dir, "data")
    if not os.path.isdir(data_dir):
        return cliutil.fail(f"no data/ dir under {game_dir}")
    os.makedirs(out_dir, exist_ok=True)

    col = Collector()

    _map_names = _load_map_names(data_dir)
    tree = _collect_data_files(data_dir, _map_names, col)

    if not no_plugins:
        n = extract_plugin_text(game_dir, col)
        if n:
            log("plugin parameter text: %d strings" % n)

    # drop pure-ASCII keys (EV001-style ids, "OK", ...) - nothing to translate
    ja_keys = {k for k in col.keys if JA.search(k)}
    template = dict.fromkeys(sorted(ja_keys, key=lambda k: (-col.count[k], k)), "")
    col.kind_of = {k: v for k, v in col.kind_of.items() if k in ja_keys}
    col.context = {k: col.context[k] for k in ja_keys}

    names = _collect_actor_names(data_dir, col)
    name_macros = build_name_macros(data_dir)

    _write_translation_package(out_dir, template, col, tree, names,
                               name_macros)

    log("template: %d keys; names: %d candidates; maps: %d; name macros: %d"
        % (len(template), len(names), len(tree), len(name_macros)))
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="build_translation.py")


if __name__ == "__main__":
    raise SystemExit(main())
