#!/usr/bin/env python3
"""Compress a JoiPlay folder into a `.7z` archive (7z + ZStandard).

Thin wrapper over `rpgmaker/archive.py`, which owns the archive format and
the py7zr backend (measured 1.7x faster than the 7-Zip CLI at the same
archive size; see that module's docstring).  Kept as its own module because
the rest of the toolkit and the tests use these two function names.

Exposed as a plain function + CLI subcommand; NOT run by default in the
pipeline (so the project stays testable).
"""
import logging

from . import archive, runtime

log = logging.getLogger("rpgmaker.compress")


def compress(folder, archive_path, level=archive.DEFAULT_LEVEL, threads=None,
             root=None):
    """Create a zstd 7z archive of `folder`. Returns the archive path.

    `root` sets the archive's top-level entry name (default: the folder's own
    basename) - `deliver` passes the delivered game name so the archive and
    the games-dir folder agree.

    Any existing file at `archive_path` is replaced (py7zr opens in "w"
    mode; the explicit removal keeps the log line and guards against a
    half-written leftover).

    `threads`: None = auto-tuned from the machine (`runtime.auto_workers`);
    an int forces that many processes for the extraction side.  py7zr has
    no compression-thread knob, so this no longer changes argv.
    """
    if threads is None:
        threads = runtime.auto_workers("compress", path=folder)
    return archive.create(folder, archive_path, level=level, threads=threads,
                          root=root)


def test_archive(archive_path):
    """Verify archive integrity (CRC pass). Returns True on success."""
    return archive.verify(archive_path)
