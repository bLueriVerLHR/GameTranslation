#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared pytest fixtures: repo path setup, synthetic RPG Maker games and
fake-tool environment wiring.

The fake tools live in tests/fake_tools/ and are injected via the FFMPEG /
FFPROBE / SEVENZ env vars (config.find_* honors env vars first), so the
whole pipeline runs hermetic - no system ffmpeg/7z needed.

Media probing/decoding is in-process (PyAV), so those tests use a real
container instead of a fake binary: `tests/fixtures/sine_loop.ogg` is a
5.8 KB Ogg Vorbis (synthetic 440 Hz sine, 1 ch, 22.05 kHz, 2 s) carrying
LOOPSTART/LOOPLENGTH.  Copy it with `real_ogg()`.
"""
import json
import os
import shutil
import socket
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import pytest  # noqa: E402

FAKE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_tools")
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fixtures")
REAL_OGG = os.path.join(FIXTURE_DIR, "sine_loop.ogg")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def real_ogg(dest):
    """Copy the committed real-Ogg fixture to `dest`; returns `dest`.

    The source is a genuine libvorbis stream with LOOPSTART/LOOPLENGTH tags,
    so probe/decode assertions test real container parsing rather than a
    stub.  Generated once (see the fixture's provenance in the test docs).
    """
    shutil.copyfile(REAL_OGG, dest)
    return dest


def make_launcher(script_path, workdir):
    """Return an executable launcher for a script, portable across platforms.

    POSIX runs the script directly (shebang + exec bit).  Windows cannot exec
    a .py through CreateProcess, so a .cmd shim calling the current
    interpreter is generated instead - that keeps the fake-tool protocol
    identical on both platforms, which matters because the tools are injected
    through the same environment variables a real installation would use.
    """
    if sys.platform != "win32":
        os.chmod(script_path, os.stat(script_path).st_mode | 0o111)
        return str(script_path)
    stem = os.path.splitext(os.path.basename(script_path))[0]
    launcher = os.path.join(workdir, stem + ".cmd")
    with open(launcher, "w", encoding="ascii", newline="\r\n") as f:
        f.write("@echo off\n")
        f.write('"{}" "{}" %*\n'.format(sys.executable, script_path))
    return launcher


def fake_launcher(script, workdir):
    """Launcher for one of the bundled tests/fake_tools/ scripts."""
    return make_launcher(os.path.join(FAKE_DIR, script), workdir)


def make_png_bytes(w=1, h=1):
    """A minimal valid PNG (1x1 RGBA by default) via Pillow."""
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(buf, "PNG")
    return buf.getvalue()


def write_system_json(root, encrypted=False):
    sys_json = {
        "titleBgm": {"name": "bgm1", "volume": 90, "pitch": 100, "pan": 0},
        "sounds": [{"name": "se1", "volume": 80, "pitch": 100, "pan": 0}],
        "hasEncryptedImages": encrypted,
        "hasEncryptedAudio": encrypted,
        "hasEncryptedData": encrypted,
        "encryptionKey": "0123456789abcdef0123456789abcdef" if encrypted else "",
    }
    path = os.path.join(root, "data", "System.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sys_json, f, ensure_ascii=False)


def make_game(root, mv=False, encrypted=False, with_movies=True,
              with_tilesets=True, add_junk=True):
    """Build a synthetic RPG Maker game (MZ layout by default) at `root`.

    Returns the web root path (root itself for MZ, root/www for MV).
    """
    web = root
    if mv:
        web = os.path.join(root, "www")
        os.makedirs(web, exist_ok=True)
    for d in ("css", "data", "fonts", "js", "audio/bgm", "audio/se",
              "img/pictures", "img/tilesets", "effects", "icon"):
        os.makedirs(os.path.join(web, d), exist_ok=True)
    if with_movies:
        os.makedirs(os.path.join(web, "movies"), exist_ok=True)

    with open(os.path.join(web, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><body>test game</body></html>\n")
    with open(os.path.join(web, "js", "main.js"), "w", encoding="utf-8") as f:
        f.write("// main\n")
    if mv:
        with open(os.path.join(web, "js", "rpg_core.js"), "w", encoding="utf-8") as f:
            f.write("// rpg_core\n")
    else:
        with open(os.path.join(web, "js", "rmmz_core.js"), "w", encoding="utf-8") as f:
            f.write("// rmmz_core\n")
        with open(os.path.join(web, "js", "rmmz_plugins.js"), "w", encoding="utf-8") as f:
            f.write("// rmmz_plugins\n")
    with open(os.path.join(web, "js", "plugins.js"), "w", encoding="utf-8") as f:
        f.write("var $plugins = [];\n")
    with open(os.path.join(web, "css", "main.css"), "w", encoding="utf-8") as f:
        f.write('@font-face { font-family: "TestFont"; src: url("used_font.ttf"); }\n')

    write_system_json(web, encrypted=encrypted)

    for fn, content in (("Map001.json", {"@name": "Map001", "events": []}),
                        ("Actors.json", [{"name": "Hero"}])):
        with open(os.path.join(web, "data", fn), "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False)
    if with_tilesets:
        with open(os.path.join(web, "data", "Tilesets.json"), "w",
                  encoding="utf-8") as f:
            json.dump([{"tilesetNames": ["World_A1"]}], f, ensure_ascii=False)

    for rel, data in (
            ("audio/bgm/bgm1.ogg", b"O" * 100000),
            ("audio/se/se1.ogg", b"S" * 60000),
            ("audio/bgm/bgm_mono.ogg", b"M" * 70000),
            ("img/pictures/pic1.png", make_png_bytes()),
            ("img/pictures/big_pic.png", make_png_bytes(64, 48)),
            ("fonts/used_font.ttf", b"\x00\x01\x00\x00" + b"F" * 100),
            ("fonts/unused_font.otf", b"OTTO" + b"O" * 100),
            ("fonts/CaseFont.TTF", b"\x00\x01\x00\x00" + b"C" * 100)):
        with open(os.path.join(web, rel), "wb") as f:
            f.write(data)
    if with_tilesets:
        with open(os.path.join(web, "img", "tilesets", "World_A1.png"), "wb") as f:
            f.write(make_png_bytes())
        with open(os.path.join(web, "img", "tilesets", "unused.png"), "wb") as f:
            f.write(make_png_bytes())
    if add_junk:
        with open(os.path.join(web, "img", "junk.txt"), "w", encoding="utf-8") as f:
            f.write("editor leftover\n")
        with open(os.path.join(web, "img", "pictures", "junk.clip"), "w",
                  encoding="utf-8") as f:
            f.write("clip\n")
    # NW.js desktop runtime files (stripped by build, never copied)
    for fn in ("Game.exe", "nw.dll", "icudtl.dat"):
        with open(os.path.join(root, fn), "wb") as f:
            f.write(b"NWJS" * 10)
    return web


@pytest.fixture
def game_dir(tmp_path):
    """A synthetic MZ game; returns (root, web_root)."""
    root = str(tmp_path / "game")
    web = make_game(root)
    return root, web


@pytest.fixture
def fake_tools(monkeypatch, tmp_path_factory):
    """Point FFMPEG/FFPROBE/SEVENZ at the fake tool launchers.

    Returns a mapping tool-name -> launcher path (``fake_tools["ffmpeg"]``),
    which is also what the subprocess-based CLI tests must export into their
    environment.
    """
    workdir = str(tmp_path_factory.mktemp("fake-tools"))
    mapping = {}
    for name, script in (("FFMPEG", "ffmpeg.py"), ("FFPROBE", "ffprobe.py"),
                         ("SEVENZ", "7z.py")):
        launcher = fake_launcher(script, workdir)
        monkeypatch.setenv(name, launcher)
        mapping[os.path.splitext(script)[0]] = launcher
    mapping["dir"] = workdir
    for var in ("FAKE_HIGH_BITRATE", "FAKE_SMALL_OUTPUT", "GT_WORKERS"):
        monkeypatch.delenv(var, raising=False)
    return mapping


@pytest.fixture
def fake_powershell(monkeypatch, tmp_path_factory):
    """Point POWERSHELL_EXE at the fake capture interpreter."""
    workdir = str(tmp_path_factory.mktemp("fake-powershell"))
    launcher = fake_launcher("fake_powershell.py", workdir)
    monkeypatch.setenv("POWERSHELL_EXE", launcher)
    return launcher


@pytest.fixture
def launcher_factory(tmp_path_factory):
    """Factory making an arbitrary test script executable on this platform
    (tests that need a purposely failing / custom tool stub)."""
    workdir = str(tmp_path_factory.mktemp("launchers"))

    def make(script_path):
        return make_launcher(str(script_path), workdir)

    return make


def fs_is_case_sensitive(path):
    """True when `path`'s filesystem distinguishes file-name case."""
    probe = os.path.join(str(path), "CaseProbe")
    with open(probe, "w", encoding="ascii") as f:
        f.write("x")
    try:
        return not os.path.exists(os.path.join(str(path), "caseprobe"))
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(autouse=True)
def hermetic_resolution(monkeypatch):
    """Keep application/path resolution independent of the host machine.

    GT_NO_PROBE switches off the well-known-install-location probing, so a
    test never picks up whichever binary happens to be installed on the
    developer's box; the once-per-process warning sentinels are reset so
    warn-once assertions stay isolated.  Tests that exercise probing itself
    monkeypatch the probe anchors and unset GT_NO_PROBE explicitly.
    """
    from rpgmaker import config

    monkeypatch.setenv("GT_NO_PROBE", "1")
    monkeypatch.setattr(config, "_warned_defaults", set())
    yield
