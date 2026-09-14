"""KAG3 (.ks) -> TyranoScript project converter -- compatibility layer.

The implementation moved into the `kirikiri.kag` package (split by concern:
tags / scenario / assets / shims / fonts / project / cli).  This module stays
as the historical import path and as the runnable entry point:

    python kirikiri/convert_kag.py <unpacked> <engine> <out>   # unchanged CLI
    from kirikiri import convert_kag as ck                     # names re-exported

.. deprecated::
   New code should import from `kirikiri.kag` directly.  Everything the old
   module exposed is re-exported here so existing scripts, tests and one-off
   probes (``ck.convert_ks_line``, ``ck.RUNTIME_SHIM_IIFE``, ...) keep working.
"""

# ruff: noqa: F401  -- re-exporting is this module's entire job
from kirikiri.kag.tags import (
    KAG3_TAG_INTENT,
    SHIM_TAG_NAMES,
    SYSTEM_ISCRIPT_DROP,
    TAG_MAP,
    VIDEO_TAGS,
    _DROPPED_TAGS,
    _strip_js_comments,
    collect_scene_tags,
    collect_tag_usage,
    engine_tag_names,
    tag_intent,
)
from kirikiri.kag.shims import (
    FAST_SKIP_SHIM_JS,
    MAP_ENGINE_JS,
    NOOP_PLUS_REAL_JS,
    PORTRAIT_CSS,
    RUNTIME_SHIM_IIFE,
    VIDEO_SHIM_JS,
    WAITSKIP_SHIM_JS,
    _shim_js,
)
from kirikiri.kag.assets import (
    IMAGE_EXTS,
    _ASSET_CACHE,
    _asset_map,
    _asset_map_from_output,
    _asset_map_full,
    _convert_assets,
    _convert_bmp,
    _convert_region_image,
    _convert_tlg,
    _convert_videos,
    _decoder_mtime,
    _find_asset,
    _is_image_asset,
    _is_region_image,
    _layer_map,
    _merge_asset_maps,
    _runtime_asset_maps,
    _up_to_date,
    _video_map_from_output,
)
from kirikiri.kag.scenario import (
    GRAPHIC_ATTR_RE,
    STORAGE_ATTR_RE,
    _balance_if_endif,
    _convert_exp,
    _dangling_call,
    _export_globals,
    _finalize_output_lines,
    _remap_part,
    _replace_layer_image,
    _scan_tags,
    _strip_comment_tail,
    _strip_continuation,
    _tag_spans,
    _wait_to_waitskip,
    convert_ks_line,
    convert_scenario_file,
)
from kirikiri.kag.fonts import (
    _inject_font,
    _inject_portrait,
)
from kirikiri.kag.project import (
    _collect_macros,
    _copy_tree,
    _load_state_overrides,
    _state_overrides_js,
    write_intents,
)
from kirikiri.kag.cli import convert, log, main
from kirikiri.ks_extract import detect_encoding
from kirikiri import tlg, tjs2js

if __name__ == "__main__":
    raise SystemExit(main())
