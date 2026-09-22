#!/usr/bin/env python3
"""Portability contract: text I/O must not depend on the host locale codec.

Why this file exists
--------------------
The audit ran the suite on Windows, where the default text codec is cp1252.
Sixteen tests failed for one reason that had nothing to do with the code under
test: the *fixture* wrote `open(path, "w")` and then wrote Japanese into it, so
the host codec raised

    UnicodeEncodeError: 'charmap' codec can't encode characters in position
    15-17: character maps to <undefined>

This project translates Japanese into Chinese, so every text artifact it writes
is CJK.  A locale-dependent default is therefore a latent production bug, not
just a test smell: it works on the developer's machine and fails on a CI runner
(or, worse, silently writes mojibake with a permissive codec like cp1252,
which maps unmappable characters instead of raising).

The contract enforced here
--------------------------
1. Every builtin ``open()`` in **text** mode must pin ``encoding=``.
   Binary modes are exempt, and ``.open()`` attribute calls (``av.open``,
   ``Image.open``, ``zipfile.open``) are ignored because they do not take an
   ``encoding`` argument.
2. Source files must not start with a UTF-8 BOM.  Python tolerates it, but it
   breaks ``ast.parse`` on a token read from the file and makes the first line
   of a script fragile (a shebang preceded by U+FEFF is not a shebang).
3. The two known-bad patterns this audit actually hit are asserted directly, so
   the specific defects cannot come back even if the static scan is rewritten.
4. A ``subprocess`` call that asks for *text* output must pin ``encoding=``
   too.  This is the same defect class wearing a different hat: without
   ``encoding=`` the reader thread decodes the child's output with the host
   locale codec, so a child that prints Chinese (every CLI `--help` in this
   repo does) raises

    UnicodeDecodeError: 'charmap' codec can't decode byte 0x90 in position
    623: character maps to <undefined>

   inside ``threading`` rather than at the call site, which makes it look like
   an unrelated crash.  ``rpgmaker/proctools.py`` already pins UTF-8 for every
   caller that goes through it; this covers the direct calls.
"""
import ast
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# open(file, mode, ...) - only these count as text mode.
TEXT_MODES = frozenset(["r", "rt", "w", "wt", "a", "at", "r+", "w+", "a+",
                        "x", "xt"])

def _tracked_python_files():
    """Every .py file git knows about, including not-yet-committed ones.

    `--others --exclude-standard` matters: plain `git ls-files` omits untracked
    files, so a new module with a locale-dependent `open()` would pass this
    gate locally right up until it was committed (the same blind spot that let
    a dead resolver through `tests/test_tool_registry.py`'s first version).
    Gitignored files stay excluded, which is what keeps `.venv/`, `.tmp/` and
    the private data directories out of the scan.
    """
    proc = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "*.py"],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        pytest.skip("git is unavailable; cannot enumerate tracked files")
    return [p for p in proc.stdout.split() if p]


def _static_mode(node):
    """The mode argument of an open() call, or None when it is dynamic."""
    if len(node.args) >= 2:
        arg = node.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None
    for kw in node.keywords:
        if kw.arg == "mode":
            if isinstance(kw.value, ast.Constant):
                return kw.value.value
            return None
    return "r"          # the documented default


def _has_encoding(node):
    return any(kw.arg == "encoding" for kw in node.keywords)


def _scan_tree(tree):
    """[protects] (path, lineno, mode) for every unpinned text-mode open()"""
    problems = []
    dynamic = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # `av.open(...)` / `Image.open(...)` are attributes: not the builtin.
        if isinstance(func, ast.Attribute):
            continue
        if not (isinstance(func, ast.Name) and func.id == "open"):
            continue
        mode = _static_mode(node)
        if mode is None:
            dynamic.append(node.lineno)
            continue
        if "b" in mode or mode not in TEXT_MODES:
            continue
        if _has_encoding(node):
            continue
        problems.append((node.lineno, mode))
    return problems, dynamic


def _iter_scanned():
    """Yield (relpath, tree, source) for every tracked Python file."""
    for rel in _tracked_python_files():
        path = os.path.join(REPO_ROOT, rel)
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:                      # pragma: no cover
            pytest.skip(f"cannot read {rel}: {exc}")
        try:
            yield rel, ast.parse(raw.decode("utf-8"), rel), raw
        except (SyntaxError, UnicodeDecodeError) as exc:
            pytest.fail(f"{rel} is not parseable as UTF-8 Python: {exc}")


# subprocess entry points that take text=True / universal_newlines=True.
SUBPROCESS_CALLS = frozenset([
    "run", "Popen", "check_output", "check_call", "call",
])


def _static_truthy(node):
    """True/False when the argument is a literal, None when it is dynamic."""
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return False if isinstance(node, ast.Constant) and node.value is None \
        else None


