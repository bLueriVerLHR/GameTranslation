"""Every `tools/` and `translation.cli` entry point must gate its own paths.

`tests/test_engine_ownership.py` proves the *engine* entry points enforce the
AGENTS.md CRITICAL cross-system rule.  The 27 command-line tools in `tools/`
plus the translation CLI were still unguarded: each took a game directory or a
build directory as a positional argument and went straight to `os.path.isdir`
/ `makedirs` / `open`.  A WSL process could therefore read and rewrite a
Windows-side game (the exact shape of the 2026-08 incident - and it was a read
as much as a write).

Every tool now calls `cliutil.own_paths("<what>", ...)` as the first statement
of its command body, which delegates to `platform.require_native_paths`.  Two
properties are pinned here:

1. **The gate is present and reached.**  Static check: the command body calls
   `own_paths` *before* its first filesystem call, for every inventoried tool.
   This catches a new tool (or a refactor) that silently drops the gate.
2. **The gate actually refuses.**  Dynamic check: with a simulated WSL, each
   tool exits non-zero with a cross-system refusal instead of proceeding.

A static-only check would be satisfied by a call that is never reached or that
is handed the wrong variable; the dynamic half would miss a tool that is not
safely callable.  Together they cover each other's blind spot.
"""
import ast
import os
import subprocess
import sys

import pytest

import rpgmaker.inventory as inventory
from rpgmaker import cliutil, platform

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The command-line tools that take a game/build/work path.  Kept as an
#: explicit list so a tool that is *deleted* fails this file rather than
#: silently shrinking the coverage (the inventory knows what exists; this
#: list knows what was audited).
GATED_TOOLS = [
    "tools/apply_ks_translation.py",
    "tools/apply_translation_to_patch.py",
    "tools/apply_tyrano_translation.py",
    "tools/augment_adv_resources.py",
    "tools/bake_csv_translation.py",
    "tools/bake_translation.py",
    "tools/bake_with_name_prefix.py",
    "tools/batch_decode_tlg.py",
    "tools/build_ks_translation.py",
    "tools/build_translation.py",
    "tools/build_tyrano_translation.py",
    "tools/build_wolf_translation.py",
    "tools/check_iscript_js.py",
    "tools/downscale_images.py",
    "tools/extract_remaining_text.py",
    "tools/extract_rvdata2.py",
    "tools/extract_text.py",
    "tools/fit_texture_4096.py",
    "tools/fix_mojibake_names.py",
    "tools/plugin_json_leaves.py",
    "tools/qc_build_kana.py",
    "tools/qc_ks_kana.py",
    "tools/resolve_text_keys.py",
    "tools/transcode_video.py",
    "tools/translate_rpgmaker.py",
    "tools/unlock_gallery.py",
    "translation/cli.py",
]

#: Names that mean "this call touches the filesystem".  `os.path.isdir` and
#: friends are included because a stat on a foreign mount is what the rule
#: forbids first, and because a gate placed after the first stat has already
#: admitted it meant to proceed.
FS_CALLS = {
    "makedirs", "mkdir", "rmtree", "remove", "unlink", "rename", "replace",
    "copy", "copy2", "copytree", "move", "open", "write_text", "write_bytes",
    "read_text", "read_bytes", "glob", "walk", "listdir", "scandir",
    "isdir", "isfile", "exists", "getsize", "stat", "abspath", "realpath",
}

#: Calls that read the filesystem without being named like it.  The `gt`
#: commands reach the disk through these before any `open`, so a gate placed
#: after one has already walked the foreign tree.
INDIRECT_FS_CALLS = {"resolve_web_root", "find_web_root"}

#: The two spellings of the gate: `cliutil.own_paths` in the tools, and the
#: local `_own` wrapper in rpgmaker/cli.py (that one has to convert the error
#: itself, because those commands run through Typer's standalone_mode).
GATE_NAMES = {"own_paths", "_own"}


