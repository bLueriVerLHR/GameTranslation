#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Documentation tree vs. repo consistency check (README directory tree).

Parses the box-drawing directory tree inside README.md (the fenced code
block rooted at the repo name, e.g. "GameTranslation/") and verifies it
stays in sync with the actual files in the repository.

What is checked
---------------
* every path listed in the README tree must exist in the repo with the
  right type: a `name/` entry must be a directory, a plain entry must be a
  file, and an entry containing a glob (e.g. `test_*.py`) must match at
  least one file.  A tree entry that is gone from the repo is reported as
  [MISSING] (or [TYPE] when it exists with a different type) and fails the
  run.
* every repo file must be covered by the tree: an explicit file entry, a
  glob entry in its directory, or a `...` ellipsis marker in that
  directory.  A repo file the tree never mentions is reported as [EXTRA]
  and fails the run.

What is NOT checked (excluded, so the tree does not have to list them)
---------------------------------------------------------------------
* repo metadata at the root: AGENTS.md, LICENSE, README.md, pyproject.toml,
  .gitignore, .gitattributes (the tree documents the tool layout, not the
  repo metadata)
* VCS / env internals: .git/, .venv/, __pycache__/
* gitignored local dirs: docs/table/ (local noun tables), work/, tmp/
* generated files: *.pyc, *.pyo, *.7z, *.csv, .DS_Store
* package markers: __init__.py
* test scaffolding: tests/fake_tools/ (fake tool scripts), tests/fixtures/
  (binary fixtures) - regenerated, not part of the documented tool layout

Ellipsis handling
-----------------
An entry such as `...（旧版：...）` is a "more files here" marker, not a
path.  It is skipped as a path, and the directory containing it is treated
as deliberately non-exhaustive: files under it are considered covered and
are not reported as [EXTRA].

Usage
-----
    check_docs.py [--readme README.md] [--repo .] [--verbose]

Exit code: 0 when the tree matches the repo; 1 when anything is missing,
mistyped or extra (a diff is printed).
"""
import argparse
import fnmatch
import os
import re
import sys
from collections import namedtuple

# Root-level repo metadata not part of the tool-layout tree.
EXCLUDED_ROOT_FILES = frozenset({
    "AGENTS.md", "LICENSE", "README.md", "pyproject.toml",
    ".gitignore", ".gitattributes",
})
# Local / generated / scaffolding dirs never expected in the tree.
EXCLUDED_DIRS = frozenset({
    ".git", ".venv", "docs/table", "work", "tmp", "__pycache__",
    ".pytest_cache", "tests/fake_tools", "tests/fixtures",
})
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".7z", ".csv", ".DS_Store")
# Package marker exempt everywhere.
PACKAGE_MARKER = "__init__.py"

_ENTRY_RE = re.compile(r"^((?:[│\s]\s{3}|\s{4})*)([├└])──\s?(.*)$")

Report = namedtuple("Report", (
    "entries",          # [(relpath, is_dir)] tree entries actually verified
    "missing",          # [relpath] in tree, absent from the repo
    "type_mismatch",    # [relpath] exists but with a different type
    "extra",            # [relpath] in repo, not covered by the tree
    "covered_files",    # set of repo files the tree covers
    "ellipsis_dirs",    # set of dirs containing a `...` marker
    "repo_files",       # set of non-excluded files found on disk
))


def is_excluded(relpath):
    """True when a repo path is not part of the documented tool layout."""
    parts = relpath.replace("\\", "/").split("/")
    for i in range(1, len(parts) + 1):
        if "/".join(parts[:i]) in EXCLUDED_DIRS:
            return True
    if len(parts) == 1 and parts[0] in EXCLUDED_ROOT_FILES:
        return True
    if parts[-1] == PACKAGE_MARKER:
        return True
    return relpath.endswith(EXCLUDED_SUFFIXES)


def find_tree_block(readme_text, root_name="GameTranslation/"):
    """Locate the fenced code block whose first line is the tree root.
    Returns the block's text (first line = root) or None."""
    for block in re.findall(r"```\n(.*?)\n```", readme_text, re.S):
        lines = block.splitlines()
        if lines and lines[0].strip().startswith(root_name):
            return block
    return None


