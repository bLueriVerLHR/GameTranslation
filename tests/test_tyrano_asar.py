#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for tyrano/asar.py - asar access through the ``asar`` package.

`tyrano/asar.py` used to run `npx @electron/asar` for every operation, which
made a Node.js install (and a possible package download on a cold npx cache)
a hard requirement of the Tyrano build.  It now uses the pure-Python ``asar``
package.

The regression fixture `tests/fixtures/tiny_app.asar` was packed by the
**official** Node tool (see the generation note in the repo history), so these
tests read a real, externally produced archive rather than something the
package under test wrote itself.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tyrano import asar as asar_mod  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "tiny_app.asar")

asar = pytest.importorskip("asar", reason="the 'asar' package is optional")


class TestRealArchive:
    """An archive produced by `npx @electron/asar pack`."""

    def test_list_files_returns_plain_paths(self):
        names = asar_mod.list_files(FIXTURE)
        assert "index.html" in names
        assert "data/System.json" in names
        # the Node CLI prints backslash-separated paths on Windows; the
        # wrapper normalises to forward slashes
        assert not any("\\" in n for n in names)

    def test_extract_writes_the_files(self, tmp_path):
        out = tmp_path / "out"
        assert asar_mod.extract(FIXTURE, str(out)) == str(out)
        html = (out / "index.html").read_text(encoding="utf-8")
        assert "tiny app" in html
        data = json.loads((out / "data" / "System.json").read_text("utf-8"))
        assert data == {"gameTitle": "tiny", "version": 1}

    def test_nested_directory_is_recreated(self, tmp_path):
        out = tmp_path / "out"
        asar_mod.extract(FIXTURE, str(out))
        assert (out / "data").is_dir()
        assert sorted(p.name for p in (out / "data").iterdir()) == \
            ["Config.tjs", "System.json"]

    def test_missing_archive_raises_before_creating_output(self, tmp_path):
        out = tmp_path / "nope"
        with pytest.raises(FileNotFoundError):
            asar_mod.extract(str(tmp_path / "missing.asar"), str(out))
        assert not out.exists()

    def test_list_missing_archive_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            asar_mod.list_files(str(tmp_path / "missing.asar"))


class TestRoundTripThroughThePackage:
    """Packing with the package and reading it back (unpacked entries too)."""

    def make_source(self, tmp_path):
        src = tmp_path / "src"
        (src / "data").mkdir(parents=True)
        (src / "index.html").write_text("<html>x</html>", encoding="utf-8")
        (src / "tiny.bin").write_bytes(bytes(range(256)))
        (src / "data" / "System.json").write_text('{"a": 1}', encoding="utf-8")
        return src

    def test_unpacked_entry_round_trip(self, tmp_path):
        src = self.make_source(tmp_path)
        archive = tmp_path / "app.asar"
        asar.create_archive(src, archive, unpack="*.bin")
        out = tmp_path / "out"
        asar_mod.extract(str(archive), str(out))
        assert (out / "tiny.bin").read_bytes() == bytes(range(256))
        assert (out / "index.html").read_text(encoding="utf-8") == \
            "<html>x</html>"

    def test_list_matches_the_files_on_disk(self, tmp_path):
        src = self.make_source(tmp_path)
        archive = tmp_path / "app.asar"
        asar.create_archive(src, archive)
        names = set(asar_mod.list_files(str(archive)))
        assert {"index.html", "tiny.bin", "data/System.json"} <= names


class TestCli:
    def test_list_command_prints_every_entry(self, capsys):
        assert asar_mod.main(["list", FIXTURE]) == 0
        out = capsys.readouterr().out
        assert "index.html" in out and "data/System.json" in out

    def test_extract_command_writes_files(self, tmp_path, capsys):
        out = tmp_path / "cli-out"
        assert asar_mod.main(["extract", FIXTURE, str(out)]) == 0
        assert (out / "index.html").is_file()
        assert "extracted" not in capsys.readouterr().out  # log goes to stderr

    def test_extract_command_fails_on_a_missing_archive(self, tmp_path,
                                                        capsys):
        with pytest.raises(FileNotFoundError):
            asar_mod.main(["extract", str(tmp_path / "no.asar"),
                           str(tmp_path / "out")])

    def test_unknown_subcommand_is_a_usage_error(self, capsys):
        assert asar_mod.main(["nope"]) == 2

    def test_help_returns_zero(self, capsys):
        assert asar_mod.main(["--help"]) == 0
        assert "Usage:" in capsys.readouterr().out


class TestNoNodeDependency:
    def test_module_does_not_shell_out(self):
        """The point of the swap: no subprocess, no npx, no Node.js."""
        import inspect

        source = inspect.getsource(asar_mod)
        code = source.split('"""', 2)[2]      # drop the module docstring
        assert "proctools" not in code
        assert "subprocess" not in code
        assert "find_npx" not in code
