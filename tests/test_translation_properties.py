#!/usr/bin/env python3
"""Property tests for the translation data contract and the config schema.

PLAN Phase 5 task 5 asks for properties over *control-code parse/render*,
*translation raw library atomic I/O* and *profile/schema*.  These three are
the places where a single wrong character silently destroys work:

  * the control-code helpers decide what a translator may and may not change,
    so "splitting a string keeps every character, in order" and "a code is
    never split" must hold for *any* string - not just the examples;
  * ``translations.raw.txt`` is the only durable translation store (the
    library is append-only and the executors' reasoning is gone), so writing
    and reading it back must be lossless for any value the batch format can
    express - including values that end in a newline (a real MZ build could
    never translate 10 ``Items.json`` descriptions until this held);
  * the machine config rejects the whole file on any problem, so the schema
    check must be total: no input shape may raise, and an unknown section can
    never be silently accepted.

The library property is careful about *what the format can express*: a block
is ``@@@id@@@`` + lines, and a value whose text contains a line looking like a
header would be ambiguous, so the generator excludes that shape.  Every other
value round-trips byte for byte.
"""

import json
import os
import sys
import tempfile

import pytest
from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from rpgmaker import settings  # noqa: E402
from translation import codes, rawlib  # noqa: E402

#: Ids are opaque to the library, but '@@@' inside one is rejected by
#: ``append_block`` (it would forge a header), so the generator keeps it out.
IDS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789._-", min_size=1,
              max_size=8)
#: Characters that carry meaning for the block format, and which a plain
#: ``st.text()`` finds only by luck.  Phase 5 proved the luck is not enough:
#: reverting the CR fix left the property test GREEN because Hypothesis never
#: generated an interior ``\r`` in that run - only the two explicit example
#: tests in ``TestBareCarriageReturn`` failed.  Mixing these in makes the
#: generator produce the interesting shapes on (almost) every run, so the
#: property keeps working as a regression test rather than a formality.
#: ``@@@`` is deliberately absent: a header-looking line is a format limit, not
#: data, and that is filtered out below.
MEANINGFUL = "\\[]\n\r<>"
#: Values: any text the block format can express.  Two shapes cannot, and the
#: filter is why the round-trip property is a *true* statement rather than a
#: passing test with a hole in it:
#:   * a line that looks like an ``@@@id@@@`` header would be read as a new
#:     block (the extractor guarantees no source string starts that way);
#:   * a value *ending* in a bare ``\r``: the last line's CR is
#:     indistinguishable from a CRLF ending, so ``rstrip("\r")`` eats it.
#:
#: ``\r`` as a whole was also filtered here until Phase 5, described as "the
#: reader normalises CRLF to LF on purpose" - but only the CR of an *interior*
#: CRLF was intended.  A bare CR is data: ``append_block`` stored it verbatim
#: while the reader (default universal newlines) folded it into a line break, so
#: the library could hold a value it could never read back.  ``read_library`` now
#: opens with ``newline="\n"``, and ``TestBareCarriageReturn`` pins the fix, so
#: this generator accepts interior bare CRs again instead of hiding the bug.
#:
#: The filter is about what the *format* can express, and a CR is only lost when
#: it sits at a line boundary: a value ending in CR (its CR looks like a CRLF
#: tail) or one containing CRLF (its lines are rejoined with LF, because the
#: line-break gate counts ``\n`` only).  Both limits are pinned separately by
#: ``TestBareCarriageReturn``; an interior **bare** CR is real data and now
#: round-trips.  Surrogates are excluded - see ``_has_surrogate``.
def _has_surrogate(text):
    """True when `text` holds a lone surrogate code point.

    Hypothesis' ``st.characters()`` can emit one (`\ud800`).  A Python ``str``
    may hold it, but no text file can: ``TextIOWrapper`` encodes with UTF-8,
    which raises ``UnicodeEncodeError: surrogates not allowed``.  That made
    ``test_append_block_then_read_round_trips`` fail intermittently with a
    watchdog-looking "Falsifying example" instead of a real defect - it was
    reproduced on the unmodified tree, so it was never a refactor regression.
    The translation-library contract is about text, so lone surrogates are out
    of scope.
    """
    return any(0xD800 <= ord(c) <= 0xDFFF for c in text)


VALUES = st.one_of(
    st.text(alphabet=st.characters(exclude_characters="\r"), max_size=40),
    st.text(alphabet=MEANINGFUL, max_size=12),
).filter(
    lambda text: "\r\n" not in text and not text.endswith("\r")
    and not any(rawlib.HEADER_RE.match(line) for line in text.split("\n"))
    and not _has_surrogate(text))


