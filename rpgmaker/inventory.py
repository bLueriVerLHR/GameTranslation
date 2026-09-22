"""Machine-readable inventory of every production module in this repo.

Why this exists
---------------
The repository accumulated three environments' worth of one-off scripts, and
seven packages that grew engine by engine.  Before that can be reorganised,
every module needs an explicit status: is it live, is it a deliberate manual
recovery tool, was it replaced, or is it dead?  Deciding that by reading a
filename is exactly how dead code survives, so the answer lives here and
`tests/test_inventory.py` fails when a module is missing from this table.

The table is deliberately plain data with no imports: `rpgmaker/` (core) must
not import an engine, and a record naming `kirikiri.xp3tool` is a string, not
an import edge.

Fields
------
module      Dotted module path, or a repo-relative `.py` path for files that
            are not importable as a module (root scripts).
status      One of STATUSES below.
kind        Coarse role, used for reporting and for the CLI smoke matrix.
engines     Engine families this module serves, from ENGINES.  `()` for
            engine-agnostic infrastructure.
wheel       Must the module be present in the installed wheel for the public
            entry points (`gt`, `gt-tyrano`, `python -m translation.cli`) to
            work?  True only when something outside the module's own package
            imports it or the package is a public entry point.
entry       Public CLI entry, if any: ``"argv shape"`` as a human-readable
            string, or "" when the module has no CLI.
replacement Set for superseded modules: what replaced them.

Rules
-----
* A module with no importer outside its own package and no live CLI use is
  `DEAD` - unless the docs tell an operator to run it, in which case it is
  `MAINTENANCE`.
* `MAINTENANCE` is a legitimate, permanent status: post-incident data repair
  cannot always be automated, and deleting the tool means the next incident is
  unsolvable.
* Adding a production module without adding it here fails the test suite.
"""

from typing import NamedTuple

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

#: Engine families this toolkit understands.  `core` is engine-agnostic.
ENGINES = (
    "core",
    "rpgmaker",
    "tyrano",
    "kirikiri",
    "wolfrpg",
    "unity",
)

#: Lifecycle status.  See module docstring for the decision rule.
STATUSES = (
    "active",       # used by production code or a live pipeline
    "maintenance",  # deliberate manual/recovery one-off, still wanted
    "superseded",   # replaced in-repo; the replacement is recorded
    "dead",         # no importer, no live CLI user, obsolete
)

#: Coarse role.  Drives the CLI smoke-test matrix.
KINDS = (
    "core",         # shared infrastructure (config, logging, process, ...)
    "engine",       # one engine's pipeline or library code
    "shared-lib",   # importable helper shared by tools and engines
    "cli",          # command surface
    "pipeline",     # engine pipeline entry point
    "maintenance",  # manual operator tool
    "superseded",   # archived
)


class Module(NamedTuple):
    """One row of the inventory."""

    module: str
    status: str
    kind: str
    engines: tuple
    wheel: bool
    entry: str = ""
    replacement: str = ""


# ---------------------------------------------------------------------------
# The inventory
# ---------------------------------------------------------------------------

