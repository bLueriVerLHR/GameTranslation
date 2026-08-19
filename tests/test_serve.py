#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for rpgmaker/serve.py HTTP server + smoke test.

The handler is exercised through real loopback HTTP round-trips so the
tests observe the same behavior a browser would (status code, Content-Type,
cache headers, directory listing).

Two transport helpers are used:
  * http.client.HTTPConnection for direct round-trips - it talks straight
    to 127.0.0.1 with no proxy layer at all, so it is fully hermetic.
  * urllib.request for smoke_test (the module itself uses urlopen). urllib
    caches its opener in a module global (urllib.request._opener), so the
    no_proxy fixture both clears proxy env vars and resets that cache to
    force a fresh read of the environment.
"""
import http.client
import mimetypes
import os
import threading
import urllib.parse
import urllib.request

import pytest

from conftest import free_port, make_game

from rpgmaker import serve


@pytest.fixture
def no_proxy(monkeypatch):
    """Route urllib straight to 127.0.0.1: drop proxy env vars (common in
    dev shells) and reset urllib's cached opener so urlopen re-reads the
    (now clean) environment."""
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(urllib.request, "_opener", None)


@pytest.fixture
def game_web(tmp_path):
    """A synthetic MZ game web root (conftest make_game)."""
    return make_game(str(tmp_path / "game"))


def _http_get(base, path):
    """GET over http.client: returns (status, dict(headers), body) with
    header keys normalized to lowercase (http.client keeps the on-wire
    casing, e.g. 'Content-type')."""
    host, _, port = base[len("http://"):].partition(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, headers, resp.read()
    finally:
        conn.close()


class TestMimeRegistration:
    """serve.py registers font/audio MIME types because Python's bare
    mimetypes db lacks them and Chromium rejects font loads without a
    correct type."""

    @pytest.mark.parametrize("ext,expected", [
        (".ttf", "font/ttf"),
        (".otf", "font/otf"),
        (".woff", "font/woff"),
        (".woff2", "font/woff2"),
        (".eot", "application/vnd.ms-fontobject"),
        (".webm", "video/webm"),
        (".ogg", "audio/ogg"),
        (".m4a", "audio/mp4"),
    ])
    def test_font_audio_extensions_registered(self, ext, expected):
        assert mimetypes.guess_type("x" + ext)[0] == expected


class TestServerRoundtrip:
    """Real loopback HTTP round-trips against start_server()."""

    @pytest.fixture(autouse=True)
    def _setup(self, game_web):
        self.web = game_web

    def _start(self, web=None):
        port = free_port()
        srv, thread = serve.start_server(web or self.web, port=port,
                                         host="127.0.0.1")
        assert isinstance(thread, threading.Thread)
        base = "http://127.0.0.1:%d" % port
        return srv, base

    def test_serves_index(self):
        srv, base = self._start()
        try:
            status, _h, body = _http_get(base, "/index.html")
            assert status == 200
            assert b"test game" in body
        finally:
            serve.stop_server(srv)

    def test_root_serves_index(self):
        # SimpleHTTPRequestHandler serves index.html for "/"
        srv, base = self._start()
        try:
            status, _h, _b = _http_get(base, "/")
            assert status == 200
        finally:
            serve.stop_server(srv)

    def test_correct_font_content_type(self):
        srv, base = self._start()
        try:
            status, hdrs, _b = _http_get(base, "/fonts/used_font.ttf")
            assert status == 200
            assert hdrs.get("content-type") == "font/ttf"
        finally:
            serve.stop_server(srv)

    def test_correct_audio_content_type(self):
        srv, base = self._start()
        try:
            status, hdrs, _b = _http_get(base, "/audio/bgm/bgm1.ogg")
            assert status == 200
            assert hdrs.get("content-type") == "audio/ogg"
        finally:
            serve.stop_server(srv)

    def test_directory_listing(self):
        srv, base = self._start()
        try:
            status, hdrs, body = _http_get(base, "/img/")
            assert status == 200
            assert "text/html" in hdrs.get("content-type", "")
            assert b"junk.txt" in body  # file directly inside /img/
        finally:
            serve.stop_server(srv)

    def test_missing_file_is_404(self):
        srv, base = self._start()
        try:
            status, _h, _b = _http_get(base, "/no/such/file.js")
            assert status == 404
        finally:
            serve.stop_server(srv)

    def test_url_quoted_non_ascii_filename(self):
        with open(os.path.join(self.web, "my file 中文.bin"), "wb") as f:
            f.write(b"BIN")
        srv, base = self._start()
        try:
            path = "/" + urllib.parse.quote("my file 中文.bin")
            status, _h, body = _http_get(base, path)
            assert status == 200
            assert body == b"BIN"
        finally:
            serve.stop_server(srv)

    def test_no_cache_headers(self):
        # NoCacheHandler adds anti-cache headers so a stale 404 never
        # shadows a freshly added asset during play-testing.
        srv, base = self._start()
        try:
            status, hdrs, _b = _http_get(base, "/index.html")
            assert status == 200
            assert hdrs.get("cache-control") == \
                "no-store, no-cache, must-revalidate, max-age=0"
            assert hdrs.get("pragma") == "no-cache"
            assert hdrs.get("expires") == "0"
        finally:
            serve.stop_server(srv)


class TestServeBindAndExit:
    def test_bind_and_exit(self, tmp_path):
        # serve(..., bind_and_exit=True) verifies the port binds, closes and
        # returns True - used by the pipeline to pre-flight a port choice.
        web = make_game(str(tmp_path / "game"))
        assert serve.serve(web, port=free_port(), bind_and_exit=True) is True


class TestSmokeTest:
    def test_healthy_game_all_200(self, game_web, no_proxy):
        results, ok = serve.smoke_test(game_web, port=free_port())
        assert ok, results
        assert set(results) and all(v == 200 for v in results.values())

    def test_missing_index_fails(self, game_web, no_proxy):
        os.remove(os.path.join(game_web, "index.html"))
        results, ok = serve.smoke_test(game_web, port=free_port())
        assert not ok
        # urlopen surfaces a 404 as an HTTPError, recorded as a string
        assert results["index.html"] != 200

    def test_smoke_test_stops_server(self, game_web, no_proxy):
        # after smoke_test returns, the port must be free again
        port = free_port()
        serve.smoke_test(game_web, port=port)
        # re-binding the same port succeeds => server was stopped
        srv = serve.start_server(game_web, port=port, host="127.0.0.1")[0]
        serve.stop_server(srv)
