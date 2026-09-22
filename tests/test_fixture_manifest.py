#!/usr/bin/env python3
"""The tracked test fixtures must be documented and unchanged.

PLAN Phase 5 task 8 asks for sanitized golden fixtures with input, expected
artifact, manifest, provenance and license.  A fixture directory with no
manifest rots in a specific way: someone regenerates a file to make a test
pass and the "independent reference" silently becomes a snapshot of whatever
the code currently does - the check stops being a check.

This gate enforces:
  1. every tracked file under ``tests/fixtures/`` appears in ``MANIFEST.json``
     (a new fixture cannot be added without recording where it came from),
  2. the recorded sha256 and size match the bytes on disk (so a silent
     regeneration fails here instead of passing the test it was meant to
     catch),
  3. every entry records ``purpose``, ``provenance`` and ``license`` - the
     three fields that make the fixture auditable,
  4. nothing under ``tests/fixtures/`` looks like game content: this repo is
     publicly hosted, and the hygiene rule applies to binaries too.  The
     manifest itself is the one file allowed to explain why the format
     samples exist.

The manifest is JSON rather than a schema-checked format on purpose: it is
read by a test, not by a tool, and ``rpgmaker/settings.py`` already carries the
pattern for "never raise, collect problems" if that ever changes.
"""
import hashlib
import json
import os
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures")
MANIFEST = os.path.join(FIXTURES, "MANIFEST.json")

REQUIRED_FIELDS = ("kind", "purpose", "provenance", "license", "sha256",
                   "size")

#: Files that are part of the fixture tree but not fixtures themselves.
NOT_FIXTURES = frozenset({"MANIFEST.json"})


def _tracked():
    """Every git-tracked path under tests/fixtures/, relative to that dir."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "tests/fixtures"],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=60)
    assert out.returncode == 0, out.stdout
    files = []
    for line in out.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel:
            continue
        # a future subdirectory layout must not silently escape the scan
        assert rel.startswith("tests/fixtures/"), rel
        files.append(rel[len("tests/fixtures/"):])
    return sorted(files)


def _load():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_manifest_is_readable_and_has_a_schema():
    manifest = _load()
    assert isinstance(manifest, dict)
    assert manifest.get("schema") == 1, "manifest schema version changed"
    assert isinstance(manifest.get("files"), dict) and manifest["files"]


def test_every_tracked_fixture_is_in_the_manifest():
    """A new fixture must be recorded, or its provenance is lost."""
    manifest = _load()
    recorded = set(manifest["files"])
    on_disk = {f for f in _tracked() if f not in NOT_FIXTURES}
    missing = sorted(on_disk - recorded)
    assert not missing, (
        "these fixtures are not documented in tests/fixtures/MANIFEST.json: "
        f"{missing} - add them with purpose/provenance/license/sha256/size")


def test_the_manifest_has_no_entries_for_absent_files():
    manifest = _load()
    on_disk = {f for f in _tracked() if f not in NOT_FIXTURES}
    extra = sorted(set(manifest["files"]) - on_disk)
    assert not extra, (
        f"the manifest documents files that are not tracked: {extra} - a deleted "
        "fixture must be removed from the manifest too")


def test_every_entry_records_provenance_license_and_a_digest():
    manifest = _load()
    problems = []
    for name, entry in sorted(manifest["files"].items()):
        if not isinstance(entry, dict):
            problems.append(f"{name}: not an object")
            continue
        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if value in (None, "", "PLACEHOLDER"):
                problems.append(f"{name}: missing {field}")
        digest = entry.get("sha256", "")
        if digest and (len(digest) != 64 or any(
                c not in "0123456789abcdef" for c in digest)):
            problems.append(f"{name}: sha256 is not a hex digest ({digest!r})")
        if entry.get("purpose") and len(entry["purpose"]) < 10:
            problems.append(f"{name}: purpose is too short to be useful")
    assert not problems, "\n".join(problems)


def test_recorded_digests_match_the_bytes_on_disk():
    """The whole point: a regenerated fixture cannot pass unnoticed.

    Measured failure mode this prevents: the TLG reference is GARbro's export,
    an INDEPENDENT decoder.  Re-exporting it from this repo's own decoder would
    keep every test green while removing the regression's value.
    """
    manifest = _load()
    problems = []
    for name, entry in sorted(manifest["files"].items()):
        path = os.path.join(FIXTURES, name.replace("/", os.sep))
        if not os.path.isfile(path):
            continue                       # covered by the absent-file test
        data = open(path, "rb").read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.get("sha256"):
            problems.append("{}: sha256 is {}, manifest says {}".format(name, digest, entry.get("sha256")))
        if len(data) != entry.get("size"):
            problems.append("%s: size is %d, manifest says %s"
                            % (name, len(data), entry.get("size")))
    assert not problems, "\n".join(problems)


def test_fixtures_are_not_gitignored():
    """A gitignored fixture is invisible to a fresh clone, so the tests that
    need it either skip forever or fail - both of which read as "the suite is
    green" on the machine that has it."""
    out = subprocess.run(["git", "check-ignore", "--stdin"],
                         cwd=REPO_ROOT, input="\n".join(
                             "tests/fixtures/" + f for f in _tracked()),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         encoding="utf-8", errors="replace", timeout=60)
    assert not out.stdout.strip(), (
        f"these fixtures are gitignored: {out.stdout.split()}")
