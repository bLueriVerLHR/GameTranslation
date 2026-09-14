#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cliutil.py - the shared CLI conventions for every tool.

Every tool used to build its own ``argparse.ArgumentParser`` (53 files, 223
``add_argument`` calls) with its own hand-written help, its own ``--verbose``
wiring and its own exit-code handling.  This module is the single place those
conventions live, on top of Typer (the same framework the two pipeline entry
points use):

  * ``Verbose`` / ``Quiet`` / ``LogFile`` - reusable annotated options, so
    ``-v`` (DEBUG), ``-q`` (warnings only) and ``--log-file`` work identically
    everywhere, wired to :func:`setup_logging`.
  * ``app()`` / ``command_app()`` - build a Typer app with the toolkit's
    conventions (no shell completion, help from the module docstring).
  * ``run()`` - execute an app and **return** its exit code, so a tool's
    ``main(argv=None)`` stays testable and callable: success returns 0,
    failures come back as argparse-style codes (2 = usage, 1 = failure)
    instead of raising ``SystemExit`` from deep inside the framework.

Tool template (keep the CLI strings identical to the argparse version - the
docs and the owner's habits depend on them)::

    import typer
    from typing import Annotated
    from rpgmaker import cliutil

    def cmd(work_dir: Annotated[str, typer.Argument(help="translation work dir")],
            window: Annotated[int, typer.Option("--window", help="context lines")] = 1,
            verbose: cliutil.Verbose = False,
            quiet: cliutil.Quiet = False,
            log_file: cliutil.LogFile = None) -> int:
        \"\"\"One line about what the command does.\"\"\"
        cliutil.setup_logging(verbose, quiet, log_file)
        ...
        return 0

    app = cliutil.command_app(cmd, help=__doc__)

    def main(argv=None) -> int:
        return cliutil.run(app, argv, prog="tool_name.py")

    if __name__ == "__main__":
        raise SystemExit(main())

Sub-commands (``list`` / ``extract`` / ``repack``) use one decorated function
per command::

    app = cliutil.app(help=__doc__)

    @app.command()
    def list_(xp3: Annotated[str, typer.Argument(help="archive")]) -> int:
        ...

Do not use ``typer.run()`` (it cannot take an argv), and do not call
``sys.exit()`` inside a command: return the code, or ``raise typer.Exit(code)``
for a failure raised deep inside a helper.
"""
import logging
import os
import sys
from typing import Annotated, Optional

import typer

from . import logsetup

__all__ = ["app", "command_app", "run", "setup_logging", "fail",
           "Verbose", "Quiet", "LogFile", "Argument", "Option"]

#: ``-v`` / ``--verbose``: DEBUG diagnostics (per-file detail).
Verbose = Annotated[bool, typer.Option(
    "-v", "--verbose", help="DEBUG diagnostics (per-file detail)")]

#: ``-q`` / ``--quiet``: warnings and errors only (batch runs).
Quiet = Annotated[bool, typer.Option(
    "-q", "--quiet", help="only warnings and errors (batch runs)")]

#: ``--log-file PATH``: tee the log into a UTF-8 file as well.
LogFile = Annotated[Optional[str], typer.Option(
    "--log-file", metavar="PATH", help="also write the log to PATH (UTF-8)")]

# Re-exported so a tool needs one import for its type annotations.
Argument = typer.Argument
Option = typer.Option


def setup_logging(verbose=False, quiet=False, log_file=None):
    """Configure logging for one command run (single entry point: logsetup)."""
    return logsetup.setup(verbose=verbose, quiet=quiet, log_file=log_file)


def app(help=None, no_args_is_help=True):
    """A Typer app with the toolkit's conventions.

    ``help`` defaults to the module docstring of the caller; shell completion
    stays off because these tools are run by hand or from the pipeline.

    ``rich_markup_mode=None`` is deliberate: the default (``"rich"``) parses
    square brackets in help text as style tags, so a tool documenting
    ``[iscript]`` blocks or ``[l]`` line tags would print them mangled.
    """
    if help is None:
        help = _caller_doc()
    return typer.Typer(help=help, no_args_is_help=no_args_is_help,
                       add_completion=False, rich_markup_mode=None)


def command_app(fn, help=None):
    """A one-command app wrapping `fn` (the common case for a tool).

    The text is attached to the *command* as well as to the app: for a single
    command Typer renders the command's own docstring, so without this the
    tool's module docstring would only show up for multi-command apps.
    """
    text = help if help is not None else fn.__doc__
    if text and not fn.__doc__:
        fn.__doc__ = text
    application = app(help=text)
    application.command()(fn)
    return application


def fail(message, code=1):
    """Print ``error: <message>`` to stderr and return the exit code.

    For the tools whose failure path used to be ``print(...); sys.exit(code)``:
    ``return cliutil.fail("...", 2)`` keeps the message on stderr and the code
    flowing back through ``run()``.
    """
    print("error: %s" % message, file=sys.stderr)
    return code


def run(target, argv=None, prog=None):
    """Execute a Typer app and return its exit code (never raises).

    ``argv`` defaults to ``sys.argv[1:]``; pass a list to drive the tool
    programmatically (tests, wrappers).  Usage errors print their message and
    return 2, a failed command returns its own code, and ``--help`` returns 0.
    """
    application = target
    if not isinstance(application, typer.Typer):
        application = command_app(target)
    if argv is None:
        args = list(sys.argv[1:])
    else:
        args = [str(a) for a in argv]
    if prog is None:
        prog = os.path.basename(sys.argv[0]) or "tool"
    try:
        result = application(args=args, prog_name=prog, standalone_mode=False)
    except BaseException as exc:          # noqa: BLE001 - re-raised below
        code = _error_code(exc)
        if code is None:
            raise                         # a real bug, not a CLI error
        shower = getattr(exc, "show", None)
        if callable(shower):
            # Unknown option / missing argument / bad value: the framework's
            # own message, same shape as argparse (stderr + exit 2/1).
            shower()
        else:
            print("aborted", file=sys.stderr)
        return code
    if result is None:
        return 0
    if isinstance(result, int):
        return result
    log = logging.getLogger("cliutil")
    log.warning("command %r returned %r, which is not an exit code; "
                "treating it as success", prog, result)
    return 0


def _error_code(exc):
    """Exit code for a framework-level CLI error, else None.

    Duck-typed on purpose: Typer vendors its CLI framework (``typer._click``),
    so importing those exception classes here would bind this module to a
    private path that moved between Typer versions.  A CLI error carries both
    ``show()`` and an integer ``exit_code`` (usage errors are 2); ``Abort``
    (Ctrl-C) has no message but is 1.
    """
    if callable(getattr(exc, "show", None)) \
            and isinstance(getattr(exc, "exit_code", None), int):
        return exc.exit_code
    if exc.__class__.__name__ == "Abort":
        return 1
    return None


def _caller_doc():
    """Docstring of the module that called app() (its __doc__ is the help)."""
    frame = sys._getframe(1)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        if not module.startswith("rpgmaker"):
            return frame.f_globals.get("__doc__")
        frame = frame.f_back
    return None
