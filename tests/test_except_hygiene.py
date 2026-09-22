#!/usr/bin/env python3
"""Gate: a broad `except` must say why, and must not be silent.

`except Exception` is the right shape in this repo in several places - a
binary-format parser (`kirikiri/tlg.py`, `rpgmaker/media.py`) cannot enumerate
what a corrupt file will raise, and an optional-accelerator import guard
(`numba`) must not become fatal.  The rule is therefore not "never catch
broadly" but "never catch broadly *and say nothing*":

* **silent** - the handler body is only `pass`, a bare docstring, or
  `continue`, so nothing records what happened.  This is where a real defect
  hides: `tools/check_tyrano_build.py` swallowed every CDP error for the full
  60 s readiness wait, so a broken websocket looked like a slow game.
* **unexplained** - no `# noqa: BLE001` and no nearby comment naming the
  reason.  Without one, the next reader cannot tell a deliberate best-effort
  catch from a bug someone silenced.

Both failures are reported with `path:line` so the fix is a one-line edit.
Narrowing each site is the real work (PLAN Phase 6 task 5); this gate only
stops the count from growing while that happens.
"""
import ast
import os
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The whole point of the rule: these names mean "anything".
BROAD_NAMES = frozenset({"Exception", "BaseException"})

#: A handler whose body does nothing at all.  `log.debug` is not silent: the
#: record is the evidence that the catch was taken.
SILENT_BODY_NODES = (ast.Pass, ast.Continue)

#: The archive directory that was exempt here is gone (Phase 8 retired it), so
#: the list is now empty.  Kept as a named constant because it is the place a
#: future archive would be declared, and because the scan below reads through it.
EXEMPT_PREFIXES = ()

#: Measured when the gate was written.  Two directions only: fix a site and
#: lower it, or a new broad catch needs a reason and the count stays.  A
#: deliberate new best-effort catch is a reviewer-visible edit here.
SILENT_BUDGET = 0


def _tracked_python_files():
    """Tracked and untracked (but not ignored) Python files.

    `git ls-files` without `--others` would miss a new module until it is
    committed - the blind spot that let a dead resolver through Phase 4's
    first version of the tool-registry gate.
    """
    proc = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"git ls-files failed: {proc.stderr}"
    files = [rel for rel in proc.stdout.splitlines()
             if rel and not rel.startswith(EXEMPT_PREFIXES)]
    assert len(files) > 50, (
        f"the scan found only {len(files)} file(s) - the pathspec is wrong")
    return files


def _broad_names(handler):
    """Names a handler catches, or `["bare"]` for a bare `except:`."""
    node = handler.type
    if node is None:
        return ["bare"]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Tuple):
        return [ast.unparse(elt) for elt in node.elts]
    return [ast.unparse(node)]


def _is_broad(handler):
    return any(name in BROAD_NAMES or name == "bare"
               for name in _broad_names(handler))


def _is_silent(handler):
    """True when the body records nothing (only `pass`/docstring/`continue`)."""
    if not handler.body:
        return True
    for stmt in handler.body:
        if isinstance(stmt, SILENT_BODY_NODES):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # a docstring explains the catch, so it is not silent
        return False
    return True


def _justified(lines, handler):
    """True when a comment or `# noqa: BLE001` on the line names the reason.

    Four shapes count, because they are all reviewer-visible: a `noqa` on the
    `except` line, a contiguous comment block directly above it (where long
    reasons go), a comment inside the handler body (where the existing code
    usually explains the fallback), or a bare `raise` in the body (a re-throw
    is not a swallow, so it needs no prose).
    """
    index = handler.lineno - 1
    if index < 0 or index >= len(lines):
        return False
    if "noqa" in lines[index]:
        return True
    # A comment block directly above, stopping at the first code line.
    if index > 0 and lines[index - 1].lstrip().startswith("#"):
        return True
    # Any comment between the `except` line and the end of the handler body.
    end = handler.end_lineno or index + 1
    for line in lines[index:end]:
        if line.lstrip().startswith("#"):
            return True
    return any(isinstance(stmt, ast.Raise) for stmt in handler.body)