def _command_functions(path):
    """Every top-level function in `path` that looks like a CLI command."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        body = ast.dump(node)
        if "setup_logging" not in body:
            continue
        found.append(node)
    return found


def _typer_command_functions(path):
    """Commands of a `typer.Typer` app (rpgmaker/cli.py).

    These are invisible to `_command_functions` twice over: they carry no
    `setup_logging` call of their own (`cliutil.app_options` puts the shared
    callback on the app), and they use bare `typer.Argument`/`typer.Option`
    instead of the `Annotated` form.  A decorator mentioning `command` is the
    reliable marker.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        decorators = [ast.unparse(d) for d in node.decorator_list]
        if any("command" in d for d in decorators):
            found.append(node)
    return found


def _is_fs_node(child):
    """True when this AST node is a filesystem touch we care about."""
    if isinstance(child, ast.Attribute) and child.attr in FS_CALLS:
        return True
    if isinstance(child, ast.Call):
        func = child.func
        names = FS_CALLS | INDIRECT_FS_CALLS
        if isinstance(func, ast.Attribute):
            return func.attr in names
        if isinstance(func, ast.Name):
            return func.id in names or func.id == "open"
    return False


def _first_fs_call_line(node):
    """Line number of the earliest filesystem call in a command body."""

    found = [child.lineno for child in ast.walk(node) if _is_fs_node(child)]
    return min(found) if found else None


