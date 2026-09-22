#!/usr/bin/env python3
"""config.py - deprecated façade over the split configuration modules.

PLAN Phase 4 split this module, which had grown five unrelated
responsibilities, into one module each:

    platform       platform detection, path domains and cross-system
                   conversion (``PathDomain``/``StorageSide``/``PathRef``)
    constants      RPG Maker build constants (header, bitrates, junk lists)
    settings       the gitignored private-data layout + the machine config
    tool_registry  the external-application table and its resolver
    workspace      where per-game working state lives
    deliverables   where finished builds and archives are written
    assets         which font file a translated build uses

Every public name that used to live here is re-exported below, so an
out-of-tree ``from rpgmaker import config`` keeps working for one
compatibility cycle.  **New code must import the owning module**, and
in-repo code already does.

The private helpers (``_home_dir``, ``_volume_roots``, ``_anchor_paths``,
``_read_font_paths``, ``_deliverable_bases``, ...) are deliberately NOT
re-exported.  ``monkeypatch.setattr(config, "_home_dir", ...)`` used to
redirect the resolver; with the helpers in their own modules that patch would
silently stop having any effect, which is the failure mode this whole
refactor is meant to remove.  Patch ``rpgmaker.workspace`` /
``rpgmaker.tool_registry`` / ``rpgmaker.deliverables`` / ``rpgmaker.assets``
instead - an unimplemented patch now raises ``AttributeError`` rather than
passing a test that no longer tests anything.
"""
# Re-exported for compatibility.  Grouped by the module that now owns the
# name so a reader can see at a glance where to import it from directly.
from .assets import (  # noqa: F401
    FONTS_DIR,
    discover_font,
    find_cjk_font,
    find_jp_font,
)
from .constants import (  # noqa: F401
    IMG_JUNK_EXTS,
    MONO_BITRATE_THRESHOLD,
    NWJS_RUNTIME,
    PNG_MAX_DIMENSION,
    REPACK_JUNK_DIRS,
    RPGMV_HEADER,
    STEREO_BITRATE_THRESHOLD,
    WEB_DIRS,
)
from .deliverables import (  # noqa: F401
    archives_dir,
    deliverable_bases,
    games_dir,
    probe_deliverable,
    temp_dir,
    win_temp_dir,
)
from .platform import (  # noqa: F401
    PathDomain,
    PathRef,
    StorageSide,
    domain_of,
    is_windows_side,
    is_wsl,
    localize,
    platform_key,
    posix as _posix,
    side_of,
    to_windows_path,
    to_wsl_path,
    view as _view,
)
from .settings import (  # noqa: F401
    CONFIG_SCHEMA_VERSION,
    KNOWN_SECTIONS,
    LEGACY_PRIVATE_ROOT,
    LOCAL_ENV_FILE,
    PRIVATE_PATHS,
    PRIVATE_ROOT,
    MachineConfig,
    PrivateLocation,
    load_machine_config,
    migration_status,
    private_dir,
    private_path,
)
from .tool_registry import (  # noqa: F401
    POWERSHELL_TIMEOUT,
    TOOLS,
    TOOLS_BY_KEY,
    Tool,
    ToolStatus,
    find_ffmpeg,
    find_git,
    find_node,
    find_powershell,
    probe_report,
    resolve_tool,
    run_powershell,
    win_7z,
)
from .workspace import (  # noqa: F401
    WORKSPACE_DIRNAME,
    WORKSPACE_SCHEMA_VERSION,
    default_workspaces_root,
    resolve_workspace_dir,
    workspace_root,
)

__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "FONTS_DIR",
    "IMG_JUNK_EXTS",
    "KNOWN_SECTIONS",
    "LEGACY_PRIVATE_ROOT",
    "LOCAL_ENV_FILE",
    "MONO_BITRATE_THRESHOLD",
    "NWJS_RUNTIME",
    "PNG_MAX_DIMENSION",
    "POWERSHELL_TIMEOUT",
    "PRIVATE_PATHS",
    "PRIVATE_ROOT",
    "PathDomain",
    "PathRef",
    "PrivateLocation",
    "REPACK_JUNK_DIRS",
    "RPGMV_HEADER",
    "STEREO_BITRATE_THRESHOLD",
    "StorageSide",
    "TOOLS",
    "TOOLS_BY_KEY",
    "Tool",
    "ToolStatus",
    "WEB_DIRS",
    "WORKSPACE_DIRNAME",
    "WORKSPACE_SCHEMA_VERSION",
    "MachineConfig",
    "archives_dir",
    "default_workspaces_root",
    "deliverable_bases",
    "discover_font",
    "domain_of",
    "find_cjk_font",
    "find_ffmpeg",
    "find_git",
    "find_jp_font",
    "find_node",
    "find_powershell",
    "games_dir",
    "is_windows_side",
    "is_wsl",
    "load_machine_config",
    "localize",
    "migration_status",
    "platform_key",
    "private_dir",
    "private_path",
    "probe_deliverable",
    "probe_report",
    "resolve_tool",
    "resolve_workspace_dir",
    "run_powershell",
    "side_of",
    "temp_dir",
    "to_windows_path",
    "to_wsl_path",
    "win_7z",
    "win_temp_dir",
    "workspace_root",
]
