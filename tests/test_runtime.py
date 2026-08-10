#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmz/runtime.py environment-aware worker tuning."""
import os

import pytest

from rpgmz import runtime


class TestAutoWorkers:
    def test_always_positive_int(self):
        for kind in ("copy", "decrypt", "probe", "encode", "decode",
                     "compress", "clean", "png", "unknown-kind"):
            assert isinstance(runtime.auto_workers(kind), int)
            assert runtime.auto_workers(kind) >= 1

    def test_global_env_override(self, monkeypatch):
        monkeypatch.setenv("GT_WORKERS", "3")
        for kind in ("copy", "encode", "compress"):
            assert runtime.auto_workers(kind) == 3

    def test_per_kind_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("GT_WORKERS", "8")
        monkeypatch.setenv("GT_WORKERS_ENCODE", "2")
        assert runtime.auto_workers("encode") == 2
        assert runtime.auto_workers("copy") == 8

    def test_invalid_env_override_ignored(self, monkeypatch):
        monkeypatch.setenv("GT_WORKERS", "banana")
        assert runtime.auto_workers("copy") >= 1

    def test_zero_or_negative_override_clamped(self, monkeypatch):
        monkeypatch.setenv("GT_WORKERS", "-1")
        assert runtime.auto_workers("copy") >= 1

    def test_upper_bound(self):
        for kind in ("copy", "encode", "compress"):
            assert runtime.auto_workers(kind) <= runtime.MAX_WORKERS

    def test_resolve_workers_explicit_wins(self, monkeypatch):
        monkeypatch.setenv("GT_WORKERS", "9")
        assert runtime.resolve_workers("copy", explicit=2) == 2
        assert runtime.resolve_workers("copy", explicit=None) == 9
        assert runtime.resolve_workers("copy", explicit=0) == 9

    def test_env_override_not_leaked_to_explicit(self, monkeypatch):
        monkeypatch.setenv("GT_WORKERS", "9")
        assert runtime.resolve_workers("encode", explicit=4) == 4


class TestResourceProbes:
    def test_cpu_count(self):
        assert runtime.cpu_count() >= 1

    def test_memory_bytes(self):
        b = runtime.memory_available_bytes()
        if b is not None:
            assert b > 0

    def test_memory_gib(self):
        g = runtime.memory_available_gib()
        assert g is None or g >= 0

    def test_disk_rotational_returns_none_or_bool(self):
        v = runtime.disk_is_rotational(os.getcwd())
        assert v is None or isinstance(v, bool)

    def test_auto_workers_cpu_bounded(self):
        cpus = runtime.cpu_count()
        assert runtime.auto_workers("encode") <= cpus
        assert runtime.auto_workers("compress") <= cpus
