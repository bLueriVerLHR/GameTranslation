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
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri.ks_extract import detect_encoding
from kirikiri import tlg
from kirikiri import tjs2js

log = logging.getLogger("convert_kag")


# ---------------------------------------------------------------------------
# KAG3-only tags that TyranoScript V6 does not implement.
# Registered as no-op plugin tags so scenarios do not hit undefined_tag.
# ---------------------------------------------------------------------------

SHIM_TAG_NAMES = list(dict.fromkeys([
    "laycount", "startanchor",
    "disablestore", "loadplugin", "style", "resetstyle", "hr", "wm",
    "hact", "endhact", "select_clear", "link2", "pimage",
    "clickskip", "tempsave", "tempload", "locksnapshot", "unlocksnapshot",
    "mes_return", "stoptrans", "mpeg_load", "mpeg_disp", "mpeg_effect",
    "start_mpeg", "stop_mpeg", "videolayer", "preparevideo", "openvideo",
    "playvideo", "stopvideo", "clearvideolayer", "pv_start", "pv_end",
    "staff_roll_wait", "slide_wait", "mapdisablie", "seen_list", "rvo_s",
    "vo_s", "vo_cof", "se_cof", "bgm_cof", "bgm_s", "se_stop", "se_l",
    "fadeoutse", "h_bmp", "faid_in", "faid_out", "faid_in_t", "faid_out_t",
    "t_fadein", "t_fadeout", "t_bmp", "t_off", "t_move", "t_move2",
    "t_mov_init", "t_pos_init", "t_pos_chg", "t_pos_tai", "t_pos_ret",
    "t_alpha_set", "t_sepia_set", "t_flipud_set", "t_ripple_in",
    "t_ripple_out", "m_quake", "wq", "ws", "wv", "flash", "rnd_tr",
    "tr", "bgm_fs", "bgm_fs_w", "bgm_fi", "bgm_l_s", "bgmopt", "fadeinbgm",
    "mask_chips", "cgroom_bmp", "tips_off", "tips_on", "mes_tips_on",
    "name_tips_on", "name_tips_off", "mes_size", "mes_wide", "mes_tips_off",
    "tips_w_on", "c_mark", "c_mark_off", "c_mark_ga", "anime_disp",
    "anime_bot", "anime_auto", "anime_manu", "anime_off", "anime_mode_on",
    "anime_mode_off", "start_anime", "start_anime_nowait", "stop_anime",
    "stop_anime_nowait", "zoomrot", "wzoomrot", "zoom_on", "zoom_off",
    "evcg_a", "evcg_b", "evcg_cng", "evcg_cng_off", "siru_on", "siru_off",
    "skip_bot", "skip_bot_off", "config_bot", "config_bot_off",
    "history_bot", "history_bot_off", "save_bot", "save_bot_off",
    "load_bot", "load_bot_off", "q_save_bot", "q_save_bot_off",
    "q_load_bot", "q_load_bot_off", "voice_bot", "voice_bot_off",
    "menu_bot", "menu_bot_off", "sysmenu", "name_w", "name_m", "name_m2",
    "t_next", "l_next", "rvo", "vo", "b", "b2", "bg", "select_center",
    "select_normal", "select_time_center", "select_a_time_center",
    "select_wide", "select_w_clear", "all_fadein", "all_fadeout",
    "all_tr_in", "all_tr_out", "faid_in_fs", "tr_fs", "flash_fs",
    "t_bmp_fs", "t_fadein_fs", "move_in_fs", "t_ripple_in_fs",
    "m_fadein", "m_fadeout", "m_tr_in", "m_tr_out", "m_mos_in",
    "m_mos_out", "m_turn_in", "m_turn_out", "m_wave_in", "m_wave_out",
    "scroll_u2d", "scroll_d2u", "scroll_l2r", "scroll_r2l", "m_quake_in",
    "t_sepia", "t_ripple", "wv", "wb", "wa", "stoptrans", "mpeg",
    "movie_seen", "movie_seen2", "mpglist", "seen_list", "seen_ani_list",
    "kag", "mes", "pageturn", "noise", "static", "alpha", "graphic",
    "screen", "clickanime", "click_anime", "enter", "leave", "select",
    "start", "end", "load", "save", "menu", "close", "yes", "no",
    "ex", "ex_tips", "ex_menu", "ex_anime", "ex_voice", "ex_config",
    "ex_gallery", "ex_seen", "ex_mpg", "ex_line", "ex_clear", "ex_erase",
    "kag_in", "kag_out", "sys", "sys2", "sys_menu", "system",
    "history", "move", "video", "waittrig", "locklink", "t_init",
    "belt_init", "effect_init", "effect_on", "resetwait", "ruby",
    "cg_image_button", "replay_image_button", "start_anime",
    "movie_seen", "movie_seen2", "seen", "seen2", "save", "load",
    "menu", "close", "yes", "no", "select", "start", "end", "enter",
    "leave", "graphic", "alpha", "noise", "static", "screen",
]))

# System-level scenario files whose iscript bodies are not needed for the
# main story: load/save tests, staff roll, slide galleries. Their iscript
# blocks are commented out (degraded) rather than converted. Feature
# scenarios (gallery/seen/config/submenu) keep their iscript - they are
# plain data or simple TJS and are required for the menus to work.
SYSTEM_ISCRIPT_DROP = {
    "load_test.ks", "loadgame.ks", "save_test.ks", "slide.ks",
    "staff_roll.ks", "config_test.ks", "config_test2.ks", "config_test3.ks",
    "menu_help.ks", "s_select.ks",
    "loadgame.ks", "sys_voice_set.ks", "sys_voice_mload.ks",
    "sys_voice_load.ks", "sys_voice_save.ks", "sys_voice_slide.ks",
    "sys_voice_menu.ks", "sys_voice_mcon.ks", "sys_voice_mpg.ks",
    "sys_voice_seen.ks", "sys_voice_seen_ani.ks", "sys_voice_seen_ani_set.ks",
    "sys_voice_seen_set.ks", "sys_voice_ti.ks", "sys_voice_lmain.ks",
    "zoomrot.ks",
}

# Extra KAG3 tags mapped to a Tyrano equivalent (tag -> replacement attrs).
TAG_MAP = {
    # wm (message window show) -> show message layer
    "wm": "layopt layer=message0 visible=true",
    # bg in KAG3 == background switch; Tyrano has [bg] already, keep name
}


def _shim_js(macros=()):
    """Generate the plugin js registering KAG3-only tags as no-ops.

    Only tags that TyranoScript does not implement AND are not game-defined
    macros get shimmed: if a game macro name were registered here it would
    shadow the macro (Tyrano checks master_tag before map_macro) and the
    macro body would never run.
    """
    macros = {m.lower() for m in macros}
    # Tags with a real implementation below must NOT also be registered as
    # no-ops (a later registration would win and the feature would silently
    # disappear).
    real = set(VIDEO_TAGS)
    names = [n for n in SHIM_TAG_NAMES
             if n.lower() not in macros and n.lower() not in real]
    lines = [
        "// Auto-generated by convert_kag.py: KAG3-only tags as no-ops.",
        "// Ensures scenarios do not hit TyranoScript's undefined_tag error.",
        "(function () {",
        "  var noop = function (pm) { this.kag.ftag.nextOrder(); };",
    ]
    for name in sorted(names):
        lines.append('  tyrano.plugin.kag.tag["%s"] = { start: noop };' % name)
    lines.append("})();")
    return "\n".join(lines) + "\n", len(names)


# KAG3 video system -> Tyrano [layermode_movie].
#
# KAG3 splits movie playback across a sequence of tags that share state:
#   [video top=.. left=.. width=.. height=.. loop=.. mode="layer"]  geometry
#   [videolayer channel=1 page=fore layer=N]                        target layer
#   [preparevideo]                                                  no-op
#   [openvideo storage=X]                                           the file
#   [wv]                      wait until ready (before play) / until the end
#   [playvideo]                                                     start
#   [stopvideo] / [clearvideolayer]                                 stop
# Tyrano has no equivalent sequence, but [layermode_movie] does the hard part
# (a <video> composited into the layer stack with a blend mode).  So the tags
# accumulate state here and [playvideo] issues one layermode_movie.
#
# [wv] is state-dependent exactly as in KAG3: before play it waits for the
# file to be ready, after play it waits for the video to end.  It never blocks
# forever: if there is no video, or it is already finished, it advances.
VIDEO_TAGS = ("video", "videolayer", "preparevideo", "openvideo",
              "playvideo", "stopvideo", "clearvideolayer", "wv")

VIDEO_SHIM_JS = """\
  // ---- KAG3 video system (see VIDEO_SHIM_JS in convert_kag.py) ----
  var __kag3_vid = {
    layer: null, page: 'fore', top: 0, left: 0, width: 0, height: 0,
    loop: 'true', visible: false, file: null, playing: false, url: null
  };
  var __kag3_vid_map = function () { return window.__kag3_videos || {}; };
  var __kag3_vid_resolve = function (name) {
    var s = String(name == null ? '' : name);
    if (!s) return null;
    var m = __kag3_vid_map();
    var stem = s.replace(/^.*[\\/]/, '').replace(/\\.[^.]+$/, '');
    return m[s.toLowerCase()] || m[stem.toLowerCase()] || s;
  };
  var __kag3_vid_el = function () {
    try { return $('.blendvideo, video.layer_blend_mode').last(); } catch (e) { return $(); }
  };
  var __kag3_vid_stop = function () {
    try {
      __kag3_vid_el().each(function () {
        try { this.pause(); this.removeAttribute('src'); this.load(); } catch (e) {}
        $(this).remove();
      });
    } catch (e) {}
    __kag3_vid.playing = false;
  };
  // Tyrano's [layermode_movie] sets `min-width/height: 100%` AFTER applying
  // width/height, so an explicit KAG3 box ([video width=800 height=600]) is
  // silently overridden and the movie fills the whole canvas.  Measured:
  // element 1024x768 (canvas) before, 800x600 after clearing min-*.  KAG3
  // scales the frame INTO the box, so object-fit: contain reproduces that
  // instead of stretching it.
  var __kag3_vid_fit = function () {
    try {
      __kag3_vid_el().each(function () {
        this.style.minWidth = '0';
        this.style.minHeight = '0';
        this.style.objectFit = 'contain';
      });
    } catch (e) {}
  };

  tyrano.plugin.kag.tag['video'] = {
    start: function (pm) {
      var v = __kag3_vid;
      if (pm.layer !== undefined) v.layer = String(pm.layer);
      if (pm.top !== undefined) v.top = parseInt(pm.top, 10) || 0;
      if (pm.left !== undefined) v.left = parseInt(pm.left, 10) || 0;
      if (pm.width !== undefined) v.width = parseInt(pm.width, 10) || 0;
      if (pm.height !== undefined) v.height = parseInt(pm.height, 10) || 0;
      if (pm.loop !== undefined) v.loop = String(pm.loop);
      if (pm.visible !== undefined) v.visible = String(pm.visible) === 'true';
      __kag3_log('video setup layer=' + v.layer + ' ' + v.left + ',' + v.top +
                 ' ' + v.width + 'x' + v.height + ' loop=' + v.loop);
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['videolayer'] = {
    start: function (pm) {
      var v = __kag3_vid;
      if (pm.layer !== undefined) v.layer = String(pm.layer);
      if (pm.page !== undefined) v.page = String(pm.page);
      __kag3_log('videolayer ' + v.layer + ' page=' + v.page);
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['preparevideo'] = {
    start: function (pm) { this.kag.ftag.nextOrder(); },
  };

  tyrano.plugin.kag.tag['openvideo'] = {
    start: function (pm) {
      var name = pm.storage || pm.file || '';
      __kag3_vid.file = __kag3_vid_resolve(name);
      __kag3_vid.playing = false;
      __kag3_log('openvideo ' + name + ' -> ' + __kag3_vid.file);
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['playvideo'] = {
    start: function (pm) {
      var v = __kag3_vid;
      var kag = this.kag;
      if (pm.storage) v.file = __kag3_vid_resolve(pm.storage);
      if (!v.file) {
        __kag3_log('playvideo: no file opened; skipped');
        kag.ftag.nextOrder();
        return;
      }
      var opt = { video: v.file, loop: v.loop, mode: 'normal', wait: 'false' };
      // layermode_movie prepends ./data/video/ itself, so pass a bare name.
      if (v.width) opt.width = v.width;
      if (v.height) opt.height = v.height;
      opt.top = v.top;
      opt.left = v.left;
      __kag3_log('playvideo ' + JSON.stringify(opt));
      __kag3_vid.playing = true;
      try {
        kag.ftag.startTag('layermode_movie', opt);
        __kag3_vid_fit();
      } catch (e) {
        __kag3_log('playvideo ERROR: ' + e);
        __kag3_vid.playing = false;
      }
      // KAG3 [playvideo] does not wait; [wv] does.
      kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['stopvideo'] = {
    start: function (pm) {
      __kag3_vid_stop();
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['clearvideolayer'] = {
    start: function (pm) {
      __kag3_vid_stop();
      this.kag.ftag.nextOrder();
    },
  };

  // [wv]: wait for the movie.  Before playback that means "loaded", after it
  // means "finished"; a build with no video (or an already finished one) must
  // not stall, so both fall through to nextOrder.
  tyrano.plugin.kag.tag['wv'] = {
    start: function (pm) {
      var v = __kag3_vid;
      var kag = this.kag;
      if (!v.playing) {
        kag.ftag.nextOrder();
        return;
      }
      var el = __kag3_vid_el().get(0);
      if (!el || el.ended) {
        v.playing = false;
        kag.ftag.nextOrder();
        return;
      }
      var done = false;
      var finish = function (why) {
        if (done) return;
        done = true;
        v.playing = false;
        __kag3_log('wv finished (' + why + ')');
        kag.ftag.nextOrder();
      };
      $(el).one('ended', function () { finish('ended'); });
      $(el).one('error', function () { finish('error'); });
      // A loop video never ends: honour canskip by letting a click through
      // instead of blocking the scenario forever.
      if (v.loop === 'true') {
        var le = kag.layer && kag.layer.layer_event;
        if (le) {
          try { le.show(); } catch (e) {}
          kag.on('click-event.wv', function () { finish('click'); });
        }
      }
    },
  };
"""

