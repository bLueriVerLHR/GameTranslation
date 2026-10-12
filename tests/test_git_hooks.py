#!/usr/bin/env python3
"""The `main` protection rule's mechanism: the in-repo pre-commit hook.

AGENTS.md "main 保护" states that main must not receive a commit before the
change has been audited and reviewed.  The rule is documentation; the
mechanism is `.githooks/pre-commit`, enabled by
`git config core.hooksPath .githooks` (or, before that mechanism has landed on
main, by copying the file to `.git/hooks/pre-commit`).

These tests invoke the hook the way git does - through a real `git commit` in
a throwaway repository - because the hook's whole value lies in how git calls
it.  A test of the shell logic in isolation would stay green while the
activation path was broken, which is the failure mode that matters here.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not available")


def git(cwd, *args, check=True):
    # encoding is explicit: the machine locale here is cp1252 while git emits
    # UTF-8 (paths, the hook's message), so `text=True` alone dies with
    # UnicodeDecodeError and leaves stdout None - the same locale trap that
    # tests/test_text_io_portability.py guards elsewhere.
    proc = subprocess.run([GIT, "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed "
                             f"({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc


def install_hook(repo):
    """Copy the hook where git will find it, as a clone would have it."""
    dest = repo / ".git" / "hooks" / "pre-commit"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HOOK, dest)
    os.chmod(dest, 0o755)
    return dest


def init_repo(tmp_path, branch="main", with_hook=True):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    # `git init -b` needs git 2.28; writing HEAD works on every version the
    # repo supports, and the branch name is the thing under test.
    git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    git(repo, "config", "user.email", "hook@example.invalid")
    git(repo, "config", "user.name", "hook test")
    # Pin hooks to this throwaway repo: a machine-global core.hooksPath would
    # otherwise make the test pass or fail for the wrong reason.
    git(repo, "config", "core.hooksPath", str(repo / ".git" / "hooks"))
    if with_hook:
        install_hook(repo)
    return repo


def commit(repo, message="change", *, check=True, extra=()):
    (repo / "file.txt").write_text(message, encoding="utf-8")
    git(repo, "add", "file.txt")
    return git(repo, "commit", "-m", message, *extra, check=check)


def head_exists(repo):
    return git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


# --------------------------------------------------------------- the rule

def test_direct_commit_on_main_is_refused(tmp_path):
    repo = init_repo(tmp_path)
    proc = commit(repo, check=False)
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "refuse" in out
    assert "AGENTS.md" in out          # the message points at the rule
    assert "main" in out
    assert not head_exists(repo), "no commit may have been created"


def test_the_refusal_message_explains_the_sanctioned_path(tmp_path):
    repo = init_repo(tmp_path)
    out = commit(repo, check=False)
    text = out.stdout + out.stderr
    assert "gtrans/<feature>" in text
    assert "merge" in text


# ----------------------------------------------------- the allowed paths

def test_commit_on_a_feature_branch_is_allowed(tmp_path):
    repo = init_repo(tmp_path)
    git(repo, "switch", "-c", "gtrans/feature")
    assert commit(repo).returncode == 0
    assert head_exists(repo)


def test_branch_name_that_merely_contains_main_is_allowed(tmp_path):
    """The comparison is exact: `gtrans/main-protection` is not `main`."""
    repo = init_repo(tmp_path)
    git(repo, "switch", "-c", "gtrans/main-protection")
    assert commit(repo).returncode == 0


def test_detached_head_commit_is_allowed(tmp_path):
    """A detached checkout is not a branch commit; nothing to protect."""
    repo = init_repo(tmp_path)
    git(repo, "switch", "-c", "feature")
    assert commit(repo, "one").returncode == 0
    git(repo, "checkout", "--detach")
    assert commit(repo, "two").returncode == 0


def test_concluding_a_merge_on_main_is_allowed(tmp_path):
    """The reviewed path must survive: a conflicted merge is finished with
    `git commit`, and blocking that would make the rule unlivable."""
    repo = init_repo(tmp_path, with_hook=False)
    assert commit(repo, "seed").returncode == 0
    git(repo, "switch", "-c", "feature")
    assert commit(repo, "feature side").returncode == 0
    git(repo, "switch", "main")
    assert commit(repo, "main side").returncode == 0
    install_hook(repo)                 # enforce from here on
    proc = git(repo, "merge", "feature", check=False)
    assert proc.returncode != 0, "the fixture must produce a conflict"
    assert (repo / ".git" / "MERGE_HEAD").is_file()
    # Resolving the conflict is not the hook's business; only the concluding
    # `git commit` is, and it is the moment a merge gets recorded.
    (repo / "file.txt").write_text("resolved", encoding="utf-8")
    git(repo, "add", "file.txt")
    concluded = git(repo, "commit", "--no-edit", check=False)
    assert concluded.returncode == 0, concluded.stdout + concluded.stderr
    parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert len(parents) == 3, "the conclusion must be a real merge commit"


def test_no_verify_bypasses_the_hook(tmp_path):
    """The escape hatch exists and is deliberate; documented in AGENTS.md."""
    repo = init_repo(tmp_path)
    assert commit(repo, extra=("--no-verify",)).returncode == 0
    assert head_exists(repo)


# -------------------------------------------------- the installed artifact

def test_hook_is_committed_executable(tmp_path):
    """A hook that arrives without its exec bit is a silent no-op."""
    assert HOOK.is_file(), f"{HOOK} is missing"
    assert HOOK.read_text(encoding="utf-8").startswith("#!"), "no shebang"
    listed = git(REPO_ROOT, "ls-files", "-s", ".githooks/pre-commit")
    if not listed.stdout.strip():
        pytest.fail(".githooks/pre-commit is not tracked; add it with git add")
    mode = listed.stdout.split()[0]
    assert mode == "100755", (f"the hook must be executable in the index "
                              f"(got {mode!r}); use `git update-index "
                              f"--chmod=+x .githooks/pre-commit`")


def test_hook_uses_lf_endings():
    r"""A CRLF script fails on sh with `\r: not found`, and core.autocrlf is
    on for this machine - so the worktree copy (the bytes git actually
    executes) is what has to be LF.  No git call, so no skip is needed."""
    assert b"\r\n" not in HOOK.read_bytes()
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "eol=lf" in attributes, (
        "the hook relies on .gitattributes keeping LF on this machine")
