#!/usr/bin/env python3
"""Environment-aware resource tuning for the toolkit.

Every step that runs parallel work asks `resolve_workers(kind, explicit)` for
its worker count.  Instead of a hardcoded default per step, the count is
derived from the machine the pipeline is actually running on:

  - **physical core count**: hyperthreads do not help the CPU-bound steps and
    every extra worker costs memory (measured on 16C/32T: encoding 381 audio
    files took 11.2 s with 16 workers, and no less with 32).  Probed per
    platform by `physical_cpu_count()`, which falls back to the logical count
    when the topology cannot be read.
  - available memory (Linux /proc/meminfo, Windows GlobalMemoryStatusEx)
  - disk type: rotational (HDD) disks get conservative caps, since many
    parallel readers/writers thrash a spinning disk far worse than an SSD

Every cap below is *derived* from that core count instead of being an
absolute constant, so a machine with more cores gets a proportionally larger
default without a code change.

Kinds are tuned for the bottleneck of the step:

  copy      I/O-bound tree copy (build)           -> cores*2+2, hdd capped
  decrypt   I/O-bound byte XOR (decrypt)          -> cores, hdd capped
  clean     I/O-bound corpus scan (clean)         -> cores, hdd capped
  png       I/O-bound header reads (verify)       -> cores, hdd capped
  qc        in-process text scan (chunk QC)       -> cores, hdd capped
  probe     in-process PyAV demux (audio probe)   -> cores*2, hdd capped
  encode    CPU-heavy ffmpeg subprocess (encode)  -> cores, memory-aware
  decode    in-process PyAV decode (verify)       -> cores, memory-aware
  tlg       in-process TLG/PIL decode (KAG assets) -> cores, memory-aware
  video     VP9 WebM encode (movie transcode)      -> cores/2, memory-aware
  compress  py7zr threads (compress)               -> cores, memory-aware

Explicit `--workers N` always wins.  Env overrides:

  GT_WORKERS=<n>          global override for every kind
  GT_WORKERS_<KIND>=<n>   per-kind override (uppercased kind, e.g.
                          GT_WORKERS_ENCODE=2)

All numbers are clamped to >= 1 (and to `worker_ceiling()` when they come
from the environment, so a typo cannot spawn 10000 workers).
"""
import ctypes
import logging
import os
import struct
import sys
from ctypes import wintypes

log = logging.getLogger("rpgmaker.runtime")

#: Floor for `worker_ceiling()`: the ceiling itself is derived from the core
#: count, so this only matters on very small machines.
MAX_WORKERS = 32

#: Memoized result of `physical_cpu_count()` (None = not probed yet).
_PHYSICAL_CORES = None


def cpu_count():
    """Usable *logical* CPUs (SMT threads included), >= 1."""
    return os.cpu_count() or 4


def _physical_windows():
    """Physical cores via GetLogicalProcessorInformationEx, or None.

    Each returned entry is `DWORD Relationship, DWORD Size, <union>`;
    `RelationProcessorCore` (0) entries are physical cores, and their Flag
    group lists the SMT threads belonging to them.
    """
    try:
        # getattr, not ``ctypes.windll``: the attribute is typed only on
        # Windows, so spelling it directly makes the recorded error budget
        # platform-dependent (measured: 189 errors on Linux CI against 188 on
        # Windows for the same tree, the difference being this one line).
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        kernel32 = windll.kernel32
        length = wintypes.DWORD(0)
        kernel32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(length))
        if not length.value:
            return None
        buf = ctypes.create_string_buffer(length.value)
        if not kernel32.GetLogicalProcessorInformationEx(0, buf,
                                                         ctypes.byref(length)):
            return None
        data = buf.raw[:length.value]
    except (OSError, AttributeError):
        # OSError = DLL/function load failure, AttributeError = no windll
        # (non-Windows Python pretending): both mean "probe unavailable".
        return None
    count = 0
    offset = 0
    while offset + 8 <= len(data):
        relationship, size = struct.unpack_from("<II", data, offset)
        if size < 8:
            return None
        if relationship == 0:
            count += 1
        offset += size
    return count or None


def _physical_linux_cpuinfo(text):
    """Physical cores from /proc/cpuinfo content, or None.

    Counts distinct (physical id, core id) pairs.  `physical id` is absent on
    single-socket, containerised and ARM systems; a missing socket is treated
    as socket "0" so the core ids still add up.
    """
    pairs = set()
    phys = core = None

    def flush():
        if core is not None:
            pairs.add((phys if phys is not None else "0", core))

    for line in text.splitlines():
        if not line.strip():
            flush()
            phys = core = None
            continue
        if line.startswith("physical id"):
            phys = line.split(":", 1)[1].strip()
        elif line.startswith("core id"):
            core = line.split(":", 1)[1].strip()
    flush()
    return len(pairs) or None


def _physical_linux_sysfs(base="/sys/devices/system/cpu"):
    """Physical cores from sysfs topology, or None.

    Every SMT thread of one core shares its `thread_siblings_list`, so the
    number of distinct lists is the core count.  This is the fallback for
    kernels/containers that hide `physical id` from /proc/cpuinfo.
    """
    groups = set()
    try:
        names = os.listdir(base)
    except OSError:
        return None
    for name in names:
        if not name.startswith("cpu") or not name[3:].isdigit():
            continue
        siblings = os.path.join(base, name, "topology", "thread_siblings_list")
        try:
            with open(siblings, encoding="ascii") as f:
                groups.add(f.read().strip())
        except OSError:
            continue
    return len(groups) or None