# KAG3 [wait canskip=true time=N] -> [kagwaitskip]: a timed wait that a
# click ends early. Tyrano [wait] hard-blocks clicks (weakly+strongly stop),
# so a custom tag is required. Design:
# - Registered into tyrano.plugin.kag.tag at script-parse time WITHOUT any
#   TYRANO.kag guard, exactly like the no-op shim tags: TYRANO.kag does not
#   exist at parse time, but ftag.init() copies every tag from
#   tyrano.plugin.kag.tag into master_tag during boot, making it callable.
# - The event layer must be shown, otherwise clicks never reach the handler
#   (Tyrano starts with it hidden; only waitClick() shows it).
# - We do NOT stop anything: the normal click handler advances the order
#   right after the click-event trigger, so the listener only disarms the
#   timer (never calls nextOrder itself, which would double-advance).
# - The listener mirrors the click handler's early-return checks (hidden
#   event layer, swipe consumption, hidden message, adding text, stop):
#   if the handler would bail, the timer stays armed so the wait still ends.
WAITSKIP_SHIM_JS = """\
  // KAG3 [wait canskip=true] -> [kagwaitskip]: timed wait ended early by
  // a click (Tyrano [wait] hard-blocks clicks for its whole duration).
  tyrano.plugin.kag.tag['kagwaitskip'] = {
    start: function (pm) {
      var kag = this.kag;
      var ms = parseInt(pm.time) || 1000;
      var finished = false;
      var on_click = function () {
        if (finished) return;
        // Mirror the click handler's early-return checks: if it would
        // bail, keep the timer armed so the wait still ends.
        try {
          var le = kag.layer && kag.layer.layer_event;
          if (!le || le.css('display') === 'none') return;
          if (kag.key_mouse && kag.key_mouse.is_swipe) return;
          if (kag.stat.is_hide_message || kag.stat.is_adding_text ||
              kag.stat.is_click_text || kag.stat.is_stop) return;
        } catch (e) { return; }
        if (finished) return;
        finished = true;
        clearTimeout(kag.tmp.wait_id);
        try { kag.off('click-event.kagwaitskip'); } catch (e) {}
      };
      // KAG3 shows a clickable area during canskip waits; Tyrano's
      // event layer starts hidden, so show it for the click to land.
      try { kag.layer.showEventLayer(); } catch (e) {}
      kag.tmp.wait_id = setTimeout(function () {
        if (finished) return;
        finished = true;
        try { kag.off('click-event.kagwaitskip'); } catch (e) {}
        kag.cancelStrongStop();
        kag.cancelWeakStop();
        kag.stat.is_wait = false;
        kag.ftag.nextOrder();
      }, ms);
      kag.on('click-event.kagwaitskip', on_click);
    },
  };
"""


