#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rpgmaker/logsetup.py - the single logging configuration.

The regression this guards: a module that configures logging at IMPORT time
rewrites the root logger for the whole process (a pytest session included),
and the later configuration in the real entry point becomes a silent no-op.
"""
import logging

import pytest

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


def test_ensure_utf8_streams_never_raises():
    # streams without reconfigure (test capture objects) must be ignored
    logsetup.ensure_utf8_streams()


def test_quiet_sets_warning():
    root, saved = _fresh_root()
    try:
        logsetup.setup(quiet=True)
        assert root.level == logging.WARNING
    finally:
        _restore(root, saved)


def test_verbose_wins_over_quiet():
    root, saved = _fresh_root()
    try:
        logsetup.setup(verbose=True, quiet=True)
        assert root.level == logging.DEBUG
    finally:
        _restore(root, saved)


class TestLevelResolution:
    def test_env_override_is_used(self, monkeypatch):
        monkeypatch.setenv(logsetup.LEVEL_ENV, "debug")
        assert logsetup.resolve_level() == logging.DEBUG

    def test_env_override_beats_the_flags(self, monkeypatch):
        monkeypatch.setenv(logsetup.LEVEL_ENV, "warning")
        assert logsetup.resolve_level(verbose=True) == logging.WARNING

    def test_explicit_level_beats_the_env(self, monkeypatch):
        monkeypatch.setenv(logsetup.LEVEL_ENV, "debug")
        assert logsetup.resolve_level(level=logging.ERROR) == logging.ERROR

    @pytest.mark.parametrize("raw", ["", "  ", "nonsense", "INFO "]) 
    def test_env_value_is_case_insensitive_or_ignored(self, monkeypatch, raw):
        monkeypatch.setenv(logsetup.LEVEL_ENV, raw)
        expected = logging.INFO if raw.strip().lower() == "info" else \
            logging.INFO
        assert logsetup.resolve_level() == expected

    def test_bogus_env_falls_back_to_info(self, monkeypatch):
        monkeypatch.setenv(logsetup.LEVEL_ENV, "nonsense")
        assert logsetup.resolve_level() == logging.INFO

    def test_no_flags_is_info(self, monkeypatch):
        monkeypatch.delenv(logsetup.LEVEL_ENV, raising=False)
        assert logsetup.resolve_level() == logging.INFO


class TestHandlers:
    def test_setup_twice_does_not_stack_handlers(self):
        root, saved = _fresh_root()
        try:
            logsetup.setup()
            first = list(root.handlers)
            logsetup.setup(verbose=True)
            assert len(root.handlers) == len(first) == 1
            assert first[0] not in root.handlers   # replaced, not stacked
            assert root.level == logging.DEBUG     # the second call still wins
        finally:
            _restore(root, saved)

    def test_foreign_handlers_are_preserved(self):
        """pytest's capture handler must keep receiving records."""
        root, saved = _fresh_root()
        foreign = logging.NullHandler()
        try:
            root.addHandler(foreign)
            logsetup.setup()
            assert foreign in root.handlers
        finally:
            _restore(root, saved)

    def test_log_file_receives_formatted_lines(self, tmp_path):
        root, saved = _fresh_root()
        path = tmp_path / "run" / "tool.log"
        try:
            logsetup.setup(log_file=path)
            logging.getLogger("probe").info("阶段：提取 中文名")
            logging.shutdown()
            text = path.read_text(encoding="utf-8")
        finally:
            _restore(root, saved)
        assert "probe" in text and "阶段：提取 中文名" in text
        assert "INFO" in text

    def test_a_second_setup_switches_the_log_file(self, tmp_path):
        root, saved = _fresh_root()
        first = tmp_path / "a.log"
        second = tmp_path / "b.log"
        try:
            logsetup.setup(log_file=first)
            logsetup.setup(log_file=second)
            logging.getLogger("probe").warning("second-run")
            logging.shutdown()
        finally:
            _restore(root, saved)
        assert "second-run" in second.read_text(encoding="utf-8")
        assert not first.exists() or "second-run" not in first.read_text(
            encoding="utf-8")


class TestPhase:
    def test_logs_start_and_done_with_elapsed_time(self, caplog):
        with caplog.at_level(logging.INFO, logger="phase"):
            with logsetup.phase("audio encode", logging.getLogger("phase")):
                pass
        text = caplog.text
        assert "audio encode: start" in text
        assert "audio encode: done in" in text
        assert ": start" in text and "s" in text

    def test_failure_is_logged_at_error_and_reraised(self, caplog):
        with caplog.at_level(logging.INFO, logger="phase"):
            with pytest.raises(ValueError):
                with logsetup.phase("pack", logging.getLogger("phase")):
                    raise ValueError("boom")
        assert "pack: FAILED" in caplog.text


class TestWarnOnce:
    def test_one_message_per_key(self, caplog):
        seen = set()
        log = logging.getLogger("probe")
        with caplog.at_level(logging.WARNING, logger="probe"):
            assert logsetup.warn_once(log, "k", "first %s", "a", seen=seen) \
                is True
            assert logsetup.warn_once(log, "k", "second", seen=seen) is False
        assert "first a" in caplog.text
        assert "second" not in caplog.text

    def test_distinct_keys_both_warn(self, caplog):
        seen = set()
        log = logging.getLogger("probe")
        with caplog.at_level(logging.WARNING, logger="probe"):
            logsetup.warn_once(log, "k1", "one", seen=seen)
            logsetup.warn_once(log, "k2", "two", seen=seen)
        assert "one" in caplog.text and "two" in caplog.text


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