def parse_tree(readme_text, root_name="GameTranslation/"):
    """Parse the directory tree code block.

    Returns (entries, ellipsis_dirs): entries is a list of (relpath,
    is_dir); ellipsis_dirs is the set of directories that contain a `...`
    "more files here" marker (the extra check is waived there).
    """
    block = find_tree_block(readme_text, root_name)
    if block is None:
        raise ValueError(
            "no directory tree block rooted at %r found (fenced ``` block "
            "whose first line starts with the root name)" % root_name)
    entries = []
    ellipsis_dirs = set()
    stack = []  # directory stack by depth
    for ln in block.splitlines()[1:]:
        m = _ENTRY_RE.match(ln)
        if not m:
            continue  # continuation line (description of the previous entry)
        depth = len(m.group(1)) // 4
        rest = m.group(3).rstrip()
        if "#" in rest:
            rest = rest.split("#", 1)[0].rstrip()
        if not rest:
            continue
        if rest.startswith("..."):
            # ellipsis marker: "more files here"; the containing directory
            # is the stack before this entry is added
            if stack:
                ellipsis_dirs.add("/".join(stack[:depth]))
            continue
        del stack[depth:]
        if rest.endswith("/"):
            name = rest.rstrip("/")
            stack.append(name)
            entries.append(("/".join(stack), True))
        else:
            entries.append(("/".join(stack + [rest]), False))
    return entries, ellipsis_dirs


def collect_repo_files(repo_path):
    """All files under repo_path (posix relative paths), skipping excluded
    paths and not descending into .git / __pycache__."""
    files = set()
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__")]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), repo_path)
            rel = rel.replace(os.sep, "/")
            if not is_excluded(rel):
                files.add(rel)
    return files


def compare(readme_path, repo_path):
    """Cross-check a README directory tree against a repo directory.

    Returns a Report namedtuple (see above).
    """
    with open(readme_path, encoding="utf-8") as f:
        text = f.read()
    entries, ellipsis_dirs = parse_tree(text)

    repo_files = collect_repo_files(repo_path)
    covered = set()
    missing = []
    type_mismatch = []
    checked = []

    for path, is_dir in entries:
        if is_excluded(path):
            continue
        checked.append((path, is_dir))
        full = os.path.join(repo_path, path)
        if is_dir:
            if os.path.isfile(full):
                type_mismatch.append(path)
            elif not os.path.isdir(full):
                missing.append(path)
        elif "*" in path:
            matches = [f for f in repo_files if fnmatch.fnmatch(f, path)]
            if matches:
                covered.update(matches)
            else:
                missing.append(path)
        elif os.path.isdir(full):
            type_mismatch.append(path)
        elif not os.path.isfile(full):
            missing.append(path)
        else:
            covered.add(path)

    # files under a `...` dir are deliberately not enumerated -> covered
    for d in ellipsis_dirs:
        prefix = d + "/"
        covered.update(f for f in repo_files if f.startswith(prefix))

    extra = sorted(f for f in repo_files if f not in covered)
    return Report(checked, missing, type_mismatch, extra, covered,
                  ellipsis_dirs, repo_files)


def render(report, verbose=False):
    """Render the comparison result as a list of lines."""
    lines = []
    if verbose:
        for path, is_dir in sorted(report.entries):
            lines.append("[OK] %s%s" % (path, "/" if is_dir else ""))
        lines.append("-- checked %d tree entries, %d repo files, "
                     "%d ellipsis dirs --" % (
                         len(report.entries), len(report.repo_files),
                         len(report.ellipsis_dirs)))
    for p in sorted(report.missing):
        lines.append("[MISSING] %s (in README tree, not found in repo)" % p)
    for p in sorted(report.type_mismatch):
        lines.append("[TYPE] %s (tree entry exists but with a different "
                     "type)" % p)
    for p in sorted(report.extra):
        lines.append("[EXTRA] %s (in repo, missing from README tree)" % p)
    if not (report.missing or report.type_mismatch or report.extra):
        lines.append("docs tree matches repo (%d tree entries, %d repo "
                     "files)" % (len(report.entries), len(report.repo_files)))
    else:
        lines.append("docs tree drift: %d missing, %d type, %d extra" % (
            len(report.missing), len(report.type_mismatch),
            len(report.extra)))
    return lines


def run(argv=None):
    """Run the check and return the exit code (0 = consistent, 1 = drift)."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", default=None,
                    help="README path (default: <repo>/README.md)")
    ap.add_argument("--repo", default=".",
                    help="repository root (default: current directory)")
    ap.add_argument("--verbose", action="store_true",
                    help="also print every checked tree entry")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    readme = args.readme or os.path.join(repo, "README.md")
    try:
        report = compare(readme, repo)
    except (OSError, ValueError) as e:
        print("check_docs: %s" % e, file=sys.stderr)
        return 1
    for line in render(report, verbose=args.verbose):
        print(line)
    if report.missing or report.type_mismatch or report.extra:
        return 1
    return 0


def main(argv=None):
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
