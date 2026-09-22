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
from typing import Annotated

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
from rpgmaker import cliutil, platform

log = logging.getLogger(__name__)


def convert(*, unpacked, engine, out_dir, keep_game_buttons=False,
            scenario_dir="scenario", scenario_only=False, fonts=None,
            video_dir=None, fast_skip=False, state_overrides_path=None,
            portrait=False, workers=None, video_fit="box", msg_style="plate",
            title_jump=None, asset_dirs=None, first_scenario=None):
    """Convert one unpacked KAG3 game into a TyranoScript project.

    Programmatic entry point; the Typer command below is its CLI wrapper.  The
    body is the historical ``main()`` with its argparse namespace replaced by
    these explicit arguments (behaviour unchanged); `workers` is the only new
    knob (image/copy parallelism, None = auto-tuned from the machine).

    ``video_fit``: "box" honours the KAG3 [video width=/height=] box;
    "fill" scales the movie to the whole game canvas (object-fit keeps the
    frame ratio).  ``msg_style``: "plate" keeps the game's message window
    frame; "bare" drops the plate and gives the text an outline + shadow at
    reduced opacity (experimental, main story layer only).
    ``asset_dirs`` overrides the source-folder -> data-folder table for this
    game (KAG3 games name their asset folders inconsistently; see
    kirikiri.kag.assets.DEFAULT_ASSET_DIRS).
    """
    # AGENTS.md CRITICAL: the source tree, the engine skeleton and the output
    # folder are all read/written by this WSL-native process.  Gate before the
    # first write (the engine skeleton copy, which also rmtree's the output's
    # scenario dir).
    own = platform.require_native_paths("convert kag3 game", unpacked=unpacked,
                                        engine=engine, out_dir=out_dir)
    unpacked, engine = str(own["unpacked"]), str(own["engine"])
    out_dir = str(own["out_dir"])
    args = SimpleNamespace(
        unpacked=unpacked, engine=engine, out_dir=out_dir,
        keep_game_buttons=keep_game_buttons, scenario_dir=scenario_dir,
        scenario_only=scenario_only, font=fonts, video_dir=video_dir,
        fast_skip=fast_skip, state_overrides=state_overrides_path,
        portrait=portrait, video_fit=video_fit, msg_style=msg_style,
        title_jump=title_jump, asset_dirs=asset_dirs,
        first_scenario=first_scenario,
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
        sys_dst = _copy_engine_skeleton(args.engine, out)

    os.makedirs(out_data, exist_ok=True)

    # macros (informational)
    macros = _collect_macros(unpacked)

    # Scenario: EVERY .ks anywhere in the tree, flattened into data/scenario/.
    scen_dst = os.path.join(out_data, "scenario")
    os.makedirs(scen_dst, exist_ok=True)
    seen = _convert_scenarios(unpacked, scen_dst, macros, stats)

    # Entry scenario.  Tyrano boots by loading `data/scenario/first.ks` unless
    # index.html overrides it through `#first_scenario_file`.
    _set_entry_scenario(out, getattr(args, "first_scenario", None), seen)

    make_ks = _write_make_ks(scen_dst)
    if make_ks:
        log.info("make.ks: generated load/return pass-through")

    # assets
    video_map = _prepare_assets(args, unpacked, out_data, stats, workers)

    # game-specific Config.tjs settings (window size from the KAG3 game)
    _rewrite_config_tjs(sys_dst, args.portrait)

    # portrait layout: scale art to the top, message text into the black
    # bottom area (768x1024 canvas; engine CSS + shim [position] remap;
    # idempotent, so it also runs in scenario-only mode)
    if args.portrait:
        _inject_portrait(out, log)

    # unified CJK font (project convention, parameterized --font)
    _inject_fonts(out, args.font)

    # shim plugin + runtime shim
    plugin_dir = _shim_plugin_dir(out)
    tag_usage = collect_tag_usage(unpacked)
    shim_js, shim_n = _write_shim(plugin_dir, args, unpacked, out_data, macros,
                                  video_map, state_overrides, tag_usage)
    stats["shim_tags"] = shim_n
    _inject_shim_script(out)

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


def _copy_engine_skeleton(engine, out):
    """Copy the TyranoScript engine tree in and return the system dir.

    Only `Config.tjs` and `KeyConfig.js` survive from the engine's own
    `data/system`; the engine's sample scenarios (`scene1.ks` etc) are deleted
    from the output because the scenario walk would otherwise pick them up as
    game files and pollute the build.
    """
    _copy_tree(engine, out, ignore_exts=())
    out_scen = os.path.join(out, "data", "scenario")
    if os.path.isdir(out_scen):
        shutil.rmtree(out_scen)
    sys_dst = os.path.join(out, "data", "system")
    sys_src = os.path.join(engine, "data", "system")
    if os.path.isdir(sys_src):
        os.makedirs(sys_dst, exist_ok=True)
        for fn in ("Config.tjs", "KeyConfig.js"):
            src = os.path.join(sys_src, fn)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(sys_dst, fn))
    return sys_dst


