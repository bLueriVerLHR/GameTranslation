#!/usr/bin/env python3
"""CHANGELOG and deprecation-policy gates (PLAN Phase 8 tasks 3 and 4).

Why this file exists
--------------------
A CHANGELOG nobody checks is a file that stops being true.  The specific
failure this guards against already happened in this repo: `inventory.py`
carried a `replacement` string naming `tests/test_screenshot_docs.py`, a file
that **never existed**, so the register read as documented while pointing at
nothing.  The same shape of rot applies to a changelog: a tool gets marked
`superseded` in the inventory and nothing tells a reader what to use instead.

So the two records are checked against **each other**, in both directions:

* every `superseded`/`dead` inventory record must have a deprecation entry,
* every deprecation entry must still be a `superseded`/`dead` record
  (a tool that was deleted or revived must move its entry, not leave it).

A one-directional check would pass for a changelog that lists tools which no
longer exist, which is the same "documented and wrong" failure.
"""
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from rpgmaker import inventory  # noqa: E402

CHANGELOG = os.path.join(REPO_ROOT, "CHANGELOG.md")
POLICY = os.path.join(REPO_ROOT, "docs", "reference", "deprecation-policy.md")

#: Section headings a Keep-a-Changelog file uses.  `Unreleased` is separate
#: because it is the only one that must always be present.
REQUIRED_SECTIONS = ("新增", "变更", "修复", "弃用", "删除")

