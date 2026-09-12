"""Unit tests for kirikiri/convert_kag.py (KAG3 -> TyranoScript converter)."""

import os
import sys
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

    def test_at_syntax_converted(self, fake_unpacked):
        out = ck.convert_ks_line("@s\n", str(fake_unpacked), set(), False)
        assert out.strip() == "[s]"

    def test_label_kept(self, fake_unpacked):
        out = ck.convert_ks_line("*start|タイトル\n", str(fake_unpacked), set(), False)
        assert out.strip() == "*start|タイトル"

    def test_comment_kept(self, fake_unpacked):
        out = ck.convert_ks_line("; comment\n", str(fake_unpacked), set(), False)
        assert out.strip() == "; comment"

    def test_multitag_split(self, fake_unpacked):
        out = ck.convert_ks_line('[if exp="sf.mpg_mode==0"][image storage="black" layer=4][endif]\n',
                                 str(fake_unpacked), set(), False)
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 3
        assert lines[0].startswith("[if")

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


def test_decoder_mtime_tracks_only_the_image_decoder():
    """The image cache must invalidate when the decoder changes, but not when
    unrelated converter code changes.

    Including convert_kag.py in the decoder timestamp meant every shim or
    scenario tweak reconverted all 748 images (~35 min per edit), which defeats
    the cache; omitting the decoder entirely meant a decoder fix silently kept
    serving images built by the old one.
    """
    from kirikiri import tlg as ktlg

    mtime = ck._decoder_mtime()
    assert mtime > 0
    assert abs(mtime - os.path.getmtime(ktlg.__file__)) < 1.0
    assert mtime < os.path.getmtime(ck.__file__), (
        "convert_kag.py itself must not be part of the image cache key")


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
    assert "'.message_inner[data-kag3-fit]>p>span{font-size:inherit !important;'" in js
    assert "line-height:inherit !important}'" in js
    # the concatenated statement ends with a terminator before the append
    assert "line-height:inherit !important}';" in js, js[-700:]


def test_message_text_is_clipped_to_its_window():
    """Hard guarantee: dialogue can never paint over the bottom-right UI."""
    assert ".message_inner{overflow:hidden}" in ck.RUNTIME_SHIM_IIFE


def test_fit_only_overrides_a_message_it_marked():
    """The engine writes each message's font-size/line-height as inline styles
    on the <span> (kag.tag.js), so a fit applied to .message_inner needs those
    turned into inheritance -- but only for a marked element, otherwise an
    unmarked message would lose the engine's own styling."""
    js = ck.RUNTIME_SHIM_IIFE
    assert ".message_inner[data-kag3-fit]>p," in js
    assert "el.removeAttribute('data-kag3-fit')" in js
    assert "el.setAttribute('data-kag3-fit', '1')" in js


def test_message_text_is_squeezed_back_into_its_window():
    """Tyrano's default line box is taller than KAG3's, so a three-line KAG3
    message can outgrow the window. The fit must measure without its own
    overrides, recover the engine's per-message font size (stored scale in
    data-kag3-k), then squeeze line height and font size until it fits."""
    js = ck.RUNTIME_SHIM_IIFE
    assert "window.__kag3_fit_message" in js
    assert "el.scrollHeight <= el.clientHeight + 1" in js
    assert "setTimeout(run, 150)" in js  # debounce: no per-frame reflow
    assert "data-kag3-k" in js
    assert "span.style.fontSize" in js  # the engine's own request is the base


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


def test_message_window_gets_a_translucent_backing():
    """KAG3 games usually draw a transparent message window over the CG art,
    so dialogue sits directly on the picture and is hard to read. The backing
    goes behind .message_outer (the window frame AND the name plate, which is
    another message layer)."""
    js = ck.RUNTIME_SHIM_IIFE
    assert ".message_outer{background-color:rgba(0,0,0,.5)" in js, js[:400]


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
    through the source because it is applied by main()'s Config.tjs rewrite."""
    import inspect

    src = inspect.getsource(ck.main)
    assert "skipSpeed" in src
    assert ";skipSpeed = 1;" in src


def test_fast_skip_driver_gate_and_scheduling():
    """The driver must keep the gate that was measured to work.

    It advances only when the topmost element at the screen centre is the event
    layer (so choices/menus are never skipped through; measured 13.7 tags/s).
    A wider gate was tried and advanced NOTHING (every tick refused during the
    opening), so the strict rule stays and the rate comes from self-scheduling
    plus config.skipSpeed = 1. The message window's visibility must NOT be a
    condition: sections that run with a hidden window (common in openings)
    then refused every tick and skip appeared to do nothing at all.
    """
    js = ck.FAST_SKIP_SHIM_JS
    assert 'indexOf("layer_event_click") >= 0' in js
    assert "setTimeout(tick, 0)" in js  # self-scheduling, not a 30 ms interval
    assert "setInterval" not in js
    assert "is_strong_stop" in js
    assert "is_hide_message" not in js
