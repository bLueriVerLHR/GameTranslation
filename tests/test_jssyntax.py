#!/usr/bin/env python3
"""Direct contract tests for the in-process JavaScript syntax checker.

`rpgmaker/jssyntax.py` is used by the scenario extractors and the `[iscript]`
block checker.  The checks here pin its two entry points and the two paths the
callers exercise (`is_valid` as the boolean form, and error de-duplication when
a parser error and a missing node share a position).
"""
from rpgmaker import jssyntax


class TestIsValid:
    def test_valid_source(self):
        assert jssyntax.is_valid("var a = 1;") is True

    def test_invalid_source(self):
        assert jssyntax.is_valid("var x = \"abc") is False

    def test_is_valid_is_the_inverse_of_parse_errors(self):
        for source in ("function f() { return 1; }", "x(", "if (a) { b(); }"):
            assert jssyntax.is_valid(source) == (not
                                                jssyntax.parse_errors(source))


class TestParseErrors:
    def test_clean_source_has_no_errors(self):
        assert jssyntax.parse_errors("function f(a) { return a; }") == []

    def test_broken_source_names_the_region(self):
        errors = jssyntax.parse_errors("var x = ;")
        assert errors, "an assignment without a value must not parse"
        assert errors[0]["line"] == 1
        assert errors[0]["column"] >= 1
        assert errors[0]["error"].startswith("line 1:")
        assert "unexpected" in errors[0]["error"]

    def test_missing_node_is_reported_as_missing(self):
        errors = jssyntax.parse_errors("function f() {\n  var a = 1;\n")
        assert len(errors) == 1, errors
        assert "missing" in errors[0]["error"]
        assert errors[0]["line"] == 2

    def test_two_nodes_at_one_position_are_reported_once(self):
        """An error node and a node inside it can share a start position.

        The deduplication is what keeps the report readable; without it the
        same broken character is listed twice.
        """
        source = "if (x) { y(); } el'e { z(); }"
        errors = jssyntax.parse_errors(source)
        positions = [(e["line"], e["column"]) for e in errors]
        assert len(positions) == len(set(positions)), errors
        assert len(errors) == 1, errors
