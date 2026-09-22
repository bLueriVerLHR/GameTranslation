"""The module inventory must cover the repository, and stay true.

`rpgmaker/inventory.py` is only worth having if it cannot rot.  The failure
mode it prevents is the one that created the mess: a script nobody can date,
whose status is decided by guessing from its filename.  So this module checks
the inventory against the actual tree and against actual imports:

* every production `.py` appears in the inventory (no unclassified files);
* every inventoried module that still exists has a valid status;
* `wheel=True` is not wishful thinking - it matches real cross-package imports;
* superseded modules name what replaced them;
* no module claims a capability its engine cannot have.
"""

import ast
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from rpgmaker import inventory  # noqa: E402

#: Packages that hold production code.  `tests/` is not a product; the retired
#: `superseded/` archive was deleted in Phase 8.
PRODUCTION_PACKAGES = ("rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity",
                       "translation", "tools")


def _git_ls_files(pattern):
    """Files git knows about matching a pathspec, including untracked ones.

    Two things have gone wrong here before, so both are pinned:

    * `pattern` must reach *every directory depth*.  A bare `*.py` is not a
      recursive glob to git, and `:(glob)*.py` is worse than useless - it
      matches only the repo-root files, so `_production_files()` silently
      returned just `['pipeline.py']` and the "every production file is
      classified" gate was near-vacuous (the packages looked empty, so
      nothing was ever reported as unclassified).  The `**/` prefix is what
      makes it recursive; the assertion below keeps a future edit from
      quieting the scan again.
    * `--others --exclude-standard` keeps untracked files in scope: a plain
      `git ls-files` omits them, so a new module would pass this gate locally
      right up until it was committed.  Gitignored paths stay excluded.
    """
    if not pattern.startswith("**/"):
        pattern = "**/" + pattern
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         ":(glob)" + pattern],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True).stdout
    return [line for line in out.splitlines() if line]


def _production_files():
    """Every production `.py` git knows about, as a repo-relative path."""
    files = list(_git_ls_files("*.py"))
    # A near-empty scan is the failure mode of a wrong pathspec, and it makes
    # every gate below pass for the wrong reason.
    assert len(files) > 100, (
        "the production scan found only %d file(s) - the pathspec is wrong: %s"
        % (len(files), files[:5]))
    return sorted(
        rel for rel in files
        if rel.split("/")[0] in PRODUCTION_PACKAGES or "/" not in rel)


def _module_name(rel):
    """Inventory name for a repo-relative path.

    `a/b.py` -> `a.b`; `a/b/__init__.py` -> `a.b` (a package is inventoried as
    the package, not as its `__init__` module); a root script keeps its
    filename because it is not importable as a module.
    """
    if rel.endswith("/__init__.py"):
        return rel[: -len("/__init__.py")].replace("/", ".")
    if "/" not in rel:
        return rel
    return rel[:-3].replace("/", ".")


def _is_facade(rel):
    """Root or package `__init__` files carry no logic of their own."""
    return os.path.basename(rel) in ("__init__.py",)


class TestCoverageOfTheRepository:
    def test_every_production_file_is_inventoried(self):
        """An unclassified file is exactly the situation this table prevents."""
        known = set(inventory.BY_MODULE)
        missing = []
        for rel in _production_files():
            name = _module_name(rel)
            if name not in known:
                missing.append(f"{rel} (as {name})")
        assert not missing, (
            "production modules missing from rpgmaker/inventory.py - add them "
            "with an explicit status:\n  " + "\n  ".join(missing))

    def test_facade_packages_are_inventoried(self):
        """`pkg/__init__.py` maps to the package name; it must be listed."""
        known = set(inventory.BY_MODULE)
        for rel in _production_files():
            if not _is_facade(rel) or rel == "__init__.py":
                continue
            package = rel[: -len("/__init__.py")].replace("/", ".")
            assert package in known, (
                f"package {package} has an __init__.py but no inventory row")

    def test_inventory_has_no_phantom_entries(self):
        """Every inventoried name must correspond to a real file.

        A stale row is worse than a missing one: it makes a deleted module
        look alive.
        """
        phantom = []
        for record in inventory.MODULES:
            if record.module == "pipeline.py":
                rel = "pipeline.py"
            else:
                rel = record.module.replace(".", "/") + ".py"
            if not os.path.exists(os.path.join(REPO_ROOT, rel)):
                alt = record.module.replace(".", "/") + "/__init__.py"
                if not os.path.exists(os.path.join(REPO_ROOT, alt)):
                    phantom.append(f"{record.module} (looked for {rel})")
        assert not phantom, (
            "inventory lists modules that do not exist:\n  "
            + "\n  ".join(phantom))


