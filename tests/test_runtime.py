#!/usr/bin/env python3
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
            assert runtime.auto_workers(kind) <= runtime.worker_ceiling()

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
        """CPU-bound kinds never exceed the *physical* core count."""
        cores = runtime.physical_cpu_count()
        for kind in ("encode", "compress", "decode", "tlg"):
            assert runtime.auto_workers(kind) <= cores


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


def _core_entry(size=48, relationship=0):
    """One LOGICAL_PROCESSOR_RELATIONSHIP entry (header + zeroed union)."""
    import struct as _struct
    return _struct.pack("<II", relationship, size) + b"\x00" * (size - 8)


class _FakeTopologyKernel32:
    """Mimics the two-call GetLogicalProcessorInformationEx protocol."""

    def __init__(self, payload=b"", second_ok=True):
        self.payload = payload
        self.second_ok = second_ok
        self.calls = 0

    def GetLogicalProcessorInformationEx(self, relation, buf, plen):
        self.calls += 1
        if not buf:
            plen._obj.value = len(self.payload)
            return 0            # ERROR_INSUFFICIENT_BUFFER, as the real API does
        import ctypes as _ctypes
        _ctypes.memmove(buf, self.payload, len(self.payload))
        plen._obj.value = len(self.payload)
        return 1 if self.second_ok else 0


class _FakeCtypesTopology:
    """Minimal `ctypes` stand-in exposing only what the topology probe uses."""

    def __init__(self, kernel32):
        import ctypes as _ctypes
        self.windll = type("W", (), {"kernel32": kernel32})()
        self.create_string_buffer = _ctypes.create_string_buffer
        self.byref = _ctypes.byref


