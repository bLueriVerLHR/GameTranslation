#!/usr/bin/env python3
"""Fill a TyranoScript translation work package from an external {ja: zh}
dictionary.

This is the TyranoScript counterpart of `translate_rpgmaker --trs` (the RPG
Maker route for an MTool runtime dictionary): a repack can ship a
`翻译文件.json` that the game only ever consults at runtime through an MTool
hook, which means the JoiPlay/browser build has no translation at all.  Baking
it means writing those values into the `.ks` scenario, which is what
`apply_tyrano_translation.py` consumes.

Why rebuilding is exact here
----------------------------
The work package's keys are whole `.ks` lines with their tags in place, and
`apply_tyrano_translation.py` replaces a line whole.  The dictionary, on the
other hand, is keyed on the *rendered* text (that is what an MTool hook sees),
so baking means rebuilding each line: everything byte-for-byte, the rendered
text swapped for its translation.

Two shapes carry that text, and handling only the first leaves visible
Japanese behind (measured on a real game: the three title-screen buttons - 3
keys):

* an inline run between tags - `[font color=red]本文[l][p]`
* the display-text attribute of a block tag - `[glink text="始めから" ...]`

Measured on a real Electron-packaged TyranoBuilder game: every one of the
2344 text-bearing keys carries exactly **one** text unit (either shape), so
the rebuild is exact rather than a guess.  A key with more than one unit is
refused, not guessed at - deciding where a translation belongs between tag or
attribute boundaries would mean inventing content.

Gates (a refused key keeps its original Japanese line and is reported)
---------------------------------------------------------------------
* the dictionary value is non-empty and carries no line break
* no kana left in the value (an untranslated leftover; the same rule as the
  v2 flow's kana-residue gate)
* the rebuilt line carries exactly the original tag sequence
* stripping the tags off the rebuilt line gives back the value

Coverage is translated keys / keys with text.  Below ``--min-coverage`` the
tool refuses to write and points at the full-translation route, because a
half-baked bake poisons every later completion pass (this is the same gate
`translation bake` applies to RPG Maker data).  ``--force`` overrides it for a
deliberate staged harvest.

The dictionary path is always a command-line argument: a game's own dictionary
is local private data and never enters the repository.

Usage:
    python3 tools/bake_tyrano_dict.py <work_dir> <dict.json> \
        [--out translated.json] [--min-coverage 0.5] [--force] \
        [--report report.json]

Run `tools/qc_ks_kana.py <patch_dir>` and
`python -m tools.apply_tyrano_translation <work_dir>` afterwards; the first is
an independent kana-residue gate, the second writes the patch tree.
"""

import logging
import os
import re
from typing import Annotated

import typer

from rpgmaker import cliutil, japanese
from tools import plain_io
from tyrano.tyrano_extract import JA

log = logging.getLogger("bake_tyrano_dict")

#: Tags are `[name attr=..]`; the same span convention as tyrano_extract's
#: display_text (a `]` inside a quoted attribute would end the span early, and
#: no shipped Tyrano tag does that).
TAG_SPAN = re.compile(r"\[[^\]]*\]")

#: The display-text attribute of a block tag (`[glink text=..]`), captured
#: with its prefix so the original quoting/spacing survives the rebuild.
TEXT_ATTR = re.compile(r'\b(text\s*=\s*")([^"]*)(")')

#: Same default as the RPG Maker bake: a bake that translates less than half
#: the keys is a half-Japanese build waiting to happen.
DEFAULT_MIN_COVERAGE = 0.5

OK = "ok"
NO_TEXT = "no-text-unit"
MULTI_UNIT = "multiple-text-units"
MISSING = "not-in-dictionary"
EMPTY = "empty-value"
NEWLINE = "value-has-line-break"
KANA = "kana-left-in-value"
TAGS = "tag-sequence-changed"


