"""Stale raw movie containers must not survive next to their converted WebM.

Measured on a real game: the first port ran before the WebM transcode cache
existed, so the video pass copied 446 raw .mpg/.wmv into data/video/.  Once the
cache was in place the pass added the 222 .webm but left the raw copies behind
(~1.3 GiB of files no browser can play), and the build silently grew to 1948 MiB.
The pass must clean up after itself, while never touching a video that really
has no converted counterpart.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri.kag import assets  # noqa: E402


def _stats():
    return {"video": 0, "video_raw": 0}


def _run(tmp_path, src_files, cache_files, out_files):
    src = tmp_path / "src"
    (src / "others").mkdir(parents=True)
    for name in src_files:
        (src / "others" / name).write_bytes(b"raw")
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in cache_files:
        (cache / name).write_bytes(b"webm")
    out = tmp_path / "out" / "data"
    (out / "video").mkdir(parents=True)
    for name in out_files:
        (out / "video" / name).write_bytes(b"stale")
    stats = _stats()
    vmap = assets._convert_videos(str(src), str(out), str(cache), stats)
    return sorted(os.listdir(out / "video")), stats, vmap


def test_stale_raw_is_removed_when_a_webm_exists(tmp_path):
    got, stats, vmap = _run(tmp_path, ["op.mpg"], ["op.webm"], ["op.mpg"])
    assert got == ["op.webm"]
    assert stats["video"] == 1 and stats["video_raw"] == 0
    assert stats["video_stale"] == 1
    assert vmap["op"] == "op.webm"


def test_stale_pair_is_cleaned_for_each_source(tmp_path):
    """A raw .mpg + .wmv pair maps onto one WebM; both leftovers must go."""
    got, stats, _vmap = _run(
        tmp_path, ["op.mpg", "op.wmv"], ["op.webm"], ["op.mpg", "op.wmv"])
    assert got == ["op.webm"]
    assert stats["video_stale"] == 2
    assert stats["video_raw"] == 0


def test_raw_is_kept_when_there_is_really_no_webm(tmp_path):
    got, stats, vmap = _run(tmp_path, ["op.mpg"], [], [])
    assert got == ["op.mpg"]
    assert stats["video_raw"] == 1 and stats["video_stale"] == 0
    assert vmap["op"] == "op.mpg"       # the runtime resolver still finds it


def test_unrelated_extension_with_same_stem_is_never_touched(tmp_path):
    """Only raw containers of this stem may be removed - a .png of the same
    stem is an unrelated asset."""
    got, stats, _vmap = _run(
        tmp_path, ["op.mpg"], ["op.webm"], ["op.png"])
    assert got == ["op.png", "op.webm"]
    assert stats["video_stale"] == 0


def test_other_videos_are_not_touched_by_this_iteration(tmp_path):
    got, stats, _vmap = _run(
        tmp_path, ["op.mpg"],
        ["op.webm"],
        ["op.mpg", "ed.mpg", "ed.wmv"])   # ed.* belong to a video not in src
    assert got == ["ed.mpg", "ed.wmv", "op.webm"]
    assert stats["video_stale"] == 1


def test_no_stale_file_means_nothing_reported(tmp_path):
    got, stats, _vmap = _run(tmp_path, ["op.wmv"], ["op.webm"], [])
    assert got == ["op.webm"]
    assert stats["video_stale"] == 0
