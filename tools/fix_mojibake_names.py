#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_mojibake_names.py - repair CP936-misread Shift-JIS file names.

A repack built on a Chinese-locale machine sometimes extracts an archive whose
entry names are Shift-JIS bytes but decodes them as CP936, so the name that
lands on disk is mojibake of the original: a directory the engine loads as
`H効果音2` exists as `H岠壥壒2`, a tile image as `MV梡xBCDE1.png` instead of
`MV用xBCDE1.png`.  The game database still references the *original* name, so
every affected asset silently stops loading - no error, just missing sound or
a missing tile.

The repair is a pure round-trip of the name::

    fixed = name.encode("cp936").decode("cp932")

It is only accepted when all of the following hold:

* every character is CP936-encodable - otherwise the name was never CP936
  text (full-width kana and most Japanese-only kanji are not in CP936, which
  is why a genuine Japanese name can never be touched), and the bytes decode
  cleanly as CP932;
* the result differs and contains a CJK ideograph or a katakana/hiragana
  character, i.e. it really decodes to Japanese text;
* the result contains **no half-width katakana**.  Half-width katakana in the
  decoded name is the fingerprint of the opposite direction: CP936 bytes
  (`0xA1-0xDF`) read as CP932 become half-width katakana, so a genuine Chinese
  name - a repack promo file, say - decodes to `ｺﾃﾓﾃｱ...` and is left alone.

Renames are never written unless `--apply` is given: the default is a dry run
that prints the mapping for review.  Renames run deepest-path-first so a
directory rename never invalidates a child path, and an existing target is
reported and skipped instead of overwriting.

Usage:
  python fix_mojibake_names.py <root> [--apply] [--json PATH]
"""
import io
import json
import logging
import os
import sys
from typing import Annotated, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("fix_mojibake_names")

#: Half-width katakana block - fingerprint of CP936 text read as CP932.
HALFWIDTH_KANA = (0xFF61, 0xFF9F)
#: Hiragana, full-width katakana and CJK ideographs (plus the half-width
#: kana block is *excluded* explicitly by the guard above).
JAPANESE_RANGES = ((0x3040, 0x30FF), (0x3400, 0x9FFF), (0xF900, 0xFAFF))


def has_halfwidth_kana(text):
    return any(HALFWIDTH_KANA[0] <= ord(c) <= HALFWIDTH_KANA[1] for c in text)


def has_japanese(text):
    for char in text:
        cp = ord(char)
        if any(lo <= cp <= hi for lo, hi in JAPANESE_RANGES):
            return True
    return False


def fix_name(name):
    """Return the repaired name, or ``None`` when `name` is not this mojibake.

    Only the *name* component is inspected - callers pass ``os.path.basename``.
    """
    if not any(ord(c) > 127 for c in name):
        return None
    try:
        raw = name.encode("cp936")
    except UnicodeEncodeError:
        return None                      # not CP936 text: a genuine JP name
    try:
        fixed = raw.decode("cp932")
    except UnicodeDecodeError:
        return None
    if fixed == name:
        return None                      # already correct - nothing to do
    if has_halfwidth_kana(fixed):
        return None                      # the other direction (CJK read as SJIS)
    if not has_japanese(fixed):
        return None
    return fixed


def candidates(root):
    """Every (path, fixed_name) under `root` that `fix_name` accepts."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in list(dirnames) + filenames:
            fixed = fix_name(name)
            if fixed:
                found.append((os.path.join(dirpath, name), fixed))
    # Deepest first: renaming a parent never invalidates a collected child.
    found.sort(key=lambda item: item[0].count(os.sep), reverse=True)
    return found


def apply_renames(root, found, dry_run=True):
    """Rename each candidate -> summary dict.  Existing targets are skipped."""
    done, skipped = [], []
    for path, fixed in found:
        target = os.path.join(os.path.dirname(path), fixed)
        rel = os.path.relpath(path, root)
        if os.path.exists(target):
            log.warning("target already exists, skipped: %s -> %s", rel, fixed)
            skipped.append((rel, fixed, "target exists"))
            continue
        if dry_run:
            log.info("would rename %s -> %s", rel, fixed)
            done.append((rel, fixed))
            continue
        try:
            os.rename(path, target)
        except OSError as exc:
            log.warning("rename failed (%s): %s -> %s", exc, rel, fixed)
            skipped.append((rel, fixed, str(exc)))
            continue
        log.info("renamed %s -> %s", rel, fixed)
        done.append((rel, fixed))
    return {"renamed": done, "skipped": skipped,
            "old_names": [os.path.basename(p) for p, _f in found]}


def cmd(root: Annotated[str, cliutil.Argument(
            help="game folder to inspect (walked recursively)")],
        apply_: Annotated[bool, cliutil.Option(
            "--apply", help="actually rename (default: dry run)")] = False,
        json_out: Annotated[Optional[str], cliutil.Option(
            "--json", metavar="PATH",
            help="also write the report as UTF-8 JSON")] = None,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Repair CP936-misread Shift-JIS names (dry run unless --apply)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return cliutil.fail("not a folder: %s" % root)
    found = candidates(root)
    log.info("%d mojibake name(s) found under %s", len(found), root)
    # Log every finding, renamed or not: a skipped one is what a human needs
    # to see (it is either a collision or a wrongly-classified name).
    for path, fixed in found:
        log.debug("candidate %s -> %s", os.path.relpath(path, root), fixed)
    summary = apply_renames(root, found, dry_run=not apply_)
    summary["root"] = root
    summary["dry_run"] = not apply_
    if json_out:
        with io.open(json_out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
    log.info("%s %d name(s), skipped %d",
             "would rename" if not apply_ else "renamed",
             len(summary["renamed"]), len(summary["skipped"]))
    return 0


app = cliutil.command_app(cmd, help=__doc__)
cmd.__doc__ = __doc__


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="fix_mojibake_names.py")


if __name__ == "__main__":
    raise SystemExit(main())
