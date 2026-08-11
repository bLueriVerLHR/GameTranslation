#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inject a translated.json ({ja: zh}) dictionary into the extracted
KiriKiri scenario tree and (optionally) pack a patch.xp3.

Whole-line replacement: for every structure item (scenario file, line
number) the stripped original line is looked up in translated.json; on a
hit the line is rewritten in place - original indentation, line ending and
file encoding are preserved.  Keys missing from the dictionary stay
untouched and are counted (run qc_ks_kana.py afterwards to locate them).

Patch layout mirrors the scenario tree, so packing the output directory
produces a patch.xp3 the engine overlays over the base archives.

Usage:
    python3 tools/apply_ks_translation.py <work_dir> \
        [--scenario-dir DIR] [--out DIR] [--pack patch.xp3]
"""

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kirikiri import ks_extract  # noqa: E402

log = logging.getLogger("apply_ks_translation")


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def patch_line(line, trans):
    """Rewrite one line: keep indentation and line ending, replace the
    stripped middle when it is a dictionary key."""
    left = len(line) - len(line.lstrip())
    right = len(line.rstrip())
    key = line[left:right]
    if key not in trans:
        return None
    return line[:left] + trans[key] + line[right:]


def patch_file(src_path, out_path, items, trans, stats):
    """Rewrite one .ks file; returns (replaced, missing).

    The file keeps its original encoding unless the translation cannot be
    encoded in it (Shift-JIS has no Chinese glyphs) - then the whole file
    is converted to UTF-16LE, which the engine sniffs via BOM."""
    text, enc = ks_extract.load_ks(src_path)
    lines = text.splitlines(True)
    replaced = missing = 0
    for item in items:
        idx = item["line"] - 1
        if idx >= len(lines):
            log.warning("%s: line %d out of range", src_path, item["line"])
            continue
        patched = patch_line(lines[idx], trans)
        if patched is None:
            missing += 1
            stats["missing"].append("%s:%d" % (src_path, item["line"]))
        else:
            lines[idx] = patched
            replaced += 1

    data = "".join(lines)
    try:
        encoded = data.encode(enc)
    except UnicodeEncodeError:
        encoded = data.encode("utf-16")
        log.warning("%s: %s cannot encode the translation, file converted "
                    "to UTF-16LE", src_path, enc)
    with open(out_path, "wb") as f:
        f.write(encoded)
    return replaced, missing


def apply(work_dir, scenario_dir, out_dir, pack_name):
    work_dir = os.path.abspath(work_dir)
    scenario_dir = os.path.abspath(scenario_dir)
    out_dir = os.path.abspath(out_dir)

    trans = load_json(os.path.join(work_dir, "translated.json"))
    structure = load_json(os.path.join(work_dir, "structure.json"))
    if not os.path.isdir(scenario_dir):
        log.error("scenario dir not found: %s", scenario_dir)
        raise SystemExit(1)

    stats = {"replaced": 0, "untranslated": 0, "missing": []}
    os.makedirs(out_dir, exist_ok=True)
    files_written = 0
    for m in structure.get("maps", []):
        name = m["id"]
        src_path = os.path.join(scenario_dir, name)
        if not os.path.exists(src_path):
            log.warning("%s: source missing, skipped", src_path)
            continue
        out_path = os.path.join(out_dir, name)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        replaced, missing = patch_file(src_path, out_path, m["items"],
                                       trans, stats)
        files_written += 1
        stats["replaced"] += replaced
        stats["untranslated"] += missing
        log.debug("%s: %d replaced, %d missing", name, replaced, missing)

    if stats["missing"]:
        log.warning("%d untranslated lines (samples: %s)",
                    len(stats["missing"]),
                    ", ".join(stats["missing"][:8]))
    log.info("%d files, %d lines replaced, %d untranslated -> %s",
             files_written, stats["replaced"], stats["untranslated"], out_dir)

    if pack_name:
        pack_patch(out_dir, os.path.join(work_dir, pack_name))
    return stats


def pack_patch(patch_dir, out_path):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from kirikiri import xp3pack

    _files, _total = xp3pack.pack(patch_dir, out_path)
    log.info("packed %s", out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("work_dir")
    ap.add_argument("--scenario-dir", default=None,
                    help="scenario tree to patch (default: <work>/scenario)")
    ap.add_argument("--out", default=None,
                    help="patched tree output (default: <work>/patch)")
    ap.add_argument("--pack", default=None, metavar="patch.xp3",
                    help="also pack the patched tree into a patch.xp3 "
                         "(relative to <work_dir>)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    work = os.path.abspath(args.work_dir)
    scenario = os.path.abspath(args.scenario_dir or os.path.join(work, "scenario"))
    out = os.path.abspath(args.out or os.path.join(work, "patch"))
    apply(work, scenario, out, args.pack)


if __name__ == "__main__":
    main()
