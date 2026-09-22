#!/usr/bin/env python3
"""Serve a game folder over HTTP for a browser/JoiPlay smoke test.
PC browsers block RPG Maker's `file://` XHR, so tests must run over HTTP.

Exposed as plain functions + a CLI subcommand so you can test the build
before (or instead of) compressing it.
"""
import functools
import http.client
import http.server
import logging
import mimetypes
import os
import threading
import urllib.parse
import urllib.request

log = logging.getLogger("rpgmaker.serve")

# Python's http.server ships a bare mimetypes db on Windows; without a
# correct MIME type Chromium rejects @font-face/FontFace font loads
# ("LoadError fonts/x.ttf") during PC play-testing. Register them explicitly.
for _ext, _mime in {
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".eot": "application/vnd.ms-fontobject",
    ".webm": "video/webm",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}.items():
    mimetypes.add_type(_mime, _ext)

SMOKE_PATHS = [
    "index.html",
    "js/main.js",
    "js/plugins.js",
    "data/System.json",
    "audio/bgm",
    "img/pictures",
]

# TyranoScript / TyranoBuilder tree (index.html + tyrano/ + data/).
TYRANO_SMOKE_PATHS = [
    "index.html",
    "tyrano/tyrano.js",
    "tyrano/plugins/kag/kag.js",
    "data/scenario/first.ks",
    "data/system/Config.tjs",
]

# (directory, extensions) holding one real audio and one real picture.
_LAYOUT_MEDIA = {
    "mz": (("audio/bgm", (".ogg",)), ("img/pictures", (".png",))),
    "tyrano": (("data/bgm", (".ogg", ".m4a")), ("data/fgimage", (".png",))),
}


def _first_file(folder, rel_dir, exts):
    """First file under `rel_dir` (walked in sorted order) with one of
    `exts`, as a root-relative URL path - or None when there is none."""
    root = os.path.join(folder, *rel_dir.split("/"))
    if not os.path.isdir(root):
        return None
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
            if fn.lower().endswith(exts):
                rel = os.path.relpath(os.path.join(dp, fn), folder)
                return rel.replace(os.sep, "/")
    return None


def smoke_paths(folder):
    """Paths to request for a play-test smoke check.

    The supported layouts ship completely different trees: RPG Maker
    (js/, audio/, img/, data/*.json) vs TyranoScript (tyrano/, data/scenario,
    data/system).  Probing RPG Maker paths against a Tyrano build reported
    ISSUES on a build that plays fine, so the probe follows the layout -
    detected from the build itself, never from a flag the caller must know.
    """
    tyrano = os.path.isfile(os.path.join(folder, "tyrano", "tyrano.js"))
    paths = list(TYRANO_SMOKE_PATHS if tyrano else SMOKE_PATHS)
    # add one concrete audio + one concrete picture for a real byte check
    for rel_dir, exts in _LAYOUT_MEDIA["tyrano" if tyrano else "mz"]:
        probe = _first_file(folder, rel_dir, exts)
        if probe:
            paths.append(probe)
    return list(dict.fromkeys(paths))


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Serve game files with cache disabled, so a stale cached 404 from a
    just-added asset never shadows a reload during play-testing."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def serve(folder, port=8100, host="127.0.0.1", bind_and_exit=False):
    """Start an HTTP server rooted at `folder`. If bind_and_exit is True,
    only verify the port binds then return (caller decides)."""
    handler = functools.partial(NoCacheHandler, directory=folder)
    srv = http.server.ThreadingHTTPServer((host, port), handler)
    log.info("serving %s at http://%s:%d", folder, host, port)
    if bind_and_exit:
        srv.server_close()
        return True
    srv.serve_forever()
    return True


def start_server(folder, port=8100, host="127.0.0.1"):
    """Start the server in a background thread; return (server, thread)."""
    handler = functools.partial(NoCacheHandler, directory=folder)
    srv = http.server.ThreadingHTTPServer((host, port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log.info("server started on %s:%d", host, port)
    return srv, t


def stop_server(srv):
    srv.shutdown()
    srv.server_close()


def smoke_test(folder, port=8100, host="127.0.0.1"):
    """Start server, request key files, report status codes, stop server."""
    srv, _t = start_server(folder, port, host)
    results = {}
    try:
        base = "http://%s:%d" % (host, port)
        for path in smoke_paths(folder):
            url = base + "/" + urllib.parse.quote(path)
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    results[path] = r.status
            except (OSError, http.client.HTTPException, ValueError) as e:
                # OSError: URLError/HTTPError/socket (incl. timeouts & 404s);
                # HTTPException: malformed HTTP responses; ValueError: bad URL.
                results[path] = str(e)
    finally:
        stop_server(srv)
    ok = bool(results) and all(v == 200 for v in results.values())
    log.info("smoke test: %s", "ALL 200 OK" if ok else "ISSUES")
    for k, v in results.items():
        log.info("  %-40s %s", k, v)
    return results, ok