# ---------------------------------------------------------------------------
# Control codes
# ---------------------------------------------------------------------------

class TestCodeRoundTrip:
    @given(text=st.text(max_size=60))
    def test_split_keeps_every_character_in_order(self, text):
        pieces = codes.split_keep_codes(text)
        assert "".join(piece for _, piece in pieces) == text

    @given(text=st.text(max_size=60))
    def test_parse_codes_are_exactly_the_is_code_pieces(self, text):
        pieces = codes.split_keep_codes(text)
        assert codes.parse_codes(text) == [p for is_code, p in pieces if is_code]

    @given(text=st.text(max_size=60))
    def test_taken_codes_out_leave_no_backslash_token_behind(self, text):
        """Removing every parsed code leaves no token the regex still matches.

        If this failed, a code would be invisible to the gate: the bake gate
        compares ``parse_codes`` output, so a code the parser misses is a code
        a translation may drop without complaint.
        """
        stripped = codes.CODE_RE.sub("", text)
        assert codes.parse_codes(stripped) == []

    @given(text=st.text(max_size=40),
           argument=st.sampled_from(["1", "27", "", "abc", "役名,表示"]))
    def test_code_key_is_stable_under_a_parameter_rewrite(self, text, argument):
        """A code's *key* must not depend on its parameter.

        The gate allows translating a textual parameter (a name box) but never
        a numeric one; that decision is only sound if the key is derived from
        the code name alone.
        """
        token = f"\\nc<{argument}>"
        assert codes.code_key(token) == "NC"
        assert codes.code_key(token) in [key for key, _ in
                                         codes.parse_code_sequence(token)]

    @given(name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz",
                        min_size=1, max_size=4))
    def test_code_key_uppercases_the_letters(self, name):
        assert codes.code_key("\\" + name) == name.upper()

    def test_text_parameter_is_the_only_translatable_part(self):
        assert codes.has_text_parameter("\\nc<チンピラ>")
        assert not codes.has_text_parameter("\\C[3]")
        assert not codes.has_text_parameter("\\px[200]")
        assert codes.parameter_of("\\nc<name>") == "name"
        assert codes.parameter_of("\\C[3]") == "3"
        assert codes.parameter_of("\\{") is None


# ---------------------------------------------------------------------------
# The raw library (the only durable translation store)
# ---------------------------------------------------------------------------

def _library(path, values):
    rawlib.write_library(path, values)
    return path


#: Hypothesis cannot reset a *function-scoped* fixture between generated
#: inputs, so no property here takes ``tmp_path``: each example creates and
#: removes its own temporary directory.  A shared directory would be worse
#: than a health-check warning - the append property below would accumulate
#: every earlier example's blocks and its assertion would be meaningless.
class _TempDir:
    """Per-example temporary directory, removed even when the property fails."""

    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory(prefix="gt-prop-")
        return self._dir.name

    def __exit__(self, *exc):
        self._dir.cleanup()
        return False


class TestLibraryRoundTrip:
    @given(values=st.dictionaries(IDS, VALUES, max_size=6))
    def test_write_then_read_is_lossless(self, values):
        """Including a trailing newline, which is a real character."""
        with _TempDir() as tmp:
            path = _library(os.path.join(tmp, rawlib.LIBRARY_NAME), values)
            assert dict(rawlib.read_library(path)) == values

    @given(values=st.dictionaries(IDS, VALUES, min_size=1, max_size=4))
    def test_append_block_then_read_round_trips(self, values):
        """`append_block` is the only write path; min_size=1 keeps the file real.

        An empty mapping would mean "nothing was ever appended", so no library
        file exists and there is nothing to read back - a different statement
        than this one.
        """
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            for key, text in values.items():
                rawlib.append_block(path, key, text)
            assert dict(rawlib.read_library(path)) == values


