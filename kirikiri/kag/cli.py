"""KAG3 (.ks) -> TyranoScript project converter.

Converts an extracted KiriKiri/KAG3 game directory (xp3tool extract output)
into a standard TyranoScript project layout that the tyrano/pipeline.py
toolchain can build and serve.

Strategy (validated against TyranoScript V6 engine source):

1. **Macros are kept as-is.** TyranoScript's `[macro name=X]`/`[endmacro]`
   plus `%param` (macro arg with default) / `&expr` (evaluated expression)
   / `*` (pass-through) entity syntax is identical to KAG3, so the game's
   macro definition files (define.ks, name.ks, t_macro.ks, ...) port over
   unchanged.
2. **Tags pass through by name.** Most KAG3 core tags exist in Tyrano with
   the same name and semantics (l/p/r/er/cm/ct/current/image/freeimage/
   layopt/position/backlay/wt/trans/locate/jump/call/return/link/endlink/
   button/s/wait/font/if/elsif/else/endif/eval/macro/endmacro/iscript/
   endscript/emb/playse/stopse/bgmopt/seopt/playbgm/stopbgm/fadeinbgm/
   fadeoutbgm/quake/graph/cursor/title/history...). No rewriting needed.
3. **TJS expressions -> JS.** f./sf./tf. work directly in Tyrano's
   embScript eval() scope. Rewrites needed:
   - attribute values starting with `&` are evaluated expressions in both
     engines, but KAG3 also allows bare `f.xxx` inside exp="..." strings,
     which is already valid JS on the Tyrano side.
   - `[if exp="..."]` / `[eval exp="..."]` / cond="..." expressions are
     evaluated with eval(), so mostly pass through.
4. **Missing KAG3-only tags are shimmed.** Tags Tyrano does not implement
   (laycount, mapdisable, mapaction, rclick, startanchor, disablestore,
   loadplugin, style, resetstyle, hr, wm, ch, hact, select_clear, link2,
   pimage, clickskip, tempsave, tempload, locksnapshot, unlocksnapshot,
   mes_return, ...) are registered as no-op tags via a generated plugin
   js (see _SHIM_JS). This keeps the scenario running instead of hitting
   Tyrano's "undefined_tag" error.
5. **Storage extension completion.** Tyrano defaults to
   defaultStorageExtension=jpg and only appends when the storage value has
   no dot. KAG3 game scripts reference assets without extension
   (storage="black", storage=%bgm). The converter rewrites storage=
   attribute values to the actual file name (with extension) found in the
   unpacked asset tree, so the browser can resolve them.
6. **Encoding.** Input .ks files are detected per-file (UTF-16LE/BE,
   Shift-JIS, UTF-8); output is UTF-8 (TyranoScript standard).

The output layout mirrors TyranoScript's data/ directory:
  data/scenario/*.ks
  data/bgimage/  data/fgimage/  data/image/  data/bgm/  data/sound/
  data/video/  data/system/
plus a standard engine skeleton (index.html + tyrano/) copied from a
TyranoScript engine source tree.

Usage:
    python3 kirikiri/convert_kag.py <unpacked_game> <tyrano_engine> <out_dir>
    (same CLI; the implementation lives in the kirikiri.kag package)
"""

import json
import logging
import os
import re
import shutil
from collections import Counter
from types import SimpleNamespace
from typing import Annotated, List, Optional

import typer

from kirikiri import tjs2js
from kirikiri.kag.assets import (_ASSET_CACHE, _convert_assets, _convert_videos,
                                 _runtime_asset_maps, _video_map_from_output)
from kirikiri.kag.fonts import _inject_font, _inject_portrait
from kirikiri.kag.project import (_collect_macros, _copy_tree,
                                  _load_state_overrides, _state_overrides_js,
                                  write_intents)
from kirikiri.kag.scenario import convert_scenario_file
from kirikiri.kag.shims import FAST_SKIP_SHIM_JS, RUNTIME_SHIM_IIFE, _shim_js
from kirikiri.kag.tags import (_DROPPED_TAGS, SYSTEM_ISCRIPT_DROP,
                               collect_scene_tags, collect_tag_usage)
from rpgmaker import cliutil

log = logging.getLogger(__name__)


