#!/usr/bin/env python3
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
from rpgmaker import cliutil, compress as compress_mod
from rpgmaker import decrypt, deliver, detect, doctor, evb, plugincompat
from rpgmaker import serve as serve_mod
from rpgmaker import verify as verify_mod

log = logging.getLogger("rpgmaker.cli")

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="RPG Maker MZ/MV -> JoiPlay conversion & compression.")
tyrano = typer.Typer(add_completion=False, no_args_is_help=True,
                     help="TyranoScript / TyranoBuilder -> JoiPlay conversion.")

# One definition of -v/-q/--log-file for both apps (rpgmaker/cliutil.py).
cliutil.app_options(app)
cliutil.app_options(tyrano)

WORKERS_HELP = "parallel workers (default: auto-tuned to this machine)"


def resolve_web_root(game_dir: str) -> str:
    """Detect the MZ/MV web root, or abort with an actionable message."""
    web_root = detect.find_web_root(game_dir)
    if not web_root:
        raise typer.BadParameter(
            f"no web root found under {game_dir} (need index.html + js/ + data/, or "
            "www/ with the same layout). A launcher repack keeps the database "
            "packed inside <Game>.exe (Enigma Virtual Box: PE sections "
            ".enigma1/.enigma2) - extract data/ from the exe first, then "
            "build.")
    log.info("engine: %s, web root: %s",
             "MZ" if detect.is_mz(web_root) else "MV", web_root)
    return web_root


def _own(what: str, **paths) -> None:
    """Declare the storage side of every path a command touches.

    `cliutil.own_paths` is the shared gate (AGENTS.md CRITICAL cross-system
    rule); here it is wrapped so a refusal reaches the operator as one logged
    line + exit 1 instead of a traceback.  These commands are invoked through
    Typer's `standalone_mode`, which does not translate the error the way
    `cliutil.run()` does for the `tools/` commands.

    Placed before `resolve_web_root()`, `find_web_root()` and the first
    `open`/`makedirs` in each command body: the point of the rule is to refuse
    *before* touching the other side, and a detection walk is already a read.
    """
    try:
        cliutil.own_paths(what, **paths)
    except cliutil.CrossSideError as exc:
        log.error("%s", exc)
        raise typer.Exit(1) from None


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
    _own("unpack data from the exe", game=game, out=out)
    target = out or os.path.join(game, "data")
    try:
        summary = evb.unpack(game, target, dry_run=dry_run)
    except evb.EvbError as exc:
        log.error("unpack-data: %s", exc)
        # The message is already logged with its own detail; `from None` keeps
        # the CLI refusal to one readable line instead of a chained traceback.
        raise typer.Exit(1) from None
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
    _own("build the JoiPlay folder", game=game, out=out)
    build_mod.build_joiplay(resolve_web_root(game), out, workers=workers)


@app.command("decrypt")
def cmd_decrypt(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    key: str = typer.Option(None, help="explicit hex encryptionKey override "
                                       "(when System.json is runtime-decrypted)"),
    workers: int = typer.Option(None, help="parallel decrypt workers (default: auto-tuned)"),
):
    """Decrypt .png_/.ogg_ assets and clear the System.json encryption flags."""
    _own("decrypt the build", game=game)
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
    _own("re-encode the build's audio", game=game, report=report)
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
    _own("check plugin compatibility", game=game)
    report = plugincompat.run(resolve_web_root(game), dry_run=dry_run, strict=strict)
    if strict and report.findings:
        raise typer.Exit(1)


@app.command("clean")
def cmd_clean(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="report only, don't delete"),
):
    """Remove junk files, unused fonts and unused tilesets."""
    # Gated even for --dry-run: resolve_web_root() walks the game tree, and a
    # walk over the other storage side is already the read the rule forbids.
    _own("clean the build", game=game)
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
    _own("verify the build", game=game, source=source)
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
    # Deliberately ungated: this command takes no path argument, so there is
    # no cross-side input to inspect.  doctor.run() resolves the *tool* and
    # *config* locations itself and reports them; refusing here would only
    # hide the very diagnostic the operator ran the command for.
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
    _own("serve the build", game=game)
    _serve(resolve_web_root(game), port, host, test)


@app.command("compress")
def cmd_compress(
    game: str = typer.Argument(..., help="JoiPlay folder (web root)"),
    out: str = typer.Option("", "-o", "--out", help="archive path (default: game folder + .7z)"),
    level: int = typer.Option(15, help="zstd compression level"),
):
    """Package the build as a 7z-zstd archive (integrity-tested)."""
    _own("compress the build", game=game, out=out)
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
    # deliver.deliver() gates these roles itself; declaring them here too is
    # what makes "every command body states its paths" checkable statically.
    _own("deliver the build", game=game)
    deliver.deliver(game, name=name, level=level)


# ----------------------------------------------------------------- Tyrano

