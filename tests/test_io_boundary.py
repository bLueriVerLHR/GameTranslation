#!/usr/bin/env python3
"""The shared I/O boundary (PLAN Phase 6 task 4).

`rpgmaker/io_boundary.py` is judged by three properties that a plain
`open(path, "w")` does **not** have, so each gets a test that fails without it:

* a reader never sees a partial file (atomicity),
* a failed write does not destroy the previous content,
* a BOM is accepted on read and never invented on write.

The atomicity tests are the load-bearing ones.  "Write a temp file and rename
it" looks correct and is trivially got wrong (temp in the system directory ->
`os.replace` raises `EXDEV`; `chmod` before the rename on a first write ->
`FileNotFoundError`; no cleanup -> a stray `.gt-tmp-*` per crash), so the
failure paths are tested directly rather than only the happy path.
"""
import errno
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from rpgmaker import io_boundary  # noqa: E402


def _leftovers(directory):
    """Temporary files the boundary failed to clean up."""
    return [n for n in os.listdir(directory) if n.startswith(".gt-tmp-")]


class TestAtomicWrites:
    def test_write_text_replaces_the_previous_content(self, tmp_path):
        target = tmp_path / "state.txt"
        io_boundary.write_text(target, "first\n")
        io_boundary.write_text(target, "second\n")
        assert io_boundary.load_text(target) == "second\n"

    def test_no_temporary_survives_a_successful_write(self, tmp_path):
        io_boundary.write_text(tmp_path / "a.txt", "x")
        io_boundary.dump_json(tmp_path / "b.json", {"k": 1})
        assert _leftovers(tmp_path) == []

    def test_the_temporary_is_created_beside_the_target(self, tmp_path):
        """The temp must share the target's directory or `os.replace` can fail.

        `os.replace` across filesystems raises `OSError: [Errno 18] Invalid
        cross-device link`, and `%TEMP%` is routinely on another drive than the
        file being written - so the boundary must not accept a temp directory.
        """
        seen = []
        real_mkstemp = io_boundary.tempfile.mkstemp

        def spy(*args, **kwargs):
            seen.append(kwargs.get("dir"))
            return real_mkstemp(*args, **kwargs)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(io_boundary.tempfile, "mkstemp", spy)
            io_boundary.write_text(tmp_path / "sub" / "deep.txt", "x")
        assert seen == [str(tmp_path / "sub")]

    def test_a_failed_write_keeps_the_previous_content(self, tmp_path):
        target = tmp_path / "state.json"
        io_boundary.dump_json(target, {"good": True})
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(io_boundary.os, "replace",
                          _raise(OSError(errno.EXDEV, "Invalid cross-device link")))
            with pytest.raises(OSError):
                io_boundary.dump_json(target, {"good": False})
        assert io_boundary.load_json(target) == {"good": True}

    def test_a_failed_write_leaves_no_temporary_behind(self, tmp_path):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(io_boundary.os, "replace", _raise(OSError("nope")))
            with pytest.raises(OSError):
                io_boundary.write_text(tmp_path / "a.txt", "x")
        assert _leftovers(tmp_path) == []

    def test_an_interrupted_write_also_cleans_up(self, tmp_path):
        """A KeyboardInterrupt is the most likely interruption, not an edge case.

        Catching only `Exception` here would leak the temporary on precisely
        the Ctrl-C this function is supposed to make safe.
        """
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(io_boundary.os, "replace",
                          _raise(KeyboardInterrupt()))
            with pytest.raises(KeyboardInterrupt):
                io_boundary.write_text(tmp_path / "a.txt", "x")
        assert _leftovers(tmp_path) == []

    def test_a_first_write_succeeds_without_an_existing_target(self, tmp_path):
        """`chmod` has nothing to copy from on a first write and must not raise."""
        target = tmp_path / "fresh.txt"
        io_boundary.write_text(target, "x")
        assert target.read_text(encoding="utf-8") == "x"

    def test_an_existing_mode_survives_a_rewrite(self, tmp_path):
        """The rewrite must not change the target's permissions.

        This is the test that catches a boundary which forgets to carry the
        old mode onto the fresh temporary: `mkstemp` creates 0600, so on POSIX
        a rewrite without the `chmod` step silently narrows the file.  On
        Windows `chmod` only toggles the read-only bit, so the invariant is
        asserted as "unchanged" rather than as an exact number - which is the
        property that actually matters and holds on both platforms.
        """
        target = tmp_path / "mode.txt"
        io_boundary.write_text(target, "old")
        os.chmod(target, 0o640)
        before = os.stat(target).st_mode & 0o777
        io_boundary.write_text(target, "new")
        assert os.stat(target).st_mode & 0o777 == before
        assert io_boundary.load_text(target) == "new"

    def test_where_chmod_is_unsupported_the_write_still_lands(self, tmp_path):
        target = tmp_path / "x.txt"
        io_boundary.write_text(target, "old")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(io_boundary.os, "chmod", _raise(OSError("EACCES")))
            io_boundary.write_text(target, "new")
        assert io_boundary.load_text(target) == "new"

    def test_durable_writes_still_produce_the_same_bytes(self, tmp_path):
        """`durable` is a durability knob, not a formatting one."""
        plain = tmp_path / "plain.json"
        synced = tmp_path / "synced.json"
        io_boundary.dump_json(plain, {"k": "值"})
        io_boundary.dump_json(synced, {"k": "值"}, durable=True)
        assert plain.read_bytes() == synced.read_bytes()

    def test_the_parent_directory_is_created(self, tmp_path):
        target = tmp_path / "a" / "b" / "c.json"
        io_boundary.dump_json(target, {"k": 1})
        assert target.exists()

    def test_ensure_parent_false_reports_the_missing_directory(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            io_boundary.write_text(tmp_path / "nope" / "x.txt", "x",
                                    ensure_parent=False)


class TestByteExactStyles:
    def test_pretty_json_is_indent_one_with_a_trailing_newline(self, tmp_path):
        target = tmp_path / "stats.json"
        io_boundary.dump_json(target, {"keys": 3})
        assert target.read_text(encoding="utf-8") == '{\n "keys": 3\n}\n'

    def test_compact_json_has_no_spaces_and_no_trailing_newline(self, tmp_path):
        """The style of the files shipped *inside* the game.

        `js/plugins.js` and `data/System.json` are written back into a
        third-party build; several tests pin their exact bytes, so the
        separator style is part of the contract and not a preference.
        """
        target = tmp_path / "plugins.js"
        io_boundary.dump_json(target, [{"a": 1, "b": "值"}], compact=True)
        assert target.read_text(encoding="utf-8") == '[{"a":1,"b":"值"}]'

    def test_compact_json_can_ask_for_a_trailing_newline(self, tmp_path):
        target = tmp_path / "x.json"
        io_boundary.dump_json(target, {"a": 1}, compact=True,
                              trailing_newline=True)
        assert target.read_text(encoding="utf-8") == '{"a":1}\n'

    def test_pretty_json_can_suppress_the_trailing_newline(self, tmp_path):
        target = tmp_path / "x.json"
        io_boundary.dump_json(target, {"a": 1}, trailing_newline=False)
        assert target.read_text(encoding="utf-8") == '{\n "a": 1\n}'

    def test_non_ascii_is_written_literally(self, tmp_path):
        """`ensure_ascii=False`: the files are read and diffed by humans."""
        target = tmp_path / "kv.json"
        io_boundary.dump_json(target, {"朝": "晨"})
        assert "朝" in target.read_text(encoding="utf-8")
        assert "\\u" not in target.read_text(encoding="utf-8")

    def test_sort_keys_is_available_for_reproducible_output(self, tmp_path):
        target = tmp_path / "s.json"
        io_boundary.dump_json(target, {"b": 1, "a": 2}, sort_keys=True)
        assert target.read_text(encoding="utf-8") == '{\n "a": 2,\n "b": 1\n}\n'


class TestByteExactLineEndings:
    def test_lf_is_written_on_every_platform(self, tmp_path):
        """CRLF here would change every line of a file the build gates compare."""
        target = tmp_path / "a.txt"
        io_boundary.write_text(target, "one\ntwo\n")
        assert target.read_bytes() == b"one\ntwo\n"

    def test_appending_also_uses_lf(self, tmp_path):
        target = tmp_path / "a.txt"
        io_boundary.write_text(target, "one\n")
        io_boundary.append_text(target, "two\n")
        assert target.read_bytes() == b"one\ntwo\n"

    def test_an_empty_write_creates_an_empty_file(self, tmp_path):
        target = tmp_path / "empty.txt"
        io_boundary.write_text(target, "")
        assert target.read_bytes() == b""

    def test_bytes_are_utf8_not_the_locale_encoding(self, tmp_path):
        target = tmp_path / "cjk.txt"
        io_boundary.write_text(target, "日本語\n")
        assert target.read_bytes() == "日本語\n".encode()


class TestBomHandling:
    def test_a_bom_is_stripped_on_read(self, tmp_path):
        target = tmp_path / "bom.json"
        target.write_bytes(b'\xef\xbb\xbf{"k": 1}')
        assert io_boundary.load_json(target) == {"k": 1}

    def test_load_text_tolerates_a_bom(self, tmp_path):
        target = tmp_path / "tone.md"
        target.write_bytes(b"\xef\xbb\xbfabc")
        assert io_boundary.load_text(target).lstrip("\ufeff") == "abc"

    def test_a_bom_is_never_written(self, tmp_path):
        """Editing a file must not silently add three bytes to it.

        `rpgmaker/plugincompat.py` keeps a comment about a writer that would
        have done exactly this, so it is pinned rather than assumed.
        """
        target = tmp_path / "no-bom.json"
        io_boundary.dump_json(target, {"k": "值"})
        assert not target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_the_bom_constant_is_the_character_a_reader_strips(self):
        assert io_boundary.BOM == "\ufeff"


class TestJsonl:
    def test_round_trip_of_three_records(self, tmp_path):
        target = tmp_path / "pending.jsonl"
        for payload in ({"id": 1}, {"id": 2, "t": "值"}, {"id": 3}):
            io_boundary.append_jsonl(target, payload)
        assert io_boundary.read_jsonl(target) == [{"id": 1},
                                                  {"id": 2, "t": "值"},
                                                  {"id": 3}]

    def test_each_record_is_one_line(self, tmp_path):
        target = tmp_path / "l.jsonl"
        io_boundary.append_jsonl(target, {"id": 1})
        io_boundary.append_jsonl(target, {"id": 2})
        assert target.read_bytes() == b'{"id": 1}\n{"id": 2}\n'

    def test_a_missing_file_reads_as_empty(self, tmp_path):
        assert io_boundary.read_jsonl(tmp_path / "absent.jsonl") == []

    def test_blank_lines_are_skipped(self, tmp_path):
        target = tmp_path / "l.jsonl"
        target.write_text('{"id": 1}\n\n   \n{"id": 2}\n', encoding="utf-8")
        assert io_boundary.read_jsonl(target) == [{"id": 1}, {"id": 2}]

    def test_a_bad_line_raises_naming_path_and_line(self, tmp_path):
        """Silently dropping it would turn "damaged" into "nothing to do"."""
        target = tmp_path / "l.jsonl"
        target.write_text('{"id": 1}\nnot json\n', encoding="utf-8")
        with pytest.raises(ValueError) as excinfo:
            io_boundary.read_jsonl(target)
        message = str(excinfo.value)
        assert "l.jsonl:2:" in message
        assert "bad JSON line" in message

    def test_a_truncated_last_line_is_reported_not_ignored(self, tmp_path):
        """The interrupted-writer case: a half-written JSONL line."""
        target = tmp_path / "l.jsonl"
        target.write_text('{"id": 1}\n{"id": 2, "tex', encoding="utf-8")
        with pytest.raises(ValueError):
            io_boundary.read_jsonl(target)

    def test_the_bom_a_windows_editor_added_does_not_break_the_first_record(
            self, tmp_path):
        target = tmp_path / "l.jsonl"
        io_boundary.append_jsonl(target, {"id": 1})
        target.write_bytes(b"\xef\xbb\xbf" + target.read_bytes())
        assert io_boundary.read_jsonl(target) == [{"id": 1}]


class TestLoadErrorsAreNotSwallowed:
    def test_a_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            io_boundary.load_json(tmp_path / "absent.json")

    def test_malformed_json_raises_jsondecodeerror(self, tmp_path):
        target = tmp_path / "bad.json"
        target.write_text("{not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            io_boundary.load_json(target)

    def test_an_empty_file_is_a_decode_error_not_a_silent_none(self, tmp_path):
        target = tmp_path / "empty.json"
        target.write_text("", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            io_boundary.load_json(target)


class TestBackupFile:
    def test_the_first_copy_wins(self, tmp_path):
        """The backup's job is to hold the *pre-patch* content.

        Overwriting it on a second pass would replace the original with
        post-patch text and destroy the only route back - the exact failure a
        backup is supposed to prevent.
        """
        source = tmp_path / "game" / "js" / "plugins.js"
        source.parent.mkdir(parents=True)
        source.write_text("original", encoding="utf-8")
        root = tmp_path / "backup"
        assert io_boundary.backup_file(source, root, "js/plugins.js") == "js/plugins.js"
        source.write_text("patched", encoding="utf-8")
        io_boundary.backup_file(source, root, "js/plugins.js")
        assert (root / "js" / "plugins.js").read_text(encoding="utf-8") == "original"

    def test_the_intermediate_directories_are_created(self, tmp_path):
        source = tmp_path / "a.txt"
        source.write_text("x", encoding="utf-8")
        io_boundary.backup_file(source, tmp_path / "deep" / "root", "a.txt")
        assert (tmp_path / "deep" / "root" / "a.txt").exists()

    def test_a_missing_source_backs_up_nothing(self, tmp_path):
        assert io_boundary.backup_file(tmp_path / "absent.txt",
                                       tmp_path / "b") is None
        assert not (tmp_path / "b").exists()

    def test_the_relative_name_defaults_to_the_basename(self, tmp_path):
        source = tmp_path / "x" / "a.txt"
        source.parent.mkdir()
        source.write_text("v", encoding="utf-8")
        assert io_boundary.backup_file(source, tmp_path / "b") == "a.txt"

    def test_pathlib_arguments_are_accepted(self, tmp_path):
        """Every caller has a Path; requiring `str` would force a conversion."""
        source = tmp_path / "p.txt"
        source.write_text("v", encoding="utf-8")
        assert io_boundary.backup_file(source, tmp_path / "b",
                                       "p.txt") == "p.txt"


class TestTheBoundaryIsActuallyUsed:
    def test_the_module_is_registered_in_the_inventory(self):
        """An unregistered production module fails `tests/test_inventory.py`.

        Pinned here too so the failure names the cause: a new core module that
        is not in the inventory is invisible to the CLI smoke matrix and to
        the packaging checks.
        """
        from rpgmaker import inventory
        names = {record.module for record in inventory.MODULES}
        assert "rpgmaker.io_boundary" in names

    def test_it_is_documented_as_the_single_entry_point(self):
        from pathlib import Path
        tooling = Path(REPO_ROOT) / "docs" / "reference" / "tooling.md"
        body = tooling.read_text(encoding="utf-8")
        assert "io_boundary" in body

    def test_it_does_not_import_an_engine(self):
        """Core must not depend on an engine (PLAN Phase 3 task 7)."""
        source = (os.path.join(REPO_ROOT, "rpgmaker", "io_boundary.py"))
        body = open(source, encoding="utf-8").read()
        for engine in ("kirikiri", "tyrano", "wolfrpg", "unity"):
            assert f"import {engine}" not in body


def _raise(error):
    """A stand-in that raises `error` when called (monkeypatch helper)."""
    def fail(*_args, **_kwargs):
        raise error
    return fail
