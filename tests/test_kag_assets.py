#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the parallelised KAG asset pass (kirikiri/kag/assets.py).

The image work (TLG/BMP/region -> PNG) moved into worker processes so it no
longer runs one image at a time (measured: 0.87 s per TLG image, 658 of them).
Parallelism is only safe if it is *observably* identical to the serial path:
same files, same bytes, same counters, same WARN lines.  These tests pin that
equivalence, plus the status accounting the parent aggregates, plus the asset
*folder mapping* (which used to be hardcoded to one game's layout and silently
dropped 84% of another game's assets).
"""
import hashlib
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri.kag import assets  # noqa: E402

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fixtures", "tlg")
REAL_TLG = "a_t002a.tlg"
REAL_BMP = "a_t002a.bmp"


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_digest(root):
    """{relative path: sha256} for every file under `root`."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            out[os.path.relpath(p, root).replace("\\", "/")] = _digest(p)
    return out


def _make_source(tmp_path):
    """A miniature unpacked KAG3 tree covering every job kind.

    - two real TLG fixture images (the expensive, CPU-bound path),
    - one real BMP fixture (PIL),
    - one indexed province image (`_p.png`, the region rewrite),
    - one broken TLG (the per-image failure fallback),
    - one plain asset (the thread-pooled copy path),
    - one nested subdirectory (recursive walk).
    """
    if not os.path.isfile(os.path.join(FIXTURE_DIR, REAL_TLG)):
        pytest.skip("no TLG fixtures present (tests/fixtures/tlg/)")
    root = tmp_path / "unpacked"
    (root / "fgimage" / "chara").mkdir(parents=True)
    (root / "bgimage").mkdir()
    (root / "bgm").mkdir()
    (root / "fgimage" / "chara" / "hero.tlg").write_bytes(
        open(os.path.join(FIXTURE_DIR, REAL_TLG), "rb").read())
    (root / "fgimage" / "hero2.tlg").write_bytes(
        open(os.path.join(FIXTURE_DIR, REAL_TLG), "rb").read())
    (root / "bgimage" / "telop.bmp").write_bytes(
        open(os.path.join(FIXTURE_DIR, REAL_BMP), "rb").read())
    (root / "fgimage" / "broken.tlg").write_bytes(b"TLG")     # undecodable
    (root / "bgm" / "theme.ogg").write_bytes(b"OggS-fake")    # plain copy

    pil = pytest.importorskip("PIL")
    from PIL import Image
    assert pil  # silence the linter about the unused import binding
    Image.new("P", (4, 3), 2).save(str(root / "fgimage" / "map_p.png"))
    return root


def _run(root, out, workers):
    stats = Counter()
    assets._convert_assets(str(root), str(out), stats, workers=workers)
    return stats


class TestParallelEqualsSerial:
    def test_same_files_same_bytes_same_stats(self, tmp_path):
        root = _make_source(tmp_path)
        serial, parallel = tmp_path / "out_serial", tmp_path / "out_par"
        s1 = _run(root, serial, 1)
        s2 = _run(root, parallel, 4)

        assert _tree_digest(serial) == _tree_digest(parallel)
        assert dict(s1) == dict(s2)
        # sanity: the fixture really exercised every path
        assert s1["tlg"] == 2 and s1["bmp"] == 1 and s1["region"] == 1
        assert s1["copied"] == 1
        assert s1["tlg_fail"] == 1

    def test_workers_one_never_builds_a_pool(self, tmp_path, monkeypatch):
        """`--workers 1` is the documented escape hatch back to serial: it must
        not spawn processes at all (authoring/debug runs)."""

        class _Boom:
            def __init__(self, *a, **kw):
                raise AssertionError("workers=1 must not start a process pool")

        monkeypatch.setattr(assets, "ProcessPoolExecutor", _Boom)
        root = _make_source(tmp_path)
        stats = _run(root, tmp_path / "out", 1)
        assert stats["tlg"] == 2

    def test_default_worker_count_comes_from_runtime(self, tmp_path, monkeypatch):
        """No hardcoded default: the pool size is the machine's physical cores
        (capped by the job count)."""
        seen = {}
        real = assets.runtime.resolve_workers

        def spy(kind, explicit=None, path=None):
            n = real(kind, explicit, path=path)
            seen[kind] = n
            return n

        monkeypatch.setattr(assets.runtime, "resolve_workers", spy)
        root = _make_source(tmp_path)
        _run(root, tmp_path / "out", None)
        assert seen["tlg"] == assets.runtime.physical_cpu_count()
        assert seen["copy"] == assets.runtime.auto_workers("copy")


class TestImageJobAccounting:
    def test_ok_cached_and_fail_statuses(self, tmp_path):
        if not os.path.isfile(os.path.join(FIXTURE_DIR, REAL_TLG)):
            pytest.skip("no TLG fixtures present")
        src = tmp_path / "in.tlg"
        src.write_bytes(open(os.path.join(FIXTURE_DIR, REAL_TLG), "rb").read())
        dst = tmp_path / "out.png"

        assert assets._image_job(str(src), str(dst), "tlg") == ("tlg", "ok", None)
        assert dst.is_file()
        # a second run sees an up-to-date target
        assert assets._image_job(str(src), str(dst), "tlg") == ("tlg", "cached", None)

        bad = tmp_path / "bad.tlg"
        bad.write_bytes(b"not a tlg")
        kind, status, err = assets._image_job(str(bad), str(tmp_path / "bad.png"), "tlg")
        assert (kind, status) == ("tlg", "fail")
        assert err and "bad.tlg" not in err       # the caller adds the path

    def test_results_are_folded_into_stats_and_log(self, tmp_path, caplog):
        stats = Counter()
        bad = tmp_path / "broken.tlg"
        bad.write_bytes(b"TLG")
        with caplog.at_level("WARNING", logger="kirikiri.kag.assets"):
            assets._apply_image_result(
                stats, str(bad), *assets._image_job(str(bad), str(tmp_path / "b.png"),
                                                    "tlg"))
        assert stats["tlg_fail"] == 1
        assert any("tlg convert failed" in r.message for r in caplog.records), \
            "the WARN text is part of the owner's workflow (grep-able log)"

    def test_kind_labels_cover_every_image_kind(self):
        assert set(assets._FAIL_LABEL) == set(assets.IMAGE_KINDS)
