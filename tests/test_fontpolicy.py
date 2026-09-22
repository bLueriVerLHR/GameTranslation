#!/usr/bin/env python3
"""Tests for rpgmaker.fontpolicy - the PLAN Phase 4 task 7 policy matrix.

The matrix exists because the failure this guards against is silent: a Chinese
build whose font was not applied renders every Chinese character as a box, and
a report that says "done" while doing nothing is indistinguishable from success
in a log.  So the cases are split by *who* is allowed to be lenient:

* a build we translated ourselves (``required``) must FAIL rather than ship;
* a game that already ships a translation (``auto``) must only WARN and must
  never write, even when a perfectly good font was found;
* ``preserve`` must not even look, which is what makes it a guarantee.

The manifest is the authority for a logical id, so a broken manifest has to
block ``required`` before any file is copied.
"""
import hashlib
import json
import os

import pytest

from rpgmaker import fontpolicy

FONT_BYTES = b"\x00\x01\x02font-payload"
SHA = hashlib.sha256(FONT_BYTES).hexdigest()


def _entry(font_id="common-zh", filename="common.otf", **overrides):
    entry = {
        "id": font_id,
        "file": filename,
        "family": "Placeholder Sans",
        "purpose": "unified zh/ja/latin UI font",
        "license": "OFL-1.1",
        "sha256": SHA,
        "coverage": {"covers_gb_simplified": True,
                     "covers_japanese_kana": False},
    }
    entry.update(overrides)
    return entry


def _write_manifest(directory, fonts, schema_version=1):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / fontpolicy.MANIFEST_NAME).write_text(
        json.dumps({"schema_version": schema_version, "fonts": fonts},
                   ensure_ascii=False),
        encoding="utf-8")
    return directory


def _load_example():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "docs", "reference", "schema",
                        "font-manifest.example.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def fonts(tmp_path):
    """A registered, checksum-correct font directory."""
    directory = _write_manifest(tmp_path / "fonts", [_entry()])
    (directory / "common.otf").write_bytes(FONT_BYTES)
    return directory


@pytest.fixture(autouse=True)
def no_operator_override(monkeypatch):
    """Neutralise the machine-local font overrides by default.

    Without this every case would silently depend on the machine it runs on,
    which is exactly how "the font policy did not apply" hides.  Only the
    font-paths *file* is suppressed here; ``CJK_FONT_PATH`` stays live so the
    override tests can exercise the real resolution order.
    """
    from rpgmaker import assets

    monkeypatch.delenv("CJK_FONT_PATH", raising=False)
    monkeypatch.setattr(assets, "read_font_paths", list)


# --------------------------------------------------------------------------
# Policy table
# --------------------------------------------------------------------------
class TestPolicyNames:
    def test_the_three_policies_are_pinned(self):
        assert fontpolicy.POLICIES == ("required", "auto", "preserve")

    def test_required_is_the_delivery_default(self):
        assert fontpolicy.DEFAULT_POLICY == "required"

    def test_unknown_policy_is_a_programming_error(self, fonts):
        with pytest.raises(ValueError, match="unknown font policy"):
            fontpolicy.decide_font("forcefully", fonts_dir=fonts)


# --------------------------------------------------------------------------
# required - the self-translated build
# --------------------------------------------------------------------------
class TestRequiredIsMandatory:
    def test_a_registered_font_is_applied(self, fonts):
        decision = fontpolicy.decide_font("required", fonts_dir=fonts)
        assert decision.apply is True
        assert decision.source == "registered manifest"
        assert decision.font_id == "common-zh"
        assert decision.path == str(fonts / "common.otf")
        assert decision.files == (decision.path,)

    def test_a_missing_font_directory_fails(self, tmp_path):
        with pytest.raises(fontpolicy.FontPolicyError) as excinfo:
            fontpolicy.decide_font("required", fonts_dir=tmp_path / "absent")
        message = str(excinfo.value)
        assert "cannot be satisfied" in message
        assert "docs/reference/local-layout.md" in message

    def test_a_missing_font_file_fails(self, fonts):
        (fonts / "common.otf").unlink()
        with pytest.raises(fontpolicy.FontPolicyError, match="font file missing"):
            fontpolicy.decide_font("required", fonts_dir=fonts)

    def test_an_unregistered_id_fails_and_lists_what_is_registered(self, fonts):
        with pytest.raises(fontpolicy.FontPolicyError) as excinfo:
            fontpolicy.decide_font("required", font_id="common-ja",
                                   fonts_dir=fonts)
        assert "not registered" in str(excinfo.value)
        assert "common-zh" in str(excinfo.value)

    def test_a_swapped_font_file_fails(self, fonts):
        (fonts / "common.otf").write_bytes(b"a different font")
        with pytest.raises(fontpolicy.FontPolicyError,
                           match="checksum mismatch"):
            fontpolicy.decide_font("required", fonts_dir=fonts)

    def test_a_missing_manifest_fails(self, tmp_path):
        directory = tmp_path / "fonts"
        directory.mkdir()
        (directory / "common.otf").write_bytes(FONT_BYTES)
        with pytest.raises(fontpolicy.FontPolicyError, match="not found"):
            fontpolicy.decide_font("required", fonts_dir=directory)


