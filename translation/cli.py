#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cli.py - the v2 translation toolkit command line (Typer, per cliutil).

``prepare`` is the one call the parent needs before handing a workspace to the
translation subagent: extract the key list, derive the control-code table, then
create the state files and MISSION.md.  Everything else inspects or finishes
the job:

    prepare   <game_dir> <work_dir>   extract + scaffold
    extract   <game_dir> <work_dir>   story-ordered keys.jsonl + code table
    scaffold  <work_dir>              state files + MISSION.md
    codes     <work_dir>              regenerate control_codes.md
    slice     <work_dir>              a slice of keys.jsonl for one scene
    append    <work_dir> --batch F    validate a batch, then append it
    to-json   <work_dir>              raw library -> translated.json (escaping)
    rewrite   <work_dir>              execute rewrites.jsonl over the library
    gates     <work_dir>              the four hard gates (bake needs all green)
    status    <work_dir>              progress at a glance
"""
import json
import logging
import os
from typing import Annotated

from rpgmaker import cliutil

from . import codes, mvkeys, rawlib, workspace

log = logging.getLogger(__name__)


def prepare(
    game_dir: Annotated[str, cliutil.Argument(help="game directory (data/, js/)")],
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    window: Annotated[int, cliutil.Option(
        "--window", help="context lines kept on each side of a key")] = 2,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Extract the key list and scaffold the workspace in one go."""
    cliutil.setup_logging(verbose, quiet, log_file)
    stats = mvkeys.extract(game_dir, work_dir, window=window)
    created = workspace.scaffold(work_dir, stats)
    log.info("keys: %d (%s)", stats["keys"],
             ", ".join("%s %d" % (k, v) for k, v in stats["by_kind"].items()))
    log.info("created: %s", ", ".join(created))
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


