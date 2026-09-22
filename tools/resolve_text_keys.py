#!/usr/bin/env python3
"""resolve_text_keys.py - inline runtime text keys (``\\T[id]``) into a build.

Some MZ repacks do not carry display text in ``data/*.json`` at all: every
string is a **key** (``\\T[SIS1036]``, ``\\T[ITEM007n]``) and the text lives in
a table the game reads at runtime.  MZ has no such escape code - the resolution
is one of two mechanisms, and both fail on a JoiPlay/browser build:

* the **game's own** multilingual plugin (``Chimaki_Lang`` and friends) reads
  its table through Node's ``fs``.  A browser has no ``fs``, so the plugin can
  never work there - and it must not be enabled: registering it makes the title
  screen die with ``TypeError: ... reading 'SIS1036'`` mid-render.
* **MTool's** "mount translation" mode (marker: ``MTool挂载翻译.txt``) disables
  that plugin and resolves the keys from its own runtime dictionary
  (``<title>.json`` / ``翻译文件.json``).  None of that runtime survives in a
  web build, so the keys are drawn verbatim: the title menu reads
  ``\\T[SIS1036]`` instead of "New Game".

The fix is to inline the keys at build time from the data the repack already
ships.  Resolution tiers, best first:

1. ``csv.<lang>`` - the game's own text table (``csv/UI.csv``, columns
   ``id,who,tw,cn,en``): ``cn`` is a human-shaped Simplified Chinese
   translation, ``tw`` holds the Japanese source text.
2. ``dict.id`` - the runtime dictionary's **term** rows, keyed by the same ids
   (``"ID,who,ja,zh,en": "ID,who',zh,en"``).
3. ``dict.jp`` - the Japanese text of that id, translated through the
   dictionary's plain ``{japanese: chinese}`` pairs.
4. ``csv.tw`` - the Japanese source text itself, when nothing has a Chinese
   version.  Japanese on screen beats a raw ``\\T[BT0076p1s2]`` on screen, and
   the report counts these so the gap stays visible.
5. ``unresolved`` - no table row and no dictionary entry: the key is left
   verbatim and reported (``--strict`` makes that a non-zero exit).

Only **display text** is touched: the field rules are delegated to
``tools/qc_build_kana.py`` (``classify``), so asset names, event names,
``note`` fields and a 357 plugin command's dispatch keys are skipped exactly
where the acceptance scan skips them.  Writes use the bake's JSON style
(``ensure_ascii=False, indent=2``); ``js/plugins.js`` keeps the editor style.

Usage:
    python3 tools/resolve_text_keys.py <build_dir> [--csv CSV] [--dict DICT]
                                       [--lang cn] [--dry-run] [--strict]
                                       [--report REPORT.json]
"""
import collections
import csv
import glob
import json
import logging
import os
import sys
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpgmaker import cliutil  # noqa: E402
from rpgmaker import plugins_io  # noqa: E402
from tools import qc_build_kana  # noqa: E402
from translation import codes as tcodes, mvkeys, prefill  # noqa: E402

log = logging.getLogger("resolve_text_keys")

__all__ = ["TEXT_KEY", "Resolver", "read_text_table", "read_term_dict",
           "resolve_build", "resolve_value", "rewrite_document"]

#: ``\T[id]``, with the backslash run that carries its JSON escaping level.
#: The pattern lives in ``translation.codes`` - the acceptance scan
#: (``tools/qc_build_kana.py``) fails the build on the same hits, so both tools
#: must agree byte-for-byte (see the comment there).
TEXT_KEY = tcodes.TEXT_KEY_RE

#: Column of the game's text table that holds the target language.
DEFAULT_LANG = "cn"
#: Column that holds the Japanese source text (the author's base column).
SOURCE_COL = "tw"

#: Root-level file names a repack uses for its runtime dictionary.
DICT_NAMES = ("翻译文件.json", "AI翻译.json", "MTool翻译.json", "trs.json")
#: Nesting limit for keys whose text contains another key.
MAX_PASSES = 5