class TestStatusIsMeaningful:
    @pytest.mark.parametrize("record", inventory.MODULES,
                             ids=lambda r: r.module)
    def test_status_and_kind_are_from_the_vocabulary(self, record):
        assert record.status in inventory.STATUSES, record
        assert record.kind in inventory.KINDS, record

    @pytest.mark.parametrize("record", inventory.MODULES,
                             ids=lambda r: r.module)
    def test_engines_are_known(self, record):
        unknown = [e for e in record.engines if e not in inventory.ENGINES]
        assert not unknown, f"{record.module} declares unknown engine(s) {unknown}"

    @pytest.mark.parametrize(
        "record",
        [r for r in inventory.MODULES if r.status == "superseded"],
        ids=lambda r: r.module)
    def test_superseded_modules_say_what_replaced_them(self, record):
        assert record.replacement, (
            f"{record.module} is superseded but does not name its replacement; without it "
            "nobody can tell whether the successor still exists")

    def test_the_superseded_replacement_names_a_real_target(self):
        """A replacement must resolve, not just be non-empty.

        The archive this rule was written for carried a replacement string
        naming `tests/test_screenshot_docs.py`, a file that never existed.  A
        register that points at nothing reads as documented and is not, so
        every target in a replacement is resolved here - both path shapes
        (`tools/x.py`, `docs/y.md`) and dotted module paths
        (`translation.cli`), because the live rows all use the latter.

        The scan asserts it actually resolved something: a gate whose whole
        rule is "these tokens must exist" is empty the moment the tokens stop
        looking like paths, and passing for that reason is worse than failing.
        """
        unresolved, checked = [], 0
        for record in inventory.MODULES:
            if record.status != "superseded":
                continue
            for token in record.replacement.replace(",", " ").split():
                candidate = token.strip("()[]`;'\"")
                if not candidate:
                    continue
                if "/" in candidate or candidate.endswith(".py"):
                    looked_for = candidate
                elif "." in candidate:
                    looked_for = candidate.replace(".", "/") + ".py"
                else:
                    continue
                checked += 1
                if not os.path.exists(os.path.join(REPO_ROOT, looked_for)):
                    unresolved.append("%s -> %s (%s)"
                                      % (record.module, candidate, looked_for))
        assert checked >= 4, (
            "only %d replacement target(s) were resolved - the parser is too "
            "narrow and this gate has stopped checking anything" % checked)
        assert not unresolved, (
            "a superseded record names a replacement that does not exist:\n  "
            + "\n  ".join(unresolved))


