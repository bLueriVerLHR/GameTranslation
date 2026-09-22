#!/usr/bin/env python3
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
from typing import Annotated


from rpgmaker import cliutil, platform

from . import asar as asar_mod

log = logging.getLogger("tyrano.build")

DEFAULT_ASAR_REL = os.path.join("resources", "app.asar")

CONFIG_SAVE_RE = re.compile(r"(configSave\s*=\s*)(file|webstorage|webstorage_compress)")
ELECTRON_RUNTIME = {
    "main.js", "package.json", "LICENSES.chromium.html",
    "chrome_100_percent.pak", "chrome_200_percent.pak",
    "d3dcompiler_47.dll", "ffmpeg.dll", "icudtl.dat", "libEGL.dll",
    "libGLESv2.dll", "natives_blob.bin", "preload.js", "resources.pak",
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
    # AGENTS.md CRITICAL: the source, the output and the asar all have to be
    # on this processor's side.  Checked before rmtree: deleting a Windows-side
    # directory from WSL is the exact shape of the recorded incident.
    own = platform.require_native_paths("unpack tyrano game", game_dir=game_dir,
                                        work_dir=work_dir,
                                        asar_path=asar_path or game_dir)
    game_dir, work_dir = str(own["game_dir"]), str(own["work_dir"])
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


def cmd(game_dir: Annotated[str, cliutil.Argument(help="game root folder")],
        out_dir: Annotated[str, cliutil.Argument(help="build output folder")],
        asar: Annotated[str | None, cliutil.Option(
            "--asar", help="path to app.asar (absolute, or relative to "
            "game_dir)")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Unpack the Electron build and strip the desktop runtime."""
    cliutil.setup_logging(verbose, quiet, log_file)
    build(game_dir, out_dir, asar)
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="build.py")


if __name__ == "__main__":
    raise SystemExit(main())
