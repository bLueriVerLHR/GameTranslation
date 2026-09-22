#!/usr/bin/env python3
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated

from rpgmaker import audio as rpg_audio
from rpgmaker import runtime as rpg_runtime
from rpgmaker import platform
from rpgmaker import tool_registry as rpg_tools
from .tyrano_extract import load_ks

from rpgmaker import cliutil

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
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=rpg_audio.FFMPEG_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        # OSError: spawn failure; TimeoutExpired: slow file.
        log.error("%s: ffmpeg failed: %s", path, exc)
        return None
    if r.returncode != 0 or not os.path.isfile(ogg):
        log.error("%s: transcode failed: %s", path,
                  (r.stderr or r.stdout)[-500:])
        return None
    if not keep:
        os.remove(path)
    return ogg


def convert_all(web_root, workers=None, keep=False, sample=None):
    """Transcode every mp3 under bgm/ and sound/ to ogg.  Returns counts.

    ffmpeg runs are heavyweight subprocesses; a modest thread pool keeps
    the CPU/disk busy without thrashing.  `workers=None` auto-tunes from
    the machine (see rpgmaker/runtime.py)."""
    files = list(iter_mp3(web_root))
    if sample:
        files = files[:sample]
    workers = rpg_runtime.resolve_workers("encode", workers, path=web_root)
    ffmpeg = rpg_tools.find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError(
            "ffmpeg not found - install ffmpeg or set the FFMPEG env var")
    done = ok = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(convert_one, ffmpeg, p, keep): p for p in files}
        for fut in as_completed(futures):
            done += 1
            if fut.result():
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


def convert(web_root, workers=None, keep=False, sample=None):
    # AGENTS.md CRITICAL: this rewrites scripts and deletes the source mp3s
    # with WSL-native tools (plain I/O + ffmpeg), so the folder must be on
    # this processor's side.  Gated before any rewrite, not before the first
    # deletion.
    web_root = str(platform.require_native_paths(
        "convert tyrano audio", web_root=web_root)["web_root"])
    # Rewrite script refs FIRST: conversion removes the mp3 files, and the
    # ref rewrite only touches refs whose source file exists (or whose ogg
    # already exists).  Running conversion first would orphan every ref.
    files, refs, dangling = rewrite_script_refs(web_root)
    counts = convert_all(web_root, workers=workers, keep=keep, sample=sample)
    counts["ref_files"] = files
    counts["refs"] = refs
    counts["dangling"] = dangling
    return counts


def cmd(web_root: Annotated[str, cliutil.Argument(
            help="built game folder (contains data/)")],
        keep: Annotated[bool, cliutil.Option(
            "--keep", help="keep the original mp3 files")] = False,
        sample: Annotated[int | None, cliutil.Option(
            "--sample", help="convert at most N files (trial run)")] = None,
        workers: Annotated[int | None, cliutil.Option(
            "--workers", help="parallel ffmpeg processes (default: auto-tuned)"
        )] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Convert a built TyranoScript game's mp3 audio to ogg."""
    cliutil.setup_logging(verbose, quiet, log_file)
    print(convert(web_root, workers=workers, keep=keep, sample=sample))
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="audio.py")


if __name__ == "__main__":
    raise SystemExit(main())
