#!/usr/bin/env python3
"""Documentation tree vs. repo consistency check (repo layout tree).

Parses the box-drawing directory tree inside the layout document (the
fenced code block rooted at the repo name, e.g. "GameTranslation/") and
verifies it stays in sync with the actual files in the repository.

The tree lives in ``docs/reference/repo-layout.md`` - the single
authoritative place for the layout - so the README can stay a short entry
document instead of a wall of directory listings.  The tree is a
consistency check, not the semantic one: which module belongs to which
engine and whether it is live is answered by ``rpgmaker/inventory.py`` and
``docs/reference/support-matrix.md``.

What is checked
---------------
* every path listed in the layout tree must exist in the repo with the
  right type: a `name/` entry must be a directory, a plain entry must be a
  file, and an entry containing a glob (e.g. `test_*.py`) must match at
  least one file.  A tree entry that is gone from the repo is reported as
  [MISSING] (or [TYPE] when it exists with a different type) and fails the
  run.
* every repo file must be covered by the tree: an explicit file entry, a
  glob entry in its directory, or a `...` ellipsis marker in that
  directory.  A repo file the tree never mentions is reported as [EXTRA]
  and fails the run.

It also runs the **documentation gates** over every tracked markdown file:

* relative links resolve (targets that point at a real file or directory)
* no duplicate headings inside one file (they break anchor links)
* no operational reference to a local private data directory (that data is
  not in the repo, so a reader following the doc hits a dead end)
* entry points named in the docs really exist (``python -m <module>`` must
  resolve to a repo module or a known external tool; ``gt``/``gt-tyrano``
  subcommands must be registered on the real Typer apps)

The gates are deliberately *structural*: they catch the drift that a human
reviewer would miss (a renamed file, a deleted section, a stale command),
not wrong prose.

What is NOT checked (excluded, so the tree does not have to list them)
---------------------------------------------------------------------
* repo metadata at the root: AGENTS.md, LICENSE, README.md, pyproject.toml,
  .gitignore, .gitattributes (the tree documents the tool layout, not the
  repo metadata)
* VCS / env internals: .git/, .venv/, __pycache__/
* gitignored local dirs: the local private data roots (dictionaries, machine
  config, fonts - see docs/reference/local-layout.md), work/, tmp/, .tmp/
  (workspace scratch), .pi/ (harness state), .tools/ (local downloads &
  test runtimes).  The repo file set comes from git
  (`ls-files --cached --others --exclude-standard`), so anything gitignored is
  invisible here automatically; the exclusion list below is only a fallback
  for running outside a git checkout.
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
    check_docs.py [--readme docs/reference/repo-layout.md] [--repo .]
                  [--tree-only] [--verbose]

Exit code: 0 when the tree matches the repo and every gate passes; 1 when
the tree drifted, a gate failed, or a gate could not run (a diff is
printed).  A gate that cannot run is a failure, never a silent pass.
"""
import fnmatch
import importlib
import importlib.util
import os
import re
import sys
from collections import namedtuple
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402
from rpgmaker import proctools  # noqa: E402
from rpgmaker.tool_registry import find_git  # noqa: E402

# --- documentation gates -------------------------------------------------

# Every local private data root the project has used or documented.  Naming
# one of these as the place to read a dictionary/password/font makes the
# document un-followable on a fresh checkout; the escape hatch for the
# documents that *define* them is an allowlist entry below.
#   - ``.private/`` and ``.asset/`` are the current private roots, but the
#     layout behind them (``.private/secrets/passwords.*``) is not knowable
#     from a fresh checkout, so documents must name the concept and let
#     docs/reference/local-layout.md define the location.
#   - ``docs/table/`` is the legacy layout the current one replaces.  It stays
#     on the list so a re-introduced hard-coded path fails loudly.
# Not listed: ``.tmp/``, ``.tools/`` and ``.venv/`` - the instructions that
# mention them are the thing that creates them (``git clone ... .tools/``),
# so naming those paths is actionable rather than unfollowable.
LOCAL_PRIVATE_NAMES = (
    "docs/table",
    ".private/", ".private\\", ".asset/",
)
# Documents allowed to name them: the layout reference defines them, AGENTS.md
# states the rule, and the memory notes record the migration history.
LOCAL_PRIVATE_ALLOWED = frozenset({
    "docs/reference/local-layout.md",
    "docs/reference/support-matrix.md",
    "AGENTS.md",
})
# Archive files describe the layout as it *was*, so old paths are their subject
# matter rather than an instruction.  The archive preamble says not to follow
# them; everything outside it must not name a local private path.
LOCAL_PRIVATE_ALLOWED_DIRS = ("docs/archive/",)

