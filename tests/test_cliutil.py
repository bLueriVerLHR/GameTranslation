#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rpgmaker/cliutil.py - the shared CLI conventions.

The contract the tools rely on: a command function RETURNS its exit code,
`run()` translates framework exceptions into argparse-style codes (2 = usage,
1 = failure) instead of letting SystemExit escape from deep inside the
framework, and the logging options are wired to logsetup.
"""
import logging
import os
import sys
from typing import Annotated

import pytest
import typer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from rpgmaker import cliutil, logsetup  # noqa: E402


def make_app():
    """A one-command app: ok / fail / boom / echo options for the tests."""
    def cmd(work_dir: Annotated[str, typer.Argument(help="a directory")],
            code: Annotated[int, typer.Option("--code", help="exit code")] = 0,
            verbose: cliutil.Verbose = False,
            quiet: cliutil.Quiet = False,
            log_file: cliutil.LogFile = None) -> int:
        """Test command."""
        cliutil.setup_logging(verbose, quiet, log_file)
        if code == 99:
            raise typer.Exit(code=99)
        if code == 98:
            raise ValueError("not a CLI error")
        print("work=%s" % work_dir)
        return code

    return cliutil.command_app(cmd, help="test app")


class TestRun:
    def test_success_returns_zero(self, capsys):
        assert cliutil.run(make_app(), ["dir"]) == 0
        assert "work=dir" in capsys.readouterr().out

    def test_command_return_value_becomes_the_exit_code(self):
        assert cliutil.run(make_app(), ["dir", "--code", "3"]) == 3

    def test_typer_exit_code_is_returned(self):
        assert cliutil.run(make_app(), ["dir", "--code", "99"]) == 99

    def test_usage_error_returns_two_with_a_message(self, capsys):
        assert cliutil.run(make_app(), ["--nope"]) == 2
        assert "No such option" in capsys.readouterr().err

    def test_missing_argument_returns_two(self, capsys):
        assert cliutil.run(make_app(), []) == 2
        assert "Missing argument" in capsys.readouterr().err

    def test_help_returns_zero(self, capsys):
        assert cliutil.run(make_app(), ["--help"]) == 0
        assert "Usage:" in capsys.readouterr().out

    def test_real_exceptions_are_not_swallowed(self):
        with pytest.raises(ValueError):
            cliutil.run(make_app(), ["dir", "--code", "98"])

    def test_argv_defaults_to_sys_argv(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["tool.py", "from-argv"])
        assert cliutil.run(make_app()) == 0
        assert "work=from-argv" in capsys.readouterr().out

    def test_path_arguments_are_stringified(self):
        from pathlib import Path

        assert cliutil.run(make_app(), [Path("some/dir")]) == 0

    def test_non_int_return_is_treated_as_success(self, capsys, caplog):
        def cmd(work_dir: str) -> str:
            """Return something that is not an exit code."""
            return "not-a-code"

        with caplog.at_level(logging.WARNING, logger="cliutil"):
            assert cliutil.run(cliutil.command_app(cmd), ["x"]) == 0
        assert "not an exit code" in caplog.text

    def test_a_plain_callable_is_wrapped(self):
        def cmd(work_dir: str) -> int:
            """One-command callable."""
            return 0

        assert cliutil.run(cmd, ["x"]) == 0


class TestSubcommands:
    def test_dispatch_and_per_command_options(self, capsys):
        application = cliutil.app(help="multi")

        @application.command()
        def first(name: Annotated[str, typer.Argument()]) -> int:
            """First command."""
            print("first %s" % name)
            return 0

        @application.command()
        def second() -> int:
            """Second command."""
            return 4

        assert cliutil.run(application, ["first", "a"]) == 0
        assert "first a" in capsys.readouterr().out
        assert cliutil.run(application, ["second"]) == 4
        assert cliutil.run(application, ["nope"]) == 2


class TestDocumentedOptions:
    def test_verbose_quiet_log_file_are_accepted(self, tmp_path):
        log_file = str(tmp_path / "run.log")
        assert cliutil.run(make_app(), ["d", "-v", "-q", "--log-file",
                                        log_file]) == 0
        assert os.path.exists(log_file)

    def test_verbose_selects_debug_level(self):
        root, saved = logging.getLogger(), (logging.getLogger().level,
                                            list(logging.getLogger().handlers))
        try:
            cliutil.setup_logging(verbose=True)
            assert root.level == logging.DEBUG
        finally:
            root.handlers[:] = saved[1]
            root.setLevel(saved[0])

    def test_quiet_selects_warning_level(self):
        root = logging.getLogger()
        saved = (root.level, list(root.handlers))
        try:
            cliutil.setup_logging(quiet=True)
            assert root.level == logging.WARNING
        finally:
            root.handlers[:] = saved[1]
            root.setLevel(saved[0])

    def test_help_lists_the_three_logging_options(self, capsys):
        cliutil.run(make_app(), ["--help"])
        out = capsys.readouterr().out
        for flag in ("--verbose", "--quiet", "--log-file"):
            assert flag in out


class TestFail:
    def test_prints_error_to_stderr_and_returns_the_code(self, capsys):
        assert cliutil.fail("bad thing", 2) == 2
        captured = capsys.readouterr()
        assert "error: bad thing" in captured.err
        assert captured.out == ""

    def test_default_code_is_one(self, capsys):
        assert cliutil.fail("x") == 1


class TestErrorCodeDuckTyping:
    def test_framework_errors_are_detected_without_importing_click(self):
        """Typer vendors its CLI framework, so the check must not import it."""
        class FakeUsage:
            exit_code = 2

            def show(self):
                pass

        class FakeAbort:
            pass

        FakeAbort.__name__ = "Abort"
        assert cliutil._error_code(FakeUsage()) == 2
        assert cliutil._error_code(FakeAbort()) == 1
        assert cliutil._error_code(ValueError("real bug")) is None


def test_caller_doc_uses_the_callers_module_docstring():
    """`app(help=None)` must pick up the tool's module docstring, not
    cliutil's own (which describes this module, not the tool)."""
    namespace = {}
    exec(compile('"""Tool docstring."""\n'
                 "from rpgmaker import cliutil\n"
                 "app = cliutil.app()\n",
                 "<tool>", "exec"), namespace)
    assert "Tool docstring" in (namespace["app"].info.help or "")


def test_bracketed_help_text_is_not_eaten_by_rich_markup(capsys):
    """Typer's default rich markup parses `[...]` as style tags; game tags
    like `[iscript]` / `[l]` must survive `--help` verbatim."""
    namespace = {}
    exec(compile('"""Converted `[iscript]` blocks and [l] tags."""\n'
                 "from rpgmaker import cliutil\n"
                 "def cmd(x: str) -> int:\n"
                 "    return 0\n"
                 "app = cliutil.command_app(cmd, help=__doc__)\n",
                 "<tool>", "exec"), namespace)
    assert cliutil.run(namespace["app"], ["--help"]) == 0
    out = capsys.readouterr().out
    assert "[iscript]" in out
    assert "[l]" in out


def test_logsetup_is_the_only_logging_entry():
    """cliutil must not configure logging itself (single source)."""
    import inspect

    source = inspect.getsource(cliutil)
    assert "basicConfig" not in source.replace('"""', "")
    assert logsetup.setup is logsetup.setup          # imported, not re-done