# KAG3 clickable-map engine port (engine-level generic, from the KAG3
# GraphicLayer/ProvinceContext semantics):
# - [mapaction storage=X.ma layer=L] loads per-region actions (region number
#   = palette index of the province image "_p" file, sampled at the cursor)
# - [mapimage storage=X] loads the province image explicitly
# - [mapdisable layer=L] detaches the map
# - [image storage=X] auto-attaches X.ma + X_p.png when present (KAG3
#   loadImages behavior), and clears the layer's previous map
# - click: sample province pixel -> region action -> exp, then jump to
#   storage/target; map auto-disables after a click unless region 0 sets
#   autodisable=false
# - hover: onenter/onleave callbacks fire on region change
# The converter rewrites province images to grayscale (gray == palette
# index), so the runtime reads the R channel. .ma bodies are evaluated like
# KAG3 does (in a ProvinceContext-like object, f/sf/tf/kag in scope).
MAP_ENGINE_JS = """\
  // ---- KAG3 clickable maps: region actions, province images, hit test ----
  window.__kag3_maps = {};
  var __kag3_debug = function () {
    try { return window.localStorage.getItem('kag3debug') === '1'; } catch (e) { return false; }
  };
  var __kag3_log = function (msg) {
    try { if (__kag3_debug()) console.log('[kag3] ' + msg); } catch (e) {}
  };
  // KAG3 variable semantics: f/sf/tf/mp missing keys read as '' (KAG3
  // scripts universally test f.xxx=='' for unset values; Tyrano returns
  // undefined which fails those tests). Shared by the eval scopes and
  // the map action bodies.
  var __kag3_proxy = function (obj) {
    if (!obj) obj = {};
    return new Proxy(obj, {
      get: function (t, k) {
        var v = t[k];
        return v === undefined ? '' : v;
      },
      set: function (t, k, v) { t[k] = v; return true; },
    });
  };
  var __kag3_assets = function () { return window.__kag3_assets || {}; };
  var __kag3_assets_ma = function () { return window.__kag3_assets_ma || {}; };
  // Storage values resolved by the tag hook look like "../fgimage/x.png":
  // they are relative to the data/<folder>/ a tag prepends.  A consumer that
  // builds a URL itself (this shim, whose page is at the site root) must drop
  // the leading "../" or it escapes data/ entirely - measured: a bare
  // "../fgimage/TITLE.MA" was requested as "/fgimage/TITLE.MA" (404).
  var __kag3_data_url = function (rel) {
    return './data/' + String(rel == null ? '' : rel).replace(/^\\.\\.\\//, '');
  };
  var __kag3_fetch_text = function (rel) {
    if (!rel) return null;
    // `rel` is a canonical path ("fgimage/x.ma") since each asset lives in
    // exactly one place; the ../ form a tag would carry must be normalised
    // because THIS consumer builds the URL from the page root.
    var clean = String(rel).replace(/^\\.\\.\\//, '');
    var urls = [__kag3_data_url(clean)];
    if (clean.indexOf('/') < 0) {
      var folders = ['fgimage', 'bgimage', 'image', 'sound', 'bgm'];
      for (var i = 0; i < folders.length; i++) {
        urls.push('./data/' + folders[i] + '/' + clean);
      }
    }
    for (var u = 0; u < urls.length; u++) {
      try {
        var x = new XMLHttpRequest();
        x.open('GET', urls[u], false);
        x.send();
        if (x.status >= 200 && x.status < 400) return x.responseText;
      } catch (e) {}
    }
    return null;
  };
  var __kag3_ctx_fields = ['storage', 'target', 'onenter', 'onleave', 'hint',
                           'exp', 'cursor', 'countpage', 'autodisable'];
  var __kag3_run_body = function (body, ctx) {
    var kag = window.TYRANO && TYRANO.kag;
    if (!kag || !body) return;
    try {
      var TG = kag;
      var f = __kag3_proxy(kag.stat.f);
      var sf = __kag3_proxy(kag.variable.sf);
      var tf = __kag3_proxy(kag.variable.tf);
      var mp = __kag3_proxy(kag.stat.mp);
      // Pre-declare the province fields so `with` assigns into ctx: JS
      // `with` walks the scope chain when a property is absent and would
      // silently write globals (KAG3's incontextof always targets the
      // context object).
      for (var i = 0; i < __kag3_ctx_fields.length; i++) {
        ctx[__kag3_ctx_fields[i]] = undefined;
      }
      eval('with (ctx) { ' + String(body).replace(/\\bkag\\./g, 'TG.') + ' }');
    } catch (e) {}
  };
  var __kag3_parse_ma = function (text) {
    var actions = {};
    var lines = String(text).split(/\\r?\\n/);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line || line.charAt(0) === ';') continue;
      var colon = line.indexOf(':');
      if (colon < 0) continue;
      var n = parseInt(line.substring(0, colon).trim(), 10);
      if (isNaN(n)) continue;
      actions[n] = line.substring(colon + 1);
    }
    return actions;
  };
  var __kag3_query = function (map, n) {
    if (!map || !map.actions) return null;
    if (n === 0) return null;
    var raw = map.actions[n];
    if (raw === undefined) return null;
    var ctx = {};
    __kag3_run_body(raw, ctx);
    if (ctx.storage === undefined && ctx.target === undefined && ctx.onenter === undefined &&
        ctx.onleave === undefined && ctx.hint === undefined && ctx.exp === undefined &&
        ctx.cursor === undefined && ctx.countpage === undefined && ctx.autodisable === undefined) {
      return null;
    }
    return ctx;
  };
  var __kag3_query0 = function (map) {
    if (!map || !map.actions) return null;
    var raw = map.actions[0];
    if (raw === undefined) return null;
    var ctx = {};
    __kag3_run_body(raw, ctx);
    return ctx;
  };
  var __kag3_region_of = function (map, x, y) {
    if (!map || !map.regionCtx || !map.regionCanvas) return 0;
    if (x < 0 || y < 0 || x >= map.regionCanvas.width || y >= map.regionCanvas.height) return 0;
    var d = map.regionCtx.getImageData(x, y, 1, 1).data;
    return d[3] === 0 ? 0 : d[0];
  };
  var __kag3_layer_img_rect = function (kag, layerName, verbose) {
    try {
      var lay = kag.layer.getLayer(layerName, 'fore');
      if (!lay || !lay.length) lay = kag.layer.getLayer(layerName, 'back');
      if (!lay || !lay.length) {
        if (verbose) __kag3_log('map rect: layer div missing ' + layerName);
        return null;
      }
      var el = lay.find('img')[0];
      var r = null;
      if (el) {
        r = el.getBoundingClientRect();
      } else {
        // base layers render via CSS background-image, not <img>:
        // accept the layer div itself when it (or its back twin) carries
        // a background image
        var bg = lay.css('background-image');
        if (!bg || bg === 'none') {
          var b = kag.layer.getLayer(layerName, 'back');
          if (b && b.length) {
            var bbg = b.css('background-image');
            if (bbg && bbg !== 'none') {
              lay = b;
              bg = bbg;
            }
          }
        }
        if (!bg || bg === 'none') {
          if (verbose) {
            __kag3_log('map rect: no img nor background in ' + layerName);
          }
          return null;
        }
        r = lay[0].getBoundingClientRect();
      }
      if (r.width <= 0 || r.height <= 0) {
        if (verbose) __kag3_log('map rect: zero-size ' + layerName);
        return null;
      }
      return r;
    } catch (e) { return null; }
  };
  var __kag3_map_set = function (layerName, actions, maRel) {
    var map = window.__kag3_maps[layerName] = window.__kag3_maps[layerName] || {};
    map.actions = actions;
    map.maRel = maRel || '';
    if (map.pointing === undefined) map.pointing = -1;
    return map;
  };
  var __kag3_map_clear = function (layerName) {
    delete window.__kag3_maps[layerName];
  };
  var __kag3_region_load = function (map, rel) {
    if (!rel) return;
    var folders = ['fgimage', 'bgimage', 'image'];
    var idx = 0;
    var try_load = function () {
      if (idx >= folders.length) {
        __kag3_log('region image FAILED: ' + rel);
        return;
      }
      var img = new Image();
      img.onload = function () {
        var c = document.createElement('canvas');
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        var cx = c.getContext('2d');
        cx.drawImage(img, 0, 0);
        map.regionCanvas = c;
        map.regionCtx = cx;
        map.pointing = -1;
        __kag3_log('region image loaded: ' + rel + ' ' + c.width + 'x' + c.height);
      };
      img.onerror = function () { idx++; try_load(); };
      // canonical path first; the per-folder probes only matter for a bare
      // name.  A leading "../" must go: this URL is built from the page root,
      // so "../fgimage/x.png" would escape data/ (measured 404).
      var clean = String(rel).replace(/^\\.\\.\\//, '');
      img.src = clean.indexOf('/') >= 0
        ? __kag3_data_url(clean)
        : './data/' + folders[idx++] + '/' + clean;
    };
    try_load();
  };
  // Map keys are bare basenames ("title_p"), while a storage value may now be
  // a full canonical path ("fgimage/TITLE.MA") or the resolved
  // "../<dir>/<file>" form.  Every place that derives a key from a path must
  // go through this, or the lookup silently misses - measured: the title
  // menu's region image was never found ("hasRegionCanvas: false"), so the
  // buttons rendered but no click could be hit-tested.
  var __kag3_stem = function (name) {
    return String(name == null ? '' : name)
      .replace(/^\\.\\.\\//, '')
      .replace(/^.*[\\\\/]/, '')
      .replace(/\\.[^.]+$/, '')
      .toLowerCase();
  };
  var __kag3_resolve = function (name, map) {
    var s = String(name == null ? '' : name);
    if (!s) return null;
    var key = s.replace(/^\\.\\.\\//, '').toLowerCase();
    var r = map[key];
    if (!r) r = map[key.replace(/\\.[^.]+$/, '')];
    if (!r) r = map[__kag3_stem(key)];
    return r || null;
  };
  var __kag3_jump = function (kag, storage, target) {
    try {
      // KAG3 map jump = window.process -> loadScenario+goToLabel+run,
      // which discards any pending scenario wait ([s]/[l] parked state,
      // wt skip arm, weak/strong stop). Mirror that: clear wait state
      // before jumping so a stale [l] cannot eat the next click.
      try {
        if (kag.tmp && kag.tmp.__kag3_wt_skip) { kag.tmp.__kag3_wt_skip = null; }
        try { kag.off('click-event.kag3wtskip'); } catch (e2) {}
        try { kag.off('click-event.kagwaitskip'); } catch (e2) {}
        kag.cancelWeakStop();
        kag.cancelStrongStop();
        if (kag.stat) {
          kag.stat.is_stop = false;
          kag.stat.is_wait = false;
          kag.stat.is_click_text = false;
        }
        if (kag.tmp && kag.tmp.wait_id) { clearTimeout(kag.tmp.wait_id); kag.tmp.wait_id = null; }
      } catch (e1) {}
      kag.ftag.startTag('jump', { storage: String(storage || ''), target: String(target || '') });
    } catch (e) {}
  };
  var __kag3_target_is_ui = function (e) {
    var el = e && e.target ? e.target : null;
    while (el && el !== document) {
      if (el.classList &&
          (el.classList.contains('event-setting-element') ||
           el.classList.contains('layer_event_click') ||
           el.classList.contains('layer_menu') ||
           el.classList.contains('layer_free'))) {
        return true;
      }
      el = el.parentNode;
    }
    return false;
  };
  var __kag3_map_click = function (e) {
    var kag = window.TYRANO && TYRANO.kag;
    if (!kag || __kag3_target_is_ui(e)) return false;
    var names = Object.keys(window.__kag3_maps);
    names.sort(function (a, b) {
      var na = parseInt(a, 10), nb = parseInt(b, 10);
      if (!isNaN(na) && !isNaN(nb)) return nb - na;
      if (isNaN(na) && isNaN(nb)) return 0;
      return isNaN(na) ? -1 : 1;
    });
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      var map = window.__kag3_maps[name];
      if (!map || !map.actions) continue;
      var r = __kag3_layer_img_rect(kag, name, true);
      if (!r) continue;
      var w = map.regionCanvas ? map.regionCanvas.width : r.width;
      var h = map.regionCanvas ? map.regionCanvas.height : r.height;
      var x = Math.floor((e.clientX - r.left) * w / r.width);
      var y = Math.floor((e.clientY - r.top) * h / r.height);
      var n = __kag3_region_of(map, x, y);
      __kag3_log('map click ' + name + ' @' + e.clientX + ',' + e.clientY + ' -> px ' + x + ',' + y +
                 ' region=' + n + (map.regionCanvas ? '' : ' (no region canvas)'));
      var action = __kag3_query(map, n);
      if (!action) continue;
      if (action.exp !== undefined) __kag3_run_body(action.exp, {});
      if (action.storage || action.target) {
        __kag3_log('map jump ' + name + ' -> ' + action.storage + ' ' + action.target);
        var q0 = __kag3_query0(map);
        if (!q0 || q0.autodisable === undefined || String(q0.autodisable) !== 'false') {
          __kag3_map_clear(name);
        }
        __kag3_jump(kag, action.storage, action.target);
        // Only a real jump may swallow the click: stopping propagation
        // here blocks the event layer's click-event, which would stall
        // any pending [wt canskip] wait. exp/onenter-only regions must
        // leave the click flowing to the engine.
        return true;
      }
      __kag3_log('map region ' + name + ' region=' + n +
                 ' (no jump, click passes through)');
    }
    return false;
  };
  var __kag3_map_hover = function (e) {
    var kag = window.TYRANO && TYRANO.kag;
    if (!kag) return;
    for (var name in window.__kag3_maps) {
      var map = window.__kag3_maps[name];
      if (!map || !map.actions) continue;
      var r = __kag3_layer_img_rect(kag, name, false);
      if (!r) continue;
      var w = map.regionCanvas ? map.regionCanvas.width : r.width;
      var h = map.regionCanvas ? map.regionCanvas.height : r.height;
      var x = Math.floor((e.clientX - r.left) * w / r.width);
      var y = Math.floor((e.clientY - r.top) * h / r.height);
      var n = __kag3_region_of(map, x, y);
      if (n === map.pointing) continue;
      if (map.pointing !== -1) {
        var old = __kag3_query(map, map.pointing);
        if (old && old.onleave !== undefined) __kag3_run_body(old.onleave, {});
      }
      map.pointing = n;
      if (n !== 0) {
        var act = __kag3_query(map, n);
        if (act && act.onenter !== undefined) {
          __kag3_log('map hover ' + name + ' -> region ' + n + ' (onenter)');
          __kag3_run_body(act.onenter, {});
        }
      }
    }
  };
  var __kag3_hook_input = function () {
    if (window.__kag3_input_hooked) return;
    window.__kag3_input_hooked = true;
    document.addEventListener('click', function (e) {
      try {
        __kag3_log('map click event @' + e.clientX + ',' + e.clientY +
                   ' target=' + ((e.target && e.target.tagName) || '?') + '.' +
                   ((e.target && e.target.className && e.target.className.baseVal !== undefined
                     ? e.target.className.baseVal : e.target && e.target.className) || ''));
        if (__kag3_map_click(e)) e.stopPropagation();
      } catch (err) {
        __kag3_log('map click ERROR: ' + err);
      }
    }, true);
    document.addEventListener('mousemove', function (e) {
      try { __kag3_map_hover(e); } catch (err) { __kag3_log('map hover ERROR: ' + err); }
    }, true);
  };
  tyrano.plugin.kag.tag['mapaction'] = {
    start: function (pm) {
      var kag = this.kag;
      var layerName = String(pm.layer || 'base');
      var rel = __kag3_resolve(pm.storage, __kag3_assets_ma()) || String(pm.storage || '');
      var text = __kag3_fetch_text(rel);
      var actions = text === null ? {} : __kag3_parse_ma(text);
      var map = __kag3_map_set(layerName, actions, rel);
      var base = __kag3_stem(rel);
      var reg = __kag3_assets()[base + '_p'];
      __kag3_log('mapaction ' + layerName + ' <- ' + rel + ' (' + Object.keys(actions).length +
                 ' regions' + (reg ? ', region ' + reg : ', no region image') + ')');
      if (reg) __kag3_region_load(map, reg);
      __kag3_hook_input();
      kag.ftag.nextOrder();
    },
  };
  tyrano.plugin.kag.tag['mapimage'] = {
    start: function (pm) {
      var layerName = String(pm.layer || 'base');
      var map = window.__kag3_maps[layerName] || __kag3_map_set(layerName, {}, '');
      var rel = __kag3_resolve(pm.storage, __kag3_assets()) || String(pm.storage || '');
      __kag3_region_load(map, rel);
      __kag3_hook_input();
      this.kag.ftag.nextOrder();
    },
  };
  tyrano.plugin.kag.tag['mapdisable'] = {
    start: function (pm) {
      __kag3_map_clear(String(pm.layer || 'base'));
      this.kag.ftag.nextOrder();
    },
  };
"""


