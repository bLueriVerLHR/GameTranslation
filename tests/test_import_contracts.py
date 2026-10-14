"""Package imports must not depend on checkout-path bootstrap patches."""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _is_path(node, sys_names, path_names):
    if isinstance(node, ast.Subscript):
        return _is_path(node.value, sys_names, path_names)
    return ((isinstance(node, ast.Name) and node.id in path_names)
            or (isinstance(node, ast.Attribute) and node.attr == "path"
                and isinstance(node.value, ast.Name) and node.value.id in sys_names))


def _mutations(tree):
    """Find direct sys.path mutations, including aliases and assignments."""
    sys_names = {"sys"}
    path_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            sys_names.update(n.asname or n.name for n in node.names if n.name == "sys")
        elif isinstance(node, ast.ImportFrom) and node.module == "sys":
            path_names.update(n.asname or n.name for n in node.names if n.name == "path")
    lines = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"insert", "append", "extend", "remove", "pop", "clear"}
                and _is_path(node.func.value, sys_names, path_names)):
            lines.append(node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            if any(_is_path(n, sys_names, path_names) for n in targets):
                lines.append(node.lineno)
    return sorted(set(lines))


def _literal_code(node):
    """Render literal child-code strings; dynamic f-string values become None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [_literal_code(n) if not isinstance(n, ast.FormattedValue) else "None"
                 for n in node.values]
        return "".join(parts) if all(n is not None for n in parts) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal_code(node.left), _literal_code(node.right)
        return left + right if left is not None and right is not None else None
    return None


def _bootstrap_locations(source):
    tree = ast.parse(source)
    found = [f"line {n}" for n in _mutations(tree)]
    # Assigned child-code literals are executable snippets, unlike inert
    # parametrized negative fixtures used to test this detector below.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        text = _literal_code(node.value)
        if text is None or not re.search(r"\bsys\b", text):
            continue
        try:
            snippet = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        if _mutations(snippet):
            found.append(f"child code at line {node.lineno}")
    return found


def _bare_imports(source, tools):
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            first = name.split(".")[0]
            if first in tools or first in {"conftest", "pipeline"} or first.startswith("test_"):
                bad.append(f"line {node.lineno}: {name}")
    return bad


@pytest.mark.parametrize("source", [
    "import sys; sys.path.insert(0, 'tools')",
    "import sys as runtime; runtime.path.append('tools')",
    "from sys import path as search; search.extend(['tools'])",
    "import sys; sys.path = ['tools']",
    "import sys; sys.path += ['tools']",
    "import sys; sys.path[0:0] = ['tools']",
    "import sys; del sys.path[0]",
    "code = \"import sys; sys.path.insert(0, 'tools')\"",
    "code = f\"import sys; sys.path.insert(0, {root!r})\"",
    "code = 'import sys; ' + \"sys.path.append('tools')\"",
])
def test_bootstrap_detector_rejects_patches(source):
    assert _bootstrap_locations(source)


@pytest.mark.parametrize("source", [
    "from tools import plain_io",
    "from tests.helpers import make_game",
    "from pathlib import Path; root = Path(__file__).resolve().parents[1]",
    "import sys; before = list(sys.path)",
    "code = 'from tools import plain_io'",
    "description = 'Do not alter sys.path for imports.'",
])
def test_bootstrap_detector_accepts_formal_imports_and_resource_paths(source):
    assert _bootstrap_locations(source) == []


@pytest.mark.parametrize("source, expected", [
    ("import pipeline as pipeline_mod", True),
    ("from pipeline import main", True),
    ("from rpgmaker import cli as pipeline_mod", False),
    ("import plain_io", True),
    ("from plain_io import load", True),
    ("from conftest import make_game", True),
    ("from test_xp3tool import make_archive", True),
    ("from tools import plain_io", False),
    ("from tools.plain_io import load", False),
    ("from tests.helpers import make_game", False),
    ("from tests import test_xp3tool", False),
])
def test_bare_import_detector(source, expected):
    assert bool(_bare_imports(source, {"plain_io"})) is expected


def test_all_test_modules_use_package_imports_without_bootstrap():
    tools = {p.stem for p in (ROOT / "tools").glob("*.py")}
    files = sorted((ROOT / "tests").rglob("*.py"))
    assert len(files) > 100, "the test-source inventory unexpectedly shrank"
    failures = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        problems = _bootstrap_locations(source) + _bare_imports(source, tools)
        failures.extend(f"{path.relative_to(ROOT)}: {p}" for p in problems)
    assert not failures, "\n".join(failures)


def test_pytest_imports_by_package_without_pythonpath_override():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    options = config["tool"]["pytest"]["ini_options"]
    assert "--import-mode=importlib" in options["addopts"]
    assert not options.get("pythonpath"), "do not move bootstrap patches into config"
    assert (ROOT / "tests" / "__init__.py").is_file()
    assert not any(p == "tests" or p.startswith("tests.")
                   for p in config["tool"]["setuptools"]["packages"])


def test_installed_imports_work_outside_checkout_without_path_changes(tmp_path):
    code = (
        "import sys; before = list(sys.path); "
        "from tools import plain_io; from kirikiri import xp3tool; "
        "from translation import codes; "
        "assert sys.path == before; "
        "assert 'plain_io' not in sys.modules; "
        "assert plain_io.__name__ == 'tools.plain_io'; print('OK')"
    )
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                            env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK"


def test_isolated_negative_control_cannot_use_checkout_pythonpath(tmp_path):
    # This deliberate source-path injection is a negative control, never a
    # fallback for ordinary tests. -I ignores it, and -S removes installation.
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", "from tools import plain_io"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode != 0, "the control unexpectedly imported the checkout"
    assert "No module named 'tools'" in result.stderr, result.stderr