@tyrano.command("build")
def cmd_tyrano_build(
    game: str = typer.Argument(..., help="original game folder (contains resources/app.asar)"),
    out: str = typer.Option(None, "-o", "--out", help="output folder"),
    asar: str = typer.Option(None, help="path to app.asar (absolute, or relative to game)"),
):
    """Unpack app.asar, strip the Electron runtime, fix the save backend."""
    _own("unpack the tyrano game", game=game, out=out, asar=asar)
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
    _own("convert the tyrano build's audio", out=out)
    from tyrano import audio as tyrano_audio
    # convert(), not convert_all(): the conversion deletes the mp3 files, so
    # the scenario refs must be rewritten first (a convert_all-only wiring
    # silently leaves every ref dangling = a build with no audio at all).
    counts = tyrano_audio.convert(out, workers=workers, keep=keep,
                                  sample=sample)
    log.info("audio: %s", counts)


@tyrano.command("clean")
def cmd_tyrano_clean(
    out: str = typer.Argument(..., help="built game folder"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Remove MTool residues and desktop leftovers."""
    _own("clean the tyrano build", out=out)
    from tyrano import clean as tyrano_clean
    tyrano_clean.cleanup_all(out, dry_run=dry_run)


@tyrano.command("fix-autoplay")
def cmd_fix_autoplay(out: str = typer.Argument(..., help="built game folder")):
    """Patch [bgmovie] play() for the browser autoplay policy (idempotent)."""
    _own("patch the tyrano autoplay behaviour", out=out)
    from tyrano import autoplay
    autoplay.patch_autoplay(out)


@tyrano.command("localize-ui")
def cmd_tyrano_localize_ui(
    out: str = typer.Argument(..., help="built game folder"),
    mapping: str = typer.Option(None, "--map", help="JSON {key: translation} "
                                                  "for tyrano/lang.js"),
    dump: str = typer.Option(None, "--dump", help="write the engine UI "
                                                    "strings as JSON"),
    dry_run: bool = typer.Option(False, "--dry-run", help="report only"),
):
    """Localize the engine's own UI text (tyrano/lang.js).

    The engine dialogs (return-to-title confirm, "no save data", script
    errors) live outside data/scenario, so a translated scenario still
    shows Japanese there.  Entries are matched by key, unknown keys are
    reported and something that fails the mechanical gate is refused.
    """
    import json
    from tyrano import ui_lang
    _own("localize the tyrano engine UI", out=out, mapping=mapping, dump=dump)
    lang = ui_lang.find_lang_file(out)
    if not lang:
        log.error("no tyrano/lang.js under %s", out)
        raise typer.Exit(1)
    strings = ui_lang.extract(lang)
    log.info("localize-ui: %s carries %d engine UI strings", lang, len(strings))
    if dump:
        with open(dump, "w", encoding="utf-8") as f:
            json.dump(strings, f, ensure_ascii=False, indent=4)
            f.write("\n")
        log.info("wrote %s", dump)
    if not mapping:
        return
    with open(mapping, encoding="utf-8") as f:
        table = json.load(f)
    report = ui_lang.apply_map(lang, table, dry_run=dry_run)
    log.info("localize-ui: %d applied, %d not in this lang.js, %d refused",
             len(report["applied"]), len(report["missing"]),
             len(report["refused"]))
    for key in report["missing"]:
        log.warning("localize-ui: no such key in lang.js: %s", key)
    for item in report["refused"]:
        log.error("localize-ui: refused: %s", item)
    if report["refused"]:
        raise typer.Exit(1)


@tyrano.command("verify")
def cmd_tyrano_verify(
    out: str = typer.Argument(..., help="built game folder"),
    source: str = typer.Option(None, help="original game folder"),
    png: bool = typer.Option(True, "--png/--no-png", help="also check PNG limits"),
):
    """Check layout, save backend, audio refs and PNG limits."""
    _own("verify the tyrano build", out=out, source=source)
    from tyrano import verify as tyrano_verify
    problems = tyrano_verify.verify(out, source=source, check_png=png)
    for problem in problems:
        log.error("verify: %s", problem)
    if problems:
        raise typer.Exit(1)


@tyrano.command("serve")
def cmd_tyrano_serve(
    out: str = typer.Argument(..., help="built game folder"),
    port: int = typer.Option(8100, "-p", "--port"),
    host: str = typer.Option("127.0.0.1", help="bind address.  Use 0.0.0.0 so the "
                                               "owner can play from another device (phone)"),
    test: bool = typer.Option(False, "--test", help="smoke test then exit"),
):
    """HTTP server + smoke test (shared with the RPG Maker pipeline)."""
    _own("serve the tyrano build", out=out)
    _serve(out, port, host, test)


@tyrano.command("compress")
def cmd_tyrano_compress(
    out: str = typer.Argument(..., help="built game folder"),
    archive: str = typer.Option(None, "-o", "--archive", help="output .7z path"),
    level: int = typer.Option(15),
):
    """Package the build as a 7z-zstd archive (integrity-tested)."""
    _own("compress the tyrano build", out=out, archive=archive)
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
    _own("deliver the tyrano build", out=out)
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