def _scan_text_subprocess(tree):
    """[line] for subprocess calls requesting text without encoding=."""
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute)
                and func.attr in SUBPROCESS_CALLS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"):
            continue
        wants_text = None
        has_encoding = False
        for kw in node.keywords:
            if kw.arg in ("text", "universal_newlines"):
                wants_text = _static_truthy(kw.value)
            elif kw.arg == "encoding":
                has_encoding = True
        if wants_text and not has_encoding:
            offenders.append(node.lineno)
    return offenders


def test_every_tracked_python_file_parses_as_utf8():
    """A file that cannot be parsed cannot be scanned either."""
    count = 0
    for _rel, _tree, _raw in _iter_scanned():
        count += 1
    assert count > 100, "suspiciously few Python files: %d" % count


def test_text_mode_open_always_pins_an_encoding():
    """The defect class that broke 16 tests: locale-dependent text I/O."""
    offenders = []
    dynamic = []
    for rel, tree, _raw in _iter_scanned():
        problems, dynamic_lines = _scan_tree(tree)
        offenders.extend("%s:%d (mode=%r)" % (rel, ln, m)
                         for ln, m in problems)
        dynamic.extend("%s:%d" % (rel, ln) for ln in dynamic_lines)
    assert not offenders, (
        "builtin open() in text mode without encoding= - the host locale "
        "codec decides how CJK is written, which raises UnicodeEncodeError "
        "under Windows cp1252:\n  " + "\n  ".join(offenders))
    assert not dynamic, (
        "open() mode is not a literal, so encoding cannot be audited "
        "statically; pass a literal mode or an explicit encoding:\n  "
        + "\n  ".join(dynamic))


# Directories whose text-subprocess calls are exempt: the retired archive is
# gone (Phase 8), so only the guard's own helpers remain, which must not flag
# themselves.
SUBPROCESS_EXEMPT_PREFIXES = ("tests/test_text_io_portability.py",)


def test_no_text_subprocess_decodes_with_the_host_locale():
    """A child that prints Chinese must not be decoded with cp1252."""
    offenders = []
    for rel, tree, _raw in _iter_scanned():
        if rel.startswith(SUBPROCESS_EXEMPT_PREFIXES):
            continue
        offenders.extend("%s:%d" % (rel, ln)
                         for ln in _scan_text_subprocess(tree))
    assert not offenders, (
        "subprocess call asks for text output without encoding=; the child's "
        "stdout is then decoded with the host locale codec, so any CLI that "
        "prints Chinese raises UnicodeDecodeError inside its reader thread.  "
        "Pass encoding='utf-8' (plus errors='replace' when the child is not "
        "ours) or route the call through rpgmaker/proctools.py:\n  "
        + "\n  ".join(offenders))


def test_no_source_file_starts_with_a_bom():
    """U+FEFF at offset 0 breaks ast.parse and eats a leading shebang."""
    bom = []
    for rel in _tracked_python_files():
        path = os.path.join(REPO_ROOT, rel)
        with open(path, "rb") as handle:
            if handle.read(3) == b"\xef\xbb\xbf":
                bom.append(rel)
    assert not bom, "UTF-8 BOM at the start of: {}".format(", ".join(bom))


class TestTheSpecificDefectsFound:
    """Direct assertions on the incidents, independent of the static scan."""

    def test_compress_fixture_writes_utf8(self):
        """14 failures: this fixture writes a Japanese gameTitle."""
        path = os.path.join(REPO_ROOT, "tests", "test_compress.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        assert 'encoding="utf-8"' in source
        assert '"w", encoding="utf-8"' in source or \
            '"w",\n              encoding="utf-8"' in source

    def test_proctools_child_writes_raw_utf8_bytes(self):
        """1 failure: the child encoded with its own locale codec."""
        path = os.path.join(REPO_ROOT, "tests", "test_proctools.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        assert "sys.stdout.buffer.write" in source, (
            "the decoder contract must be tested with bytes, not with "
            "sys.stdout.write which re-encodes using the child's locale")

    def test_kirikiri_font_test_does_not_read_private_data(self):
        """1 failure: the test required gitignored local font data."""
        path = os.path.join(REPO_ROOT, "tests", "test_kirikiri_pipeline.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        assert "monkeypatch.setattr(pipeline, \"FONT_DIR\"" in source, (
            "the font positive case must build its own fixture; reading the "
            "real font dir made the suite fail on any clean checkout")

    def test_wheel_probe_decodes_cli_help_as_utf8(self):
        """The CLI answers `--help` in Chinese, so the probe must pin utf-8."""
        path = os.path.join(REPO_ROOT, "tests", "test_wheel_contents.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        assert 'PROBE_ENCODING = "utf-8"' in source, (
            "without a pinned encoding the reader thread decodes a child's "
            "stdout with the host locale codec and raises UnicodeDecodeError "
            "on the first Chinese character")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