# Runtime patches that touch TYRANO.kag. kag is created at boot
# (tyrano.core.loadModule), not at script-parse time, so every block here
# used to silently skip when the shim first loaded -> the audio extension
# wrapper, the kag.n/historyLayer stubs and the undefined-tag tracker never
# applied (persistent bugs: "No codec support", "reading 'clear'"). The IIFE
# polls until kag.ftag.master_tag exists (set by ftag.init during boot), then
# applies every patch exactly once. Tag registrations (kagwaitskip, map
# engine, no-op shim) live outside this and are parse-time safe.
RUNTIME_SHIM_IIFE = "\n".join([
    "// KAG3 runtime shims for TyranoScript (generated by convert_kag.py)",
    "window.__missing_tags = window.__missing_tags || [];",
    "(function () {",
    WAITSKIP_SHIM_JS,
    VIDEO_SHIM_JS,
    "// KAG3 [s] -> [kag3stop]: pure stop. Registered at parse time like",
    "// kagwaitskip (boot copies tyrano.plugin.kag.tag into master_tag).",
    "// KAG3's [s] parks the scenario (inSleep=true, no click callback) and",
    "// the flow resumes only via window.process()/jump/links/maps; a plain",
    "// click must NOT advance it (dead-zone clicks on the title do nothing).",
    "// Strong stop + hidden event layer make Tyrano clicks inert; the map",
    "// engine's document-capture listener, [link] spans and [jump] all work",
    "// independently of the flow state.",
    "tyrano.plugin.kag.tag['kag3stop'] = {",
    "  start: function (pm) {",
    "    this.kag.weaklyStop();",
    "    this.kag.stronglyStop();",
    "    try { this.kag.layer.hideEventLayer(); } catch (e) {}",
    "  },",
    "};",
    "// KAG3 [ch text=\"...\"] renders text on the current message layer with",
    "// the current font settings (names, choice labels, menu items all use",
    "// it via macros). Tyrano's text tag does the same and calls nextOrder",
    "// itself when the typewriter finishes, so this shim must NOT advance.",
    "tyrano.plugin.kag.tag['ch'] = {",
    "  start: function (pm) {",
    "    var p = { val: pm.text === undefined ? '' : String(pm.text) };",
    "    if (pm.p !== undefined) p.p = pm.p;",
    "    if (pm.size !== undefined) p.size = pm.size;",
    "    if (pm.color !== undefined) p.color = pm.color;",
    "    if (pm.face !== undefined) p.face = pm.face;",
    "    this.kag.ftag.startTag('text', p);",
    "  },",
    "};",
    MAP_ENGINE_JS,
    "// KAG3 [rclick] right-click handler. KAG3 fires the registered jump on",
    "// right-click (comming/lineup screens, submenu back). Touch devices",
    "// have no right-click, so a left click that is NOT on an active map",
    "// region also triggers it while the flow is parked at [kag3stop].",
    "// Plain [rclick enabled=true] (no jump) is the system-menu default:",
    "// registered as null -> no-op (the port has no system menu overlay).",
    "var __kag3_rclick = null;",
    "var __kag3_exec_rclick = function () {",
    "  var kag = window.TYRANO && TYRANO.kag;",
    "  if (!kag || !__kag3_rclick) return;",
    "  var r = __kag3_rclick;",
    "  __kag3_rclick = null;",
    "  __kag3_log('rclick -> ' + r.storage + ' ' + r.target);",
    "  if (r.exp) { try { __kag3_run_body(r.exp, {}); } catch (e) {} }",
    "  if (r.storage || r.target) __kag3_jump(kag, r.storage, r.target);",
    "};",
    "tyrano.plugin.kag.tag['rclick'] = {",
    "  start: function (pm) {",
    "    var enabled = String(pm.enabled === undefined ? true : pm.enabled) === 'true';",
    "    var jump = String(pm.jump === undefined ? false : pm.jump) === 'true';",
    "    var has_tgt = String(pm.storage || '') || String(pm.target || '');",
    "    if (!enabled || (!jump && !has_tgt)) {",
    "      __kag3_rclick = null;",
    "    } else {",
    "      __kag3_rclick = { storage: pm.storage || '', target: pm.target || '', exp: pm.exp || '' };",
    "    }",
    "    this.kag.ftag.nextOrder();",
    "  },",
    "};",
    "document.addEventListener('contextmenu', function (e) {",
    "  if (!__kag3_rclick || __kag3_target_is_ui(e)) return;",
    "  e.preventDefault();",
    "  __kag3_exec_rclick();",
    "}, true);",
    "document.addEventListener('click', function (e) {",
    "  // touch fallback: only when no map is active (maps own their clicks)",
    "  if (!__kag3_rclick || __kag3_target_is_ui(e)) return;",
    "  if (Object.keys(window.__kag3_maps || {}).length > 0) return;",
    "  __kag3_exec_rclick();",
    "}, true);",
    "  var apply_runtime = function () {",
    "    var kag = window.TYRANO && TYRANO.kag;",
    "    if (!kag || !kag.ftag || !kag.ftag.master_tag) return false;",
    "    if (window.__kag3_runtime_applied) return true;",
    "    window.__kag3_runtime_applied = true;",
    "    try {",
    "      // KAG3 storage resolution: extensionless storages (bgm001,",
    "      // yuki_title, macro params like %bmp) resolve against the",
    "      // converted asset tree via the emitted __kag3_assets map (exact",
    "      // on-disk case, subdirectory paths). Tyrano never appends an",
    "      // extension, so resolve before the tag runs.",
    "      //",
    "      // Every asset now exists in exactly ONE place, so the resolved",
    "      // value is `../<canonical_dir>/<file>`: the browser normalises the",
    "      // dot segment (measured: ./data/image/../bgimage/x.png arrives as",
    "      // /data/bgimage/x.png), so any tag finds it whichever",
    "      // data/<folder>/ it prepends - including engine code that",
    "      // concatenates the folder by hand.",
    "      var __kag3_asset_path = function (s) {",
    "        if (!s) return s;",
    "        var t = String(s);",
    "        if (/[.]/.test(t) || t.indexOf('http') === 0 ||",
    "            t.charAt(0) === '/' || t.indexOf('../') === 0) return s;",
    "        var r = __kag3_assets()[t.toLowerCase()];",
    "        return r ? '../' + r : s;",
    "      };",
    "      var _resolve_storage = function (pm) {",
    "        if (!pm) return pm;",
    "        var s = pm.storage ? String(pm.storage) : '';",
    "        var r = __kag3_asset_path(s);",
    "        if (r !== s) {",
    "          pm.storage = r;",
    "          __kag3_log('storage ' + s + ' -> ' + r);",
    "        }",
    "        return pm;",
    "      };",
    "      // One hook on the dispatcher covers EVERY tag, including ones this",
    "      // build does not know about and macro-generated calls; a per-tag",
    "      // list would silently miss the next storage-bearing tag.",
    "      if (!kag.ftag.__kag3_dispatcher_hooked) {",
    "        kag.ftag.__kag3_dispatcher_hooked = true;",
    "        var _start_tag = kag.ftag.startTag;",
    "        kag.ftag.startTag = function (name, pm) {",
    "          try {",
    "            if (pm && typeof pm === 'object') {",
    "              pm = _resolve_storage(pm) || pm;",
    "              if (pm.graphic) {",
    "                var g = __kag3_asset_path(pm.graphic);",
    "                if (g !== pm.graphic) pm.graphic = g;",
    "              }",
    "            }",
    "          } catch (e) {}",
    "          return _start_tag.apply(this, arguments);",
    "        };",
    "      }",
    "      var _wrap_storage = function (tag) {",
    "        var t = kag.ftag.master_tag[tag];",
    "        if (!t || !t.start) return;",
    "        var orig = t.start;",
    "        t.start = function (pm) {",
    "          pm = _resolve_storage(pm) || pm;",
    "          return orig.call(this, pm);",
    "        };",
    "      };",
    "      // KAG3 loadImages semantics: ANY image load on a layer clears",
    "      // the layer's clickable map, then X.ma + X_p.png are auto-attached",
    "      // when present (GraphicLayer.tjs). [image]/[bg]/[bg2]/[graph] all",
    "      // go through loadImages. The map survives scenario jumps/process()",
    "      // (MainWindow.tjs process() never touches it) and is only removed",
    "      // by a new image on the same layer or an explicit [mapdisable].",
    "      ['image', 'bg', 'bg2', 'graph'].forEach(function (tag) {",
    "        var _img = kag.ftag.master_tag[tag];",
    "        if (!_img || !_img.start) return;",
    "        var _imgs = _img.start;",
    "        _img.start = function (pm) {",
    "          var layerName = String(pm.layer || 'base');",
    "          var before = String(pm.storage || '');",
    "          pm = _resolve_storage(pm) || pm;",
    "          __kag3_map_clear(layerName);",
    "          var base = __kag3_stem(pm.storage);",
    "          var maRel = __kag3_assets_ma()[base];",
    "          if (maRel) {",
    "            var text = __kag3_fetch_text(maRel);",
    "            var actions = text === null ? {} : __kag3_parse_ma(text);",
    "            var map = __kag3_map_set(layerName, actions, maRel);",
    "            var reg = __kag3_assets()[base + '_p'];",
    "            __kag3_log('imgload ' + tag + ' ' + before + ' -> ' + pm.storage + ' on ' + layerName +",
    "                       (maRel ? ' (auto-map ' + maRel + ', region ' + (reg || '-') + ')' : ''));",
    "            if (reg) __kag3_region_load(map, reg);",
    "            __kag3_hook_input();",
    "          } else {",
    "            __kag3_log('imgload ' + tag + ' ' + before + ' -> ' + pm.storage + ' on ' + layerName);",
    "          }",
    "          return _imgs.call(this, pm);",
    "        };",
    "      });",
    "      _wrap_storage('graph');",
    "      _wrap_storage('ptext');",
    "      _wrap_storage('chara_show');",
    "      _wrap_storage('chara_mod');",
    "      _wrap_storage('chara_ptext');",
    "      _wrap_storage('playse');",
    "      _wrap_storage('playbgm');",
    "      // NOTE: no jump/call/return/link wrappers clear clickable maps.",
    "      // KAG3 keeps the map alive across process()/jumps; scenarios",
    "      // disable it explicitly with [mapdisable] (e.g. the title's",
    "      // *game_start) or a new image load clears it (loadImages).",
    "      // KAG3 [button graphic=X] art lives in bgimage/fgimage (mirrored",
    "      // into image/ during conversion); Tyrano loads it from",
    "      // ./data/image/ without appending an extension, so resolve the",
    "      // extensionless graphic name through the asset map too.",
    "      var _btn = kag.ftag.master_tag && kag.ftag.master_tag.button;",
    "      if (_btn && _btn.start) {",
    "        var _btns = _btn.start;",
    "        _btn.start = function (pm) {",
    "          var g = pm && pm.graphic ? String(pm.graphic) : '';",
    "          if (g && !/[.]/.test(g) && g.indexOf('http') !== 0) {",
    "            var r = __kag3_assets()[g.toLowerCase()];",
    "            if (r) { __kag3_log('button graphic ' + g + ' -> ' + r); pm.graphic = r; }",
    "          }",
    "          // KAG3 '[current layer=messageN][locate x=0 y=0][button]'",
    "          // anchors the button at the message area origin; Tyrano puts",
    "          // free-layer buttons at locate (0,0) -> every system button",
    "          // stacked at the top-left corner. Anchor to the current",
    "          // message layer's outer frame when no explicit x/y is given.",
    "          // The outer is already portrait-remapped by the [position]",
    "          // wrapper, so anchored buttons must NOT be scaled again.",
    "          var _anchored = false;",
    "          if ((pm.x === undefined || pm.x === '') &&",
    "              (pm.y === undefined || pm.y === '')) {",
    "            var cl = this.kag.stat.current_layer;",
    "            if (cl && String(cl).indexOf('message') === 0) {",
    "              var _outer = this.kag.layer.getLayer(cl, this.kag.stat.current_page || 'fore').find('.message_outer');",
    "              var _ol = parseInt(_outer.css('left'), 10) || 0;",
    "              var _ot = parseInt(_outer.css('top'), 10) || 0;",
    "              var _lx = parseInt(this.kag.stat.locate.x, 10) || 0;",
    "              var _ly = parseInt(this.kag.stat.locate.y, 10) || 0;",
    "              pm.x = String(_ol + _lx);",
    "              pm.y = String(_ot + _ly);",
    "              _anchored = true;",
    "            }",
    "          }",
    "          if (window.__kag3_portrait && !_anchored) {",
    "            // explicit x/y live in the 1024x768 art space; the free",
    "            // layer is unscaled, so scale them to match the canvas",
    "            if (pm.x !== undefined && pm.x !== '') pm.x = String(Math.round(parseInt(pm.x, 10) * 0.75));",
    "            if (pm.y !== undefined && pm.y !== '') pm.y = String(Math.round(parseInt(pm.y, 10) * 0.75));",
    "          }",
    "          return _btns.call(this, pm);",
    "        };",
    "      }",
    "      // embScript (used by [if]/[button exp]/[emb]) has no TG in scope;",
    "      // expose it globally so the kag.->TG. rewrite works everywhere.",
    "      window.TG = kag;",
    "      // KAG3 [trans] may get layer=&sf.xxx which evaluates to undefined",
    "      // when the init script has not run; Tyrano requires a layer value.",
    "      var _tr = kag.ftag.master_tag && kag.ftag.master_tag.trans;",
    "      if (_tr && _tr.start) {",
    "        var _trs = _tr.start;",
    "        _tr.start = function (pm) {",
    "          if (pm && !pm.layer) pm.layer = 'base';",
    "          __kag3_log('trans ' + (pm && pm.layer) + ' ' + (pm && pm.method) + ' ' + (pm && pm.time));",
    "          return _trs.call(this, pm);",
    "        };",
    "      }",
    "      var _wt = kag.ftag.master_tag && kag.ftag.master_tag.wt;",
    "      if (_wt && _wt.start) {",
    "        var _wts = _wt.start;",
    "        _wt.start = function (pm) {",
    "          if (pm && String(pm.canskip) === 'true' && kag.stat.is_trans) {",
    "            // KAG3 [wt canskip=true]: a click skips the wait for the",
    "            // transition to finish. Disarmed on trans completion so",
    "            // the click never double-advances.",
    "            var done = false;",
    "            var finish = function () {",
    "              if (done) return;",
    "              done = true;",
    "              try { kag.off('click-event.kag3wtskip'); } catch (e) {}",
    "              kag.cancelWeakStop();",
    "              kag.ftag.nextOrder();",
    "            };",
    "            kag.on('click-event.kag3wtskip', finish);",
    "            kag.tmp.__kag3_wt_skip = finish;",
    "            // Tyrano hides the event layer on every nextOrder; without",
    "            // it the click never reaches j_event_layer and click-event",
    "            // never fires, so the skip never triggers.",
    "            try { kag.layer.showEventLayer(); } catch (e) {}",
    "            __kag3_log('wt canskip: click-skips armed');",
    "          }",
    "          return _wts.call(this, pm);",
    "        };",
    "      }",
    "      var _ct = kag.ftag && kag.ftag.completeTrans;",
    "      if (_ct) {",
    "        kag.ftag.completeTrans = function () {",
    "          __kag3_log('trans complete (is_stop=' + kag.stat.is_stop + ')');",
    "          if (kag.tmp && kag.tmp.__kag3_wt_skip) {",
    "            var _f = kag.tmp.__kag3_wt_skip;",
    "            kag.tmp.__kag3_wt_skip = null;",
    "            try { kag.off('click-event.kag3wtskip'); } catch (e) {}",
    "          }",
    "          return _ct.apply(this, arguments);",
    "        };",
    "      }",
    "      // KAG3 variable semantics: f/sf/tf/mp missing keys read as ''",
    "      // (KAG3 scripts universally test f.xxx=='' for unset values;",
    "      // Tyrano returns undefined which fails those tests - e.g. the",
    "      // FAID_IN_T macro's mp.sepia check would skip image loads).",
    "      // evalScript ([eval]/[iscript]) and embScript ([if]/[emb]/exp)",
    "      // both get proxied scopes; kag.->TG. rewriting is folded in.",
    "      // Portrait mode (--portrait): remap message windows from the",
    "      // 1024x768 art grid into the 768x1024 portrait canvas. Text",
    "      // windows (message0/1: dialogue, choices) scale x to 768 and",
    "      // shift y down into the bottom black area (image area is 768x576);",
    "      // other message layers (scene UI icons) ride the scaled art.",
    "      if (window.__kag3_portrait) {",
    "        var _pos = kag.ftag.master_tag && kag.ftag.master_tag.position;",
    "        if (_pos && _pos.start) {",
    "          var _poss = _pos.start;",
    "          _pos.start = function (pm) {",
    "            var lname = pm && pm.layer ? String(pm.layer) : '';",
    "            if (lname.indexOf('message') === 0 && pm.left !== '' && pm.top !== '') {",
    "              var L = parseInt(pm.left, 10) || 0;",
    "              var T = parseInt(pm.top, 10) || 0;",
    "              if (lname === 'message0' || lname === 'message1') {",
    "                pm.left = Math.round(L * 0.75);",
    "                if (pm.width !== '') pm.width = Math.round((parseInt(pm.width, 10) || 0) * 0.75);",
    "                pm.top = T + 256;",
    "                __kag3_log('portrait pos ' + lname + ' -> ' + pm.left + ',' + pm.top);",
    "              } else {",
    "                pm.left = Math.round(L * 0.75);",
    "                if (pm.width !== '') pm.width = Math.round((parseInt(pm.width, 10) || 0) * 0.75);",
    "                pm.top = Math.round(T * 0.75);",
    "                if (pm.height !== '') pm.height = Math.round((parseInt(pm.height, 10) || 0) * 0.75);",
    "              }",
    "            }",
    "            return _poss.call(this, pm);",
    "          };",
    "        }",
    "      }",
    "      if (kag.evalScript) {",
    "        kag.evalScript = (function (orig) {",
    "          return function (str) {",
    "            var TG = this;",
    "            var f = __kag3_proxy(this.stat.f);",
    "            var sf = __kag3_proxy(this.variable.sf);",
    "            var tf = __kag3_proxy(this.variable.tf);",
    "            var mp = __kag3_proxy(this.stat.mp);",
    "            try {",
    "              eval(String(str).replace(/\\bkag\\./g, 'TG.'));",
    "              this.saveSystemVariable();",
    "            } catch (e) {",
    "              console.error(e);",
    "              try { this.warning(e, true); } catch (e2) {}",
    "            }",
    "          };",
    "        })(kag.evalScript);",
    "      }",
    "      if (kag.embScript) {",
    "        kag.embScript = (function (orig) {",
    "          return function (str, preexp) {",
    "            var TG = this;",
    "            var f = __kag3_proxy(this.stat.f);",
    "            var sf = __kag3_proxy(this.variable.sf);",
    "            var tf = __kag3_proxy(this.variable.tf);",
    "            var mp = __kag3_proxy(this.stat.mp);",
    "            var src = String(str).replace(/\\bkag\\./g, 'TG.');",
    "            try {",
    "              return eval('(' + src + ')');",
    "            } catch (e) {",
    "              try { return eval(src); } catch (e2) { return undefined; }",
    "            }",
    "          };",
    "        })(kag.embScript);",
    "      }",
    "      // KAG3 runtime: kag.n / kag.historyLayer (scenario code calls",
    "      // kag.n.clear()), kag.se[] voice/sfx channels, runtime flags.",
    "      var _hl = {",
    "        clear: function () { return 0; },",
    "        output: function () { return 0; },",
    "      };",
    "      kag.historyLayer = kag.historyLayer || _hl;",
    "      kag.n = kag.n || _hl;",
    "      if (!kag.se) {",
    "        var _se = function (i) {",
    "          var ch = {",
    "            status: 'stop',",
    "            setOptions: function (o) { return this; },",
    "            play: function (o) { return this; },",
    "            stop: function () { return this; },",
    "            setVolume: function () { return this; },",
    "          };",
    "          return ch;",
    "        };",
    "        var _searr = [];",
    "        for (var _i = 0; _i < 8; _i++) { _searr[_i] = _se(_i); }",
    "        kag.se = _searr;",
    "      }",
    "      // KAG3 runtime flags read by iscript/eval",
    "      kag.autoMode = kag.autoMode || 0;",
    "      kag.clickWaiting = kag.clickWaiting || false;",
    "      kag.transCount = kag.transCount || 0;",
    "      kag.inStable = kag.inStable || 1;",
    "      kag.stat = kag.stat || {};",
    "      // KAG3 kag.process(storage, label): replace the current flow and",
    "      // run from the label (used by map onenter/onleave and iscript).",
    "      // Tyrano's nextOrderWithLabel strips a leading '*' itself.",
    "      if (!kag.process) {",
    "        kag.process = function (storage, target) {",
    "          __kag3_jump(kag, storage, target);",
    "        };",
    "      }",
    "      kag.callExtraConductor = kag.callExtraConductor || function () { return 0; };",
    "      // debug/UX hotkeys (KAG3 port niceties):",
    "      //   Ctrl+Enter  jump to the next [select] tag in the current",
    "      //               scenario (skip dialogue up to the next choice)",
    "      //   Ctrl+S      toggle Tyrano skip mode",
    "      if (!window.__kag3_hotkeys) {",
    "        window.__kag3_hotkeys = true;",
    "        document.addEventListener('keydown', function (e) {",
    "          var kag = window.TYRANO && TYRANO.kag;",
    "          if (!kag || !e.ctrlKey) return;",
    "          if (e.key === 'Enter') {",
    "            var arr = kag.ftag.array_tag || [];",
    "            for (var i = kag.ftag.current_order_index + 1; i < arr.length; i++) {",
    "              if (arr[i] && arr[i].name === 'select') {",
    "                kag.ftag.nextOrderWithIndex(i, kag.stat.current_scenario);",
    "                e.preventDefault();",
    "                __kag3_log('hotkey: jump to next choice at index ' + i);",
    "                return;",
    "              }",
    "            }",
    "          }",
    "          if (e.key === 's' || e.key === 'S') {",
    "            var on = !kag.stat.is_skip;",
    "            kag.setSkip(on, {});",
    "            __kag3_log('hotkey: skip ' + (on ? 'ON' : 'OFF'));",
    "            e.preventDefault();",
    "          }",
    "        });",
    "      }",
    "      // record unknown tags for debugging",
    "      if (kag.error) {",
    "        var orig = kag.error;",
    "        kag.error = function (type, tag) {",
    "          if (type === 'undefined_tag' && tag && tag.name) {",
    "            window.__missing_tags.push(tag.name);",
    "            var d = document.getElementById('__missing_tags');",
    "            if (!d) { d = document.createElement('div'); d.id = '__missing_tags'; d.style.display = 'none'; document.body.appendChild(d); }",
    "            d.textContent = window.__missing_tags.join(',');",
    "          }",
    "          return orig.apply(this, arguments);",
    "        };",
    "      }",
    "      return true;",
    "    } catch (e) {",
    "      window.__kag3_runtime_applied = false;",
    "      return false;",
    "    }",
    "  };",
    "  if (!apply_runtime()) {",
    "    var _t = setInterval(function () { if (apply_runtime()) clearInterval(_t); }, 200);",
    "  }",
    "})();",
])


