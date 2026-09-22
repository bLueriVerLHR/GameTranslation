#!/usr/bin/env python3
"""Unit tests for tyrano/autoplay.py ([bgmovie] autoplay-policy fix).

The engine's kag.tag_ext.js calls <video>.play() inside event handlers
that are not backed by user activation, so browsers/WebViews reject the
promise and wait_bgmovie hangs forever.  The fix wraps every .play()
call so a rejected promise attaches one-shot click/touchstart/keydown
listeners that replay the video on first user interaction.

The expected wrapped form below is byte-identical to the patch that was
hand-applied and shipped in a real delivered build (round-trip verified).
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tyrano import autoplay  # noqa: E402

KAG_REL = os.path.join("tyrano", "plugins", "kag", "kag.tag_ext.js")

# The exact wrapped call from the shipped build (video2 = stacked movie).
WRAPPED_VIDEO2 = (
    'var _p=video2.play();if(_p&&_p.catch){_p.catch(function(){'
    'var _u=function(){video2.play();'
    'document.removeEventListener("click",_u);'
    'document.removeEventListener("touchstart",_u);'
    'document.removeEventListener("keydown",_u)};'
    'document.addEventListener("click",_u);'
    'document.addEventListener("touchstart",_u);'
    'document.addEventListener("keydown",_u)})}'
)
# Original call site as it appears in the shipped engine (no trailing
# semicolon in the minified file: play()j_video2.css relies on ASI).
ORIGINAL_VIDEO2 = "video2.play()"

# Same wrap for the plain video element.
WRAPPED_VIDEO = WRAPPED_VIDEO2.replace("video2", "video")


def write_kag(root, text):
    path = os.path.join(root, KAG_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestPatchAutoplay:
    def test_wraps_every_play_call(self, tmp_path):
        root = str(tmp_path)
        write_kag(root, 'var a="x";video.play();video2.play();')
        assert autoplay.patch_autoplay(root) == 2
        text = open(os.path.join(root, KAG_REL), encoding="utf-8").read()
        assert text.count("_p&&_p.catch") == 2
        assert WRAPPED_VIDEO2 in text
        assert WRAPPED_VIDEO in text

    def test_shipped_form_byte_identical(self, tmp_path):
        """Original -> patch must equal the exact text shipped in a real
        delivered build (known-good reference)."""
        root = str(tmp_path)
        write_kag(root, ORIGINAL_VIDEO2)
        assert autoplay.patch_autoplay(root) == 1
        text = open(os.path.join(root, KAG_REL), encoding="utf-8").read()
        assert text == WRAPPED_VIDEO2

    def test_idempotent_second_run_skips(self, tmp_path):
        root = str(tmp_path)
        write_kag(root, 'video.play();')
        assert autoplay.patch_autoplay(root) == 1
        before = open(os.path.join(root, KAG_REL), encoding="utf-8").read()
        assert autoplay.patch_autoplay(root) == 0
        after = open(os.path.join(root, KAG_REL), encoding="utf-8").read()
        assert after == before

    def test_pre_patched_file_left_untouched(self, tmp_path):
        root = str(tmp_path)
        write_kag(root, "var x=1;" + WRAPPED_VIDEO2)
        assert autoplay.patch_autoplay(root) == 0
        text = open(os.path.join(root, KAG_REL), encoding="utf-8").read()
        assert text == "var x=1;" + WRAPPED_VIDEO2

    def test_no_play_calls_is_noop(self, tmp_path):
        root = str(tmp_path)
        write_kag(root, "var a=1;var b=2;")
        assert autoplay.patch_autoplay(root) == 0
        text = open(os.path.join(root, KAG_REL), encoding="utf-8").read()
        assert text == "var a=1;var b=2;"

    def test_other_receiver_names_wrapped(self, tmp_path):
        """The engine version may name its video variable differently;
        the fix must wrap any element .play() call."""
        root = str(tmp_path)
        write_kag(root, "movie.play();clip.play();")
        assert autoplay.patch_autoplay(root) == 2
        text = open(os.path.join(root, KAG_REL), encoding="utf-8").read()
        assert text.count("_p&&_p.catch") == 2
        assert "var _p=movie.play()" in text and "var _p=clip.play()" in text

    def test_missing_file_returns_none(self, tmp_path):
        root = str(tmp_path / "empty")
        os.makedirs(root)
        assert autoplay.patch_autoplay(root) is None
