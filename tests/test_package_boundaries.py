"""Package boundaries must hold - the arrow may not point back the wrong way.

Phase 3 of PLAN.md is "package boundaries + unified `gt`", and PLAN.md §7
forbids "core importing concrete engines".  Nothing enforced that before this
file: the boundary was a convention, so the one real violation
(`rpgmaker/plugincompat.py` doing `from tools import plugins_io`) survived
unnoticed until an ad-hoc scan found it.

The rules, each with the reason it exists:

1. Only engine packages may import `tools.*`, and only for the handful of
   genuinely shared libraries inventoried as `shared-lib`.  `tools/` is the
   maintenance directory; nothing in the shipped core may depend on it.
2. No package may import an engine package other than its own (or the
   assembly-layer CLI that wires engines together on purpose).
3. A core module must be importable without the package's own name being on
   `sys.path` - i.e. the sibling `sys.path` hacks that used to live in
   `kirikiri/ks_extract.py` and `tyrano/tyrano_extract.py` must not come back.

Core 1 vs core 2 (the exact set) is decided by `rpgmaker/inventory.py`, so the
gate follows the inventory instead of keeping a second list that would drift.
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

#: Directories that hold products.  `tests/` is not a product.
PACKAGES = ("rpgmaker", "kirikiri", "tyrano", "wolfrpg", "unity", "translation",
            "tools")

ENGINE_PACKAGES = ("rpgmaker", "tyrano", "kirikiri", "wolfrpg", "unity")

#: Other engine packages may compare against these; `rpgmaker` is excluded
#: because it is also the shared core (`config`, `cliutil`, `config`,
#: `media`, `proctools`), so "tyrano imports rpgmaker" is the intended
#: direction and not a cross-engine dependency.
FOREIGN_ENGINE_PACKAGES = ("tyrano", "kirikiri", "wolfrpg", "unity")

#: Modules that are still launched as *scripts* by hand rather than through
#: their package.  Each declares `python -m <package>.<module>` as its
#: inventory entry, but the package root is not importable in that form yet
#: (`kirikiri/` and `unity/rmunite/` have no installed parent on `sys.path`
#: when the script is run from inside the directory).  Removing their
#: preamble needs the entry to change with it, which is a later phase; the
#: exemption is listed here so it stays visible instead of being ignored.
SCRIPT_FORM_ENTRIES = {
    "kirikiri.merge_font": "kirikiri/merge_font.py",
    "kirikiri.pipeline": "kirikiri/pipeline.py",
    "tyrano.pipeline": "tyrano/pipeline.py",
    "unity.rmunite.extract_game": "unity/rmunite/extract_game.py",
    "unity.rmunite.prefill": "unity/rmunite/prefill.py",
    "wolfrpg.dxarchive": "wolfrpg/dxarchive.py",
}

#: `from tools import <name>` edges that are legitimate: the engine libraries
#: that really are shared (inventoried `shared-lib`) plus `tools/` importing
#: its own siblings.  Anything else is the violation rule 1 prevents.
TOOLS_IMPORTS_ALLOWED = {
    # kirikiri engine libraries that live under tools/ for historical
    # reasons: the script checker and the kana QC pass.  `kirikiri.pipeline`
    # imports them lazily inside `convert_game`.
    "kirikiri.pipeline": {"check_iscript_js", "qc_ks_kana"},
}

#: A bare `from tools import x` contributes the sentinel below for `tools`
#: itself; that is the package, not a module inside it, so it is always fine.
TOOLS_PACKAGE_SENTINEL = "__package__"

#: Cross-engine imports that are the assembly layer doing its job: the single
#: top-level CLI is allowed to wire engines together (PLAN Phase 3 task 7).
CROSS_ENGINE_ALLOWED = {
    "rpgmaker.cli": {"tyrano"},
}

#: `import` of another package's *private* module is never fine, allowlist or
#: not, unless the target is a documented entry point.
ASSEMBLY_ENTRY_POINTS = {"rpgmaker.cli"}

#: A module the inventory calls `core`/`shared-lib` must not import an engine
#: *within its own package* either: that is the same wrong-direction edge,
#: just hidden inside one directory.  `rpgmaker/verify.py` was classified
#: `core` while doing `from . import audio` / `from . import plugincompat`,
#: and it verifies RPG Maker-specific artefacts (`System.json`, `rpg_core.js`)
#: - so the classification was what was wrong, not the import.  Fixing the
#: inventory is the right repair because `ENGINE_CAPABILITIES` is derived from
#: it, and a "core" module must stay engine-neutral by definition.
CORE_KINDS = ("core", "shared-lib")

#: One package is exempt from the rule above, and the reason is recorded in
#: `tests/test_inventory.py` too ("`translation.*` is allowed to hold
#: engine-specific modules"): `translation.mvkeys` is RPG Maker key
#: extraction and `translation.bake` is its write-back, so the MZ/MV
#: translation flow is engine code that lives in the translation package on
#: purpose.  Its core helpers (`prefill`, `rawlib`, `workspace`) read the same
#: `keys.jsonl` through `mvkeys.load_keys`, which is the key-table contract,
#: not a dependency on RPG Maker.  Splitting `mvkeys` out would be a larger
#: refactor with its own ADR, so the exemption is explicit rather than
#: silent.
CORE_ENGINE_EXEMPT_PACKAGES = ("translation",)


def _git_ls_files(pattern):
    """Files git knows about matching a pathspec, including untracked ones.

    `--others --exclude-standard` keeps this honest for a brand-new module: a
    plain `git ls-files` would not see it until it was committed, so a
    boundary violation introduced by an uncommitted file would slip through
    the very gate meant to catch it.  Gitignored paths stay excluded.
    """
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         ":(glob)" + pattern],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True).stdout
    return [line for line in out.splitlines() if line]


def _module_name(rel):
    if rel.endswith("/__init__.py"):
        return rel[: -len("/__init__.py")].replace("/", ".")
    return rel[:-3].replace("/", ".")


def _imports(tree, source_module):
    """Yield ``(target_module, lineno)`` for every import in `tree`.

    Relative imports are resolved against `source_module` so
    `from . import audio` in `rpgmaker/verify.py` is reported as
    `rpgmaker.audio`, not as `.audio`.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parts = source_module.split(".")
                base = ".".join(parts[: len(parts) - node.level])
                prefix = (f"{base}.{node.module}") if node.module else base
            else:
                prefix = node.module or ""
            if not prefix:
                continue
            yield prefix, node.lineno
            for alias in node.names:
                yield f"{prefix}.{alias.name}", node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno


