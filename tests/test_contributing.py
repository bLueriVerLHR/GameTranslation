#!/usr/bin/env python3
"""CONTRIBUTING templates gate (PLAN Phase 8 task 4).

Why this file exists
--------------------
The plan's acceptance criterion for Phase 8 is that "every entry has an owner
and a documented path".  An undocumented contribution path is how a repo ends
up with five different ways to add an engine, and this repo has already paid
for that: `docs/reference/tooling.md` records that the same capability had
grown two implementations (a second `shutil.which`, a second 7z argv builder)
before the "one entry point per capability" rule was written down.

So the check is not "CONTRIBUTING exists" - it is "each of the five things a
contributor actually does has a written procedure": add an engine, add a CLI
command, add a test, add a document, add an ADR.  Each of the five must name
the concrete file or command a contributor must touch, because a template that
says "follow the existing convention" points at nothing.

Why the checks read the named anchors rather than just the headings: a section
with a heading and no named artifact is the failure mode being guarded (it
looks documented and tells you nothing).
"""
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

CONTRIBUTING = os.path.join(REPO_ROOT, "docs", "CONTRIBUTING.md")

#: (section heading, artifacts that section must name).  The artifacts are the
#: ones a contributor cannot guess: the registry they must register in, the
#: helper that owns the convention, or the gate that will fail if they skip it.
TEMPLATES = (
    ("新增引擎", ("rpgmaker/inventory.py", "docs/reference/support-matrix.md")),
    ("新增命令", ("rpgmaker/cliutil.py",)),
    ("新增测试", ("tests/", "tools/check_all.py")),
    ("新增文档", ("docs/index.md", "docs/reference/repo-layout.md")),
    ("新增 ADR", ("docs/reference/adr/",)),
)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _section(text, name):
    """Body of `## <name>` up to the next `##`, or "" when absent."""
    match = re.search(rf"^##\s+{re.escape(name)}\s*$", text, re.M)
    if not match:
        return ""
    rest = text[match.end():]
    end = re.search(r"^##\s+", rest, re.M)
    return rest[:end.start()] if end else rest


class TestEveryContributionPathIsDocumented:
    @pytest.mark.parametrize("name,artifacts", TEMPLATES,
                             ids=[name for name, _ in TEMPLATES])
    def test_the_section_exists_and_names_its_artifacts(self, name, artifacts):
        body = _section(_read(CONTRIBUTING), name)
        assert body.strip(), (
            f"docs/CONTRIBUTING.md has no '{name}' section; a contributor has "
            "to reverse-engineer the procedure from the code")
        missing = [item for item in artifacts if item not in body]
        assert not missing, (
            f"the '{name}' section does not name {missing}; naming the file "
            "that must change is the whole point of a template")

    def test_the_templates_are_not_merely_headings(self):
        """Each template must carry a procedure, not just a title.

        Pinned because a heading with one sentence is the shape this gate is
        meant to reject - it reads as documented and transfers nothing.
        """
        text = _read(CONTRIBUTING)
        thin = [name for name, _ in TEMPLATES if len(_section(text, name).strip()) < 120]
        assert not thin, (
            f"these sections are too thin to be procedures: {thin}")


class TestTheTemplatesPointAtTheRealRegistry:
    def test_the_engine_template_names_a_real_inventory_status(self):
        """Registering an engine means picking one of the documented statuses."""
        sys.path.insert(0, REPO_ROOT)
        from rpgmaker import inventory

        body = _section(_read(CONTRIBUTING), "新增引擎")
        assert any(status in body for status in inventory.STATUSES), (
            "the engine template should say which inventory status the new "
            "record starts with (one of %s)" % (inventory.STATUSES,))

    def test_the_cli_template_names_the_single_entry_point(self):
        """The repo has exactly one CLI convention; the template must point at
        it rather than restate it (a restatement is how two conventions start).
        """
        body = _section(_read(CONTRIBUTING), "新增命令")
        assert "cliutil" in body
        assert "argparse" in body, (
            "the template should say explicitly that argparse is not used, "
            "because the repo still has historical argparse usage to migrate")


class TestTheTemplatesAgreeWithTheGates:
    def test_the_test_template_names_a_real_gate(self):
        """The template tells contributors how to run the checks; that command
        must be the one the repo actually documents."""
        body = _section(_read(CONTRIBUTING), "新增测试")
        assert "check_all.py" in body
        assert os.path.isfile(os.path.join(REPO_ROOT, "tools", "check_all.py"))

    def test_the_document_template_names_the_two_drift_gates(self):
        """New docs must land in the index (discoverability) and in the layout
        tree (check_docs.py verifies the tree against the repo)."""
        body = _section(_read(CONTRIBUTING), "新增文档")
        assert "check_docs.py" in body or "repo-layout.md" in body

    def test_the_adr_template_names_the_directory_and_a_numbering_rule(self):
        body = _section(_read(CONTRIBUTING), "新增 ADR")
        adr_dir = os.path.join(REPO_ROOT, "docs", "reference", "adr")
        assert os.path.isdir(adr_dir)
        assert "编号" in body or "number" in body.lower()
