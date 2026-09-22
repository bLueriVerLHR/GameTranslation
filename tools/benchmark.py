#!/usr/bin/env python3
"""Run a reproducible synthetic build/verify benchmark and compare trends.

The corpus is deliberately synthetic and contains no game-specific data.  The
first repetition is labelled ``cold-ish``: the operating system cache is not
purged, so this is not a claim of a truly cold disk.  Later repetitions are
labelled ``warm-ish`` because they reuse the same source tree.  Results record
both phases instead of pretending either one is exact.

Usage:
    python -m tools.benchmark run --out .tmp/benchmark.json
    python -m tools.benchmark compare .tmp/baseline.json .tmp/benchmark.json
"""
from __future__ import annotations

import json
import math
import platform
import random
import statistics
import struct
import tempfile
import time
import zlib
from pathlib import Path
from typing import Annotated

from rpgmaker import build, cliutil, verify

SCHEMA_VERSION = 1
DEFAULT_FILES = 80
DEFAULT_REPEATS = 3
BENCHMARK_WORKERS = 1
DEFAULT_SEED = 20260922
DEFAULT_MAX_REGRESSION = 0.25


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    """Return a deterministic 1x1 RGBA PNG without an image dependency."""
    raw = b"\x00" + bytes((*color, 255))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def create_corpus(root: Path, files: int, seed: int) -> dict[str, int]:
    """Create the fixed corpus and return its measured file/byte counts."""
    rng = random.Random(seed)
    for directory in ("data", "img/pictures", "audio/bgm", "js"):
        (root / directory).mkdir(parents=True, exist_ok=True)

    (root / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    for name in ("main.js", "rpg_core.js", "plugins.js"):
        contents = "var $plugins = [];\n" if name == "plugins.js" else "// synthetic benchmark\n"
        (root / "js" / name).write_text(contents, encoding="utf-8")
    (root / "data" / "System.json").write_text("{}\n", encoding="utf-8")
    for index in range(files):
        payload = {
            "@name": f"Map {index:04d}",
            "events": [],
            "seed": rng.randrange(0, 2**31),
        }
        (root / "data" / f"Map{index + 1:04d}.json").write_text(
            json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
        (root / "img" / "pictures" / f"pic_{index:04d}.png").write_bytes(
            _png_bytes((index % 256, (index * 3) % 256, (index * 7) % 256)))
        (root / "audio" / "bgm" / f"bgm_{index:04d}.ogg").write_bytes(
            bytes((index % 251,)) * 256)

    paths = [path for path in root.rglob("*") if path.is_file()]
    return {"files": len(paths), "bytes": sum(path.stat().st_size for path in paths)}


def _measure_once(source: Path, destination: Path, workers: int) -> dict[str, float | int]:
    """Measure one build and one verification pass on a fresh destination."""
    started = time.perf_counter()
    build.build_joiplay(str(source), str(destination), keep_movies=False,
                        workers=workers)
    build_seconds = time.perf_counter() - started

    started = time.perf_counter()
    issues = verify.verify_all(str(destination), workers=workers)
    verify_seconds = time.perf_counter() - started
    if issues:
        raise RuntimeError(f"synthetic benchmark verification failed: {issues}")
    output_files = sum(1 for path in destination.rglob("*") if path.is_file())
    return {
        "build_seconds": build_seconds,
        "verify_seconds": verify_seconds,
        "output_files": output_files,
    }


def run_benchmark(files: int = DEFAULT_FILES, repeats: int = DEFAULT_REPEATS,
                  workers: int = BENCHMARK_WORKERS, seed: int = DEFAULT_SEED) -> dict:
    """Run the benchmark in a temporary workspace and return its JSON report."""
    if files < 1 or repeats < 1 or workers < 1:
        raise ValueError("files, repeats and workers must be positive")
    with tempfile.TemporaryDirectory(prefix="gametranslation-benchmark-") as temp:
        workspace = Path(temp)
        source = workspace / "source"
        corpus = create_corpus(source, files, seed)
        samples = []
        for iteration in range(repeats):
            destination = workspace / f"build-{iteration}"
            sample = _measure_once(source, destination, workers)
            sample["iteration"] = iteration
            sample["cache_phase"] = "cold-ish" if iteration == 0 else "warm-ish"
            samples.append(sample)

    def median(name: str) -> float:
        return statistics.median(float(sample[name]) for sample in samples)

    return {
        "schema": SCHEMA_VERSION,
        "kind": "gametranslation-synthetic-benchmark",
        "platform": {"system": platform.system().lower(),
                     "machine": platform.machine().lower()},
        "python": {"implementation": platform.python_implementation().lower(),
                   "version": ".".join(platform.python_version_tuple()[:2])},
        "seed": seed,
        "corpus": {**corpus, "map_files": files, "repeats": repeats,
                   "workers": workers},
        "cache_policy": {
            "cold": "first repetition only; OS caches are not purged",
            "warm": "later repetitions reuse the same source tree",
        },
        "samples": samples,
        "summary": {
            "build_seconds": median("build_seconds"),
            "verify_seconds": median("verify_seconds"),
        },
    }


def _report_errors(report: object, label: str) -> list[str]:
    """Return structural/value errors without letting malformed JSON crash."""
    if not isinstance(report, dict):
        return [f"{label}: report must be a JSON object"]
    errors = []
    if report.get("schema") != SCHEMA_VERSION:
        errors.append(f"{label}: unsupported benchmark schema")
    if report.get("kind") != "gametranslation-synthetic-benchmark":
        errors.append(f"{label}: unexpected benchmark kind")
    errors.extend(
        f"{label}: {key} must be an object"
        for key in ("platform", "python", "corpus", "summary")
        if not isinstance(report.get(key), dict)
    )
    summary = report.get("summary")
    if isinstance(summary, dict):
        for name in ("build_seconds", "verify_seconds"):
            value = summary.get(name)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or value <= 0):
                errors.append(f"{label}: {name} must be finite and positive")
    return errors


def compare_reports(baseline: object, current: object,
                    max_regression: float = DEFAULT_MAX_REGRESSION) -> list[str]:
    """Return validation and trend failures for comparable environments."""
    failures = (_report_errors(baseline, "baseline")
                + _report_errors(current, "current"))
    if (not isinstance(max_regression, (int, float))
            or isinstance(max_regression, bool)
            or not math.isfinite(max_regression) or max_regression < 0):
        failures.append("max_regression must be finite and non-negative")
    if failures:
        return failures
    assert isinstance(baseline, dict) and isinstance(current, dict)
    for field, message in (
        ("platform", "platform differs from the baseline"),
        ("python", "Python runtime differs from the baseline"),
        ("seed", "corpus seed differs from the baseline"),
        ("corpus", "corpus configuration differs from the baseline"),
        ("cache_policy", "cache policy differs from the baseline"),
    ):
        if baseline.get(field) != current.get(field):
            failures.append(message)
    if failures:
        return failures
    for name in ("build_seconds", "verify_seconds"):
        before = float(baseline["summary"][name])
        after = float(current["summary"][name])
        ratio = (after - before) / before
        if ratio > max_regression:
            failures.append(
                f"{name}: regression {ratio:.1%} exceeds {max_regression:.1%}")
    return failures


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def cmd_run(
    out: Annotated[str, cliutil.Option("--out", help="JSON report path")]
        = ".tmp/benchmark.json",
    files: Annotated[int, cliutil.Option("--files", help="map files in corpus")]
        = DEFAULT_FILES,
    repeats: Annotated[int, cliutil.Option("--repeats", help="sample count")]
        = DEFAULT_REPEATS,
    workers: Annotated[int, cliutil.Option("--workers", help="build workers")]
        = BENCHMARK_WORKERS,
    seed: Annotated[int, cliutil.Option("--seed", help="synthetic corpus seed")]
        = DEFAULT_SEED,
) -> int:
    """Generate a synthetic corpus, benchmark it, and save a JSON report."""
    try:
        report = run_benchmark(files, repeats, workers, seed)
        _write_report(Path(out), report)
    except (OSError, ValueError, RuntimeError) as exc:
        return cliutil.fail(f"benchmark failed: {exc}")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


def cmd_compare(
    baseline: Annotated[str, cliutil.Argument(help="baseline JSON report")],
    current: Annotated[str, cliutil.Argument(help="current JSON report")],
    max_regression: Annotated[float, cliutil.Option(
        "--max-regression", help="allowed relative slowdown")]
        = DEFAULT_MAX_REGRESSION,
) -> int:
    """Compare same-OS reports and fail only on a significant slowdown."""
    try:
        old = json.loads(Path(baseline).read_text(encoding="utf-8"))
        new = json.loads(Path(current).read_text(encoding="utf-8"))
        failures = compare_reports(old, new, max_regression)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return cliutil.fail(f"cannot compare benchmark reports: {exc}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return cliutil.fail("benchmark trend regression")
    print("OK: benchmark trend within threshold")
    return 0


app = cliutil.app(help=__doc__)
app.command(name="run")(cmd_run)
app.command(name="compare")(cmd_compare)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="benchmark.py")


if __name__ == "__main__":
    raise SystemExit(main())