_RPGMAKER = [
    Module("rpgmaker", "active", "core", (), True, "package"),
    Module("rpgmaker.archive", "active", "core", (), True),
    Module("rpgmaker.assets", "active", "core", (), True),
    Module("rpgmaker.audio", "active", "engine", ("rpgmaker",), True),
    Module("rpgmaker.build", "active", "engine", ("rpgmaker",), True),
    Module("rpgmaker.clean", "active", "engine", (), True),
    Module("rpgmaker.cli", "active", "cli", ("rpgmaker", "tyrano"), True,
           "gt / gt-tyrano / python -m rpgmaker.cli"),
    Module("rpgmaker.cliutil", "active", "core", (), True),
    Module("rpgmaker.compress", "active", "core", (), True),
    Module("rpgmaker.config", "active", "core", (), True,
           # Retired facade: re-exports the split modules for one
           # compatibility cycle so an out-of-tree `from rpgmaker import
           # config` keeps working.  In-repo code imports the owner (pinned
           # by tests/test_config_facade.py), so it ships but has no logic.
           ),
    Module("rpgmaker.constants", "active", "core", (), True),
    Module("rpgmaker.decrypt", "active", "engine", ("rpgmaker",), True),
    Module("rpgmaker.deliver", "active", "core", (), True),
    Module("rpgmaker.deliverables", "active", "core", (), True),
    Module("rpgmaker.detect", "active", "core", (), True),
    Module("rpgmaker.doctor", "active", "cli", (), True,
           "python -m rpgmaker.doctor"),
    Module("rpgmaker.evb", "active", "engine", ("rpgmaker",), True),
    Module("rpgmaker.fontpolicy", "active", "core", (), True),
    Module("rpgmaker.inventory", "active", "core", (), True,
           # The classification table itself.  It had been missing from its
           # own inventory until the pathspec fix in tests/test_inventory.py
           # made `_production_files()` recursive - the scan had been
           # returning only `pipeline.py`, so this gap could not surface.
           ),
    Module("rpgmaker.japanese", "active", "core", (), True),
    Module("rpgmaker.jssyntax", "active", "core", (), True),
    Module("rpgmaker.io_boundary", "active", "core", (), True),
    Module("rpgmaker.logsetup", "active", "core", (), True),
    Module("rpgmaker.media", "active", "core", (), True),
    Module("rpgmaker.platform", "active", "core", (), True),
    Module("rpgmaker.plugins_io", "active", "core", (), True),
    Module("rpgmaker.plugincompat", "active", "engine", ("rpgmaker",), True),
    Module("rpgmaker.proctools", "active", "core", (), True),
    Module("rpgmaker.runtime", "active", "core", (), True),
    Module("rpgmaker.serve", "active", "core", (), True),
    Module("rpgmaker.settings", "active", "core", (), True),
    Module("rpgmaker.textencoding", "active", "core", (), True),
    Module("rpgmaker.tool_registry", "active", "core", (), True),
    Module("rpgmaker.verify", "active", "engine", ("rpgmaker",), True),
    Module("rpgmaker.workspace", "active", "core", (), True),
]