class TestBareCarriageReturn:
    """A lone CR is data, not a line ending (Phase 5 defect fix).

    ``append_block`` writes the value verbatim, so a bare CR reached the disk,
    but ``read_library`` used the default universal-newline mode, which folds
    CR into a line break: the value came back as ``"a\nb"``.  The library
    could therefore store a value it could never read back - and the old
    property-test generator hid it by filtering ``\r`` out.

    ``newline="\n"`` is the fix.  Note that ``newline=""`` is **not**: it only
    stops *translating* line endings, it still splits on a lone CR (measured -
    see the docstring of ``read_library`` and
    ``test_newline_empty_still_splits_on_a_lone_cr`` below, which pins that
    difference so the wrong fix is not applied again).
    """

    def test_newline_empty_still_splits_on_a_lone_cr(self):
        """Why the fix is ``newline="\n"`` and not the more obvious ``""``.

        A future reader will reach for ``newline=""`` ("do not touch my line
        endings"); it does not do what it sounds like.  This pins the measured
        behaviour of all three modes on the same bytes.
        """
        raw = "@@@k@@@\na\rb\n"
        with _TempDir() as tmp:
            path = os.path.join(tmp, "x.txt")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(raw)
            got = {}
            for setting in (None, "", "\n"):
                with open(path, encoding="utf-8", newline=setting) as handle:
                    got[setting] = list(handle)
        assert got["\n"] == ["@@@k@@@\n", "a\rb\n"]
        # Both other modes split on the lone CR; they differ only in whether
        # the surviving CR is translated.  Measured, not assumed.
        assert got[None] == ["@@@k@@@\n", "a\n", "b\n"]
        assert got[""] == ["@@@k@@@\n", "a\r", "b\n"]
        assert len(got[""]) == 3, (
            "newline='' preserves line endings but still splits on a lone CR; "
            "if this assertion changed, re-read read_library's docstring")
        assert got[""][1].rstrip("\r") == "a"
        assert got[None][1] == "a\n"

    def test_an_interior_bare_cr_round_trips(self):
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            rawlib.append_block(path, "k", "a\rb")
            assert dict(rawlib.read_library(path))["k"] == "a\rb"

    def test_a_bare_cr_in_a_hand_written_library_is_kept(self):
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("@@@k@@@\na\rb\n")
            assert dict(rawlib.read_library(path))["k"] == "a\rb"

    def test_a_crlf_line_ending_still_normalises_to_lf(self):
        """The contract the old filter was protecting - keep it."""
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("@@@k@@@\r\nfirst\r\nsecond\r\n")
            assert dict(rawlib.read_library(path))["k"] == "first\nsecond"

    def test_an_interior_crlf_loses_its_cr(self):
        """The other known limit: ``\r\n`` inside a value reads back as ``\n``.

        ``bare`` is per line and the writer joins with LF, so the CR of an
        interior CRLF cannot survive.  Documented rather than fixed: the
        line-break gate counts ``\n``, so nothing downstream distinguishes
        them, and making values carry raw CRLF would put the format and the
        gate at odds for no gain.
        """
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            rawlib.append_block(path, "k", "a\r\nb")
            assert dict(rawlib.read_library(path))["k"] == "a\nb"

    def test_a_value_ending_in_a_bare_cr_is_unrepresentable(self):
        """The known limit, pinned so nobody calls it a new bug later.

        ``write_library`` emits ``@@@k@@@\n<value>\n``; a value ending in CR
        produces ``...\r\n``, whose CR is stripped as if it were a CRLF tail.
        No translation target is expected to end in a bare CR, and the
        round-trip property above excludes exactly this shape.
        """
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("@@@k@@@\na\r\n")
            assert dict(rawlib.read_library(path))["k"] == "a"

    @given(text=st.text(min_size=1, max_size=30).filter(
        lambda t: "@@@" not in t and "\r" not in t))
    def test_a_value_ending_in_a_newline_survives(self, text):
        value = text + "\n"
        values = {"k": value}
        with _TempDir() as tmp:
            path = _library(os.path.join(tmp, rawlib.LIBRARY_NAME), values)
            assert dict(rawlib.read_library(path)) == values

    @given(stray=st.text(min_size=1, max_size=20).filter(
               lambda t: "@@@" not in t and t.strip()
               and not t.lstrip().startswith("#")),
           lead=st.text(max_size=10).filter(
               lambda t: "@@@" not in t
               and all(not line.strip() or line.lstrip().startswith("#")
                       for line in t.split("\n"))))
    def test_text_before_the_first_header_is_a_value_error(self, stray, lead):
        """Only blank lines and ``#`` notes may precede the first header.

        The generator must produce a line the reader really rejects.  An
        earlier version filtered on ``t.strip()`` alone, and Hypothesis shrank
        a failure to ``'#'`` - a ``#`` note, which the reader tolerates on
        purpose.  The property was false and the code was right, so the fix
        belongs here: ``stray`` is a line the guard fires on, ``lead`` is
        tolerated noise in front of it.
        """
        with _TempDir() as tmp:
            path = os.path.join(tmp, "stray.txt")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(lead + "\n" + stray + "\n")
            with pytest.raises(ValueError, match="before the first"):
                rawlib.read_library(path)

    @given(note=st.text(min_size=1, max_size=20).filter(
               lambda t: "@@@" not in t and "\n" not in t and "\r" not in t
               and t.strip() and not t.startswith("#")))
    def test_a_hash_note_before_the_first_header_is_tolerated(self, note):
        """The other half of the contract the shrinking above exposed.

        A comment is not a value: reading it as stray text would make every
        hand-annotated library unreadable, so the guard deliberately lets it
        through - and that asymmetry has to be pinned, or the next fix to the
        guard removes it.

        ``\r`` is excluded from the note generator for the same reason
        ``\n`` is: a note is one line, and a bare CR inside it would make the
        rest of the note a second, unmarked line.  (That is what the first
        version of this test got wrong - it generated ``'\r0'`` and the reader
        rightly complained about line 2.)
        """
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(f"# {note}\n@@@k@@@\nvalue\n")
            assert dict(rawlib.read_library(path)) == {"k": "value"}

    @given(key=st.text(alphabet="ab@", min_size=3, max_size=3).filter(
        lambda k: "@@@" in k))
    def test_append_block_rejects_an_id_that_forges_a_header(self, key):
        with _TempDir() as tmp:
            path = os.path.join(tmp, rawlib.LIBRARY_NAME)
            with pytest.raises(ValueError, match="must not contain"):
                rawlib.append_block(path, key, "value")