class TestPhysicalCores:
    """The worker defaults are based on *physical* cores, so the probe has to
    be right (or degrade safely) on every platform."""

    def test_counts_only_core_entries(self, monkeypatch):
        # 6 processor cores + 1 package entry ("number of sockets"): only the
        # RelationProcessorCore (0) entries are cores.
        payload = _core_entry() * 6 + _core_entry(size=8, relationship=1)
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypesTopology(_FakeTopologyKernel32(payload)))
        assert runtime._physical_windows() == 6

    def test_empty_topology_returns_none(self, monkeypatch):
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypesTopology(_FakeTopologyKernel32(b"")))
        assert runtime._physical_windows() is None

    def test_second_call_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(runtime, "ctypes", _FakeCtypesTopology(
            _FakeTopologyKernel32(_core_entry(), second_ok=False)))
        assert runtime._physical_windows() is None

    def test_malformed_entry_size_returns_none(self, monkeypatch):
        payload = _core_entry() + b"\x00\x00\x00\x00" + _core_entry()
        monkeypatch.setattr(runtime, "ctypes",
                            _FakeCtypesTopology(_FakeTopologyKernel32(payload)))
        assert runtime._physical_windows() is None

    def test_no_windll_degrades_to_none(self, monkeypatch):
        import types as _types
        monkeypatch.setattr(runtime, "ctypes", _types.SimpleNamespace())
        assert runtime._physical_windows() is None

    def test_a_partial_windll_degrades_to_none(self, monkeypatch):
        """A `windll` that exists but has no `kernel32` must also degrade.

        The probe reads `getattr(ctypes, "windll", None)` so the common
        non-Windows case returns early instead of raising; this covers the
        *other* AttributeError - the one line 81 really can raise - which is
        what the surrounding `except AttributeError` exists for.  Without it
        the handler is only reachable through OSError.
        """
        import types as _types
        monkeypatch.setattr(runtime, "ctypes", _types.SimpleNamespace(
            windll=_types.SimpleNamespace()))
        assert runtime._physical_windows() is None

    def test_linux_cpuinfo_counts_hyperthreads_once(self):
        # 4 cores with 2 SMT threads each: 8 processors, 4 distinct pairs.
        text = "\n".join(
            "processor\t: %d\nphysical id\t: 0\ncore id\t\t: %d\n" % (i, i // 2)
            for i in range(8))
        assert runtime._physical_linux_cpuinfo(text) == 4

    def test_linux_cpuinfo_two_sockets(self):
        text = ""
        for socket in (0, 1):
            for core in (0, 1):
                text += ("processor\t: %d\nphysical id\t: %d\ncore id\t\t: %d\n\n"
                         % (socket * 2 + core, socket, core))
        assert runtime._physical_linux_cpuinfo(text) == 4

    def test_linux_cpuinfo_without_physical_id(self):
        """Single-socket/container/ARM boxes have no `physical id` line; the
        core ids must still add up (this used to return None)."""
        text = "processor\t: 0\ncore id\t\t: 0\n\nprocessor\t: 1\ncore id\t\t: 1\n"
        assert runtime._physical_linux_cpuinfo(text) == 2

    def test_linux_cpuinfo_without_topology_is_none(self):
        assert runtime._physical_linux_cpuinfo("processor\t: 0\n") is None
        assert runtime._physical_linux_cpuinfo("") is None

    def test_sysfs_counts_sibling_groups(self, tmp_path, monkeypatch):
        """Fallback path: distinct thread_siblings_list values = cores."""
        cpu = tmp_path / "cpu"
        for i, siblings in enumerate(("0,4", "1,5", "2,6", "3,7", "0,4")):
            d = cpu / ("cpu%d" % i) / "topology"
            d.mkdir(parents=True)
            (d / "thread_siblings_list").write_text(siblings, encoding="ascii")
        (cpu / "cpufreq").mkdir()
        (cpu / "online").write_text("1", encoding="ascii")
        assert runtime._physical_linux_sysfs(str(cpu)) == 4

    def test_sysfs_missing_dir_is_none(self, tmp_path):
        assert runtime._physical_linux_sysfs(str(tmp_path / "nope")) is None

    def test_never_exceeds_logical_and_is_positive(self):
        n = runtime.physical_cpu_count()
        assert isinstance(n, int) and 1 <= n <= runtime.cpu_count()

    def test_result_is_memoized(self, monkeypatch):
        monkeypatch.setattr(runtime, "_PHYSICAL_CORES", 7)
        assert runtime.physical_cpu_count() == 7

    def test_falls_back_to_logical_when_probe_fails(self, monkeypatch):
        monkeypatch.setattr(runtime, "_PHYSICAL_CORES", None)
        monkeypatch.setattr(runtime, "cpu_count", lambda: 12)
        monkeypatch.setattr(runtime, "_physical_windows", lambda: None)
        monkeypatch.setattr(sys, "platform", "win32")
        assert runtime.physical_cpu_count() == 12

    def test_absurd_probe_value_falls_back(self, monkeypatch):
        """A probe that reports more cores than threads is wrong: ignore it."""
        monkeypatch.setattr(runtime, "_PHYSICAL_CORES", None)
        monkeypatch.setattr(runtime, "cpu_count", lambda: 4)
        monkeypatch.setattr(runtime, "_physical_windows", lambda: 99)
        monkeypatch.setattr(sys, "platform", "win32")
        assert runtime.physical_cpu_count() == 4


class TestAutoWorkersPhysicalBase:
    """`auto_workers` must be derived from the physical cores (no hardcoded
    per-kind cap that silently under-uses a bigger machine)."""

    @staticmethod
    def _pin(monkeypatch, cores, avail_gib=64, hdd=False):
        monkeypatch.setattr(runtime, "physical_cpu_count", lambda: cores)
        monkeypatch.setattr(runtime, "memory_available_bytes",
                            lambda: avail_gib * 1024 ** 3)
        monkeypatch.setattr(runtime, "disk_is_rotational", lambda p: hdd)

    def test_cpu_bound_kinds_default_to_the_core_count(self, monkeypatch):
        self._pin(monkeypatch, 6)
        for kind in ("encode", "decode", "tlg", "compress"):
            assert runtime.auto_workers(kind) == 6

    def test_io_bound_kinds_may_oversubscribe(self, monkeypatch):
        self._pin(monkeypatch, 6)
        assert runtime.auto_workers("decrypt") == 6
        assert runtime.auto_workers("png") == 6
        assert runtime.auto_workers("clean") == 6
        assert runtime.auto_workers("qc") == 6
        assert runtime.auto_workers("probe") == 12
        assert runtime.auto_workers("copy") == 14

    def test_a_bigger_machine_gets_more_workers(self, monkeypatch):
        """The whole point: no absolute cap ties the default to one machine."""
        self._pin(monkeypatch, 8)
        small = runtime.auto_workers("encode")
        self._pin(monkeypatch, 32)
        big = runtime.auto_workers("encode")
        assert big > small == 8 and big == 32

    def test_hdd_halves_the_cpu_bound_kinds(self, monkeypatch):
        self._pin(monkeypatch, 8, hdd=True)
        assert runtime.auto_workers("encode") == 4
        assert runtime.auto_workers("decode") == 4
        assert runtime.auto_workers("compress") == 8      # threads, not disk I/O

    def test_ram_only_truncates_when_workers_do_not_fit(self, monkeypatch):
        # 512 MiB free / 256 MiB per ffmpeg process = 2 workers, not 16
        self._pin(monkeypatch, 16, avail_gib=0.5)
        assert runtime.auto_workers("encode") == 2
        # in-process decodes are lighter (128 MiB each)
        assert runtime.auto_workers("decode") == 4

    def test_ram_failure_is_not_a_cap(self, monkeypatch):
        self._pin(monkeypatch, 16)
        monkeypatch.setattr(runtime, "memory_available_bytes", lambda: None)
        assert runtime.auto_workers("encode") == 16

    def test_env_override_is_clamped_by_the_ceiling(self, monkeypatch):
        self._pin(monkeypatch, 4)
        monkeypatch.setenv("GT_WORKERS", "9999")
        assert runtime.auto_workers("encode") == runtime.worker_ceiling()
        assert runtime.worker_ceiling() >= runtime.MAX_WORKERS

    def test_ceiling_grows_with_the_machine(self, monkeypatch):
        self._pin(monkeypatch, 64)
        assert runtime.worker_ceiling() == 256
