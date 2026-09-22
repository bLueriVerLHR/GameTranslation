#!/usr/bin/env python3
"""Packaging gate: the built wheel must be usable, not just buildable.

The audit behind this file built the wheel and measured it: 68 members, with
``translation/``, ``tools/`` and ``tyrano/ui_lang_zh.json`` all absent.  Three
documented entry points were broken by that:

  * ``python -m translation.cli``      - the v2 translation flow's public CLI
  * ``gt`` (via ``rpgmaker/plugincompat.py``, which does ``from tools import
    plugins_io``)
  * ``gt localize-ui`` (loads ``tyrano/ui_lang_zh.json``)

An editable install hid all of it by importing straight from the checkout, so
nothing in the suite noticed.  These tests build a real wheel, install it into
a throwaway directory, and import the public surface from there with the
checkout off ``sys.path``.

Isolation is deliberately belt-and-braces, because a half-isolated probe is
worse than none (it reports a green gate that proves nothing):

  * every probe runs with ``-S``, which skips ``site`` entirely and therefore
    never processes the venv's ``__editable__*.pth`` - the file that made
    ``import rpgmaker`` reach back into this checkout;
  * the interpreter's own site-packages are re-added *explicitly and after*
    the throwaway install, because ``-S`` also hides ``typer``/``py7zr`` and
    the probes genuinely need the runtime dependencies;
  * :func:`test_the_probe_rejects_an_empty_install` is the negative control:
    the same invocation against an empty directory MUST raise
    ``ModuleNotFoundError``.  It drops the site directories from its own
    environment, because on CI the wheel is installed into the system
    site-packages, so keeping them would let it import ``rpgmaker`` from the
    *global* install and fail for a reason unrelated to the isolation under
    test.  Without it, a future edit that quietly restores site processing
    would turn these tests back into no-ops;
  * :func:`test_the_isolation_control_itself_can_fail` guards the guard: the
    same empty directory *without* ``-S`` must still resolve ``rpgmaker``, so
    the control above cannot pass merely because import is broken everywhere.

Skipped when ``setuptools`` is unavailable, so a bare runtime install can still
run the suite (same policy as ``tests/test_lint.py``).

Marked `slow`: every test here depends on the session fixture that builds a
wheel and pip-installs it into a throwaway directory (measured ~8 s, the
second-slowest module).  CI keeps a dedicated `wheel` job for it, so the PR
layer can run without it and nothing goes unchecked.
"""
import os
import shutil
import subprocess
import sys
import zipfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.slow

# Members that must exist in the wheel: one per documented entry point plus the
# non-Python runtime data an installed copy reads through importlib.resources.
REQUIRED_MEMBERS = (
    "rpgmaker/__init__.py",
    "rpgmaker/cli.py",
    "rpgmaker/plugincompat.py",          # core js/plugins.js compatibility
    "rpgmaker/japanese.py",              # core kana regexes (engines import)
    "rpgmaker/plugins_io.py",            # core js/plugins.js parser
    "translation/__init__.py",
    "translation/cli.py",                # python -m translation.cli
    "tools/__init__.py",
    "tools/plugins_io.py",               # deprecated re-export shim
    "tools/japanese_utils.py",           # deprecated re-export shim
    "kirikiri/__init__.py",
    "kirikiri/kag/__init__.py",
    "tyrano/__init__.py",
    "wolfrpg/__init__.py",
    "unity/__init__.py",
    "unity/rmunite/__init__.py",
)

# Modules imported inside the throwaway install, with the checkout absent from
# sys.path.  Each one failed against the incomplete wheel.
IMPORT_PROBE = (
    "import rpgmaker, rpgmaker.cli, rpgmaker.plugincompat",
    "import rpgmaker.japanese, rpgmaker.plugins_io",
    "import tools.plugins_io, tools.japanese_utils, tools.plain_io",
    "import translation.cli",
    "import kirikiri.pipeline, kirikiri.ks_extract",
    "import tyrano.pipeline, tyrano.tyrano_extract",
    "import wolfrpg.dxarchive, unity.rmunite.extract_game",
    "from importlib.resources import files; "
    "files('kirikiri.kag').joinpath('js').is_dir() or "
    "(_ for _ in ()).throw(SystemExit('kag shim js/ missing'))",
    "from importlib.resources import files; "
    "p = files('tyrano').joinpath('ui_lang_zh.json'); "
    "p.is_file() or (_ for _ in ()).throw("
    "SystemExit('tyrano/ui_lang_zh.json missing'))",
)