class TestSafeReplaceIsIdempotent:
    @given(text=st.text(max_size=30), old=st.text(min_size=1, max_size=4),
           new=st.text(min_size=1, max_size=4))
    def test_applying_a_rule_twice_equals_applying_it_once(self, text, old, new):
        """The whole reason the helper exists: ``杂鱼`` -> ``杂鱼剑`` twice."""
        once = rawlib.safe_replace(text, old, new)
        assert rawlib.safe_replace(once, old, new) == once

    @given(old=st.sampled_from(["a", "ab", "abc"]),
           count=st.integers(min_value=0, max_value=6))
    def test_a_first_pass_replaces_every_occurrence(self, old, count):
        text = (old + "|") * count
        assert rawlib.safe_replace(text, old, "X") == ("X|" * count)

    def test_the_documented_growing_case(self):
        assert rawlib.safe_replace("杂鱼", "杂鱼", "杂鱼剑") == "杂鱼剑"
        assert rawlib.safe_replace("杂鱼剑", "杂鱼", "杂鱼剑") == "杂鱼剑"

    def test_the_documented_shrinking_case(self):
        assert rawlib.safe_replace("嫩穴摹本", "嫩穴摹本", "嫩穴") == "嫩穴"


class TestControlCodeGate:
    """``code_problems`` must judge codes, not text - for any input."""

    @given(text=st.text(max_size=30))
    def test_identical_text_has_no_problems(self, text):
        assert rawlib.code_problems(text, text) == []

    @given(text=st.text(max_size=20),
           parameter=st.text(alphabet="abcdefghijklmnopqrstuvwxyz",
                             min_size=1, max_size=6))
    def test_dropping_a_numeric_code_is_always_reported(self, text, parameter):
        source = f"\\C[{parameter}]{text}"
        assert rawlib.code_problems(source, text) != []

    @given(text=st.text(max_size=20))
    def test_reordering_two_codes_is_reported(self, text):
        assert rawlib.code_problems(f"\\C[1]\\N[2]{text}",
                                    f"\\N[2]\\C[1]{text}") != []

    def test_a_translated_name_box_is_accepted(self):
        assert rawlib.code_problems("\\nc<チンピラ>です", "\\nc<混混>啊") == []

    def test_a_lost_bracket_shape_is_reported(self):
        assert rawlib.code_problems("\\nc<チンピラ>です", "\\nc[混混]啊") != []

    def test_a_code_without_a_bracket_pair_compares_as_no_shape(self):
        """`bracket_pair` returns None when a token carries no `()`/`[]`.

        Only `<...>` and `[...]` are shapes, so a code like `\\{` has *no*
        shape on either side.  Both sides being None must compare equal - a
        naive implementation that compared `None != None` (or crashed on
        `None == None`) would report a problem on every escaped-punctuation
        code in the game.
        """
        for bare in ("\\{", "\\.", "\\$", "\\|", "\\^", "\\!"):
            assert rawlib.code_problems(f"{bare}あ", f"{bare}啊") == [], bare
        # A shape appearing on only one side is still a real difference.
        assert rawlib.code_problems("\\nc<あ>です", "\\nc混混啊") != []


