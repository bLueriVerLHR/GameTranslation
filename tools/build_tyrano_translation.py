#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the standard translation work package from a TyranoScript /
TyranoBuilder game's scenario tree.

Outputs the same contract as build_ks_translation.py so the shared chunk
pipeline (gen_translation_shards -> subagents -> merge_plain_chunks ->
merge_translation) translates it unchanged:

  template.json   {key: ""}  one entry per translatable line
  kinds.json      {key: "story"}
  structure.json  scene tree: maps -> items; map id = scenario file name,
                  each item = {"key": key, "line": N} (1-based line number,
                  used by apply_tyrano_translation.py)
  context.json    key -> {"where": "file:line", "window": [...]}
  scenario/       copy of the extracted scenario files (later patched)

Keys are the STRIPPED .ks lines with tags kept in place - translating a key
means translating the Japanese fragments inside it and keeping every tag
byte-for-byte.  Lines collected: every translatable line inside
[tb_start_text]..[_tb_end_text] blocks (speaker "#Name" lines and text
lines) plus glink / tb_ptext_show / p_notify / tb_alert_dialog lines with
a Japanese text="..." attribute.  Comment lines, blank lines, unbalanced
bracket lines and tag-only lines are never extracted.

Story order: scenario files are traced from the entry file (default
first.ks) through [call]/[jump] storage references; unreferenced files are
appended in sorted order.

Usage:
    python3 tools/build_tyrano_translation.py <game_dir> <work_dir> \
        [--scenario-dir scenario] [--entry first.ks]
"""

import argparse
import json
import logging
import os
import shutil
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tyrano.tyrano_extract import (display_text, load_ks,
                                   scenario_storage_refs, translatable)  # noqa: E402

log = logging.getLogger("build_tyrano_translation")

DEFAULT_SCENARIO = "scenario"
DEFAULT_ENTRY = "first.ks"
WINDOW_RADIUS = 2

SCENARIO_CANDIDATES = ("scenario", "data/scenario")


def find_scenario_dir(game_dir, explicit):
    if explicit:
        path = os.path.join(game_dir, explicit)
        return path if os.path.isdir(path) else None
    for cand in SCENARIO_CANDIDATES:
        path = os.path.join(game_dir, cand)
        if os.path.isdir(path):
            return path
    return None


def resolve_storage(name):
    """storage="foo" may omit the extension."""
    return name if name.lower().endswith(".ks") else name + ".ks"


def story_order(scenario_dir, entry):
    """Scenario files in story order: BFS from the entry through storage
    refs; files never referenced are appended in sorted order."""
    files = sorted(f for f in os.listdir(scenario_dir)
                   if f.lower().endswith(".ks")
                   and not os.path.isdir(os.path.join(scenario_dir, f)))
    if not files:
        return files
    start = entry or DEFAULT_ENTRY
    if start not in files:
        log.warning("%s not found in %s, falling back to sorted order",
                    start, scenario_dir)
        return files
    order = []
    visited = set()
    queue = deque([start])
    while queue:
        name = queue.popleft()
        if name in visited:
            continue
        visited.add(name)
        order.append(name)
        path = os.path.join(scenario_dir, name)
        try:
            text, _enc = load_ks(path)
        except Exception as exc:
            log.error("%s: cannot read: %s", path, exc)
            continue
        refs, has_next = scenario_storage_refs(text)
        for ref in refs:
            resolved = resolve_storage(ref)
            if resolved in files and resolved not in visited:
                queue.append(resolved)
    order.extend(f for f in files if f not in visited)
    return order


def _line_keys(text):
    """All translatable line keys of one .ks file, in order, with their
    real 1-based line numbers."""
    hits = []
    in_block = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("[tb_start_text"):
            in_block = True
            continue
        if stripped.startswith("[_tb_end_text]"):
            in_block = False
            continue
        if in_block:
            if stripped and not stripped.startswith(";"):
                kind = "speaker" if stripped.startswith("#") else "text"
                if translatable(stripped):
                    hits.append((stripped, kind, lineno))
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if translatable(stripped) and _has_text_attr(stripped):
                hits.append((stripped, "text", lineno))
    return hits


def _has_text_attr(line):
    """True when the line carries a text="..." attribute (block lines
    carry the attribute inline too, but those are caught by in_block)."""
    return 'text="' in line


def extract_file(path, name, tpl, kinds, ctx, items):
    """One .ks file: fill template/kinds/context entries and structure items.
    Returns the count of extracted lines."""
    text, _enc = load_ks(path)
    hits = _line_keys(text)
    for pos, (key, kind, lineno) in enumerate(hits):
        if key not in tpl:
            tpl[key] = ""
            kinds[key] = "story"
            ctx[key] = {"where": "%s:%d" % (name, lineno),
                        "window": _window(hits, pos)}
        items.append({"key": key, "line": lineno})
    return len(hits)


def _window(hits, pos):
    """Neighbouring translatable lines as readable display text."""
    out = []
    lo = max(0, pos - WINDOW_RADIUS)
    for k, _kind, _ln in hits[lo:pos]:
        out.append(display_text(k))
    hi = min(len(hits), pos + 1 + WINDOW_RADIUS)
    for k, _kind, _ln in hits[pos + 1:hi]:
        out.append(display_text(k))
    return out


def build(game_dir, work_dir, scenario_dir, entry):
    src = find_scenario_dir(game_dir, scenario_dir)
    if not src:
        log.error("no scenario dir found under %s (tried %s); extract the "
                  "game with tyrano/asar.py first",
                  game_dir, ", ".join(SCENARIO_CANDIDATES))
        raise SystemExit(1)

    tpl, kinds, ctx = {}, {}, {}
    maps = []
    total_lines = 0
    for name in story_order(src, entry):
        items = []
        n = extract_file(os.path.join(src, name), name, tpl, kinds, ctx, items)
        if items:
            maps.append({"id": name, "items": items})
        total_lines += n
        log.debug("%s: %d translatable lines", name, n)

    os.makedirs(work_dir, exist_ok=True)
    _save(work_dir, "template.json", tpl)
    _save(work_dir, "kinds.json", kinds)
    _save(work_dir, "structure.json", {"maps": maps})
    _save(work_dir, "context.json", ctx)
    _save_meta(work_dir, {"game_dir": game_dir, "scenario_dir": src,
                          "entry": entry})

    dest = os.path.join(work_dir, "scenario")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    log.info("%d files / %d translatable lines / %d unique keys -> %s",
             len(maps), total_lines, len(tpl), work_dir)
    return len(tpl)


def _save(work_dir, name, data):
    path = os.path.join(work_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _save_meta(work_dir, data):
    _save(work_dir, "tyrano_meta.json", data)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("game_dir")
    ap.add_argument("work_dir")
    ap.add_argument("--scenario-dir", default=None,
                    help="scenario dir relative to game_dir (default: "
                         "auto-detect scenario/ or data/scenario)")
    ap.add_argument("--entry", default=DEFAULT_ENTRY,
                    help="entry scenario file for story order "
                         "(default: first.ks)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    build(args.game_dir, args.work_dir, args.scenario_dir, args.entry)


if __name__ == "__main__":
    main()
