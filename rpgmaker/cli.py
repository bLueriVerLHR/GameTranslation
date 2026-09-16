#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli.py - the toolkit's command line, built with Typer.

One definition per command, two apps:

  * ``app``      - RPG Maker MZ/MV: build / compat / decrypt / audio / clean /
                   verify / doctor / serve / compress / deliver /
                   unpack-data (launcher-packed data/)
  * ``tyrano``   - TyranoScript: build / audio / clean / fix-autoplay /
                   verify / serve / compress / deliver

``pipeline.py`` and ``tyrano/pipeline.py`` stay as thin wrappers so the
documented invocations keep working.  serve / compress / deliver exist once
here and are shared by both apps (re-declaring them is what let the two entry
points drift apart), and the Tyrano smoke test uses
``rpgmaker.serve.smoke_test`` instead of a second copy.

``-v/--verbose`` is an app-level option, so it goes before the subcommand:
``python pipeline.py -v audio <dir>``.

Exit codes: a failing verify / smoke test / archive integrity check exits
non-zero via ``typer.Exit``.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import typer

from rpgmaker import audio as audio_mod
from rpgmaker import build as build_mod
from rpgmaker import clean as clean_mod
from rpgmaker import compress as compress_mod
from rpgmaker import decrypt, deliver, detect, doctor, evb, logsetup, plugincompat
from rpgmaker import serve as serve_mod
from rpgmaker import verify as verify_mod

log = logging.getLogger("rpgmaker.cli")

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="RPG Maker MZ/MV -> JoiPlay conversion & compression.")
tyrano = typer.Typer(add_completion=False, no_args_is_help=True,
                     help="TyranoScript / TyranoBuilder -> JoiPlay conversion.")

VERBOSE = typer.Option(False, "-v", "--verbose",
                       help="DEBUG diagnostics (per-file detail)")
WORKERS_HELP = "parallel workers (default: auto-tuned to this machine)"


@app.callback()
def _app_options(verbose: bool = VERBOSE):
    """Configure logging for this run (never at import time)."""
    logsetup.setup(verbose=verbose)


@tyrano.callback()
def _tyrano_options(verbose: bool = VERBOSE):
    """Configure logging for this run (never at import time)."""
    logsetup.setup(verbose=verbose)


def resolve_web_root(game_dir: str) -> str:
    """Detect the MZ/MV web root, or abort with an actionable message."""
    web_root = detect.find_web_root(game_dir)
    if not web_root:
        raise typer.BadParameter(
            "no web root found under %s (need index.html + js/ + data/, or "
            "www/ with the same layout). A launcher repack keeps the database "
            "packed inside <Game>.exe (Enigma Virtual Box: PE sections "
            ".enigma1/.enigma2) - extract data/ from the exe first, then "
            "build." % game_dir)
    log.info("engine: %s, web root: %s",
             "MZ" if detect.is_mz(web_root) else "MV", web_root)
    return web_root


def _test_archive(archive: str) -> None:
    """A corrupt archive must never leave a green exit code behind."""
    if not compress_mod.test_archive(archive):
        raise typer.Exit(1)


# --------------------------------------------------------------- RPG Maker