class TestJsonStructureGate:
    @given(payload=st.recursive(
        st.one_of(st.integers(), st.text(max_size=6)),
        lambda children: st.one_of(st.lists(children, max_size=3),
                                   st.dictionaries(st.text(max_size=3),
                                                   children, max_size=3)),
        max_leaves=5))
    def test_a_structure_identical_translation_is_accepted(self, payload):
        text = json.dumps(payload, ensure_ascii=False)
        assert rawlib.structure_problems(text, text) == []

    def test_a_lost_bracket_is_reported(self):
        source = '{"label": "戦う", "switchId": "0"}'
        target = '{"label": "战斗", "switchId": "0"'
        assert rawlib.structure_problems(source, target) != []

    def test_plain_dialogue_is_not_json_checked(self):
        """Ordinary text starting with a bracket is out of scope, not a bug."""
        assert rawlib.structure_problems("[戦う]です", "[战斗]啊") == []

    def test_nested_string_json_is_checked(self):
        source = '["{\\"label\\": \\"戦う\\"}"]'
        target = '["{\\"label\\": \\"战斗\\""]'
        assert rawlib.structure_problems(source, target) != []


# ---------------------------------------------------------------------------
# Machine config schema
# ---------------------------------------------------------------------------

CONFIG_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda children: st.one_of(st.lists(children, max_size=3),
                               st.dictionaries(st.text(max_size=6),
                                               children, max_size=3)),
    max_leaves=6)


class TestMachineConfigNeverRaises:
    @given(payload=CONFIG_VALUES)
    def test_any_json_shape_is_handled(self, payload):
        """`load_machine_config` is documented as never raising."""
        with _TempDir() as tmp:
            path = os.path.join(tmp, "environment.json")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle)
            config = settings.load_machine_config(path)
            assert config.present
            if config.problems:
                assert config.raw == {}
            else:
                assert isinstance(config.raw, dict)

    @given(text=st.text(max_size=40))
    def test_any_bytes_are_handled(self, text):
        with _TempDir() as tmp:
            path = os.path.join(tmp, "environment.json")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            config = settings.load_machine_config(path)
            assert config.present
            assert config.raw == {} or not config.problems

    def test_unknown_sections_are_rejected_whole(self, tmp_path):
        path = os.path.join(str(tmp_path), "environment.json")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"version": 1, "tools": {"ffmpeg": "x"},
                       "typo_section": {}}, handle)
        config = settings.load_machine_config(path)
        assert not config.ok
        assert config.raw == {}
        assert any("unknown section" in problem for problem in config.problems)

    def test_a_newer_schema_version_is_rejected(self, tmp_path):
        path = os.path.join(str(tmp_path), "environment.json")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"version": settings.CONFIG_SCHEMA_VERSION + 1}, handle)
        config = settings.load_machine_config(path)
        assert not config.ok
        assert any("newer than this build" in problem for problem in
                   config.problems)

    def test_a_missing_file_is_normal(self, tmp_path):
        config = settings.load_machine_config(
            os.path.join(str(tmp_path), "absent.json"))
        assert not config.present and config.ok and not config.problems

    @given(version=st.integers(min_value=1,
                               max_value=settings.CONFIG_SCHEMA_VERSION))
    def test_a_current_version_is_accepted(self, version):
        with _TempDir() as tmp:
            path = os.path.join(tmp, "environment.json")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"version": version, "tools": {},
                           "deliverables": {}}, handle)
            config = settings.load_machine_config(path)
            assert config.ok, config.problems


class TestFontManifestSchema:
    """The font manifest is the other schema: any shape must not raise."""

    @given(payload=CONFIG_VALUES)
    def test_any_shape_is_reported_not_raised(self, payload):
        from rpgmaker import fontpolicy
        with _TempDir() as tmp:
            with open(os.path.join(tmp, "manifest.json"), "w",
                         encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle)
            manifest = fontpolicy.load_manifest(tmp)
            assert manifest.present
            assert manifest.ok == (not manifest.problems)
            if manifest.problems:
                assert manifest.fonts == {}

    @given(entries=st.lists(st.dictionaries(st.text(max_size=4),
                                            CONFIG_VALUES, max_size=3),
                            max_size=3))
    def test_arbitrary_entries_are_reported_not_raised(self, entries):
        from rpgmaker import fontpolicy
        with _TempDir() as tmp:
            with open(os.path.join(tmp, "manifest.json"), "w",
                         encoding="utf-8", newline="\n") as handle:
                json.dump({"schema_version": fontpolicy.MANIFEST_SCHEMA_VERSION,
                           "fonts": entries}, handle)
            manifest = fontpolicy.load_manifest(tmp)
            assert manifest.present
            assert manifest.ok == (not manifest.problems)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
