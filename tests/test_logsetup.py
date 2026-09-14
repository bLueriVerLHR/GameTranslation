#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rpgmaker/logsetup.py - the single logging configuration.

The regression this guards: a module that configures logging at IMPORT time
rewrites the root logger for the whole process (a pytest session included),
and the later configuration in the real entry point becomes a silent no-op.
"""
import argparse
import logging

from rpgmaker import logsetup


def _fresh_root():
    """A clean root logger, so basicConfig actually applies (pytest installs
    its own handler/level, which would make the assertions meaningless)."""
    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    return root, saved


def _restore(root, saved):
    root.handlers[:] = saved[1]
    root.setLevel(saved[0])


def test_setup_installs_a_handler_and_honours_verbose():
    root, saved = _fresh_root()
    try:
        logsetup.setup(verbose=False)
        assert root.handlers, "setup() must install a handler"
        assert root.level == logging.INFO
    finally:
        _restore(root, saved)


def test_verbose_sets_debug():
    root, saved = _fresh_root()
    try:
        logsetup.setup(verbose=True)
        assert root.level == logging.DEBUG
    finally:
        _restore(root, saved)


def test_explicit_level_wins_over_verbose():
    root, saved = _fresh_root()
    try:
        logsetup.setup(verbose=True, level=logging.ERROR)
        assert root.level == logging.ERROR
    finally:
        _restore(root, saved)


def test_format_carries_level_and_name():
    # the format must never drop the level name (two tools used "%(message)s")
    assert "%(levelname)" in logsetup.FORMAT
    assert "%(name)s" in logsetup.FORMAT
    assert "%(asctime)s" in logsetup.FORMAT


def test_add_verbose_registers_the_standard_flag():
    ap = argparse.ArgumentParser()
    logsetup.add_verbose(ap)
    assert ap.parse_args([]).verbose is False
    assert ap.parse_args(["-v"]).verbose is True
    assert ap.parse_args(["--verbose"]).verbose is True


def test_ensure_utf8_streams_never_raises():
    # streams without reconfigure (test capture objects) must be ignored
    logsetup.ensure_utf8_streams()


def test_entry_points_do_not_configure_logging_at_import():
    """Importing an entry point must not change global logging.

    The historical bug: tools/bake_translation.py and
    tools/harvest_translation.py called basicConfig at module level.
    """
    import pathlib
    import re

    repo = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for rel in ("pipeline.py", "tyrano/pipeline.py", "tools/bake_translation.py",
                "tools/harvest_translation.py"):
        text = (repo / rel).read_text(encoding="utf-8")
        # module-level (column 0) basicConfig == import-time side effect
        if re.search(r"^logging\.basicConfig\(", text, re.M):
            offenders.append(rel)
    assert offenders == []
