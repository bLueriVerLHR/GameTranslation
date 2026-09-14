#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify a built TyranoScript JoiPlay folder.

Checks the essentials for the game to actually run in JoiPlay / a browser:
  - index.html + tyrano/ engine + data/ present
  - save backend is webstorage (not the Node-fs file backend)
  - scenario .ks references resolve to existing audio files
    (after the ogg conversion only .ogg refs may point at .ogg files)
  - every referenced audio file exists on disk (source-aware optional)
  - PNG dimensions within the Android WebGL 4096 limit
"""
import logging
import os
import re
import struct
import sys
from typing import Annotated, Optional


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpgmaker import config as rpg_config  # noqa: E402
from .tyrano_extract import load_ks  # noqa: E402

from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("tyrano.verify")

AUDIO_REF = re.compile(r'\b(?:storage|clickse|enterse|decidese|cancelse)=(")([^"]*\.(?:mp3|ogg|m4a|wav))(")')
AUDIO_DIRS = ("data/bgm", "data/sound")


def _rel(path, root):
    return os.path.relpath(path, root)


def check_layout(web_root):
    problems = []
    for name in ("index.html", "tyrano", "data"):
        if not os.path.exists(os.path.join(web_root, name)):
            problems.append("missing %s" % name)
    return problems


def check_save_backend(web_root):
    cfg = os.path.join(web_root, "data", "system", "Config.tjs")
    if not os.path.isfile(cfg):
        return ["missing data/system/Config.tjs"]
    with open(cfg, encoding="utf-8-sig") as f:
        text = f.read()
    m = re.search(r"configSave\s*=\s*(\w+)", text)
    if not m:
        return ["no configSave= line in data/system/Config.tjs"]
    if m.group(1) != "webstorage":
        return ["configSave=%s (needs webstorage for JoiPlay)" % m.group(1)]
    return []


def _audio_exists(web_root, ref):
    for base in AUDIO_DIRS:
        if os.path.isfile(os.path.join(web_root, base, ref)):
            return True
    return False


def _audio_refs(web_root):
    """Yield every (file, ref) audio reference in the scenario tree."""
    scenario = os.path.join(web_root, "data", "scenario")
    if not os.path.isdir(scenario):
        return
    for dp, _dn, fns in os.walk(scenario):
        for fn in sorted(fns):
            if not fn.lower().endswith(".ks"):
                continue
            path = os.path.join(dp, fn)
            text, _enc = load_ks(path)
            for m in AUDIO_REF.finditer(text):
                yield path, m.group(2)


def check_audio_refs(web_root, source=None):
    """Every audio ref in the scenario must point at an existing file.

    With `source` (the original game folder), refs that are missing in
    BOTH the build and the original are downgraded to warnings - a source
    defect is not a conversion regression."""
    missing = []
    mp3_refs = 0
    for path, ref in _audio_refs(web_root):
        if ref.endswith(".mp3"):
            mp3_refs += 1
        if not _audio_exists(web_root, ref):
            missing.append("%s: %s" % (_rel(path, web_root), ref))
    if source:
        source_missing = {ref for _p, ref in _audio_refs(source)
                          if not _audio_exists(source, ref)}
        mp3_refs = sum(1 for _p, ref in _audio_refs(web_root)
                       if ref.endswith(".mp3") and ref not in source_missing)
        missing = [m for m in missing if m.split(": ", 1)[1] not in source_missing]
    problems = ["%d mp3 refs left after conversion" % mp3_refs] \
        if mp3_refs else []
    problems += ["dangling audio ref %s" % m for m in missing[:10]]
    if len(missing) > 10:
        problems.append("...and %d more" % (len(missing) - 10))
    return problems


def _png_size(path):
    """(w, h) from the IHDR header, or None when it is not a PNG header.

    A file with the PNG signature but a truncated header (interrupted copy)
    must be reported as unreadable - this function's job is to find bad
    images, so it must not crash on one.
    """
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or len(head) < 24:
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def _has_png_signature(path):
    """Cheap signature probe used only for a file whose header was
    unreadable, to tell a truncated PNG from a non-PNG with a .png name."""
    try:
        with open(path, "rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def check_png_limits(web_root):
    """Android WebView textures cap at PNG_MAX_DIMENSION px per side; report
    over-limit.  A file that carries the PNG signature but no readable IHDR
    (interrupted copy / truncation) is reported too - it renders broken on
    every platform, and silently skipping it made this check blind."""
    limit = rpg_config.PNG_MAX_DIMENSION
    over = []
    broken = []
    count = 0
    for dp, _dn, fns in os.walk(web_root):
        for fn in fns:
            if not fn.lower().endswith(".png"):
                continue
            path = os.path.join(dp, fn)
            size = _png_size(path)
            if size is None:
                if _has_png_signature(path):
                    broken.append(_rel(path, web_root))
                continue
            count += 1
            w, h = size
            if w > limit or h > limit:
                over.append("%s (%dx%d)" % (_rel(path, web_root), w, h))
    log.info("png: %d checked, %d unreadable", count, len(broken))
    problems = ["png unreadable: %s" % b for b in broken[:10]]
    problems += ["png over %d: %s" % (limit, o) for o in over[:10]]
    return problems


def verify(web_root, source=None, check_png=True):
    """Return the list of problems (empty = OK).  `source` is an optional
    original game folder whose audio tree supplements the built one."""
    problems = []
    problems += check_layout(web_root)
    problems += check_save_backend(web_root)
    problems += check_audio_refs(web_root, source=source)
    if check_png:
        problems += check_png_limits(web_root)
    if problems:
        log.warning("verify: %d problems", len(problems))
    else:
        log.info("verify: OK")
    return problems


def cmd(web_root: Annotated[str, cliutil.Argument(help="built game folder")],
        source: Annotated[Optional[str], cliutil.Option(
            "--source", help="original game folder (audio existence fallback)"
        )] = None,
        no_png: Annotated[bool, cliutil.Option(
            "--no-png", help="skip the PNG size check")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Verify a built TyranoScript folder (problems are printed, one per line)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    problems = verify(web_root, source=source, check_png=not no_png)
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        return 1
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="verify.py")


if __name__ == "__main__":
    raise SystemExit(main())