@app.command("unpack-data")
def cmd_unpack_data(
    game: str = typer.Argument(..., help="game folder whose <Game>.exe packs the database"),
    out: str = typer.Option(None, "-o", "--out", help="target data folder (default: <game>/data)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="list the packed files, write nothing"),
):
    """Restore data/ packed inside <Game>.exe (launcher repack: Enigma Virtual Box).

    Such a folder plays fine but has no data/ on disk, so `build` refuses it.
    Run this first, then the normal pipeline.
    """
    target = out or os.path.join(game, "data")
    try:
        summary = evb.unpack(game, target, dry_run=dry_run)
    except evb.EvbError as exc:
        log.error("unpack-data: %s", exc)
        raise typer.Exit(1)
    if summary["skipped"]:
        log.warning("unpack-data: %d non-JSON payload item(s) skipped (repacker leftovers)",
                    len(summary["skipped"]))
    if not summary.get("dry_run"):
        log.info("unpack-data: %s is now a web root - continue with `build`", game)


@app.command("build")
def cmd_build(
    game: str = typer.Argument(..., help="source game folder"),
    out: str = typer.Option(..., "-o", "--out", help="destination JoiPlay folder"),
    workers: int = typer.Option(None, help="parallel copy workers (default: auto-tuned to the machine)"),
):
    """Copy web files into a JoiPlay folder (strip the NW.js runtime)."""
    build_mod.build_joiplay(resolve_web_root(game), out, workers=workers)


@app.command("decrypt")
def cmd_decrypt(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    key: str = typer.Option(None, help="explicit hex encryptionKey override "
                                       "(when System.json is runtime-decrypted)"),
    workers: int = typer.Option(None, help="parallel decrypt workers (default: auto-tuned)"),
):
    """Decrypt .png_/.ogg_ assets and clear the System.json encryption flags."""
    decrypt.decrypt_and_clear(resolve_web_root(game),
                              key=bytes.fromhex(key) if key else None,
                              workers=workers)


@app.command("audio")
def cmd_audio(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    probe_only: bool = typer.Option(False, "--probe-only", help="only probe, no encode"),
    report: str = typer.Option("", help="write a probe CSV report"),
    sample: int = typer.Option(0, help="probe/encode only the first N files"),
    workers: int = typer.Option(None, help="parallel ffmpeg workers (default: auto-tuned)"),
):
    """Probe + re-encode Vorbis audio (the biggest size win)."""
    web = resolve_web_root(game)
    infos = audio_mod.probe_all(web, sample=sample or None, workers=workers)
    if report:
        audio_mod.write_probe_csv(infos, report)
    if probe_only:
        return
    counts, saved = audio_mod.reencode_all(web, infos, workers=workers)
    log.info("audio: %s, saved %.1f MB", dict(counts), saved / 1e6)


@app.command("compat")
def cmd_compat(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="report only, don't write"),
    strict: bool = typer.Option(False, "--strict", help="exit non-zero when a load-time "
                                                        "NW.js reference is left unhandled"),
):
    """Guard known NW.js-only plugin checks (load-time crash in browser/JoiPlay)."""
    report = plugincompat.run(resolve_web_root(game), dry_run=dry_run, strict=strict)
    if strict and report.findings:
        raise typer.Exit(1)


@app.command("clean")
def cmd_clean(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="report only, don't delete"),
):
    """Remove junk files, unused fonts and unused tilesets."""
    clean_mod.cleanup_all(resolve_web_root(game), dry_run=dry_run)


@app.command("verify")
def cmd_verify(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    decode: bool = typer.Option(False, help="also decode-check every audio file"),
    sample: int = typer.Option(0, help="decode only the first N files"),
    source: str = typer.Option(None, help="original game folder: audio refs "
                                          "missing there too are warnings, not failures"),
    workers: int = typer.Option(None, help="parallel PNG/decode workers (default: auto-tuned)"),
):
    """Verify build integrity (PNG/JSON/flags/audio refs/decode)."""
    issues = verify_mod.verify_all(resolve_web_root(game), decode=decode,
                                   sample=sample or None, source_dir=source,
                                   workers=workers)
    if issues:
        raise typer.Exit(1)


@app.command("doctor")
def cmd_doctor(
    as_json: bool = typer.Option(False, "--json", help="machine-readable report "
                                                       "(resolved app paths + their source)"),
):
    """Environment self-check (applications, config, deliverable dirs)."""
    raise typer.Exit(doctor.run(["--json"] if as_json else []))


@app.command("serve")
def cmd_serve(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    port: int = typer.Option(8100, "-p", "--port"),
    host: str = typer.Option("127.0.0.1", help="bind address.  Use 0.0.0.0 so the "
                                               "owner can play from another device (phone)"),
    test: bool = typer.Option(False, "--test", help="run the smoke test, then exit"),
):
    """HTTP server + smoke test (run this for a play-test, not on the phone)."""
    _serve(resolve_web_root(game), port, host, test)


@app.command("compress")
def cmd_compress(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    out: str = typer.Option("", "-o", "--out", help="archive path (default: game folder + .7z)"),
    level: int = typer.Option(15, help="zstd compression level"),
):
    """Package the build as a 7z-zstd archive (integrity-tested)."""
    web = resolve_web_root(game)
    _test_archive(compress_mod.compress(web, out or (web + ".7z"), level=level))


@app.command("deliver")
def cmd_deliver(
    game: str = typer.Argument(..., help="finished JoiPlay folder (usually in temp)"),
    name: str = typer.Option(None, help="delivered name (archive + games-dir folder); "
                                      "defaults to the folder's basename"),
    level: int = typer.Option(15, help="zstd compression level"),
):
    """Write back to storage: compress, copy the archive, extract into games."""
    deliver.deliver(game, name=name, level=level)


# ----------------------------------------------------------------- Tyrano

@tyrano.command("build")
def cmd_tyrano_build(
    game: str = typer.Argument(..., help="original game folder (contains resources/app.asar)"),
    out: str = typer.Option(None, "-o", "--out", help="output folder"),
    asar: str = typer.Option(None, help="path to app.asar (absolute, or relative to game)"),
):
    """Unpack app.asar, strip the Electron runtime, fix the save backend."""
    from tyrano import build as tyrano_build
    tyrano_build.build(game, out, asar_path=asar)


