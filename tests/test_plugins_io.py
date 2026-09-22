#!/usr/bin/env python3
"""Unit tests for rpgmaker/plugins_io.py tolerant js/plugins.js parsing."""
import re

import pytest

from rpgmaker import plugins_io

EDITOR_STYLE = '''var $plugins =
[
    {
        "name": "TestPlugin.js",
        "status": true,
        "description": "desc",
        "parameters": { "Title": "タイトル" }
    },
    {
        "name": "NoText.js",
        "status": true,
        "description": "",
        "parameters": { "Count": 3 }
    }
];
'''

MINIFIED = '''var $plugins=[{"name":"M.js","status":true,"description":"","parameters":{"Key":"値"}}];'''

UNQUOTED = '''
var $plugins =
[
    {
        name: "U.js",
        status: false,
        description: null,
        parameters: { Key: "テキスト" }
    }
];
'''

COMMENTED = '''var $plugins =
[
    // the battle plugin
    {
        "name": "C.js", /* panel title */
        "status": true,
        "description": "",
        "parameters": {
            // label shown in the menu
            "Title": "コメント付き"
        }
    },
    /* trailing block comment */
    {
        "name": "D.js",
        "status": true,
        "description": "",
        "parameters": { "Key": "値" }
    }
];
/* footer */
'''

JA = re.compile(r"[\u3040-\u30ff]")


class TestParse:
    def test_editor_style(self):
        plugins = plugins_io.parse_plugins_js(EDITOR_STYLE)
        assert len(plugins) == 2
        assert plugins[0]["name"] == "TestPlugin.js"
        assert plugins[0]["parameters"]["Title"] == "タイトル"
        assert plugins[1]["parameters"]["Count"] == 3

    def test_minified(self):
        plugins = plugins_io.parse_plugins_js(MINIFIED)
        assert plugins[0]["parameters"]["Key"] == "値"

    def test_unquoted_keys(self):
        plugins = plugins_io.parse_plugins_js(UNQUOTED)
        assert plugins[0]["name"] == "U.js"
        assert plugins[0]["status"] is False
        assert plugins[0]["parameters"]["Key"] == "テキスト"

    def test_line_and_block_comments(self):
        """The docstring promises comment tolerance; the failure mode was
        silent (callers WARN and skip all plugin text)."""
        plugins = plugins_io.parse_plugins_js(COMMENTED)
        assert [p["name"] for p in plugins] == ["C.js", "D.js"]
        assert plugins[0]["parameters"]["Title"] == "コメント付き"
        assert plugins[1]["parameters"]["Key"] == "値"

    def test_unterminated_block_comment_does_not_hang(self):
        # A truncated file must raise, not loop forever.
        with pytest.raises(ValueError):
            plugins_io.parse_plugins_js('var $plugins = [ /* oops {"a": 1}]')

    def test_bom_tolerated(self):
        plugins = plugins_io.parse_plugins_js("\ufeff" + EDITOR_STYLE)
        assert len(plugins) == 2

    def test_empty_raises(self):
        # an empty/broken plugins.js has no array literal to parse
        with pytest.raises(ValueError):
            plugins_io.parse_plugins_js("")


class TestDump:
    def test_roundtrip(self):
        plugins = [{"name": "A.js", "status": True, "description": "",
                    "parameters": {"K": "日本語"}}]
        text = plugins_io.dump_plugins_js(plugins)
        assert "var $plugins =" in text
        assert plugins_io.parse_plugins_js(text) == plugins

    def test_ascii_escaped_when_no_cjk(self):
        text = plugins_io.dump_plugins_js([{"parameters": {"a": "1"}}])
        assert "a" in text


class TestIterators:
    def test_iter_plugin_strings(self):
        plugins = plugins_io.parse_plugins_js(EDITOR_STYLE)
        hits = list(plugins_io.iter_plugin_strings(plugins, JA))
        assert len(hits) == 1
        where, val = hits[0]
        assert "TestPlugin.js" in where and "Title" in where
        assert val == "タイトル"

    def test_iter_literals(self):
        hits = list(plugins_io.iter_literals('a "x" b "y\\n"'))
        assert hits == ["x", "y\n"]
