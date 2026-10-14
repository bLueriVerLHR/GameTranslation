#!/usr/bin/env python3
"""cli.py - the toolkit's command line, built with Typer.

One definition per command, two apps:

  * ``app``      - RPG Maker MZ/MV: unpack-data / clean / doctor /
                   compress / deliver
  * ``tyrano``   - TyranoScript: clean / localize-ui / compress / deliver

``pipeline.py`` and ``tyrano/pipeline.py`` stay as thin wrappers so the
documented invocations keep working.  compress / deliver exist once here and
are shared by both apps (re-declaring them is what let the two entry points
drift apart).

``-v/--verbose`` is an app-level option, so it goes before the subcommand:
``python pipeline.py -v clean <dir>``.

Exit codes: a failing archive integrity check exits non-zero via
``typer.Exit``.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import typer

from rpgmaker import clean as clean_mod
from rpgmaker import cliutil, deliver, detect, doctor, evb
from rpgmaker import compress as compress_mod

log = logging.getLogger("rpgmaker.cli")

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="RPG Maker MZ/MV: unpack, clean, package, deliver.")
tyrano = typer.Typer(add_completion=False, no_args_is_help=True,
                     help="TyranoScript / TyranoBuilder: clean, localize, package, deliver.")

# One definition of -v/-q/--log-file for both apps (rpgmaker/cliutil.py).
cliutil.app_options(app)
cliutil.app_options(tyrano)


def resolve_web_root(game_dir: str) -> str:
    """Detect the MZ/MV web root, or abort with an actionable message."""
    web_root = detect.find_web_root(game_dir)
    if not web_root:
        raise typer.BadParameter(
            f"no web root found under {game_dir} (need index.html + js/ + data/, or "
            "www/ with the same layout). A launcher repack keeps the database "
            "packed inside <Game>.exe (Enigma Virtual Box: PE sections "
            ".enigma1/.enigma2) - unpack data/ from the exe first (unpack-data).")
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

    Placed before `resolve_web_root()` and the first `open`/`makedirs` in each
    command body: the point of the rule is to refuse *before* touching the
    other side, and a detection walk is already a read.
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

    Such a folder has no data/ on disk, so every data-side tool refuses it.
    Run this first, then the normal extraction and translation steps.
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
        log.info("unpack-data: %s is now a web root", game)


@app.command("clean")
def cmd_clean(
    game: str = typer.Argument(..., help="game folder"),
    dry_run: bool = typer.Option(False, "--dry-run", help="report only, don't delete"),
):
    """Remove junk files, unused fonts and unused tilesets."""
    # Gated even for --dry-run: resolve_web_root() walks the game tree, and a
    # walk over the other storage side is already the read the rule forbids.
    _own("clean the game tree", game=game)
    clean_mod.cleanup_all(resolve_web_root(game), dry_run=dry_run)


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


@app.command("compress")
def cmd_compress(
    game: str = typer.Argument(..., help="game folder"),
    out: str = typer.Option("", "-o", "--out", help="archive path (default: game folder + .7z)"),
    level: int = typer.Option(15, help="zstd compression level"),
):
    """Package a folder as a 7z-zstd archive (integrity-tested)."""
    _own("compress the game folder", game=game, out=out)
    web = resolve_web_root(game)
    _test_archive(compress_mod.compress(web, out or (web + ".7z"), level=level))


@app.command("deliver")
def cmd_deliver(
    game: str = typer.Argument(..., help="finished folder (usually in temp)"),
    name: str = typer.Option(None, help="delivered name (archive + games-dir folder); "
                                      "defaults to the folder's basename"),
    level: int = typer.Option(15, help="zstd compression level"),
):
    """Write back to storage: compress, copy the archive, extract into games."""
    # deliver.deliver() gates these roles itself; declaring them here too is
    # what makes "every command body states its paths" checkable statically.
    _own("deliver the folder", game=game)
    deliver.deliver(game, name=name, level=level)


# ----------------------------------------------------------------- Tyrano

@tyrano.command("clean")
def cmd_tyrano_clean(
    out: str = typer.Argument(..., help="game folder"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Remove MTool residues and desktop leftovers."""
    _own("clean the tyrano game", out=out)
    from tyrano import clean as tyrano_clean
    tyrano_clean.cleanup_all(out, dry_run=dry_run)


@tyrano.command("localize-ui")
def cmd_tyrano_localize_ui(
    out: str = typer.Argument(..., help="game folder"),
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


@tyrano.command("compress")
def cmd_tyrano_compress(
    out: str = typer.Argument(..., help="game folder"),
    archive: str = typer.Option(None, "-o", "--archive", help="output .7z path"),
    level: int = typer.Option(15),
):
    """Package a folder as a 7z-zstd archive (integrity-tested)."""
    _own("compress the tyrano game", out=out, archive=archive)
    _test_archive(compress_mod.compress(out, archive or (out + ".7z"),
                                        level=level))


@tyrano.command("deliver")
def cmd_tyrano_deliver(
    out: str = typer.Argument(..., help="finished game folder"),
    archive: str = typer.Option(
        None, "--archive",
        help="local .7z path to write first (default: temp dir)"),
    name: str = typer.Option(
        None, "--name",
        help="delivered name (archive + games-dir folder); defaults to the "
             "folder's own name, so pass it when working in a slot "
             "like .../out/"),
):
    """Write back to the storage side (compress, copy, extract)."""
    _own("deliver the tyrano game", out=out)
    deliver.deliver(out, archive=archive, name=name)


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