def _scan(rel, source, lines):
    """`(silent, unexplained)` sites in one file, as `path:line` strings."""
    tree = ast.parse(source, filename=rel)
    silent, unexplained = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not _is_broad(node):
            continue
        site = f"{rel}:{node.lineno}"
        if _is_silent(node):
            silent.append(site)
        elif not _justified(lines, node):
            unexplained.append(site)
    return silent, unexplained


def _scan_repo():
    silent, unexplained = [], []
    for rel in _tracked_python_files():
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as handle:
            source = handle.read()
        found_silent, found_unexplained = _scan(rel, source,
                                                source.splitlines())
        silent.extend(found_silent)
        unexplained.extend(found_unexplained)
    return silent, unexplained


def test_the_scan_reaches_the_whole_repo():
    """Guards the guard: an empty file list would make every test vacuous."""
    files = _tracked_python_files()
    assert any(rel.startswith("rpgmaker/") for rel in files)
    assert any(rel.startswith("tools/") for rel in files)


def test_no_broad_except_is_silent():
    """`except Exception: pass` hides the failure it was written to survive."""
    silent, _ = _scan_repo()
    assert len(silent) <= SILENT_BUDGET, (
        "these broad handlers swallow the error without recording it; log it, "
        "re-raise, or narrow the catch:\n  " + "\n  ".join(sorted(silent)))


def test_every_broad_except_names_its_reason():
    """A broad catch is fine; a broad catch with no stated reason is not."""
    _, unexplained = _scan_repo()
    assert not unexplained, (
        "these broad handlers carry no `# noqa: BLE001` and no comment naming "
        "the reason, so a deliberate best-effort catch is indistinguishable "
        "from a silenced bug:\n  " + "\n  ".join(sorted(unexplained)))


class TestTheScannerItself:
    """The measurements the two gates rely on, on known inputs."""

    def test_a_silent_pass_is_found(self):
        source = "try:\n    f()\nexcept Exception:\n    pass\n"
        silent, unexplained = _scan("x.py", source, source.splitlines())
        assert silent == ["x.py:3"] and not unexplained

    def test_a_continue_only_body_is_silent(self):
        source = "for x in y:\n    try:\n        f(x)\n    except Exception:\n        continue\n"
        silent, _ = _scan("x.py", source, source.splitlines())
        assert silent == ["x.py:4"]

    def test_a_logged_broad_except_is_neither(self):
        source = ("try:\n    f()\nexcept Exception as exc:  # noqa: BLE001\n"
                  "    log.debug('f failed: %s', exc)\n")
        assert _scan("x.py", source, source.splitlines()) == ([], [])

    def test_a_reason_comment_above_counts_as_justified(self):
        source = ("try:\n    f()\n# A corrupt file can raise anything here.\n"
                  "except Exception as exc:\n    log.debug('%s', exc)\n")
        assert _scan("x.py", source, source.splitlines()) == ([], [])

    def test_a_reason_comment_inside_the_body_counts(self):
        source = ("try:\n    f()\nexcept Exception as exc:\n"
                  "    # Best effort: a partial file is still worth reading.\n"
                  "    log.debug('%s', exc)\n")
        assert _scan("x.py", source, source.splitlines()) == ([], [])

    def test_a_reraise_needs_no_comment(self):
        source = "try:\n    f()\nexcept BaseException:\n    raise\n"
        assert _scan("x.py", source, source.splitlines()) == ([], [])

    def test_a_broad_except_without_a_reason_is_reported(self):
        source = "try:\n    f()\nexcept Exception as exc:\n    log.debug('%s', exc)\n"
        silent, unexplained = _scan("x.py", source, source.splitlines())
        assert unexplained == ["x.py:3"] and not silent

    def test_a_narrow_catch_is_ignored(self):
        source = "try:\n    f()\nexcept (OSError, ValueError):\n    pass\n"
        assert _scan("x.py", source, source.splitlines()) == ([], [])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
