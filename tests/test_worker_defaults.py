#!/usr/bin/env python3
"""Repo-level invariants for parallelism defaults.

Owner directive: the default worker count is never a hardcoded number -- it is
probed from the machine (physical cores) through the single entry point
`rpgmaker/runtime.py`.  These tests fail when a new tool invents its own
default, re-introduces a legacy constant, or sizes a pool from
`os.cpu_count()` instead of the resolver.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpgmaker import runtime  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGES = ("rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity", "tools")
SKIP_DIRS = {".git", ".venv", ".tmp", ".tools", "__pycache__", "docs", "tests"}
#: The one module allowed to ask the OS for the core count.
RUNTIME_REL = os.path.join("rpgmaker", "runtime.py")


def _repo_sources():
    """{relative path: source text} for every toolkit module."""
    out = {}
    for pkg in PACKAGES:
        base = os.path.join(REPO, pkg)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, REPO)
                with open(path, encoding="utf-8") as f:
                    out[rel] = f.read()
    return out


SOURCES = _repo_sources()


class TestCoreProbingIsCentralised:
    def test_os_cpu_count_is_only_in_runtime(self):
        """A second `os.cpu_count()` means a second, drifting answer to
        "how many workers"."""
        offenders = sorted(rel for rel, text in SOURCES.items()
                           if rel != RUNTIME_REL and "cpu_count()" in text)
        assert offenders == [], (
            "use rpgmaker.runtime.physical_cpu_count()/resolve_workers() "
            f"instead: {offenders}")

    def test_multiprocessing_cpu_count_is_only_in_runtime(self):
        offenders = sorted(rel for rel, text in SOURCES.items()
                           if rel != RUNTIME_REL and "process_cpu_count" in text)
        assert offenders == []

    def test_legacy_hardcoded_worker_constants_are_gone(self):
        legacy = ("DEFAULT_WORKERS", "DEFAULT_PROBE_WORKERS",
                  "DEFAULT_ENCODE_WORKERS", "MAX_QC_WORKERS")
        found = {name: sorted(rel for rel, text in SOURCES.items() if name in text)
                 for name in legacy}
        assert all(v == [] for v in found.values()), found


class TestPoolsDeriveTheirSize:
    """A module that builds a pool must get its size from the resolver."""

    def test_pool_call_sites_reference_runtime(self):
        offenders = []
        for rel, text in SOURCES.items():
            if rel == RUNTIME_REL:
                continue
            if ("max_workers=" in text or "Pool(" in text) and "runtime" not in text:
                offenders.append(rel)
        assert offenders == [], (
            f"pool without rpgmaker.runtime sizing: {sorted(offenders)}")

    def test_qc_pool_uses_the_qc_kind(self):
        src = SOURCES[os.path.join("tools", "merge_plain_chunks.py")]
        assert 'runtime.auto_workers("qc"' in src

    def test_tlg_batch_tool_uses_the_tlg_kind(self):
        src = SOURCES[os.path.join("tools", "batch_decode_tlg.py")]
        assert 'runtime.resolve_workers("tlg"' in src

    def test_video_tool_default_is_not_a_constant(self):
        src = SOURCES[os.path.join("tools", "transcode_video.py")]
        assert 'runtime.resolve_workers("video"' in src


class TestVideoKind:
    """Video encoding jobs are half the cores: each VP9 encoder is itself
    multi-threaded, so one job per core would oversubscribe."""

    @staticmethod
    def _pin(monkeypatch, cores):
        monkeypatch.setattr(runtime, "physical_cpu_count", lambda: cores)
        monkeypatch.setattr(runtime, "memory_available_bytes",
                            lambda: 64 * 1024 ** 3)
        monkeypatch.setattr(runtime, "disk_is_rotational", lambda p: False)

    def test_half_the_cores(self, monkeypatch):
        self._pin(monkeypatch, 16)
        assert runtime.auto_workers("video") == 8
        self._pin(monkeypatch, 8)
        assert runtime.auto_workers("video") == 4

    def test_never_zero(self, monkeypatch):
        self._pin(monkeypatch, 1)
        assert runtime.auto_workers("video") == 1

    def test_explicit_jobs_wins(self, monkeypatch):
        self._pin(monkeypatch, 16)
        assert runtime.resolve_workers("video", 3) == 3
