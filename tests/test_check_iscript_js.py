#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tools/check_iscript_js.py.

The tool exists to turn "the scenario silently stopped advancing" into a
filename and a syntax error, so both directions matter: it must report broken
JavaScript, and it must not invent problems in valid blocks.
"""
import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import check_iscript_js as cij  # noqa: E402

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def write_ks(path, text, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return str(path)


# ------------------------------------------------------------------ extraction

def test_extracts_block_body():
    text = "[iscript]\nvar a = 1;\n[endscript]\n"
    blocks = list(cij.iter_iscript_blocks(text))
    assert len(blocks) == 1
    offset, body = blocks[0]
    assert "var a = 1;" in body
    assert offset == 0


def test_extracts_multiple_blocks_with_offsets():
    text = "x\n[iscript]a();[endscript]\ny\n[iscript]b();[endscript]\n"
    blocks = list(cij.iter_iscript_blocks(text))
    assert len(blocks) == 2
    assert blocks[0][0] < blocks[1][0]
    assert "a()" in blocks[0][1] and "b()" in blocks[1][1]


def test_ignores_empty_blocks():
    assert list(cij.iter_iscript_blocks("[iscript]\n\n[endscript]\n")) == []


def test_unclosed_block_is_not_guessed():
    # No [endscript]: do not silently treat the rest of the file as code.
    assert list(cij.iter_iscript_blocks("[iscript]\nvar a = 1;\n")) == []


def test_block_with_attributes_is_handled():
    text = "[iscript x=1]\nvar a = 1;\n[endscript]\n"
    blocks = list(cij.iter_iscript_blocks(text))
    assert len(blocks) == 1 and "var a = 1;" in blocks[0][1]


# ------------------------------------------------------------------ checking

@needs_node
def test_valid_javascript_passes(tmp_path):
    write_ks(tmp_path / "ok.ks",
             "[iscript]\nfunction f(a) { return a + 1; }\n[endscript]\n")
    checked, problems = cij.scan_tree(str(tmp_path))
    assert (checked, problems) == (1, [])


@needs_node
def test_invalid_javascript_is_reported_with_file_and_offset(tmp_path):
    write_ks(tmp_path / "bad.ks",
             "head\n[iscript]\nvar x = 1;\nsetter(ma){\nthis.a = 1;\n}\n"
             "[endscript]\n")
    checked, problems = cij.scan_tree(str(tmp_path))
    assert checked == 1
    assert len(problems) == 1
    p = problems[0]
    assert p["file"].endswith("bad.ks")
    assert p["offset"] > 0
    assert "SyntaxError" in p["error"]


@needs_node
def test_the_real_regression_pattern_is_caught(tmp_path):
    # A TJS `setter(x){...}` left inside an object literal is exactly what
    # stopped a real converted build.  Reproduce that file's exact shape:
    # the getter's closing brace is NOT followed by a comma, so node reports
    # `Unexpected identifier 'setter'`.
    write_ks(tmp_path / "conv.ks",
             "[iscript]\n"
             "Object.defineProperty(F.prototype, 'G', {\n"
             "  get: function () {\n    return 1;\n  }\n"
             "  setter(ma){\n    this.a = ma;\n  },\n"
             "  set: function (ma) { this.a = ma; },\n"
             "});\n[endscript]\n")
    _checked, problems = cij.scan_tree(str(tmp_path))
    assert len(problems) == 1
    assert "setter" in problems[0]["error"]


@needs_node
def test_comma_form_is_valid_js_so_node_cannot_catch_it(tmp_path):
    # Boundary of this tool: with a comma after the getter, a leaked
    # `setter(ma){...}` parses as an ES6 method shorthand, so it is NOT a
    # syntax error and node --check stays silent - even though the accessor
    # is missing.  The hard failure (no comma -> `Unexpected identifier`)
    # is what this tool catches; the silent variant must be caught by the
    # converter's own tests (tests/test_tjs2js.py asserts no raw `setter(`
    # survives conversion).
    write_ks(tmp_path / "silent.ks",
             "[iscript]\n"
             "Object.defineProperty(F.prototype, 'G', {\n"
             "  get: function () { return 1; },\n"
             "  setter(ma){\n    this.a = ma;\n  },\n"
             "  set: function (ma) { this.a = ma; },\n"
             "});\n[endscript]\n")
    checked, problems = cij.scan_tree(str(tmp_path))
    assert checked == 1
    assert problems == [], (
        "if this ever fails, node started rejecting the comma form and the "
        "tool got stronger - update the note in tools/check_iscript_js.py")


@needs_node
def test_clean_tree_reports_zero_errors(tmp_path):
    write_ks(tmp_path / "a.ks", "[iscript]\nvar a = 1;\n[endscript]\n")
    write_ks(tmp_path / "b.ks", "; no code here\n[wait time=100]\n")
    checked, problems = cij.scan_tree(str(tmp_path))
    assert checked == 1 and problems == []


@needs_node
def test_limit_stops_early(tmp_path):
    for i in range(3):
        write_ks(tmp_path / ("bad%d.ks" % i),
                 "[iscript]\nsetter(x){\n}\n[endscript]\n")
    checked, problems = cij.scan_tree(str(tmp_path), limit=2)
    assert len(problems) == 2
    assert checked >= 2


@needs_node
def test_utf16_scenario_is_decoded(tmp_path):
    write_ks(tmp_path / "u16.ks",
             "[iscript]\nvar a = 1;\n[endscript]\n", encoding="utf-16")
    checked, problems = cij.scan_tree(str(tmp_path))
    assert checked == 1 and problems == []


@needs_node
def test_shift_jis_scenario_is_decoded(tmp_path):
    write_ks(tmp_path / "sjis.ks",
             "; コメント\n[iscript]\nvar a = 1;\n[endscript]\n",
             encoding="cp932")
    checked, problems = cij.scan_tree(str(tmp_path))
    assert checked == 1 and problems == []


# ----------------------------------------------------------------------- CLI

@needs_node
def test_cli_exit_code_zero_on_clean_build(tmp_path, capsys):
    write_ks(tmp_path / "ok.ks", "[iscript]\nvar a = 1;\n[endscript]\n")
    assert cij.main([str(tmp_path)]) == 0


@needs_node
def test_cli_exit_code_one_on_broken_build(tmp_path):
    write_ks(tmp_path / "bad.ks", "[iscript]\nsetter(x){\n}\n[endscript]\n")
    assert cij.main([str(tmp_path)]) == 1


@needs_node
def test_cli_json_reports_counts(tmp_path, capsys):
    write_ks(tmp_path / "bad.ks", "[iscript]\nsetter(x){\n}\n[endscript]\n")
    cij.main([str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["blocks"] == 1 and len(payload["errors"]) == 1


def test_cli_rejects_a_missing_directory(tmp_path, capsys):
    assert cij.main([str(tmp_path / "nope")]) == 1


def test_missing_node_is_reported_not_silently_passed(monkeypatch, tmp_path):
    # Reporting "0 errors" when the checker never ran would be worse than
    # failing: it is a false all-clear on a build that may be broken.
    write_ks(tmp_path / "a.ks", "[iscript]\nvar a = 1;\n[endscript]\n")

    def no_node(*_a, **_kw):
        raise FileNotFoundError("node")

    monkeypatch.setattr(cij.subprocess, "run", no_node)
    assert cij.main([str(tmp_path)]) == 2
