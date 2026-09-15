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
CommonEvent names) and file paths in plugin parameters.  Those are reported in
``stats.json`` under ``skipped``.
"""
import io
import json
import os
import re
from collections import Counter, OrderedDict, defaultdict

from . import codes as codes_mod
from .codes import CJK_RE, KANA_RE, code_key, parse_codes

__all__ = ["extract", "load_keys", "text_codes", "speaker_of", "is_candidate"]

#: Command codes whose first parameter is displayed text.
TEXT_CODES = (401, 405)
#: Show Choices: parameters[0] is the list of choice texts.
CHOICE_CODE = 102

#: Database files and the fields that hold displayed text.  `note` is
#: deliberately absent: it carries plugin commands, not prose.
DB_FIELDS = OrderedDict([
    ("Actors.json", ("name", "nickname")),
    ("Classes.json", ("name",)),
    ("Skills.json", ("name", "description")),
    ("Items.json", ("name", "description")),
    ("Weapons.json", ("name", "description")),
    ("Armors.json", ("name", "description")),
    ("Enemies.json", ("name",)),
    ("States.json", ("name", "message1", "message2", "message3", "message4")),
])

_SYSTEM_KEYS = ("gameTitle", "currencyUnit", "armorTypes", "elements",
                "skillTypes", "weaponTypes", "equipTypes")

_PATH_RE = re.compile(
    r"\.(?:png|jpg|jpeg|bmp|webp|ogg|m4a|mp3|wav|webm|mp4|json|js|txt|ttf|otf"
    r"|rpgmvp|rpgmvo|rpgmvm|zip)\b", re.I)
_SCRIPTISH_RE = re.compile(
    r"=>|function\s*\(|\$data|\bthis\.|\breturn\b|;\s*$|\{\s*$", re.M)

#: Version of the JSONL contract; bumped when a field's meaning changes.
SCHEMA = 2


def text_codes(command):
    """The displayed strings of one MV/MZ command, as ``[(path, text)]``.

    A command is normally ``[code, indent, *params]``, but plugin-written
    entries can be any shape (a dict, a short list); anything that is not a
    command is ignored here and counted as `malformed` by the caller.
    """
    if not isinstance(command, (list, tuple)) or len(command) < 3:
        return []
    code, params = command[0], command[2:]
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

    Kana always means text.  Kanji-only strings count for database/UI/plugin
    kinds (labels such as "攻撃"), but not for map dialogue (there a kana-less
    string is a symbol, a number or a stray control code).
    """
    if not isinstance(text, str) or not text.strip():
        return False
    if KANA_RE.search(text):
        return True
    if kind in ("db", "ui", "plugin") and CJK_RE.search(text):
        return not _PATH_RE.search(text) and not _SCRIPTISH_RE.search(text)
    return False


def speaker_of(text):
    """Speaker referenced by a line: name box, bracket prefix or ``X「``."""
    if not text:
        return None
    for token in parse_codes(text):
        if code_key(token) == "NC" and "<" in token:
            return token[token.index("<") + 1:-1].strip() or None
    match = re.match(r"^【([^】]{1,16})】", text)
    if match:
        return match.group(1).strip() or None
    match = re.match(r"^([^\s「」『』、。！？!?]{1,12})[「『]", text)
    return match.group(1) if match else None


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

    def add(self, key_id, kind, where, text, stream, name_hint=None):
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
            for index, entry in enumerate(entries):
                low = max(0, index - self.window)
                high = min(len(entries), index + self.window + 1)
                entry["prev"] = [e["ja"] for e in entries[low:index]]
                entry["next"] = [e["ja"] for e in entries[index + 1:high]]
        for entry in self.entries:
            entry.setdefault("prev", [])
            entry.setdefault("next", [])
        return self.entries


def _cmd_id(rel, path, suffix):
    return "%s#%s.parameters[0]%s" % (rel, path, suffix)


def _walk_list(collector, lst, rel, path, where, stream):
    for index, command in enumerate(lst or []):
        if not isinstance(command, (list, tuple)):
            collector.skipped["malformed"] += 1
            continue
        for field, text in text_codes(command):
            collector.add(_cmd_id(rel, "%s[%d]" % (path, index), field),
                          "map" if "Map" in rel else
                          ("common" if "CommonEvents" in rel else "troop"),
                          "%s/%s" % (where, command[0]),
                          text, stream)


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