def convert(*, unpacked, engine, out_dir, keep_game_buttons=False,
            scenario_dir="scenario", scenario_only=False, fonts=None,
            video_dir=None, fast_skip=False, state_overrides_path=None,
            portrait=False, workers=None):
    """Convert one unpacked KAG3 game into a TyranoScript project.

    Programmatic entry point; the Typer command below is its CLI wrapper.  The
    body is the historical ``main()`` with its argparse namespace replaced by
    these explicit arguments (behaviour unchanged); `workers` is the only new
    knob (image/copy parallelism, None = auto-tuned from the machine).
    """
    args = SimpleNamespace(
        unpacked=unpacked, engine=engine, out_dir=out_dir,
        keep_game_buttons=keep_game_buttons, scenario_dir=scenario_dir,
        scenario_only=scenario_only, font=fonts, video_dir=video_dir,
        fast_skip=fast_skip, state_overrides=state_overrides_path,
        portrait=portrait,
    )

    try:
        state_overrides = _load_state_overrides(args.state_overrides)
    except ValueError as e:
        return cliutil.fail(str(e), 2)

    # Tags dropped for this run (see _DROPPED_TAGS). Must be set before any
    # scenario is converted, not next to the shim build.
    _DROPPED_TAGS.clear()
    if not getattr(args, "keep_game_buttons", False):
        _DROPPED_TAGS.add("button")

    stats = Counter()
    unpacked = args.unpacked.rstrip("/")
    out = args.out_dir.rstrip("/")
    out_data = os.path.join(out, "data")

    # engine skeleton (skipped in scenario-only mode)
    sys_dst = os.path.join(out_data, "system")
    if not args.scenario_only:
        if not os.path.isdir(os.path.join(args.engine, "tyrano")):
            log.error("engine dir missing tyrano/ : %s", args.engine)
            return 1
        _copy_tree(args.engine, out, ignore_exts=())
        # keep engine system files (Config.tjs, KeyConfig.js), drop the rest
        engine_data = os.path.join(args.engine, "data")
        # remove engine sample scenarios copied into the output (scene1.ks
        # etc) - they would be picked up as game files and pollute the game
        out_scen = os.path.join(out, "data", "scenario")
        if os.path.isdir(out_scen):
            shutil.rmtree(out_scen)
        sys_src = os.path.join(engine_data, "system")
        if os.path.isdir(sys_src):
            os.makedirs(sys_dst, exist_ok=True)
            for fn in ("Config.tjs", "KeyConfig.js"):
                sp = os.path.join(sys_src, fn)
                if os.path.isfile(sp):
                    shutil.copy2(sp, os.path.join(sys_dst, fn))

    os.makedirs(out_data, exist_ok=True)

    # macros (informational)
    macros = _collect_macros(unpacked)

    # scenario
    scen_src = os.path.join(unpacked, args.scenario_dir)
    scen_dst = os.path.join(out_data, "scenario")
    if os.path.isdir(scen_src):
        os.makedirs(scen_dst, exist_ok=True)
        for fn in sorted(os.listdir(scen_src)):
            sp = os.path.join(scen_src, fn)
            if not (os.path.isfile(sp) and fn.endswith(".ks")):
                continue
            dp = os.path.join(scen_dst, fn.lower())
            convert_scenario_file(sp, unpacked, dp, macros, stats)
    # root-level .ks (first.ks / 112.ks / newgame.ks ...)
    for fn in sorted(os.listdir(unpacked)):
        if fn.endswith(".ks"):
            sp = os.path.join(unpacked, fn)
            if os.path.isfile(sp):
                dp = os.path.join(scen_dst, fn.lower())
                convert_scenario_file(sp, unpacked, dp, macros, stats)

    # assets
    video_map = {}
    if not args.scenario_only:
        _convert_assets(unpacked, out_data, stats, workers=workers)
        video_map = _convert_videos(unpacked, out_data, args.video_dir, stats)
    else:
        video_map = _video_map_from_output(out_data)
        log.info("scenario-only: assets reused from existing output")

    # game-specific Config.tjs settings (window size from the KAG3 game)
    cfg_path = os.path.join(sys_dst if 'sys_dst' in dir() else os.path.join(out_data, "system"), "Config.tjs")
    if os.path.isfile(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = f.read()
        scw, sch = (768, 1024) if args.portrait else (1024, 768)
        cfg = re.sub(r"(?m)^;?\s*scWidth\s*=.*$", ";scWidth = %d;" % scw, cfg)
        cfg = re.sub(r"(?m)^;?\s*scHeight\s*=.*$", ";scHeight = %d;" % sch, cfg)
        cfg = re.sub(r"(?m)^;?\s*configSave\s*=.*$", ";configSave = webstorage;", cfg)
        cfg = re.sub(r"(?m)^;?\s*numMessageLayers\s*=.*$", ";numMessageLayers = 14;", cfg)
        cfg = re.sub(r"(?m)^;?\s*numCharacterLayers\s*=.*$", ";numCharacterLayers = 12;", cfg)
        # text speed: near-instant so clicks advance dialogue immediately
        # (KAG3 typewriter waits eat clicks; players expect click-to-advance)
        cfg = re.sub(r"(?m)^;?\s*chSpeed\s*=.*$", ";chSpeed = 3;", cfg)
        cfg = re.sub(r"(?m)^;?\s*chSpeeds\.fast\s*=.*$", ";chSpeeds.fast = 1;", cfg)
        cfg = re.sub(r"(?m)^;?\s*chSpeeds\.normal\s*=.*$", ";chSpeeds.normal = 3;", cfg)
        cfg = re.sub(r"(?m)^;?\s*chSpeeds\.slow\s*=.*$", ";chSpeeds.slow = 5;", cfg)
        # skip speed: Tyrano waits config.skipSpeed ms per printed line while
        # skipping (kag.tag.js: after all characters are shown it does
        # setTimeout(nextOrder, skipSpeed)), so it caps skipping at
        # 1000/skipSpeed lines per second. The template's 30 ms caps it at
        # 33 lines/s, which dominates fast-forwarding a build for testing;
        # 1 ms lets the flow run as fast as the browser allows. Only skip mode
        # reads this, so normal reading speed is unaffected.
        cfg = re.sub(r"(?m)^;?\s*skipSpeed\s*=.*$", ";skipSpeed = 1;", cfg)
        if args.portrait:
            # default message window sits in the bottom black area
            # (image area is the top 768x576 of the 768x1024 canvas)
            cfg = re.sub(r"(?m)^;?\s*ml\s*=.*$", ";ml = 0;", cfg)
            cfg = re.sub(r"(?m)^;?\s*mt\s*=.*$", ";mt = 640;", cfg)
            cfg = re.sub(r"(?m)^;?\s*mw\s*=.*$", ";mw = 768;", cfg)
            cfg = re.sub(r"(?m)^;?\s*mh\s*=.*$", ";mh = 384;", cfg)
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(cfg)
        log.info("Config.tjs: scWidth/Height=%dx%d, configSave=webstorage", scw, sch)

    # portrait layout: scale art to the top, message text into the black
    # bottom area (768x1024 canvas; engine CSS + shim [position] remap;
    # idempotent, so it also runs in scenario-only mode)
    if args.portrait:
        _inject_portrait(out, log)

    # unified CJK font (project convention, parameterized --font)
    if args.font:
        for f in args.font:
            if os.path.isfile(f):
                _inject_font(out, f, "Glow Sans SC", log)
            else:
                log.warning("font file not found: %s", f)

    # shim plugin
    plugin_dir = os.path.join(out, "tyrano", "plugins", "kag")
    if not os.path.isdir(plugin_dir):
        plugin_dir = os.path.join(out, "tyrano", "plugins")
        os.makedirs(plugin_dir, exist_ok=True)
    # asset name maps for the runtime storage resolver (extensionless KAG3
    # storages) and the clickable-map engine (.ma files, _p region images).
    amap, full_map = _runtime_asset_maps(unpacked, out_data, args.scenario_only)
    _ASSET_CACHE[unpacked] = (amap, full_map)
    ma_map = {k.rsplit(".", 1)[0]: v for k, v in full_map.items() if k.endswith(".ma")}
    runtime_assets = dict(amap)
    runtime_assets.update(full_map)
    asset_js = "window.__kag3_assets = " + json.dumps(runtime_assets, ensure_ascii=False) + ";\n"
    asset_ma_js = "window.__kag3_assets_ma = " + json.dumps(ma_map, ensure_ascii=False) + ";\n"
    # name -> converted movie, for the KAG3 video shim ([openvideo storage=X])
    asset_video_js = "window.__kag3_videos = " + json.dumps(
        video_map, ensure_ascii=False) + ";\n"
    tag_usage = collect_tag_usage(args.unpacked)
    shim_js, shim_n = _shim_js(macros, args.engine,
                               collect_scene_tags(args.unpacked), tag_usage)
    runtime_shim = "\n".join([
        "window.__kag3_portrait = " + ("true" if args.portrait else "false") + ";",
        RUNTIME_SHIM_IIFE,
        FAST_SKIP_SHIM_JS if args.fast_skip else "",
        tjs2js.SPRINTF_SHIM,
        asset_js,
        asset_ma_js,
        asset_video_js,
        _state_overrides_js(state_overrides),
        "if (typeof window.seen_list === 'undefined') { window.seen_list = []; }",
        "if (typeof window.seen_ani_list === 'undefined') { window.seen_ani_list = []; }",
        "if (typeof window.anlist === 'undefined') { window.anlist = []; }",
        "if (typeof window.sentaku === 'undefined') { window.sentaku = []; }",
        "if (typeof window.mpglist === 'undefined') { window.mpglist = []; }",
        "window.StoreData = window.StoreData || function () {};",
        "window.SeenAniData = window.SeenAniData || function () {};",
        "window.CharHisVoFlgCheck = window.CharHisVoFlgCheck || function () { return 0; };",
        "window.CharVoiceFlgCheck = window.CharVoiceFlgCheck || function () { return 0; };",
        "window.CharVoiceVolCheck = window.CharVoiceVolCheck || function () { return 0; };",
        "window.AutoModeCheck = window.AutoModeCheck || function () {};",
        "window.FukuSabunChk = window.FukuSabunChk || function (a) { return a; };",
        "window.intrandom = window.intrandom || function (a, b) { return a + Math.floor(Math.random() * (b - a + 1)); };",
        "window.System = window.System || {",
        "  shellExecute: function (url) { try { window.open(url); } catch (e) {} },",
        "  touchImages: function (arr) { return 0; },",
        "  inform: function (m) { console.log('[kag System.inform]', m); },",
        "  exit: function () {},",
        "  setCursorStyle: function () {},",
        "  messageBox: function (m) { console.log('[kag System.messageBox]', m); },",
        "  isExistentStorage: function (p) { return false; },",
        "  getBookMarkFileNameAtNum: function (n) { return 'save' + n + '.dat'; },",
        "};",
        "window.Storages = window.Storages || {",
        "  extractStorageExt: function (p) { var i = String(p).lastIndexOf('.'); return i >= 0 ? String(p).slice(i + 1) : ''; },",
        "  isExistentStorage: function (p) { return false; },",
        "};",
        "",
    ])
    with open(os.path.join(plugin_dir, "kag.tag_kag3shim.js"), "w", encoding="utf-8") as f:
        f.write(runtime_shim + shim_js)
    stats["shim_tags"] = shim_n
    # load the shim: index.html lists tag js files explicitly, so inject
    # a <script> tag after kag.tag.js
    idx_path = os.path.join(out, "index.html")
    if os.path.isfile(idx_path):
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = f.read()
        shim_tag = '<script src="./tyrano/plugins/kag/kag.tag_kag3shim.js"></script>'
        if shim_tag not in idx:
            # insert after the kag.tag.js <script> line (line-based insert,
            # immune to quote/replace quirks in the engine template)
            lines = idx.splitlines(keepends=True)
            out_lines = []
            done = False
            for ln in lines:
                out_lines.append(ln)
                if not done and 'kag.tag.js"' in ln and 'kag3shim' not in ln:
                    out_lines.append("        " + shim_tag + "\n")
                    done = True
            if done:
                idx = "".join(out_lines)
                with open(idx_path, "w", encoding="utf-8") as f:
                    f.write(idx)
                log.info("index.html: injected kag3shim script tag")
            else:
                log.warning("index.html: kag.tag.js script line not found")

    log.info("scenario files: %d (%d lines), skipped %d", stats["files"], stats["lines"], stats.get("skipped", 0))
    log.info("tlg converted: %d (fail %d), bmp: %d (fail %d), copied: %d",
             stats["tlg"], stats["tlg_fail"], stats["bmp"], stats["bmp_fail"],
             stats["copied"])
    log.info("shim tags: %d; game macros: %d", stats["shim_tags"], len(macros))
    # Intent inventory: hand-writing the real behaviour later starts from this.
    shim_names = re.findall(r'define\("([^"]+)"\)', shim_js)
    intents_path = write_intents(out, tag_usage, shim_names,
                                 dropped=_DROPPED_TAGS,
                                 degraded=SYSTEM_ISCRIPT_DROP)
    log.info("intents -> %s (%d stubbed tags, %d dropped)",
             os.path.basename(intents_path), len(shim_names), len(_DROPPED_TAGS))
    log.info("done -> %s", out)
    return 0


# --- CLI ---------------------------------------------------------------------

def cmd(
    unpacked: Annotated[str, typer.Argument(
        help="extracted KAG3 game dir (xp3tool extract)")],
    engine: Annotated[str, typer.Argument(
        help="TyranoScript engine source tree (index.html + tyrano/)")],
    out_dir: Annotated[str, typer.Argument(help="output TyranoScript project")],
    keep_game_buttons: Annotated[bool, typer.Option(
        "--keep-game-buttons",
        help="keep the game's own system-button row (default: dropped; it "
             "overlaps the message text and needs engine APIs Tyrano lacks)")] = False,
    scenario_dir: Annotated[str, typer.Option(
        "--scenario-dir", help="scenario subdir in unpacked (default: scenario)")] = "scenario",
    scenario_only: Annotated[bool, typer.Option(
        "--scenario-only",
        help="only re-convert scenario .ks (skip engine copy and assets)")] = False,
    font: Annotated[Optional[List[str]], typer.Option(
        "--font", metavar="OTF",
        help="install a CJK font as the default text face (font.css @font-face "
             "+ Config.tjs userFace; repeatable)")] = None,
    video_dir: Annotated[Optional[str], typer.Option(
        "--video-dir", metavar="DIR",
        help="directory of pre-transcoded WebM movies named <stem>.webm "
             "(default: <unpacked>/_video_webm).  A movie with no WebM is "
             "copied as-is and warned about, since browsers cannot play WMV")] = None,
    fast_skip: Annotated[bool, typer.Option(
        "--fast-skip",
        help="drive the flow while skip mode is on, so skipping fast-forwards "
             "without a click per line (debugging)")] = False,
    state_overrides: Annotated[Optional[str], typer.Option(
        "--state-overrides", metavar="JSON",
        help="JSON file containing persistent f/sf/tf variable defaults; use "
             "this for game-specific gallery unlock flags")] = None,
    portrait: Annotated[bool, typer.Option(
        "--portrait",
        help="768x1024 portrait layout: art scaled to the top, message text in "
             "the bottom black area")] = False,
    workers: Annotated[Optional[int], typer.Option(
        "--workers",
        help="parallel asset workers (default: physical cores, auto-tuned; "
             "1 = serial)")] = None,
    verbose: cliutil.Verbose = False,
    quiet: cliutil.Quiet = False,
    log_file: cliutil.LogFile = None,
) -> int:
    """Minimal KAG3 (.ks) -> TyranoScript project conversion."""
    cliutil.setup_logging(verbose, quiet, log_file)
    return convert(unpacked=unpacked, engine=engine, out_dir=out_dir,
                   keep_game_buttons=keep_game_buttons,
                   scenario_dir=scenario_dir, scenario_only=scenario_only,
                   fonts=font, video_dir=video_dir, fast_skip=fast_skip,
                   state_overrides_path=state_overrides, portrait=portrait,
                   workers=workers)


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    """Run the CLI (``python kirikiri/convert_kag.py ...`` stays supported)."""
    return cliutil.run(app, argv, prog="convert_kag.py")


if __name__ == "__main__":
    raise SystemExit(main())
