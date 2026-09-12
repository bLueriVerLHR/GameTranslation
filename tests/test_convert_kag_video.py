#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the KAG3 video system handling in kirikiri/convert_kag.py.

Two things had to be right for movies to work at all:
  * KAG3 keeps .wmv/.mpg under `others/`, which the image-directory copy never
    visits - so they were not being shipped at all;
  * browsers cannot play WMV, so each file must be replaced by the WebM from
    transcode_video.py while the game keeps referring to the old name.
"""
import os
import sys
from collections import Counter

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kirikiri import convert_kag as ck  # noqa: E402


def make(unpacked, rel, data=b"x"):
    p = os.path.join(unpacked, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)
    return p


# ------------------------------------------------------------ discovery

def test_finds_movies_outside_the_image_dirs(tmp_path):
    # The whole point: `others/` is not in the asset mapping, so a
    # directory-driven copy would miss every movie.
    make(str(tmp_path), "others/a_ev001a.wmv")
    make(str(tmp_path), "_video_webm/a_ev001a.webm", b"webm")
    out = tmp_path / "data"
    vmap = ck._convert_videos(str(tmp_path), str(out), str(tmp_path / "_video_webm"),
                              Counter())
    assert os.path.isfile(out / "video" / "a_ev001a.webm")
    assert not os.path.isfile(out / "video" / "a_ev001a.wmv")
    assert vmap["a_ev001a"] == "a_ev001a.webm"
    assert vmap["a_ev001a.wmv"] == "a_ev001a.webm"


def test_no_movies_returns_empty_map(tmp_path):
    make(str(tmp_path), "bgimage/x.png")
    assert ck._convert_videos(str(tmp_path), str(tmp_path / "data"), None,
                              Counter()) == {}


def test_retained_video_map_supports_stem_and_filename(tmp_path):
    video = tmp_path / "data" / "video"
    video.mkdir(parents=True)
    (video / "Scene01.webm").write_bytes(b"webm")

    vmap = ck._video_map_from_output(str(tmp_path / "data"))

    assert vmap["scene01"] == "Scene01.webm"
    assert vmap["scene01.webm"] == "Scene01.webm"


def test_retained_video_map_handles_missing_directory(tmp_path):
    assert ck._video_map_from_output(str(tmp_path / "data")) == {}


def test_both_extension_forms_resolve(tmp_path):
    # Scripts reference movies both with and without the extension
    # ([openvideo storage="&mpglist[...].file"] vs a literal .wmv).
    make(str(tmp_path), "others/op.wmv")
    make(str(tmp_path), "_video_webm/op.webm", b"webm")
    vmap = ck._convert_videos(str(tmp_path), str(tmp_path / "data"),
                              str(tmp_path / "_video_webm"), Counter())
    assert vmap["op"] == vmap["op.wmv"] == "op.webm"


# ------------------------------------------------------------ fallbacks

def test_movie_without_webm_is_shipped_raw_and_warned(tmp_path, caplog):
    # Dropping it silently would remove a scene's video with no trace.
    make(str(tmp_path), "others/old.mpg", b"mpg")
    stats = Counter()
    with caplog.at_level("WARNING"):
        vmap = ck._convert_videos(str(tmp_path), str(tmp_path / "data"), None,
                                  stats)
    assert os.path.isfile(tmp_path / "data" / "video" / "old.mpg")
    assert vmap["old"] == "old.mpg"
    assert stats["video_raw"] == 1
    assert any("no WebM counterpart" in r.message for r in caplog.records)


def test_webm_next_to_the_source_is_found(tmp_path):
    # A hand-transcoded file dropped beside the source must be picked up.
    make(str(tmp_path), "others/hand.wmv")
    make(str(tmp_path), "others/hand.webm", b"webm")
    vmap = ck._convert_videos(str(tmp_path), str(tmp_path / "data"), None,
                              Counter())
    assert vmap["hand"] == "hand.webm"


def test_video_dir_takes_precedence(tmp_path):
    # An explicit --video-dir must win over a stale sibling .webm.
    make(str(tmp_path), "others/v.wmv")
    make(str(tmp_path), "others/v.webm", b"stale")
    make(str(tmp_path), "cache/v.webm", b"fresh")
    out = tmp_path / "data"
    ck._convert_videos(str(tmp_path), str(out), str(tmp_path / "cache"),
                       Counter())
    with open(out / "video" / "v.webm", "rb") as fh:
        assert fh.read() == b"fresh"


def test_video_cache_dir_is_not_scanned_as_source(tmp_path):
    # A .webm in the cache dir must not be treated as a source movie.
    make(str(tmp_path), "_video_webm/lonely.webm", b"webm")
    assert ck._convert_videos(str(tmp_path), str(tmp_path / "data"),
                              str(tmp_path / "_video_webm"), Counter()) == {}


@pytest.mark.parametrize("ext", [".wmv", ".mpg", ".mpeg", ".avi"])
def test_all_source_extensions_are_collected(tmp_path, ext):
    make(str(tmp_path), "others/m" + ext)
    make(str(tmp_path), "_video_webm/m.webm", b"webm")
    vmap = ck._convert_videos(str(tmp_path), str(tmp_path / "data"),
                              str(tmp_path / "_video_webm"), Counter())
    assert vmap["m"] == "m.webm"


def test_uppercase_extension_is_matched(tmp_path):
    make(str(tmp_path), "others/BIG.WMV")
    make(str(tmp_path), "_video_webm/BIG.webm", b"webm")
    vmap = ck._convert_videos(str(tmp_path), str(tmp_path / "data"),
                              str(tmp_path / "_video_webm"), Counter())
    assert vmap["big"] == "BIG.webm"


# ------------------------------------------------------- shim registration

def test_video_tags_are_not_registered_as_noops():
    # If both a no-op and a real implementation were registered, the later
    # registration would win and movie playback would silently do nothing.
    js, _n = ck._shim_js(set())
    for tag in ck.VIDEO_TAGS:
        assert ('tag["%s"] = { start: noop }' % tag) not in js, tag


def test_video_shim_implements_every_video_tag():
    for tag in ck.VIDEO_TAGS:
        assert ("tag['%s']" % tag) in ck.VIDEO_SHIM_JS, tag


def test_video_shim_wv_cannot_stall_forever():
    # [wv] waits for the movie, but a build with no movie (or a finished one)
    # must still advance - a wait that never completes looks exactly like a
    # broken build.
    js = ck.VIDEO_SHIM_JS
    assert "if (!v.playing)" in js
    assert "nextOrder" in js
    assert "'ended'" in js and "'error'" in js


def test_video_shim_applies_the_kag3_box_over_tyrano_min_sizes():
    # Tyrano sets min-width/height:100% AFTER width/height, which silently
    # overrides KAG3's [video width=.. height=..] box (measured: the element
    # ended up 1024x768, the full canvas, instead of 800x600).
    js = ck.VIDEO_SHIM_JS
    assert "__kag3_vid_fit" in js
    assert "minWidth = '0'" in js and "minHeight = '0'" in js
    assert "objectFit = 'contain'" in js
    # ...and it must actually be applied when the movie starts
    play = js.split("tag['playvideo']")[1]
    assert "__kag3_vid_fit()" in play