def find_units(key, require_japanese=True):
    """Every text unit of a work-package key.

    A unit is ``(prefix, lead, core, tail, suffix)``: rebuilding a line is
    ``prefix + lead + translation + tail + suffix``.  ``lead``/``tail`` keep
    the whitespace a unit carries, so a rebuild never moves text against its
    tags.  Only units carrying Japanese are collected - an ASCII run is not
    something the dictionary was ever keyed on.

    ``require_japanese=False`` is for checking a *rebuilt* line: a translation
    may legitimately contain no Japanese at all (``っっ！？`` -> ``！！？``), and
    the self-check must not mistake that for a lost text unit.
    """
    prefix = "#" if key.startswith("#") else ""
    body = key[1:] if prefix else key
    units = []
    runs = []
    pos = 0
    for match in TAG_SPAN.finditer(body):
        if match.start() > pos:
            runs.append((pos, match.start()))
        pos = match.end()
    if pos < len(body):
        runs.append((pos, len(body)))
    for start, end in runs:
        run = body[start:end]
        if require_japanese and not JA.search(run):
            continue
        units.append((prefix + body[:start],
                      run[:len(run) - len(run.lstrip())],
                      run.strip(),
                      run[len(run.rstrip()):],
                      body[end:]))
    for match in TEXT_ATTR.finditer(body):
        raw = match.group(2)
        if require_japanese and not JA.search(raw):
            continue
        # The closing quote is part of the match, so it has to be put back:
        # dropping it turns the whole tag line into a broken attribute.
        units.append((prefix + body[:match.start()] + match.group(1),
                      raw[:len(raw) - len(raw.lstrip())],
                      raw.strip(),
                      raw[len(raw.rstrip()):],
                      match.group(3) + body[match.end():]))
    return units


def split_line(key):
    """The key's single text unit, or ``None`` when it has none or several."""
    units = find_units(key)
    return units[0] if len(units) == 1 else None


def rebuild(parts, value):
    """The line with the text run replaced, tags byte-for-byte."""
    prefix, lead, _core, tail, suffix = parts
    return prefix + lead + value + tail + suffix


def same_shape(unit, other):
    """Same bytes around the text unit.

    This is the real invariant, and it is stricter than comparing tag spans:
    a block tag's span *contains* the `text=".."` value we are replacing, so
    "the tag sequence is unchanged" is false by construction for that shape.
    What must not change is the unit's own surroundings - a value carrying a
    `"` or a `]` breaks them and is refused rather than written into the tag.
    """
    return (unit[0], unit[1]) == (other[0], other[1]) \
        and (unit[3], unit[4]) == (other[3], other[4])


def kana_residual(value):
    return bool(japanese.KANA.search(value))


def clean_dictionary(table):
    """Drop dictionary entries that cannot be used, with a count per reason.

    Identity entries (value == key, kana present) must go: they shadow the
    real text with the Japanese original and make a bake look complete when
    the line was never translated.
    """
    dropped = {"identity": 0, "empty": 0}
    clean = {}
    for key, value in table.items():
        if not isinstance(value, str):
            continue
        if value == key and kana_residual(key):
            dropped["identity"] += 1
            continue
        if not value.strip():
            dropped["empty"] += 1
            continue
        clean[key] = value
    return clean, dropped


def bake_key(key, table):
    """``(status, translated_line)`` for one work-package key."""
    units = find_units(key)
    if len(units) != 1:
        return (MULTI_UNIT if units else NO_TEXT), None
    value = table.get(units[0][2])
    if value is None:
        return MISSING, None
    if not value.strip():
        return EMPTY, None
    if "\n" in value or "\r" in value:
        return NEWLINE, None
    if kana_residual(value):
        return KANA, None
    line = rebuild(units[0], value)
    rebuilt = find_units(line, require_japanese=False)
    if len(rebuilt) != 1 or rebuilt[0][2] != value:
        return TAGS, None
    if not same_shape(units[0], rebuilt[0]):
        return TAGS, None
    return OK, line