def physical_cpu_count():
    """Physical cores on this machine (best effort), >= 1.

    Memoized: every step asks for it, and on Linux the fallback chain touches
    /proc and sysfs.  Falls back to the logical count when the platform
    topology cannot be read, so this is never worse than what it replaces.
    """
    global _PHYSICAL_CORES
    if _PHYSICAL_CORES is None:
        probed = None
        if sys.platform == "win32":
            probed = _physical_windows()
        elif sys.platform.startswith("linux"):
            try:
                with open("/proc/cpuinfo", encoding="ascii",
                          errors="replace") as f:
                    probed = _physical_linux_cpuinfo(f.read())
            except OSError:
                probed = None
            probed = probed or _physical_linux_sysfs()
        logical = cpu_count()
        if probed and 1 <= probed <= logical:
            _PHYSICAL_CORES = probed
            if probed != logical:
                log.debug("physical cores: %d (logical %d)", probed, logical)
        else:
            _PHYSICAL_CORES = logical
    return _PHYSICAL_CORES


def worker_ceiling():
    """Hard upper bound for any worker count (sanity ceiling).

    Derived from the machine rather than fixed, and wide enough not to clip
    the most oversubscribing kind (`copy`/`probe` allow `cores * 4`);
    `MAX_WORKERS` is only the floor for very small machines.
    """
    return max(MAX_WORKERS, physical_cpu_count() * 4)


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
    if sys.platform != "linux" or not hasattr(os, "major"):
        return None
    try:
        st = os.stat(path)
        major, minor = os.major(st.st_dev), os.minor(st.st_dev)
        dev = os.path.basename(os.readlink("/sys/dev/block/%d:%d" % (major, minor)))
        with open(f"/sys/block/{dev}/queue/rotational", encoding="ascii") as f:
            return f.read().strip() == "1"
    except OSError:
        return None


def _clamp(n, lo=1, hi=MAX_WORKERS):
    return max(lo, min(int(n), hi))


def _env_override(kind):
    """Env override (global GT_WORKERS, then per-kind). Returns None if unset."""
    for name in (f"GT_WORKERS_{kind.upper()}", "GT_WORKERS"):
        raw = os.environ.get(name)
        if raw:
            try:
                return _clamp(int(raw), hi=worker_ceiling())
            except ValueError:
                log.warning("ignoring invalid %s=%r (not an integer)", name, raw)
    return None


def _hdd_factor(hdd):
    """Worker cap multiplier for slow disks: 0.5 on HDD, 1.0 elsewhere."""
    return 0.5 if hdd else 1.0


def _ram_bounded(n, per_worker_mb):
    """Truncate `n` so that many workers still fit in the available RAM.

    The core count *is* the default; RAM only lowers it when a worker's
    footprint would not fit, so a machine with 16 cores and plenty of memory
    gets 16 workers (this used to cap at `ram // 2`, which was a correction
    for the old logical-core base and halved the count unnecessarily).

    Per-worker estimates are deliberately coarse (measured: an
    ffmpeg+Vorbis process sits around 50 MB; an in-process PyAV/PIL decode
    holds one frame plus parser buffers).
    """
    avail = memory_available_bytes()
    if not avail:
        return n
    fits = int(avail // (per_worker_mb * 1024 * 1024))
    return max(1, min(n, fits))


def auto_workers(kind, path=None):
    """Recommended worker count for `kind` on the current machine (>= 1).

    The base is the *physical* core count (see `physical_cpu_count`); the
    per-kind caps are multiples of it, so no absolute limit can silently
    under-use a larger machine.

    `path` (optional) lets disk-type detection probe the filesystem that will
    actually be worked on; defaults to the current working directory.
    """
    override = _env_override(kind)
    if override is not None:
        return override
    cores = physical_cpu_count()
    hdd = disk_is_rotational(path or os.getcwd()) or False
    f = _hdd_factor(hdd)

    if kind == "copy":
        # I/O-bound: oversubscribing the cores keeps the queue full while
        # workers wait on the filesystem.
        return _clamp(int((cores * 2 + 2) * f), lo=2, hi=cores * 4)
    if kind in ("decrypt", "png", "clean", "qc"):
        return _clamp(cores * f, lo=1, hi=cores * 2)
    if kind == "probe":
        return _clamp(int(cores * 2 * f), lo=2, hi=cores * 4)
    if kind in ("encode", "decode", "tlg"):
        # Each worker is a whole process (ffmpeg) or holds a decoded frame
        # (PyAV, TLG); RAM only truncates when the count would not fit.  The
        # HDD factor still applies: these steps read many files.
        per_worker = 256 if kind == "encode" else 128
        return _clamp(int(_ram_bounded(cores, per_worker) * f), lo=1, hi=cores)
    if kind == "compress":
        # 7z -mmt=N: zstd blocks also consume memory per thread.
        return _clamp(_ram_bounded(cores, 256), lo=1, hi=cores)
    if kind == "video":
        # Each VP9 encoder is a whole process *and* multi-threaded internally
        # (libvpx defaults to one thread per core), so running one job per core
        # would oversubscribe badly.  Half the cores is a conservative default;
        # `--jobs N` overrides it.
        return _clamp(_ram_bounded(max(1, cores // 2), 512), lo=1, hi=cores)
    return _clamp(cores, lo=1, hi=worker_ceiling())


def resolve_workers(kind, explicit=None, path=None):
    """Workers for a step: explicit --workers value wins, else auto-tuned."""
    if explicit is not None and explicit > 0:
        return int(explicit)
    return auto_workers(kind, path=path)