_KIRIKIRI = [
    Module("kirikiri", "active", "engine", ("kirikiri",), True, "package"),
    Module("kirikiri.convert_kag", "active", "pipeline", ("kirikiri",), True,
           "python -m kirikiri.convert_kag"),
    Module("kirikiri.kag", "active", "engine", ("kirikiri",), True,
           "package"),
    Module("kirikiri.kag.assets", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.kag.cli", "active", "cli", ("kirikiri",), True,
           "python -m kirikiri.kag.cli"),
    Module("kirikiri.kag.fonts", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.kag.project", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.kag.scenario", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.kag.shims", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.kag.tags", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.ks_extract", "active", "shared-lib", ("kirikiri",), True),
    Module("kirikiri.merge_font", "maintenance", "maintenance", (), False,
           "python -m kirikiri.merge_font",
           # Font merging is per-game and driven by local font data; nothing
           # imports it, so it stays out of the wheel.
           ),
    Module("kirikiri.pipeline", "active", "pipeline", ("kirikiri",), True,
           "python -m kirikiri.pipeline"),
    Module("kirikiri.tjs2js", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.tlg", "active", "engine", ("kirikiri",), True),
    Module("kirikiri.xp3pack", "active", "engine", ("kirikiri",), True,
           "python -m kirikiri.xp3pack"),
    Module("kirikiri.xp3tool", "active", "engine", ("kirikiri",), True,
           "python -m kirikiri.xp3tool"),
]

_TYRANO = [
    Module("tyrano", "active", "engine", ("tyrano",), True, "package"),
    Module("tyrano.asar", "active", "engine", ("tyrano",), True,
           "python -m tyrano.asar"),
    Module("tyrano.audio", "active", "engine", ("tyrano",), True),
    Module("tyrano.autoplay", "active", "engine", ("tyrano",), True),
    Module("tyrano.build", "active", "engine", ("tyrano",), True),
    Module("tyrano.clean", "active", "engine", ("tyrano",), True),
    Module("tyrano.pipeline", "active", "pipeline", ("tyrano",), True,
           "gt-tyrano / python -m tyrano.pipeline"),
    Module("tyrano.tyrano_extract", "active", "shared-lib", ("tyrano",), True),
    Module("tyrano.ui_lang", "active", "engine", ("tyrano",), True),
    Module("tyrano.verify", "active", "engine", ("tyrano",), True),
]

_WOLF = [
    Module("wolfrpg", "active", "engine", ("wolfrpg",), True, "package"),
    Module("wolfrpg.dxarchive", "active", "engine", ("wolfrpg",), True,
           "python -m wolfrpg.dxarchive"),
]

_UNITY = [
    Module("unity", "active", "engine", ("unity",), True, "package"),
    Module("unity.rmunite", "active", "engine", ("unity",), True, "package"),
    Module("unity.rmunite.extract_game", "active", "engine", ("unity",), True,
           "python -m unity.rmunite.extract_game"),
    Module("unity.rmunite.prefill", "active", "engine", ("unity",), True,
           "python -m unity.rmunite.prefill"),
]

_TRANSLATION = [
    Module("translation", "active", "core", (), True, "package"),
    Module("translation.bake", "active", "engine", (), True),
    Module("translation.cli", "active", "cli", (), True,
           "python -m translation.cli"),
    Module("translation.codes", "active", "core", (), True),
    Module("translation.mvkeys", "active", "engine", ("rpgmaker",), True),
    Module("translation.prefill", "active", "core", (), True),
    Module("translation.rawlib", "active", "core", (), True),
    Module("translation.workspace", "active", "core", (), True),
]

# Tools imported from OUTSIDE tools/ (the only reason tools/ needs to ship).
# Verified by tests/test_inventory.py against real AST import edges.
_TOOLS_SHARED = [
    Module("tools", "active", "shared-lib", (), True, "package"),
    Module("tools.japanese_utils", "active", "shared-lib", (), False,
           "",
           # Deprecated re-export of rpgmaker.japanese, kept for one
           # compatibility cycle so an out-of-tree `import japanese_utils`
           # still resolves.  Nothing in-repo imports it any more, so it is
           # not wheel-bound.
           ),
    Module("tools.plugins_io", "active", "shared-lib", (), False,
           "",
           # Deprecated re-export of rpgmaker.plugins_io (same reason).
           ),
    Module("tools.qc_ks_kana", "active", "shared-lib", ("kirikiri",), True,
           "python -m tools.qc_ks_kana"),
    Module("tools.check_iscript_js", "active", "shared-lib", ("kirikiri",), True,
           "python -m tools.check_iscript_js"),
]

# Tools only ever run as scripts by an operator.  Not needed in the wheel.
_TOOLS_MAINTENANCE = [
    Module("tools.apply_ks_translation", "active", "maintenance",
           ("kirikiri",), False, "python -m tools.apply_ks_translation"),
    Module("tools.apply_translation_to_patch", "active", "maintenance",
           ("kirikiri",), False, "python -m tools.apply_translation_to_patch"),
    Module("tools.apply_tyrano_translation", "active", "maintenance",
           ("tyrano",), False, "python -m tools.apply_tyrano_translation"),
    Module("tools.audit_prefilled", "active", "maintenance", (), False,
           "python -m tools.audit_prefilled"),
    Module("tools.augment_adv_resources", "active", "maintenance", (), False,
           "python -m tools.augment_adv_resources"),
    Module("tools.bake_csv_translation", "active", "maintenance", (), False,
           "python -m tools.bake_csv_translation"),
    Module("tools.bake_translation", "active", "maintenance", ("rpgmaker",),
           False, "python -m tools.bake_translation"),
    Module("tools.bake_with_name_prefix", "active", "maintenance", (), False,
           "python -m tools.bake_with_name_prefix"),
    Module("tools.batch_decode_tlg", "active", "maintenance", ("kirikiri",),
           False, "python -m tools.batch_decode_tlg"),
    Module("tools.build_csv_template", "active", "maintenance", (), False,
           "python -m tools.build_csv_template"),
    Module("tools.build_ks_translation", "active", "maintenance", ("kirikiri",),
           False, "python -m tools.build_ks_translation"),
    Module("tools.build_translation", "active", "maintenance", ("rpgmaker",),
           False, "python -m tools.build_translation"),
    Module("tools.build_tyrano_translation", "active", "maintenance",
           ("tyrano",), False, "python -m tools.build_tyrano_translation"),
    Module("tools.build_wolf_translation", "active", "maintenance",
           ("wolfrpg",), False, "python -m tools.build_wolf_translation"),
    Module("tools.check_all", "active", "maintenance", (), False,
           "python tools/check_all.py"),
    Module("tools.check_docs", "active", "maintenance", (), False,
           "python -m tools.check_docs"),
    Module("tools.check_coverage", "active", "maintenance", (), False,
           "python tools/check_coverage.py coverage.json"),
    Module("tools.mypy_check", "active", "maintenance", (), False,
           "python tools/mypy_check.py"),
    Module("tools.check_tyrano_build", "active", "maintenance", ("tyrano",),
           False, "python -m tools.check_tyrano_build"),
    Module("tools.clean_kana_ticks", "active", "maintenance", (), False,
           "python -m tools.clean_kana_ticks"),
    Module("tools.downscale_images", "active", "maintenance", (), False,
           "python -m tools.downscale_images"),
    Module("tools.extract_remaining_text", "active", "maintenance",
           ("rpgmaker",), False, "python -m tools.extract_remaining_text"),
    Module("tools.extract_rvdata2", "active", "maintenance", ("rpgmaker",),
           False, "python -m tools.extract_rvdata2"),
    Module("tools.final_qc", "active", "maintenance", (), False,
           "python -m tools.final_qc"),
    Module("tools.fit_texture_4096", "active", "maintenance", (), False,
           "python -m tools.fit_texture_4096"),
    Module("tools.fix_mojibake_names", "active", "maintenance", (), False,
           "python -m tools.fix_mojibake_names"),
    Module("tools.gen_completion_shards", "active", "maintenance", (), False,
           "python -m tools.gen_completion_shards"),
    Module("tools.gen_translation_shards", "active", "maintenance", (), False,
           "python -m tools.gen_translation_shards"),
    Module("tools.harvest_translation", "active", "maintenance", (), False,
           "python -m tools.harvest_translation"),
    Module("tools.merge_plain_chunks", "active", "maintenance", (), False,
           "python -m tools.merge_plain_chunks"),
    Module("tools.merge_translation", "active", "maintenance", (), False,
           "python -m tools.merge_translation"),
    Module("tools.mutation_check", "active", "maintenance", (), False,
           "python tools/mutation_check.py"),
    Module("tools.plugin_json_leaves", "active", "maintenance", ("rpgmaker",),
           False, "python -m tools.plugin_json_leaves"),
    Module("tools.qc_build_kana", "active", "maintenance", (), False,
           "python -m tools.qc_build_kana"),
    Module("tools.qc_translation_chunks", "active", "maintenance", (), False,
           "python -m tools.qc_translation_chunks"),
    Module("tools.resolve_text_keys", "active", "maintenance", ("rpgmaker",),
           False, "python -m tools.resolve_text_keys"),
    Module("tools.skip_report", "active", "maintenance", (), False,
           "python tools/skip_report.py"),
    Module("tools.transcode_video", "active", "maintenance", (), False,
           "python -m tools.transcode_video"),
    Module("tools.unlock_gallery", "active", "maintenance", ("rpgmaker",),
           False, "python -m tools.unlock_gallery"),
    # Post-incident data repair: a corrupted dictionary or line-ending damage
    # cannot be re-derived, so these stay even though nothing imports them.
    Module("tools.fix_dbl_nl", "maintenance", "maintenance", (), False,
           "python -m tools.fix_dbl_nl"),
    Module("tools.fix_key_prefix", "maintenance", "maintenance", (), False,
           "python -m tools.fix_key_prefix"),
    Module("tools.fix_literal_nl", "maintenance", "maintenance", (), False,
           "python -m tools.fix_literal_nl"),
    Module("tools.patch_names", "maintenance", "maintenance", (), False,
           "python -m tools.patch_names"),
]

# Retired by translation v2 (single-writer file mailbox + five gates).  The
# v1 flow (slice -> one agent per chunk -> merge ja/zh) is gone; only engines
# that still use a line-based import/apply chain keep their own tools.
_TOOLS_SUPERSEDED = [
    Module("tools.ctrl_codes", "active", "shared-lib", (), False),
    Module("tools.extract_text", "superseded", "superseded", ("rpgmaker",),
           False, replacement="translation.cli prepare"),
    Module("tools.plain_io", "active", "shared-lib", ("rpgmaker",), False),
    Module("tools.plain_to_translated", "superseded", "superseded", (), False,
           replacement="translation.cli bake"),
    Module("tools.rpgmaker_common", "active", "shared-lib", ("rpgmaker",),
           False),
    Module("tools.rpgmaker_constants", "active", "shared-lib", ("rpgmaker",),
           False),
    Module("tools.rvdata2_io", "active", "shared-lib", ("rpgmaker",), False),
    Module("tools.scenario_common", "active", "shared-lib", (), False),
    Module("tools.translate_rpgmaker", "superseded", "superseded",
           ("rpgmaker",), False, replacement="translation.cli prepare"),
    Module("tools.gen_csv_shards", "superseded", "superseded", (), False,
           replacement="translation.cli slice"),
]

_ROOT = [
    Module("pipeline.py", "active", "pipeline", ("rpgmaker",), False,
           "python pipeline.py"),
]

#: Every production module, in reporting order.
MODULES = tuple(
    _RPGMAKER + _KIRIKIRI + _TYRANO + _WOLF + _UNITY + _TRANSLATION
    + _TOOLS_SHARED + _TOOLS_MAINTENANCE + _TOOLS_SUPERSEDED + _ROOT)

#: Module names must be unique - a duplicate row silently shadows a status.
_names = [m.module for m in MODULES]
if len(set(_names)) != len(_names):
    raise ValueError(
        f"duplicate module in the inventory: {sorted({n for n in _names if _names.count(n) > 1})}")

# ---------------------------------------------------------------------------
# Engine capabilities
# ---------------------------------------------------------------------------

#: Every capability a pipeline step can provide.  An engine that lacks one
#: must report that explicitly rather than silently doing nothing.
CAPABILITIES = ("detect", "unpack", "adpack", "decrypt", "extract_text",
                "apply_translation", "audio", "verify", "build_mobile",
                "serve", "package", "inject")

#: Which capabilities each engine declares.  `detect` is universal: an unknown
#: engine is a detection result, not a failure to detect.
#:
#: Unity and Wolf RPG deliberately have no build_mobile: they are translated
#: in place and never run through a JoiPlay pipeline.
ENGINE_CAPABILITIES = {
    "rpgmaker": ("detect", "adpack", "decrypt", "extract_text",
                 "apply_translation", "audio", "verify", "build_mobile",
                 "serve", "package"),
    "tyrano": ("detect", "unpack", "extract_text", "apply_translation",
               "audio", "verify", "build_mobile", "serve", "package"),
    "kirikiri": ("detect", "unpack", "extract_text", "apply_translation",
                 "audio", "verify", "build_mobile", "serve", "package",
                 "inject"),
    "wolfrpg": ("detect", "unpack", "extract_text", "apply_translation"),
    "unity": ("detect", "unpack", "extract_text", "apply_translation",
              "inject"),
}


def supports(engine, capability):
    """True when `engine` declares `capability`.

    Callers use this to report an unsupported step explicitly.  An engine with
    no entry at all supports nothing.
    """
    return capability in ENGINE_CAPABILITIES.get(engine, ())


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

BY_MODULE = {m.module: m for m in MODULES}

#: Modules that must ship in the wheel, in install order.
WHEEL_MODULES = tuple(m.module for m in MODULES if m.wheel)

#: Modules with a command-line surface, for the CLI smoke matrix.
CLI_MODULES = tuple(m for m in MODULES if m.entry and m.status == "active")


def status_of(module):
    """Return the status of `module`, or None when it is not inventoried."""
    rec = BY_MODULE.get(module)
    return rec.status if rec else None