def _convert_scenarios(unpacked, scen_dst, macros, stats):
    """Convert EVERY ``.ks`` anywhere under `unpacked`; return the name set.

    KAG3 games keep scenarios in the root, in `scenario/`, and sometimes in
    nested folders - measured: one entry scenario was
    `system/gamesystem/first.ks` and another game's were all in `scenario/`.
    The old two-level scan (root + `scenario/`) silently dropped the nested
    ones, including the entry, so the build booted to a black screen with
    "file not found: ./data/scenario/first.ks".  The walk is sorted so the
    first copy of a duplicated basename wins deterministically.
    """
    seen = set()
    for root_dir, dirs, files in os.walk(unpacked):
        dirs.sort()
        for fn in sorted(files):
            if not fn.lower().endswith(".ks"):
                continue
            target = fn.lower()
            if target in seen:
                continue
            seen.add(target)
            convert_scenario_file(os.path.join(root_dir, fn), unpacked,
                                  os.path.join(scen_dst, target), macros, stats)
    if not seen:
        log.warning("no .ks scenario found under %s", unpacked)
    return seen


def _set_entry_scenario(out, explicit, seen):
    """Point index.html's ``#first_scenario_file`` at the boot scenario.

    Tyrano boots by loading `data/scenario/first.ks` unless index.html
    overrides it, and the engine's template ships that input with a
    placeholder value pointing at `http://test.com/...` - a game whose entry
    is not `first.ks` therefore booted to a black screen.  KAG3 has no
    readable declaration of the entry, so prefer the caller's value (game
    data) and fall back to the `first.ks` convention - loudly when neither
    works.
    """
    entry = _resolve_first_scenario(explicit, seen)
    idx_path = os.path.join(out, "index.html")
    if not (entry and os.path.isfile(idx_path)):
        return
    with open(idx_path, encoding="utf-8") as f:
        html = f.read()
    patched, n = re.subn(
        r'(id="first_scenario_file"[^>]*?value=")[^"]*(")',
        lambda m: m.group(1) + entry + m.group(2), html)
    if n == 0:
        patched, n = re.subn(
            r'(<body[^>]*>)',
            lambda m: m.group(1) + '\n<input type="hidden" '
                      f'id="first_scenario_file" value="{entry}">',
            html, count=1)
    if n:
        with open(idx_path, "w", encoding="utf-8") as f:
            f.write(patched)
        log.info("index.html: first scenario = %s", entry)
    else:
        log.warning("index.html: could not set #first_scenario_file; the "
                    "build may not boot")


def _prepare_assets(args, unpacked, out_data, stats, workers):
    """Convert assets (or reuse the existing ones) and return the video map."""
    if args.scenario_only:
        log.info("scenario-only: assets reused from existing output")
        return _video_map_from_output(out_data)
    _convert_assets(unpacked, out_data, stats, workers=workers,
                    asset_dirs=args.asset_dirs)
    return _convert_videos(unpacked, out_data, args.video_dir, stats)


