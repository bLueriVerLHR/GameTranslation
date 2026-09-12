#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the resolved-storage path form in the generated shim.

Each asset exists in exactly ONE directory, and the tag hook resolves a name
to `../<canonical_dir>/<file>` so any tag finds it (browsers normalise dot
segments).  But a consumer that builds its own URL from the PAGE ROOT must
drop the leading `../` or it escapes `data/` entirely.

Measured regression this guards against: `[mapaction storage="title.ma"]` was
rewritten to `../fgimage/TITLE.MA`, the shim's own fetch prefixed `./data/`,
and the browser ended up requesting `/fgimage/TITLE.MA` -> 404.  Found by
checking the server request log for 404s, not by looking at the screen.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kirikiri import convert_kag as ck  # noqa: E402

# JS as the browser sees it: the Python literal "\." is the regex "\."
DOT_SLASH_STRIP = "replace(/^\\.\\.\\//, '')"


def test_map_engine_has_the_data_url_helper():
    assert "__kag3_data_url" in ck.MAP_ENGINE_JS


def test_data_url_helper_strips_the_relative_prefix():
    js = ck.MAP_ENGINE_JS
    helper = js.split("var __kag3_data_url")[1].split("};")[0]
    assert DOT_SLASH_STRIP in helper, helper[:300]
    assert "./data/" in helper


def test_fetch_text_normalises_the_dot_prefix():
    js = ck.MAP_ENGINE_JS
    fetch = js.split("var __kag3_fetch_text")[1].split("var __kag3_ctx")[0]
    assert "__kag3_data_url" in fetch, fetch[:400]
    assert DOT_SLASH_STRIP in fetch, fetch[:400]


def test_region_image_load_normalises_the_dot_prefix():
    js = ck.MAP_ENGINE_JS
    region = js.split("var __kag3_region_load")[1].split("var __kag3_resolve")[0]
    assert DOT_SLASH_STRIP in region, region[:400]


def test_resolve_accepts_a_resolved_path_not_only_a_bare_name():
    # __kag3_resolve receives pm.storage, which may already be the resolved
    # "../fgimage/TITLE.MA" form; it must still find the map entry.
    js = ck.MAP_ENGINE_JS
    fn = js.split("var __kag3_resolve = function")[1].split("var __kag3_jump")[0]
    assert DOT_SLASH_STRIP in fn, fn[:400]
    assert "__kag3_stem(key)" in fn, fn[:400]


def test_stem_is_the_one_place_a_path_becomes_a_map_key():
    # Map keys are bare basenames; every derivation from a path must use this,
    # or a lookup silently misses.  Measured failure: the title menu's region
    # image was never found (hasRegionCanvas: false) because its key was built
    # as "fgimage/title_p" after the canonical path change - the artwork drew
    # but no click could be hit-tested.
    js = ck.MAP_ENGINE_JS
    assert "var __kag3_stem = function" in js
    stem = js.split("var __kag3_stem")[1].split("};\n")[0]
    assert DOT_SLASH_STRIP in stem, stem[:300]        # drop ../
    assert "replace(/^.*[\\\\/]/, '')" in stem, stem[:300]   # drop dirs
    assert "replace(/\\.[^.]+$/, '')" in stem, stem[:300]   # drop extension
    assert ".toLowerCase()" in stem
    # no inline re-derivation left behind
    assert js.count("__kag3_stem(") >= 2
    assert "replace(/\\.[^.]+$/, '').toLowerCase()" not in js


def test_tag_hook_still_emits_the_relative_form():
    # The tag-facing behaviour must NOT change: tags need the ../ form.
    assert "'../' + r" in ck.RUNTIME_SHIM_IIFE


def test_runtime_hook_does_not_prefix_twice():
    # A value that already carries ../ must be passed through untouched.
    assert "t.indexOf('../') === 0" in ck.RUNTIME_SHIM_IIFE


def test_video_resolver_takes_a_basename_from_a_path():
    # [openvideo storage=...] may arrive as a path or a bare name; the video
    # map is keyed by basename, so both must resolve.
    js = ck.VIDEO_SHIM_JS
    assert "replace(/^.*[\\\\/]/, '')" in js or "replace(/^.*[\\/]/, '')" in js
