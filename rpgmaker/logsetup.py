#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logsetup.py - the one logging configuration used by the entry points.

Before this module every tool called ``logging.basicConfig`` itself: 24 of
them, with four different formats (two dropped the level name entirely), four
of them at IMPORT time - which rewrote the root logger for the whole process
(an entire pytest session included) and silently turned a later call into a
no-op - and no timestamps anywhere.

Policy (AGENTS.md "调试与日志"):

  * INFO = stages and results, DEBUG = per-file/per-key diagnosis
  * ``-v`` / ``--verbose`` turns DEBUG on for that run
  * one format, with a timestamp, so tool output can be correlated with the
    HTTP server's request log during a play-test

Modules that are also runnable directly from their own directory (e.g.
``python3 kirikiri/xp3tool.py list game.xp3``) must NOT import this module:
``rpgmaker`` is not on ``sys.path`` in that case, and adding another
``sys.path`` insert would make that worse.  Those keep a two-line local call.
"""
import logging
import sys

# Timestamp + level + logger name.  A short time-only stamp keeps lines
# readable while still allowing correlation with the server log.
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%H:%M:%S"


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
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError, LookupError):
            # detached / closed / already-wrapped stream: nothing to do
            pass


def setup(verbose=False, level=None):
    """Configure root logging for one CLI run (idempotent, call from main()).

    Never call this at import time: a module that configures logging on
    import changes the behaviour of anything that imports it.
    """
    ensure_utf8_streams()
    logging.basicConfig(
        level=level if level is not None else (
            logging.DEBUG if verbose else logging.INFO),
        format=FORMAT, datefmt=DATEFMT)


def add_verbose(parser):
    """Add the standard ``-v/--verbose`` flag to an ArgumentParser."""
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="DEBUG diagnostics (per-file detail)")
    return parser