# --------------------------------------------------------------------------
# auto - the already-translated game: report only, never write
# --------------------------------------------------------------------------
class TestAutoIsReportOnly:
    def test_a_good_font_is_still_not_applied(self, fonts):
        decision = fontpolicy.decide_font("auto", fonts_dir=fonts)
        assert decision.apply is False
        assert decision.policy == "auto"
        assert decision.warnings
        assert "report-only" in decision.detail
        # The path is kept so a report/doctor can say what *would* happen.
        assert decision.path == str(fonts / "common.otf")

    def test_a_missing_font_only_warns(self, tmp_path):
        decision = fontpolicy.decide_font("auto", fonts_dir=tmp_path / "absent")
        assert decision.apply is False
        assert any("was not applied" in w for w in decision.warnings)

    def test_a_broken_manifest_only_warns(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(mystery_field="x")])
        (directory / "common.otf").write_bytes(FONT_BYTES)
        decision = fontpolicy.decide_font("auto", fonts_dir=directory)
        assert decision.apply is False
        assert decision.warnings

    def test_a_swapped_file_only_warns(self, fonts):
        (fonts / "common.otf").write_bytes(b"swapped")
        decision = fontpolicy.decide_font("auto", fonts_dir=fonts)
        assert decision.apply is False
        assert decision.warnings