def _setuptools_available():
    try:
        import setuptools  # noqa: F401
    except ImportError:
        return False
    return True


def _copy_tree_to(src, dest):
    """Copy the buildable source into `dest` (never the caches/tests).

    The wheel has to be built somewhere, and building it inside the repo root
    is actively harmful: several pytest workers import from `tools/` while
    setuptools deletes and rewrites `build/`, which fails with
    `could not delete 'build/.../tools/__init__.py': The process cannot access
    the file because it is being used by another process`.

    `uv.lock` is required, not optional: without it uv re-locks in the copy.
    """
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(
        "build", "dist", "*.egg-info", "__pycache__", ".venv", ".git",
        ".pytest_cache", ".ruff_cache", ".tmp", ".tools", ".pi", "tests",
        "docs", "tmp", "work", ".private", ".asset", "PLAN.md",
        # Hypothesis' example database is per-machine state, not source; a
        # copy that carries it would let a cached counterexample (or its
        # absence) decide what the copied tree tests.
        ".hypothesis"))


@pytest.fixture(scope="module")
def wheel_path(tmp_path_factory):
    """Build the wheel once for the whole module, from a source copy."""
    if not _setuptools_available():
        pytest.skip("setuptools is unavailable; cannot build a wheel")
    src = tmp_path_factory.mktemp("src")
    _copy_tree_to(REPO_ROOT, str(src / "GameTranslation"))
    out = src / "wheel"
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
         "--no-build-isolation", "-w", str(out)],
        cwd=str(src / "GameTranslation"), capture_output=True, text=True,
        encoding=PROBE_ENCODING, errors="replace", timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    wheels = [p for p in os.listdir(str(out)) if p.endswith(".whl")]
    assert len(wheels) == 1, wheels
    return os.path.join(str(out), wheels[0])


@pytest.fixture(scope="module")
def wheel_members(wheel_path):
    with zipfile.ZipFile(wheel_path) as zf:
        return sorted(i.filename for i in zf.infolist())


PROBE_TIMEOUT = 300
# The probes read the CLI's own `--help`, which is Chinese, so the decoding
# must not depend on the host locale (CP1252 on a default Windows console
# raises UnicodeDecodeError inside subprocess's reader thread).  Every
# subprocess in this module pins utf-8 for that reason.
PROBE_ENCODING = "utf-8"


def _dependency_paths():
    """Site directories of the interpreter running the tests.

    ``-S`` (see :func:`_probe_env`) removes every site directory along with
    the editable ``.pth`` that points at this checkout.  That is the point -
    but it also hides ``typer``, ``click``, ``py7zr`` and everything else the
    installed copy needs at runtime, so those paths are put back explicitly.
    They are always appended *after* the throwaway install, so the install
    wins every name collision.
    """
    import sysconfig

    paths = {sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]}
    return [p for p in sorted(paths) if os.path.isdir(p)]