@tyrano.command("audio")
def cmd_tyrano_audio(
    out: str = typer.Argument(..., help="built game folder"),
    workers: int = typer.Option(None, help="parallel ffmpeg processes (default: auto-tuned)"),
    keep: bool = typer.Option(False, help="keep the original mp3 files"),
    sample: int = typer.Option(None, help="convert at most N files (trial run)"),
):
    """mp3 -> Ogg Vorbis, rewriting the scenario .ks references in lockstep."""
    from tyrano import audio as tyrano_audio
    tyrano_audio.convert_all(out, workers=workers, keep=keep, sample=sample)


@tyrano.command("clean")
def cmd_tyrano_clean(
    out: str = typer.Argument(..., help="built game folder"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Remove MTool residues and desktop leftovers."""
    from tyrano import clean as tyrano_clean
    tyrano_clean.cleanup_all(out, dry_run=dry_run)


@tyrano.command("fix-autoplay")
def cmd_fix_autoplay(out: str = typer.Argument(..., help="built game folder")):
    """Patch [bgmovie] play() for the browser autoplay policy (idempotent)."""
    from tyrano import autoplay
    autoplay.patch_autoplay(out)


@tyrano.command("verify")
def cmd_tyrano_verify(
    out: str = typer.Argument(..., help="built game folder"),
    source: str = typer.Option(None, help="original game folder"),
    png: bool = typer.Option(True, "--png/--no-png", help="also check PNG limits"),
):
    """Check layout, save backend, audio refs and PNG limits."""
    from tyrano import verify as tyrano_verify
    problems = tyrano_verify.verify(out, source=source, check_png=png)
    for problem in problems:
        log.error("verify: %s", problem)
    if problems:
        raise typer.Exit(1)


@tyrano.command("serve")
def cmd_tyrano_serve(
    out: str = typer.Argument(..., help="built game folder"),
    port: int = typer.Option(8100, "--port"),
    host: str = typer.Option("127.0.0.1", help="bind address.  Use 0.0.0.0 so the "
                                               "owner can play from another device (phone)"),
    test: bool = typer.Option(False, "--test", help="smoke test then exit"),
):
    """HTTP server + smoke test (shared with the RPG Maker pipeline)."""
    _serve(out, port, host, test)


@tyrano.command("compress")
def cmd_tyrano_compress(
    out: str = typer.Argument(..., help="built game folder"),
    archive: str = typer.Option(None, "-o", "--archive", help="output .7z path"),
    level: int = typer.Option(15),
):
    """Package the build as a 7z-zstd archive (integrity-tested)."""
    _test_archive(compress_mod.compress(out, archive or (out + ".7z"),
                                        level=level))


@tyrano.command("deliver")
def cmd_tyrano_deliver(
    out: str = typer.Argument(..., help="built game folder"),
    archive: str = typer.Option(
        None, "--archive",
        help="local .7z path to write first (default: temp dir)"),
    name: str = typer.Option(
        None, "--name",
        help="delivered name (archive + games-dir folder); defaults to the "
             "build folder's own name, so pass it when building into a slot "
             "like .../out/"),
):
    """Write back to the storage side (compress, copy, extract)."""
    deliver.deliver(out, archive=archive, name=name)


def _serve(folder: str, port: int, host: str, test: bool) -> None:
    """One serve implementation for both pipelines."""
    if test:
        _results, ok = serve_mod.smoke_test(folder, port=port, host=host)
        if not ok:
            raise typer.Exit(1)
        return
    serve_mod.serve(folder, port=port, host=host)


# ------------------------------------------------------------------ entry

def _prog_name(argv, default):
    """Keep the historical program name in help/usage output."""
    if argv is not None:
        return default
    return Path(sys.argv[0]).name or default


def _run(command, argv, prog_name, default_prog):
    """Run a Typer app with a test-friendly contract.

    Success returns normally (no SystemExit(0)), a failure keeps raising
    SystemExit with its exit code - which is what callers and tests expect,
    and what `python pipeline.py ...` produces either way.
    """
    try:
        command(args=list(argv) if argv is not None else None,
                prog_name=prog_name or default_prog)
    except SystemExit as exc:
        if exc.code in (0, None):
            return
        raise


def main(argv=None) -> None:
    """Entry point for `python pipeline.py ...` and the `gt` script."""
    _run(app, argv, _prog_name(argv, None), "pipeline")


def tyrano_main(argv=None) -> None:
    """Entry point for `python tyrano/pipeline.py ...`."""
    _run(tyrano, argv, _prog_name(argv, None), "tyrano-pipeline")


if __name__ == "__main__":  # pragma: no cover - convenience
    main()
