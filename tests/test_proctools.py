#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for rpgmaker/proctools.py - the shared external-process runner.

Focused on the four properties every call site depends on: a finite timeout,
UTF-8 decoding that cannot raise, a failure message that names the program and
its exit code, and an unchanged FileNotFoundError for a missing binary (the
resolver's install hint is the message the user must see).
"""
import subprocess
import sys

import pytest

from rpgmaker import proctools

PY = sys.executable


def test_returns_completed_process():
    proc = proctools.run([PY, "-c", "print('hello')"])
    assert proc.returncode == 0
    assert proc.stdout.strip() == "hello"


def test_utf8_output_is_decoded_not_mojibake():
    """The child prints CJK; the host locale codec (cp932/cp1252) used to
    raise UnicodeDecodeError here."""
    proc = proctools.run([PY, "-c",
                          "import sys; sys.stdout.write('日本語タイトル')"])
    assert proc.stdout == "日本語タイトル"


def test_unencodable_bytes_do_not_raise():
    # raw 0xff is invalid UTF-8: errors="replace" must swallow it
    proc = proctools.run([PY, "-c",
                          "import sys; sys.stdout.buffer.write(b'a\\xffb')"])
    assert proc.stdout.startswith("a")
    assert proc.stdout.endswith("b")


def test_surrogateescape_is_available_for_path_lists():
    proc = proctools.run([PY, "-c",
                          "import sys; sys.stdout.buffer.write(b'a\\xffb')"],
                         errors="surrogateescape")
    assert proc.stdout == "a\udcffb"


def test_nonzero_exit_raises_with_program_and_tail():
    with pytest.raises(RuntimeError) as ei:
        proctools.run([PY, "-c",
                       "import sys; sys.stderr.write('the real reason');"
                       "sys.exit(7)"], label="fake-tool")
    msg = str(ei.value)
    assert "fake-tool failed (exit 7)" in msg
    assert "the real reason" in msg


def test_check_false_returns_the_failure():
    proc = proctools.run([PY, "-c", "import sys; sys.exit(3)"], check=False)
    assert proc.returncode == 3


def test_timeout_is_finite():
    with pytest.raises(subprocess.TimeoutExpired):
        proctools.run([PY, "-c", "import time; time.sleep(30)"], timeout=0.5)


def test_missing_program_keeps_file_not_found():
    """config.find_*() raises FileNotFoundError with the install hint; the
    runner must not rewrap that into something else."""
    with pytest.raises(FileNotFoundError):
        proctools.run(["definitely-not-a-real-program-xyz"])


def test_never_uses_a_shell():
    """A shell would reinterpret the '*' and fail; list form passes it through."""
    proc = proctools.run([PY, "-c", "import sys; print(sys.argv[1])", "*.py"])
    assert proc.stdout.strip() == "*.py"


def test_tail_prefers_stderr_then_stdout():
    err = subprocess.CompletedProcess(["x"], 1, stdout="out", stderr="boom")
    assert proctools.tail(err) == "boom"
    only_out = subprocess.CompletedProcess(["x"], 1, stdout="out", stderr="")
    assert proctools.tail(only_out) == "out"


def test_tail_is_capped():
    big = subprocess.CompletedProcess(["x"], 1, stdout="", stderr="x" * 5000)
    assert len(proctools.tail(big, limit=100)) == 100


def test_argv_text_is_readable():
    assert proctools.argv_text([PY, "-c", "hello world"]) == \
        "%s -c hello world" % PY
