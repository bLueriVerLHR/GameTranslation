#!/usr/bin/env python3
"""Repository hygiene gate (public-repo rules from AGENTS.md).

The documented shell scan could never pass: the rule text itself contains the
forbidden literals (`C:\\Users\\`, `/mnt/c/Users/`), so "zero hits" was
unreachable and real leaks hid behind the noise (a personal path sat in
tools/check_tyrano_build.py for months).  This test is the enforceable
version:

  * only files git considers part of the repo are scanned
  * placeholder forms ARE allowed (`<user>`, `<用户名>`, `<name>`), because
    AGENTS.md prescribes them
  * synthetic test fixtures naming a fake user are allowlisted explicitly
  * docs/table/** is excluded (legacy local data, never pushed)

It is deliberately narrow: it checks machine-path/username leaks.  Game
names, adult vocabulary and promotion wording are checked against the local
keyword table, which lives in the local private dictionary directory - see
docs/reference/local-layout.md.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# A real Windows user profile path, e.g. C:\Users\alice\... but NOT
# C:\Users\<user>\... (the prescribed placeholder form).
WIN_PROFILE = re.compile(r"[A-Za-z]:\\Users\\(?![<「])([A-Za-z0-9._-]+)")
# The same path as seen from WSL: /mnt/c/Users/alice/...
WSL_PROFILE = re.compile(r"/mnt/[a-z]/Users/(?![<「])([A-Za-z0-9._-]+)")
# The author's own machine appeared in a tracked file - never again.
BANNED_USERNAMES = {"blur"}

# Fake users used by tests to exercise path conversion.  Adding an entry here
# is a deliberate review decision, not a convenience.
ALLOWED_FIXTURE_USERS = {"me", "user", "tester", "test", "example", "alice"}

SKIP_DIRS = (".git", ".venv", ".tools", ".tmp", "docs/table",
            ".private", ".asset")
SKIP_SUFFIXES = (".pyc", ".pyo", ".7z", ".csv", ".png", ".jpg", ".ogg", ".webp")
# This file necessarily contains the forbidden literals (it is the detector),
# so it excludes itself from the repo-wide scan; its own patterns are unit
# tested below.
SELF = "tests/test_repo_hygiene.py"


def repo_files():
    """Files git considers part of the repo (tracked + untracked, no ignored).

    Falling back to a disk walk keeps the test usable outside a checkout.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, check=True, timeout=120).stdout
        names = [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        names = [str(p.relative_to(REPO)).replace(os.sep, "/")
                 for p in REPO.rglob("*") if p.is_file()]
    out = []
    for name in names:
        if name.startswith(SKIP_DIRS) or name.endswith(SKIP_SUFFIXES):
            continue
        if name == SELF:
            continue
        out.append(name)
    return sorted(out)


def _hits(path, pattern):
    try:
        text = (REPO / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [(i, m.group(0), m.group(1))
            for i, line in enumerate(text.splitlines(), 1)
            for m in [pattern.search(line)] if m]


def leaks():
    """[(path, line, match, username)] for every disallowed profile path."""
    found = []
    for name in repo_files():
        for pattern in (WIN_PROFILE, WSL_PROFILE):
            for line, match, user in _hits(name, pattern):
                if user in BANNED_USERNAMES or user not in ALLOWED_FIXTURE_USERS:
                    found.append((name, line, match, user))
    return found


def test_no_machine_profile_paths_in_tracked_files():
    found = leaks()
    assert found == [], (
        "machine path / username leaked into tracked files:\n" +
        "\n".join("  %s:%d  %s" % (p, ln, m) for p, ln, m, _u in found))


@pytest.mark.parametrize("path", ["AGENTS.md", "docs/CONTRIBUTING.md"])
def test_rule_files_use_placeholders_not_real_names(path):
    # the rule files legitimately quote the forbidden pattern, but only in its
    # placeholder form
    for pattern in (WIN_PROFILE, WSL_PROFILE):
        for line, match, user in _hits(path, pattern):
            assert user in ALLOWED_FIXTURE_USERS or user.startswith("<"), (
                "%s:%d uses a real profile name in the rule example: %s"
                % (path, line, match))


def test_local_tables_are_never_referenced_by_absolute_name():
    """AGENTS.md once referenced a local noun table by a filename that did not
    exist (the real file had a different name).  The rule must describe the
    table by role - the local private dictionary directory defines it - not by
    a name the repo cannot verify."""
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "adult_noun_table.md" not in text


def test_repo_files_helper_skips_local_tables():
    names = repo_files()
    assert not [n for n in names if n.startswith("docs/table/")]
    assert not [n for n in names if n.startswith(".git/")]
    # sanity: the helper does see normal repo files
    assert "rpgmaker/logsetup.py" in names


class TestPatterns:
    """The detector must flag real leaks and pass the prescribed forms."""

    def test_flags_a_real_profile_path(self):
        assert WIN_PROFILE.search(r'DEFAULT = r"C:\Users\alice\bin"')
        assert WSL_PROFILE.search("--dir /mnt/d/Users/bob/shots")

    def test_passes_the_placeholder_form(self):
        assert not WIN_PROFILE.search(r"`C:\Users\<用户名>\`")
        assert not WSL_PROFILE.search("--dir /mnt/c/Users/<user>/Pictures")

    def test_author_username_is_banned_even_in_allowlisted_position(self):
        real = WIN_PROFILE.search("C:\\Users\\blur\\.pi\\agent")
        assert real and real.group(1) == "blur"

    def test_current_repo_is_clean(self):
        assert leaks() == []
