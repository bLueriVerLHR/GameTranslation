#!/usr/bin/env python3
"""logsetup.py - the one logging configuration used by every entry point.

Before this module every tool called ``logging.basicConfig`` itself: 24 of
them, with four different formats (two dropped the level name entirely), four
of them at IMPORT time - which rewrote the root logger for the whole process
(an entire pytest session included) and silently turned a later call into a
no-op - and no timestamps anywhere.

Policy (AGENTS.md "调试与日志"):

  * INFO = stages and results, DEBUG = per-file/per-key diagnosis
  * ``-v`` / ``--verbose`` turns DEBUG on, ``-q`` / ``--quiet`` keeps only
    warnings and errors
  * ``GT_LOG_LEVEL`` (debug/info/warning/error) overrides the flags for one
    process, so a long batch run can be re-run with DEBUG without editing the
    command line
  * ``--log-file`` tees the same lines into a file (a multi-hour batch should
    leave a log behind)
  * one format, with a timestamp, so tool output can be correlated with the
    HTTP server's request log during a play-test
  * ``setup()`` is called from ``main()`` only.  Never at import time: a
    module that configures logging on import changes the behaviour of
    anything that imports it (pytest sessions included).

Every module can use this, including the ones that are runnable from their
own directory (``python3 kirikiri/xp3tool.py list game.xp3``): they append the
repo root to ``sys.path`` (append, not insert, so a same-named sibling module
in their own directory still wins) before importing this module.
"""
import contextlib
import logging
import os
import sys
import time

# Timestamp + level + logger name.  A short time-only stamp keeps lines
# readable while still allowing correlation with the server log.
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%H:%M:%S"

#: Environment override for the level, e.g. ``GT_LOG_LEVEL=debug``.
LEVEL_ENV = "GT_LOG_LEVEL"

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

# Handlers this module installed, so a second setup() in the same process
# replaces them instead of stacking duplicates (tools called from tests).
_owned: list[logging.Handler] = []

# Keys already warned about (warn_once): one message per key per process.
_seen_warnings: set[str] = set()


def ensure_utf8_streams():
    """Best-effort: decode/encode console output as UTF-8 with ``replace``.

    Tool output routinely contains CJK (game event names, kana QC hits).  On
    Windows a redirected stdout/stderr uses the locale codec, so those lines
    raised UnicodeEncodeError and killed the tool at the moment it was
    reporting a problem.  Never fatal: streams without ``reconfigure`` (test
    capture objects) are left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # detached / closed / already-wrapped stream: nothing to do
        with contextlib.suppress(ValueError, OSError, LookupError):
            reconfigure(encoding="utf-8", errors="replace")


def level_from_env(env=None):
    """Level named by ``GT_LOG_LEVEL``, or None when unset/unrecognised."""
    raw = (os.environ.get(LEVEL_ENV) if env is None else env) or ""
    return _LEVELS.get(raw.strip().lower())


def resolve_level(verbose=False, quiet=False, level=None):
    """The level one run should use.

    Precedence: explicit ``level`` > ``GT_LOG_LEVEL`` > ``--verbose`` >
    ``--quiet`` > INFO.  (Verbose beats quiet when both are given: a run that
    asks for detail gets detail.)
    """
    if level is not None:
        return level
    from_env = level_from_env()
    if from_env is not None:
        return from_env
    if verbose:
        return logging.DEBUG
    if quiet:
        return logging.WARNING
    return logging.INFO


def setup(verbose=False, quiet=False, level=None, log_file=None):
    """Configure root logging for one CLI run (call from ``main()``).

    Replaces the handlers this module installed before (never touching other
    handlers, e.g. pytest's capture handler, which must keep seeing records).
    Returns the root logger.
    """
    ensure_utf8_streams()
    root = logging.getLogger()
    for handler in _owned:
        root.removeHandler(handler)
        handler.close()
    _owned.clear()

    formatter = logging.Formatter(FORMAT, DATEFMT)
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        parent = os.path.dirname(os.path.abspath(str(log_file)))
        if parent:
            os.makedirs(parent, exist_ok=True)
        handlers.append(logging.FileHandler(str(log_file), encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
        _owned.append(handler)
    root.setLevel(resolve_level(verbose=verbose, quiet=quiet, level=level))
    return root


@contextlib.contextmanager
def phase(name, logger=None, level=logging.INFO):
    """Time one pipeline stage and log its start/end (AGENTS 采样测性能).

    The elapsed time is logged at INFO so a batch run reports where the time
    went without extra instrumentation:

        with logsetup.phase("audio encode", log):
            ...
    """
    log = logger or logging.getLogger("phase")
    started = time.perf_counter()
    log.log(level, "%s: start", name)
    try:
        yield
    except BaseException:
        log.error("%s: FAILED after %.1fs", name, time.perf_counter() - started)
        raise
    log.log(level, "%s: done in %.1fs", name, time.perf_counter() - started)


def warn_once(logger, key, message, *args, seen=None):
    """Log `message` at WARNING once per process per `key`; True if emitted.

    For conditions that repeat on every file/entry (e.g. "no override for
    tool X, using default") and would otherwise flood the log.  Pass `seen`
    to keep the marks somewhere else, so a caller (or a test) can reset its
    own once-per-process marks without touching everyone else's.
    """
    store = _seen_warnings if seen is None else seen
    if key in store:
        return False
    store.add(key)
    logger.warning(message, *args)
    return True