def _production_modules():
    """Every production module git knows about except `__init__` facades.

    Includes untracked files (`--others --exclude-standard`) so a boundary
    violation in a brand-new module is caught before it is committed rather
    than after.  Gitignored paths stay out.
    """
    found = 0
    for rel in _git_ls_files("**/*.py"):
        top = rel.split("/")[0]
        if top not in PACKAGES or os.path.basename(rel) == "__init__.py":
            continue
        found += 1
        yield rel, _module_name(rel)
    # A wrong pathspec once made a scan like this return almost nothing, so
    # every gate built on it passed for the wrong reason (see tests/
    # test_inventory.py `_git_ls_files`).  Failing loudly beats a silent pass.
    assert found > 50, "the production scan found only %d modules" % found


class TestCoreDoesNotDependOnTools:
    def test_only_allowed_packages_import_tools(self):
        """`tools/` is maintenance; the shipped core must not need it.

        This is the rule whose violation was found by hand: a core module
        doing `from tools import plugins_io` meant the wheel silently needed
        the whole maintenance directory.  The parser now lives in
        `rpgmaker/plugins_io.py` and `tools/plugins_io.py` is a shim.
        """
        offenders = []
        for rel, module in _production_modules():
            package = rel.split("/")[0]
            if package == "tools":
                continue        # tools/ may import its own siblings
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            allowed = TOOLS_IMPORTS_ALLOWED.get(module, set()) | {
                TOOLS_PACKAGE_SENTINEL}
            for target, line in _imports(tree, module):
                names = _tools_names(target)
                offenders.extend("%s:%d imports tools.%s" % (rel, line, name)
                                 for name in names if name not in allowed)
        assert not offenders, (
            "code outside tools/ imports the maintenance directory:\n  "
            + "\n  ".join(sorted(set(offenders)))
            + "\nMove the library into the package that uses it, or add it to "
              "TOOLS_IMPORTS_ALLOWED with a reason.")

    def test_the_allowlist_does_not_rot(self):
        """Every allowlist entry must still correspond to a real import.

        An allowlist nobody prunes is how a boundary quietly disappears.
        """
        found = {}
        for rel, module in _production_modules():
            if module not in TOOLS_IMPORTS_ALLOWED:
                continue
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            for target, _line in _imports(tree, module):
                found.setdefault(module, set()).update(_tools_names(target))
        for module, allowed in TOOLS_IMPORTS_ALLOWED.items():
            assert found.get(module), (
                f"{module} is allowlisted to import tools/ but imports none; drop the "
                "entry")
            stale = allowed - found.get(module, set())
            assert not stale, (
                f"{module} no longer imports {sorted(stale)}; drop the allowlist entry")