# --------------------------------------------------------------------------
# preserve - does not even look
# --------------------------------------------------------------------------
class TestPreserveLooksAtNothing:
    def test_preserve_never_applies(self):
        decision = fontpolicy.decide_font("preserve")
        assert decision.apply is False
        assert decision.files == ()
        assert "no font file is inspected or written" in decision.detail

    def test_preserve_does_not_read_the_font_directory(self, monkeypatch):
        """Fail loudly if preserve ever grows a read path."""

        def explode(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("preserve must not read the manifest")

        monkeypatch.setattr(fontpolicy, "load_manifest", explode)
        decision = fontpolicy.decide_font("preserve",
                                         fonts_dir="/does/not/exist")
        assert decision.apply is False

    def test_preserve_skips_even_a_good_manifest(self, fonts, monkeypatch):
        monkeypatch.setattr(
            fontpolicy, "load_manifest",
            lambda *a, **k: pytest.fail("preserve read the manifest"))
        assert fontpolicy.decide_font("preserve", fonts_dir=fonts).apply is False


# --------------------------------------------------------------------------
# Explicit selection
# --------------------------------------------------------------------------
class TestExplicitSelection:
    def test_an_explicit_path_is_used_for_required(self, tmp_path):
        chosen = tmp_path / "hand-picked.otf"
        chosen.write_bytes(b"whatever")
        decision = fontpolicy.decide_font("required", font_path=str(chosen),
                                         fonts_dir=tmp_path / "absent")
        assert decision.apply is True
        assert decision.source == "explicit path"
        assert decision.path == str(chosen)

    def test_an_explicit_path_outranks_the_registered_manifest(self, fonts,
                                                               tmp_path):
        chosen = tmp_path / "hand-picked.otf"
        chosen.write_bytes(b"whatever")
        decision = fontpolicy.decide_font("required", font_path=str(chosen),
                                         fonts_dir=fonts)
        assert decision.path == str(chosen)

    def test_a_missing_explicit_path_fails_for_required(self, tmp_path):
        with pytest.raises(fontpolicy.FontPolicyError,
                           match="given font file does not exist"):
            fontpolicy.decide_font("required",
                                   font_path=str(tmp_path / "typo.otf"))

    def test_apply_is_stable_across_repeated_calls(self, fonts):
        first = fontpolicy.decide_font("required", fonts_dir=fonts)
        second = fontpolicy.decide_font("required", fonts_dir=fonts)
        assert first == second

    def test_explicit_font_helper_skips_the_manifest(self, tmp_path):
        chosen = tmp_path / "hand-picked.otf"
        chosen.write_bytes(b"whatever")
        decision = fontpolicy.explicit_font(str(chosen))
        assert decision.apply is True
        assert decision.source == "explicit path"

    def test_explicit_font_helper_rejects_a_missing_file(self, tmp_path):
        with pytest.raises(fontpolicy.FontPolicyError, match="not found"):
            fontpolicy.explicit_font(str(tmp_path / "absent.otf"))


# --------------------------------------------------------------------------
# Operator override (CJK_FONT_PATH / local font-paths file)
# --------------------------------------------------------------------------
class TestOperatorOverride:
    def test_the_env_var_is_honoured(self, tmp_path, monkeypatch):
        chosen = tmp_path / "env.otf"
        chosen.write_bytes(b"env font")
        monkeypatch.setenv("CJK_FONT_PATH", str(chosen))
        decision = fontpolicy.decide_font("required",
                                         fonts_dir=tmp_path / "absent")
        assert decision.apply is True
        assert decision.source == "CJK_FONT_PATH"
        assert decision.path == str(chosen)

    def test_the_local_font_paths_file_is_the_second_choice(self, fonts,
                                                            tmp_path,
                                                            monkeypatch):
        from rpgmaker import assets

        chosen = tmp_path / "local.otf"
        chosen.write_bytes(b"local font")
        monkeypatch.setattr(assets, "read_font_paths", lambda: [str(chosen)])
        decision = fontpolicy.decide_font("required", fonts_dir=fonts)
        assert decision.source == "the local font-paths file"
        assert decision.path == str(chosen)

    def test_the_env_var_outranks_the_local_font_file(self, tmp_path,
                                                      monkeypatch):
        from rpgmaker import assets

        env_font = tmp_path / "env.otf"
        env_font.write_bytes(b"env font")
        file_font = tmp_path / "local.otf"
        file_font.write_bytes(b"local font")
        monkeypatch.setenv("CJK_FONT_PATH", str(env_font))
        monkeypatch.setattr(assets, "read_font_paths",
                            lambda: [str(file_font)])
        decision = fontpolicy.decide_font("required",
                                         fonts_dir=tmp_path / "absent")
        assert decision.source == "CJK_FONT_PATH"
        assert decision.path == str(env_font)


# --------------------------------------------------------------------------
# Manifest validation blocks required
# --------------------------------------------------------------------------
class TestManifestValidation:
    def test_a_clean_manifest_round_trips(self, fonts):
        manifest = fontpolicy.load_manifest(fonts)
        assert manifest.ok is True
        assert manifest.version == 1
        assert set(manifest.fonts) == {"common-zh"}
        assert "ok (1 font(s)" in manifest.describe()

    def test_an_absent_manifest_is_not_an_error_by_itself(self, tmp_path):
        manifest = fontpolicy.load_manifest(tmp_path)
        assert manifest.present is False
        assert manifest.problems == ()
        assert manifest.ok is False
        assert manifest.describe().endswith("not found")

    def test_invalid_json_is_reported_not_raised(self, tmp_path):
        (tmp_path / fontpolicy.MANIFEST_NAME).write_text("{broken",
                                                        encoding="utf-8")
        manifest = fontpolicy.load_manifest(tmp_path)
        assert any("not valid JSON" in p for p in manifest.problems)
        assert manifest.ok is False

    def test_a_non_object_root_is_reported(self, tmp_path):
        (tmp_path / fontpolicy.MANIFEST_NAME).write_text("[]", encoding="utf-8")
        manifest = fontpolicy.load_manifest(tmp_path)
        assert "not an object" in manifest.problems[0]

    def test_an_unknown_schema_version_is_reported(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts", [_entry()],
                                    schema_version=99)
        manifest = fontpolicy.load_manifest(directory)
        assert any("supported version" in p for p in manifest.problems)

    def test_a_missing_schema_version_is_reported(self, tmp_path):
        (tmp_path / fontpolicy.MANIFEST_NAME).write_text(
            json.dumps({"fonts": []}), encoding="utf-8")
        manifest = fontpolicy.load_manifest(tmp_path)
        assert any("schema_version" in p for p in manifest.problems)

    def test_missing_required_fields_are_reported(self, tmp_path):
        entry = _entry()
        del entry["license"]
        directory = _write_manifest(tmp_path / "fonts", [entry])
        manifest = fontpolicy.load_manifest(directory)
        assert any("license" in p for p in manifest.problems)

    def test_an_unknown_field_is_reported(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(mystery="value")])
        manifest = fontpolicy.load_manifest(directory)
        assert any("mystery" in p and "not a known field" in p
                   for p in manifest.problems)

    def test_a_bad_logical_id_is_reported(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(font_id="Common_ZH")])
        manifest = fontpolicy.load_manifest(directory)
        assert any("logical-id pattern" in p for p in manifest.problems)

    def test_a_non_hex_checksum_is_reported(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(sha256="NOT-A-HASH")])
        manifest = fontpolicy.load_manifest(directory)
        assert any("lowercase hex sha256" in p for p in manifest.problems)

    def test_a_path_in_the_file_field_is_reported(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(file="sub/dir.otf")])
        manifest = fontpolicy.load_manifest(directory)
        assert any("bare filename" in p for p in manifest.problems)

    def test_a_non_boolean_coverage_flag_is_reported(self, tmp_path):
        directory = _write_manifest(
            tmp_path / "fonts",
            [_entry(coverage={"covers_gb_simplified": "yes"})])
        manifest = fontpolicy.load_manifest(directory)
        assert any("is not a boolean" in p for p in manifest.problems)

    def test_a_non_positive_size_is_reported(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(size_bytes=0)])
        manifest = fontpolicy.load_manifest(directory)
        assert any("positive integer" in p for p in manifest.problems)

    def test_a_null_size_is_allowed(self, tmp_path):
        """The schema version of the field is optional."""
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(size_bytes=None)])
        (directory / "common.otf").write_bytes(FONT_BYTES)
        assert fontpolicy.load_manifest(directory).ok is True

    def test_a_duplicate_id_is_reported(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(), _entry(file="other.otf")])
        manifest = fontpolicy.load_manifest(directory)
        assert any("duplicate" in p for p in manifest.problems)

    def test_every_validation_problem_blocks_required(self, tmp_path):
        """The point of validating: a broken manifest must not be applied."""
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(sha256="NOT-A-HASH")])
        (directory / "common.otf").write_bytes(FONT_BYTES)
        with pytest.raises(fontpolicy.FontPolicyError,
                           match="invalid|checksum"):
            fontpolicy.decide_font("required", fonts_dir=directory)

    def test_checksum_checking_can_be_switched_off(self, fonts):
        (fonts / "common.otf").write_bytes(b"swapped")
        assert fontpolicy.decide_font("required", fonts_dir=fonts,
                                      check_checksum=False).apply is True
        assert fontpolicy.verify_font(
            fontpolicy.load_manifest(fonts).get("common-zh"),
            check_checksum=False) is None