# ---------------------------------------------------------------------------
# Scenario conversion
# ---------------------------------------------------------------------------

STORAGE_ATTR_RE = re.compile(r'(storage\s*=\s*)(?:"([^"]*)"|\'([^\']*)\'|([^\s>\]]+))')


def _wait_to_waitskip(m):
    """Rewrite [wait ...] -> [kagwaitskip time=N] where clickable.

    KAG3 [wait canskip=true time=N] is a timed wait skippable by click, and
    plain [wait time=N] reads as canskip-less in KAG3 but players expect to
    click through dialogue pauses anyway; only explicit canskip=false keeps
    the native hard wait. Dynamic (&f.x) or missing times stay native.
    """
    tag = m.group(0)
    if re.search(r'\bcanskip\s*=\s*"?false"?', tag):
        return tag
    t = re.search(r'\btime\s*=\s*([0-9]+)', tag)
    if t:
        return '[kagwaitskip time=%s]' % t.group(1)
    return tag


def _dangling_call(m, unpacked):
    """Replace a [call]/[jump storage=..] whose target .ks is missing from
    the unpacked tree with an inert [er]; keep it otherwise."""
    storage = m.group(2)
    if not storage.endswith(".ks"):
        return m.group(0)
    base = os.path.join(unpacked, "scenario", storage)
    if os.path.isfile(base):
        return m.group(0)
    if os.path.isfile(os.path.join(unpacked, storage)):
        return m.group(0)
    return "[er]"


