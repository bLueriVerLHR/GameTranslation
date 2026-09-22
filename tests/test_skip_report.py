#!/usr/bin/env python3
"""Tests for tools/skip_report.py - the skip inventory CI prints every run.

Why this file exists
--------------------
`tests/test_test_layers.py` proves a skip is *allowed* (it names a layer, and
the count is inside `SKIP_BUDGET`), but a green build still hides which
capability is missing: "2 skipped" does not say whether Node, a media codec, an
optional extra or an incomplete checkout is the reason.  `tools/skip_report.py`
answers that, and CI runs it, so it has to be right about two things:

* the classification of each reason (the table it reports from lives in the
  gate, and this tool must *import* it rather than keep a copy that drifts);
* the failure path - a skip nobody can attribute must fail the run, or the
  report becomes decoration.

The real inventory is asserted too, because the report is only useful if the
numbers it prints describe this repository.
"""

import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO_ROOT, "tools", "skip_report.py")
if os.path.join(REPO_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import skip_report as sr  # noqa: E402


def _run(*argv):
    return subprocess.run(
        [sys.executable, TOOL, *argv],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")


class TestClassify:
    """`classify` is the whole judgement; the CLI is a printer around it."""

    def test_a_named_capability_maps_to_its_layer(self):
        bucket, detail = sr.classify("Node.js is required for this test", "",
                                     "skip")
        assert bucket == "node"
        assert "node.js" in detail

    def test_a_media_capability_is_not_confused_with_a_guard(self):
        for reason in ("the encoder lacks libvpx",
                       "PyAV is needed to transcode"):
            bucket, _detail = sr.classify(reason, "", "skip")
            assert bucket == "media", reason

    def test_two_capabilities_are_both_reported(self):
        """A reason naming two layers must not silently pick one of them."""
        bucket, _detail = sr.classify(
            "PyAV is needed and Node.js is required", "", "skip")
        assert bucket == "media+node"

    def test_a_documented_guard_is_reported_as_a_guard(self):
        for reason in ("git is unavailable",
                       "case-insensitive filesystem",
                       "cannot read the file",
                       "ruff is not installed"):
            bucket, _detail = sr.classify(reason, "", "skip")
            assert bucket == sr.GUARD, reason

    def test_an_unexplained_reason_is_unknown(self):
        bucket, detail = sr.classify("moon phase is wrong", "", "skip")
        assert bucket == sr.UNKNOWN
        assert detail == "moon phase is wrong"

    def test_importorskip_uses_the_package_not_the_reason(self):
        bucket, pkg = sr.classify("", "'numba'", "importorskip")
        assert bucket == "optional-import"
        assert pkg == "numba"

    def test_importorskip_of_something_unlisted_is_unknown(self):
        """A new optional import must be recorded, not waved through."""
        bucket, pkg = sr.classify("", "'some_new_package'", "importorskip")
        assert bucket == sr.UNKNOWN
        assert pkg == "some_new_package"

    def test_a_formatted_reason_is_matched_against_its_source(self):
        """Guard reasons are built with `%`, so they are not literals."""
        bucket, _detail = sr.classify('"cannot read %s: %s" % (rel, exc)', "",
                                      "skip")
        assert bucket == sr.GUARD


class TestCollect:
    def test_every_site_gets_a_bucket(self):
        rows = sr.collect()
        assert rows, "the scan found no skip site at all"
        for rel, lineno, name, _arg, bucket, detail in rows:
            assert rel.startswith("tests/"), (rel, lineno)
            assert name in ("skip", "importorskip", "xfail")
            assert bucket, "%s:%d has no bucket" % (rel, lineno)
            assert detail or bucket == sr.GUARD, (rel, lineno)

    def test_the_scan_skips_its_own_gate(self):
        """The gate's own string literals look like skip sites."""
        assert "tests/test_test_layers.py" not in {row[0] for row in
                                                   sr.collect()}

    def test_every_site_is_attributable(self):
        """The repository's own inventory must have no unknown skip.

        If this fails, either a reason lost its wording or a new capability
        appeared - both are the point of the gate.
        """
        unknown = [row for row in sr.collect() if row[4] == sr.UNKNOWN]
        assert not unknown, unknown

    def test_the_totals_match_the_gate_budget(self):
        """The inventory and `SKIP_BUDGET` count the same sites."""
        import test_test_layers as layers
        assert len(sr.collect()) == layers.SKIP_BUDGET


class TestCli:
    def test_the_report_lists_the_buckets(self):
        result = _run("--verbose")
        assert result.returncode == 0, result.stderr
        assert "skip inventory:" in result.stdout
        assert "budget" in result.stdout
        # Verbose adds the per-site lines.
        assert "tests/" in result.stdout

    def test_the_json_form_is_parseable_and_self_consistent(self):
        result = _run("--json")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["total"] == len(payload["sites"])
        assert payload["unknown"] == []
        assert sum(payload["by_capability"].values()) == payload["total"]

    def test_an_unexplained_skip_makes_the_run_fail(self, monkeypatch, capsys):
        """The failure path is the reason the tool is in CI at all.

        Note the explicit ``as_json=False``: a plain ``cmd()`` call would pass
        Typer's ``OptionInfo`` object as the default, which is truthy, so the
        in-process call would silently take the JSON branch.  Drive the tool
        through ``main([...])`` (as the CLI does) or spell the argument out.
        """
        monkeypatch.setattr(sr, "collect", lambda: [
            ("tests/test_x.py", 1, "skip", "'change of plan'", sr.UNKNOWN,
             "change of plan")])
        assert sr.main(["--verbose"]) == 1
        out = capsys.readouterr().out
        assert "unexplained skip(s)" in out
        assert "SKIP_REASON_LAYERS" in out

    def test_an_unexplained_skip_fails_the_json_form_too(self, monkeypatch,
                                                         capsys):
        """CI consumes --json, so the exit code must not depend on the format."""
        monkeypatch.setattr(sr, "collect", lambda: [
            ("tests/test_x.py", 7, "skip", "'moon phase'", sr.UNKNOWN,
             "moon phase")])
        assert sr.main(["--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["unknown"] == [{"file": "tests/test_x.py", "line": 7,
                                       "call": "skip",
                                       "reason": "moon phase"}]
        assert payload["total"] == 1
        assert payload["by_capability"] == {"unknown": 1}

    def test_help_renders(self):
        result = _run("--help")
        assert result.returncode == 0
        assert "skip" in result.stdout.lower()