def _rewrite_config_tjs(sys_dst, portrait):
    """Rewrite the game-specific Config.tjs knobs (window size, speeds)."""
    cfg_path = os.path.join(sys_dst, "Config.tjs")
    if not os.path.isfile(cfg_path):
        return
    with open(cfg_path, encoding="utf-8") as f:
        cfg = f.read()
    scw, sch = (768, 1024) if portrait else (1024, 768)
    replacements = [
        (r"scWidth", ";scWidth = %d;" % scw),
        (r"scHeight", ";scHeight = %d;" % sch),
        (r"configSave", ";configSave = webstorage;"),
        (r"numMessageLayers", ";numMessageLayers = 14;"),
        (r"numCharacterLayers", ";numCharacterLayers = 12;"),
        # text speed: near-instant so clicks advance dialogue immediately
        # (KAG3 typewriter waits eat clicks; players expect click-to-advance)
        (r"chSpeed", ";chSpeed = 3;"),
        (r"chSpeeds\.fast", ";chSpeeds.fast = 1;"),
        (r"chSpeeds\.normal", ";chSpeeds.normal = 3;"),
        (r"chSpeeds\.slow", ";chSpeeds.slow = 5;"),
        # skip speed: Tyrano waits config.skipSpeed ms per printed line while
        # skipping (kag.tag.js: after all characters are shown it does
        # setTimeout(nextOrder, skipSpeed)), so it caps skipping at
        # 1000/skipSpeed lines per second.  The template's 30 ms caps it at
        # 33 lines/s, which dominates fast-forwarding a build for testing;
        # 1 ms lets the flow run as fast as the browser allows.  Only skip
        # mode reads this, so normal reading speed is unaffected.
        (r"skipSpeed", ";skipSpeed = 1;"),
    ]
    if portrait:
        # default message window sits in the bottom black area
        # (image area is the top 768x576 of the 768x1024 canvas)
        replacements += [(r"ml", ";ml = 0;"), (r"mt", ";mt = 640;"),
                         (r"mw", ";mw = 768;"), (r"mh", ";mh = 384;")]
    for key, value in replacements:
        cfg = re.sub(r"(?m)^;?\s*%s\s*=.*$" % key, value, cfg)
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(cfg)
    log.info("Config.tjs: scWidth/Height=%dx%d, configSave=webstorage", scw, sch)


def _inject_fonts(out, fonts):
    """Install each ``--font`` file as the default text face (project policy)."""
    for path in fonts or ():
        if os.path.isfile(path):
            _inject_font(out, path, "Glow Sans SC", log)
        else:
            log.warning("font file not found: %s", path)


def _shim_plugin_dir(out):
    """The directory the shim plugin goes in (engine layouts differ)."""
    plugin_dir = os.path.join(out, "tyrano", "plugins", "kag")
    if not os.path.isdir(plugin_dir):
        plugin_dir = os.path.join(out, "tyrano", "plugins")
        os.makedirs(plugin_dir, exist_ok=True)
    return plugin_dir


def _write_shim(plugin_dir, args, unpacked, out_data, macros, video_map,
                state_overrides, tag_usage):
    """Write the runtime shim + generated KAG3-only tag stubs; return them.

    Returns ``(shim_js, stub_count)``: `shim_js` is also what the intent
    inventory parses for the stubbed tag names.
    """
    # asset name maps for the runtime storage resolver (extensionless KAG3
    # storages) and the clickable-map engine (.ma files, _p region images).
    amap, full_map = _runtime_asset_maps(unpacked, out_data, args.scenario_only)
    _ASSET_CACHE[unpacked] = (amap, full_map)
    ma_map = {k.rsplit(".", 1)[0]: v for k, v in full_map.items()
              if k.endswith(".ma")}
    runtime_assets = dict(amap)
    runtime_assets.update(full_map)
    asset_js = ("window.__kag3_assets = "
                + json.dumps(runtime_assets, ensure_ascii=False) + ";\n")
    asset_ma_js = ("window.__kag3_assets_ma = "
                   + json.dumps(ma_map, ensure_ascii=False) + ";\n")
    # name -> converted movie, for the KAG3 video shim ([openvideo storage=X])
    asset_video_js = "window.__kag3_videos = " + json.dumps(
        video_map, ensure_ascii=False) + ";\n"
    # build knobs consumed by the shims (video box vs. full-canvas playback,
    # experimental bare message style)
    video_fit_js = "window.__kag3_video_fill = " + \
        ("true" if args.video_fit == "fill" else "false") + ";\n"
    msg_style_js = "window.__kag3_msg_style = " + \
        json.dumps(str(args.msg_style)) + ";\n"
    # In-game menu target: the title storage/label is game data, so the caller
    # passes it in ("storage:label") instead of the shim guessing.
    _tj_storage, _tj_target = _split_title_jump(getattr(args, "title_jump", None))
    title_jump_js = "window.__kag3_title_jump = " + json.dumps(
        {"storage": _tj_storage, "target": _tj_target}) + ";\n"
    shim_js, shim_n = _shim_js(macros, args.engine,
                               collect_scene_tags(unpacked), tag_usage)
    runtime_shim = "\n".join([
        "window.__kag3_portrait = " + ("true" if args.portrait else "false") + ";",
        video_fit_js,
        msg_style_js,
        title_jump_js,
        RUNTIME_SHIM_IIFE,
        FAST_SKIP_SHIM_JS if args.fast_skip else "",
        tjs2js.SPRINTF_SHIM,
        asset_js,
        asset_ma_js,
        asset_video_js,
        _state_overrides_js(state_overrides),
    ] + _KAG3_COMPAT_STUBS)
    with open(os.path.join(plugin_dir, "kag.tag_kag3shim.js"), "w",
              encoding="utf-8") as f:
        f.write(runtime_shim + shim_js)
    return shim_js, shim_n


