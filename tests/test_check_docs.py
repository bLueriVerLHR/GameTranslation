#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for tools/check_docs.py README-tree vs repo consistency check.

Covers the four mandated scenarios plus edge cases:
  * consistent   tree <-> repo match -> exit 0
  * missing      tree lists a file/dir absent from the repo -> [MISSING],
                 exit 1
  * extra        repo has a file the tree never mentions -> [EXTRA], exit 1
  * excluded     tree lists gitignored/local paths (docs/table/ etc.) and
                 the repo holds local/generated files -> neither flagged
And: type mismatch, glob entries, `...` ellipsis waiving, no-tree-block
error, and --readme/--repo argument handling.
"""
import os
import textwrap

import pytest

import check_docs

ROOT = "GameTranslation/"


def write_readme(repo, body):
    """Write README.md into repo containing the given tree block body."""
    path = os.path.join(repo, "README.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Sample repo\n\n```\n%s\n```\n" % body)
    return path


def make_files(repo, rels):
    """Create (empty) files under repo, creating parent dirs as needed."""
    for rel in rels:
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("")
    return repo


def make_dirs(repo, rels):
    for rel in rels:
        os.makedirs(os.path.join(repo, rel), exist_ok=True)
    return repo


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / "repo")
    os.makedirs(root, exist_ok=True)
    return root


class TestConsistent:
    def test_tree_matches_repo(self, repo):
        make_files(repo, ["a.py", "sub/b.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            └── sub/
                └── b.py
        """))
        report = check_docs.compare(readme, repo)
        assert not report.missing
        assert not report.type_mismatch
        assert not report.extra
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 0

    def test_glob_entry_covers_multiple_files(self, repo):
        make_files(repo, ["test_a.py", "test_b.py", "conftest.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── conftest.py
            └── test_*.py
        """))
        report = check_docs.compare(readme, repo)
        assert not report.missing and not report.extra
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 0

    def test_ellipsis_waives_extra_in_dir(self, repo):
        make_files(repo, ["main.py", "tools/a.py", "tools/b.py", "tools/c.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── main.py
            └── tools/
                ├── a.py
                └── ...（旧版：未逐一列出的工具）
        """))
        report = check_docs.compare(readme, repo)
        assert not report.extra
        assert not report.missing
        assert "tools" in report.ellipsis_dirs
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 0


class TestMissing:
    def test_file_missing(self, repo):
        make_files(repo, ["a.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            └── ghost.py
        """))
        report = check_docs.compare(readme, repo)
        assert report.missing == ["ghost.py"]
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 1

    def test_dir_missing(self, repo):
        make_files(repo, ["a.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            └── missing_dir/
        """))
        report = check_docs.compare(readme, repo)
        assert report.missing == ["missing_dir"]
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 1

    def test_glob_matching_nothing_is_missing(self, repo):
        make_files(repo, ["a.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            └── test_*.py
        """))
        report = check_docs.compare(readme, repo)
        assert report.missing == ["test_*.py"]
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 1


class TestExtra:
    def test_repo_file_not_in_tree(self, repo):
        make_files(repo, ["a.py", "undocumented.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            └── a.py
        """))
        report = check_docs.compare(readme, repo)
        assert report.extra == ["undocumented.py"]
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 1

    def test_extra_in_subdir(self, repo):
        make_files(repo, ["a.py", "sub/b.py", "sub/c.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            └── sub/
                └── b.py
        """))
        report = check_docs.compare(readme, repo)
        assert report.extra == ["sub/c.py"]


class TestExcluded:
    def test_tree_lists_excluded_dir_without_error(self, repo):
        # docs/table is gitignored and does not exist here; the tree entry
        # must be skipped, not reported as missing. The docs/ parent dir is
        # real (created below) and passes.
        make_files(repo, ["a.py"])
        make_dirs(repo, ["docs"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            └── docs/
                └── table/   # LOCAL ONLY, gitignored
        """))
        report = check_docs.compare(readme, repo)
        assert not report.missing
        assert not report.extra
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 0

    def test_local_generated_files_not_extra(self, repo):
        make_files(repo, ["a.py"])
        make_files(repo, [".venv/bin/python", "docs/table/glossary.json",
                          "work/x.txt", "tmp/y.txt",
                          "__pycache__/a.pyc", "built.pyc",
                          ".pytest_cache/v/cache/nodeids"])
        readme = write_readme(repo, "GameTranslation/\n└── a.py\n")
        report = check_docs.compare(readme, repo)
        assert not report.extra
        assert not report.missing

    def test_root_metadata_and_init_not_extra(self, repo):
        make_files(repo, ["a.py", "AGENTS.md", "LICENSE", "README.md",
                          "pyproject.toml", ".gitignore", ".gitattributes",
                          "pkg/__init__.py", "pkg/mod.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            └── pkg/
                └── mod.py
        """))
        report = check_docs.compare(readme, repo)
        assert not report.extra
        assert not report.missing


class TestTypeMismatch:
    def test_file_listed_as_dir(self, repo):
        make_files(repo, ["a.py"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            └── a.py/
        """))
        report = check_docs.compare(readme, repo)
        assert report.type_mismatch == ["a.py"]

    def test_dir_listed_as_file(self, repo):
        make_dirs(repo, ["sub"])
        readme = write_readme(repo, textwrap.dedent("""\
            GameTranslation/
            └── sub
        """))
        report = check_docs.compare(readme, repo)
        assert report.type_mismatch == ["sub"]