# ``python -m X`` entries that are not repo modules (standard library, or a
# third-party tool the docs legitimately tell the operator to run).  Anything
# else must resolve to a module inside the repo - an allowlist that grows by
# accident is how a typo survives.
EXTERNAL_MODULES = frozenset({
    "build",          # PyPA build frontend (release steps)
    "pip", "pip_audit",
    "pytest", "ruff", "uv", "py_compile", "venv",
    "translation.cli",  # resolved from repo root below, kept for clarity
})
# ``gt``/``gt-tyrano`` subcommands documented but not implemented yet.  Each
# entry is a promise with an owner phase; remove it when the command lands.
PLANNED_COMMANDS = frozenset({
    "workspace",   # PLAN Phase 4: gt workspace list/info/clean
})
CLI_APPS = (
    ("gt", "rpgmaker.cli", "app"),
    ("gt-tyrano", "rpgmaker.cli", "tyrano"),
)

_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE_RE = re.compile(r"``(?:[^`]|`(?!`))+``|`+([^`]+)`+")
_MODULE_ENTRY_RE = re.compile(r"python\d?(?:\.\d+)?\s+-m\s+([A-Za-z_][\w.]*)")
_CMD_ENTRY_RE = re.compile(r"\b(gt-tyrano|gt)\s+([a-z][a-z0-9-]*)")

Issue = namedtuple("Issue", ("path", "line", "kind", "detail"))


def _strip_code(text):
    r"""Drop fenced blocks and inline code spans before link/heading checks.

    A code span such as ``re.sub(r'^\[s\]\s*$', ...)`` contains something
    that looks exactly like a markdown link.  Matching it produced the one
    false positive this gate was written against
    (docs/experience-tyrano.md:40), so stripping is part of the contract,
    not an optimisation.
    """
    out = []
    fenced = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        out.append(_INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line))
    return "\n".join(out)


def _each_line(text, skip_fenced=True):
    """Yield (1-based line number, line) outside fenced blocks.

    ``skip_fenced=False`` scans every line: entry-point mentions live inside
    code fences (that is where commands are written), while link and heading
    checks must not look at sample code.
    """
    fenced = False
    for i, line in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            fenced = not fenced
            continue
        if not fenced or not skip_fenced:
            yield i, line


def link_issues(path, text):
    """Relative markdown links that do not resolve to a real file/dir."""
    issues = []
    stripped = _strip_code(text)
    for n, line in _each_line(stripped):
        for m in _LINK_RE.finditer(line):
            target = m.group(2).strip()
            if not target or target.startswith(("#", "http://", "https://",
                                                "mailto:", "tel:")):
                continue
            if target.startswith("<") and target.endswith(">"):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            resolved = os.path.normpath(
                os.path.join(os.path.dirname(path), target.replace("/", os.sep)))
            if not os.path.exists(resolved):
                issues.append(Issue(path, n, "link",
                                    f"{m.group(2)!r} does not resolve ({resolved})"))
    return issues


def heading_issues(path, text):
    """Duplicate headings in one file (they break anchor links)."""
    seen = {}
    issues = []
    for n, line in _each_line(text):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        key = re.sub(r"[^\w\u4e00-\u9fff]+", "", m.group(2)).lower()
        if not key:
            continue
        if key in seen:
            issues.append(Issue(path, n, "heading",
                                "duplicate heading %r (first at line %d)" % (
                                    m.group(2), seen[key])))
        else:
            seen[key] = n
    return issues


def private_data_issues(path, text):
    """Operational references to a local private data directory.

    Any of these makes a document un-followable on a fresh checkout, so the
    escape hatch is an allowlist entry here rather than a rewording.
    """
    rel = path.replace(os.sep, "/")
    if rel in LOCAL_PRIVATE_ALLOWED or rel.startswith(LOCAL_PRIVATE_ALLOWED_DIRS):
        return []
    issues = []
    for n, line in _each_line(text):
        for name in LOCAL_PRIVATE_NAMES:
            if name in line:
                issues.append(Issue(path, n, "private-data",
                                    f"names a local private data location {name!r}; "
                                    "state the logical location or the API "
                                    "instead (see "
                                    "docs/reference/local-layout.md)"))
                break
    return issues