def _probe_env(installed, dependencies=True):
    """Environment for a probe: the throwaway install first, deps after.

    ``PYTHONNOUSERSITE`` is belt-and-braces for the interpreter that cannot
    take ``-S`` (the Windows ``.exe`` console-script shim).

    ``dependencies=False`` drops the interpreter's own site directories.  The
    negative control needs that: on CI the wheel is installed into the system
    site-packages, so keeping them on the path would let the control import
    ``rpgmaker`` from the *global* install and fail for a reason that has
    nothing to do with the isolation being tested.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    paths = [installed] + (_dependency_paths() if dependencies else [])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONNOUSERSITE"] = "1"
    env["GT_NO_PROBE"] = "1"
    return env


def _cli_probe(installed, argv, expect="Usage"):
    """Run a console entry point against the throwaway install only."""
    proc = subprocess.run([sys.executable, "-S", "-m"] + argv + ["--help"],
                          cwd=installed, capture_output=True, text=True,
                          encoding=PROBE_ENCODING, errors="replace",
                          timeout=PROBE_TIMEOUT, env=_probe_env(installed))
    assert proc.returncode == 0, "{} --help failed\n{}\n{}".format(
        " ".join(argv), proc.stdout, proc.stderr)
    assert expect in proc.stdout or expect.lower() in proc.stdout, proc.stdout


@pytest.fixture(scope="module")
def installed(wheel_path, tmp_path_factory):
    """Install the wheel into a throwaway directory (module-scoped: it is slow)."""
    target = tmp_path_factory.mktemp("installed")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps",
         "--target", str(target), "--no-index", wheel_path],
        capture_output=True, text=True, encoding=PROBE_ENCODING,
        errors="replace", timeout=900)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return str(target)


def test_the_probe_rejects_an_empty_install(tmp_path):
    """Negative control for the isolation claim.

    If this fails, every probe in this module is worthless: it means the
    interpreter found `rpgmaker` somewhere other than the throwaway install
    (the venv's editable `.pth` pointing at this checkout, typically) and a
    missing wheel member would sail through as a pass.  Measured before the
    fix: an empty target still printed the checkout's `rpgmaker/__init__.py`.

    The dependency paths are deliberately left out here.  This control asserts
    that an empty target provides *nothing*; with the interpreter's own site
    directories on `PYTHONPATH` that claim is false on CI, where the wheel is
    installed globally, and the control would fail while the isolation it
    guards is perfectly intact.  `-S` is what makes the assertion meaningful
    in both environments: without it the site directories come back and the
    import succeeds again.
    """
    empty = tmp_path / "empty-install"
    empty.mkdir()
    (empty / "decoy.txt").write_text("not a package", encoding="utf-8")
    probe = "import rpgmaker; print(rpgmaker.__file__)"
    env = _probe_env(str(empty), dependencies=False)
    assert env["PYTHONPATH"] == str(empty), env["PYTHONPATH"]
    isolated = subprocess.run([sys.executable, "-S", "-c", probe],
                              cwd=str(empty), capture_output=True, text=True,
                              encoding=PROBE_ENCODING, errors="replace",
                              timeout=PROBE_TIMEOUT, env=env)
    assert isolated.returncode != 0, (
        "the probe imported rpgmaker from outside the throwaway install, so "
        "the packaging probes below prove nothing:\n" + isolated.stdout)
    assert "No module named 'rpgmaker'" in isolated.stderr, isolated.stderr


def test_the_isolation_control_itself_can_fail(tmp_path):
    """The control above must be able to fail; otherwise it asserts nothing.

    Same empty target, same interpreter, but *without* ``-S``: the site
    directories come back, so `rpgmaker` resolves to whatever the environment
    happens to provide (this checkout via the editable `.pth` locally, the
    globally installed wheel on CI).  If even that could not find `rpgmaker`,
    the negative control would be vacuous - it would pass because the import
    machinery is broken, not because the isolation works.
    """
    empty = tmp_path / "empty-install"
    empty.mkdir()
    probe = "import rpgmaker; print(rpgmaker.__file__)"
    loaded = subprocess.run([sys.executable, "-c", probe],
                            cwd=str(empty), capture_output=True, text=True,
                            encoding=PROBE_ENCODING, errors="replace",
                            timeout=PROBE_TIMEOUT,
                            env=_probe_env(str(empty), dependencies=False))
    assert loaded.returncode == 0, (
        "this environment exposes no rpgmaker at all, so the empty-install "
        "control proves nothing:" + loaded.stdout + loaded.stderr)


def test_source_copies_exclude_private_data(tmp_path):
    from tools.mutation_check import COPY_IGNORE

    source = tmp_path / "source"
    source.mkdir()
    for name in (".private", ".asset", ".hypothesis"):
        (source / name).mkdir()
        (source / name / "synthetic.txt").write_text("synthetic", encoding="utf-8")
    (source / "PLAN.md").write_text("local only", encoding="utf-8")
    (source / "public.py").write_text("", encoding="utf-8")
    built = tmp_path / "build-copy"
    _copy_tree_to(source, built)
    mutated = tmp_path / "mutation-copy"
    shutil.copytree(source, mutated, ignore=COPY_IGNORE)
    for copied in (built, mutated):
        assert sorted(p.name for p in copied.iterdir()) == ["public.py"]


class TestWheelContents:
    @pytest.mark.parametrize("member", REQUIRED_MEMBERS)
    def test_ships_every_documented_entry_point(self, wheel_members, member):
        assert member in wheel_members, (
            f"{member} is missing from the wheel; a documented entry point or a "
            "runtime import would fail on an installed copy (see "
            "pyproject.toml [tool.setuptools] packages)")

    def test_ships_kag_shim_sources(self, wheel_members):
        js = [m for m in wheel_members if m.startswith("kirikiri/kag/js/")]
        assert js, ("the KAG3 converter reads these through importlib.resources "
                    "(kirikiri/kag/shims.py); [tool.setuptools.package-data] "
                    "must keep shipping them")

    def test_ships_engine_ui_mapping(self, wheel_members):
        assert "tyrano/ui_lang_zh.json" in wheel_members

    def test_does_not_ship_the_test_suite(self, wheel_members):
        assert not [m for m in wheel_members if m.startswith("tests/")], \
            "tests/ must not be installed"

    def test_does_not_ship_build_leftovers(self, wheel_members):
        assert not [m for m in wheel_members if "__pycache__" in m], \
            "wheel carries __pycache__ entries"
        assert not [m for m in wheel_members if m.startswith("build/")], \
            "wheel carries unpacked build/ leftovers"

    def test_version_matches_the_module(self, wheel_path, wheel_members):
        """pyproject used to pin a literal that could drift from the package."""
        import rpgmaker
        metadata = [m for m in wheel_members if m.endswith(".dist-info/METADATA")]
        assert metadata, wheel_members
        with zipfile.ZipFile(wheel_path) as zf:
            text = zf.read(metadata[0]).decode("utf-8")
        version_line = [ln for ln in text.splitlines()
                        if ln.startswith("Version: ")][0]
        assert version_line == f"Version: {rpgmaker.__version__}", (
            "wheel version and rpgmaker.__version__ disagree; the version is "
            "declared dynamic in pyproject.toml and must stay single-sourced")


class TestInstalledWheelIsUsable:
    """The decisive test: install it elsewhere and import from there."""

    def test_console_scripts_are_declared(self, installed):
        """`gt` and `gt-tyrano` must be real console scripts.

        The filename depends on the platform and the installer (POSIX writes
        `gt`, Windows writes `gt.exe`), and `--target` may create either
        `bin/` or `Scripts/`, so both spellings are accepted in both places.
        """
        found = set()
        for sub in ("bin", "Scripts"):
            path = os.path.join(installed, sub)
            if os.path.isdir(path):
                found |= set(os.listdir(path))
        assert {"gt", "gt.exe"} & found, sorted(found)
        assert {"gt-tyrano", "gt-tyrano.exe"} & found, sorted(found)

    def test_installed_entry_points_help(self, installed):
        """Every documented CLI must at least start from an installed copy.

        PLAN.md Phase 1 lists these three by name; `gt localize-ui` is what
        reads tyrano/ui_lang_zh.json, which the wheel used to omit.
        """
        _cli_probe(installed, ["rpgmaker.cli"])
        _cli_probe(installed, ["translation.cli"])
        _cli_probe(installed, ["tyrano.pipeline"])

    def test_console_scripts_run(self, installed):
        """The declared scripts must be executable, not just present.

        Every candidate is exercised, not just the first one found.  A POSIX
        console script is a Python file, so it can be run with ``-S`` and gets
        the same checkout-free environment as the ``-m`` probes; the Windows
        ``.exe`` shim embeds its interpreter and cannot take ``-S``, so there
        the provenance argument rests on the ``-m`` probes above and this one
        only has to prove the script is wired to an importable entry point.
        """
        candidates = []
        for sub in ("bin", "Scripts"):
            path = os.path.join(installed, sub)
            if not os.path.isdir(path):
                continue
            candidates += [os.path.join(path, name)
                           for name in sorted(os.listdir(path))
                           if name.split(".")[0] in ("gt", "gt-tyrano")]
        assert candidates, sorted(os.listdir(installed))
        for script in candidates:
            argv = [sys.executable, "-S", script] \
                if script.endswith((".py", "gt", "gt-tyrano")) else [script]
            proc = subprocess.run(argv + ["--help"], cwd=installed,
                                  capture_output=True, text=True,
                                  encoding=PROBE_ENCODING, errors="replace",
                                  timeout=PROBE_TIMEOUT,
                                  env=_probe_env(installed))
            assert proc.returncode == 0, \
                f"{script} --help\n{proc.stdout}\n{proc.stderr}"

    @pytest.mark.parametrize("statement", IMPORT_PROBE)
    def test_public_surface_imports_without_the_checkout(self, installed,
                                                         statement):
        # `-S` skips `site`, so the venv's editable `.pth` cannot put this
        # checkout back on sys.path; the throwaway install and the runtime
        # dependencies are the only entries.  Without `-S` an empty target
        # still imported `rpgmaker` from the working copy.
        proc = subprocess.run([sys.executable, "-S", "-c", statement],
                              cwd=installed, capture_output=True, text=True,
                              encoding=PROBE_ENCODING, errors="replace",
                              timeout=PROBE_TIMEOUT, env=_probe_env(installed))
        assert proc.returncode == 0, (
            f"import failed from an installed copy: {statement!r}\n{proc.stdout}\n{proc.stderr}")
