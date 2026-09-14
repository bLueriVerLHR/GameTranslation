#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the serve commands' bind host (both pipelines).

The owner plays from another device over the LAN (an AGENTS requirement), and
a loopback-only server is unreachable there.  The host used to be hardcoded to
127.0.0.1, so --host has to be plumbed all the way to the HTTP server.

Both pipelines now share one implementation (`rpgmaker.cli._serve`), so the
plumbing is asserted once, through the Typer command functions (calling a
Typer-decorated function directly passes Python values through).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from rpgmaker import cli  # noqa: E402


def test_smoke_test_receives_the_host(monkeypatch):
    seen = {}

    def fake_smoke(folder, port=0, host="127.0.0.1"):
        seen["smoke"] = host
        return {}, True

    monkeypatch.setattr(cli.serve_mod, "smoke_test", fake_smoke)
    cli.cmd_tyrano_serve("x", 1, "0.0.0.0", True)
    assert seen["smoke"] == "0.0.0.0"


def _capture_serve(monkeypatch):
    seen = {}

    def fake_serve(folder, port=0, host="127.0.0.1", **kw):
        seen["start"] = host
        return True

    monkeypatch.setattr(cli.serve_mod, "serve", fake_serve)
    # the RPG Maker command detects a web root first; skip that here so the
    # test is about host plumbing only
    monkeypatch.setattr(cli, "resolve_web_root", lambda game: game)
    return seen


def test_plain_serve_passes_the_host_to_the_http_server(monkeypatch):
    seen = _capture_serve(monkeypatch)
    cli.cmd_serve("x", 1, "0.0.0.0", False)
    assert seen["start"] == "0.0.0.0"


def test_tyrano_serve_shares_the_implementation(monkeypatch):
    seen = _capture_serve(monkeypatch)
    cli.cmd_tyrano_serve("x", 1, "0.0.0.0", False)
    assert seen["start"] == "0.0.0.0"


def test_default_host_is_loopback_so_tests_stay_local():
    """Only an explicit --host may expose the build on the LAN."""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    # both serve commands declare the loopback default (Typer derives
    # `--host` from the parameter name, so the flag string is not literal)
    assert src.count('typer.Option("127.0.0.1"') >= 2
    assert src.count("host: str = typer.Option(") >= 2


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.3", "127.0.0.1"])
def test_host_is_forwarded_verbatim(monkeypatch, host):
    seen = _capture_serve(monkeypatch)
    cli.cmd_serve("x", 1, host, False)
    assert seen["start"] == host
