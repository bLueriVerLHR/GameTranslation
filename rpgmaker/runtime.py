#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Environment-aware resource tuning for the toolkit.

Every step that runs parallel work asks `resolve_workers(kind, explicit)` for
its worker count.  Instead of a hardcoded default per step, the count is
derived from the machine the pipeline is actually running on:

  - CPU count (os.cpu_count)
  - available memory (Linux /proc/meminfo, Windows GlobalMemoryStatusEx)
  - disk type: rotational (HDD) disks get conservative caps, since many
    parallel readers/writers thrash a spinning disk far worse than an SSD

Kinds are tuned for the bottleneck of the step:

  copy      I/O-bound tree copy (build)        -> cpu*2+2, hdd capped
  decrypt   I/O-bound byte XOR (decrypt)       -> cpu, hdd capped
  clean     I/O-bound corpus scan (clean)      -> cpu, hdd capped
  png       I/O-bound header reads (verify)    -> cpu, hdd capped
  probe     subprocess spawn + I/O (ffprobe)   -> cpu*2, hdd capped
  encode    CPU-heavy subprocess (ffmpeg)      -> cpu, memory-aware, capped
  decode    CPU-heavy subprocess (verify)      -> cpu, memory-aware, capped
  compress  multi-thread archive (7z -mmt)     -> cpu, memory-aware, capped

Explicit `--workers N` always wins.  Env overrides:

  GT_WORKERS=<n>          global override for every kind
  GT_WORKERS_<KIND>=<n>   per-kind override (uppercased kind, e.g.
                          GT_WORKERS_ENCODE=2)

All numbers are clamped to >= 1.
"""
import ctypes
import logging
import os
import sys

log = logging.getLogger("rpgmaker.runtime")

MAX_WORKERS = 32


def cpu_count():
    """Number of usable CPU cores (>= 1)."""
    return os.cpu_count() or 4


def memory_available_bytes():
    """Best-effort available RAM in bytes, or None when undetectable."""
    if sys.platform == "linux":
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
        except OSError:
            pass
    elif sys.platform == "win32":
        try:
            class _MS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]
            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return int(m.ullAvailPhys)
        except (OSError, AttributeError):
            # Best-effort probe: OSError = DLL/function load failure, AttributeError
            # = missing windll attribute; both mean "cannot detect, use defaults".
            pass
    return None


def memory_available_gib():
    """Best-effort available RAM in GiB (rounded down), or None."""
    b = memory_available_bytes()
    return b // (1024 ** 3) if b else None


def disk_is_rotational(path):
    """True when the filesystem hosting `path` sits on a spinning disk.

    Resolves the block device for the path via st_dev major:minor and reads
    /sys/block/<dev>/queue/rotational.  Best effort only - returns None when
    undetectable (WSL, network mounts, exotic sysfs), and the caller treats
    None as "not rotational" (modern default).
    """
    if sys.platform != "linux":
        return None
    try:
        st = os.stat(path)
        major, minor = os.major(st.st_dev), os.minor(st.st_dev)
        dev = os.path.basename(os.readlink("/sys/dev/block/%d:%d" % (major, minor)))
        with open("/sys/block/%s/queue/rotational" % dev, encoding="ascii") as f:
            return f.read().strip() == "1"
    except OSError:
        return None


def _clamp(n, lo=1, hi=MAX_WORKERS):
    return max(lo, min(int(n), hi))


def _env_override(kind):
    """Env override (global GT_WORKERS, then per-kind). Returns None if unset."""
    for name in ("GT_WORKERS_%s" % kind.upper(), "GT_WORKERS"):
        raw = os.environ.get(name)
        if raw:
            try:
                return _clamp(int(raw))
            except ValueError:
                log.warning("ignoring invalid %s=%r (not an integer)", name, raw)
    return None


def _hdd_factor(hdd):
    """Worker cap multiplier for slow disks: 0.5 on HDD, 1.0 elsewhere."""
    return 0.5 if hdd else 1.0


def auto_workers(kind, path=None):
    """Recommended worker count for `kind` on the current machine (>= 1).

    `path` (optional) lets disk-type detection probe the filesystem that will
    actually be worked on; defaults to the current working directory.
    """
    override = _env_override(kind)
    if override is not None:
        return override
    cpus = cpu_count()
    hdd = disk_is_rotational(path or os.getcwd()) or False
    f = _hdd_factor(hdd)

    if kind == "copy":
        return _clamp(int((cpus * 2 + 2) * f), lo=2, hi=16)
    if kind in ("decrypt", "png", "clean"):
        return _clamp(cpus * f, lo=1, hi=12)
    if kind == "probe":
        return _clamp(int(cpus * 2 * f), lo=2, hi=12)
    if kind in ("encode", "decode"):
        # Each ffmpeg instance is a full process with its own threads and a
        # per-file memory footprint; parallel count is CPU- and RAM-bounded.
        n = cpus
        ram = memory_available_gib()
        if ram is not None:
            if ram < 4:
                n = 1
            elif ram < 8:
                n = min(n, 2)
            else:
                n = min(n, ram // 2)
        return _clamp(n * f, lo=1, hi=8)
    if kind == "compress":
        # 7z -mmt=N: zstd blocks also consume memory per thread.
        n = cpus
        ram = memory_available_gib()
        if ram is not None:
            n = min(n, max(1, ram // 2))
        return _clamp(n, lo=1, hi=8)
    return _clamp(cpus, lo=1, hi=MAX_WORKERS)


def resolve_workers(kind, explicit=None, path=None):
    """Workers for a step: explicit --workers value wins, else auto-tuned."""
    if explicit is not None and explicit > 0:
        return int(explicit)
    return auto_workers(kind, path=path)
