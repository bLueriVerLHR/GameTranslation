#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mvkeys.py - story-ordered key extraction for RPG Maker MV / MZ data trees.

v2 workflow step 1 (design: `.tmp/TRANSLATION_WORKFLOW_V2.md`): turn a game's
data tree into ONE flat, stable, story-ordered key list, so the translation
subagent reads `keys.jsonl` instead of reading the game.

Order (the same convention the pipeline docs use): MapInfos order -> map ->
event -> page -> command position, then CommonEvents, then Troops, then the
database files, then System/UI, then plugin parameters.  That order is what
makes a translation stay coherent across a scene: the keys of one scene are
adjacent, in the order the player sees them.

Identity: a key's id is its JSON path inside the game's data tree, e.g.
``data/Map003.json#events[2].pages[0].list[7].parameters[0]``.  It is derived,
never invented, and it must stay stable across re-extraction - a translation
library is keyed by it, so an unstable id would silently lose work.

Outputs, all inside the work dir:

``keys.jsonl``            one JSON object per key (see ``FIELDS`` below)
``control_codes.md``      derived code table (see ``codes``)
``names_candidates.json`` name candidates with occurrence counts
``stats.json``            counts by kind / code, and what was skipped

Never mixed in: `note` fields (plugin commands, functional), script lines
(355/655), comment lines (108/408), editor-only names (MapInfos/event/
CommonEvent names), file paths in plugin parameters, the 657 plugin-command
continuation (an editor echo the engine never executes) and the 357's
``parameters[2]`` (@text - the engine hands the plugin ``parameters[3]`` only).
Those are reported in ``stats.json`` under ``skipped``.
"""
import io
import json
import os
import re
from collections import Counter, OrderedDict, defaultdict

from . import codes as codes_mod
from .codes import CJK_RE, KANA_RE, code_key, parse_codes

__all__ = ["extract", "load_keys", "text_codes", "extra_text_codes",
           "is_command", "command_code", "speaker_of", "is_candidate"]

#: Command codes whose first parameter is displayed text.
TEXT_CODES = (401, 405)
#: Show Choices: parameters[0] is the list of choice texts.
CHOICE_CODE = 102
#: Show Text: parameters[4] is the **name plate** drawn above the window.  It is
#: the game's speaker name and was invisible to an extractor that only looked at
#: parameters[0] - a real build showed 1,800+ untranslated name plates.
NAME_CODE = 101
NAME_PARAM = 4
#: Show Choices branch: parameters[1] repeats the chosen label, so it has to
#: follow the choice text (a plugin may print it).
BRANCH_CODE = 402
BRANCH_PARAM = 1
#: Plugin command.  Its parameters are ``[plugin name, command name, @text,
#: args]``: the first two are identifiers and the display text lives in the
#: arg object at index 3.
PLUGIN_CMD_CODE = 357
#: Index of the command's ``@text`` inside a 357 - the label the *editor* shows
#: (「選択肢の表示」).  ``Game_Interpreter.prototype.command357`` calls
#: ``PluginManager.callCommand(this, pluginName, params[1], params[3])``, so
#: index 2 reaches neither the plugin nor the player.
PLUGIN_LABEL_PARAM = 2
#: Editor-only continuation of a plugin command.  The editor writes one 657 per
#: argument holding a wrapped ``"argName = value"`` echo of the 357's args, and
#: **no** engine version implements ``command657`` - an unhandled code is
#: skipped by ``executeCommand`` - so its text is never read or displayed.
#: Extracting it costs one key per plugin argument (23,864 in one MZ build,
#: 47% of the whole key list) and risks rewriting editor bookkeeping.
PLUGIN_CONT_CODE = 657
PLUGIN_IDENTIFIER_PARAMS = 2

def _params_of(command):
    """The parameter list of either command shape (None when not a command)."""
    if isinstance(command, dict):
        return command.get("parameters") or []
    if isinstance(command, (list, tuple)) and len(command) >= 3:
        return list(command[2:])
    return None


def _nested_texts(value, trail=""):
    """Strings inside a plugin parameter object/list, with their trail.

    Plugin command parameters are structured: an option object like
    ``{"windowId": 1, "messageText": "叫び声が響く……」}`` carries displayed text
    in a *field*, which an extractor that only looks at top-level strings never
    sees (a real build lost its popup messages and a keyboard hint that way).
    """
    out = []
    if isinstance(value, str):
        out.append((trail, value))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_nested_texts(item, "%s[%d]" % (trail, index)))
    elif isinstance(value, dict):
        for key, item in value.items():
            out.extend(_nested_texts(item, "%s.%s" % (trail, key)))
    return out


def extra_text_codes(command):
    """Displayed strings the base ``text_codes`` does not cover.

    Returns ``[(param_index, suffix, text)]`` for name plates (101), choice
    branch labels (402) and plugin-command prose (357/657).  Plugin parameters
    are a mix of identifiers and prose, so a string counts only when
    ``is_candidate`` accepts it - plugin/command names, the JSON parameter
    object, paths and script fragments are dropped.
    """
    code = command_code(command)
    params = _params_of(command)
    if not params:
        return []
    out = []
    if code == NAME_CODE:
        if len(params) > NAME_PARAM and isinstance(params[NAME_PARAM], str) \
                and is_candidate(params[NAME_PARAM]):
            out.append((NAME_PARAM, "", params[NAME_PARAM]))
    elif code == BRANCH_CODE:
        if len(params) > BRANCH_PARAM and isinstance(params[BRANCH_PARAM], str) \
                and is_candidate(params[BRANCH_PARAM]):
            out.append((BRANCH_PARAM, "", params[BRANCH_PARAM]))
    elif code == PLUGIN_CMD_CODE:
        for index, value in enumerate(params[PLUGIN_IDENTIFIER_PARAMS:],
                                        PLUGIN_IDENTIFIER_PARAMS):
            if isinstance(value, str):
                # index 2 is the command's @text (editor label, dropped by the
                # engine).  A *dict* at that index means the build has no @text
                # slot, so it is scanned like any other parameter object.
                if index == PLUGIN_LABEL_PARAM:
                    continue
                if is_candidate(value, "plugin"):
                    out.append((index, "", value))
                continue
            for suffix, text in _nested_texts(value):
                if is_candidate(text, "plugin"):
                    out.append((index, suffix, text))
    # PLUGIN_CONT_CODE (657) is intentionally absent: see the constant's note.
    return out


#: Database files and the fields that hold displayed text.  `note` is
#: deliberately absent: it carries plugin commands, not prose.
DB_FIELDS = OrderedDict([
    ("Actors.json", ("name", "nickname", "profile")),
    ("Classes.json", ("name",)),
    ("Skills.json", ("name", "description", "message1", "message2")),
    ("Items.json", ("name", "description", "message1", "message2")),
    ("Weapons.json", ("name", "description", "message1", "message2")),
    ("Armors.json", ("name", "description", "message1", "message2")),
    ("Enemies.json", ("name",)),
    ("States.json", ("name", "message1", "message2", "message3", "message4")),
])

#: System.json fields holding displayed text.  `switches`/`variables` are here
#: because variable/switch *names* are drawn by variable-window plugins (a real
#: build shows `${$dataSystem.variables[id]}` in a UI window).  References to
#: switches/variables are by **id**, and no plugin in the surveyed builds looks
#: one up by name, so translating the names is safe.
_SYSTEM_KEYS = ("gameTitle", "currencyUnit", "armorTypes", "elements",
                "skillTypes", "weaponTypes", "equipTypes",
                "switches", "variables")

_PATH_RE = re.compile(
    r"\.(?:png|jpg|jpeg|bmp|webp|ogg|m4a|mp3|wav|webm|mp4|json|js|txt|ttf|otf"
    r"|rpgmvp|rpgmvo|rpgmvm|zip)\b", re.I)
_SCRIPTISH_RE = re.compile(
    r"=>|function\s*\(|\$data|\bthis\.|\breturn\b|;\s*$|\{\s*$", re.M)

#: Version of the JSONL contract; bumped when a field's meaning changes.
SCHEMA = 2


def is_command(command):
    """Could this page-list entry be a command?  (array or object shape)"""
    if isinstance(command, dict):
        return "code" in command
    return isinstance(command, (list, tuple)) and len(command) >= 3


def command_code(command):
    """The numeric command code of either shape (None when unreadable)."""
    if isinstance(command, dict):
        return command.get("code")
    if isinstance(command, (list, tuple)) and command:
        return command[0]
    return None


def text_codes(command):
    """The displayed strings of one MV/MZ command, as ``[(suffix, text)]``.

    A command has two equivalent shapes and real builds ship both: the
    editor's array (``[401, 0, "text"]``) and the named-object form
    (``{"code": 401, "indent": 0, "parameters": ["text"]}``) that a tool
    rewriting the data tends to save - the engine reads named properties, so
    both run.  Anything that is not a command at all (plugins do write their
    own entries into a page list) is ignored here and counted by the caller.
    """
    if isinstance(command, dict):
        code = command.get("code")
        params = command.get("parameters") or []
    elif isinstance(command, (list, tuple)) and len(command) >= 3:
        code, params = command[0], command[2:]
    else:
        return []
    out = []
    if code in TEXT_CODES and params and isinstance(params[0], str):
        out.append(("", params[0]))
    elif code == CHOICE_CODE and params and isinstance(params[0], list):
        for index, choice in enumerate(params[0]):
            if isinstance(choice, str):
                out.append(("[%d]" % index, choice))
    return out


def is_candidate(text, kind="map"):
    """Is this string something to translate?

    Kana always means text, and kanji-only strings count too: a location
    banner (``\\px[200]場所：診察室``), a menu label, a database name or a
    battle message is often kanji-only, and dropping those would leave parts
    of the game untranslated while looking like success (a real sample of 25
    maps held ~1300 such lines).  ASCII-only strings, file paths and - where
    script values are plausible - script fragments are excluded.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    if not (KANA_RE.search(text) or CJK_RE.search(text)):
        return False
    if _PATH_RE.search(text):
        return False
    if kind in ("db", "ui", "plugin") and _SCRIPTISH_RE.search(text):
        return False
    return True


def namebox_of(text):
    """The name a ``\\nc<...>`` name box in this text refers to, else None."""
    if not text:
        return None
    for token in parse_codes(text):
        if code_key(token) == "NC" and "<" in token:
            return token[token.index("<") + 1:-1].strip() or None
    return None


def prefix_speaker(text):
    """A speaker written into the text itself: ``【名前】`` or ``名前「``."""
    if not text:
        return None
    match = re.match(r"^【([^】]{1,16})】", text)
    if match:
        return match.group(1).strip() or None
    match = re.match(r"^([^\s「」『』、。！？!?]{1,12})[「『]", text)
    return match.group(1) if match else None


def speaker_of(text):
    """Speaker referenced by a line: name box, bracket prefix or ``X「``.

    The name box is only a *hint* here: real data often puts it at the end of a
    speaker's paragraph or on a line of its own, so which lines it labels can
    only be decided per message window (see ``_Collector.result``).
    """
    if not text:
        return None
    return namebox_of(text) or prefix_speaker(text)


class _Collector:
    """Accumulates keys in story order and remembers usage for the report."""

    def __init__(self, window=2):
        self.window = window
        self.entries = []
        self.code_counts = Counter()
        self.skipped = Counter()
        self.names = defaultdict(lambda: {"count": 0, "sources": []})
        self.actors = {}
        self._streams = defaultdict(list)

    def add(self, key_id, kind, where, text, stream, name_hint=None, window=0):
        if not is_candidate(text, kind):
            self.skipped[kind] += 1
            return
        entry = {
            "id": key_id,
            "kind": kind,
            "where": where,
            "ja": text,
            "speaker": speaker_of(text),
        }
        entry["_window"] = (stream, window)
        self.entries.append(entry)
        self._streams[stream].append(entry)
        for token in parse_codes(text):
            self.code_counts[token] += 1
        hint = entry["speaker"] or name_hint
        if hint:
            self._note_name(hint, "speaker")
        for token in parse_codes(text):
            if code_key(token) == "NC" and "<" in token:
                self._note_name(token[token.index("<") + 1:-1].strip(), "namebox")

    def _note_name(self, name, source):
        if not name:
            return
        record = self.names[name]
        record["count"] += 1
        if source not in record["sources"]:
            record["sources"].append(source)

    def note_db_name(self, name, source="db"):
        if isinstance(name, str) and name.strip():
            self._note_name(name.strip(), source)

    def result(self):
        """Assign story order + context windows, return the key list."""
        for entry in self.entries:
            for token in parse_codes(entry["ja"]):
                if code_key(token) != "N":
                    continue
                match = re.fullmatch(r"\[[ ]*(\d+)[ ]*\]", token[2:])
                if match:
                    self._note_name(self.actors.get(int(match.group(1))),
                                    "macro")
        for seq, entry in enumerate(self.entries):
            entry["seq"] = seq
        for entries in self._streams.values():
            windows = {}
            for entry in entries:
                marker = entry.pop("_window", None)
                windows.setdefault(marker, []).append(entry)
            for window_entries in windows.values():
                names = [name for entry in window_entries
                         if (name := namebox_of(entry["ja"]))]
                # One message window belongs to one speaker, and the box can
                # sit anywhere inside it (often at the end), so the last box
                # labels the whole window - except for lines that name their
                # speaker in the text itself (【name】), which stays explicit.
                window_name = names[-1] if names else None
                for entry in window_entries:
                    entry["speaker"] = (prefix_speaker(entry["ja"])
                                        or window_name or entry["speaker"])
            for index, entry in enumerate(entries):
                low = max(0, index - self.window)
                high = min(len(entries), index + self.window + 1)
                entry["prev"] = [e["ja"] for e in entries[low:index]]
                entry["next"] = [e["ja"] for e in entries[index + 1:high]]
        for entry in self.entries:
            entry.setdefault("prev", [])
            entry.setdefault("next", [])
        return self.entries


def _cmd_id(rel, path, suffix, param=0):
    return "%s#%s.parameters[%d]%s" % (rel, path, param, suffix)


def _walk_list(collector, lst, rel, path, where, stream):
    window = 0
    for index, command in enumerate(lst or []):
        if not is_command(command):
            collector.skipped["malformed"] += 1
            continue
        if command_code(command) == 101:
            # Show Text starts a message window; a name box only labels lines
            # inside its own window.
            window += 1
        elif command_code(command) == PLUGIN_CONT_CODE:
            # Editor echo of a 357's arguments; counted so the report shows why
            # the key list is smaller than the raw command count.
            collector.skipped["plugin-continuation"] += 1
        for field, text in text_codes(command):
            collector.add(_cmd_id(rel, "%s[%d]" % (path, index), field),
                          "map" if "Map" in rel else
                          ("common" if "CommonEvents" in rel else "troop"),
                          "%s/%s" % (where, command_code(command)),
                          text, stream, window=window)
        for param, field, text in extra_text_codes(command):
            collector.add(_cmd_id(rel, "%s[%d]" % (path, index), field, param),
                          "map" if "Map" in rel else
                          ("common" if "CommonEvents" in rel else "troop"),
                          "%s/%s" % (where, command_code(command)),
                          text, stream, window=window)


def _map_order(data_dir):
    """Map ids in MapInfos order, then any map file MapInfos forgot."""
    ids = []
    path = os.path.join(data_dir, "MapInfos.json")
    if os.path.isfile(path):
        with io.open(path, encoding="utf-8") as handle:
            infos = json.load(handle)
        named = [info for info in infos if isinstance(info, dict)]
        named.sort(key=lambda info: (info.get("order") or 0, info.get("id") or 0))
        ids = [info["id"] for info in named if isinstance(info.get("id"), int)]
    known = set(ids)
    have = set()
    for name in os.listdir(data_dir):
        match = re.fullmatch(r"Map(\d{3,})\.json", name)
        if match:
            have.add(int(match.group(1)))
    ids += sorted(have - known)
    return ids


def _records(data):
    """A JSON file that should hold a list of records - positions preserved.

    MV/MZ database arrays carry ``null`` at index 0, and a key's id is its
    array index, so entries must never be filtered out (that would shift every
    later id).  Non-dict entries are skipped by the caller, in place.
    """
    return data if isinstance(data, list) else []


def _read_json(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _collect_maps(collector, game_dir, data_dir):
    for map_id in _map_order(data_dir):
        path = os.path.join(data_dir, "Map%03d.json" % map_id)
        if not os.path.isfile(path):
            continue
        rel = "data/Map%03d.json" % map_id
        data = _read_json(path)
        title = data.get("displayName") or "Map%03d" % map_id
        if isinstance(data.get("displayName"), str):
            # A location banner is often kanji-only, so it counts as UI text
            # (the kana rule would drop it) even though it lives in map data.
            collector.add("%s#displayName" % rel, "ui",
                          "%s/displayName" % title, data["displayName"],
                          "%s#displayName" % rel)
        for event_index, event in enumerate(data.get("events") or []):
            if not event:
                continue
            event_name = event.get("name") or "event%d" % event_index
            for page_index, page in enumerate(event.get("pages") or []):
                base = "events[%d].pages[%d].list" % (event_index, page_index)
                stream = "%s#%s" % (rel, base)
                _walk_list(collector, page.get("list"), rel, base,
                           "%s / %s / p%d" % (title, event_name, page_index),
                           stream)


def _collect_common(collector, data_dir):
    path = os.path.join(data_dir, "CommonEvents.json")
    if not os.path.isfile(path):
        return
    for index, event in enumerate(_records(_read_json(path))):
        if not isinstance(event, dict):
            continue
        base = "[%d].list" % index
        _walk_list(collector, event.get("list"), "data/CommonEvents.json", base,
                   "%s / CommonEvent %s" % (event.get("name") or "", index),
                   "data/CommonEvents.json#%s" % base)


def _collect_troops(collector, data_dir):
    path = os.path.join(data_dir, "Troops.json")
    if not os.path.isfile(path):
        return
    for index, troop in enumerate(_records(_read_json(path))):
        if not isinstance(troop, dict):
            continue
        name = troop.get("name") or "Troop%d" % index
        collector.add("data/Troops.json#[%d].name" % index, "troop",
                      "%s/name" % name, name, "data/Troops.json#[%d]" % index)
        for page_index, page in enumerate(troop.get("pages") or []):
            base = "[%d].pages[%d].list" % (index, page_index)
            _walk_list(collector, page.get("list"), "data/Troops.json", base,
                       "%s / Troops / p%d" % (name, page_index),
                       "data/Troops.json#%s" % base)


def _collect_db(collector, data_dir):
    for filename, fields in DB_FIELDS.items():
        path = os.path.join(data_dir, filename)
        if not os.path.isfile(path):
            continue
        rel = "data/" + filename
        for index, record in enumerate(_records(_read_json(path))):
            if not isinstance(record, dict):
                continue
            label = record.get("name") or "%s[%d]" % (filename, index)
            collector.note_db_name(record.get("name"))
            if filename == "Actors.json" and record.get("name"):
                collector.actors[index + 1] = record["name"]
            for field in fields:
                text = record.get(field)
                if isinstance(text, list):
                    for sub_index, item in enumerate(text):
                        collector.add("%s#[%d].%s[%d]" % (rel, index, field,
                                                          sub_index),
                                      "db", "%s/%s[%d]" % (label, field,
                                                           sub_index),
                                      item, "%s#[%d]" % (rel, index))
                    continue
                collector.add("%s#[%d].%s" % (rel, index, field), "db",
                              "%s/%s" % (label, field), text,
                              "%s#[%d]" % (rel, index))


def _collect_system(collector, data_dir):
    path = os.path.join(data_dir, "System.json")
    if not os.path.isfile(path):
        return
    data = _read_json(path)
    rel = "data/System.json"

    def walk(node, path):
        if isinstance(node, str):
            collector.add("%s#%s" % (rel, path), "ui", "System/%s" % path,
                          node, "%s#%s" % (rel, path))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, "%s[%d]" % (path, index))
        elif isinstance(node, dict):
            for key, item in node.items():
                walk(item, "%s.%s" % (path, key) if path else key)

    for key in _SYSTEM_KEYS:
        if key in data:
            walk(data[key], key)
    walk(data.get("terms") or {}, "terms")


def _collect_plugins(collector, game_dir):
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.isfile(path):
        return
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    match = re.search(r"\[\s*\{.*\}\s*\]", source, re.S)
    if not match:
        collector.skipped["plugin"] += 1
        return
    try:
        plugins = json.loads(match.group(0))
    except ValueError:
        collector.skipped["plugin"] += 1
        return
    for index, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            continue
        name = plugin.get("name") or "plugin%d" % index
        params = plugin.get("parameters")
        if not isinstance(params, dict):
            continue
        for key, value in params.items():
            if not isinstance(value, str) or not is_candidate(value, "plugin"):
                continue
            if _PATH_RE.search(value) or _SCRIPTISH_RE.search(value):
                collector.skipped["plugin"] += 1
                continue
            collector.add("js/plugins.js#[%d].parameters.%s" % (index, key),
                          "plugin", "%s/%s" % (name, key), value,
                          "js/plugins.js#[%d]" % index)


def extract(game_dir, work_dir, window=2):
    """Extract every translatable string, write the work dir, return stats."""
    data_dir = os.path.join(game_dir, "data")
    if not os.path.isdir(data_dir):
        raise FileNotFoundError("no data/ directory under %s" % game_dir)
    collector = _Collector(window=window)
    _collect_maps(collector, game_dir, data_dir)
    _collect_common(collector, data_dir)
    _collect_troops(collector, data_dir)
    _collect_db(collector, data_dir)
    _collect_system(collector, data_dir)
    _collect_plugins(collector, game_dir)
    entries = collector.result()

    os.makedirs(work_dir, exist_ok=True)
    keys_path = os.path.join(work_dir, "keys.jsonl")
    with io.open(keys_path, "w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    names = {name: record for name, record in sorted(
        collector.names.items(), key=lambda kv: (-kv[1]["count"], kv[0]))}
    with io.open(os.path.join(work_dir, "names_candidates.json"), "w",
                 encoding="utf-8", newline="\n") as handle:
        json.dump(names, handle, ensure_ascii=False, indent=1, sort_keys=False)
        handle.write("\n")

    table = codes_mod.inventory(game_dir, collector.code_counts)
    codes_mod.write_markdown(os.path.join(work_dir, "control_codes.md"), table,
                             total_keys=len(entries))

    by_kind = Counter(entry["kind"] for entry in entries)
    stats = {
        "schema": SCHEMA,
        "game_dir": os.path.abspath(game_dir),
        "keys": len(entries),
        "by_kind": dict(sorted(by_kind.items())),
        "streams": len(collector._streams),
        "codes": {key: info["count"] for key, info in
                  sorted(table.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
                  if info["count"]},
        "undocumented_codes": sorted(
            key for key, info in table.items()
            if info["count"] and not info.get("documented")),
        "skipped": dict(sorted(collector.skipped.items())),
        "names": len(names),
        "window": window,
    }
    with io.open(os.path.join(work_dir, "stats.json"), "w", encoding="utf-8",
                 newline="\n") as handle:
        json.dump(stats, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return stats


def load_keys(work_dir):
    """Read ``keys.jsonl`` back as a list (streaming, order preserved)."""
    path = os.path.join(work_dir, "keys.jsonl")
    out = []
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def slice_keys(work_dir, start=0, count=None, kind=None, skip_ids=None):
    """A slice of the key list, streamed - the translator reads one at a time.

    The whole list is far too large for one context (tens of thousands of
    keys), so the subagent works scene by scene: this returns ``start`` to
    ``start + count`` in story order, optionally filtered by kind.

    ``skip_ids`` drops keys that already have a translation (ids whose value
    came from a harvested dictionary), applied **before** ``count`` so a slice
    is always ``count`` keys of real work.  ``start`` still counts positions in
    the full list, so a resume can be expressed either way.
    """
    out = []
    path = os.path.join(work_dir, "keys.jsonl")
    with io.open(path, encoding="utf-8") as handle:
        for seq, line in enumerate(handle):
            line = line.strip()
            if not line or seq < start:
                continue
            if count is not None and len(out) >= count:
                break
            entry = json.loads(line)
            if kind and entry.get("kind") != kind:
                continue
            if skip_ids and entry["id"] in skip_ids:
                continue
            out.append(entry)
    return out
