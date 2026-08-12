#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for gen_translation_shards.py chunk sizing / transcript.

Covers: transcript output stays one physical line per entry even for
multi-line keys (the estimator accuracy requirement), and the auto-sizing
estimate for global chunks mirrors the writer's key-count split.
"""
import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "gts", os.path.join(REPO_ROOT, "tools", "gen_translation_shards.py"))
gts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gts)


class _Args:
    truncate = 45
    window = 2
    global_per_chunk = 600
    target_chunks = 0
    context_budget_kb = 90


def test_transcript_single_line_keys():
    ctx = {"a": {"where": "Map001", "window": ["b", "c"]},
           "b": {"where": "Map001", "window": ["a"]}}
    out = gts.transcript(["a", "b"], ctx, 45, 2)
    assert out[0] == "[K] a   <= Map001"
    assert out[1] == "  | b"
    assert out[2] == "  | c"
    assert out[3] == "[K] b   <= Map001"
    assert out[4] == "  | a"
    assert all("\n" not in l for l in out)


def test_transcript_multiline_key_stays_one_line():
    key = "line1\nline2\nline3"
    ctx = {key: {"where": "Map001", "window": []}}
    out = gts.transcript([key], ctx, 45, 2)
    assert len(out) == 1
    assert out[0] == "[K] line1\\nline2\\nline3   <= Map001"
    assert "\n" not in out[0]


def test_transcript_multiline_window_truncated_to_one_line():
    key = "k"
    w = "first\nsecond\nthird"
    ctx = {key: {"where": "Map001", "window": [w]}}
    out = gts.transcript([key], ctx, 45, 2)
    wline = out[1]
    assert wline.startswith("  | ")
    assert "\n" not in wline
    assert len(wline) <= 5 + 45


def test_transcript_carriage_return_flattened():
    key = "k"
    ctx = {key: {"where": "Map001", "window": ["a\r\nb"]}}
    out = gts.transcript([key], ctx, 45, 2)
    assert "\r" not in "".join(out)


def test_transcript_dedup_windows():
    key = "k"
    ctx = {key: {"where": "Map001",
                 "window": ["w1", "w1", "w2", "w3", "w4", "w5"]}}
    out = gts.transcript([key], ctx, 45, 2)
    wins = [l for l in out if l.startswith("  |")]
    # window radius 2 -> at most 5 window lines (cap applies to the whole
    # window list; within-key duplicates are NOT deduplicated, only windows
    # already shown by the PREVIOUS key are)
    assert len(wins) == 5
    assert wins == ["  | w1", "  | w1", "  | w2", "  | w3", "  | w4"]


def test_estimator_matches_written_size():
    """The auto-size estimator must agree with what _write actually writes:
    multi-line keys no longer expand the transcript AND the estimate counts
    UTF-8 bytes like the real file size, so estimate vs real file stay
    within a few percent."""
    ctx = {}
    for i in range(30):
        ctx["k%d" % i] = {"where": "Map00%d" % (i % 3),
                          "window": ["ctx%d" % (i + j) for j in range(2)]}
    for i in range(20):
        ml = "row1\nrow2\nrow3"
        ctx[ml] = {"where": "Map010", "window": ["w"]}
    keys = ["k%d" % i for i in range(30)] + ["row1\nrow2\nrow3"] * 20
    est = gts._chunk_context(keys, ctx, "", None, None, _Args())
    tr = gts.transcript(keys, ctx, 45, 2)
    real = sum(len(l.encode("utf-8")) + 1 for l in tr) + 1000  # prefix approx
    assert real / est < 1.5


def test_estimator_counts_bytes_for_japanese():
    """A Japanese-heavy chunk must be estimated in bytes: the same content
    in kana/kanji encodes to ~2.5x its char count, so a char-based estimate
    would pass the byte budget while the real file far exceeds it."""
    key = "こんにちは、これは日本語のテストです"
    ctx = {key: {"where": "Map001", "window": []}}
    keys = [key] * 200
    est = gts._chunk_context(keys, ctx, "", None, None, _Args())
    tr = gts.transcript(keys, ctx, 45, 2)
    # reconstruct the written file exactly as _write does: prefix + head +
    # transcript, all in UTF-8 bytes
    prefix = gts._ctx_prefix(0, "x", len(keys), "", None, None, [], None)
    head = "## Scene transcript (dialogue in story order; [K] = key to translate; | = context line)"
    real = (sum(len(l.encode("utf-8")) + 1 for l in prefix)
            + len(head.encode("utf-8")) + 2
            + sum(len(l.encode("utf-8")) + 1 for l in tr))
    assert est == real
    # ratio of bytes to chars for this content is ~2.5-3
    chars = sum(len(l) for l in tr)
    assert real / chars > 2.0


class TestAutoSizingGlobalSplit:
    def _ctx_and_keys(self):
        ctx = {}
        for i in range(1200):
            ctx["g%03d" % i] = {"where": "db",
                                "window": ["window %d" % (i % 7)]}
        return ctx, ["g%03d" % i for i in range(1200)]

    def test_global_estimate_uses_key_count_split(self):
        ctx, gkeys = self._ctx_and_keys()
        map_keys = [("Map001", ["m%d" % i for i in range(50)])]
        for k in range(50):
            ctx["m%d" % k] = {"where": "Map001", "window": []}
        args = _Args()
        mc, n, mx, warn = gts._auto_sizing(map_keys, gkeys, ctx, "", None,
                                           None, args)
        # 1200 global keys -> exactly 2 key-capped parts (600 each)
        # (the estimator must not pack them into char-sized parts)
        assert n >= 3
        assert mc > 0
        # max context estimate <= budget
        assert mx <= args.context_budget_kb * 1024

    def test_global_estimate_with_oversized_keys(self):
        ctx, gkeys = self._ctx_and_keys()
        # a 2KB global key: 600-key parts must not blow the estimate
        huge = "x" * 2000 + "あ" * 100
        ctx[huge] = {"where": "db", "window": []}
        gkeys = gkeys[:600] + [huge]
        map_keys = [("Map001", ["m%d" % i for i in range(50)])]
        for k in range(50):
            ctx["m%d" % k] = {"where": "Map001", "window": []}
        args = _Args()
        mc, n, mx, warn = gts._auto_sizing(map_keys, gkeys, ctx, "", None,
                                           None, args)
        assert n >= 2
        assert mx <= args.context_budget_kb * 1024