def _asset_map(unpacked):
    """Build {lower_basename: out_relpath} for the whole asset tree.

    out_relpath is the asset's ONE canonical location, including its directory
    (`bgimage/telop1.png`).  It accounts for format conversion (tlg/bmp ->
    png), directory moves (rule -> fgimage) and subdirectories
    (fgimage/select/x -> fgimage/select/x).

    The directory is part of the value because each asset is written exactly
    once: the runtime resolves names to `../<dir>/<file>`, which works from
    any tag's folder because browsers normalise dot segments in URLs
    (measured: `./data/fgimage/../bgimage/x.png` arrives as
    `/data/bgimage/x.png`).  Writing a copy into every directory a tag might
    look in tripled the build and ~75% of that survived compression.

    Image extensions win over same-named non-images (map01_01.bmp + the
    map01_01.ma action file share the basename: the image must win).
    """
    mapping = {
        "bgimage": "bgimage",
        "fgimage": "fgimage",
        "image": "image",
        "bgm": "bgm",
        "sound": "sound",
        "video": "video",
        "rule": "fgimage",
    }
    img_exts = ("png", "jpg", "jpeg", "gif", "bmp", "tlg", "webp")
    amap = {}
    full = {}

    def _scan(src_sub, parts=(), want_img=None):
        d = os.path.join(unpacked, src_sub, *parts)
        if not os.path.isdir(d):
            return
        for fn in sorted(os.listdir(d)):
            sp = os.path.join(d, fn)
            if os.path.isdir(sp):
                _scan(src_sub, parts + (fn,), want_img)
                continue
            base = fn.rsplit(".", 1)[0].lower() if "." in fn else fn.lower()
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if want_img is not None and (ext in img_exts) != want_img:
                continue
            # Storage keys are always slash-separated: they end up inside
            # generated TyranoScript/HTML references, so they must not follow
            # the host OS separator (a Windows build would emit "select\\x.png").
            name = base + ".png" if ext in ("tlg", "bmp") else fn
            out = "/".join((mapping[src_sub],) + tuple(parts) + (name,))
            full.setdefault(base + "." + ext, out)
            amap.setdefault(base, out)

    # two passes: images first so a same-named .ma (map01_01.ma vs the
    # map01_01 image) never shadows the image for extensionless storages
    for src_sub in mapping:
        _scan(src_sub, (), want_img=True)
    for src_sub in mapping:
        _scan(src_sub, (), want_img=False)
    return amap, full


def _asset_map_full(unpacked):
    """{lower_basename_with_ext: out_relpath} for every asset (no preference)."""
    return _asset_map(unpacked)[1]


_ASSET_CACHE = {}


def _layer_map(unpacked):
    """Parse sf.lay_xxx = N assignments from laynumber_init.ks (layer ids)."""
    lm = {}
    p = os.path.join(unpacked, "scenario", "laynumber_init.ks")
    if not os.path.isfile(p):
        return lm
    raw = open(p, "rb").read()
    try:
        txt = raw.decode(detect_encoding(raw), errors="replace")
    except (UnicodeDecodeError, LookupError):
        # errors="replace" already suppresses decode errors; this guards the
        # theoretical unknown-codec / truncated-input cases only.
        return lm
    for m in re.finditer(r'sf\.(lay_[a-z0-9_]+)\s*=\s*(\d+)', txt):
        lm[m.group(1)] = m.group(2)
    return lm


def _find_asset(unpacked, name):
    """Resolve a storage= value against the asset tree.

    Handles extensionless names (black -> BLACK.PNG / black.png after
    conversion), names whose source extension changed during conversion
    (telop1.bmp -> telop1.png) and exact names with extension (title.ma ->
    TITLE.MA, preserving on-disk case).

    Returns `../<dir>/<file>`: a path relative to whatever `data/<folder>/`
    the receiving tag will prepend, so it hits the asset's single canonical
    location no matter which tag asks.  The browser normalises the dot
    segment (measured), so even engine code that concatenates the folder by
    hand lands on the right URL.
    """
    if not name or "/" in name or "\\" in name:
        return name
    key = unpacked
    if key not in _ASSET_CACHE:
        _ASSET_CACHE[key] = _asset_map(unpacked)
    amap, full = _ASSET_CACHE[key]
    base = name.lower()
    if base in full:
        return "../" + full[base]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    hit = amap.get(stem)
    return "../" + hit if hit else name


def _convert_exp(exp):
    """Minimal TJS2 -> JS expression adjustments.

    Most KAG3 expressions (f./sf./tf. member access, comparisons,
    && / || / !) are already valid JS. Handle the known divergences:
    - TJS `!==`/`===` are already JS.
    - `&&`/`||` are already JS.
    - TJS `++`/`--` work in JS.
    - `kag.` runtime object references are left as-is (may be undefined
      in shim context, guarded by callers).
    """
    return exp


def _strip_continuation(line, in_script):
    """Remove KAG3 line-continuation backslashes (trailing '\').

    In KAG3 a trailing backslash joins the line to the next one; TyranoScript
    has no such syntax and treats '\' as an escape char, injecting stray
    newlines into the message layer. Inside [iscript] blocks the backslash
    is code and must be kept.
    """
    if in_script:
        return line
    s = line.rstrip("\r\n")
    if s.endswith("\\") and not s.endswith("\\\\"):
        return s[:-1] + line[len(s):]
    return line


def convert_ks_line(line, unpacked, macros, in_script=False):
    """Convert one .ks source line to TyranoScript. Returns new line or None
    to drop the line."""
    line = _strip_continuation(line, in_script)
    s = line.strip()
    if in_script:
        # inside [iscript]: TJS2 -> JS. KAG-plugin classes that cannot be
        # ported (ZoomRot etc. extend KAGPlugin / touch KAG runtime layers)
        # are dropped: their [if exp=...]@iscript guards already keep them
        # out of the critical path, but the TJS syntax would still break
        # the JS eval.
        for drop_marker in ("extends KAGPlugin", "class ZoomRotPlugin"):
            if drop_marker in line:
                return "; // dropped: " + line.strip() + "\n"
        return tjs2js.convert_iscript(line)


    if not s:
        return line
    if s.startswith(";"):
        return line
    if s.startswith("/*"):
        return line
    # labels: *name or *name|chapter (KAG3 also uses *name|chapter)
    if s.startswith("*"):
        return line
    if s.startswith("@"):
        # @tag syntax -> [tag]
        return "[" + s[1:] + "]"
    # bare text line: keep
    if not s.startswith("["):
        return line
    # tag line: rewrite storage= attributes to include extensions for
    # ASSET tags only ([image]/[bg]/[playse]/[playbgm]/[movie]/...). KAG3
    # storage="X.ks" on [call]/[jump] must stay untouched (they are scenario
    # files, and asset-name collision would corrupt the jump target).
    first_tag = re.match(r'^\[([a-z0-9_]+)', s, re.I)
    tag_name = first_tag.group(1).lower() if first_tag else ""
    if tag_name in ("image", "bg", "bg2", "playse", "playbgm", "movie",
                    "bgmovie", "graph", "ptext", "chara_show", "chara_mod",
                    "chara_ptext", "button", "glink", "preload",
                    "mapaction", "mapimage"):
        line = STORAGE_ATTR_RE.sub(
            lambda m: m.group(1) + '"' + _find_asset(unpacked, m.group(2) or m.group(3) or m.group(4) or "") + '"',
            line,
        )
    line = re.sub(
        r'(exp|cond)\s*=\s*"([^"]*)"',
        lambda m: '%s="%s"' % (m.group(1), tjs2js.convert_expr(m.group(2))),
        line,
    )
    # KAG3 defaults vs Tyrano vital params: [trans] needs layer (KAG3
    # defaults to base; Tyrano requires it explicitly)
    line = re.sub(
        r'\[trans(?![^\]]*\blayer\s*=)',
        '[trans layer=base',
        line,
    )
    # KAG3 transition methods with no Tyrano/animate.css equivalent
    # (universal/wave/ripple/mosaic) would leave is_trans=true forever:
    # no CSS animation runs, animationend never fires, completeTrans
    # never runs and the following [wt] weak-stop hangs. Map to real
    # animate.css methods (engine-level, applies to any KAG3 game).
    _TRANS_METHODS = {
        "universal": "fadeIn",
        "wave": "fadeIn",
        "ripple": "fadeIn",
        "mosaic": "fadeIn",
        "turn": "flipInX",
        "scroll": "slideInUp",
    }
    line = re.sub(
        r'\[trans\b([^\]]*\bmethod\s*=\s*)(["\']?)([a-zA-Z_0-9]+)\2',
        lambda m: '[trans%s%s%s%s' % (m.group(1), m.group(2),
                                      _TRANS_METHODS.get(m.group(3).lower(), m.group(3)),
                                      m.group(2)),
        line,
    )
    # KAG3 [s] = pure stop (inSleep, no click callback, scenario ends;
    # MainWindow.tjs 's' handler returns -1). The flow is resumed ONLY by
    # window.process()/jump (clickable maps, [link] choices, rclick) or a
    # new scenario load. Tyrano's [l] would let dead-zone clicks advance
    # the flow, so [s] maps to [kag3stop] (see runtime shim).
    line = re.sub(r'^\[s\](\s*)$', lambda m: '[kag3stop]' + m.group(1), line)
    # KAG3 [wait canskip=true time=N] = timed wait skippable by click;
    # Tyrano [wait] hard-blocks clicks for the whole duration -> map to
    # [kagwaitskip] (click-skippable wait defined in the runtime shim).
    # Plain [wait time=N] is also made clickable (players expect to click
    # through dialogue pauses); only explicit canskip=false keeps the
    # native hard wait.
    line = re.sub(
        r'\[wait\b[^\]]*\]',
        _wait_to_waitskip,
        line,
    )
    # dynamic layer references layer=&sf.lay_xxx -> static value from
    # laynumber_init.ks (Tyrano cannot eval them in tag params reliably)
    lm = _layer_map(unpacked)
    if lm:
        line = re.sub(
            r'layer\s*=\s*&sf\.(lay_[a-z0-9_]+)',
            lambda m: 'layer=%s' % lm.get(m.group(1), "base"),
            line,
        )
    # `global` (KAG runtime global) is undefined in Tyrano: neutralize
    # typeof(global.x) guards so they evaluate false instead of throwing
    line = line.replace('typeof(global.', 'typeof(window.')
    line = line.replace('global.', 'window.')
    # dangling [call storage="x.ks"] / [jump storage="x.ks"] where the
    # scenario file does not exist in the source tree: replace with [er]
    # (the original game references missing files; Tyrano would 404)
    line = re.sub(
        r'\[(call|jump)\b[^]]*storage\s*=\s*"([^"]+)"[^]]*\]',
        lambda m: _dangling_call(m, unpacked),
        line,
    )
    tags = _scan_tags(line)
    if len(tags) > 1:
        parts = ["[" + t + "]" for t in tags]
        return "\n".join(re.sub(r'^\[s\](\s*)$', lambda m: '[kag3stop]' + m.group(1), p) for p in parts) + "\n"
    return re.sub(r'^\[s\](\s*)$', lambda m: '[kag3stop]' + m.group(1), line)