def _own_paths_line(node):
    """Line number of the gate call (`cliutil.own_paths` or `_own`)."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr in GATE_NAMES:
            return child.lineno
        if isinstance(func, ast.Name) and func.id in GATE_NAMES:
            return child.lineno
    return None


class TestEveryToolGatesItsPaths:
    """The gate exists, and it runs before the first filesystem access."""

    @pytest.mark.parametrize("path", GATED_TOOLS)
    def test_the_command_calls_own_paths(self, path):
        functions = _command_functions(os.path.join(REPO_ROOT, path))
        assert functions, f"{path}: no command function found (setup_logging?)"
        for node in functions:
            assert _own_paths_line(node) is not None, (
                f"{path}:{node.lineno} {node.name}() never calls "
                "cliutil.own_paths, so its paths are ungated")

    @pytest.mark.parametrize("path", GATED_TOOLS)
    def test_the_gate_precedes_the_first_filesystem_call(self, path):
        """A gate after a stat/read has already admitted the foreign path.

        `tools/build_ks_translation.py` delegates to a library function, so it
        has no filesystem call of its own — the assertion is conditional and
        that case is covered by the dynamic test below.
        """
        for node in _command_functions(os.path.join(REPO_ROOT, path)):
            gate = _own_paths_line(node)
            first = _first_fs_call_line(node)
            if first is None:
                continue
            assert gate < first, (
                f"{path}:{node.lineno} {node.name}() calls a filesystem "
                f"function on line {first} before its gate on line {gate}")

    def test_the_audited_list_covers_every_path_taking_tool(self):
        """A new tool that takes a game directory must be added here.

        Searches the inventory for commands whose help mentions a game/build
        directory; if one is missing from `GATED_TOOLS` the audit has a hole.
        """
        hints = ("game directory", "game folder", "built game",
                 "output directory", "web root", "work dir", "source game")
        known = {os.path.splitext(os.path.basename(p))[0] for p in GATED_TOOLS}
        missing = []
        for record in inventory.MODULES:
            name = record.module.replace(".", "/")
            if not name.startswith("tools/"):
                continue
            mod = record.module
            if mod.split(".")[-1] in known:
                continue
            entry = record.entry or ""
            if any(h in entry for h in hints):
                missing.append(mod)
        assert not missing, (
            "these tools take a game/build path but are not in GATED_TOOLS: "
            f"{missing}")


class TestTheGtCliGatesItsPaths:
    """`rpgmaker/cli.py` is the `gt` / `pipeline.py` CLI, not a tools script.

    It was the last ungated family: these commands take a game folder and hand
    it straight to `resolve_web_root()`, which walks the tree, so an ungated
    one read the other storage side before any gate could fire.
    """

    CLI = "rpgmaker/cli.py"

    #: Commands that deliberately take no path argument, with the reason.
    PATHLESS = {
        "cmd_doctor": "takes only --json; it *reports* the resolved tool and "
                      "config locations, so refusing it would hide the "
                      "diagnostic the operator asked for",
    }

    def _commands(self):
        return _typer_command_functions(os.path.join(REPO_ROOT, self.CLI))

    def test_the_audited_command_list_is_complete(self):
        """A new `gt` command must be gated or added to PATHLESS.

        Without this the audit silently decays the moment someone adds a
        command.
        """
        names = {node.name for node in self._commands()}
        assert len(names) >= 20, f"found only {sorted(names)}"
        ungated = sorted(
            node.name for node in self._commands()
            if _own_paths_line(node) is None and node.name not in self.PATHLESS)
        assert not ungated, (
            f"{self.CLI}: these commands neither gate their paths nor are "
            f"declared pathless: {ungated}")

    def test_every_declared_pathless_command_is_still_pathless(self):
        """PATHLESS is an exemption, so it must not outlive its reason.

        If `doctor` ever grows a path argument this fails, and the exemption
        has to be justified again instead of silently covering a real path.
        """
        by_name = {node.name: node for node in self._commands()}
        for name, reason in self.PATHLESS.items():
            assert name in by_name, f"{name} is no longer a command"
            assert reason, f"{name}: an exemption needs a stated reason"
            node = by_name[name]
            path_args = [a.arg for a in node.args.args
                         if a.arg not in ("as_json", "verbose", "quiet",
                                          "log_file")]
            assert not path_args, (
                f"{self.CLI}:{node.lineno} {name}() now takes {path_args}, so "
                f"its exemption ({reason}) no longer applies")

    def test_the_gate_precedes_the_web_root_walk(self):
        """`resolve_web_root()` stats the tree, so it must come after the gate.

        This is the specific ordering bug the class exists for: a gate placed
        after `resolve_web_root()` has already walked a foreign mount.
        """
        for node in self._commands():
            gate = _own_paths_line(node)
            first = _first_fs_call_line(node)
            if gate is None or first is None:
                continue
            assert gate < first, (
                f"{self.CLI}:{node.lineno} {node.name}() touches the "
                f"filesystem on line {first} before its gate on line {gate}")

    def test_the_gt_cli_refuses_a_windows_side_path(self):
        """End to end: the refusal is one log line and exit code 1.

        `_run()` (used by `main`) swallows only SystemExit(0), so a refusal
        must surface as 1 - not as a traceback, and not as success.
        """
        code = (
            "import sys;"
            "from rpgmaker import platform;"
            "platform.is_wsl = lambda: True;"
            "import rpgmaker.cli as cli;"
            "cli.main(['build', '/mnt/c/game', '-o', '/mnt/c/out'])"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120)
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 1, (
            f"gt accepted a Windows-side path under WSL (exit "
            f"{proc.returncode}):\n{combined[-1500:]}")
        assert "cross-system" in combined, (
            f"gt refused for the wrong reason:\n{combined[-1500:]}")
        assert "refusing to build the JoiPlay folder" in combined, (
            f"the refusal must name the operation:\n{combined[-1500:]}")

    def test_the_gt_cli_accepts_a_native_path(self, tmp_path):
        """Negative control: a native path must not be refused.

        `build` is expected to fail afterwards (there is no web root in an
        empty folder) - what must not appear is a cross-system refusal, which
        is what a gate wired to the wrong variable would produce.
        """
        game = tmp_path / "game"
        game.mkdir()
        out = tmp_path / "out"
        code = (
            "import sys;"
            "import rpgmaker.cli as cli;"
            f"cli.main(['build', {str(game)!r}, '-o', {str(out)!r}])"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120)
        combined = proc.stdout + proc.stderr
        assert "cross-system" not in combined, (
            f"a native path was refused:\n{combined[-1500:]}")


class TestTheGateRefusesAtRuntime:
    """A simulated WSL + a Windows-side path must exit non-zero, not proceed."""

    def _run(self, module, args, monkeypatch_env):
        env = dict(os.environ)
        env.update(monkeypatch_env)
        return subprocess.run(
            [sys.executable, "-m", module] + args,
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, env=env)

    @pytest.mark.parametrize("module,args", [
        ("tools.extract_text", ["/mnt/c/game"]),
        ("tools.downscale_images", ["/mnt/c/game"]),
        ("tools.unlock_gallery", ["/mnt/c/game"]),
        ("tools.batch_decode_tlg", ["/mnt/c/game", "/mnt/c/out"]),
        ("tools.qc_ks_kana", ["/mnt/c/game"]),
        ("tools.build_wolf_translation", ["/mnt/c/patch", "/mnt/c/out"]),
        ("tools.bake_with_name_prefix",
         ["/mnt/c/game", "/mnt/c/out", "--trs", "/mnt/c/trs.json"]),
        ("tools.resolve_text_keys", ["/mnt/c/game"]),
    ])
    def test_foreign_path_is_refused(self, module, args):
        """The tool must fail with the cross-system error, not a traceback.

        `require_native_paths` refuses because the *processor* is simulated as
        WSL while the argument is spelled as a Windows-side mount.
        """
        code = (
            "import sys;"
            "from rpgmaker import platform;"
            "platform.is_wsl = lambda: True;"
            "import runpy;"
            f"sys.argv = ['{module}'] + {args!r};"
            f"runpy.run_module('{module}', run_name='__main__')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120)
        assert proc.returncode != 0, (
            f"{module} accepted a Windows-side path under WSL:\n"
            f"{proc.stdout[-1500:]}")
        combined = proc.stdout + proc.stderr
        assert "cross-system" in combined, (
            f"{module} failed for the wrong reason:\n{combined[-1500:]}")

    def test_the_same_call_succeeds_on_the_native_side(self, tmp_path):
        """The gate must not refuse a same-side path (negative control).

        Without this, a gate that refuses *everything* would pass the checks
        above.  The tool is expected to fail later for a missing input; what
        must not happen is a cross-system refusal.

        ``--output`` is redirected into ``tmp_path`` because the tool's
        default is ``translations.json`` relative to the CWD: leaving it
        default would write a stray file into the checkout.
        """
        game = tmp_path / "game"
        game.mkdir()
        out = tmp_path / "out.json"
        code = (
            "import sys;"
            "import runpy;"
            f"sys.argv = ['tools.extract_text', {str(game)!r},"
            f" '--output', {str(out)!r}];"
            "runpy.run_module('tools.extract_text', run_name='__main__')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120)
        combined = proc.stdout + proc.stderr
        assert "cross-system" not in combined, (
            f"a native path was refused:\n{combined[-1500:]}")


class TestOwnPathsHelper:
    """`cliutil.own_paths` is the shared declaration point for tool paths."""

    def test_blank_and_none_roles_are_skipped(self, tmp_path):
        """An unused optional option must not become an empty-path error.

        No ``is_wsl`` patch here: ``tmp_path`` is native on whatever host this
        runs on, so the assertion is about the None/``""`` filter alone.  A
        hard-coded POSIX spelling would be wrong on a Windows host, where
        ``/tmp/a`` is the drive-root spelling ``C:/tmp/a``.
        """
        owned = cliutil.own_paths("x", a=str(tmp_path), b=None, c="")
        assert set(owned) == {"a"}

    def test_a_multi_value_option_is_expanded_by_position(self, monkeypatch):
        """`--csv A B` refusing B must say which position, not just "list".

        A list value used to reach `PathRef.parse` whole and raise
        `TypeError: expected str, bytes or os.PathLike object, not list`, so
        the operator got a traceback instead of a named path.
        """
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        with pytest.raises(platform.CrossSideError, match=r"csv\[1\]="):
            cliutil.own_paths("x", csv=["C:/ok.csv", "C:/bad.csv"])

    def test_a_foreign_path_raises_the_shared_error(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        with pytest.raises(platform.CrossSideError, match="cross-system"):
            cliutil.own_paths("extract text", game_dir="/mnt/c/game")

    def test_run_turns_the_refusal_into_exit_one(self, monkeypatch, capsys):
        """The operator sees one line, not a Typer traceback."""
        monkeypatch.setattr(platform, "is_wsl", lambda: True)

        def cmd(game_dir: str) -> int:
            """Gated command."""
            cliutil.own_paths("test command", game_dir=game_dir)
            raise AssertionError("the gate did not fire")

        assert cliutil.run(cliutil.command_app(cmd), ["/mnt/c/game"]) == 1
        assert "refusing to test command" in capsys.readouterr().err
