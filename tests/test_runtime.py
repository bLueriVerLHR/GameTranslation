#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/runtime.py environment-aware worker tuning."""
import os
import sys


from rpgmaker import runtime


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


class _FakeMemStatus:
    """Mimics the MEMORYSTATUSEX struct written by GlobalMemoryStatusEx."""

    def __init__(self, avail=0):
        self.dwLength = 0
        self.dwMemoryLoad = 0
        self.ullTotalPhys = 0
        self.ullAvailPhys = avail
        self.ullTotalPageFile = 0
        self.ullAvailPageFile = 0
        self.ullTotalVirtual = 0
        self.ullAvailVirtual = 0
        self.ullAvailExtendedVirtual = 0


class _FakeKernel32:
    """GlobalMemoryStatusEx variants: ok / returns False / raises OSError."""

    def __init__(self, avail, fail=None):
        self._avail = avail
        self._fail = fail

    def GlobalMemoryStatusEx(self, m):
        if self._fail == "oserror":
            raise OSError("kernel32 load failure")
        if self._fail == "false":
            return False
        m.ullAvailPhys = self._avail
        return True


class _FakeWindll:
    def __init__(self, avail, fail=None):
        self.kernel32 = _FakeKernel32(avail, fail)


class _FakeCtypes:
    """Drop-in for the ctypes module with a scriptable windll."""

    class Structure:
        pass

    # the real code's _fields_ reference these ctypes scalars by name; a plain
    # class only needs them to exist (they are never actually used for layout)
    c_uint32 = int
    c_uint64 = int

    def __init__(self, avail=0, fail=None, no_windll=False):
        self._avail = avail
        self._fail = fail
        self._no_windll = no_windll

    @property
    def windll(self):
        if self._no_windll:
            raise AttributeError("no windll on this platform")
        return _FakeWindll(self._avail, self._fail)

    @staticmethod
    def sizeof(_s):
        return 72

    @staticmethod
    def byref(m):
        return m


class TestWindowsMemory:
    """GlobalMemoryStatusEx branch of memory_available_bytes (mocked ctypes -
    only ever runs on native Windows, so the branch has no other test hook)."""

    def test_windows_success_returns_avail_bytes(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypes(avail=8 * 1024 ** 3))
        assert runtime.memory_available_bytes() == 8 * 1024 ** 3

    def test_windows_false_return_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypes(avail=123, fail="false"))
        assert runtime.memory_available_bytes() is None

    def test_windows_oserror_degrades_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypes(avail=123, fail="oserror"))
        assert runtime.memory_available_bytes() is None

    def test_windows_missing_windll_degrades_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypes(avail=123, no_windll=True))
        assert runtime.memory_available_bytes() is None

    def test_memory_gib_uses_windows_bytes(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypes(avail=6 * 1024 ** 3))
        assert runtime.memory_available_gib() == 6


class TestDiskRotationalSysfs:
    """HDD detection degrades to None when /sys is unreachable (WSL, network
    mounts, exotic sysfs) and reads the rotational flag when present."""

    def test_sysfs_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")

        def missing(p):
            raise FileNotFoundError("no such sysfs entry")
        monkeypatch.setattr(runtime.os, "readlink", missing)
        assert runtime.disk_is_rotational(str(tmp_path)) is None

    def test_stat_failure_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")

        def missing(p):
            raise FileNotFoundError("no such file")
        monkeypatch.setattr(runtime.os, "stat", missing)
        assert runtime.disk_is_rotational(str(tmp_path)) is None

    def test_non_linux_returns_none(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert runtime.disk_is_rotational(os.getcwd()) is None

    @staticmethod
    def _mock_rotational(monkeypatch, value):
        class _FakeSt:
            st_dev = (8 << 8) | 0  # major=8 minor=0 (sd*)
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(runtime.os, "stat", lambda p: _FakeSt())
        # os.major/os.minor are POSIX-only: create them on Windows so the
        # sysfs branch can be exercised from any host (raising=False).
        monkeypatch.setattr(runtime.os, "major", lambda dev: dev >> 8,
                            raising=False)
        monkeypatch.setattr(runtime.os, "minor", lambda dev: dev & 0xFF,
                            raising=False)
        monkeypatch.setattr(runtime.os, "readlink", lambda p: "sda")
        real_open = open

        class _F:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return value

        def fake_open(path, *a, **kw):
            if str(path).endswith("/queue/rotational"):
                return _F()
            return real_open(path, *a, **kw)
        monkeypatch.setattr("builtins.open", fake_open)

    def test_rotational_flag_1_true(self, tmp_path, monkeypatch):
        self._mock_rotational(monkeypatch, "1")
        assert runtime.disk_is_rotational(str(tmp_path)) is True

    def test_rotational_flag_0_false(self, tmp_path, monkeypatch):
        self._mock_rotational(monkeypatch, "0")
        assert runtime.disk_is_rotational(str(tmp_path)) is False