def bake(work_dir, dict_path, out_path, min_coverage, force):
    """Fill translated.json; returns the report dictionary."""
    template = plain_io.load_json(os.path.join(work_dir, "template.json"))
    table, dropped = clean_dictionary(plain_io.load_json(dict_path))
    for reason, count in sorted(dropped.items()):
        if count:
            log.warning("dictionary: %d %s entr%s dropped",
                        count, reason, "y" if count == 1 else "ies")

    translated = {}
    status = {}
    samples = {}
    for key in template:
        result, line = bake_key(key, table)
        status[key] = result
        if result == OK:
            translated[key] = line
        elif len(samples.setdefault(result, [])) < 5:
            samples[result].append(key[:70])

    counts = {}
    for result in status.values():
        counts[result] = counts.get(result, 0) + 1
    total = sum(counts.get(r, 0) for r in (OK, MISSING, EMPTY, NEWLINE, KANA,
                                           TAGS, MULTI_UNIT))
    coverage = counts.get(OK, 0) / total if total else 0.0

    log.info("baked %d/%d keys with text = %.1f%% (%d keys in the package)",
             counts.get(OK, 0), total, coverage * 100, len(template))
    for result in sorted(counts):
        if result != OK:
            log.warning("  %-22s %d", result, counts[result])
    for result in sorted(samples):
        log.warning("  e.g. %s: %s", result, " | ".join(samples[result]))

    if total and coverage < min_coverage and not force:
        log.error("coverage %.1f%% is below --min-coverage %.2f: refusing to "
                  "write a half-translated build (%s). Translate the remaining "
                  "keys, or pass --force for a deliberate staged harvest.",
                  coverage * 100, min_coverage * 100, out_path)
        raise typer.Exit(code=1)

    if out_path:
        plain_io.save_json(out_path, translated)
        log.info("wrote %s (%d entries)", out_path, len(translated))
    return {"coverage": coverage, "keys": len(template), "counts": counts,
            "dropped": dropped, "samples": samples}


def cmd(work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
        dict_path: Annotated[str, cliutil.Argument(
            help="external {ja: zh} dictionary (e.g. an MTool 翻译文件.json)")],
        out: Annotated[str | None, cliutil.Option(
            "--out", help="translated.json to write "
            "(default: <work_dir>/translated.json)")] = None,
        min_coverage: Annotated[float, cliutil.Option(
            "--min-coverage", help="refuse to write below this coverage "
            "(default 0.5)")] = DEFAULT_MIN_COVERAGE,
        force: Annotated[bool, cliutil.Option(
            "--force", help="write even below --min-coverage")] = False,
        report: Annotated[str | None, cliutil.Option(
            "--report", help="also write the statistics as JSON here")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Bake an external dictionary into a TyranoScript work package."""
    cliutil.setup_logging(verbose, quiet, log_file)
    # Single gate for every path this command touches, before the first
    # stat/open/mkdir (AGENTS.md CRITICAL cross-system rule).
    cliutil.own_paths("bake tyrano dictionary", work_dir=work_dir,
                      dict_path=dict_path, out=out, report=report)
    work = os.path.abspath(work_dir)
    out_path = os.path.abspath(out or os.path.join(work, "translated.json"))
    if not os.path.isfile(os.path.join(work, "template.json")):
        log.error("%s has no template.json: run "
                  "tools/build_tyrano_translation.py <game_dir> <work_dir> "
                  "first", work)
        raise typer.Exit(code=1)
    stats = bake(work, os.path.abspath(dict_path), out_path, min_coverage,
                 force)
    if report:
        plain_io.save_json(os.path.abspath(report), stats)
        log.info("wrote %s", report)
    return 0


# --help prints the tool's full documentation: a single-command Typer app
# shows the COMMAND docstring, so the module docstring is attached to it
# (the argparse version printed the same text as its description).
cmd.__doc__ = __doc__
app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="bake_tyrano_dict.py")


if __name__ == "__main__":
    raise SystemExit(main())