#: Globals the KAG3 system scripts expect; deferred to the engine when it has
#: a real implementation (`window.X = window.X || ...` never overwrites one).
_KAG3_COMPAT_STUBS = [
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
]


#: The shim <script> tag; index.html lists tag js files explicitly.
_SHIM_SCRIPT_TAG = ('<script src="./tyrano/plugins/kag/'
                    'kag.tag_kag3shim.js"></script>')


def _inject_shim_script(out):
    """Add the shim <script> line to index.html right after kag.tag.js.

    A line-based insert rather than a regex: the engine template's quoting
    varies between TyranoScript versions, so matching the line the engine
    itself loads `kag.tag.js` from is the stable anchor.
    """
    idx_path = os.path.join(out, "index.html")
    if not os.path.isfile(idx_path):
        return
    with open(idx_path, encoding="utf-8") as f:
        idx = f.read()
    if _SHIM_SCRIPT_TAG in idx:
        return
    out_lines = []
    done = False
    for ln in idx.splitlines(keepends=True):
        out_lines.append(ln)
        if not done and 'kag.tag.js"' in ln and 'kag3shim' not in ln:
            out_lines.append("        " + _SHIM_SCRIPT_TAG + "\n")
            done = True
    if not done:
        log.warning("index.html: kag.tag.js script line not found")
        return
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write("".join(out_lines))
    log.info("index.html: injected kag3shim script tag")


def _write_make_ks(scen_dst):
    """Generate Tyrano's load/return pass-through when the game has none.

    When a save is restored the engine inserts `[call storage="make.ks"]`
    before jumping back to the saved position (kag.menu.js), and with no such
    file it raises a *blocking* alert (lang.js `file_not_found`:
    "ファイルが見つかりませんでした。 / ./data/scenario/make.ks") that freezes
    the page - measured as "loading a save hangs the game".  KAG3 has no
    make.ks, so generate the engine's own pass-through ([return]); an existing
    file (a game that ships one) is never touched.
    """
    path = os.path.join(scen_dst, "make.ks")
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write("; Tyrano load/return pass-through, generated by the KAG3 converter.\n"
                "; The engine calls this on save-load and expects a return.\n"
                "[return]\n")
    return True


def _resolve_first_scenario(explicit, seen):
    """Which scenario the build should boot; None when it cannot be told.

    ``explicit`` is game data (CLI/profile), never a hardcoded title; the
    fallback is the KAG3 `first.ks` convention.  A wrong entry is invisible
    offline - it shows up as a black screen with "file not found:
    ./data/scenario/first.ks" - so an unresolvable entry is a loud warning.
    """
    if explicit:
        name = os.path.basename(explicit).lower()
        if name not in seen:
            log.warning("first scenario %s is not among the game's scenarios "
                        "(%d known); the build will not boot", explicit,
                        len(seen))
        return name
    if "first.ks" in seen:
        return "first.ks"
    log.warning("this game has no first.ks and no --first-scenario was given: "
                "the build will boot to a black screen.  Find the entry "
                "(title/menu script) and pass --first-scenario NAME.ks")
    return None


