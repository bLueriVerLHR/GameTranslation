#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Large-directory performance smoke test (review report §3.4 / D).

Principle: NO hard timing threshold that could flake on a slow machine.  The
primary assertions are behavioral - the walkers and the pipeline must touch
EVERY file in a large synthetic build - and a deliberately generous wall-clock
bound (60s) only guards against an O(n^2) regression (double copying, repeated
rescans), never against normal machine slowness.
"""
import io
import os
import time


from conftest import make_game

from rpgmaker import audio, build, runtime, verify


def make_large_game(root, n_maps=80, n_pngs=120, n_audio=60):
    """A synthetic game with many data JSONs, PNGs and audio files."""
    from PIL import Image
    web = make_game(root, with_movies=False, add_junk=False)
    data_dir = os.path.join(web, "data")
    png_dir = os.path.join(web, "img", "pictures")
    audio_dir = os.path.join(web, "audio", "bgm")
    for i in range(n_maps):
        with open(os.path.join(data_dir, "Map%03d.json" % (i + 1)),
                  "w", encoding="utf-8") as f:
            f.write('{"@name": "Map%03d", "displayName": "Map%03d", '
                    '"events": []}' % (i + 1, i + 1))
    for i in range(n_pngs):
        buf = io.BytesIO()
        Image.new("RGBA", (4, 4), (i % 256, 0, 0, 255)).save(buf, "PNG")
        with open(os.path.join(png_dir, "pic_%03d.png" % i), "wb") as f:
            f.write(buf.getvalue())
    for i in range(n_audio):
        with open(os.path.join(audio_dir, "bgm_%03d.ogg" % i), "wb") as f:
            f.write(b"O" * 20000)
    return web


class TestLargeBuildSmoke:
    def test_walkers_cover_every_file(self, tmp_path, fake_tools):
        """The corpus walkers must enumerate the whole large tree - a
        regression that silently drops files would hide below any timing
        bound, so the file COUNT is the hard assertion."""
        web = make_large_game(str(tmp_path / "src"))
        pngs = list(verify._iter_png_files(web))
        audios = list(audio.iter_audio_files(web))
        assert len(pngs) >= 120
        assert len(audios) >= 60
        # every generated file is reachable (no walker truncation)
        assert len({os.path.basename(p) for p in pngs}) >= 120
        assert len({os.path.basename(a) for a in audios}) >= 60

    def test_build_and_verify_large_tree_within_generous_bound(
            self, tmp_path, fake_tools):
        """Build + verify a several-hundred-file tree completes in reasonable
        time (generous 60s; only an O(n^2) regression would trip it)."""
        web = make_large_game(str(tmp_path / "src"))
        out = str(tmp_path / "out")
        t0 = time.monotonic()
        build.build_joiplay(web, out, workers=4)
        t_build = time.monotonic() - t0
        assert t_build < 60, "build took %.1fs - likely O(n^2) regression" % t_build

        t0 = time.monotonic()
        issues = verify.verify_all(out, workers=4)
        t_verify = time.monotonic() - t0
        assert issues == []
        assert t_verify < 60, \
            "verify took %.1fs - likely O(n^2) regression" % t_verify

        # every map JSON survived the build (count preserved through copy)
        n_built = len([f for f in os.listdir(os.path.join(out, "data"))
                       if f.startswith("Map") and f.endswith(".json")])
        assert n_built >= 80

    def test_audio_reencode_large_batch_smoke(self, tmp_path, fake_tools):
        """Probe + re-encode a batch of 60 files completes within the bound
        and reports per-file counts (no loss of files under load)."""
        web = make_large_game(str(tmp_path / "src"))
        infos = audio.probe_all(web, workers=4, sample=60)
        assert len(infos) == 60
        t0 = time.monotonic()
        counts, _saved = audio.reencode_all(web, infos, workers=4)
        elapsed = time.monotonic() - t0
        assert elapsed < 60, \
            "reencode took %.1fs - likely O(n^2) regression" % elapsed
        assert sum(counts.values()) == 60

    def test_auto_workers_parallelism_active(self, tmp_path, fake_tools):
        """The build path auto-tunes to >1 workers on a large tree (parallel
        copy is the optimization under test; a single-threaded regression
        would show up as workers == 1 here)."""
        web = make_large_game(str(tmp_path / "src"))
        workers = runtime.resolve_workers("copy", None, path=web)
        assert workers >= 2