def _repo_module_exists(repo_root, module):
    parts = module.split(".")
    base = os.path.join(repo_root, *parts)
    return (os.path.isfile(base + ".py")
            or os.path.isfile(os.path.join(base, "__init__.py")))


def _registered_commands(module, attr, repo_root):
    """Command names registered on a Typer app, or None when unimportable."""
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    try:
        mod = importlib.import_module(module)
    except Exception:  # noqa: BLE001 - a broken import is reported by callers
        return None
    app = getattr(mod, attr, None)
    if app is None or not hasattr(app, "registered_commands"):
        return None
    names = set()
    for cmd in app.registered_commands:
        name = getattr(cmd, "name", None)
        if not name and getattr(cmd, "callback", None) is not None:
            name = cmd.callback.__name__
        if name:
            names.add(name.replace("_", "-"))
    return names or None


def entry_point_issues(path, text, repo_root, command_sets):
    """Entry points named in the docs must exist."""
    issues = []
    for n, line in _each_line(text, skip_fenced=False):
        for m in _MODULE_ENTRY_RE.finditer(_INLINE_CODE_RE.sub(" ", line)):
            module = m.group(1)
            if module in EXTERNAL_MODULES:
                continue
            if not _repo_module_exists(repo_root, module):
                issues.append(Issue(path, n, "entry",
                                    f"python -m {module} is not a repo module and is "
                                    "not an allowlisted external tool"))
        for m in _CMD_ENTRY_RE.finditer(line):
            prog, command = m.group(1), m.group(2)
            known = command_sets.get(prog)
            if known is None:
                issues.append(Issue(path, n, "entry",
                                    f"{prog} command set could not be read from the "
                                    f"CLI (the gate cannot verify {command!r})"))
            elif command not in known and command not in PLANNED_COMMANDS:
                issues.append(Issue(path, n, "entry",
                                    f"{prog} {command} is not a registered command"))
    return issues


def markdown_files(repo_root):
    """Tracked markdown files to gate (git view, disk walk fallback)."""
    from_git = git_repo_files(repo_root)
    files = from_git if from_git is not None else collect_repo_files(repo_root)
    return sorted(f for f in files if f.endswith(".md") and not is_excluded(f))