def _mutates_sys_path(tree):
    """True if `tree` contains `sys.path.append/insert/extend(...)`."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute):
            continue
        value = fn.value
        if not isinstance(value, ast.Attribute):
            continue
        if (value.attr == "path" and isinstance(value.value, ast.Name)
                and value.value.id == "sys"
                and fn.attr in ("append", "insert", "extend")):
            return node.lineno
    return None


def _tools_names(target):
    """The `tools.X` names an import target refers to (possibly none)."""
    if target.startswith("tools."):
        return {target[len("tools."):].split(".")[0]}
    if target == "tools":
        return {TOOLS_PACKAGE_SENTINEL}
    return set()


class TestEnginesDoNotImportEachOther:
    def test_no_engine_imports_a_different_engine(self):
        """A package may not reach into another engine's code.

        Today the only cross-engine import is `rpgmaker/cli.py` reaching for
        the Tyrano CLI, which is the assembly layer doing exactly what PLAN
        Phase 3 task 7 wants ("the top-level CLI assembles engines").  Any
        other edge would mean two engines are entangled and neither can be
        moved or retired independently.
        """
        offenders = []
        for rel, module in _production_modules():
            package = rel.split("/")[0]
            if package not in FOREIGN_ENGINE_PACKAGES:
                continue
            allowed = CROSS_ENGINE_ALLOWED.get(module, set())
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            for target, line in _imports(tree, module):
                other = target.split(".")[0]
                if (other in FOREIGN_ENGINE_PACKAGES and other != package
                        and other not in allowed):
                    offenders.append("%s:%d imports %s" % (rel, line, target))
        assert not offenders, (
            "one engine imports another:\n  " + "\n  ".join(sorted(set(offenders)))
            + "\nEngines may import `rpgmaker` core, never each other; if the "
              "edge is the assembly layer, add it to CROSS_ENGINE_ALLOWED.")

    def test_the_cross_engine_allowlist_is_only_the_cli(self):
        """Naming the assembly layer once, so the allowlist cannot grow silently."""
        assert set(CROSS_ENGINE_ALLOWED) <= ASSEMBLY_ENTRY_POINTS, (
            "only the assembly-layer entry points may import another engine; "
            f"got {sorted(CROSS_ENGINE_ALLOWED)}")

    def test_engines_may_import_core(self):
        """The allowed direction must stay open - otherwise the rule is useless.

        Every engine importing a core module (`rpgmaker.platform`,
        `rpgmaker.config`, `rpgmaker.cliutil`) is the intended design (shared
        tool resolution, shared logging), so assert at least one such edge
        still exists; a "no engine imports rpgmaker" rule would be a
        different, much worse architecture.
        """
        users = set()
        for rel, module in _production_modules():
            if rel.split("/")[0] == "rpgmaker":
                continue
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            for target, _line in _imports(tree, module):
                if target.startswith("rpgmaker."):
                    users.add(rel.split("/")[0])
        assert users, "no engine imports rpgmaker core any more - check the scan"


class TestNoReverseImportsOfTyrano:
    def test_no_module_needs_a_sys_path_hack_to_import_its_package(self):
        """Task 4 of Phase 3: no `sys.path` surgery for package-internal imports.

        `kirikiri/ks_extract.py` and `tyrano/tyrano_extract.py` used to insert
        `<repo>/tools` and then try both `import japanese_utils` and
        `from tools import japanese_utils` to paper over it.  Both now import
        `rpgmaker.japanese` directly, and this test is what stops the pattern
        returning.

        Only the packages are checked: the `tools/` maintenance scripts still
        carry their own preambles so they can run from their directory, and
        normalising those is a later phase.
        """
        checked = 0
        problems = []
        for rel, _module in _production_modules():
            top = rel.split("/")[0]
            if top == "tools":
                continue        # deferred; see the docstring
            if rel in SCRIPT_FORM_ENTRIES.values():
                continue        # declared script-form entries, see the set
            checked += 1
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            line = _mutates_sys_path(tree)
            if line:
                problems.append("%s:%d mutates sys.path" % (rel, line))
        assert checked > 20, "the scan checked almost nothing - glob is wrong"
        assert not problems, (
            "production packages must import their siblings normally:\n  "
            + "\n  ".join(problems))


    @pytest.mark.parametrize("module", sorted(SCRIPT_FORM_ENTRIES))
    def test_script_form_exemptions_are_real_script_entries(self, module):
        """The sys.path exemption must correspond to a real `-m` entry.

        Exempting a module whose package is already importable would hide a
        violation, so require two things: the module exists in the inventory
        as a live entry, and the file still really carries the preamble.
        """
        rel = SCRIPT_FORM_ENTRIES[module]
        record = inventory.BY_MODULE.get(module)
        assert record is not None, f"{module} is not inventoried"
        assert record.status in ("active", "maintenance"), (
            f"{module} is {record.status}; dead code does not need a sys.path exemption")
        assert os.path.exists(os.path.join(REPO_ROOT, rel)), rel
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
            source = fh.read()
        assert "sys.path.append" in source or "sys.path.insert" in source, (
            f"{rel} no longer mutates sys.path; drop it from SCRIPT_FORM_ENTRIES")

    def test_every_sys_path_mutator_is_either_fixed_or_declared(self):
        """No production module may mutate `sys.path` unnoticed.

        The two legitimate groups are the `tools/` maintenance scripts
        (deferred) and `SCRIPT_FORM_ENTRIES`.  Anything else means a new
        preamble appeared without being reasoned about.
        """
        offenders = []
        for rel, _module in _production_modules():
            top = rel.split("/")[0]
            if top == "tools" or rel in SCRIPT_FORM_ENTRIES.values():
                continue
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            if _mutates_sys_path(tree):
                offenders.append(rel)
        assert not offenders, (
            "production modules mutate sys.path without being declared:\n  "
            + "\n  ".join(offenders))


class TestCoreStaysEngineNeutral:
    def test_no_core_module_imports_an_engine_module(self):
        """`core` means engine-neutral; imports must agree with the label.

        Without this the inventory can drift: a module gets called `core` for
        historical reasons and quietly starts depending on one engine, and
        then every engine is forced to ship that engine's dependencies.
        """
        kinds = {m.module: m.kind for m in inventory.MODULES}
        engines = {m.module: m.engines for m in inventory.MODULES}
        offenders = []
        for rel, module in _production_modules():
            if kinds.get(module) not in CORE_KINDS:
                continue
            if rel.split("/")[0] in CORE_ENGINE_EXEMPT_PACKAGES:
                continue        # documented exception, see the constant
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            for target, line in _imports(tree, module):
                if kinds.get(target) != "engine":
                    continue
                if not engines.get(target):
                    continue        # engine-neutral engine-kind module
                offenders.append(
                    "%s:%d (%s) imports %s (%s)"
                    % (rel, line, kinds.get(module), target,
                       ",".join(engines.get(target, ()))))
        assert not offenders, (
            "core modules depend on one engine - either move the import or "
            "correct the kind in rpgmaker/inventory.py:\n  "
            + "\n  ".join(sorted(set(offenders))))

    def test_the_exemption_is_still_justified(self):
        """An exemption with nothing to exempt is a hole, not a decision.

        If `translation` ever stops importing its engine module, the
        exemption must go with it - otherwise a future violation inside that
        package would pass unnoticed.
        """
        kinds = {m.module: m.kind for m in inventory.MODULES}
        engines = {m.module: m.engines for m in inventory.MODULES}
        seen = set()
        for rel, module in _production_modules():
            package = rel.split("/")[0]
            if package not in CORE_ENGINE_EXEMPT_PACKAGES:
                continue
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
            for target, _line in _imports(tree, module):
                if (kinds.get(module) in CORE_KINDS
                        and kinds.get(target) == "engine"
                        and engines.get(target)):
                    seen.add(package)
        assert seen == set(CORE_ENGINE_EXEMPT_PACKAGES), (
            f"stale exemption: {sorted(set(CORE_ENGINE_EXEMPT_PACKAGES) - seen)}")


class TestTheInventoryDescribesTheBoundary:
    def test_every_package_in_the_scan_is_inventoried(self):
        """The gate and the inventory must cover the same tree."""
        known = {m.module.split(".")[0] for m in inventory.MODULES}
        for package in PACKAGES:
            assert package in known, (
                f"{package} is scanned for boundaries but absent from the inventory")

    @pytest.mark.parametrize("module", sorted(TOOLS_IMPORTS_ALLOWED))
    def test_allowlisted_importers_match_the_inventory_kind(self, module):
        """An allowlisted importer must be a real, non-superseded module.

        This keeps the allowlist honest: exempting a retired script would
        hide a boundary violation behind dead code.
        """
        record = inventory.BY_MODULE.get(module)
        assert record is not None, f"{module} is not in the inventory"
        assert record.status in ("active", "maintenance"), (
            f"{module} is {record.status}; an allowlist for dead code hides real violations")
