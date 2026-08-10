#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_wolf_translation.py - Convert rewolf-trans patch files into the
standard GameTranslation work package (template/kinds/structure/context),
so the standard chunk pipeline (gen_translation_shards -> subagents ->
merge_plain_chunks -> merge_translation) can translate Wolf RPG games.

Input: the rewt-patch directory produced by
`npx rewolf-trans -r <game> -p <patch> generate`:
  patch_dir/rewt-patch/
    MapData/<map>.txt            story dialogue in story order
    BasicData/CommonEvent/*.txt  common events (story, referenced by maps)
    BasicData/DataBase/*.txt     database text (items/skills/UI, global)
    BasicData/SysDatabase/*.txt  system database text (global)
    BasicData/CDataBase/*.txt    chara database text (global)
    ..._Danger.txt / ..._Extra.txt  higher-risk strings - skipped by default

Patch file format (rewolf-trans):
  > REWOLF TRANS PATCH FILE VERSION 1.0
  > BEGIN STRING
  <key lines, \\s[9] control codes, real newlines inside the message>
  > CONTEXT [NEW] MPS:<map>/<page>/<event>/[<cmd>]Message/<n>
  > END STRING

Keys: the string content exactly as stored (real newlines are kept; the
patch stores `\\s[9]` as a literal backslash-s).  The chunk pipeline's
plain_io escaping turns real newlines into literal `\n` and literal
backslashes into `\\`.

Structure: MapData maps appear in story order (the order rewolf-trans
walked the map archive, which follows the editor's map list); CommonEvents
come after the maps (they are referenced by maps but authored globally);
database files are global text (no scene order).

Context: every CONTEXT line is recorded as the key's location; keys that
appear in multiple contexts (dialogue shared between a CommonEvent and a
map) get all locations.

Usage:
    python tools/build_wolf_translation.py <patch_dir> <work_dir> [--no-danger] [--no-extra]
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402

JA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")

BEGIN = "> BEGIN STRING"
END = "> END STRING"
CTX = "> CONTEXT"


def parse_patch(path):
    """Yield (key_lines, [context_lines]) in file order."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    blocks = []
    in_block = False
    cur_key = []
    cur_ctx = []
    for line in content.splitlines():
        if line == BEGIN:
            in_block = True
            cur_key, cur_ctx = [], []
        elif line == END:
            in_block = False
            if cur_key:
                blocks.append((cur_key, cur_ctx))
        elif line.startswith(CTX):
            cur_ctx.append(line)
        elif in_block:
            cur_key.append(line)
    return blocks


def parse_ctx(ctx_line):
    """Parse a CONTEXT line into (kind, location)."""
    m = re.search(r"\[NEW\]\s+([A-Z]+):(.+)$", ctx_line)
    if not m:
        return None, ctx_line
    return m.group(1), m.group(2)


def scene_key(ctx_line):
    """Map a CONTEXT line to a scene (same scene = same map+page+event)."""
    m = re.search(r"\[NEW\]\s+([A-Z]+):([^/]+)/([^/]+)/([^/]+)/", ctx_line)
    if not m:
        return None
    return "%s:%s/%s/%s" % (m.group(1), m.group(2), m.group(3), m.group(4))


def collect(patch_dir, with_danger, with_extra):
    """Collect (key, contexts, order, kind) tuples in story order."""
    items = []

    def walk_dir(d, kind, order_base):
        paths = []
        for root, _dirs, files in os.walk(os.path.join(patch_dir, d)):
            for fn in files:
                if not fn.endswith(".txt"):
                    continue
                if fn.endswith("_Danger.txt"):
                    if not with_danger:
                        continue
                elif fn.endswith("_Extra.txt"):
                    if not with_extra:
                        continue
                paths.append(os.path.join(root, fn))
        paths.sort()
        for i, p in enumerate(paths):
            blocks = parse_patch(p)
            rel = os.path.relpath(p, patch_dir)
            for bi, (key_lines, ctx_lines) in enumerate(blocks):
                key = "\n".join(key_lines)
                items.append((key, ctx_lines, order_base + i * 1000 + bi, kind, rel))

    walk_dir("MapData", "story", 0)
    walk_dir(os.path.join("BasicData", "CommonEvent"), "commonevent", 1_000_000)
    walk_dir(os.path.join("BasicData", "DataBase"), "db", 2_000_000)
    walk_dir(os.path.join("BasicData", "SysDatabase"), "system", 3_000_000)
    walk_dir(os.path.join("BasicData", "CDataBase"), "cdb", 4_000_000)
    return items


def build_structure(items):
    """Group by source file into the scene tree the shards read."""
    maps = []          # {id, items: [{key, ctx}]}
    seen_keys = set()
    global_items = []  # non-story files

    def append_map(label, key, ctx, kind):
        if kind == "story":
            m = re.search(r"MapData/([^/]+)\.txt$", label)
            mname = m.group(1) if m else label
        else:
            m = re.search(r"BasicData/CommonEvent/([^/]+)\.txt$", label)
            mname = "[CE] " + (m.group(1) if m else label)
        cur = None
        for mm in maps:
            if mm["id"] == mname:
                cur = mm
                break
        if cur is None:
            cur = {"id": mname, "items": []}
            maps.append(cur)
        cur["items"].append({"key": key, "ctx": ctx})

    for key, ctx, order, kind, label in items:
        if kind in ("story", "commonevent"):
            append_map(label, key, ctx, kind)
        else:
            global_items.append({"key": key, "ctx": ctx, "label": label})

    # story maps first (patch order), common events after, both scene order
    maps.sort(key=lambda m: _map_order(m["id"]))
    return {"maps": maps, "global": global_items}


def _map_order(mname):
    """Order maps: MapData before CommonEvent, then patch-file order."""
    return (0 if not mname.startswith("[CE]") else 1, mname)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("patch_dir", help="directory containing rewt-patch/")
    ap.add_argument("out_dir")
    ap.add_argument("--no-danger", action="store_true",
                    help="skip *_Danger.txt (higher-risk strings)")
    ap.add_argument("--no-extra", action="store_true",
                    help="skip *_Extra.txt files")
    args = ap.parse_args()

    patch_root = os.path.join(args.patch_dir, "rewt-patch")
    if not os.path.isdir(patch_root):
        sys.exit("no rewt-patch/ under %s" % args.patch_dir)
    os.makedirs(args.out_dir, exist_ok=True)

    items = collect(patch_root, not args.no_danger, not args.no_extra)

    # dedup keys (keep first occurrence / lowest order), skip pure-ASCII
    seen = {}
    for key, ctx, order, kind, label in items:
        if key in seen:
            seen[key]["ctx"].extend(ctx)
            continue
        if not JA.search(key):
            continue
        seen[key] = {"ctx": list(ctx), "order": order, "kind": kind, "label": label}

    keys = sorted(seen, key=lambda k: (seen[k]["order"], k))
    template = {k: "" for k in keys}
    kinds = {k: seen[k]["kind"] for k in keys}
    context = {k: {"where": seen[k]["label"], "window": []} for k in keys}

    # Scene windows: neighbouring dialogue lines within the same scene
    # (same map+page+event, or same common event).  Keys keep the order
    # they appeared in the patch (already scene-contiguous per file).
    scenes = {}  # scene -> ordered unique keys in that scene
    for k in keys:
        sc = None
        for ctx_line in seen[k]["ctx"]:
            s = scene_key(ctx_line)
            if s:
                sc = s
                break
        scenes.setdefault(sc, [])
        if k not in scenes[sc]:
            scenes[sc].append(k)
    for k in keys:
        if seen[k]["kind"] in ("db", "system", "cdb"):
            continue  # global terms: no scene window needed
        sc = None
        for ctx_line in seen[k]["ctx"]:
            s = scene_key(ctx_line)
            if s:
                sc = s
                break
        seq = scenes.get(sc) or [k]
        try:
            idx = seq.index(k)
        except ValueError:
            continue
        win = seq[max(0, idx - 2) : idx] + seq[idx + 1 : idx + 3]
        context[k]["window"] = [w for w in win if w != k][:4]

    # build structure tree
    struct_items = [(k, seen[k]["ctx"], seen[k]["order"], seen[k]["kind"],
                     seen[k]["label"]) for k in keys]
    structure = build_structure(struct_items)

    plain_io.save_json(os.path.join(args.out_dir, "template.json"), template)
    plain_io.save_json(os.path.join(args.out_dir, "kinds.json"), kinds)
    plain_io.save_json(os.path.join(args.out_dir, "context.json"), context)
    plain_io.save_json(os.path.join(args.out_dir, "structure.json"), structure)

    n_ja = sum(1 for k in keys if JA.search(k))
    print("template: %d keys (%d with Japanese); maps: %d; global: %d"
          % (len(keys), n_ja, len(structure["maps"]), len(structure["global"])))


if __name__ == "__main__":
    main()
