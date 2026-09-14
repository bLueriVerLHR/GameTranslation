#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""augment_adv_resources.py - Merge custom text-resource JSON files (ADV
plugins, SNS feeds, etc.) into an existing static-translation work package.

RPG Maker MZ games with a custom text-resource plugin (e.g. TextResource.js)
keep their real dialogue in data/resources/<lang>/*.json instead of standard
401 message commands.  build_translation.py cannot see them, so the story
chunks would miss the main script.  This tool augments the work package the
shard generator reads (template/kinds/structure/context):

- every kana-bearing string VALUE in each resource file becomes a template
  key (kind "story"), with context windows built from its neighbouring
  values in the same file - scene continuity for the translator.
- JSON keys (IDs like "Hiroka_HEV1_000") are functional lookups and are
  NEVER extracted; only values are translatable.
- the "metadata" key is always skipped.
- nested string arrays (e.g. SNS tweet lists) are flattened in document
  order, so a feed reads in the same order the player sees it.
- resource files are processed in --order, not alphabetically, so scene
  order matches the story.

The same tool backs the bake step: --bake <game_dir> --trs translated.json
exact-matches kana values against the dict and rewrites them in place
(keys/metadata untouched).  Bake refuses below --min-coverage unless --force.

Usage:
    python augment_adv_resources.py <game_dir> <work_dir> \
        --order Hiroka_Prologue,Hiroka_MapEvent,... [--window 2]
    python augment_adv_resources.py <game_dir> --bake --trs translated.json \
        [--min-coverage 0.5] [--force]
"""

import os
import sys
from typing import Annotated, Optional

import typer

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root: rpgmaker/
sys.path.insert(0, _HERE)                   # sibling tools
import bake_translation  # noqa: E402
import japanese_utils  # noqa: E402
import plain_io  # noqa: E402
from rpgmaker import cliutil  # noqa: E402

# ADV text-resource detection uses the coarser hiragana+katakana block range
# (U+3040-30FF, no half-width) - keep it distinct from the canonical KANA so
# the extraction/bake detection behavior is unchanged.
KANA = japanese_utils.KANA_BLOCKS
DEFAULT_MIN_COVERAGE = bake_translation.DEFAULT_MIN_COVERAGE
DEFAULT_DIRS = ["ja-JP"]
DEFAULT_TWEETS = ["hiroka_tweet_list.json"]


def log(msg):
    print(msg, flush=True)


def is_kana_str(v):
    return isinstance(v, str) and bool(KANA.search(v))


def ordered_kana_strings(obj):
    """All kana-bearing strings in document order (nested values too)."""
    out = []
    if isinstance(obj, dict):
        for v in obj.values():
            out.extend(ordered_kana_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(ordered_kana_strings(v))
    elif is_kana_str(obj):
        out.append(obj)
    return out


def walk_resources(game_dir, lang_dirs, tweet_files, order):
    """[(where, key)] in story order; keys are the resource VALUES."""
    items = []
    if not order:
        raise SystemExit("--order is required (comma list of resource file "
                         "stems; files are scene groups, alphabetical order "
                         "would scramble the story)")
    for lang in lang_dirs:
        base = os.path.join(game_dir, "data", "resources", lang)
        if not os.path.isdir(base):
            log("skip: %s (no such dir)" % base)
            continue
        seen = {}
        for stem in order:
            path = os.path.join(base, stem + ".json")
            if not os.path.isfile(path):
                log("skip: %s (not found)" % os.path.relpath(path, game_dir))
                continue
            data = plain_io.load_json(path)
            if not isinstance(data, dict):
                log("skip: %s (not an object)" % os.path.relpath(path, game_dir))
                continue
            for key, val in data.items():
                if key == "metadata":
                    continue
                if is_kana_str(val) and val not in seen:
                    seen[val] = True
                    items.append(("%s/%s" % (lang, stem), val))
    for tf in tweet_files:
        path = os.path.join(game_dir, "data", "resources", tf)
        if not os.path.isfile(path):
            log("skip: %s (not found)" % os.path.relpath(path, game_dir))
            continue
        for s in ordered_kana_strings(plain_io.load_json(path)):
            items.append(("tweets/%s" % tf, s))
    return items


def augment(work_dir, items, window):
    tpl_path = os.path.join(work_dir, "template.json")
    kinds_path = os.path.join(work_dir, "kinds.json")
    struct_path = os.path.join(work_dir, "structure.json")
    ctx_path = os.path.join(work_dir, "context.json")
    tpl = plain_io.load_json(tpl_path)
    kinds = plain_io.load_json(kinds_path)
    struct = plain_io.load_json(struct_path)
    ctx = plain_io.load_json(ctx_path)

    # group by where (file), preserving story order
    groups = []
    group_keys = {}
    for where, key in items:
        if key in tpl:
            continue
        if where not in group_keys:
            group_keys[where] = []
            groups.append((where, group_keys[where]))
        group_keys[where].append(key)

    for where, keys in groups:
        tpl.update({k: "" for k in keys})
        for k in keys:
            kinds[k] = "story"
        idx = keys.index
        ctx.update({
            k: {
                "where": "data/resources/%s" % where,
                "window": _window(keys, idx(k), window),
            }
            for k in keys
        })
        # flat Wolf-style layout: {"kind","key"} items directly on the map
        struct["maps"].append({
            "id": where,
            "items": [{"kind": "story", "key": k} for k in keys],
        })
    plain_io.save_json(tpl_path, tpl)
    plain_io.save_json(kinds_path, kinds)
    plain_io.save_json(struct_path, struct)
    plain_io.save_json(ctx_path, ctx)
    log("augmented %d keys in %d resource groups"
        % (sum(len(ks) for _w, ks in groups), len(groups)))


def _window(keys, pos, radius):
    out = []
    start = max(0, pos - radius)
    end = min(len(keys), pos + radius + 1)
    for i in range(start, end):
        if i == pos:
            continue
        out.append(keys[i][:45])
    return out


# ------------------------------------------------------------------- bake

def bake_resources(game_dir, trs, min_coverage, force, lang_dirs,
                   tweet_files):
    D = plain_io.load_json(trs)
    hits = misses = 0
    miss_samples = []
    targets = []
    for lang in lang_dirs:
        base = os.path.join(game_dir, "data", "resources", lang)
        if not os.path.isdir(base):
            continue
        for fn in sorted(os.listdir(base)):
            if not fn.endswith(".json"):
                continue
            targets.append(os.path.join(base, fn))
    for tf in tweet_files:
        p = os.path.join(game_dir, "data", "resources", tf)
        if os.path.isfile(p):
            targets.append(p)
    n_changed = 0
    for path in targets:
        data = plain_io.load_json(path)

        def fix(v):
            nonlocal hits, misses
            if not is_kana_str(v):
                return v
            if v in D:
                hits += 1
                return D[v]
            misses += 1
            if len(miss_samples) < 10 and len(v) > 4:
                miss_samples.append(v[:60])
            return v

        def walk(obj):
            nonlocal n_changed
            if isinstance(obj, dict):
                out = {}
                for k, v in obj.items():
                    if k == "metadata":
                        out[k] = v
                        continue
                    if isinstance(v, str) and is_kana_str(v):
                        fixed = fix(v)
                        if fixed is not v:
                            n_changed += 1
                        out[k] = fixed
                    elif isinstance(v, (dict, list)):
                        out[k] = walk(v)
                    else:
                        out[k] = v
                return out
            if isinstance(obj, list):
                out = []
                for x in obj:
                    if isinstance(x, (dict, list)):
                        out.append(walk(x))
                    else:
                        fixed = fix(x)
                        if fixed is not x:
                            n_changed += 1
                        out.append(fixed)
                return out
            return obj

        new = walk(data)
        plain_io.save_json(path, new)
    coverage = hits / (hits + misses) if (hits + misses) else 1.0
    log("resources coverage: %d hit / %d missed = %.0f%% (changed %d values)"
        % (hits, misses, coverage * 100, n_changed))
    for s in miss_samples:
        log("  MISS: %r" % s)
    if coverage < min_coverage and not force:
        raise SystemExit("coverage %.0f%% below --min-coverage %.2f; use "
                         "--force to bake anyway" % (coverage * 100,
                                                     min_coverage))
    log("baked resources done")


def cmd(game_dir: Annotated[str, cliutil.Argument(help="game directory")],
        work_dir: Annotated[Optional[str], cliutil.Argument(
            help="translation work dir (required unless --bake)")] = None,
        order: Annotated[str, cliutil.Option(
            "--order", help="comma list of resource file stems in story "
            "order")] = "",
        window: Annotated[int, cliutil.Option("--window")] = 2,
        bake: Annotated[bool, cliutil.Option("--bake")] = False,
        trs: Annotated[str, cliutil.Option("--trs")] = "translated.json",
        min_coverage: Annotated[float, cliutil.Option(
            "--min-coverage")] = DEFAULT_MIN_COVERAGE,
        force: Annotated[bool, cliutil.Option("--force")] = False,
        lang_dirs: Annotated[str, cliutil.Option(
            "--lang-dirs")] = ",".join(DEFAULT_DIRS),
        tweet_files: Annotated[str, cliutil.Option(
            "--tweet-files")] = ",".join(DEFAULT_TWEETS),
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    dirs = [x for x in lang_dirs.split(",") if x]
    tweets = [x for x in tweet_files.split(",") if x]
    # The resource walkers report their own argument errors with SystemExit
    # (walk_resources without --order, bake_resources under the coverage
    # gate); the command turns those into an exit code.
    try:
        if bake:
            bake_resources(game_dir, trs, min_coverage, force, dirs, tweets)
            return 0

        if not work_dir:
            raise typer.BadParameter("work_dir is required unless --bake")
        items = walk_resources(game_dir, dirs, tweets,
                               [x for x in order.split(",") if x])
        augment(work_dir, items, window)
    except SystemExit as exc:
        code = exc.code
        if code is None or code == 0:
            return 0
        if isinstance(code, int):
            return code
        return cliutil.fail(str(code))
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="augment_adv_resources.py")


if __name__ == "__main__":
    raise SystemExit(main())