class TestWheelBoundaryIsReal:
    def test_every_wheel_module_declares_a_position_that_needs_it(self):
        """`wheel=True` must be justified by the packaging contract.

        The wheel exists so the three public entry points work: `gt`,
        `gt-tyrano` and `python -m translation.cli`.  A module ships when it is
        part of a shipped package, a CLI surface, or a cross-package import.
        Modules whose declared engine is absent from their own package would
        be a mistake, so those are reported here.
        """
        suspicious = []
        for record in inventory.MODULES:
            if not record.wheel:
                continue
            if record.module.startswith("tools."):
                continue
            if record.kind not in ("core", "cli", "pipeline", "engine",
                                   "shared-lib"):
                suspicious.append(f"{record.module} has kind {record.kind}")
            if record.kind == "maintenance":
                suspicious.append(record.module)
            # `translation.*` is allowed to hold engine-specific modules
            # (`translation.mvkeys` / `translation.bake` are RPG Maker key
            # extraction and write-back); that is an intentional exception,
            # not engine code leaking into core.
            if record.kind == "engine" and (
                    record.module.split(".")[0] not in (
                        "rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity")
                    and not record.module.startswith("translation")):
                suspicious.append(f"{record.module}: engine code outside an engine package")
        assert not suspicious, suspicious

    def test_only_the_expected_tools_modules_are_wheel_bound(self):
        """`tools/` ships for exactly one reason: other packages import it.

        The set below is the complete set of `tools.*` imports found in
        rpgmaker/, kirikiri/, tyrano/, wolfrpg/, unity/ and translation/.
        If this list changes, the packaging decision must be revisited - that
        is the point of the test.

        This list shrank in Phase 3: the kana regexes and the plugins.js
        parser were core all along (`shared-lib`), so they moved into
        `rpgmaker/` as `rpgmaker.japanese` / `rpgmaker.plugins_io` and their
        `tools/` paths became deprecated re-export shims that nothing
        in-repo imports in the same way.
        """
        wheel_tools = sorted(
            r.module for r in inventory.MODULES
            if r.wheel and (r.module == "tools"
                            or r.module.startswith("tools.")))
        assert wheel_tools == [
            "tools",
            "tools.check_iscript_js",
            "tools.qc_ks_kana",
        ], (
            "the set of tools/ modules imported by other packages changed; "
            "update the wheel package list in pyproject.toml and this test "
            "together")

    def test_imported_tools_modules_really_are_imported(self):
        """Verify the wheel-bound set with real AST import edges.

        The `tools` package itself is excluded from the comparison because it
        is the parent of everything found here, not an import target.

        A `from tools import x` edge to a module that only re-exports core is
        NOT a reason to ship it: the shims (`tools.japanese_utils`,
        `tools.plugins_io`) are listed as non-wheel in the inventory and are
        skipped here, so this test still pins the real boundary.
        """
        wanted = {
            r.module.split(".", 1)[1] for r in inventory.MODULES
            if r.wheel and r.module.startswith("tools.")}
        found = set()
        for package in ("rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity",
                        "translation"):
            for rel in _git_ls_files(f"{package}/**/*.py"):
                with open(os.path.join(REPO_ROOT, rel),
                          encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=rel)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ImportFrom):
                        continue
                    module = node.module or ""
                    if module == "tools":
                        for alias in node.names:
                            found.add(alias.name.split(".")[0])
                    elif module.startswith("tools."):
                        found.add(module.split(".", 1)[1])
        assert found == wanted, (
            f"declared wheel-bound tools {sorted(wanted)} != actually imported {sorted(found)}")


class TestCapabilityDeclarations:
    def test_every_engine_has_a_capability_row(self):
        for engine in inventory.ENGINES:
            if engine == "core":
                continue
            assert engine in inventory.ENGINE_CAPABILITIES, engine

    def test_capabilities_are_from_the_vocabulary(self):
        for engine, caps in inventory.ENGINE_CAPABILITIES.items():
            unknown = [c for c in caps if c not in inventory.CAPABILITIES]
            assert not unknown, f"{engine} declares unknown capability {unknown}"

    def test_mobile_build_engines_also_declare_detection_and_verification(self):
        """A build pipeline without detect/verify cannot refuse a bad input."""
        for engine, caps in inventory.ENGINE_CAPABILITIES.items():
            if "build_mobile" not in caps:
                continue
            assert "detect" in caps, engine
            assert "verify" in caps, engine

    def test_translation_only_engines_do_not_claim_a_mobile_build(self):
        """The hard rule: Unity and Wolf RPG never get a JoiPlay build."""
        for engine in ("wolfrpg", "unity"):
            assert not inventory.supports(engine, "build_mobile")
            assert inventory.supports(engine, "extract_text")
            assert inventory.supports(engine, "apply_translation")

    def test_unknown_engine_supports_nothing_rather_than_everything(self):
        """"Fail closed": an unrecognised engine must not silently proceed."""
        assert not inventory.supports("unknown-engine", "build_mobile")
        assert not inventory.supports("", "detect")

    def test_supports_matches_the_table_for_known_engines(self):
        for engine, caps in inventory.ENGINE_CAPABILITIES.items():
            for capability in inventory.CAPABILITIES:
                assert inventory.supports(engine, capability) == (
                    capability in caps), (engine, capability)


class TestLookupHelpers:
    def test_status_of_returns_none_for_unknown_module(self):
        assert inventory.status_of("no.such.module") is None

    def test_status_of_returns_the_declared_status(self):
        assert inventory.status_of("rpgmaker.config") == "active"
        assert inventory.status_of("tools.extract_text") == "superseded"

    def test_wheel_modules_is_a_stable_tuple(self):
        assert isinstance(inventory.WHEEL_MODULES, tuple)
        assert "rpgmaker.cli" in inventory.WHEEL_MODULES
        assert "tools.extract_text" not in inventory.WHEEL_MODULES

    def test_cli_modules_all_have_an_entry_string(self):
        for record in inventory.CLI_MODULES:
            assert record.entry, record
            assert record.status == "active", record
