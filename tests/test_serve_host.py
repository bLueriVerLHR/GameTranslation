#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the serve command's bind host (tyrano pipeline).

The owner plays from another device over the LAN (an AGENTS requirement), and
a loopback-only server is unreachable there.  The host used to be hardcoded to
127.0.0.1, so --host has to be plumbed all the way to the HTTP server.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from tyrano import pipeline as tp  # noqa: E402


def make_args(host, test):
    return argparse.Namespace(out="x", game="x", port=1, host=host, test=test)


def test_smoke_test_receives_the_host(monkeypatch):
    seen = {}
    monkeypatch.setattr(tp, "_smoke_test",
                        lambda out, port, host: seen.setdefault("smoke", host)
                        and True or True)
    try:
        tp.cmd_serve(make_args("0.0.0.0", test=True))
    except SystemExit:
        pass
    assert seen["smoke"] == "0.0.0.0"


def test_plain_serve_passes_the_host_to_the_http_server(monkeypatch):
    seen = {}

    def fake_start_server(folder, port=0, host="127.0.0.1"):
        seen["start"] = host
        return object(), object()

    monkeypatch.setattr(tp.rpg_serve, "start_server", fake_start_server)
    # cmd_serve blocks forever after starting; stop it by raising from sleep
    monkeypatch.setattr(tp.time, "sleep",
                        lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        tp.cmd_serve(make_args("0.0.0.0", test=False))
    except (SystemExit, KeyboardInterrupt):
        pass
    assert seen["start"] == "0.0.0.0"


def test_default_host_is_loopback_so_tests_stay_local():
    # Only an explicit --host may expose the build on the LAN.
    src = Path(tp.__file__).read_text(encoding="utf-8")
    assert '"--host"' in src
    assert 'default="127.0.0.1"' in src
    assert "args.host" in src


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.3", "127.0.0.1"])
def test_host_is_forwarded_verbatim(monkeypatch, host):
    seen = {}

    def fake_start_server(folder, port=0, host="127.0.0.1"):
        seen["start"] = host
        return object(), object()

    monkeypatch.setattr(tp.rpg_serve, "start_server", fake_start_server)
    monkeypatch.setattr(tp.time, "sleep",
                        lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        tp.cmd_serve(make_args(host, test=False))
    except (SystemExit, KeyboardInterrupt):
        pass
    assert seen["start"] == host
