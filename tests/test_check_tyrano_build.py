#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the TyranoScript play-test gate's pure logic (no browser needed)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import check_tyrano_build as G  # noqa: E402


def snap(text=(100, 200, 300, 240), inner_z=8000, imgs=(), windows=None, ctrl=(),
         fonts=None, base=(0, 0, 1024, 768)):
    return {
        "base": list(base) if base else None,
        "text": list(text) if text else None,
        "innerZ": inner_z,
        "imgs": [dict(src=s, rect=list(r), z=z) for s, r, z in imgs],
        "windows": windows if windows is not None else [
            {"rect": [90, 190, 320, 250], "z": inner_z, "text": list(text) if text else [0, 0, 0, 0]}],
        "ctrl": [list(c) for c in ctrl],
        "fonts": fonts if fonts is not None else {"22px": 10},
        "chars": 10,
    }


def test_clean_state_has_no_violations():
    assert G.judge(snap()) == []


def test_detects_a_sprite_painted_over_the_text():
    """The regression the owner reported: a sprite layer above the message.

    This is the measured historical state -- sprite layer z=4000 against a
    message layer at z=1001 -- which is why the message layer now gets 8000.
    """
    s = snap(inner_z=1001, imgs=[("image/y.png", (50, 150, 400, 300), 4000)])
    notes = G.judge(s)
    assert any(n.startswith("Z-ORDER") for n in notes), notes


def test_detects_a_sprite_above_even_the_raised_message_layer():
    s = snap(inner_z=8000, imgs=[("image/y.png", (50, 150, 400, 300), 9000)])
    assert any(n.startswith("Z-ORDER") for n in G.judge(s))


def test_an_image_below_the_text_is_fine():
    s = snap(imgs=[("image/y.png", (50, 150, 400, 300), 3000)])
    assert G.judge(s) == []


def test_detects_text_outside_its_own_window():
    s = snap(windows=[{"rect": [100, 210, 300, 240], "z": 8000,
                       "text": [100, 200, 300, 240]}])
    assert any(n.startswith("FIT") for n in G.judge(s))


def test_a_hidden_window_is_not_judged():
    s = snap(windows=[{"rect": [0, 0, 0, 0], "z": 0, "text": [100, 200, 300, 240]}])
    assert G.judge(s) == []


def test_name_plate_and_body_are_judged_separately():
    """The name plate is its own message layer, above the body window; judging
    a union of both texts against one window produced false failures."""
    s = snap(windows=[
        {"rect": [90, 190, 320, 250], "z": 8000, "text": [100, 200, 300, 240]},
        {"rect": [90, 120, 320, 170], "z": 8000, "text": [100, 125, 200, 165]}])
    assert G.judge(s) == []


def test_detects_an_oversized_image():
    s = snap(imgs=[("image/big.png", (0, 0, 1200, 900), 3000)])
    assert any(n.startswith("OVERSCALE") for n in G.judge(s))


def test_detects_text_under_the_control_bar():
    s = snap(ctrl=[("button_menu", (280, 225, 330, 260))])
    assert any(n.startswith("SAFE") for n in G.judge(s))


def test_detects_a_mix_of_font_sizes():
    s = snap(fonts={"22px": 10, "26.88px": 3})
    assert any(n.startswith("FONTSIZE") for n in G.judge(s))


def test_overlap_helper():
    assert G.overlap([0, 0, 10, 10], [5, 5, 15, 15])
    assert not G.overlap([0, 0, 10, 10], [10, 10, 20, 20])
    assert not G.overlap([0, 0, 10, 10], [11, 0, 20, 10])


def test_exit_code_and_json_flags(monkeypatch):
    monkeypatch.setattr(G, "run", lambda port, states, shots: ([{"state": 1, "notes": ["x"]}], 3))
    assert G.main(["--port", "1", "--states", "3"]) == 1
    monkeypatch.setattr(G, "run", lambda port, states, shots: ([], 3))
    assert G.main(["--states", "3"]) == 0


@pytest.mark.parametrize("port,states", [(9390, 30), (9500, 5)])
def test_cli_arguments_reach_run(monkeypatch, port, states):
    seen = {}

    def fake(port_, states_, shots):
        seen["port"], seen["states"] = port_, states_
        return [], 0

    monkeypatch.setattr(G, "run", fake)
    G.main(["--port", str(port), "--states", str(states)])
    assert seen == {"port": port, "states": states}


def test_detects_a_character_pushed_almost_off_screen():
    """Owner report: the side characters of a multi-character shot are invisible.
    The measured cause was a compounded offset (layer -800px on top of the
    image offset)."""
    s = snap()
    s["imgs"] = [{"src": "image/y_t009a.png", "rect": [0, 0, 1024, 768], "z": 3000,
                  "layerOff": "-800px/0px", "imgOff": "-800px/0px", "artVis": 5}]
    notes = G.judge(s)
    assert any(n.startswith("OFFSCREEN") for n in notes), notes


def test_a_mostly_visible_character_is_not_flagged():
    s = snap()
    s["imgs"] = [{"src": "image/y_t003e.png", "rect": [0, 0, 1024, 768], "z": 3000,
                  "layerOff": "0px/0px", "imgOff": "0px/0px", "artVis": 100}]
    assert G.judge(s) == []


def test_snap_without_artvis_is_not_judged_offscreen():
    s = snap()
    s["imgs"] = [{"src": "bgimage/z_t001a.png", "rect": [0, 0, 1024, 768], "z": 10}]
    assert G.judge(s) == []


def test_cdp_helper_dir_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VISUAL_CHECK_SCRIPTS", str(tmp_path))
    assert G.cdp_helper_dir() == str(tmp_path)


def test_cdp_helper_dir_has_no_machine_path(monkeypatch):
    """No personal/absolute path may be baked in: without the env var the
    resolver either finds the repo-local tools/cdp or reports nothing."""
    monkeypatch.delenv("VISUAL_CHECK_SCRIPTS", raising=False)
    resolved = G.cdp_helper_dir()
    assert resolved is None or resolved.startswith(
        str(Path(G.__file__).resolve().parent))


def test_load_cdp_reports_a_missing_helper(monkeypatch, tmp_path):
    """A missing helper must be an actionable error, not an ImportError or a
    path that only exists on the author's machine."""
    monkeypatch.setenv("VISUAL_CHECK_SCRIPTS", str(tmp_path))
    with pytest.raises(SystemExit) as ei:
        G.load_cdp()
    msg = str(ei.value)
    assert "cdp_shot.py" in msg
    assert "VISUAL_CHECK_SCRIPTS" in msg


def test_load_cdp_imports_from_the_env_dir(monkeypatch, tmp_path):
    (tmp_path / "cdp_shot.py").write_text("MARK = 'loaded'\n", encoding="utf-8")
    monkeypatch.setenv("VISUAL_CHECK_SCRIPTS", str(tmp_path))
    monkeypatch.delitem(sys.modules, "cdp_shot", raising=False)
    assert G.load_cdp().MARK == "loaded"