def extract(
    game_dir: Annotated[str, cliutil.Argument(help="game directory (data/, js/)")],
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    window: Annotated[int, cliutil.Option(
        "--window", help="context lines kept on each side of a key")] = 2,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Extract every translatable string, in story order, into keys.jsonl."""
    cliutil.setup_logging(verbose, quiet, log_file)
    stats = mvkeys.extract(game_dir, work_dir, window=window)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


def scaffold(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Create the state files and MISSION.md (never overwrites content)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    for name in ("keys.jsonl",):
        if not os.path.isfile(os.path.join(work_dir, name)):
            return cliutil.fail("%s missing in %s (run extract first)"
                                % (name, work_dir))
    created = workspace.scaffold(work_dir)
    log.info("created: %s", ", ".join(created))
    return 0


def codes_(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Regenerate control_codes.md from the game's JS plus observed counts."""
    cliutil.setup_logging(verbose, quiet, log_file)
    stats_path = os.path.join(work_dir, "stats.json")
    if not os.path.isfile(stats_path):
        return cliutil.fail("stats.json missing in %s (run extract first)"
                            % work_dir)
    with open(stats_path, encoding="utf-8") as handle:
        stats = json.load(handle)
    table = codes.inventory(stats.get("game_dir") or "", stats.get("codes") or {})
    path = codes.write_markdown(os.path.join(work_dir, "control_codes.md"),
                               table, total_keys=stats.get("keys") or 0)
    log.info("wrote %s (%d codes)", path, len(table))
    return 0


def to_json(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    out: Annotated[str, cliutil.Option(
        "--out", help="translated.json path (default: inside the work dir)")] = None,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Turn the raw library into JSON - the only place escaping happens."""
    cliutil.setup_logging(verbose, quiet, log_file)
    report = rawlib.to_json(work_dir, out)
    log.info("translated %d/%d keys (%d unique sources, %d conflicts)",
             report["translated"], report["keys"], report["unique_sources"],
             len(report["conflicts"]))
    print(json.dumps({k: v for k, v in report.items() if k != "conflicts"},
                     ensure_ascii=False, indent=1))
    return 0


def rewrite(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Apply rewrites.jsonl to the library and report the impact."""
    cliutil.setup_logging(verbose, quiet, log_file)
    report = rawlib.apply_rewrites(work_dir)
    log.info("%d rewrite rules, %d keys changed", report["rules"],
             report["changed_keys"])
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def gates(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    markdown: Annotated[str, cliutil.Option(
        "--markdown", help="also write the human summary here")] = None,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Run the four hard gates; a non-zero exit means: do not bake."""
    cliutil.setup_logging(verbose, quiet, log_file)
    if not os.path.isfile(os.path.join(work_dir, "keys.jsonl")):
        return cliutil.fail("keys.jsonl missing in %s (run extract first)"
                            % work_dir)
    report = rawlib.run_gates(work_dir)
    summary = rawlib.gate_markdown(report)
    if markdown:
        with open(markdown, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(summary)
            handle.write("\n")
    print(summary)
    for gate in report["gates"]:
        if not gate["ok"]:
            log.error("gate %s FAILED (%d)", gate["name"],
                      gate.get("missing") or gate.get("mismatched")
                      or gate.get("residue") or gate.get("open") or 0)
    return 0 if report["ok"] else 1


def status(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Progress at a glance (keys, translated, pending, last gate result)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    print(json.dumps(workspace.status_summary(work_dir), ensure_ascii=False,
                     indent=1))
    return 0


def slice_(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    start: Annotated[int, cliutil.Option(
        "--start", help="first story-order position")] = 0,
    count: Annotated[int, cliutil.Option(
        "--count", help="how many keys to take")] = 40,
    kind: Annotated[str, cliutil.Option(
        "--kind", help="only this kind (map/common/troop/db/ui/plugin)")] = None,
    compact: Annotated[bool, cliutil.Option(
        "--compact", help="drop where/kind/seq (cheaper to read)")] = False,
    out: Annotated[str, cliutil.Option(
        "--out", help="write the slice here (default: stdout)")] = None,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Cut a slice of the key list out for the translator to work through.

    The key list is far bigger than one context; the translator reads a slice,
    translates it, appends the batch (see ``append``) and asks for the next.
    ``--compact`` keeps only what a translator needs to read and write.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    if not os.path.isfile(os.path.join(work_dir, "keys.jsonl")):
        return cliutil.fail("keys.jsonl missing in %s (run extract first)"
                            % work_dir)
    entries = mvkeys.slice_keys(work_dir, start=start, count=count, kind=kind)
    if compact:
        entries = [{key: entry[key] for key in
                    ("id", "ja", "speaker", "prev", "next")}
                   for entry in entries]
    payload = "\n".join(json.dumps(entry, ensure_ascii=False)
                        for entry in entries) + ("\n" if entries else "")
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        log.info("wrote %d keys (%d..%d) to %s", len(entries), start,
                 start + len(entries) - 1, out)
    else:
        print(payload, end="")
    return 0 if entries else cliutil.fail(
        "no keys in range (start=%d count=%d kind=%s)" % (start, count, kind))


def append(
    work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
    batch: Annotated[str, cliutil.Option(
        "--batch", help="batch file to append (same format as the library)")],
    note: Annotated[str, cliutil.Option(
        "--note", help="also log a progress line with this note")] = None,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Validate a translated batch, then append it to the library.

    All or nothing: unknown ids, empty values, changed control codes and kana
    residue are all reported **before** anything is written, so a batch that
    fails leaves the library exactly as it was.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    if not os.path.isfile(batch):
        return cliutil.fail("batch file not found: %s" % batch)
    if not os.path.isfile(os.path.join(work_dir, "keys.jsonl")):
        return cliutil.fail("keys.jsonl missing in %s (run extract first)"
                            % work_dir)
    try:
        report = rawlib.append_batch(work_dir, batch, note=note)
    except ValueError as error:
        return cliutil.fail("bad batch file: %s" % error)
    if report["problems"]:
        for key_id, problem in report["problems"][:40]:
            log.error("%s: %s", key_id or "(batch)", problem)
        return cliutil.fail("batch rejected: %d problem(s), library unchanged"
                            % len(report["problems"]))
    log.info("appended %d keys", report["added"])
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


app = cliutil.app(help=__doc__)
app.command()(prepare)
app.command()(extract)
app.command()(scaffold)
app.command(name="codes")(codes_)
app.command(name="to-json")(to_json)
app.command()(rewrite)
app.command()(gates)
app.command()(status)
app.command(name="slice")(slice_)
app.command()(append)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="translation")


if __name__ == "__main__":
    raise SystemExit(main())