def parse_body(body):
    """Wrap a tree body in a fenced code block and parse it."""
    return check_docs.parse_tree("# sample\n\n```\n%s\n```\n" % body)


class TestParseTree:
    def test_depths_and_paths(self):
        body = textwrap.dedent("""\
            GameTranslation/
            ├── a.py
            ├── sub/
            │   ├── x.py
            │   └── y.py
            └── docs/
                └── table/
        """)
        entries, ellipsis = parse_body(body)
        assert ("a.py", False) in entries
        assert ("sub/x.py", False) in entries
        assert ("sub", True) in entries
        assert ("docs/table", True) in entries
        assert not ellipsis

    def test_comments_stripped(self):
        entries, _ = parse_body(
            "GameTranslation/\n├── a.py  # 说明注释\n└── b.py\n")
        assert ("a.py", False) in entries

    def test_ellipsis_marker_detected(self):
        body = ("GameTranslation/\n└── tools/\n    ├── a.py\n"
                "    └── ...（旧版工具，未列出）\n")
        entries, ellipsis = parse_body(body)
        assert ("tools", True) in entries
        assert ellipsis == {"tools"}

    def test_no_tree_block_raises(self):
        with pytest.raises(ValueError):
            check_docs.parse_tree("# readme without a tree\n")


class TestIsExcluded:
    def test_documented_exclusions(self):
        for p in ("docs/table/glossary.json", ".venv/bin/python",
                  "work/x", "tmp/y", "tests/fake_tools/7z.py",
                  "tests/fixtures/tlg/a.tlg", "x.pyc", "__pycache__/m.pyc",
                  ".pytest_cache/v/cache/nodeids",
                  "AGENTS.md", "LICENSE", "pyproject.toml",
                  "rpgmaker/__init__.py", ".git/config"):
            assert check_docs.is_excluded(p), p

    def test_tool_layout_files_not_excluded(self):
        for p in ("a.py", "rpgmaker/serve.py", "tools/build_translation.py",
                  "docs/workflow.md", "tests/test_config.py"):
            assert not check_docs.is_excluded(p), p


class TestRunCli:
    def test_default_paths_current_dir(self, monkeypatch, tmp_path, capsys):
        # default --repo is "." and default --readme is <repo>/README.md
        monkeypatch.chdir(tmp_path)
        make_files(str(tmp_path), ["a.py"])
        write_readme(str(tmp_path), "GameTranslation/\n└── a.py\n")
        assert check_docs.run([]) == 0
        out = capsys.readouterr().out
        assert "docs tree matches repo" in out

    def test_no_tree_block_returns_error(self, tmp_path, capsys):
        repo = str(tmp_path / "repo")
        os.makedirs(repo, exist_ok=True)
        readme = os.path.join(repo, "README.md")
        with open(readme, "w", encoding="utf-8") as f:
            f.write("# no tree here\n")
        assert check_docs.run(["--readme", readme, "--repo", repo]) == 1
        err = capsys.readouterr().err
        assert "no directory tree block" in err

    def test_verbose_lists_checked_entries(self, repo, capsys):
        make_files(repo, ["a.py"])
        readme = write_readme(repo, "GameTranslation/\n└── a.py\n")
        assert check_docs.run(["--readme", readme, "--repo", repo,
                               "--verbose"]) == 0
        out = capsys.readouterr().out
        assert "[OK] a.py" in out
