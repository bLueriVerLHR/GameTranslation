#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`tyrano/verify.py`: commented-out audio references are not runtime lookups.

Measured false positive: a game ships `;[playbgm storage="bgm004.wav"]` in
config.ks (the real file is bgm004.ogg), and that single comment failed the
release gate for a build that was fine.  KAG3 comments are `;`-prefixed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tyrano import verify  # noqa: E402


def make_web(root, scenario_body):
    scen = root / "data" / "scenario"
    scen.mkdir(parents=True, exist_ok=True)
    (scen / "a.ks").write_text(scenario_body, encoding="utf-8")
    snd = root / "data" / "sound"
    snd.mkdir(parents=True, exist_ok=True)
    (snd / "ok.ogg").write_bytes(b"x")
    return str(root)


def test_commented_ref_is_ignored(tmp_path):
    web = make_web(tmp_path, ';[playbgm storage="ghost.wav"]\r\n'
                            '[playbgm storage="ok.ogg"]\r\n')
    assert verify.check_audio_refs(web) == []


def test_live_missing_ref_is_still_reported(tmp_path):
    web = make_web(tmp_path, '[playbgm storage="ghost.wav"]\r\n')
    problems = verify.check_audio_refs(web)
    assert len(problems) == 1
    assert "ghost.wav" in problems[0]
    assert "dangling audio ref" in problems[0]


def test_indented_comment_is_ignored(tmp_path):
    web = make_web(tmp_path, '   ; [playse storage="gone.mp3"]\r\n')
    assert verify.check_audio_refs(web) == []