# --------------------------------------------------------------------------
# Coverage warnings
# --------------------------------------------------------------------------
class TestCoverageWarnings:
    def test_a_declared_coverage_produces_no_warning(self, fonts):
        decision = fontpolicy.decide_font("required", fonts_dir=fonts)
        assert decision.warnings == ()

    def test_an_undeclared_coverage_is_reported_as_unknown(self, tmp_path):
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(coverage={})])
        (directory / "common.otf").write_bytes(FONT_BYTES)
        decision = fontpolicy.decide_font("required", fonts_dir=directory)
        assert decision.apply is True
        assert any("does not declare" in w for w in decision.warnings)

    def test_a_false_coverage_is_reported_as_boxes(self, tmp_path):
        directory = _write_manifest(
            tmp_path / "fonts",
            [_entry(coverage={"covers_gb_simplified": False})])
        (directory / "common.otf").write_bytes(FONT_BYTES)
        decision = fontpolicy.decide_font("required", fonts_dir=directory)
        assert any("may render as boxes" in w for w in decision.warnings)

    def test_missing_coverage_is_unknown_not_true(self, tmp_path):
        """None means "the manifest does not say", never "assume it is fine"."""
        directory = _write_manifest(tmp_path / "fonts",
                                    [_entry(coverage={})])
        record = fontpolicy.load_manifest(directory).get("common-zh")
        assert record.covers_gb_simplified is None

    def test_coverage_is_echoed_in_the_record(self, fonts):
        record = fontpolicy.load_manifest(fonts).get("common-zh")
        assert record.covers_gb_simplified is True
        assert record.family == "Placeholder Sans"
        assert record.license == "OFL-1.1"


# --------------------------------------------------------------------------
# The example manifest that ships in the repo
# --------------------------------------------------------------------------
class TestShippedExample:
    def test_the_example_manifest_is_valid_and_placeholder_only(self):
        raw = _load_example()
        assert raw["schema_version"] == 1
        assert raw["fonts"], "the example must show at least one entry"
        for entry in raw["fonts"]:
            assert set(entry) >= set(fontpolicy._REQUIRED_FIELDS)
            # The id is a *logical* name the policies and CLI flags refer to,
            # so it is concrete, and `purpose` describes a role rather than a
            # file.  Anything that would name a real font is a placeholder, so
            # a clean checkout never carries a font name or a real checksum.
            assert entry["id"] in ("common-zh", "common-ja")
            assert entry["sha256"] == "0" * 64
            for name in ("file", "family", "postscript_name", "license"):
                value = entry.get(name)
                if isinstance(value, str):
                    assert value.startswith("<"), (name, value)

    def test_the_example_matches_the_loader_contract(self, tmp_path):
        raw = _load_example()
        directory = _write_manifest(tmp_path / "fonts", raw["fonts"])
        # Only the unresolved checksums keep it from being usable; the entry
        # shape itself must satisfy the validator.
        problems = fontpolicy.load_manifest(directory).problems
        assert not [p for p in problems if "is not" in p or "missing" in p]
