#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for the scenario-file translation chain builders
(build_ks_translation.py and build_tyrano_translation.py).

Both builders walk an extracted scenario tree (.ks files), produce the
standard work package (template/kinds/structure/context), and copy the
scenario files for later patching.  Their per-engine differences are real
and kept local: the line-extraction pass (build_ks uses kirikiri.ks_extract,
build_tyrano uses tyrano.tyrano_extract), the per-file key logic and the
story-order BFS (the KiriKiri builder follows [next] continuations by
re-queuing every file, the Tyrano builder only queues storage refs that
exist).  Only the genuinely identical glue lives here.

Design note (review §5, "template method"): a full TranslationPipeline base
class was considered but NOT applied.  The four chains (build_translation /
build_ks_translation / build_wolf_translation / build_tyrano_translation)
extract from radically different inputs (MZ JSON vs .ks lines vs rewolf-trans
patch files), so a forced template-method abstraction would couple them for
little shared gain and raise regression risk.  This module keeps the minimal
convergence: the duplicated, low-risk helpers are shared; everything that
genuinely differs stays in the owning tool.
"""

import json
import os
import shutil


def find_scenario_dir(game_dir, explicit, candidates):
    """Locate the extracted scenario directory: an explicit path wins, else
    the first candidate that is a directory.  Returns None when absent (the
    caller logs and raises SystemExit)."""
    if explicit:
        path = os.path.join(game_dir, explicit)
        return path if os.path.isdir(path) else None
    for cand in candidates:
        path = os.path.join(game_dir, cand)
        if os.path.isdir(path):
            return path
    return None


def resolve_storage(name):
    """storage="foo" may omit the extension."""
    return name if name.lower().endswith(".ks") else name + ".ks"


def save_json(work_dir, name, data):
    """Write one work-package JSON file (ensure_ascii=False, indent=1)."""
    path = os.path.join(work_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def write_work_package(work_dir, tpl, kinds, maps, ctx, meta_name, meta,
                       scenario_src):
    """Write the standard work package (template/kinds/structure/context +
    engine meta) and copy the scenario tree for later patching.  Returns the
    number of unique keys (what build() reports)."""
    os.makedirs(work_dir, exist_ok=True)
    save_json(work_dir, "template.json", tpl)
    save_json(work_dir, "kinds.json", kinds)
    save_json(work_dir, "structure.json", {"maps": maps})
    save_json(work_dir, "context.json", ctx)
    save_json(work_dir, meta_name, meta)

    dest = os.path.join(work_dir, "scenario")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(scenario_src, dest)
    return len(tpl)
