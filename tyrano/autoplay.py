#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patch TyranoScript's kag.tag_ext.js so [bgmovie] starts despite the
browser autoplay policy.

Browsers / WebViews reject <video>.play() with NotAllowedError when the
page has no user activation (autoplay-with-sound policy).  The engine's
wait_bgmovie then waits forever and the title screen stays frozen on a
black frame.  The fix wraps every video element .play() call: when the
promise is rejected, a one-shot click/touchstart/keydown listener is
attached and the video is replayed on the first user interaction.

The patch is idempotent: an already-patched file is detected by the
'_p&&_p.catch' marker and left untouched.
"""
import logging
import os
import re
import sys
from typing import Annotated


_HERE = os.path.dirname(os.path.abspath(__file__))
# Repo root, appended (not inserted) so a same-named sibling module in
# this directory still wins.
sys.path.append(os.path.dirname(_HERE))
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("tyrano.autoplay")

KAG_TAG_EXT_REL = os.path.join("tyrano", "plugins", "kag", "kag.tag_ext.js")

# Any element .play() call inside the minified engine file, e.g.
# video.play() (bgmode movie) or video2.play() (the stacked movie).
_PLAY_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\.play\(\)")

# Marker: present once the wrap is applied -> idempotent skip.
_PATCH_MARKER = "_p&&_p.catch"

_WRAP_TMPL = (
    "var _p={var}.play();if(_p&&_p.catch){{_p.catch(function(){{"
    "var _u=function(){{{var}.play();"
    'document.removeEventListener("click",_u);'
    'document.removeEventListener("touchstart",_u);'
    'document.removeEventListener("keydown",_u)}};'
    'document.addEventListener("click",_u);'
    'document.addEventListener("touchstart",_u);'
    'document.addEventListener("keydown",_u)}})}}'
)


def _wrap_play(match):
    var = match.group(1)
    return _WRAP_TMPL.format(var=var)


def patch_autoplay(work_dir, file_rel=KAG_TAG_EXT_REL):
    """Apply the bgmovie autoplay fix to kag.tag_ext.js in a built folder.

    Returns the number of wrapped .play() call sites (0 = nothing to do,
    already patched, or no video .play() call in this engine version).
    Returns None when the file is missing (nothing was changed).
    """
    path = os.path.join(work_dir, file_rel)
    if not os.path.isfile(path):
        log.warning("%s not found, autoplay fix skipped", path)
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if _PATCH_MARKER in text:
        log.info("%s already patched, left untouched", path)
        return 0
    new_text, n = _PLAY_RE.subn(_wrap_play, text)
    if n == 0:
        log.info("%s: no .play() call sites, nothing to patch", path)
        return 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    log.info("%s: wrapped %d .play() call(s) with user-interaction fallback",
             path, n)
    return n


def cmd(out: Annotated[str, cliutil.Argument(
            help="built TyranoScript game folder")],
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Patch play() for the browser autoplay policy (idempotent)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    patch_autoplay(out)
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="autoplay.py")


if __name__ == "__main__":
    raise SystemExit(main())
