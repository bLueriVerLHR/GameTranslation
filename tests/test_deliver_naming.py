#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`rpgmaker/deliver.py`: delivered name + integrity test on the real archive.

Two defects found while delivering a build kept in a work slot:

  * the delivered archive/folder name was always the *folder's* basename, so a
    build living in `.../out/` would ship as `out.7z` / `Games/out/`;
  * `compress` appends `.7z` to a *relative* path (historical `-o` semantics)
    and returns the path it wrote, but `deliver` integrity-tested the path it
    had *requested* - with `--archive "<name>"` that path does not exist and the
    run died with a bogus "local archive failed integrity test".

The fakes below keep it hermetic (no real 7z work, no delivery dirs touched).
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rpgmaker import deliver as deliver_mod  # noqa: E402


class _FakeCompress:
    """Mimics rpgmaker.archive: writes `<path>.7z` for a relative request.

    `root` is the archive's stored top-level entry name (deliver passes the
    delivered game name so the archive and the games-dir folder agree); the
    fake records it so tests can assert the contract without real 7z work.
    """

    def __init__(self):
        self.created = None
        self.roots = []

    def compress(self, folder, archive, level=15, root=None):
        self.roots.append(root)
        path = Path(archive)
        if not str(path).endswith(".7z") and not path.is_absolute():
            path = Path(str(path) + ".7z")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"7z-data")
        self.created = path
        return str(path)

    def test_archive(self, archive):
        # the integrity test must be handed the file that exists
        return Path(archive).is_file()


@pytest.fixture
def wired(tmp_path, monkeypatch):
    fake = _FakeCompress()
    monkeypatch.setattr(deliver_mod, "compress_mod", fake)
    monkeypatch.setattr(deliver_mod, "config", _Config(tmp_path))
    monkeypatch.setattr(deliver_mod, "shutil", _NoCopy())
    # The real extraction needs a real 7z; the fake archive is not one.
    monkeypatch.setattr(deliver_mod, "_extract", _fake_extract)
    return fake


def _fake_extract(archive, dest_root, name):
    """Stand-in for the extract step: materialise the delivered folder."""
    target = Path(dest_root) / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text("<html></html>", encoding="utf-8")
    return target


def fake_roots(fake):
    """Archive root names deliver() asked for (one per compress call)."""
    return fake.roots


class _Config:
    def __init__(self, tmp_path):
        self._tmp = tmp_path

    def archives_dir(self):
        return str(self._tmp / "archives")

    def games_dir(self):
        return str(self._tmp / "games")

    def temp_dir(self):
        return str(self._tmp / "temp")

    def is_windows_side(self, _path):
        return False


class _NoCopy:
    """Copy without the 1 GB IO: record the call instead."""

    def __init__(self):
        self.calls = []

    def copy2(self, src, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(Path(src).read_bytes())
        self.calls.append((str(src), str(dst)))
        return str(dst)

    def rmtree(self, path, **kwargs):
        import shutil as _sh
        _sh.rmtree(path, **kwargs)


def _build(tmp_path, folder_name="out"):
    folder = tmp_path / folder_name
    (folder / "data").mkdir(parents=True)
    (folder / "index.html").write_text("<html></html>", encoding="utf-8")
    return folder


class TestDeliveredName:
    def test_name_overrides_the_folder_basename(self, tmp_path, wired):
        folder = _build(tmp_path)
        out = deliver_mod.deliver(str(folder), name="My Game",
                                  archives=str(tmp_path / "archives"),
                                  games=str(tmp_path / "games"))
        assert Path(out).name == "My Game.7z"
        assert (tmp_path / "archives" / "My Game.7z").is_file()
        # extracted folder is the delivered name, contents at its root
        target = tmp_path / "games" / "My Game"
        assert target.is_dir() and (target / "index.html").is_file()
        assert not (tmp_path / "games" / "out").exists()
        # the archive itself must store the delivered name, not the work-slot
        # basename: every previously delivered archive here has the game name
        # as its root entry (extracting that .7z elsewhere must not yield
        # "out/").
        assert fake_roots(wired) == ["My Game"]

    def test_archive_root_follows_name_for_a_slot_build(self, tmp_path, wired):
        """A build in `.../out/` delivered as `Real` stores `Real/`."""
        folder = _build(tmp_path, "out")
        deliver_mod.deliver(str(folder), name="Real",
                           archives=str(tmp_path / "archives"),
                           games=str(tmp_path / "games"))
        assert fake_roots(wired) == ["Real"]

    def test_without_name_it_uses_the_folder(self, tmp_path, wired):
        folder = _build(tmp_path, "somegame")
        out = deliver_mod.deliver(str(folder),
                                  archives=str(tmp_path / "archives"),
                                  games=str(tmp_path / "games"))
        assert Path(out).name == "somegame.7z"
        assert (tmp_path / "games" / "somegame").is_dir()
        assert fake_roots(wired) == ["somegame"]


class TestArchivePath:
    def test_relative_archive_is_tested_at_the_path_actually_written(
            self, tmp_path, wired, monkeypatch):
        """Regression: --archive "<name>" must not die on a bogus path.

        archive.create appends .7z to a relative request, so the file lands at
        "<name>.7z" - testing the requested "<name>" failed the whole delivery.
        """
        folder = _build(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = deliver_mod.deliver(str(folder), archive="relative-name",
                                  archives=str(tmp_path / "archives"),
                                  games=str(tmp_path / "games"))
        assert wired.created.name == "relative-name.7z"
        assert Path(out).is_file()    # copied into the archives dir

    def test_failed_integrity_test_still_raises(self, tmp_path, monkeypatch,
                                                wired):
        class _Bad(_FakeCompress):
            def test_archive(self, archive):
                return False

        monkeypatch.setattr(deliver_mod, "compress_mod", _Bad())
        folder = _build(tmp_path)
        with pytest.raises(RuntimeError, match="integrity test"):
            deliver_mod.deliver(str(folder), name="x",
                                archives=str(tmp_path / "archives"),
                                games=str(tmp_path / "games"))


def test_cli_deliver_passes_name(monkeypatch, tmp_path):
    """`deliver --name` must reach the delivery: a build living in a work slot
    (basename != real game name) has to be delivered under its real name."""
    from rpgmaker import cli as cli_mod

    seen = {}

    def fake_deliver(folder, name=None, level=15, **kwargs):
        seen.update({"folder": folder, "name": name, "level": level})
        return str(tmp_path / "out.7z")

    monkeypatch.setattr(cli_mod.deliver, "deliver", fake_deliver)
    cli_mod.cmd_deliver(str(tmp_path / "slot_build"), name="Real Name",
                        level=9)
    assert seen == {"folder": str(tmp_path / "slot_build"),
                    "name": "Real Name", "level": 9}
    # Typer passes the option's value through as-is, and omitting the option
    # yields None (which deliver() turns into the folder basename).
    cli_mod.cmd_deliver(str(tmp_path / "slot_build"), name=None)
    assert seen["name"] is None
