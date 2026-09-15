"""Unit tests for the KAG3 -> TyranoScript converter (kirikiri/kag/).

The converter was split out of kirikiri/convert_kag.py, which is now the
compatibility layer; `ck` is imported through it on purpose, so these tests
also pin the re-export surface."""

import json
import os
import re
import sys
import types
import collections
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kirikiri import convert_kag as ck


@pytest.fixture
def fake_unpacked(tmp_path):
    """A minimal unpacked game tree: scenario/ + asset dirs."""
    scen = tmp_path / "scenario"
    scen.mkdir()
    (scen / "first.ks").write_text(
        "[cm]\n"
        "[trans method=crossfade time=3000]\n"
        "[image storage=\"black\" page=fore layer=base]\n"
        "[call storage=\"ZoomRot.ks\"]\n",
        encoding="utf-8",
    )
    fg = tmp_path / "fgimage"
    fg.mkdir()
    (fg / "black.tlg").write_bytes(b"TLG")
    bg = tmp_path / "bgimage"
    bg.mkdir()
    (bg / "telop1.bmp").write_bytes(b"BMP")
    (tmp_path / "ZoomRot.ks").write_text(
        "[iscript]\nclass ZoomRotPlugin extends KAGPlugin {}\n[endscript]\n",
        encoding="utf-8",
    )
    return tmp_path