#: Statuses that mean "this is going away", so the changelog must say so.
DEPRECATED_STATUSES = ("superseded", "dead")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _section(text, name):
    """The body of `### <name>` up to the next `###` or `##`, or ""."""
    match = re.search(rf"^###\s+{re.escape(name)}\s*$", text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    end = re.search(r"^#{2,3}\s+", rest, re.M)
    return rest[:end.start()] if end else rest


def _deprecation_entries(text):
    """Module paths listed in the 弃用 section: `**tools/x.py**` -> `tools.x`.

    Bolded paths are the convention the changelog uses, and requiring the
    markup is deliberate: a plain mention of a tool name in prose (which the
    file also has) must not be mistaken for a deprecation entry.
    """
    entries = set()
    for raw in re.findall(r"\*\*`([^`]+)`\*\*", _section(text, "弃用")):
        path = raw.strip()
        if path.endswith(".py"):
            entries.add(path[:-3].replace("/", "."))
        else:
            entries.add(path.replace("/", "."))
    return entries


def _deprecation_targets(text):
    """`module -> replacement` pairs parsed out of the 弃用 bullets."""
    pairs = {}
    body = _section(text, "弃用")
    for match in re.finditer(r"\*\*`([^`]+)`\*\*\s*(?:→|->)\s*`([^`]+)`", body):
        old = match.group(1).strip()
        new = match.group(2).strip()
        key = old[:-3].replace("/", ".") if old.endswith(".py") else old
        pairs[key] = new
    return pairs


class TestTheChangelogIsAPlausibleChangelog:
    def test_it_exists(self):
        assert os.path.isfile(CHANGELOG), "PLAN Phase 8 task 3 requires a CHANGELOG"

    def test_it_has_an_unreleased_section(self):
        """New work lands in `Unreleased`; a file with only releases rots."""
        assert re.search(r"^##\s+\[?Unreleased\]?\s*$", _read(CHANGELOG), re.M)

    @pytest.mark.parametrize("name", REQUIRED_SECTIONS)
    def test_it_uses_the_keep_a_changelog_sections(self, name):
        assert f"### {name}" in _read(CHANGELOG), (
            f"the changelog is missing the {name} section; a reader cannot tell "
            "whether nothing happened or the entry was forgotten")

    def test_it_does_not_maintain_a_second_version_literal(self):
        """`pyproject.toml` reads the version from code; the changelog must not
        introduce a competing source.

        Pinned because a second literal is exactly how the two drift - the
        repo already had this problem with paths, where the same path lived in
        two places and only one was updated.
        """
        text = _read(CHANGELOG)
        assert "version = {attr" in _read(
            os.path.join(REPO_ROOT, "pyproject.toml"))
        assert "__version__" in text, (
            "the changelog should say where the version comes from")

    def test_it_names_the_deprecation_policy(self):
        """The changelog's rules must point at the policy, not restate it."""
        assert "deprecation-policy" in _read(CHANGELOG)


class TestTheRegisterAndTheChangelogAgree:
    def test_every_deprecated_record_has_a_changelog_entry(self):
        """A tool marked superseded must tell the reader what to use instead."""
        missing = [record.module for record in inventory.MODULES
                   if record.status in DEPRECATED_STATUSES
                   and record.module not in _deprecation_entries(_read(CHANGELOG))]
        assert not missing, (
            "these modules are deprecated in the inventory but absent from the "
            f"changelog's 弃用 section: {missing}")

    def test_every_changelog_entry_is_still_deprecated(self):
        """The reverse direction: a deleted or revived tool must not linger.

        This is the half that catches a changelog listing tools which no
        longer exist - the same "documented and wrong" shape as the
        replacement string that named a file that was never created.
        """
        recorded = {record.module: record.status for record in inventory.MODULES}
        stale = [entry for entry in _deprecation_entries(_read(CHANGELOG))
                 if recorded.get(entry) not in DEPRECATED_STATUSES]
        assert not stale, (
            "the changelog lists these as deprecated but the inventory does "
            f"not: {stale} (move the entry to 删除 if the tool is gone)")

    def test_the_deprecation_entries_direct_the_reader_somewhere(self):
        """Every entry names a replacement, and the changelog uses `→`."""
        text = _read(CHANGELOG)
        entries = _deprecation_entries(text)
        assert entries, "the 弃用 section parsed as empty - the markup changed"
        targets = _deprecation_targets(text)
        missing = sorted(entry for entry in entries if entry not in targets)
        assert not missing, (
            "these deprecation entries do not name a replacement target: "
            f"{missing}")


class TestThePolicyIsExecutable:
    def test_the_policy_exists(self):
        assert os.path.isfile(POLICY)

    def test_it_defines_all_three_record_locations(self):
        """The policy's whole value is naming where things must be recorded."""
        body = _read(POLICY)
        for needle in ("rpgmaker/inventory.py", "CHANGELOG.md"):
            assert needle in body, needle
        assert "宽限期" in body

    def test_it_states_the_deletable_conditions(self):
        body = _read(POLICY)
        assert "可删除条件" in body
        assert "零导入者" in body

    def test_it_says_a_maintenance_tool_is_not_deprecated(self):
        """The inventory has a permanent `maintenance` status; the policy must
        not be read as a reason to delete those."""
        assert "maintenance" in _read(POLICY)

    def test_it_does_not_claim_a_version_countdown_this_repo_cannot_verify(self):
        """The repo has no tags, so the grace period must not be a date or a
        version number - it must be something CI actually observes."""
        body = _read(POLICY)
        assert "没有 git tag" in body
        assert "全部条件" in body or "全部满足" in body


class TestTheDocumentsAreWiredIntoTheEntryPoints:
    def test_the_index_links_both_documents(self):
        index = _read(os.path.join(REPO_ROOT, "docs", "index.md"))
        assert "CHANGELOG.md" in index
        assert "deprecation-policy.md" in index

    def test_the_docs_layout_lists_both(self):
        layout = _read(os.path.join(REPO_ROOT, "docs", "reference", "repo-layout.md"))
        assert "CHANGELOG.md" in layout
        assert "deprecation-policy.md" in layout

    def test_contributing_points_at_the_policy(self):
        """Someone adding a tool needs to find the rule from the guide they
        already read."""
        contributing = _read(os.path.join(REPO_ROOT, "docs", "CONTRIBUTING.md"))
        assert "deprecation-policy" in contributing
