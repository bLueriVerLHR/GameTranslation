#!/usr/bin/env python3
"""The `rpgmaker.config` facade: what it must still provide, and what must
no longer depend on it.

`rpgmaker/config.py` was split into `platform`, `constants`, `settings`,
`tool_registry`, `workspace`, `deliverables` and `assets` (PLAN Phase 4).
The old module is kept as a *deprecation shim* for one compatibility cycle so
an out-of-tree `from rpgmaker import config` keeps working - but nothing in
the repo may import it any more, because a name read through the facade is
not the object the owning module uses (that is exactly how a
`monkeypatch.setattr(config, "_home_dir", ...)` silently stops redirecting
the resolver).

This file is deliberately its own module: deleting it is part of retiring
the facade.
"""
import ast

from rpgmaker import settings

# Names the facade existed to provide.  Anything out of tree may import one
# of these, so removing one is a breaking change that needs a deprecation
# cycle of its own.
EXPECTED_REEXPORTS = {
    # constants
    "IMG_JUNK_EXTS", "MONO_BITRATE_THRESHOLD", "NWJS_RUNTIME",
    "PNG_MAX_DIMENSION", "REPACK_JUNK_DIRS", "RPGMV_HEADER",
    "STEREO_BITRATE_THRESHOLD", "WEB_DIRS",
    # platform
    "PathDomain", "PathRef", "StorageSide", "domain_of", "is_windows_side",
    "is_wsl", "localize", "platform_key", "side_of", "to_windows_path",
    "to_wsl_path",
    # settings
    "CONFIG_SCHEMA_VERSION", "KNOWN_SECTIONS", "LEGACY_PRIVATE_ROOT",
    "LOCAL_ENV_FILE", "PRIVATE_PATHS", "PRIVATE_ROOT", "MachineConfig",
    "PrivateLocation", "load_machine_config", "migration_status",
    "private_dir", "private_path",
    # tool_registry
    "POWERSHELL_TIMEOUT", "TOOLS", "TOOLS_BY_KEY", "Tool", "ToolStatus",
    "find_ffmpeg", "find_git", "find_node", "find_powershell",
    "probe_report", "resolve_tool", "run_powershell", "win_7z",
    # deliverables
    "archives_dir", "deliverable_bases", "games_dir", "probe_deliverable",
    "temp_dir", "win_temp_dir",
    # assets
    "FONTS_DIR", "discover_font", "find_cjk_font", "find_jp_font",
    # workspace
    "WORKSPACE_DIRNAME", "WORKSPACE_SCHEMA_VERSION", "default_workspaces_root",
    "resolve_workspace_dir", "workspace_root",
}

# The core modules the split produced.  They answer "where is X" and must be
# reachable without the facade; a production import of the facade would mean
# the split did not actually happen for that caller.
SPLIT_MODULES = ("platform", "constants", "settings", "tool_registry",
                 "workspace", "deliverables", "assets", "fontpolicy")


def _production_sources():
    """(module name, source) for every production .py file git knows about.

    `--others --exclude-standard` matters: a plain `git ls-files` omits
    untracked files, so a new module importing the retired facade would pass
    this gate until it was committed.  Gitignored paths stay excluded.
    """
    import subprocess

    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "*.py"],
        cwd=settings.REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    for rel in listing.stdout.split():
        rel = rel.replace("\\", "/")
        if rel.startswith("tests/"):
            continue
        yield rel, (settings.REPO_ROOT / rel).read_text(encoding="utf-8")


class TestTheFacadeStillProvides:
    def test_every_documented_name_is_importable(self):
        from rpgmaker import config

        missing = sorted(n for n in EXPECTED_REEXPORTS
                         if not hasattr(config, n))
        assert missing == []

    def test_the_facade_all_lists_the_same_names(self):
        from rpgmaker import config

        assert set(config.__all__) >= EXPECTED_REEXPORTS

    def test_every_reexport_is_the_owning_module_object(self):
        # A re-export that resolved to a *copy* would defeat the point: the
        # facade must hand out the very object the owning module uses.
        from rpgmaker import config, platform, settings as settings_mod
        from rpgmaker import tool_registry

        assert config.private_path is settings_mod.private_path
        assert config.TOOLS is tool_registry.TOOLS
        assert config.is_wsl is platform.is_wsl
        assert config.RPGMV_HEADER == __import__(
            "rpgmaker.constants", fromlist=["x"]).RPGMV_HEADER

    def test_the_facade_defines_no_logic_of_its_own(self):
        # It may own nothing: a function or class defined here would be a
        # second implementation the split was supposed to remove.
        src = (settings.REPO_ROOT / "rpgmaker" / "config.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        defined = [n.name for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        assert defined == []


class TestNothingDependsOnTheFacade:
    def test_no_production_module_imports_the_facade(self):
        offenders = []
        for rel, src in _production_sources():
            if rel == "rpgmaker/config.py":
                continue
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    names = {a.name for a in node.names}
                    if mod == "rpgmaker.config" or (mod == "config" and
                                                    names == {"*"}) or mod == "rpgmaker" and "config" in names or mod == "" and node.level == 1 and "config" in names:
                        offenders.append("%s:%d" % (rel, node.lineno))
                elif isinstance(node, ast.Import):
                    offenders.extend("%s:%d" % (rel, node.lineno)
                                     for alias in node.names
                                     if alias.name in ("rpgmaker.config",))
            if 'from tools import config' in src:
                offenders.append(rel)
        assert offenders == [], (
            "these modules still read names through the deprecated facade; "
            f"import the owning module instead: {offenders}")

    def test_every_split_module_is_reachable_on_its_own(self):
        # No split module may import the facade either, or a fresh import of
        # one of them would pull the whole old surface back in.
        for name in SPLIT_MODULES:
            src = (settings.REPO_ROOT / "rpgmaker" / (name + ".py")).read_text(
                encoding="utf-8")
            assert "import config" not in src, name
            assert "from rpgmaker.config" not in src, name
            assert "from .config" not in src, name


class TestTheSplitModulesExist:
    def test_each_module_owns_its_docstring(self):
        import importlib

        for name in SPLIT_MODULES:
            mod = importlib.import_module(f"rpgmaker.{name}")
            assert mod.__doc__, name
            assert mod.__all__, name

    def test_only_one_module_names_the_physical_private_layout(self):
        # The single-mapping rule that makes the migration an owner action
        # rather than a code change: settings.py is the only file allowed to
        # spell the private directories.
        import re

        pattern = re.compile(r'"\.(private|asset)"|"docs"')
        for name in SPLIT_MODULES:
            if name == "settings":
                continue
            src = (settings.REPO_ROOT / "rpgmaker" / (name + ".py")).read_text(
                encoding="utf-8")
            assert not pattern.search(src), name
