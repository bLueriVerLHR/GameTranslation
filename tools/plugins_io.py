#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plugins_io.py - tolerant parse/serialize of RPG Maker MZ/MV js/plugins.js.

The editor writes the file as a JSON-ish JS literal:

    var $plugins =
    [
        {
            "name": "Foo.js",
            "status": true,
            "description": "...",
            "parameters": { "Key": "Value" }
        }
    ];

Strict path: extract the array literal and json.loads it.  If that fails
(minified / unquoted keys / comments), a small recursive-descent parser for
the JS-literal subset handles strings, objects (quoted or identifier keys),
arrays, numbers, true/false/null.  On total failure, a last-resort textual
exact-match pass is still available to bakers via iter_literals().

Serialization uses the strict editor style (quoted keys, 4-space indent) -
valid JS for the runtime, which only reads the global `$plugins` array.
"""
import json
import re

HEAD = re.compile(r"var\s+\$plugins\s*=\s*")
JS_STR = re.compile(r'"(?:[^"\\]|\\.)*"')


def _find_array(text, i):
    """Index of the outermost '[' at/after i and the matching ']'."""
    i = text.find("[", i)
    if i < 0:
        raise ValueError("no array literal")
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i, j + 1
    raise ValueError("unbalanced array literal")


def _scan_string(text, i):
    if text[i] != '"':
        raise ValueError("expected string at %d" % i)
    out = []
    i += 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            if i + 1 >= len(text):
                raise ValueError("dangling escape")
            nxt = text[i + 1]
            out.append("\\" + nxt)
            i += 2
            continue
        if c == '"':
            try:
                return json.loads('"%s"' % "".join(out)), i + 1
            except ValueError:
                raise ValueError("bad escape sequence in string")
        out.append(c)
        i += 1
    raise ValueError("unterminated string")


def _skip_ws(text, i):
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _parse_value(text, i):
    i = _skip_ws(text, i)
    if i >= len(text):
        raise ValueError("unexpected end")
    c = text[i]
    if c == '"':
        return _scan_string(text, i)
    if c == "{":
        i += 1
        obj = {}
        while True:
            i = _skip_ws(text, i)
            if i >= len(text):
                raise ValueError("unterminated object")
            if text[i] == "}":
                return obj, i + 1
            if text[i] == '"':
                key, i = _scan_string(text, i)
            else:
                m = re.match(r"[A-Za-z_$][\w$]*", text[i:])
                if not m:
                    raise ValueError("bad object key at %d" % i)
                key, i = m.group(0), i + len(m.group(0))
            i = _skip_ws(text, i)
            if i >= len(text) or text[i] != ":":
                raise ValueError("expected ':' at %d" % i)
            val, i = _parse_value(text, i + 1)
            obj[key] = val
            i = _skip_ws(text, i)
            if i < len(text) and text[i] == ",":
                i += 1
    if c == "[":
        i += 1
        arr = []
        while True:
            i = _skip_ws(text, i)
            if i >= len(text):
                raise ValueError("unterminated array")
            if text[i] == "]":
                return arr, i + 1
            val, i = _parse_value(text, i)
            arr.append(val)
            i = _skip_ws(text, i)
            if i < len(text) and text[i] == ",":
                i += 1
    m = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null", text[i:])
    if not m:
        raise ValueError("unexpected char at %d: %r" % (i, text[i:i + 20]))
    tok = m.group(0)
    if tok == "true":
        return True, i + 4
    if tok == "false":
        return False, i + 5
    if tok == "null":
        return None, i + 4
    if "." in tok or "e" in tok.lower():
        return float(tok), i + len(tok)
    return int(tok), i + len(tok)


def parse_plugins_js(text):
    """-> list of plugin dicts {name, status, description, parameters}."""
    if text.startswith("\ufeff"):
        text = text[1:]
    m = HEAD.search(text)
    if m:
        text = text[m.end():]
    try:
        start, end = _find_array(text, 0)
        plugins = json.loads(text[start:end])
    except ValueError:
        val, _ = _parse_value(text, 0)
        plugins = val
    return [p for p in plugins if isinstance(p, dict)]


def dump_plugins_js(plugins):
    return "var $plugins =\n" + json.dumps(
        plugins, ensure_ascii=False, indent=4) + ";\n"


def iter_plugin_strings(plugins, ja_re):
    """Yield (where, string) for every JA-bearing display string in plugin
    parameters.  `where` = "js/plugins.js / <plugin name> / <param key>".
    Names (filename), status booleans and numbers are skipped."""
    for p in plugins:
        name = p.get("name")
        if not isinstance(name, str):
            name = "?"
        params = p.get("parameters")
        if not isinstance(params, (dict, list)):
            continue
        items = params.items() if isinstance(params, dict) \
            else [(i, v) for i, v in enumerate(params)]
        for key, val in items:
            if not isinstance(val, str) or not val.strip():
                continue
            if not ja_re.search(val):
                continue
            yield "js/plugins.js / %s / %s" % (name, key), val


def iter_literals(text):
    """Fallback textual pass: yield every JS string literal in order."""
    for m in JS_STR.finditer(text):
        try:
            yield json.loads(m.group(0))
        except ValueError:
            continue