class TestConvertKsLine:
    @pytest.mark.parametrize("ending", ["", "\n", "\r\n"])
    def test_inline_dialogue_survives(self, fake_unpacked, ending):
        source = '[font size=24]Hello[r]World[l]' + ending
        assert ck.convert_ks_line(source, str(fake_unpacked), set()) == source

    def test_text_leading_wait_is_converted(self, fake_unpacked):
        source = 'Hello[wait time=5]World[l]\n'
        assert ck.convert_ks_line(source, str(fake_unpacked), set()) == (
            'Hello[kagwaitskip time=5]World[l]\n')

    @pytest.mark.parametrize("tag", [
        'trans method=universal time=500', 'image storage="black" layer=4',
        'wait time=5', 's',
    ])
    def test_at_and_bracket_semantics_match(self, fake_unpacked, tag):
        convert = lambda text: ck.convert_ks_line(text, str(fake_unpacked), set())
        assert convert('@' + tag + '\r\n') == convert('[' + tag + ']\r\n')

    def test_unclosed_tag_and_plain_text_are_preserved(self, fake_unpacked):
        for source in ['Hello [unfinished', 'Hello world\n', '; [s]\n']:
            assert ck.convert_ks_line(source, str(fake_unpacked), set()) == source

    def test_inline_condition_is_balanced_without_losing_text(self):
        source = ['Hello[if exp="f.x"]World\n', '[endif]\n']
        assert ck._balance_if_endif(source) == source

    def test_storage_ext_completed(self, fake_unpacked):
        out = ck.convert_ks_line('[image storage="black" page=fore layer=base]\n',
                                 str(fake_unpacked), set(), False)
        assert "black.png" in out.lower() or "black.tlg" in out

    def test_trans_layer_injected(self, fake_unpacked):
        out = ck.convert_ks_line("[trans method=crossfade time=3000]\n",
                                 str(fake_unpacked), set(), False)
        assert "layer=base" in out

    def test_trans_method_mapped(self, fake_unpacked):
        # KAG3-only transition methods must map to real animate.css
        # methods, else is_trans stays true forever and [wt] hangs.
        cases = {
            "universal": "fadeIn",
            "wave": "fadeIn",
            "ripple": "fadeIn",
            "mosaic": "fadeIn",
            "turn": "flipInX",
            "scroll": "slideInUp",
        }
        for src, dst in cases.items():
            out = ck.convert_ks_line("[trans method=%s time=1000]\n" % src,
                                     str(fake_unpacked), set(), False)
            assert "method=%s" % dst in out, (src, out)

    def test_trans_method_kept_when_supported(self, fake_unpacked):
        # crossfade is natively handled by the engine; unknown methods
        # pass through unchanged.
        out = ck.convert_ks_line("[trans method=crossfade time=1000]\n",
                                 str(fake_unpacked), set(), False)
        assert "method=crossfade" in out
        out = ck.convert_ks_line("[trans method=weirdfx time=1000]\n",
                                 str(fake_unpacked), set(), False)
        assert "method=weirdfx" in out

    def test_trans_method_quoted_and_case(self, fake_unpacked):
        out = ck.convert_ks_line('[trans method="universal" time=1000]\n',
                                 str(fake_unpacked), set(), False)
        assert "method=\"fadeIn\"" in out
        out = ck.convert_ks_line("[trans method=UNIVERSAL time=1000]\n",
                                 str(fake_unpacked), set(), False)
        assert "method=fadeIn" in out

    def test_s_to_kag3stop(self, fake_unpacked):
        out = ck.convert_ks_line('[s]\n', str(fake_unpacked), set(), False)
        assert out.strip() == '[kag3stop]'

    def test_s_to_kag3stop_inline(self, fake_unpacked):
        out = ck.convert_ks_line('[if exp="sf.x==1"][s][endif]\n', str(fake_unpacked), set(), False)
        assert '[kag3stop]' in out and '[s]' not in out

    def test_trans_dynamic_layer_resolved(self, fake_unpacked):
        # laynumber_init.ks defines sf.lay_b_mask=0
        (fake_unpacked / "scenario" / "laynumber_init.ks").write_text(
            '[eval exp="sf.lay_b_mask=0"]\n', encoding="utf-8")
        out = ck.convert_ks_line("[trans layer=&sf.lay_b_mask method=crossfade time=500]\n",
                                 str(fake_unpacked), set(), False)
        assert "layer=0" in out

    def test_trans_layer_preserved(self, fake_unpacked):
        out = ck.convert_ks_line("[trans layer=&sf.lay_b_mask method=crossfade time=500]\n",
                                 str(fake_unpacked), set(), False)
        assert "layer=&sf.lay_b_mask" in out

    def test_continuation_stripped(self, fake_unpacked):
        out = ck.convert_ks_line("[cm]\\\n", str(fake_unpacked), set(), False)
        assert not out.rstrip("\n").endswith("\\")

    def test_continuation_between_tags_is_not_a_tyrano_escape(self, fake_unpacked):
        source = '[if exp="f.x"][wait time=5]\\[endif]\\\n'
        out = ck.convert_ks_line(source, str(fake_unpacked), set())
        assert out == '[if exp="f.x"][kagwaitskip time=5][endif]\n'

    def test_literal_escaped_tag_and_quoted_brackets_are_scanned_like_tyrano(self):
        text = r'visible \[if] [ptext text="[[literal]]"] [endif]'
        assert [x.split()[0] for x in ck._scan_tags(text)] == ["ptext", "endif"]

    def test_at_syntax_converted(self, fake_unpacked):
        out = ck.convert_ks_line("@s\n", str(fake_unpacked), set(), False)
        assert out.strip() == "[kag3stop]"

    def test_label_kept(self, fake_unpacked):
        out = ck.convert_ks_line("*start|タイトル\n", str(fake_unpacked), set(), False)
        assert out.strip() == "*start|タイトル"

    def test_comment_kept(self, fake_unpacked):
        out = ck.convert_ks_line("; comment\n", str(fake_unpacked), set(), False)
        assert out.strip() == "; comment"

    def test_multitag_preserves_order(self, fake_unpacked):
        out = ck.convert_ks_line('[if exp="sf.mpg_mode==0"][image storage="black" layer=4][endif]\n',
                                 str(fake_unpacked), set(), False)
        tags = ck._scan_tags(out)
        assert [t.split()[0] for t in tags] == ["if", "freeimage", "image", "endif"]
        assert 'black.png' in out

    def test_zoomrot_dropped(self, fake_unpacked):
        out = ck.convert_ks_line("class ZoomRotPlugin extends KAGPlugin\n",
                                 str(fake_unpacked), set(), True)
        assert "dropped" in out

    def test_wait_canskip_mapped(self, fake_unpacked):
        out = ck.convert_ks_line('[wait canskip=true time=5000]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[kagwaitskip time=5000]'

    def test_wait_canskip_attr_order(self, fake_unpacked):
        out = ck.convert_ks_line('[wait time=5000 canskip=true]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[kagwaitskip time=5000]'

    def test_wait_canskip_quoted_true(self, fake_unpacked):
        out = ck.convert_ks_line('[wait canskip="true" time=2000]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[kagwaitskip time=2000]'

    def test_wait_no_canskip_kept(self, fake_unpacked):
        out = ck.convert_ks_line('[wait canskip=false time=2000]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[wait canskip=false time=2000]'

    def test_wait_plain_also_mapped(self, fake_unpacked):
        # plain [wait time=N] becomes clickable too (players click through
        # dialogue pauses); only explicit canskip=false stays hard
        out = ck.convert_ks_line('[wait time=3000]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[kagwaitskip time=3000]'

    def test_wait_canskip_false_quoted_kept(self, fake_unpacked):
        out = ck.convert_ks_line('[wait canskip="false" time=2000]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[wait canskip="false" time=2000]'

    def test_wait_canskip_dynamic_time_kept(self, fake_unpacked):
        out = ck.convert_ks_line('[wait canskip=true time=&f.w]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[wait canskip=true time=&f.w]'

    def test_wait_canskip_multitag_line(self, fake_unpacked):
        out = ck.convert_ks_line('[if exp="sf.x==1"][wait canskip=true time=1000][endif]\n',
                                 str(fake_unpacked), set(), False)
        assert '[kagwaitskip time=1000]' in out
        assert '[wait' not in out

    def test_wait_canskip_no_time_kept(self, fake_unpacked):
        # no literal time -> keep native [wait] (safe, still waits)
        out = ck.convert_ks_line('[wait canskip=true]\n',
                                 str(fake_unpacked), set(), False)
        assert out.strip() == '[wait canskip=true]'

    def test_eval_expr_converted(self, fake_unpacked):
        out = ck.convert_ks_line('[eval exp="kag.se[0].setOptions(%[gvolume:20])"]\n',
                                 str(fake_unpacked), set(), False)
        assert "{gvolume: 20}" in out


class TestBalanceIfEndif:
    def test_stray_endif_commented(self):
        out = ck._balance_if_endif(["[if exp=\"a==1\"]\n", "[endif]\n", "[endif]\n"])
        txt = "".join(out)
        assert txt.count("[if exp=\"a==1\"]") == 1
        assert txt.count("[endif]") == 1      # one real, stray dropped
        assert "[er]" in txt                   # stray replaced by [er]

    def test_missing_endif_appended(self):
        out = ck._balance_if_endif(["[if exp=\"a==1\"]\n"])
        assert "".join(out).endswith("[endif]\n")

    def test_balanced_untouched(self):
        lines = ["[if exp=\"a==1\"]\n", "[endif]\n"]
        out = ck._balance_if_endif(lines)
        assert out == lines

    def test_iscript_skipped(self):
        lines = ["[iscript]\n", "var x = 1;\n", "[endscript]\n", "[if exp=\"a\"]\n", "[endif]\n"]
        out = ck._balance_if_endif(lines)
        assert "".join(out).count("[endif]") == 1


class TestExportGlobals:
    def test_var_exported(self):
        out = ck._export_globals("var anlist = [];\n")
        assert "window.anlist = anlist;" in out

    def test_function_exported(self):
        out = ck._export_globals("function AnimeData() {\n}\n")
        assert "window.AnimeData = AnimeData;" in out

    def test_function_exported_with_brace_on_the_next_line(self):
        """Regression: this corpus writes `function f(a)\n{` and those
        declarations were skipped, so the engine's eval scoped them locally
        and the global lookup silently fell through to the runtime shim's
        fallback stub (measured: every dialogue voice was muted because the
        game's CharVoiceFlgCheck was shadowed by a stub returning 0)."""
        src = ("function CharVoiceNumGet(vo_name)\n"
               "{\n"
               "\tvar ret;\n"
               "\tret = 0;\n"
               "\treturn ret;\n"
               "}\n")
        out = ck._export_globals(src)
        assert "window.CharVoiceNumGet = CharVoiceNumGet;" in out

    def test_nested_function_is_not_exported(self):
        src = ("function Outer()\n"
               "{\n"
               "  function Inner() { return 1; }\n"
               "  return Inner();\n"
               "}\n")
        out = ck._export_globals(src)
        assert "window.Outer = Outer;" in out
        assert "Inner" not in out.split("window.Outer")[-1]

    def test_anonymous_function_expression_is_not_exported(self):
        out = ck._export_globals("var f = function (x) { return x; };\n")
        assert "window.f = f;" in out
        assert "window.function" not in out

    def test_no_export_when_none(self):
        assert ck._export_globals("var i = 0;\nfor (i = 0; i < 3; i++) {}\n") is not None


class TestFindAsset:
    """`_find_asset` returns `../<canonical_dir>/<file>`.

    Every asset is written exactly once (mirroring it into every directory a
    tag might look in tripled the build, and ~75% of that duplication
    survived compression).  The `../` prefix makes the path work from
    whatever `data/<folder>/` the receiving tag prepends, because browsers
    normalise dot segments in URLs - measured: `./data/image/../bgimage/x.png`
    arrives at the server as `/data/bgimage/x.png`.
    """

    def test_extless_to_png(self, fake_unpacked):
        # tlg source -> png output name, in its one canonical directory
        assert ck._find_asset(str(fake_unpacked), "black") == \
            "../fgimage/black.png"

    def test_bmp_to_png(self, fake_unpacked):
        assert ck._find_asset(str(fake_unpacked), "telop1") == \
            "../bgimage/telop1.png"

    def test_bmp_ext_ref_remapped(self, fake_unpacked):
        assert ck._find_asset(str(fake_unpacked), "telop1.bmp") == \
            "../bgimage/telop1.png"

    def test_unknown_kept(self, fake_unpacked):
        assert ck._find_asset(str(fake_unpacked), "nosuchfile") == "nosuchfile"

    def test_path_kept(self, fake_unpacked):
        assert ck._find_asset(str(fake_unpacked), "sub/x.png") == "sub/x.png"

    def test_result_is_relative_to_any_folder(self, fake_unpacked):
        # The whole point of the ../ form: an asset living in fgimage must be
        # reachable for a tag that prepends bgimage/ (or image/, or sound/).
        got = ck._find_asset(str(fake_unpacked), "black")
        assert got.startswith("../"), got
        assert "/" in got[3:], got


class TestShim:
    def test_macro_excluded_from_shim(self):
        # game-defined macros must not be shadowed by shim no-ops
        macros = {"t_next", "name_w", "sysmenu"}
        js, n = ck._shim_js(macros=macros)
        assert 'tag["sysmenu"]' not in js
        assert 'tag["t_next"]' not in js
        assert 'tag["name_w"]' not in js
        # Tags with a real implementation (VIDEO_TAGS) are excluded too: a
        # no-op registration would win over the implementation and the
        # feature would silently do nothing.
        assert n <= len(ck.SHIM_TAG_NAMES) - len(macros) - len(ck.VIDEO_TAGS)

    def test_real_implementations_are_not_shimmed_as_noops(self):
        js, _n = ck._shim_js()
        for tag in ck.VIDEO_TAGS:
            assert ('define("%s")' % tag) not in js, tag

    def test_non_macro_kept_in_shim(self):
        js, n = ck._shim_js(macros={"bgm"})
        assert 'define("loadplugin")' in js

    def test_shim_has_noop_start(self):
        js, _ = ck._shim_js()
        assert "start: noop" in js
        # every shimmed tag is registered through the guarded define()
        for name in ck.SHIM_TAG_NAMES[:5]:
            assert 'define("%s");' % name in js


class TestWaitskipShim:
    def test_tag_registered(self):
        assert "tyrano.plugin.kag.tag['kagwaitskip']" in ck.WAITSKIP_SHIM_JS

    def test_registration_not_guarded_by_kag(self):
        # TYRANO.kag does not exist at script-parse time: the registration
        # must be unconditional (ftag.init copies it into master_tag at boot)
        assert "TYRANO.kag" not in ck.WAITSKIP_SHIM_JS

    def test_click_listener_uses_namespace(self):
        # namespaced listener so kag.off() removes only this wait's listener
        assert "click-event.kagwaitskip" in ck.WAITSKIP_SHIM_JS
        assert "kag.off('click-event.kagwaitskip')" in ck.WAITSKIP_SHIM_JS

    def test_never_advances_twice(self):
        # the click path must NOT call nextOrder (the click handler itself
        # advances right after click-event); only the timer path advances
        assert "kag.ftag.nextOrder();" in ck.WAITSKIP_SHIM_JS
        clicks = ck.WAITSKIP_SHIM_JS.split("on_click = function ()", 1)[1]
        clicks = clicks.split("kag.tmp.wait_id = setTimeout", 1)[0]
        assert "nextOrder" not in clicks

    def test_event_layer_shown(self):
        # clicks never reach the handler while the event layer is hidden
        assert "showEventLayer" in ck.WAITSKIP_SHIM_JS

    def test_timer_defaults_to_1000ms(self):
        assert "parseInt(pm.time) || 1000" in ck.WAITSKIP_SHIM_JS


class TestRuntimeShim:
    def test_polls_until_kag_ready(self):
        # kag is created at boot, not parse: patches must wait for it
        assert "apply_runtime" in ck.RUNTIME_SHIM_IIFE
        assert "kag.ftag.master_tag" in ck.RUNTIME_SHIM_IIFE
        assert "setInterval" in ck.RUNTIME_SHIM_IIFE
        assert "__kag3_runtime_applied" in ck.RUNTIME_SHIM_IIFE

    def test_kag_n_stub_inside_runtime(self):
        # the kag.n.clear() stub must run post-boot (was silently skipped)
        assert "kag.n = kag.n || _hl" in ck.RUNTIME_SHIM_IIFE
        assert "kag.historyLayer = kag.historyLayer || _hl" in ck.RUNTIME_SHIM_IIFE

    def test_playbgm_wrap_inside_runtime(self):
        assert "_wrap_storage('playbgm')" in ck.RUNTIME_SHIM_IIFE
        assert "kag.ftag.nextOrder()" not in ck.RUNTIME_SHIM_IIFE.split(
            "_resolve_storage", 1)[1].split("_wrap_storage('graph')", 1)[0]

    def test_trans_and_emb_wraps_inside_runtime(self):
        assert "master_tag.trans" in ck.RUNTIME_SHIM_IIFE
        assert "kag.embScript" in ck.RUNTIME_SHIM_IIFE

    def test_missing_tag_tracker_inside_runtime(self):
        assert "__missing_tags" in ck.RUNTIME_SHIM_IIFE

    def test_waitskip_embedded_in_runtime(self):
        assert "kagwaitskip" in ck.RUNTIME_SHIM_IIFE


class TestMapEngine:
    def test_map_tags_registered_parse_time(self):
        assert "tyrano.plugin.kag.tag['mapaction']" in ck.MAP_ENGINE_JS
        assert "tyrano.plugin.kag.tag['mapimage']" in ck.MAP_ENGINE_JS
        assert "tyrano.plugin.kag.tag['mapdisable']" in ck.MAP_ENGINE_JS

    def test_region_palette_sampling(self):
        # region number = palette index = gray value of the converted image
        assert "getImageData" in ck.MAP_ENGINE_JS
        assert "d[0]" in ck.MAP_ENGINE_JS

    def test_autodisable_semantics(self):
        # map disables after a click unless region 0 sets autodisable=false
        assert "autodisable" in ck.MAP_ENGINE_JS
        assert "'false'" in ck.MAP_ENGINE_JS

    def test_onenter_onleave_and_exp(self):
        assert "onenter" in ck.MAP_ENGINE_JS
        assert "onleave" in ck.MAP_ENGINE_JS
        assert "action.exp" in ck.MAP_ENGINE_JS

    def test_kag_process_shim_in_runtime(self):
        assert "kag.process = function" in ck.RUNTIME_SHIM_IIFE
        assert "kag.callExtraConductor" in ck.RUNTIME_SHIM_IIFE

    def test_image_auto_map_wrapper(self):
        # [image] clears the layer map and auto-attaches X.ma when present
        assert "__kag3_map_clear(layerName)" in ck.RUNTIME_SHIM_IIFE
        assert "__kag3_assets_ma()[base]" in ck.RUNTIME_SHIM_IIFE

    def test_storage_wrappers(self):
        for tag in ("graph", "ptext", "chara_show", "chara_mod",
                    "chara_ptext", "playse", "playbgm"):
            assert "_wrap_storage('%s')" % tag in ck.RUNTIME_SHIM_IIFE

    def test_image_map_wrapper_covers_loadimages_tags(self):
        # KAG3 loadImages semantics: image/bg/bg2/graph all clear the layer
        # map and auto-attach X.ma (GraphicLayer.tjs). bg is no longer a
        # bare storage wrapper.
        assert "['image', 'bg', 'bg2', 'graph'].forEach" in ck.RUNTIME_SHIM_IIFE
        assert "_wrap_storage('bg')" not in ck.RUNTIME_SHIM_IIFE

    def test_no_jump_map_clear(self):
        # Maps survive scenario jumps/process() (MainWindow.tjs process()
        # never touches the map); scenarios disable them with [mapdisable].
        assert "_clear_maps_on_jump" not in ck.RUNTIME_SHIM_IIFE

    def test_kag3stop_tag_registered_parse_time(self):
        assert "tyrano.plugin.kag.tag['kag3stop']" in ck.RUNTIME_SHIM_IIFE
        assert "stronglyStop" in ck.RUNTIME_SHIM_IIFE

    def test_rclick_tag_registered_not_shimmed(self):
        # [rclick] is a real tag now (right-click handler + touch fallback),
        # not a no-op: comming/lineup screens continue via its jump.
        assert "tyrano.plugin.kag.tag['rclick']" in ck.RUNTIME_SHIM_IIFE
        assert "rclick" not in ck.SHIM_TAG_NAMES
        assert "__kag3_exec_rclick" in ck.RUNTIME_SHIM_IIFE
        assert "contextmenu" in ck.RUNTIME_SHIM_IIFE

    def test_ch_tag_registered_not_shimmed(self):
        # KAG3 [ch] renders text (names, choice labels, menu items) on the
        # current message layer; a no-op would leave names/choices empty.
        assert "tyrano.plugin.kag.tag['ch']" in ck.RUNTIME_SHIM_IIFE
        assert "ch" not in ck.SHIM_TAG_NAMES
        assert "startTag('text', p)" in ck.RUNTIME_SHIM_IIFE

    def test_portrait_css_and_shim(self):
        assert "scale(0.75)" in ck.PORTRAIT_CSS
        assert "1024px !important" in ck.PORTRAIT_CSS
        assert "window.__kag3_portrait" in ck.RUNTIME_SHIM_IIFE
        assert "pm.top = T + 256" in ck.RUNTIME_SHIM_IIFE

    def test_click_consumed_via_capture(self):
        assert "addEventListener('click'" in ck.MAP_ENGINE_JS
        assert "stopPropagation" in ck.MAP_ENGINE_JS

    def test_mobile_panel_uses_real_engine_actions(self):
        js = ck.RUNTIME_SHIM_IIFE
        assert "id = 'kag3-mobile-panel'" in js
        assert "kag.menu.displaySave()" in js
        assert "kag.menu.displayLoad()" in js
        assert "kag.menu.displayLog()" in js
        assert "kag.setAuto(!kag.stat.is_auto)" in js
        assert "kag.ftag.startTag('skipstart', {})" in js
        assert "else if (kag.stat.is_adding_text) kag.setSkip(true)" in js
        assert "kag.ftag.startTag('hidemessage', {})" in js
        assert "kag.layer.showMessageLayers()" in js
        assert "min-height:44px" in js
        assert "actions.style.display === 'none' ? 'flex' : 'none'" in js
        assert "Game controls" in js
        assert "button_menu.png" in js
        assert "el.id === 'kag3-mobile-panel'" in ck.MAP_ENGINE_JS

    def test_mobile_panel_uses_native_hide_lifecycle_and_serialises_menus(self):
        js = ck.RUNTIME_SHIM_IIFE
        assert "kag.ftag.startTag('hidemessage', {})" in js
        assert "kag.layer.showEventLayer('kag3-mobile-hide')" in js
        assert "kag.setSkip(false)" in js
        assert "if (menuPending || menuIsVisible()) return" in js
        assert "menuLayer.stop(true, true).hide().empty()" in js
        assert "panel.style.visibility = menuIsVisible() ? 'hidden' : 'visible'" in js

    def test_kag_ui_compatibility_methods_are_not_stubs(self):
        js = ck.RUNTIME_SHIM_IIFE
        assert "kag.showHistoryByKey = function" in js
        assert "this.menu.displayLog()" in js
        assert "kag.enterAutoMode = function" in js
        assert "this.setAuto(true)" in js
        assert "kag.cancelAutoMode = function" in js
        assert "this.setAuto(false)" in js
        assert "kag.goToStartWithAsk = function" in js
        assert "this.backTitle()" in js
        assert "_close.start = function () { kag.backTitle(); };" in js

    def test_ma_parsing_skips_comments_and_empty(self):
        actions = ck_map_parse("; comment\n0: autodisable=false;\n1: storage=\"x.ks\"; target=\"*y\";\n\n")
        assert set(actions) == {0, 1}
        assert "storage=\"x.ks\"" in actions[1]


def ck_map_parse(text):
    """Mirror of the runtime .ma parser (generic engine logic)."""
    import re as _re
    actions = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        m = _re.match(r"^(\d+)\s*:\s*(.*)$", line)
        if not m:
            continue
        actions[int(m.group(1))] = m.group(2)
    return actions


class TestAssetMap:
    def test_image_wins_over_ma(self, fake_unpacked):
        # map01_01.ma + map01_01.bmp share a basename; the image must win
        (fake_unpacked / "fgimage" / "select").mkdir(exist_ok=True)
        (fake_unpacked / "fgimage" / "select" / "map01_01.ma").write_text("1: x;", encoding="utf-8")
        (fake_unpacked / "fgimage" / "select" / "map01_01.bmp").write_bytes(b"BMP")
        amap, full = ck._asset_map(str(fake_unpacked))
        assert amap["map01_01"] == "fgimage/select/map01_01.png"
        assert full["map01_01.ma"] == "fgimage/select/map01_01.ma"

    def test_find_asset_exact_case_for_ma(self, fake_unpacked):
        # storage="title.ma" must resolve to the on-disk case (TITLE.MA)
        (fake_unpacked / "fgimage" / "TITLE.MA").write_text("0: autodisable=false;", encoding="utf-8")
        (fake_unpacked / "fgimage" / "title.png").write_bytes(b"PNG")
        assert ck._find_asset(str(fake_unpacked), "title.ma") == \
            "../fgimage/TITLE.MA"
        assert ck._find_asset(str(fake_unpacked), "title") == \
            "../fgimage/title.png"

    def test_ma_lookup_prefers_exact_storage(self, fake_unpacked):
        # 'title' must NOT resolve to the .ma when an image exists
        (fake_unpacked / "fgimage" / "TITLE.MA").write_text("0: x;", encoding="utf-8")
        (fake_unpacked / "fgimage" / "title.png").write_bytes(b"PNG")
        amap, _ = ck._asset_map(str(fake_unpacked))
        assert amap["title"] == "fgimage/title.png"

    def test_mapaction_storage_rewritten(self, fake_unpacked):
        (fake_unpacked / "fgimage" / "TITLE.MA").write_text("0: x;", encoding="utf-8")
        out = ck.convert_ks_line('[mapaction layer=base storage="title.ma"]\n',
                                 str(fake_unpacked), set(), False)
        assert "TITLE.MA" in out

    def test_existing_output_assets_are_indexed(self, tmp_path):
        out_data = tmp_path / "data"
        (out_data / "fgimage" / "nested").mkdir(parents=True)
        (out_data / "fgimage" / "nested" / "BLACK.PNG").write_bytes(b"PNG")
        (out_data / "sound").mkdir()
        (out_data / "sound" / "click.ogg").write_bytes(b"OggS")

        amap, full = ck._asset_map_from_output(str(out_data))

        assert amap["black"] == "fgimage/nested/BLACK.PNG"
        assert full["black.png"] == "fgimage/nested/BLACK.PNG"
        assert amap["click"] == "sound/click.ogg"

    def test_existing_output_prefers_image_for_shared_stem(self, tmp_path):
        out_data = tmp_path / "data"
        (out_data / "fgimage").mkdir(parents=True)
        (out_data / "fgimage" / "map.ma").write_text("0: x;", encoding="utf-8")
        (out_data / "fgimage" / "map.png").write_bytes(b"PNG")

        amap, full = ck._asset_map_from_output(str(out_data))

        assert amap["map"] == "fgimage/map.png"
        assert full["map.ma"] == "fgimage/map.ma"

    def test_is_image_asset(self):
        assert ck._is_image_asset("fgimage/title.png")
        assert ck._is_image_asset("fgimage/art.BMP")
        assert ck._is_image_asset("bgimage/title.jpg")
        assert not ck._is_image_asset("fgimage/TITLE.MA")
        assert not ck._is_image_asset("sound/se.wav")
        assert not ck._is_image_asset("")
        assert not ck._is_image_asset(None)

    def test_merge_lets_image_beat_map_file(self):
        base = {"title": "fgimage/TITLE.MA", "se": "sound/se.wav"}
        extra = {"title": "fgimage/TITLE.MA", "title.png": "fgimage/title.png"}
        merged = ck._merge_asset_maps(base, extra)
        # the .MA never displaces the art it shares a stem with
        assert merged["title.png"] == "fgimage/title.png"
        assert merged["se"] == "sound/se.wav"
        assert merged is base

    def test_merge_never_downgrades_an_image(self):
        # source has the picture, the retained build only has the map file
        base = {"title": "fgimage/title.png"}
        extra = {"title": "fgimage/TITLE.MA"}
        assert ck._merge_asset_maps(base, extra)["title"] == "fgimage/title.png"

    def test_merge_keeps_the_source_choice_between_two_images(self):
        # Both are pictures: which art a stem means is the source tree's call
        # (previous behaviour), so the merge must not reroute it.
        base = {"title": "image/button/title.png"}
        extra = {"title": "fgimage/title.png"}
        assert ck._merge_asset_maps(base, extra)["title"] == "image/button/title.png"

    def test_merge_keeps_a_map_only_stem(self):
        # no picture anywhere: the .MA must stay resolvable for [mapaction]
        base = {"submenu": "fgimage/submenu.ma"}
        extra = {}
        assert ck._merge_asset_maps(base, extra)["submenu"] == "fgimage/submenu.ma"

    def test_reduced_source_keeps_the_title_art(self, tmp_path):
        """Regression: a scenario-only rebuild must not lose the menu art.

        Measured failure: the rebuilt title screen was BLACK while its click
        regions still worked - `[image storage=title2]` resolved to the
        clickable-map action file (`TITLE2.MA`) because the reduced source tree
        had no picture under that stem and `setdefault` let the .MA win.
        """
        unpacked = tmp_path / "reduced"
        (unpacked / "fgimage").mkdir(parents=True)
        (unpacked / "scenario").mkdir()
        # reduced tree: the clickable-map files survive, the art was not copied
        (unpacked / "fgimage" / "TITLE2.MA").write_text("0: x;", encoding="utf-8")
        (unpacked / "fgimage" / "title2_P.png").write_bytes(b"PNG")

        out_data = tmp_path / "data"
        (out_data / "fgimage").mkdir(parents=True)
        # the previous build still holds the art and the region mask
        (out_data / "fgimage" / "TITLE2.MA").write_text("0: x;", encoding="utf-8")
        (out_data / "fgimage" / "title2.png").write_bytes(b"PNG")
        (out_data / "fgimage" / "title2_P.png").write_bytes(b"PNG")

        amap, full = ck._runtime_asset_maps(str(unpacked), str(out_data), True)

        assert amap["title2"] == "fgimage/title2.png"
        # the region mask keeps its own stem, so clicks still hit-test
        assert amap["title2_p"] == "fgimage/title2_P.png"
        # extension keys stay usable for exact storages
        assert full["title2.ma"] == "fgimage/TITLE2.MA"
        assert full["title2.png"] == "fgimage/title2.png"

    def test_fresh_build_map_is_untouched_by_the_output_tree(self, tmp_path):
        unpacked = tmp_path / "src"
        (unpacked / "fgimage").mkdir(parents=True)
        (unpacked / "fgimage" / "title.png").write_bytes(b"PNG")
        out_data = tmp_path / "data"
        (out_data / "fgimage").mkdir(parents=True)
        (out_data / "fgimage" / "stale.png").write_bytes(b"PNG")

        amap, _ = ck._runtime_asset_maps(str(unpacked), str(out_data), False)

        assert amap["title"] == "fgimage/title.png"
        assert "stale" not in amap


class TestRegionImage:
    def test_region_detected(self):
        assert ck._is_region_image("title_P.png")
        assert ck._is_region_image("map01_01_p.png")
        assert ck._is_region_image("map01_01_p.bmp")
        assert not ck._is_region_image("title.png")
        assert not ck._is_region_image("title_p.ma")

    def test_palette_index_to_gray(self, fake_unpacked):
        # build a small indexed PNG with palette[i] != i; conversion must
        # produce gray == palette index
        import struct, zlib
        w = h = 4
        idx = bytes([0, 1, 2, 3, 1, 2, 3, 0, 2, 3, 0, 1, 3, 0, 1, 2])
        pal = bytearray()
        for i in range(4):
            pal += bytes([i * 40, 200 - i, 10 + i])
        pal += bytes(3) * (256 - 4)
        rows = b"".join(b"\x00" + idx[r * 4:(r + 1) * 4] for r in range(4))

        def chunk(t, d):
            c = t + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"PLTE", bytes(pal))
               + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
        src = fake_unpacked / "fgimage" / "t_p.png"
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(png)
        dst = fake_unpacked / "out" / "t_p.png"
        dst.parent.mkdir(exist_ok=True)
        stats = Counter()
        ck._convert_region_image(str(src), str(dst), stats)
        assert stats["region"] == 1
        from PIL import Image as _PIL
        out_im = _PIL.open(str(dst))
        assert out_im.mode == "L"
        assert out_im.tobytes() == idx


# ---------------------------------------------------------------------------
# Regressions found while play-testing a real build.
# ---------------------------------------------------------------------------


def test_free_layer_does_not_cover_the_click_event_layer():
    """Tyrano draws [button] into the free layer, which stacks ABOVE
    .layer_event_click (z-index 999999 vs 9999) and spans the whole canvas.

    Tyrano binds click-to-advance to .layer_event_click, so while the free
    layer accepts pointer events every click lands on it instead and a
    [p]/[s] click wait can never be satisfied: the story shows a line and then
    ignores every click (no tag runs, no error, no cursor movement).  KAG3
    games build most of their UI out of [button] (sysmenu, save/load, ...), so
    this hits every scene, not just menus.

    The free layer itself must be click-through; its children (the actual
    buttons) must stay clickable.
    """
    js = ck.RUNTIME_SHIM_IIFE
    assert "data-kag3" in js and "free-layer-clickthrough" in js, js[:400]
    assert ".layer_free{pointer-events:none !important}" in js, js[:400]
    assert ".layer_free>*{pointer-events:auto !important}" in js, js[:400]


def test_decoder_mtime_tracks_only_the_image_decoder(tmp_path, monkeypatch):
    """The image cache must invalidate when the decoder changes, but not when
    unrelated converter code changes.

    Including the converter in the decoder timestamp meant every shim or
    scenario tweak reconverted all 748 images (~35 min per edit), which defeats
    the cache; omitting the decoder entirely meant a decoder fix silently kept
    serving images built by the old one.
    """
    from kirikiri import tlg as ktlg
    from kirikiri.kag import assets as kag_assets

    mtime = ck._decoder_mtime()
    assert mtime > 0
    assert abs(mtime - os.path.getmtime(ktlg.__file__)) < 1.0

    # Stronger form of "the converter itself is not in the key": point the
    # decoder module at a file with a known old timestamp and check that the
    # key equals exactly that, i.e. no other module's mtime is mixed in.
    fake = tmp_path / "tlg.py"
    fake.write_text("", encoding="utf-8")
    os.utime(fake, (1_000_000, 1_000_000))
    monkeypatch.setattr(kag_assets, "tlg", types.SimpleNamespace(__file__=str(fake)))
    assert ck._decoder_mtime() == 1_000_000, (
        "the image cache key must be the decoder only, not the converter")


def test_up_to_date_invalidates_images_when_decoder_is_newer(tmp_path):
    src = tmp_path / "a.tlg"
    dst = tmp_path / "a.png"
    src.write_bytes(b"x")
    dst.write_bytes(b"y")
    now = os.path.getmtime(src)
    os.utime(dst, (now + 100, now + 100))
    assert ck._up_to_date(str(src), str(dst)) is True
    # a decoder newer than the target forces a rebuild
    os.utime(dst, (now - 100, now - 100))
    assert ck._up_to_date(str(src), str(dst)) is False


def test_up_to_date_keeps_non_image_targets_cheap(tmp_path):
    """Non-image targets must not be tied to the decoder timestamp."""
    src = tmp_path / "a.ks"
    dst = tmp_path / "a.out"
    src.write_bytes(b"x")
    dst.write_bytes(b"y")
    now = os.path.getmtime(src)
    os.utime(dst, (now + 100, now + 100))
    assert ck._up_to_date(str(src), str(dst)) is True


# ---------------------------------------------------------------------------
# Layer replace semantics (KAG3 one-image-per-layer vs Tyrano append).
# ---------------------------------------------------------------------------


def test_image_clears_its_layer_first(fake_unpacked):
    """KAG3 [image] replaces the layer content; Tyrano's [image] only appends.

    The game clears a character slot by drawing a transparent placeholder over
    it, which silently does nothing under append semantics: the sprite stays
    visible under the transparent image and every character a scene ever
    loaded remains on screen for the rest of the game.
    """
    out = ck.convert_ks_line('[image layer=3 storage="y_t003e"]', fake_unpacked, ())
    assert out.startswith("[freeimage layer=3]"), out
    assert "[image layer=3" in out


def test_image_layer_clear_keeps_page_and_dynamic_layer(fake_unpacked):
    """The clear must hit the same page, and dynamic layer numbers must survive
    (the sprite macros compute `layer=&tf.layer1`, and Tyrano evaluates a
    leading & in any parameter)."""
    out = ck.convert_ks_line('[image layer="&tf.layer2" page=back storage="x"]',
                             fake_unpacked, ())
    assert out.startswith('[freeimage layer="&tf.layer2" page=back]'), out


def test_graph_is_covered_too(fake_unpacked):
    out = ck.convert_ks_line('[graph layer=5 storage="x"]', fake_unpacked, ())
    assert out.startswith("[freeimage layer=5]"), out


def test_image_opacity_is_applied_to_its_single_image_layer(fake_unpacked):
    """Tyrano ignores opacity on [image], so preserve it through [layopt]."""
    out = ck.convert_ks_line(
        '[image layer=7 page=back storage="hit_surface" opacity=0]',
        fake_unpacked,
        (),
    )
    assert out.startswith(
        "[freeimage layer=7 page=back][layopt layer=7 page=back opacity=0]"
    ), out
    assert '[image layer=7 page=back' in out


def test_image_without_opacity_does_not_reset_layer_opacity(fake_unpacked):
    """An unrelated layer-level fade must survive ordinary image replacement."""
    out = ck.convert_ks_line('[image layer=7 storage="sprite"]', fake_unpacked, ())
    assert "[layopt" not in out


def test_base_layer_is_not_cleared(fake_unpacked):
    """The engine's [freeimage] refuses the base layer, so injecting a clear
    there would only add a dead tag."""
    out = ck.convert_ks_line('[image layer=base storage="x"]', fake_unpacked, ())
    assert "freeimage" not in out, out


def test_image_without_layer_is_left_alone(fake_unpacked):
    out = ck.convert_ks_line('[image storage="x"]', fake_unpacked, ())
    assert out.strip() == '[image storage="x"]', out


def test_multi_tag_line_clears_each_layer(fake_unpacked):
    out = ck.convert_ks_line('[image layer=3 storage="a"][image layer=4 storage="b"]',
                             fake_unpacked, ())
    assert "[freeimage layer=3]" in out and "[freeimage layer=4]" in out, out


def test_freeimage_is_not_double_prefixed(fake_unpacked):
    out = ck.convert_ks_line('[freeimage layer=3]', fake_unpacked, ())
    assert out.strip() == "[freeimage layer=3]", out


def test_layer_clear_keeps_the_source_line_ending(fake_unpacked):
    """Injecting the [freeimage] clear must not eat the line ending.

    Dropping it glues the next source line onto this one. A `;` comment is a
    whole-line comment for KAG3 and for Tyrano's parser, but once it lands in
    the middle of a tag line Tyrano reads it as message text -- which is
    exactly how comments from the original script started showing up as
    dialogue in the message window.
    """
    out = ck.convert_ks_line('[image layer=3 storage="y_t003e"]\r\n', fake_unpacked, ())
    assert out.endswith("\r\n"), repr(out)
    out_lf = ck.convert_ks_line('[image layer=3 storage="y_t003e"]\n', fake_unpacked, ())
    assert out_lf.endswith("\n"), repr(out_lf)


def test_layer_clear_keeps_a_line_without_ending_bare(fake_unpacked):
    """A line that arrives without an ending must not gain one."""
    out = ck.convert_ks_line('[image layer=3 storage="y_t003e"]', fake_unpacked, ())
    assert not out.endswith(("\n", "\r")), repr(out)


def test_comment_after_a_tag_line_stays_on_its_own_line(fake_unpacked, tmp_path):
    r"""End-to-end guard for the reported defect: a backslash-continued tag
    line followed by a `;` comment must not merge, and the output must not
    carry a mid-line `;` (which Tyrano would print as dialogue)."""
    src = tmp_path / "scenario"
    ks = src / "t.ks"
    ks.write_text(
        '[image layer=&sf.lay_ch_left storage=&f.ini]\\\r\n'
        '[image layer=&sf.lay_ch_center storage=&f.ini]\\\r\n'
        ';画像ファイル名のクリア\r\n'
        '[eval exp="f.t_left=f.ini"]\\\r\n',
        encoding="cp932",
    )
    out_path = tmp_path / "out.ks"
    ck.convert_scenario_file(str(ks), str(tmp_path), str(out_path), {},
                             collections.defaultdict(int))
    out_lines = out_path.read_text(encoding="utf-8").splitlines()
    assert ";画像ファイル名のクリア" in out_lines, out_lines
    glued = [l for l in out_lines if ";" in l and not l.lstrip().startswith(";")]
    assert glued == [], glued


# ---------------------------------------------------------------------------
# Readability + fast-forward (play-test feedback).
# ---------------------------------------------------------------------------


def test_button_graphic_goes_through_the_asset_map_at_conversion_time(fake_unpacked):
    """[button graphic=X] must be rewritten to the '../<dir>/<file>' form.

    Tyrano's scenario runner dispatches plain tags by calling
    master_tag[x].start directly (kag.tag.js nextOrder), so a runtime hook is
    not guaranteed to see the tag. The engine then loads the graphic from
    ./data/image/, which turned every system button into a broken-image
    placeholder (measured: ./data/image/history_bot when the file sits at
    data/bgimage/HISTORY_bot.png).
    """
    out = ck.convert_ks_line('[button graphic="telop1" exp="x()"]\n',
                            str(fake_unpacked), set(), False)
    # the map also accounts for format conversion (bmp -> png in the build)
    assert 'graphic="../bgimage/telop1.png"' in out, out


def test_button_graphic_resolution_has_one_implementation(fake_unpacked):
    """Both hook points must delegate to __kag3_asset_path.

    The dispatcher hook covers macro-generated and callback tags, the button
    wrapper covers tags the engine dispatches itself. Neither may assign a bare
    asset-map value ('bgimage/x.png'), which the engine would resolve to
    ./data/image/bgimage/x.png and 404.
    """
    js = ck.RUNTIME_SHIM_IIFE
    assert "pm.graphic = r;" not in js
    assert js.count("__kag3_asset_path(pm.graphic)") == 2, js.count("__kag3_asset_path(pm.graphic)")


def test_injected_style_statement_is_terminated():
    r"""The style injection must keep its statement terminator.

    Without it JavaScript's automatic semicolon insertion reads
    `'...' (document.head...)` as a call on the string, the TypeError is
    swallowed by the surrounding try/catch and the whole style block silently
    never gets injected (measured: data-kag3 missing, overflow computed as
    visible). node --check cannot see this -- it is not a syntax error.
    """
    js = ck.RUNTIME_SHIM_IIFE
    assert ".message_inner p.kag3ch{" in js
    # the concatenated statement ends with a terminator before the append
    # (rule-agnostic: the last CSS rule before the statement must end `}';`)
    assert re.search(r"\}';\s*\(document\.head", js), js[-700:]


def test_message_text_is_clipped_to_its_window():
    """Hard guarantee: dialogue can never paint over the bottom-right UI."""
    assert ".message_inner{overflow:hidden}" in ck.RUNTIME_SHIM_IIFE


def test_message_font_keeps_source_metrics_without_shrinking():
    """Global overrides damage small nameplates and explicit source styling."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "font-size:22px !important" not in js
    assert "line-height:28px !important" not in js
    assert 'var font = this.kag.stat.font || {}' in ck.NOOP_PLUS_REAL_JS
    assert '$s.css("font-size", font.size + "px")' in ck.NOOP_PLUS_REAL_JS
    # the measurement helper may report an overflow, but must not resize
    assert "window.__kag3_fit_message" in js
    assert "setTimeout(run, 150)" in js          # debounce: no per-frame reflow
    for forbidden in ("data-kag3-fit", "data-kag3-k", "span.style.fontSize",
                      "want * scale"):
        assert forbidden not in js, forbidden


def test_fit_check_reports_but_never_resizes():
    """Owner decision: text must not be resized to make it fit.

    The helper may measure and report an overflow, but the message font comes
    from the game's own KAG3 metrics (see the metrics test), so a normal
    message fits without any rescaling."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "window.__kag3_fit_message" in js
    assert "el.scrollHeight > el.clientHeight + 1" in js   # report only
    assert "setTimeout(run, 150)" in js  # debounce: no per-frame reflow
    assert "data-kag3-k" not in js


def test_engine_tags_are_never_registered_as_no_ops(tmp_path):
    """A shim no-op must never shadow a tag the engine implements.

    A later registration wins, so a no-op silently DISABLES a working engine
    feature. Measured on this engine: bg, bgmopt, close, fadeinbgm, fadeoutse,
    ruby, style, wa, wb, wq were all masked that way.
    """
    eng = tmp_path / "tyrano" / "plugins" / "kag"
    eng.mkdir(parents=True)
    (eng / "kag.tag_audio.js").write_text(
        'tyrano.plugin.kag.tag["playse"] = { start: function () {} };\n'
        'tyrano.plugin.kag.tag.bgmopt = { start: function () {} };\n',
        encoding="utf-8",
    )
    js, _n = ck._shim_js((), str(tmp_path))
    assert 'define("playse")' not in js
    assert 'define("bgmopt")' not in js
    # a runtime guard too: the engine wins whoever registered first
    assert "if (tyrano.plugin.kag.tag[name])" in js
    assert "window.__kag3_shim_skipped" in js


def test_engine_tag_names_reads_all_registration_forms(tmp_path):
    eng = tmp_path / "tyrano"
    eng.mkdir()
    (eng / "a.js").write_text(
        'tyrano.plugin.kag.tag["alpha"] = {};\n'
        'tyrano.plugin.kag.tag.beta = {};\n'
        'plugin.kag.tag["gamma"] = {};\n',
        encoding="utf-8",
    )
    assert ck.engine_tag_names(str(tmp_path)) >= {"alpha", "beta", "gamma"}


def test_se_channels_are_backed_by_real_audio():
    """The game's voice system plays through kag.se[i] from iscript
    (`kag.se[0].play(%[storage:...])` + `kag.se[0].status` + setOptions
    gvolume). A stub channel means silent voice -- the reported defect."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "var _se_make" in js
    assert "new Audio(url)" in js
    assert "status: 'stop'" in js
    assert "this.status = 'play';" in js
    # the old stub did nothing at all
    assert "play: function (o) { return this; }" not in js
    # extensionless KAG3 names must resolve through the asset map
    assert "var rel = am[__kag3_stem(st)] || am[st.toLowerCase()];" in js


def test_engine_scan_ignores_commented_out_registrations(tmp_path):
    """A commented-out registration is not a registration.

    This engine keeps `//スタイル変更は未サポート` followed by a commented-out
    `tyrano.plugin.kag.tag["style"] = {...}`. Treating that as real made the shim
    drop its no-op for [style] while the engine lacks the tag too, so every
    [style] raised "tag style does not exist" -- a Tyrano alert() that BLOCKS the
    page (reported as repeated popups, no sound, browser says unresponsive).
    """
    eng = tmp_path / "tyrano" / "plugins" / "kag"
    eng.mkdir(parents=True)
    (eng / "kag.tag.js").write_text(
        '//style changes are not supported\n'
        '/*\n'
        'tyrano.plugin.kag.tag["style"] = { start: function () {} };\n'
        '*/\n'
        'tyrano.plugin.kag.tag["real"] = { start: function () {} };\n',
        encoding="utf-8",
    )
    names = ck.engine_tag_names(str(tmp_path))
    assert "real" in names
    assert "style" not in names, "a commented-out registration must not count"


def test_js_comment_stripper():
    # a line comment is removed but the line break survives
    line = ck._strip_js_comments("//a\nb")
    assert "a" not in line and "b" in line
    assert "style" not in ck._strip_js_comments('/* tag["style"] = 1; */')
    # a string literal keeps its content, including // and /*
    keep = ck._strip_js_comments('var u = "http://x/*y";')
    assert "http://x/*y" in keep
    # code after an unterminated-looking block is still stripped
    assert "q" not in ck._strip_js_comments("/*\nq\n*/z").replace("z", "")


def test_style_and_wq_keep_their_noops():
    """Regression guard for the blocking-popup defect: the engine does not
    implement [style] (its definition is commented out) and [style] appears 59
    times in this corpus, so the shim must keep providing it."""
    eng = os.path.join(".tools", "tyranoscript")
    if not os.path.isdir(eng):
        pytest.skip("engine source not present")
    js, _n = ck._shim_js((), eng)
    assert 'define("style")' in js
    assert 'define("wq")' in js
    # tags the engine really implements must NOT be shimmed
    for real_tag in ("bg", "bgmopt", "fadeinbgm", "fadeoutse", "wa", "wb"):
        assert ('define("%s")' % real_tag) not in js, real_tag


def test_layopt_is_a_real_implementation_not_a_noop():
    """The engine has no [layopt] at all, so a no-op silently swallowed layer
    visibility (2053 call sites) and the scene could not hide a character it had
    finished with (reported as characters staying on screen).

    [layopt] must honour visible/opacity/index but NOT left/top: the game sets the
    same offset on [image] as well, and applying both compounded it (measured a
    -800px layer offset on top of the image offset), pushing the side characters
    of a multi-character shot almost completely out of frame."""
    js, _n = ck._shim_js((), None, {"layopt"})
    assert '__kag3_real' in js
    for piece in ('getLayer', 'visible', 'opacity', "j.hide()", 'z-index'):
        assert piece in js, piece
    # no layer positioning inside the LAYOPT block: the foreground position comes
    # from [image], and applying it here as well compounded the offset (measured
    # -800px). [position] is what positions message layers, so only that block may
    # set left/top.
    layopt_block = js.split('tyrano.plugin.kag.tag["layopt"]')[-1].split('T["position"]')[0]
    assert 'j.css("left"' not in layopt_block
    assert 'j.css("top"' not in layopt_block


def test_layopt_never_overrides_an_engine_implementation():
    js, _n = ck._shim_js((), None, {"layopt"})
    assert 'if (!L || L.__kag3_real) return;' in js


def test_game_button_row_is_dropped_by_default():
    """The game's own system buttons overlap the message text and call engine
    APIs Tyrano lacks; the owner judged the row unnecessary."""
    ck._DROPPED_TAGS.clear()
    ck._DROPPED_TAGS.add("button")
    try:
        kept = ck._remap_part('[button graphic="skip_bot" exp="x"]\r\n')
        assert "button" not in kept.lower()
        assert kept.endswith("\r\n"), "the line ending must survive (comment-glue bug)"
        other = ck._remap_part('[cm]\n')
        assert other == '[cm]\n'
    finally:
        ck._DROPPED_TAGS.clear()


def test_dropped_tag_keeps_line_ending_even_without_one():
    ck._DROPPED_TAGS.clear()
    ck._DROPPED_TAGS.add("button")
    try:
        assert ck._remap_part("[button graphic=x]") in ("", "\n")
    finally:
        ck._DROPPED_TAGS.clear()


def test_message_layout_does_not_hardcode_control_padding():
    """Source margins must govern each window, especially small nameplates."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "padding-right:190px" not in js
    assert "padding-bottom:44px" not in js


def test_message_layers_outrank_the_character_layers():
    """KAG3 stacks by layer number, Tyrano by DOM order, so a sprite layer ended
    up above the message window (measured: sprite z=4000 vs .message_inner
    z=1001) and painted over the dialogue."""
    js = ck.RUNTIME_SHIM_IIFE
    assert 'div[class*="message"][class*="_fore"]' in js
    assert 'div[class*="message"][class*="_back"]' in js
    assert "{z-index:8000 !important}" in js


def test_message_backing_uses_classified_mobile_surfaces():
    """Large dialogue frames and small name frames get distinct readable surfaces.

    The classifier preserves scenario geometry, while CSS removes desktop frame art.
    Unclassified message layers remain untouched.
    """
    js = ck.RUNTIME_SHIM_IIFE + ck.NOOP_PLUS_REAL_JS
    assert "kag3-dialog-frame" in js
    assert "kag3-name-frame" in js
    assert "background-image:none !important" in js
    assert "background:rgba(5,8,14,.78)" in js
    assert "left:0 !important;width:100% !important" in js
    assert "border-radius:0 !important" in js
    assert "kag3-dialog-text" in js
    assert "kag3-name-text" in js
    assert "canvasH * 0.12" in js
    assert "w >= canvasW * 0.18" in js
    assert "w < canvasW * 0.18" in js
    assert ".message_outer.kag3-aux-frame,.message_inner.kag3-aux-text" in js


def test_r_and_style_affect_appended_ch_runs():
    """KAG3 [r] must start a new line for text appended by [ch], and [style
    align=] must align it -- otherwise the choice prompt and the first option
    share one line (owner: "第一个选项不要和描述放在同一行，换一下行吧")."""
    js, _n = ck._shim_js((), None, {"ch", "r", "style"})
    assert "getMessageInnerLayer" in js
    assert "getMessageCurrentSpan" in js
    assert "setNewParagraph" in js
    assert "__kag3_break" not in js
    assert "__kag3_align" not in js
    assert "text-align" in js
    assert "kag3ch" in js


def test_configured_waits_are_dropped_in_skip_mode():
    """Tyrano drops skippable waits while skipping
    (kag.tag.js: `if (is_skip && pm.skippable === "true") nextOrder()`), and
    [l]/[p] return early too. The shim's own click-skippable wait must do the
    same or every wait during skip runs its full duration, which is what made
    fast-forwarding feel slow."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "if (kag.stat.is_skip) { return kag.ftag.nextOrder(); }" in js


def test_skip_speed_is_configured_below_the_template_default():
    """The template's 30 ms per line caps skipping at ~33 lines/s, so the
    converter lowers it (measured: 13.7 tags/s before, dominated by the driver
    gate rather than this value; 1 ms removes this cap entirely). Asserted
    through the source because it is applied by the Config.tjs rewrite in
    cli.convert() (the converter is split by concern -- kirikiri/kag/)."""
    import inspect

    src = inspect.getsource(ck.convert)
    assert "skipSpeed" in src
    assert ";skipSpeed = 1;" in src


def test_fast_skip_driver_gate_and_scheduling():
    """The driver must keep the gate that was measured to work, and must never
    spin.

    It advances only when the topmost element at the screen centre is the event
    layer, so choices/menus are never skipped through (measured 13.7 tags/s).
    A wider gate was tried and advanced NOTHING (every tick refused during the
    opening). A self-scheduling setTimeout(tick, 0) version was also tried and
    was wrong: a 0 ms loop keeps the main thread saturated (the browser reports
    "page unresponsive" and audio is starved). It runs on a plain interval and
    returns immediately unless skip is on. The message window's visibility must
    NOT be a condition: hidden-window sections then refused every tick and skip
    appeared to do nothing at all.
    """
    js = ck.FAST_SKIP_SHIM_JS
    assert 'indexOf("layer_event_click")' in js
    assert "setInterval" in js, "a 0 ms self-scheduling loop saturates the main thread"
    assert "setTimeout(tick, 0)" not in js
    assert "is_strong_stop" in js
    assert "is_hide_message" not in js


def test_ch_renders_message_text_instead_of_being_a_noop():
    """[ch text=X] is how this game outputs BOTH dialogue and every choice item.
    As a no-op the choice text never appeared: [SELECT_CENTER] expands to
    [link ...][font color=0xFFFF00][ch text="%sel_1"][font color="default"][endlink]
    so the player got an empty message with invisible clickable areas."""
    js, _n = ck._shim_js((), None, {"ch"})
    assert "ch.__kag3_real" in js
    assert "kag3ch" in js                      # the appended text container
    assert 'cssColor' in js                      # [font color=0xRRGGBB] support
    assert 'T["font"]' in js or "T['font']" in js


def test_ch_uses_the_active_link_span_without_creating_paragraphs():
    """Choice text must remain inside exactly the link span Tyrano created."""
    js, _n = ck._shim_js((), None, {"ch", "link", "endlink"})
    assert "this.kag.getMessageInnerLayer()" in js
    assert "this.kag.getMessageCurrentSpan()" in js
    assert "$current.append($s)" in js
    assert "this.kag.setNewParagraph($i)" in js
    assert "<p class=\"kag3ch\"" not in js
    assert '$(".message_inner")' not in js.split('var ch = T["ch"]', 1)[1].split(
        "// [r]", 1)[0]


def test_font_colour_recording_is_wrapped_once():
    js, _n = ck._shim_js((), None, {"ch"})
    assert "__kag3_wrapped" in js


def test_position_delegates_complete_geometry_to_native_tag():
    """Frame resolution must happen before native outer/inner layout."""
    js, _n = ck._shim_js((), None, {"position", "locate"})
    pos = js.split('T["position"]')[-1].split('T["locate"]')[0]
    assert "__kag3_asset_path" in pos
    assert "probe.onload" in pos
    assert "args.width" in pos and "args.height" in pos
    assert "_ps.call(owner, args)" in pos
    assert 'outer.css("background-color"' in pos
    assert '"./data/image/" + path' in pos
    for geom in ('j.css("left"', 'j.css("top"', 'j.css("width"', 'j.css("height"'):
        assert geom not in pos, geom


def test_ch_composed_messages_are_exempt_from_the_hard_clip():
    """The dialogue window is 113px tall; choice items need more room, so the
    windows our [ch] writes into must not be clipped."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "kag3ch-msg" in js
    assert ".message_inner.kag3ch-msg{overflow:visible !important}" in js
    assert ".message_inner{overflow:hidden}" in js   # dialogue keeps the clip
    assert "margin:0 !important;padding:0 !important" in js


def test_link_ch_runs_form_one_touch_friendly_choice_panel():
    """Only [ch] runs owned by a link become choice items.

    Plain [ch] is also used by name plates, so classifying every run as a choice
    would move speaker names into the centre of the screen.
    """
    js = ck.RUNTIME_SHIM_IIFE + ck.NOOP_PLUS_REAL_JS
    assert '$current.hasClass("event-setting-element")' in js
    assert '$current.addClass("kag3-choice-item")' in js
    assert '$i.addClass("kag3-choice")' in js
    assert '$i.closest(".layer").addClass("kag3-choice-layer")' in js
    assert '"kag3-choice-prompt" : "kag3-choice-gap"' in js
    assert ".message_inner.kag3-choice{" in js
    assert ".kag3-choice-layer .message_outer{display:none !important}" in js
    assert ".kag3-choice-item span{" in js
    assert "color:#fff !important" in js
    assert ".kag3-choice-item>img{" in js
    assert "display:none !important" in js
    assert '$i.removeClass("kag3-choice")' in js
    assert '$i.find(".kag3-choice-item,.kag3-choice-prompt,.kag3-choice-gap").remove()' in js
    assert "window.__kag3_choice_cleanup" in js
    assert "var $owner = $(item).closest('.message_inner')" in js
    assert "var $old = $owner.find('.kag3-choice-item,.kag3-choice-prompt,.kag3-choice-gap')" in js
    assert "$old.remove()" in js
    assert "if (!$owner.find('.kag3-choice-item').length)" in js
    assert "$owner.attr('data-kag3-choice-exiting', '1')" in js
    assert "window.__kag3_prepare_message(this.kag)" in js
    assert "window.__kag3_prepare_message(kag)" in js
    assert "ownerKag.setNewParagraph($inner)" in js


def test_gallery_runtime_expands_layers_and_searches_full_scenario():
    """Large KAG3 galleries need numeric layers and long condition searches."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "kag.layer.addLayer(String(i))" in js
    assert "this.array_tag.length - this.current_order_index" in js
    assert "if (this.nextOrderWithTag(targetTags)) return true" in js
    assert "window.Debug = window.Debug || { message: function () {} }" in js


def test_empty_foreground_layers_do_not_block_click_waits():
    """Full-canvas numeric layers must pass clicks through to the event layer."""
    js = ck.RUNTIME_SHIM_IIFE
    assert ".layer_fore{pointer-events:none !important}" in js
    assert ".layer_fore>*{pointer-events:auto !important}" in js


def test_map_switch_coerces_tjs_numeric_values_to_case_strings():
    """KAG map actions commonly compare numeric state with quoted cases."""
    js = ck.RUNTIME_SHIM_IIFE
    assert r"source.replace(/\bswitch\s*\(([^()]*)\)/g, 'switch(String($1))')" in js


def test_state_overrides_load_supported_namespaces(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"sf":{"gallery_open":1},"tf":{"mode":"view"}}',
                    encoding="utf-8")
    assert ck._load_state_overrides(str(path)) == {
        "sf": {"gallery_open": 1},
        "tf": {"mode": "view"},
    }


def test_generated_make_ks_is_a_return_passthrough(tmp_path):
    # Tyrano restores a save by inserting [call storage="make.ks"] before the
    # saved position; without the file the engine raises a BLOCKING alert
    # ("ファイルが見つかりませんでした。 / ./data/scenario/make.ks") and loading a
    # save freezes the page.  KAG3 ships no make.ks, so the converter writes the
    # engine's own pass-through.  (Reached through the module, not the compat
    # layer: convert_kag re-exports a fixed surface on purpose.)
    from kirikiri.kag import cli as kag_cli
    assert kag_cli._write_make_ks(str(tmp_path)) is True
    text = (tmp_path / "make.ks").read_text(encoding="utf-8")
    assert "[return]" in text
    # an existing file (a game that ships one) must never be overwritten
    (tmp_path / "make.ks").write_text("[return]\n; game own\n", encoding="utf-8")
    assert kag_cli._write_make_ks(str(tmp_path)) is False
    assert "game own" in (tmp_path / "make.ks").read_text(encoding="utf-8")


def test_state_overrides_accept_a_utf8_bom(tmp_path):
    # The override file is hand-edited on Windows, where editors add a BOM;
    # utf-8 decoding turned that into a JSONDecodeError and the converter
    # exited 2 talking about broken JSON.
    path = tmp_path / "bom.json"
    path.write_bytes(
        '\ufeff{"sf":{"seen_max":11}}'.encode("utf-8"))
    assert ck._load_state_overrides(str(path)) == {"sf": {"seen_max": 11}}


def test_state_overrides_reject_invalid_shapes_and_namespaces(tmp_path):
    invalid = [
        "[]",
        '{"global":{"open":1}}',
        '{"sf":[1]}',
        '{"sf":{"__proto__":{}}}',
    ]
    for index, source in enumerate(invalid):
        path = tmp_path / ("bad-%d.json" % index)
        path.write_text(source, encoding="utf-8")
        with pytest.raises(ValueError):
            ck._load_state_overrides(str(path))


def test_state_overrides_runtime_targets_tyrano_variables():
    js = ck._state_overrides_js({"sf": {"gallery_open": 1}})
    assert 'window.__kag3_state_overrides = {"sf":{"gallery_open":1}}' in js
    assert "f: kag.stat.f" in js
    assert "sf: kag.variable.sf" in js
    assert "tf: kag.variable.tf" in js
    assert "JSON.parse(JSON.stringify" in js
    assert "setInterval(window.__kag3_apply_state_overrides, 100)" in js


def test_empty_state_overrides_emit_no_runtime():
    assert ck._state_overrides_js({}) == ""


def test_animation_plugin_asset_falls_back_to_representative_frame():
    """Missing animation descriptors use their converted still frame."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "key.charAt(0) === 'a'" in js
    assert "__kag3_assets()[key.slice(1)]" in js


def test_choice_jump_hotkey_recognises_macro_variants_but_not_cleanup_tags():
    """Debug jumping covers select_* macros without landing on clear/off helpers."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "/^select(?:_|$)/" in js
    assert "/(?:clear|off)$/" in js


def test_ch_skips_empty_runs():
    """An empty [ch] run must not open a paragraph: it costs a whole line and
    pushes later choice items out of the window."""
    js, _n = ck._shim_js((), None, {"ch"})
    assert "u3000" in js          # ideographic space is treated as empty


def test_collect_tag_usage_records_count_attrs_and_examples(tmp_path):
    """The inventory must say how a tag is actually called: without the call sites
    and argument names, reimplementing it later is guesswork."""
    game = tmp_path / "scenario"
    game.mkdir(parents=True)
    (game / "a.ks").write_text(
        "[T_BMP bmp_c=\"x\" place=1]\n"
        "; [T_BMP ignored=1]\n"          # comment: not a call site
        "[iscript]\n[T_BMP nope=1]\n[endscript]\n"
        "[T_BMP bmp_l=\"y\" place=0]\n",
        encoding="utf-8")
    usage = ck.collect_tag_usage(str(tmp_path))
    rec = usage["t_bmp"]
    assert rec["count"] == 2, rec
    assert set(rec["attrs"]) == {"bmp_c", "bmp_l", "place"}
    assert any("a.ks:1:" in e for e in rec["examples"])
    assert len(rec["examples"]) <= 3


def test_tag_intent_uses_the_curated_note_then_falls_back_to_arguments():
    usage = {"t_bmp": {"count": 2, "attrs": {"place": 1}, "examples": []},
             "mystery": {"count": 1, "attrs": {"foo": 1, "bar": 1}, "examples": []}}
    assert "sprite" in ck.tag_intent("t_bmp", usage)
    note = ck.tag_intent("mystery", usage)
    assert "foo" in note and "bar" in note
    assert ck.tag_intent("nothing", usage).startswith("unknown")


def test_shim_annotates_every_stub_with_its_intent():
    usage = {"t_bmp": {"count": 748, "attrs": {"place": 700},
                       "examples": ["newgame.ks:193: [T_BMP place=0]"]}}
    js, _n = ck._shim_js((), None, {"t_bmp"}, usage)
    block = js.split("// [t_bmp]")[1].split("define(")[0]
    assert "748 call site(s)" in block
    assert "arguments seen: place" in block
    assert "newgame.ks:193" in block
    assert "INTENT:" in block and "sprite" in block


def test_write_intents_emits_a_machine_readable_inventory(tmp_path):
    usage = {"t_bmp": {"count": 3, "attrs": {"place": 2}, "examples": ["x.ks:1: [t]"]}}
    path = ck.write_intents(str(tmp_path), usage, ["t_bmp", "unused_tag"],
                            dropped=["button"], degraded=["slide.ks"])
    data = json.load(open(path, encoding="utf-8"))
    tags = {e["tag"]: e for e in data["stubbed_tags"]}
    assert tags["t_bmp"]["calls"] == 3
    assert tags["t_bmp"]["intent"].startswith("display a character sprite")
    assert tags["unused_tag"]["calls"] == 0          # still listed, marked unused
    assert data["dropped_tags"] == ["button"]
    assert data["degraded_files"] == ["slide.ks"]
    assert "intent" in data["note"].lower()