def _scan_tags(text):
    """Bracket-pairing tag scan (same semantics as Tyrano's parser):
    returns the inner text of each top-level [tag ...]."""
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "[":
            depth, j = 0, i
            while j < n:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                    if depth == 0:
                        out.append(text[i + 1:j])
                        i = j + 1
                        break
                j += 1
            else:
                break
        else:
            i += 1
    return out


def _scan_tags(text):
    """Bracket-pairing tag scan (same semantics as Tyrano's parser):
    returns the inner text of each top-level [tag ...]."""
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "[":
            depth, j = 0, i
            while j < n:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                    if depth == 0:
                        out.append(text[i + 1:j])
                        i = j + 1
                        break
                j += 1
            else:
                break
        else:
            i += 1
    return out


def _export_globals(js_text):
    """Append window.X = X exports for top-level var/function declarations.

    KAG3 iscript blocks define data containers (anlist, seen_list, ...) as
    top-level `var x = ...`, but TyranoScript executes [iscript] and [eval]
    in separate eval scopes: a `var` in one eval is invisible in the other.
    Re-declaring the top-level names on `window` makes them reachable from
    [eval] expressions (embScript resolves unqualified names through the
    scope chain up to the global object).
    """
    names = []
    depth = 0
    for line in js_text.splitlines():
        m = re.match(r"^\s*var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and depth == 0 and m.group(1) not in names:
            names.append(m.group(1))
        m = re.match(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{", line)
        if m and depth == 0 and m.group(1) not in names:
            names.append(m.group(1))
        depth += line.count("{") - line.count("}")
    if not names:
        return js_text
    export = "\n".join("window.%s = %s;" % (n, n) for n in names)
    return js_text.rstrip("\n") + "\n" + export + "\n"


def _balance_if_endif(lines):
    """Repair if/endif imbalance for TyranoScript's strict deep_if check.

    KAG3 tolerates unbalanced [if]/[endif]: a missing [endif] simply ends
    when the enclosing [macro] block ends, and stray [endif]s are ignored
    by the engine. TyranoScript counts depth per file and errors on any
    mismatch. Strategy:

    - track depth per [macro]...[endmacro] block (macro bodies must be
      self-balanced), skipping [iscript]...[endscript] bodies (their
      content is JS, not tags);
    - an [endif] that would take depth below 0 is replaced by an
      always-true [if] so the file-level depth stays balanced;
    - a macro body that ends with depth > 0 gets matching [endif] lines
      injected just before [endmacro];
    - the file tail gets matching [endif] lines for leftover depth.
    """
    depth = 0
    out = []
    in_script = False
    pending = []

    def inject():
        nonlocal depth
        for _ in range(max(depth, 0)):
            out.append("[endif]\n")
        depth = 0
        pending.clear()

    for ln in lines:
        s = ln.strip()
        if in_script:
            out.append(ln)
            if s.startswith("[endscript") or s.startswith("@endscript"):
                in_script = False
            continue
        if s.startswith("[iscript") or s.startswith("@iscript"):
            in_script = True
            out.append(ln)
            continue
        m_endmacro = re.match(r'^\[endmacro\](\s*)$', s)
        if m_endmacro and depth > 0:
            inject()
        if s.startswith("["):
            tags = []
            i, n = 0, len(s)
            while i < n:
                if s[i] == "[":
                    db, j = 0, i
                    while j < n:
                        if s[j] == "[":
                            db += 1
                        elif s[j] == "]":
                            db -= 1
                            if db == 0:
                                tags.append((i, j + 1, s[i + 1:j]))
                                i = j + 1
                                break
                        j += 1
                    else:
                        break
                else:
                    i += 1
            rebuilt = ""
            pos = 0
            changed = False
            for (a, b, inner) in tags:
                name = inner.split()[0].lower() if inner.split() else ""
                if name == "endif" and depth <= 0:
                    # stray [endif]: drop it entirely (KAG3 artifact; Tyrano
                    # would underflow its deep_if counter). [er] is a harmless
                    # message-layer clear and leaves if-depth alone.
                    rebuilt += s[pos:a] + "[er]"
                    pos = b
                    changed = True
                    continue
                if name == "if":
                    depth += 1
                elif name == "endif":
                    depth -= 1
                rebuilt += s[pos:b]
                pos = b
            rebuilt += s[pos:]
            out.append(rebuilt if changed else ln)
        else:
            out.append(ln)
        if re.match(r'^\[macro\b', s):
            pending = []
    if depth > 0:
        inject()
    return out



def convert_scenario_file(src_path, unpacked, out_path, macros, stats):
    # .jsfix override: hand-rewritten JS version produced by a subagent
    # (or manual fix) takes priority over automatic TJS2->JS conversion.
    fix_path = src_path + ".jsfix"
    if os.path.isfile(fix_path):
        with open(fix_path, "r", encoding="utf-8") as f:
            data = f.read()
        # export top-level iscript declarations to window (same as the
        # auto-conversion path) so [eval] can reach them
        data = re.sub(
            r"(\[iscript\])(.*?)(\[endscript\])",
            lambda m: m.group(1) + _export_globals(m.group(2)) + m.group(3),
            data,
            flags=re.S,
        )
        # apply the same line-level tag fixes to the jsfix body
        data = "\n".join(
            re.sub(r'^\[s\](\s*)$', lambda m: '[kag3stop]' + m.group(1), ln)
            for ln in data.splitlines()
        )
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(data)
        stats["files"] += 1
        stats["lines"] += len(data.splitlines())
        stats["jsfix"] += 1
        return "utf-8"
    raw = open(src_path, "rb").read()
    """Convert one .ks file (encoding detect + storage rewrite + UTF-8 out)."""
    raw = open(src_path, "rb").read()
    enc = detect_encoding(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except (UnicodeDecodeError, LookupError):
        text = raw.decode("utf-8", errors="replace")
    out_lines = []
    dropped = 0
    in_script = False
    drop_script = os.path.basename(src_path).lower() in SYSTEM_ISCRIPT_DROP
    script_buf = []
    for ln in text.splitlines(keepends=True):
        s = ln.strip()
        if in_script:
            if s.startswith("[endscript") or s.startswith("@endscript"):
                # end of block: convert the whole block at once (classes
                # and multi-line constructs need the full body)
                if drop_script:
                    out_lines.extend("; // degraded (system iscript): " + b.rstrip("\n") + "\n"
                                      for b in script_buf)
                else:
                    body = tjs2js.convert_iscript("".join(script_buf))
                    # Tyrano's evalScript scope exposes TG (=kag), f/sf/tf/mp
                    # but not `kag`; KAG3 iscript uses kag.* heavily.
                    body = "var kag = TG;\n" + body
                    out_lines.append(_export_globals(body))
                out_lines.append(_strip_continuation(ln, False))
                in_script = False
                script_buf = []
            else:
                script_buf.append(ln)
            continue
        if s.startswith("[iscript") or s.startswith("@iscript"):
            in_script = True
            script_buf = []
            out_lines.append(_strip_continuation(ln, False))
            continue
        nl = convert_ks_line(ln, unpacked, macros, False)
        if nl is None:
            dropped += 1
            continue
        out_lines.append(nl)
    out_lines = _balance_if_endif(out_lines)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(out_lines)
    stats["files"] += 1
    stats["lines"] += len(out_lines)
    return enc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _copy_tree(src, dst, ignore_exts=()):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in files:
            if any(f.lower().endswith(e) for e in ignore_exts):
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(target, f))


def _inject_font(out, font_path, family, log):
    """Install a CJK font into the Tyrano project as the default text face.

    - copies the font file to tyrano/fonts/
    - appends an @font-face to tyrano/css/font.css (../fonts/ resolves there)
    - prepends the family to Config.tjs `;userFace =` so text without an
      explicit face="" uses it (scene text faces are untouched)
    """
    base = os.path.basename(font_path)
    fonts_dir = os.path.join(out, "tyrano", "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    shutil.copy2(font_path, os.path.join(fonts_dir, base))

    css_path = os.path.join(out, "tyrano", "css", "font.css")
    if os.path.isfile(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()
        face = ('@font-face {\n'
                '    font-family: "%s";\n'
                '    src: url("../fonts/%s") format("opentype");\n'
                '    font-weight: normal;\n'
                '    font-style: normal;\n'
                '}\n') % (family, base)
        if face not in css:
            with open(css_path, "a", encoding="utf-8") as f:
                f.write("\n" + face)
            log.info("font.css: appended @font-face %s", family)

    cfg_path = os.path.join(out, "data", "system", "Config.tjs")
    if os.path.isfile(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = f.read()
        m = re.search(r'(?m)^;userFace\s*=\s*(.*?);\s*$', cfg)
        if m and ('"%s"' % family) not in m.group(1):
            new = ';userFace = "%s", %s;' % (family, m.group(1).strip())
            cfg = cfg[:m.start()] + new + cfg[m.end():]
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(cfg)
            log.info("Config.tjs: userFace prepended %s", family)


# Portrait layout (--portrait): the game renders on a 768x1024 canvas.
# The KAG3 art grid is 1024x768, so every game layer is kept at that size
# and the whole game area is scaled by 0.75 to occupy the top 768x576 of
# the canvas; the message text is remapped into the bottom black area
# (y >= 576) by the [position] wrapper in the runtime shim.
PORTRAIT_CSS = """
/* ---- portrait layout (generated by convert_kag.py --portrait) ---- */
/* keep every game layer on the original 1024x768 art grid */
#root_layer_game .layer,
#root_layer_system .layer_fore[class*="message"],
#root_layer_system .layer_back[class*="message"] {
    width: 1024px !important;
    height: 768px !important;
}
/* scale the art to the top 768x576 of the 768x1024 portrait canvas */
#root_layer_game {
    position: absolute;
    top: 0;
    left: 0;
    transform: scale(0.75);
    transform-origin: top left;
}
"""


def _inject_portrait(out, log):
    """Append the portrait layout CSS to the engine's tyrano.css."""
    css_path = os.path.join(out, "tyrano", "css", "tyrano.css")
    if not os.path.isfile(css_path):
        css_path = os.path.join(out, "tyrano", "tyrano.css")
    if not os.path.isfile(css_path):
        log.warning("tyrano.css not found; portrait CSS not applied")
        return
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    if "portrait layout (generated" in css:
        return
    with open(css_path, "a", encoding="utf-8") as f:
        f.write("\n" + PORTRAIT_CSS)
    log.info("tyrano.css: portrait layout appended")


def _is_region_image(fn):
    """True for clickable-map province images (main_name + _p + image ext).

    KAG3 maps use a palette-indexed "province image" next to the main image
    (map_p.png); the palette index of a pixel is the region number.
    """
    lower = fn.lower()
    return lower.endswith(("_p.png", "_p.bmp", "_p.tlg", "_p.jpg"))


def _convert_region_image(src, dst, stats):
    """Rewrite a province image as a grayscale PNG where gray = palette index.

    Browsers render indexed PNGs to RGBA (palette colors), losing the index;
    converting so that pixel gray == palette index lets the runtime read the
    region number straight from the R channel. Non-indexed sources keep their
    R channel (best effort; such images are broken maps anyway).
    """
    try:
        from PIL import Image
        im = Image.open(src)
        if im.mode == "P":
            raw = im.tobytes()
            out = Image.frombytes("L", im.size, raw)
            out.save(dst, "PNG")
        elif im.mode in ("L", "I"):
            im.convert("L").save(dst, "PNG")
        else:
            im.convert("RGB").save(dst, "PNG")
        stats["region"] += 1
    except Exception as e:
        # Per-image best-effort fallback: PIL open/convert/save on arbitrary
        # game assets can raise OSError/ValueError/KeyError/DecompressionBomb-
        # Error etc. - not enumerable, so a failure just counts and continues.
        log.warning("region convert failed %s: %s", os.path.relpath(src), e)
        stats["region_fail"] += 1


def _convert_videos(unpacked, out_data, video_dir, stats):
    """Collect movies from anywhere in the unpacked tree into data/video/.

    KAG3 games keep .wmv/.mpg under `others/`, which is not an image dir, so
    a directory-driven copy misses them entirely.  Browsers cannot play WMV,
    so each file is replaced by a WebM produced beforehand by
    `transcode_video.py` (found via `video_dir`, defaulting to
    `<unpacked>/_video_webm`, or next to the source).  A movie with no WebM
    available is copied as-is and WARNed about: it is better to ship a file
    the browser refuses than to silently drop a scene's video.

    Returns {name_lower: "<stem>.webm"} for the runtime resolver, keyed both
    by the original name with and without extension so an extensionless
    `[openvideo storage=X]` lookup works.
    """
    exts = (".wmv", ".mpg", ".mpeg", ".avi")
    found = []
    for dp, dirnames, fns in os.walk(unpacked):
        dirnames[:] = [d for d in dirnames if d not in ("_video_webm",)]
        for fn in fns:
            if fn.lower().endswith(exts):
                found.append(os.path.join(dp, fn))
    if not found:
        return {}

    out_dir = os.path.join(out_data, "video")
    os.makedirs(out_dir, exist_ok=True)
    vmap = {}
    for src in sorted(found):
        stem = os.path.splitext(os.path.basename(src))[0]
        webm = None
        for cand in (os.path.join(video_dir, stem + ".webm") if video_dir else None,
                     os.path.join(os.path.dirname(src), stem + ".webm"),
                     os.path.splitext(src)[0] + ".webm"):
            if cand and os.path.isfile(cand):
                webm = cand
                break
        if webm:
            shutil.copy2(webm, os.path.join(out_dir, stem + ".webm"))
            vmap[stem.lower()] = stem + ".webm"
            vmap[os.path.basename(src).lower()] = stem + ".webm"
            stats["video"] += 1
        else:
            shutil.copy2(src, os.path.join(out_dir, os.path.basename(src)))
            vmap[stem.lower()] = os.path.basename(src)
            vmap[os.path.basename(src).lower()] = os.path.basename(src)
            stats["video_raw"] += 1
            log.warning("video %s has no WebM counterpart (looked in %s) - "
                        "copied as-is; browsers cannot play %s",
                        os.path.relpath(src, unpacked), video_dir or "-",
                        os.path.splitext(src)[1])
    log.info("videos: %d -> %s (+%d raw)", stats["video"], out_dir,
             stats["video_raw"])
    return vmap


def _convert_assets(unpacked, out_data, stats):
    """Copy/convert asset dirs into Tyrano data/ layout (recursive)."""
    mapping = [
        ("bgimage", "bgimage"),
        ("fgimage", "fgimage"),
        ("image", "image"),
        ("bgm", "bgm"),
        ("sound", "sound"),
        ("video", "video"),
        ("rule", "fgimage"),
    ]
    for src_sub, dst_sub in mapping:
        src_dir = os.path.join(unpacked, src_sub)
        if not os.path.isdir(src_dir):
            continue
        # One copy per asset: every asset goes to its canonical directory and
        # nowhere else.  The runtime resolves names to `../<dir>/<file>`, and
        # the browser normalises the dot segment, so a tag that would have
        # looked in a different directory still finds it.  The old mirroring
        # (bgimage/fgimage/image copies of everything) tripled the build for
        # no benefit - measured: ~75% of the duplicated bytes survive
        # compression, so the redundancy was real delivery size.

        def _convert_one(src_path, rel, outname, fn):
            dst_base = os.path.join(out_data, dst_sub, rel)
            if outname != fn:
                dst_path = os.path.join(os.path.dirname(dst_base), outname)
            else:
                dst_path = dst_base
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext == "tlg":
                _convert_tlg(src_path, dst_path, stats)
            elif ext == "bmp":
                _convert_bmp(src_path, dst_path, stats)
            elif _is_region_image(fn):
                _convert_region_image(src_path, dst_path, stats)
            else:
                shutil.copy2(src_path, dst_path)
                stats["copied"] += 1

        def _walk(cur, sub):
            for fn in sorted(os.listdir(cur)):
                sp = os.path.join(cur, fn)
                rel = os.path.join(sub, fn) if sub else fn
                if os.path.isdir(sp):
                    _walk(sp, rel)
                    continue
                ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                outname = fn
                if ext in ("tlg", "bmp"):
                    outname = fn.rsplit(".", 1)[0] + ".png"
                _convert_one(sp, rel, outname, fn)

        _walk(src_dir, "")


def _decoder_mtime():
    """Newest mtime among the code that decides what a converted image looks
    like.  A cache that only compares source vs target timestamps cannot see a
    decoder fix, so a corrected decoder would silently keep serving images
    built by the old one (measured: the B/R channel-order fix left every
    already-converted PNG red/blue swapped until they were deleted by hand).
    """
    newest = 0.0
    for path in (getattr(tlg, "__file__", None), __file__):
        if path:
            try:
                newest = max(newest, os.path.getmtime(path))
            except OSError:
                pass
    return newest


def _up_to_date(src, dst):
    """True when `dst` already exists and is not older than `src`.

    Rebuilding a game re-runs the converter over the whole asset tree, and a
    TLG decode is ~3.3 s per file (658 of them = ~35 min).  Skipping an
    up-to-date target makes a second build cheap, which is what makes it
    practical to iterate on the generated shim/code without paying for the
    image work again.

    Image targets are additionally invalidated when the decoder itself is
    newer than the target, so a decoder fix always regenerates them.
    """
    try:
        t_dst = os.path.getmtime(dst)
    except OSError:
        return False
    try:
        t_src = os.path.getmtime(src)
    except OSError:
        return False
    if t_dst < t_src:
        return False
    if dst.lower().endswith(".png") and t_dst < _decoder_mtime():
        return False
    return True


def _convert_tlg(src, dst, stats):
    if _up_to_date(src, dst):
        stats["tlg_cached"] += 1
        return
    try:
        with open(src, "rb") as f:
            data = f.read()
        tlg.decode_to_png(data, dst)
        stats["tlg"] += 1
    except Exception as e:
        # Per-image best-effort fallback: tlg.decode_to_png is a binary
        # format parser; malformed TLG files can raise any parser error, so
        # a failure just counts and continues the conversion.
        log.warning("tlg convert failed %s: %s", os.path.relpath(src), e)
        stats["tlg_fail"] += 1


def _convert_bmp(src, dst, stats):
    if _up_to_date(src, dst):
        stats["bmp_cached"] += 1
        return
    try:
        from PIL import Image
        Image.open(src).convert("RGBA").save(dst, "PNG")
        stats["bmp"] += 1
    except Exception as e:
        # Per-image best-effort fallback: PIL open/convert/save on arbitrary
        # game assets can raise OSError/ValueError/KeyError/DecompressionBomb-
        # Error etc. - not enumerable, so a failure just counts and continues.
        log.warning("bmp convert failed %s: %s", os.path.relpath(src), e)
        stats["bmp_fail"] += 1


def _collect_macros(unpacked):
    """Collect macro names defined in scenario/ so we know which tags are
    game-defined (not Tyrano built-ins) - informational only."""
    macros = set()
    scen = os.path.join(unpacked, "scenario")
    if os.path.isdir(scen):
        for fn in os.listdir(scen):
            if not fn.endswith(".ks"):
                continue
            raw = open(os.path.join(scen, fn), "rb").read()
            txt = raw.decode(detect_encoding(raw), errors="replace")
            for m in re.finditer(r"^\[macro name=(\S+?)([\s\]]|$)", txt, re.M):
                macros.add(m.group(1).lower())
    return macros


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("unpacked", help="extracted KAG3 game dir (xp3tool extract)")
    ap.add_argument("engine", help="TyranoScript engine source tree (index.html + tyrano/)")
    ap.add_argument("out_dir", help="output TyranoScript project")
    ap.add_argument("--scenario-dir", default="scenario", help="scenario subdir in unpacked (default: scenario)")
    ap.add_argument("--scenario-only", action="store_true",
                    help="only re-convert scenario .ks (skip engine copy and assets)")
    ap.add_argument("--font", action="append", default=None, metavar="OTF",
                    help="install a CJK font as the default text face "
                         "(font.css @font-face + Config.tjs userFace; repeatable)")
    ap.add_argument("--video-dir", default=None, metavar="DIR",
                    help="directory of pre-transcoded WebM movies named "
                         "<stem>.webm (default: <unpacked>/_video_webm).  A "
                         "movie with no WebM is copied as-is and warned about, "
                         "since browsers cannot play WMV")
    ap.add_argument("--portrait", action="store_true",
                    help="768x1024 portrait layout: art scaled to the top, "
                         "message text in the bottom black area")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

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
        _convert_assets(unpacked, out_data, stats)
        video_map = _convert_videos(unpacked, out_data, args.video_dir, stats)
    else:
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
    amap, full_map = _asset_map(unpacked)
    _ASSET_CACHE[unpacked] = (amap, full_map)
    ma_map = {k.rsplit(".", 1)[0]: v for k, v in full_map.items() if k.endswith(".ma")}
    asset_js = "window.__kag3_assets = " + json.dumps(amap, ensure_ascii=False) + ";\n"
    asset_ma_js = "window.__kag3_assets_ma = " + json.dumps(ma_map, ensure_ascii=False) + ";\n"
    # name -> converted movie, for the KAG3 video shim ([openvideo storage=X])
    asset_video_js = "window.__kag3_videos = " + json.dumps(
        video_map, ensure_ascii=False) + ";\n"
    shim_js, shim_n = _shim_js(macros)
    runtime_shim = "\n".join([
        "window.__kag3_portrait = " + ("true" if args.portrait else "false") + ";",
        RUNTIME_SHIM_IIFE,
        tjs2js.SPRINTF_SHIM,
        asset_js,
        asset_ma_js,
        asset_video_js,
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
    log.info("done -> %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
