#!/usr/bin/env python3
"""Large-directory performance smoke test.

Principle: NO hard timing threshold that could flake on a slow machine.  The
primary assertions are behavioral - packaging must cover EVERY file in a large
tree and auto-tuning must still use more than one worker - and a deliberately
generous wall-clock bound (60s) only guards against an O(n^2) regression
(repeated rescans, double copying), never against normal machine slowness.

Marked `slow`: the point is scale (80 data files, 120 PNGs, 60 audio files),
so it belongs to the nightly layer rather than every run.
"""
import os
import time

import pytest

from tests.helpers import make_game, make_png_bytes

from rpgmaker import archive as archive_mod
from rpgmaker import compress, runtime

pytestmark = pytest.mark.slow


def make_large_game(root, n_maps=80, n_pngs=120, n_audio=60):
    """A synthetic game with many data JSONs, PNGs and audio files."""
    web = make_game(root, with_movies=False, add_junk=False)
    data_dir = os.path.join(web, "data")
    png_dir = os.path.join(web, "img", "pictures")
    audio_dir = os.path.join(web, "audio", "bgm")
    for i in range(n_maps):
        with open(os.path.join(data_dir, "Map%03d.json" % (i + 1)),
                  "w", encoding="utf-8") as f:
            f.write('{"@name": "Map%03d", "displayName": "Map%03d", '
                    '"events": []}' % (i + 1, i + 1))
    png = make_png_bytes(4, 4)
    for i in range(n_pngs):
        with open(os.path.join(png_dir, "pic_%03d.png" % i), "wb") as f:
            f.write(png)
    blob = b"O" * 20000
    for i in range(n_audio):
        with open(os.path.join(audio_dir, "bgm_%03d.ogg" % i), "wb") as f:
            f.write(blob)
    return web


class TestLargeTreeSmoke:
    def test_packaging_covers_every_file(self, tmp_path):
        """Every generated file must reach the archive: a regression that
        silently drops files would hide below any timing bound, so the member
        COUNT is the hard assertion."""
        web = make_large_game(str(tmp_path / "src"))
        archive = compress.compress(web, str(tmp_path / "g.7z"))
        names = archive_mod.names(archive)
        assert len([n for n in names if n.endswith(".png")]) >= 120
        assert len([n for n in names if n.endswith(".ogg")]) >= 60
        assert len([n for n in names
                    if os.path.basename(n).startswith("Map")]) >= 80

    def test_pack_and_extract_large_tree_within_generous_bound(self, tmp_path):
        """Pack + extract a several-hundred-file tree within the generous
        bound (only an O(n^2) regression would trip it)."""
        web = make_large_game(str(tmp_path / "src"))
        archive = str(tmp_path / "g.7z")
        started = time.monotonic()
        compress.compress(web, archive)
        took = time.monotonic() - started
        assert took < 60, f"packing took {took:.1f}s - likely O(n^2) regression"

        dest = str(tmp_path / "out")
        started = time.monotonic()
        archive_mod.extract(archive, dest)
        took = time.monotonic() - started
        assert took < 60, f"extraction took {took:.1f}s - likely O(n^2) regression"

        built = os.path.join(dest, "src", "data")
        n_built = len([f for f in os.listdir(built)
                       if f.startswith("Map") and f.endswith(".json")])
        assert n_built >= 80

    def test_auto_workers_parallelism_active(self, tmp_path):
        """Auto-tuning picks more than one worker on a large tree: a
        single-threaded regression would show up as workers == 1 here."""
        web = make_large_game(str(tmp_path / "src"))
        assert runtime.resolve_workers("compress", None, path=web) >= 2
