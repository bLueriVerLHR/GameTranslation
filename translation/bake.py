#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bake.py - write the translated library back into the game (MV / MZ data).

This is the parent's half of the v2 workflow: the translator never touches
JSON, and the *only* place escaping happens is ``rawlib.to_json``; here the
already-escaped, already-gated values are put back where they came from.

Keyed by id, never by line or position: a key's id is its JSON path
(``data/Map003.json#events[2].pages[0].list[7].parameters[0]``), so a bake is
exact and re-runnable - running it twice changes nothing the second time.

Command shapes: MV/MZ accepts both ``[401, 0, "text"]`` (editor arrays) and
``{"code": 401, "indent": 0, "parameters": ["text"]}`` (what a tool that
rewrites data saves).  A path says ``.parameters[N]``, which is index ``N`` of
the ``parameters`` key in the object form and index ``2 + N`` of the array in
the array form; both are handled, because a build ships whichever its last
writer produced.

Fonts: a Chinese translation needs Chinese glyphs.  Per the local strategy
table (``docs/table/font_rollback.md``), an MV game is switched by pointing
``fonts/gamefont.css`` at a Simplified-Chinese font that also covers kana -
the game's own ``standardFontFace`` keeps saying ``GameFont``, so no JS change
is needed.  The original font file is never deleted.

Every file this module modifies is backed up into ``<work>/backup/<relpath>``
first, so a bake is always reversible without touching the sources.
"""
import io
import json
import os
import re
import shutil

__all__ = ["BakeError", "UNIFIED_FONT", "parse_path", "set_by_path",
           "load_plugin_params", "save_plugin_params", "apply_font",
           "bake"]

#: Unified Simplified-Chinese font (local private asset, never committed).
UNIFIED_FONT = "GlowSansSC-Compressed-Regular.otf"
FONT_SOURCE = os.path.join("docs", "table", "fonts", UNIFIED_FONT)
FONT_CSS = os.path.join("fonts", "gamefont.css")

_PATH_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
_PLUGINS_RE = re.compile(r"(\[\s*\{.*\}\s*\])", re.S)


class BakeError(Exception):
    """A key could not be written back (unknown path, unreadable file)."""


def parse_path(path):
    """``events[2].pages[0].list[7].parameters[0]`` -> tokens.

    Tokens are ``(name, None)`` or ``(None, index)``; the trailing ``[1]`` of a
    choice text (``parameters[0][1]``) is just another index token.
    """
    tokens = []
    position = 0
    while position < len(path):
        char = path[position]
        if char == ".":
            position += 1
            continue
        match = _PATH_TOKEN.match(path, position)
        if not match:
            raise BakeError("cannot parse path %r at %d" % (path, position))
        name, index = match.groups()
        tokens.append((name, None) if name else (None, int(index)))
        position = match.end()
    return tokens


def set_by_path(root, tokens, value):
    """Set `value` at `tokens` inside `root`; return True when it was set.

    Handles the array/object command duality: when the current node is a list
    and the token is the name ``parameters``, the realised position is
    ``2 + N`` (the array form stores code, indent, then the parameters).
    """
    node = root
    position = 0
    while position < len(tokens):
        name, index = tokens[position]
        if name == "parameters" and isinstance(node, list) \
                and position + 1 < len(tokens):
            offset = tokens[position + 1][1]
            if offset is None:
                return False
            position += 1                  # consume the "parameters" name
            name, index = None, 2 + offset
        if index is not None:
            if not isinstance(node, list) or index >= len(node):
                return False
            if position == len(tokens) - 1:
                node[index] = value
                return True
            node = node[index]
        else:
            if not isinstance(node, dict) or name not in node:
                return False
            if position == len(tokens) - 1:
                node[name] = value
                return True
            node = node[name]
        position += 1
    return False


def load_plugin_params(game_dir):
    """``(parameters list, prefix, suffix)`` of ``js/plugins.js``.

    ``plugins.js`` is a JavaScript file holding one JSON array
    (``var $plugins = [...];``); the prefix/suffix are kept so rewriting it
    does not disturb anything else in the file.
    """
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.isfile(path):
        return None, "", ""
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        source = handle.read()
    match = _PLUGINS_RE.search(source)
    if not match:
        raise BakeError("js/plugins.js does not contain a plugins array")
    try:
        plugins = json.loads(match.group(1))
    except ValueError as error:
        raise BakeError("js/plugins.js is not parseable: %s" % error)
    return (plugins, source[:match.start(1)],
            source[match.end(1):])


def save_plugin_params(game_dir, plugins, prefix, suffix):
    """Write ``js/plugins.js`` back (compact JSON, UTF-8, LF, no BOM)."""
    body = json.dumps(plugins, ensure_ascii=False, separators=(",", ":"))
    path = os.path.join(game_dir, "js", "plugins.js")
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(prefix + body + suffix)
    return path


def apply_font(game_dir, font_path=None, repo_root=None):
    """Point the game's single MV font face at a Simplified-Chinese font.

    Returns ``(changed_files, warnings)``.  A missing font asset is a warning,
    never a silent skip: shipping a Chinese build with a kana-only font means
    every Chinese character renders as a box.
    """
    warnings = []
    css_path = os.path.join(game_dir, FONT_CSS)
    if not os.path.isfile(css_path):
        return [], ["no %s (not an MV build?)" % FONT_CSS]
    font_path = font_path or os.path.join(repo_root or os.getcwd(),
                                          FONT_SOURCE)
    if not os.path.isfile(font_path):
        return [], ["unified font asset missing: %s" % font_path]
    with io.open(css_path, encoding="utf-8", errors="replace") as handle:
        css = handle.read()
    if UNIFIED_FONT in css:
        return [], []
    replaced, count = re.subn(r'src:\s*url\((?:"|\')?[^"\')]+(?:"|\')?\)',
                              'src: url("%s")' % UNIFIED_FONT, css)
    if not count:
        return [], ["%s has no @font-face src to switch" % FONT_CSS]
    destination = os.path.join(game_dir, "fonts", UNIFIED_FONT)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copyfile(font_path, destination)
    with io.open(css_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(replaced)
    return [FONT_CSS, os.path.join("fonts", UNIFIED_FONT)], warnings


def _backup(work_dir, game_dir, rel):
    source = os.path.join(game_dir, rel)
    if not os.path.isfile(source):
        return
    target = os.path.join(work_dir, "backup", rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not os.path.isfile(target):
        shutil.copyfile(source, target)


def _write_json(path, payload):
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False,
                                separators=(",", ":")))


def bake(game_dir, work_dir, apply_unified_font=True, repo_root=None,
         font_path=None, dry_run=False):
    """Write every translated key back into the game; return a report.

    With ``dry_run`` nothing is written and nothing is backed up: the report
    says what *would* change, which is how a build is inspected before touching
    it.
    """
    ids_path = os.path.join(work_dir, "translated_ids.json")
    if not os.path.isfile(ids_path):
        raise BakeError("translated_ids.json missing in %s (run to-json)"
                        % work_dir)
    with io.open(ids_path, encoding="utf-8") as handle:
        values = json.load(handle)

    by_file = {}
    for key_id, text in values.items():
        rel, _, path = key_id.partition("#")
        by_file.setdefault(rel, {})[path] = text

    written, applied, skipped = [], 0, []
    plugins = prefix = suffix = None
    for rel, entries in sorted(by_file.items()):
        if rel == "js/plugins.js":
            plugins, prefix, suffix = load_plugin_params(game_dir)
            for path, text in entries.items():
                tokens = parse_path(path)
                index = tokens[0][1]
                key = tokens[-1][0]
                if plugins is None or index is None or index >= len(plugins):
                    skipped.append((("%s#%s" % (rel, path)), "plugin missing"))
                    continue
                params = plugins[index].get("parameters") or {}
                if key not in params:
                    skipped.append((("%s#%s" % (rel, path)), "param missing"))
                    continue
                params[key] = text
                applied += 1
            continue
        path = os.path.join(game_dir, rel)
        if not os.path.isfile(path):
            skipped.append((rel, "file missing"))
            continue
        with io.open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        changed = False
        for sub_path, text in entries.items():
            try:
                ok = set_by_path(payload, parse_path(sub_path), text)
            except BakeError as error:
                skipped.append(("%s#%s" % (rel, sub_path), str(error)))
                continue
            if ok:
                applied += 1
                changed = True
            else:
                skipped.append(("%s#%s" % (rel, sub_path), "path not found"))
        if changed:
            if not dry_run:
                _backup(work_dir, game_dir, rel)
                _write_json(path, payload)
            written.append(rel)

    font_files, warnings = ([], [])
    if apply_unified_font and not dry_run:
        font_files, warnings = apply_font(game_dir, font_path=font_path,
                                          repo_root=repo_root)
        for rel in font_files:
            if rel != os.path.join("fonts", UNIFIED_FONT):
                _backup(work_dir, game_dir, rel)
    elif apply_unified_font:
        warnings = ["dry run: unified font not installed"]
    if plugins is not None and not dry_run:
        _backup(work_dir, game_dir, "js/plugins.js")
        save_plugin_params(game_dir, plugins, prefix, suffix)
        written.append("js/plugins.js")
    elif plugins is not None:
        written.append("js/plugins.js (dry run)")

    return {
        "keys": len(values),
        "applied": applied,
        "skipped": len(skipped),
        "skipped_detail": skipped[:50],
        "files": sorted(set(written)),
        "font_files": font_files,
        "font_warnings": warnings,
        "backup_dir": os.path.join(work_dir, "backup"),
    }
