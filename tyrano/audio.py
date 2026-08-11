#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-encode TyranoScript audio to Ogg Vorbis and rewrite the script refs.

The engine plays whatever filename the scripts reference (mediaFormatDefault
defaults to mp3 here), so converting files alone is not enough: every
storage=/clickse=/enterse="*.mp3" reference in the scenario .ks files must
be rewritten to "*.ogg" in lockstep.  Only refs that resolve to an actual
audio file are rewritten - a dangling ref is left alone and reported.
"""
import logging
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpgmaker import config as rpg_config  # noqa: E402
from .tyrano_extract import load_ks  # noqa: E402

log = logging.getLogger("tyrano.audio")

AUDIO_ATTRS = re.compile(r'\b((?:storage|clickse|enterse|decidese|cancelse)=)(")([^"]*\.mp3)(")')
AUDIO_DIRS = ("data/bgm", "data/sound")


def _audio_dirs(web_root):
    return {os.path.join(web_root, d) for d in AUDIO_DIRS}


def iter_mp3(web_root):
    for base in AUDIO_DIRS:
        root = os.path.join(web_root, base)
        if not os.path.isdir(root):
            continue
        for dp, _dn, fns in os.walk(root):
            for fn in sorted(fns):
                if fn.lower().endswith(".mp3"):
                    yield os.path.join(dp, fn)


def convert_one(ffmpeg, path, keep=False):
    """Transcode one mp3 to ogg (Vorbis q3, stereo kept).  Returns the ogg
    path on success, None on failure.  keep=True leaves the mp3 in place."""
    ogg = os.path.splitext(path)[0] + ".ogg"
    if os.path.isfile(ogg):
        if not keep:
            os.remove(path)
        return ogg
    cmd = [ffmpeg, "-y", "-v", "error", "-i", path, "-map", "0:a:0",
           "-c:a", "libvorbis", "-q:a", "3", ogg]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except Exception as exc:
        log.error("%s: ffmpeg failed: %s", path, exc)
        return None
    if r.returncode != 0 or not os.path.isfile(ogg):
        log.error("%s: transcode failed: %s", path,
                  (r.stderr or r.stdout)[-500:])
        return None
    if not keep:
        os.remove(path)
    return ogg


def convert_all(web_root, workers=4, keep=False, sample=None):
    """Transcode every mp3 under bgm/ and sound/ to ogg.  Returns counts."""
    files = list(iter_mp3(web_root))
    if sample:
        files = files[:sample]
    ffmpeg = rpg_config.find_ffmpeg()
    done = ok = failed = 0
    for path in files:
        done += 1
        if convert_one(ffmpeg, path, keep=keep):
            ok += 1
        else:
            failed += 1
        if done % 100 == 0 or done == len(files):
            log.info("...%d/%d", done, len(files))
    log.info("audio: %d converted, %d failed (%d files)", ok, failed, len(files))
    return {"converted": ok, "failed": failed, "total": len(files)}


def _resolvable(web_root, ref):
    """A .mp3 ref is rewritable when its audio file exists at bgm/ref or
    sound/ref (the dirs the engine concatenates with playbgm/playse), or
    when the converted .ogg already exists (idempotent re-run after a
    partial conversion)."""
    for base in AUDIO_DIRS:
        if os.path.isfile(os.path.join(web_root, base, ref)):
            return True
        if ref.lower().endswith(".mp3"):
            ogg = os.path.join(web_root, base, ref[:-4] + ".ogg")
            if os.path.isfile(ogg):
                return True
    return False


def rewrite_script_refs(web_root):
    """Rewrite .mp3 -> .ogg in scenario .ks files for every resolvable ref.
    Returns (rewritten_files, rewritten_refs, dangling)."""
    scenario = os.path.join(web_root, "data", "scenario")
    if not os.path.isdir(scenario):
        return 0, 0, 0
    rewritten_files = rewritten_refs = 0
    dangling = 0
    for dp, _dn, fns in os.walk(scenario):
        for fn in sorted(fns):
            if not fn.lower().endswith(".ks"):
                continue
            path = os.path.join(dp, fn)
            text, enc = load_ks(path)

            def _replace(m):
                nonlocal rewritten_refs, dangling
                ref = m.group(3)
                if _resolvable(web_root, ref):
                    rewritten_refs += 1
                    return m.group(1) + m.group(2) + ref[:-4] + ".ogg" + m.group(4)
                dangling += 1
                return m.group(0)

            new_text, _n = AUDIO_ATTRS.subn(_replace, text)
            if new_text != text:
                with open(path, "w", encoding=enc) as f:
                    f.write(new_text)
                rewritten_files += 1
    log.info("script refs: %d files, %d refs rewritten, %d dangling left",
             rewritten_files, rewritten_refs, dangling)
    return rewritten_files, rewritten_refs, dangling


def convert(web_root, workers=4, keep=False, sample=None):
    # Rewrite script refs FIRST: conversion removes the mp3 files, and the
    # ref rewrite only touches refs whose source file exists (or whose ogg
    # already exists).  Running conversion first would orphan every ref.
    files, refs, dangling = rewrite_script_refs(web_root)
    counts = convert_all(web_root, workers=workers, keep=keep, sample=sample)
    counts["ref_files"] = files
    counts["refs"] = refs
    counts["dangling"] = dangling
    return counts


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("web_root", help="built game folder (contains data/)")
    ap.add_argument("--keep", action="store_true",
                    help="keep the original mp3 files")
    ap.add_argument("--sample", type=int, default=None,
                    help="convert at most N files (trial run)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    print(convert(args.web_root, workers=args.workers, keep=args.keep,
                  sample=args.sample))


if __name__ == "__main__":
    main()