def _split_title_jump(value):
    """Split the ``--title-jump`` knob (``storage`` or ``storage:label``).

    The title storage/label is game data, so the shim never guesses it; the
    caller names the game's own return-to-title target (the same one the game
    uses itself, e.g. ``first.ks:*start``).
    """
    raw = str(value or "").strip().lstrip("*")
    if not raw:
        return "", ""
    if ":" in raw:
        storage, _, target = raw.partition(":")
        return storage.strip(), target.strip().lstrip("*")
    return raw, ""


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
    font: Annotated[list[str] | None, typer.Option(
        "--font", metavar="OTF",
        help="install a CJK font as the default text face (font.css @font-face "
             "+ Config.tjs userFace; repeatable)")] = None,
    video_dir: Annotated[str | None, typer.Option(
        "--video-dir", metavar="DIR",
        help="directory of pre-transcoded WebM movies named <stem>.webm "
             "(default: <unpacked>/_video_webm).  A movie with no WebM is "
             "copied as-is and warned about, since browsers cannot play WMV")] = None,
    fast_skip: Annotated[bool, typer.Option(
        "--fast-skip",
        help="drive the flow while skip mode is on, so skipping fast-forwards "
             "without a click per line (debugging)")] = False,
    state_overrides: Annotated[str | None, typer.Option(
        "--state-overrides", metavar="JSON",
        help="JSON file containing persistent f/sf/tf variable defaults; use "
             "this for game-specific gallery unlock flags")] = None,
    portrait: Annotated[bool, typer.Option(
        "--portrait",
        help="768x1024 portrait layout: art scaled to the top, message text in "
             "the bottom black area")] = False,
    video_fit: Annotated[str, typer.Option(
        "--video-fit", metavar="BOX|FILL",
        help="movie playback area: box = honour the KAG3 [video width=/height=] "
             "box (KAG3 semantics); fill = scale the movie to the whole game "
             "canvas, frame ratio preserved (default: box)")] = "box",
    msg_style: Annotated[str, typer.Option(
        "--msg-style", metavar="PLATE|BARE",
        help="story message window: plate = keep the game's window frame; "
             "bare = drop the plate, text carries an outline + shadow at 80% "
             "opacity (experimental; name plate unaffected) (default: plate)")] = "plate",
    title_jump: Annotated[str, typer.Option(
        "--title-jump", metavar="STORAGE[:LABEL]",
        help="target of the in-game menu's 'back to main menu' entry, e.g. "
             "\"first.ks:*start\"; game specific, omit to leave the menu "
             "without that entry")] = "",
    workers: Annotated[int | None, typer.Option(
        "--workers",
        help="parallel asset workers (default: physical cores, auto-tuned; "
             "1 = serial)")] = None,
    asset_dirs: Annotated[str | None, typer.Option(
        "--asset-dirs", metavar="SRC=DST[,SRC=DST...]",
        help="override the source-folder -> data-folder table for this game "
             "(e.g. \"bg=bgimage,se=sound\"); folders nobody knows are kept "
             "under their own name")] = None,
    first_scenario: Annotated[str | None, typer.Option(
        "--first-scenario", metavar="NAME.ks",
        help="scenario the engine boots (default: first.ks when the game has "
             "one); game specific - a wrong value shows up as a black "
             "screen")] = None,
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
                   workers=workers, video_fit=video_fit, msg_style=msg_style,
                   title_jump=title_jump, asset_dirs=_parse_asset_dirs(asset_dirs),
                   first_scenario=first_scenario)


def _parse_asset_dirs(spec):
    """Parse ``SRC=DST[,SRC=DST...]`` into a dict (None/empty -> None)."""
    if not spec:
        return None
    table = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise typer.BadParameter(f"bad --asset-dirs entry {item!r} (expected SRC=DST)")
        src, dst = (part.strip() for part in item.split("=", 1))
        if not src or not dst:
            raise typer.BadParameter(f"bad --asset-dirs entry {item!r} (expected SRC=DST)")
        table[src] = dst
    return table or None


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    """Run the CLI (``python kirikiri/convert_kag.py ...`` stays supported)."""
    return cliutil.run(app, argv, prog="convert_kag.py")


if __name__ == "__main__":
    raise SystemExit(main())
