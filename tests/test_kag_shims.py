#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the KAG3 converter split: shim asset loading, the compatibility
layer, and the packaging declaration that keeps the assets shippable.

The shim text moved out of Python string literals into real files
(`kirikiri/kag/js/`).  That trade (reviewable, syntax-highlighted JS) is only
safe if the loader is exact: one trailing newline dropped, LF only, and every
template marker expanded.  These tests pin exactly those invariants -- the
converter's byte-identical output gate covers the rest.
"""
import ast
import os
import sys
import tomllib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri import convert_kag as ck  # noqa: E402
from kirikiri.kag import cli as kag_cli  # noqa: E402
from kirikiri.kag import shims  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(REPO, "kirikiri", "kag", "js")
SHIM_FILES = ("runtime_shim.js", "map_engine.js", "noop_plus_real.js",
              "video_shim.js", "waitskip_shim.js", "fast_skip.js",
              "portrait.css")


class TestShimAssets:
    def test_every_shim_asset_is_lf_only(self):
        for name in SHIM_FILES:
            blob = open(os.path.join(JS_DIR, name), "rb").read()
            assert b"\r" not in blob, "%s must be LF only (no CRLF)" % name

    def test_every_shim_asset_ends_with_a_newline_but_no_blank_line(self):
        """One final newline for editors/git, which the loader drops.

        A trailing newline *inside* the JS text is legitimate (map_engine.js
        ends with one, and the generated output must keep it), so the bound is
        "no trailing blank line", not "no double newline".
        """
        for name in SHIM_FILES:
            blob = open(os.path.join(JS_DIR, name), "rb").read()
            assert blob.endswith(b"\n"), name
            assert not blob.endswith(b"\n\n\n"), \
                "%s: trailing blank lines would shift the generated output" % name

    def test_assets_are_not_empty_and_are_real_text(self):
        for name in SHIM_FILES:
            blob = open(os.path.join(JS_DIR, name), "rb").read()
            assert len(blob) > 200, name
            blob.decode("utf-8")                     # must be valid UTF-8

    def test_shim_text_drops_exactly_the_final_newline(self):
        for name in SHIM_FILES:
            blob = open(os.path.join(JS_DIR, name), "rb").read()
            expected = blob.decode("utf-8")[:-1]
            assert shims._shim_text(name) == expected


class TestDecodeShim:
    """The loader seam (`_decode_shim`) is exercised directly so a crafted
    input cannot be produced accidentally by the real assets."""

    def test_crlf_is_rejected(self):
        with pytest.raises(ValueError, match="LF line endings"):
            shims._decode_shim(b"a\r\nb\r\n", "x.js")

    def test_single_trailing_newline_is_dropped(self):
        assert shims._decode_shim(b"body\n", "x.js") == "body"

    def test_only_one_trailing_newline_is_dropped(self):
        assert shims._decode_shim(b"body\n\n", "x.js") == "body\n"

    def test_missing_trailing_newline_is_kept(self):
        assert shims._decode_shim(b"body", "x.js") == "body"

    def test_non_utf8_is_an_error(self):
        with pytest.raises(UnicodeDecodeError):
            shims._decode_shim(b"\x81\x30", "x.js")


class TestRuntimeShimAssembly:
    def test_markers_are_expanded(self):
        js = shims.RUNTIME_SHIM_IIFE
        assert "__KAG3_INCLUDE" not in js, "a template marker leaked into the output"
        for piece in (shims.MAP_ENGINE_JS, shims.VIDEO_SHIM_JS,
                      shims.WAITSKIP_SHIM_JS):
            assert piece in js

    def test_missing_marker_is_an_error(self):
        with pytest.raises(ValueError, match="marker"):
            shims._assemble("runtime_shim.js", (("NOT_IN_TEMPLATE", "x"),))

    def test_runtime_shim_ends_without_trailing_newline(self):
        """It is concatenated with per-game JS; a trailing blank line would
        change the generated plugin file."""
        assert not shims.RUNTIME_SHIM_IIFE.endswith("\n")


class TestMacroReturnCompat:
    """KAG3 expands macros at parse time, so a `[return]` inside a macro body is
    a plain tag in the caller's order stream and returns from the enclosing
    `[call]`.  Tyrano runs macros with a runtime frame stack and its own
    `[return]` resumes the *macro's* caller, leaving the frame behind (the
    engine documents it: "だからmacro で return は使えない").

    Measured: a gallery replay ended with `[if exp="tf.now_pv == 1"][return]
    [endif]` inside a macro, and the flow fell back into the story instead of
    returning to the gallery.  The shim therefore stamps the macro depth on
    every call-stack entry and truncates it before the engine's return.
    """

    def test_shim_stamps_macro_depth_on_call(self):
        js = shims.RUNTIME_SHIM_IIFE
        assert "kag.pushStack = function" in js
        assert "__kag3_macro_depth" in js
        assert "kag.stat.stack.macro || []" in js

    def test_shim_wraps_the_return_tag(self):
        js = shims.RUNTIME_SHIM_IIFE
        assert "master_tag['return']" in js
        assert "kag.getStack('call')" in js
        assert "kag.__kag3_return_patched" in js, "the patch must be idempotent"

    def test_frames_are_dropped_before_the_engine_return_runs(self):
        js = shims.RUNTIME_SHIM_IIFE
        start = js.index("master_tag['return']")
        tail = js[start:start + 1500]
        assert "frames.length = top[_macroDepthKey]" in tail
        assert "_returnStart.apply(this, arguments)" in tail
        assert tail.index("frames.length = top[_macroDepthKey]") < \
            tail.index("_returnStart.apply(this, arguments)"), \
            "the macro frames must be truncated before delegating to the engine"

    def test_patch_lives_in_the_runtime_shim_source(self):
        raw = open(os.path.join(JS_DIR, "runtime_shim.js"), encoding="utf-8").read()
        assert "__kag3_return_patched" in raw


class TestCompatLayer:
    """`kirikiri/convert_kag.py` is a re-export shim, not a second home."""

    def test_it_defines_no_functions_or_classes(self):
        src = open(os.path.join(REPO, "kirikiri", "convert_kag.py"),
                   encoding="utf-8").read()
        tree = ast.parse(src)
        assert not [n for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.ClassDef))], \
            "the compatibility layer must only re-export"

    def test_names_used_by_scripts_and_tests_are_reexported(self):
        # the names the owner's one-off probes and the test-suite touch
        for name in ("main", "convert", "RUNTIME_SHIM_IIFE", "MAP_ENGINE_JS",
                     "FAST_SKIP_SHIM_JS", "NOOP_PLUS_REAL_JS", "VIDEO_SHIM_JS",
                     "WAITSKIP_SHIM_JS", "PORTRAIT_CSS", "convert_ks_line",
                     "convert_scenario_file", "_shim_js", "_asset_map",
                     "_layer_map", "_find_asset", "_decoder_mtime",
                     "_strip_continuation", "_ASSET_CACHE", "_DROPPED_TAGS",
                     "detect_encoding", "tlg", "tjs2js"):
            assert hasattr(ck, name), "missing re-export: %s" % name

    def test_reexports_are_the_same_objects(self):
        assert ck.convert is kag_cli.convert
        assert ck.RUNTIME_SHIM_IIFE is shims.RUNTIME_SHIM_IIFE
        assert ck.convert_ks_line.__module__ == "kirikiri.kag.scenario"

    def test_mutable_module_state_is_shared_not_copied(self):
        """`_ASSET_CACHE`/`_DROPPED_TAGS` are mutated by convert(); a copy
        would silently detach the convert() in cli.py from the probes."""
        from kirikiri.kag import assets as kag_assets
        from kirikiri.kag import tags as kag_tags

        assert ck._ASSET_CACHE is kag_assets._ASSET_CACHE
        assert ck._DROPPED_TAGS is kag_tags._DROPPED_TAGS


class TestCliConventions:
    def test_no_argparse_in_the_converter(self):
        src = open(os.path.join(REPO, "kirikiri", "kag", "cli.py"),
                   encoding="utf-8").read()
        code = ast.parse(src)
        for node in ast.walk(code):
            if isinstance(node, ast.Import):
                assert all(a.name != "argparse" for a in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module != "argparse"

    def test_cli_configures_logging_through_cliutil(self):
        """logsetup is the single logging entry point: the converter must not
        configure logging itself (it used to call logging.basicConfig)."""
        src = open(os.path.join(REPO, "kirikiri", "kag", "cli.py"),
                   encoding="utf-8").read()
        assert "basicConfig" not in src
        assert "cliutil.setup_logging(" in src

    def test_programmatic_entry_is_keyword_only(self):
        """convert() is called by the CLI and by tests; positional misuse would
        silently swap two paths."""
        sig = ast.parse(open(os.path.join(REPO, "kirikiri", "kag", "cli.py"),
                             encoding="utf-8").read())
        fn = next(n for n in sig.body
                  if isinstance(n, ast.FunctionDef) and n.name == "convert")
        assert fn.args.kwonlyargs, "convert() must keep its keyword-only arguments"
        assert not fn.args.args, "convert() takes no positional arguments"

    def test_cli_exposes_verbose_quiet_and_log_file(self):
        src = open(os.path.join(REPO, "kirikiri", "kag", "cli.py"),
                   encoding="utf-8").read()
        for opt in ("cliutil.Verbose", "cliutil.Quiet", "cliutil.LogFile"):
            assert opt in src


class TestGalleryReplayUX:
    """Gallery-replay quality fixes measured against the running build.

    (1) Several scene entries open with the gallery/menu track itself
    (``[BGM bgm="bgm010"]``); Tyrano skips a same-storage ``[playbgm]``, so
    the menu music ran seamlessly through the replay.  (2) The game disarms
    its own right-click return while a replay runs, leaving touch players
    no way back.  (3) The gallery mpeg player's KAG3 box (800x600) leaves a
    black strip on the 1024x768 canvas.  (4) Experimental bare message style.
    """

    def test_playbgm_restart_wrapper_installed_after_the_storage_wrapper(self):
        raw = open(os.path.join(JS_DIR, "runtime_shim.js"), encoding="utf-8").read()
        assert "__kag3_pv_restart" in raw
        assert "now_pv == 1" in raw
        # target=se ([playse] delegates to [playbgm] internally) must be
        # excluded, and the compare must be stem-based (bare name vs resolved
        # ../bgm/x.ogg path).
        assert "!== 'se'" in raw
        assert "toLowerCase()" in raw
        # the restart wrapper must run BEFORE the storage resolver's wrapper
        # (last installed runs first), i.e. be installed after it
        assert raw.index("_wrap_storage('playbgm')") < \
            raw.index("__kag3_pv_restart")

    def test_replay_exit_button_wires_the_game_return_label(self):
        raw = open(os.path.join(JS_DIR, "runtime_shim.js"), encoding="utf-8").read()
        assert "__kag3_context_return" in raw
        # the exit action lives in the mobile control row (a separate floating
        # button overlapped the menu key -- owner-reported)
        assert "data-kag3-action=gallery" in raw
        assert "__kag3_exit_replay" in raw
        assert "__kag3_exit_available" in raw
        assert "now_pv == 1" in raw
        # the button abandons the replay frames instead of leaving them
        # dangling under the gallery (KAG3 rclick-jump = process())
        assert "stack.call.length = 0" in raw
        assert "stack.macro.length = 0" in raw
        assert "__kag3_jump(kag, __kag3_context_return.storage" in raw
        # only a *return_* label is remembered as the exit target
        assert "/return/i.test" in raw
        # the row must refresh itself: a replay can start without panel input
        assert "setInterval(sync, 500)" in raw

    def test_video_fill_branch_is_gated_on_the_injected_flag(self):
        raw = open(os.path.join(JS_DIR, "video_shim.js"), encoding="utf-8").read()
        assert "window.__kag3_video_fill" in raw
        assert "this.style.minWidth = '100%'" in raw
        assert "this.style.objectFit = 'contain'" in raw

    def test_playvideo_is_not_silent_by_default(self):
        """Tyrano's movie layer defaults to `video.volume = 0`; a KAG3
        [playvideo] carries its own audio, so the shim must pass a volume."""
        raw = open(os.path.join(JS_DIR, "video_shim.js"), encoding="utf-8").read()
        assert "opt.volume" in raw
        assert "'100'" in raw
        assert "v.volume" in raw, "a game-specified volume must pass through"

    def test_bare_message_style_is_gated_and_scoped(self):
        raw = open(os.path.join(JS_DIR, "runtime_shim.js"), encoding="utf-8").read()
        assert "window.__kag3_msg_style === 'bare'" in raw
        # message1 is the name plate; the bare style must not touch it
        assert "message0" in raw
        assert "div[class*='message1']" not in raw
        assert "opacity:.8" in raw

    def test_cli_plumbs_the_new_knobs(self):
        import inspect
        sig = inspect.signature(kag_cli.convert)
        assert sig.parameters["video_fit"].default == "box"
        assert sig.parameters["msg_style"].default == "plate"
        src = open(os.path.join(REPO, "kirikiri", "kag", "cli.py"),
                   encoding="utf-8").read()
        assert "--video-fit" in src
        assert "--msg-style" in src
        # and the flags actually reach the generated plugin file
        assert "window.__kag3_video_fill" in src
        assert "window.__kag3_msg_style" in src


class TestPackaging:
    """A non-editable install must ship the shim assets: they are read through
    importlib.resources, so a missing package-data entry breaks the converter
    only in a wheel (never in the repo checkout)."""

    def test_package_and_package_data_are_declared(self):
        with open(os.path.join(REPO, "pyproject.toml"), "rb") as f:
            cfg = tomllib.load(f)
        packages = cfg["tool"]["setuptools"]["packages"]
        assert "kirikiri.kag" in packages
        data = cfg["tool"]["setuptools"]["package-data"]
        assert data["kirikiri.kag"] == ["js/*.js", "js/*.css"]
