#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`tools/transcode_video.py`: one output name must have exactly one encoder.

KAG3 games routinely ship the same movie twice (.mpg and .wmv).  The tool used
to schedule both, both writing `<name>.webm`, so parallel workers raced on the
same path - measured on a real archive: 37 of 444 files failed the built-in
decode check ("output not decodable" / "incomplete output").

Also pinned here: a failed output is DELETED, because the cache rule is "the
file exists and probes" and a truncated file would otherwise be kept as cached
and stay broken forever.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from transcode_video import _drop_bad_output, dedupe_by_output  # noqa: E402


def entry(name):
    return {"name": name, "segments": []}


class TestDedupeByOutput:
    def test_same_stem_keeps_one_output(self):
        got = dedupe_by_output([entry("a/01_01.mpg"), entry("a/01_01.wmv")])
        assert len(got) == 1

    def test_prefers_the_configured_extension(self):
        got = dedupe_by_output([entry("01_01.mpg"), entry("01_01.wmv")])
        assert got[0]["name"].endswith(".wmv")

    def test_distinct_stems_are_all_kept(self):
        got = dedupe_by_output([entry("01_01.wmv"), entry("01_02.wmv"),
                                entry("s01_01_c.mpg")])
        assert len(got) == 3

    def test_avi_ranks_below_wmv_and_mpg(self):
        got = dedupe_by_output([entry("x.avi"), entry("x.mpg"), entry("x.wmv")])
        assert got[0]["name"] == "x.wmv"

    def test_case_and_path_insensitive_stem(self):
        got = dedupe_by_output([entry("dir/Clip.MPG"), entry("other/clip.wmv")])
        assert len(got) == 1

    def test_empty_input(self):
        assert dedupe_by_output([]) == []


class TestFailedOutputCleanup:
    def test_failed_output_is_deleted(self, tmp_path):
        dest = tmp_path / "bad.webm"
        dest.write_bytes(b"truncated")
        _drop_bad_output(str(dest))
        assert not dest.exists()

    def test_missing_file_is_tolerated(self, tmp_path):
        _drop_bad_output(str(tmp_path / "never-written.webm"))   # must not raise

    def test_good_output_is_untouched(self, tmp_path):
        dest = tmp_path / "ok.webm"
        dest.write_bytes(b"data")
        _drop_bad_output(str(tmp_path / "other.webm"))
        assert dest.is_file()
