"""Tests for the reproducible synthetic benchmark and trend gate."""
from __future__ import annotations

import json

import pytest

from tools import benchmark


def _report(system="windows", build=1.0, verify=2.0):
    return {
        "schema": benchmark.SCHEMA_VERSION,
        "platform": {"system": system},
        "corpus": {"map_files": 3, "repeats": 2, "workers": 1},
        "summary": {"build_seconds": build, "verify_seconds": verify},
    }


def test_run_benchmark_has_fixed_corpus_and_cache_phases():
    report = benchmark.run_benchmark(files=3, repeats=2, workers=1, seed=7)
    assert report["kind"] == "gametranslation-synthetic-benchmark"
    assert report["seed"] == 7
    assert report["corpus"]["map_files"] == 3
    assert [sample["cache_phase"] for sample in report["samples"]] == [
        "cold-ish", "warm-ish"
    ]
    assert report["summary"]["build_seconds"] > 0
    assert report["summary"]["verify_seconds"] > 0


def test_run_benchmark_rejects_invalid_sizes():
    with pytest.raises(ValueError, match="must be positive"):
        benchmark.run_benchmark(files=0)


def test_compare_reports_accepts_same_os_within_threshold():
    assert benchmark.compare_reports(_report(), _report(build=1.2, verify=2.1)) == []


def test_compare_reports_rejects_regression():
    failures = benchmark.compare_reports(_report(), _report(build=1.3), 0.2)
    assert failures == ["build_seconds: regression 30.0% exceeds 20.0%"]


def test_compare_reports_rejects_cross_os_absolute_comparison():
    failures = benchmark.compare_reports(_report("windows"), _report("linux"))
    assert failures == ["refusing to compare absolute times across operating systems"]


def test_cli_report_writer_is_utf8_json(tmp_path):
    report = _report()
    path = tmp_path / "benchmark.json"
    benchmark._write_report(path, report)
    assert json.loads(path.read_text(encoding="utf-8")) == report
