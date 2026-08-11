#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the JoiPlay folder for a TyranoScript game.

TyranoScript games ship as an Electron app: the game itself (index.html +
data/ + tyrano/) lives inside resources/app.asar.  JoiPlay runs the plain
HTML5 layout, so the build extracts the asar and drops the Electron
runtime, then rewrites the save backend (configSave=file needs Node's
fs; webstorage keeps saves in the browser/WebView storage).

The browser cannot serve itself from file:// (ajax loading of .ks), so the
result must be served over HTTP for PC play-testing (serve step).
"""
import logging
import os
import re
import shutil

from . import asar as asar_mod

log = logging.getLogger("tyrano.build")

DEFAULT_ASAR_REL = os.path.join("resources", "app.asar")

CONFIG_SAVE_RE = re.compile(r"(configSave\s*=\s*)(file|webstorage|webstorage_compress)")
ELECTRON_RUNTIME = {
    "main.js", "package.json", "LICENSES.chromium.html",
    "chrome_100_percent.pak", "chrome_200_percent.pak",
    "d3dcompiler_47.dll", "ffmpeg.dll", "icudtl.dat", "libEGL.dll",
    "libGLESv2.dll", "natives_blob.bin", "resources.pak",
    "snapshot_blob.bin", "v8_context_snapshot.bin", "version", "locales",
    "swiftshader", "node_modules", "tyrano.ico", "tyrano.icns",
}


def find_asar(game_dir, asar_path=None):
    """Locate the game's app.asar: explicit path, or the Electron layout."""
    if asar_path:
        path = os.path.join(game_dir, asar_path) if not os.path.isabs(asar_path) \
            else asar_path
        if os.path.isfile(path):
            return path
        log.error("asar not found at %s", asar_path)
        return None
    candidates = [
        os.path.join(game_dir, DEFAULT_ASAR_REL),
        os.path.join(game_dir, "resources", "app.asar"),
        os.path.join(game_dir, "app.asar"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def unpack_game(game_dir, work_dir, asar_path=None):
    """Extract the game from its asar into a working HTML5 folder."""
    src = find_asar(game_dir, asar_path)
    if not src:
        log.error("no app.asar found under %s", game_dir)
        raise SystemExit(1)
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(work_dir, exist_ok=True)
    asar_mod.extract(src, work_dir)
    _strip_electron(work_dir)
    return work_dir


def _strip_electron(work_dir):
    """Remove Electron runtime files from the extracted root."""
    removed = []
    for name in sorted(os.listdir(work_dir)):
        path = os.path.join(work_dir, name)
        if name in ELECTRON_RUNTIME:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed.append(name)
    log.info("removed %d electron runtime items: %s",
             len(removed), ", ".join(removed) or "none")


def fix_save_backend(work_dir):
    """Rewrite data/system/Config.tjs: configSave=file -> webstorage so
    saves work in a browser/WebView (file backend needs Node's fs)."""
    cfg = os.path.join(work_dir, "data", "system", "Config.tjs")
    if not os.path.isfile(cfg):
        log.warning("%s not found, save backend left untouched", cfg)
        return False
    with open(cfg, encoding="utf-8-sig") as f:
        text = f.read()
    if "webstorage" in text:
        log.info("%s already uses webstorage", cfg)
        return True
    new_text, n = CONFIG_SAVE_RE.subn(r"\g<1>webstorage", text)
    if n == 0:
        log.warning("%s has no configSave= line, save backend left untouched", cfg)
        return False
    with open(cfg, "w", encoding="utf-8-sig") as f:
        f.write(new_text)
    log.info("%s: configSave -> webstorage (%d substitution)", cfg, n)
    return True


def build(game_dir, out_dir, asar_path=None):
    """Full build: unpack + strip runtime + fix save backend."""
    work = unpack_game(game_dir, out_dir, asar_path)
    fix_save_backend(work)
    return work


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("game_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--asar", default=None,
                    help="path to app.asar (absolute, or relative to game_dir)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    build(args.game_dir, args.out_dir, args.asar)


if __name__ == "__main__":
    main()