def read_text_table(path):
    """``{id: {column: text}}`` from a game text table (CSV, UTF-8, quoted)."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return {}
    header = [cell.strip().lower() for cell in rows[0]]
    if not header or header[0] != "id":
        log.warning("%s: no 'id' column (header %r) - skipped", path, header)
        return {}
    table = {}
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        cells = list(row) + [""] * len(header)
        table[row[0].strip()] = {
            header[i]: cells[i].strip() for i in range(len(header))}
    return table


def chinese_field(text):
    """The Chinese cell of one dictionary term row (``ID,who,ja,zh,en``).

    The row shape varies across repacks (2-7 fields), so the rule is
    positional-free: after the id, take the **last** field that carries CJK
    without kana.  A Japanese cell (``レベル``, ``コマンド``) is skipped by the
    kana test, a trailing ``Level`` / ``New game`` cell by the CJK test.
    """
    fields = [part.strip() for part in str(text).split(",")][1:]
    cands = [part for part in fields
             if part and tcodes.CJK_RE.search(part)
             and not tcodes.KANA_LETTERS_RE.search(part)]
    return cands[-1] if cands else None


def japanese_field(text):
    """The Japanese cell of one dictionary term row (last kana-bearing field)."""
    fields = [part.strip() for part in str(text).split(",")][1:]
    cands = [part for part in fields if tcodes.KANA_LETTERS_RE.search(part)]
    return cands[-1] if cands else None


def read_term_dict(path):
    """``(pairs, by_id, ja_by_id)`` from a runtime dictionary.

    ``pairs`` is the plain ``{japanese: chinese}`` half, ``by_id`` the term half
    keyed by the text id (``SIS1036 -> 新游戏``), ``ja_by_id`` the Japanese text
    a term row carries for that id.
    """
    runtime = prefill.load_runtime_dict(path)
    pairs, by_id, ja_by_id = {}, {}, {}
    for key, value in runtime.items():
        if "," not in key:
            pairs.setdefault(key.strip(), value.strip())
            continue
        head = key.split(",")[0].strip()
        if not head:
            continue
        chinese = chinese_field(value) or chinese_field(key)
        if chinese:
            by_id.setdefault(head, chinese)
        japanese = japanese_field(key)
        if japanese:
            ja_by_id.setdefault(head, japanese)
    return pairs, by_id, ja_by_id


class Resolver:
    """Text-id -> display text, keeping the tier that answered."""

    def __init__(self, tables=None, lang=DEFAULT_LANG):
        self.lang = lang
        self.zh = {}
        self.ja = {}
        self.dict_zh = {}
        self.dict_ja = {}
        self.pairs = {}
        for table in tables or []:
            for text_id, row in table.items():
                target = row.get(lang, "")
                if target and text_id not in self.zh:
                    self.zh[text_id] = target
                source = row.get(SOURCE_COL, "")
                if source and text_id not in self.ja:
                    self.ja[text_id] = source

    def add_dict(self, pairs, by_id, ja_by_id=None):
        for text_id, text in by_id.items():
            self.dict_zh.setdefault(text_id, text)
        for text_id, text in (ja_by_id or {}).items():
            self.dict_ja.setdefault(text_id, text)
        for japanese, chinese in pairs.items():
            if japanese and chinese:
                self.pairs.setdefault(japanese, chinese)

    def resolve(self, text_id):
        """``(text, tier)`` for one key; ``text`` is None when nothing has it."""
        text = self.zh.get(text_id)
        if text:
            return text, "csv." + self.lang
        text = self.dict_zh.get(text_id)
        if text:
            return text, "dict.id"
        source = self.ja.get(text_id) or self.dict_ja.get(text_id)
        if source:
            chinese = self.pairs.get(source) or self.pairs.get(source.strip())
            if chinese:
                return chinese, "dict.jp"
            return source, "csv." + SOURCE_COL
        return None, "unresolved"


def resolve_value(text, resolver, stats):
    """Inline every ``\\T[id]`` of one string (nested keys resolve in passes)."""
    if not isinstance(text, str) or "\\T[" not in text:
        return text
    for _pass in range(MAX_PASSES):
        text, hits = _substitute(text, resolver, stats)
        if not hits:
            break
    return text


def escape_for(text, depth):
    """Escape `text` so it survives `depth` JSON.parse round trips.

    A key inside a nested JSON parameter carries one escaping level per parse
    (``\\T[id]`` inside one layer, ``\\\\T[id]`` inside two).  The inlined text has
    to be escaped the same number of times, or a text holding a quote, a
    backslash or a newline breaks the blob the plugin parses at runtime - that
    is how a QuestDatas blob died with ``SyntaxError: ... is not valid JSON``.
    """
    out = text
    for _level in range(max(0, depth)):
        out = json.dumps(out, ensure_ascii=False)[1:-1]
    return out


def _substitute(text, resolver, stats):
    """One substitution pass; returns ``(text, hit count)``."""
    hits = []

    def repl(match):
        run, text_id = match.group(1), match.group(3)
        value, tier = resolver.resolve(text_id)
        stats["tiers"][tier] += 1
        if value is None:
            stats["unresolved"][text_id] += 1
            return match.group(0)
        hits.append(text_id)
        return escape_for(value, len(run) // 2)

    new_text = TEXT_KEY.sub(repl, text)
    stats["occurrences"] += len(hits)
    return new_text, hits


def is_display_text(file_name, trail, text, code):
    """Delegate the field rules to the acceptance scan (single source of truth)."""
    return qc_build_kana.classify(file_name, trail, text, code, []) \
        == "unexpected"


def _params_of(command):
    return qc_build_kana.params_of(command)


def _set_param(command, position, value):
    if isinstance(command, dict):
        params = command.get("parameters")
        if isinstance(params, list) and position < len(params):
            params[position] = value
    elif isinstance(command, (list, tuple)) and len(command) >= 3 + position:
        command[2 + position] = value


def rewrite_document(document, file_name, resolver, stats, classify=True):
    """Inline the keys of every display string in place; returns the document."""

    def visit(node, trail, code):
        if isinstance(node, str):
            if "\\T[" not in node:
                return node
            if classify and not is_display_text(file_name, trail, node, code):
                stats["skipped_non_display"] += 1
                return node
            return resolve_value(node, resolver, stats)
        if isinstance(node, list):
            for index, item in enumerate(node):
                node[index] = visit(item, "%s[%d]" % (trail, index), code)
            return node
        if isinstance(node, dict):
            for key in list(node):
                item = node[key]
                path = f"{trail}.{key}" if trail else key
                if key == "list" and isinstance(item, list):
                    for index, command in enumerate(item):
                        command_code = mvkeys.command_code(command)
                        for position in range(len(_params_of(command))):
                            value = _params_of(command)[position]
                            _set_param(command, position, visit(
                                value,
                                "%s.list[%d].parameters[%d]"
                                % (path, index, position), command_code))
                else:
                    node[key] = visit(item, path, code)
            return node
        return node

    return visit(document, "", None)


def json_layers(value):
    """How many string leaves parse as JSON, per nesting level.

    Plugins parse their parameters at runtime (one ``JSON.parse`` per nested
    blob), so inlining must not change what parses.  ``resolve_plugins``
    compares the profile before and after and warns on a regression instead of
    shipping a parameter the game dies on at boot.
    """
    profile = collections.Counter()

    def walk(node, level):
        if isinstance(node, str):
            try:
                parsed = json.loads(node)
            except (ValueError, TypeError):
                return
            profile[level] += 1
            walk(parsed, level + 1)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item, level)
        elif isinstance(node, list):
            for item in node:
                walk(item, level)

    walk(value, 1)
    return profile


def resolve_data_files(build_dir, resolver, stats, write=True):
    """Inline keys in every ``data/*.json``; returns the changed file names."""
    data_dir = os.path.join(build_dir, "data")
    if not os.path.isdir(data_dir):
        return []
    changed = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8-sig") as handle:
                document = json.load(handle)
        except (OSError, ValueError) as exc:
            log.warning("%s: unreadable (%s)", name, exc)
            continue
        stats["files"] += 1
        stats["strings"] += len(qc_build_kana.walk_document(document))
        before = stats["occurrences"]
        rewrite_document(document, name, resolver, stats)
        if stats["occurrences"] != before:
            changed.append(name)
            if write:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(document, handle, ensure_ascii=False, indent=2)
    return changed


def resolve_plugins(build_dir, resolver, stats, write=True):
    """Inline keys in ``js/plugins.js`` parameters.

    Plugin *parameters* are free-form: the entry's ``name`` is the plugin file
    name and command dispatch keys live in the plugin source, so every string
    leaf there is display text or configuration the plugin prints.  JSON-in-JSON
    blobs keep their structure (a leaf walk, never a re-serialization of the
    blob).
    """
    path = os.path.join(build_dir, "js", "plugins.js")
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8-sig") as handle:
        text = handle.read()
    plugins = plugins_io.parse_plugins_js(text)
    before = stats["occurrences"]
    for entry in plugins:
        params = entry.get("parameters")
        if not isinstance(params, (dict, list)):
            continue
        profile = json_layers(params)
        entry["parameters"] = rewrite_document(params, "plugins.js", resolver,
                                              stats, classify=False)
        if json_layers(entry["parameters"]) != profile:
            # A key inside a nested JSON parameter carries one escaping level
            # per JSON.parse; inlining at the wrong level makes the plugin's own
            # parse fail at boot (SyntaxError: ... is not valid JSON).
            log.warning("js/plugins.js %s: nested JSON parses differently after "
                        "inlining (%s -> %s) - check the escaping level",
                        entry.get("name"), dict(profile),
                        dict(json_layers(entry["parameters"])))
    changed = stats["occurrences"] != before
    if changed and write:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(plugins_io.dump_plugins_js(plugins))
    return changed


def find_dict(build_dir):
    """The repack's runtime dictionary in the build root (or None)."""
    for name in DICT_NAMES:
        path = os.path.join(build_dir, name)
        if os.path.isfile(path):
            return path
    for path in sorted(glob.glob(os.path.join(build_dir, "*.json"))):
        try:
            pairs, by_id, _ = read_term_dict(path)
        except (OSError, ValueError):
            continue
        if by_id or len(pairs) > 1000:
            return path
    return None


def find_tables(build_dir):
    """Every ``csv/*.csv`` table shipped by the game, sorted by name."""
    return sorted(glob.glob(os.path.join(build_dir, "csv", "*.csv")))


def new_stats():
    return {"files": 0, "strings": 0, "occurrences": 0, "skipped_non_display": 0,
            "tiers": collections.Counter(), "unresolved": collections.Counter(),
            "changed_files": [], "sources": {}}


def resolve_build(build_dir, csv_paths=None, dict_path="", lang=DEFAULT_LANG,
                  write=True):
    """Inline the text keys of a built game; returns the stats structure."""
    if not os.path.isdir(os.path.join(build_dir, "data")):
        raise FileNotFoundError(f"not an MZ/MV build (no data/): {build_dir}")
    stats = new_stats()

    tables = []
    for path in (list(csv_paths) if csv_paths else find_tables(build_dir)):
        table = read_text_table(path)
        if table:
            tables.append(table)
            stats["sources"][os.path.basename(path)] = len(table)
            log.info("text table %s: %d rows", os.path.basename(path), len(table))
    resolver = Resolver(tables, lang)
    log.info("table: %d id(s) with a '%s' column, %d with '%s'",
             len(resolver.zh), lang, len(resolver.ja), SOURCE_COL)

    if not dict_path:
        dict_path = find_dict(build_dir) or ""
    if dict_path:
        try:
            pairs, by_id, ja_by_id = read_term_dict(dict_path)
        except (OSError, ValueError) as exc:
            log.warning("runtime dictionary %s unreadable (%s)",
                        os.path.basename(dict_path), exc)
            pairs, by_id, ja_by_id = {}, {}, {}
        resolver.add_dict(pairs, by_id, ja_by_id)
        stats["sources"][os.path.basename(dict_path)] = len(pairs) + len(by_id)
        log.info("runtime dictionary %s: %d pair(s), %d term id(s)",
                 os.path.basename(dict_path), len(pairs), len(by_id))
    elif not tables:
        log.warning("no text table and no runtime dictionary - nothing to "
                    "resolve; the build keeps drawing raw \\T[...] keys")

    changed = resolve_data_files(build_dir, resolver, stats, write)
    if resolve_plugins(build_dir, resolver, stats, write):
        changed.append("js/plugins.js")
    stats["changed_files"] = changed
    return stats


def format_report(stats, limit=12):
    """Readable summary lines (also the --dry-run body)."""
    total = sum(stats["tiers"].values())
    lines = ["text keys: %d occurrence(s) over %d data file(s), %d string(s)"
             % (total, stats["files"], stats["strings"])]
    for tier, count in stats["tiers"].most_common():
        lines.append("  %-12s %6d  (%.1f%%)"
                     % (tier, count, 100.0 * count / total if total else 0.0))
    if stats["skipped_non_display"]:
        lines.append("  (skipped %d key(s) in engine-read fields: asset/event "
                     "names, note, plugin dispatch keys)"
                     % stats["skipped_non_display"])
    if stats["unresolved"]:
        lines.append("  unresolved: %d key(s), %d occurrence(s)"
                     % (len(stats["unresolved"]),
                        sum(stats["unresolved"].values())))
        for text_id, count in stats["unresolved"].most_common(limit):
            lines.append("    %-16s x%d" % (text_id, count))
    if stats["changed_files"]:
        lines.append("  rewritten: {}{}".format(", ".join(stats["changed_files"][:limit]),
                        " ..." if len(stats["changed_files"]) > limit else ""))
    return lines


def cmd(build_dir: Annotated[str, cliutil.Argument(help="built game directory")],
        csv_path: Annotated[list[str] | None, cliutil.Option(
            "--csv", help="game text table(s) with an id column "
            "(default: every csv/*.csv in the build)")] = None,
        dict_path: Annotated[str, cliutil.Option(
            "--dict", help="runtime dictionary to fall back on (default: the "
            "repack's root dictionary, auto-detected)")] = "",
        lang: Annotated[str, cliutil.Option(
            "--lang", help="target-language column of the text table")] = DEFAULT_LANG,
        dry_run: Annotated[bool, cliutil.Option(
            "--dry-run", help="report the resolution without writing")] = False,
        strict: Annotated[bool, cliutil.Option(
            "--strict", help="fail when a key stays unresolved")] = False,
        report: Annotated[str, cliutil.Option(
            "--report", help="write the stats (tiers, unresolved ids) as JSON")] = "",
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Inline runtime text keys (``\\T[id]``) into a built web root."""
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the
    # first stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("resolve text keys", build_dir=build_dir, csv_path=csv_path)
    build_dir = os.path.abspath(build_dir)
    try:
        stats = resolve_build(build_dir, csv_path, dict_path, lang,
                              write=not dry_run)
    except (FileNotFoundError, ValueError) as exc:
        return cliutil.fail(str(exc))
    for line in format_report(stats):
        log.info("%s", line)
    if dry_run:
        log.info("dry run - nothing written")
    if report:
        with open(report, "w", encoding="utf-8") as handle:
            json.dump({"tiers": dict(stats["tiers"]),
                       "unresolved": dict(stats["unresolved"]),
                       "sources": stats["sources"],
                       "changed_files": stats["changed_files"],
                       "files": stats["files"], "strings": stats["strings"]},
                      handle, ensure_ascii=False, indent=2)
        log.info("report -> %s", report)
    if stats["unresolved"]:
        log.warning("%d key(s) have no text in any source (left verbatim): "
                    "translate them, or ship them as they are",
                    len(stats["unresolved"]))
        if strict:
            return cliutil.fail("unresolved text keys (see the report above)")
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="resolve_text_keys.py")


if __name__ == "__main__":
    raise SystemExit(main())