def gate_issues(repo_root, files=None, command_sets=None):
    """Run every documentation gate; returns a list of Issue."""
    if files is None:
        files = markdown_files(repo_root)
    if command_sets is None:
        command_sets = {}
        for prog, module, attr in CLI_APPS:
            command_sets[prog] = _registered_commands(module, attr, repo_root)
    issues = []
    for rel in files:
        full = os.path.join(repo_root, rel.replace("/", os.sep))
        try:
            with open(full, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            issues.append(Issue(rel, 0, "io", str(e)))
            continue
        issues += link_issues(rel, text)
        issues += heading_issues(rel, text)
        issues += private_data_issues(rel, text)
        issues += entry_point_issues(rel, text, repo_root, command_sets)
    return issues


def render_gates(issues):
    """Render gate issues as lines (one per issue, path:line grouped)."""
    lines = ["[%s] %s:%d: %s" % (
        issue.kind.upper(), issue.path, issue.line, issue.detail)
        for issue in sorted(issues)]
    if not issues:
        lines.append("documentation gates pass")
    else:
        lines.append("documentation gate failures: %d" % len(issues))
    return lines


# Root-level repo metadata not part of the tool-layout tree.
EXCLUDED_ROOT_FILES = frozenset({
    "AGENTS.md", "CHANGELOG.md", "LICENSE", "README.md", "pyproject.toml",
    ".gitignore", ".gitattributes",
})
# Local / generated / scaffolding dirs never expected in the tree.
# `.pi/` holds the agent harness runtime state (background-task logs), which is
# gitignored and must not count as repository content.  `.tools/` holds local
# downloads (engine sources used as a test runtime); `.tmp/` is workspace
# scratch.  The private data roots (`.private/`, `.asset/`) and the legacy
# `docs/table/` are gitignored too.  This list is the fallback for a non-git
# run, since the git-driven file set already skips them.
EXCLUDED_DIRS = frozenset({
    ".git", ".github", ".venv", ".pi", ".tools", ".tmp",
    ".private", ".asset", "docs/table",
    "work", "tmp",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", "tests/fake_tools", "tests/fixtures",
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
            f"no directory tree block rooted at {root_name!r} found (fenced ``` block "
            "whose first line starts with the root name)")
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


def git_repo_files(repo_path):
    """Files git considers part of the repo, or None when git is unusable.

    `ls-files --cached --others --exclude-standard` = tracked files plus
    untracked-but-not-ignored files: everything that would be committed.
    Taking the repo's file set from git (rather than a raw disk walk) makes
    this check immune to local artifacts by construction - a gitignored
    download directory, work copy or virtualenv can never be reported as an
    [EXTRA] repo file, so no hand-maintained exclusion list can fall behind.

    The git binary is resolved through the shared resolver (tool_registry.TOOLS),
    not a private PATH lookup, so `pipeline.py doctor` reports the same
    answer this check uses.  None (no git / git failed) selects the disk-walk
    fallback below.
    """
    git = find_git()
    if not git:
        return None
    try:
        proc = proctools.run(
            [git, "-C", repo_path, "ls-files", "-z", "--cached",
             "--others", "--exclude-standard"],
            timeout=120, label="git ls-files", check=False,
            errors="surrogateescape")
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout
    return {p for p in raw.split("\0") if p and not is_excluded(p)}


def collect_repo_files(repo_path):
    """All files that belong to the repo (posix relative paths).

    Prefers git's view; falls back to a disk walk (with the exclusion list
    above) when git is unavailable, so the check still works outside a
    checkout.
    """
    from_git = git_repo_files(repo_path)
    if from_git is not None:
        return from_git
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
            lines.append("[OK] {}{}".format(path, "/" if is_dir else ""))
        lines.append("-- checked %d tree entries, %d repo files, "
                     "%d ellipsis dirs --" % (
                         len(report.entries), len(report.repo_files),
                         len(report.ellipsis_dirs)))
    lines.extend(f"[MISSING] {p} (in the layout tree, not found in repo)"
                 for p in sorted(report.missing))
    lines.extend(f"[TYPE] {p} (tree entry exists but with a different type)"
                 for p in sorted(report.type_mismatch))
    lines.extend(f"[EXTRA] {p} (in repo, missing from the layout tree)"
                 for p in sorted(report.extra))
    if not (report.missing or report.type_mismatch or report.extra):
        lines.append("docs tree matches repo (%d tree entries, %d repo "
                     "files)" % (len(report.entries), len(report.repo_files)))
    else:
        lines.append("docs tree drift: %d missing, %d type, %d extra" % (
            len(report.missing), len(report.type_mismatch),
            len(report.extra)))
    return lines


def cmd(readme: Annotated[str | None, cliutil.Option(
            "--readme", help="tree document path (default: "
            "<repo>/docs/reference/repo-layout.md)")] = None,
        repo: Annotated[str, cliutil.Option(
            "--repo", help="repository root (default: current directory)")] = ".",
        tree_only: Annotated[bool, cliutil.Option(
            "--tree-only", help="only check the directory tree, skip the "
            "markdown documentation gates")] = False,
        verbose: Annotated[bool, cliutil.Option(
            "--verbose", help="also print every checked tree entry")] = False,
        ) -> int:
    repo_root = os.path.abspath(repo)
    readme_path = readme or os.path.join(
        repo_root, "docs", "reference", "repo-layout.md")
    failed = False
    try:
        report = compare(readme_path, repo_root)
    except (OSError, ValueError) as e:
        print(f"check_docs: {e}", file=sys.stderr)
        return 1
    for line in render(report, verbose=verbose):
        print(line)
    if report.missing or report.type_mismatch or report.extra:
        failed = True
    if not tree_only:
        issues = gate_issues(repo_root)
        for line in render_gates(issues):
            print(line)
        if issues:
            failed = True
    return 1 if failed else 0


app = cliutil.command_app(cmd, help=__doc__)
# argparse used the module docstring as the command description; keep that
# visible in --help (a collapsed single-command app shows the command help).
cmd.__doc__ = __doc__


def run(argv=None) -> int:
    """Run the check and return the exit code (0 = consistent, 1 = drift)."""
    return cliutil.run(app, argv, prog="check_docs.py")


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
