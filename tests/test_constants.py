#!/usr/bin/env python3
"""RPG Maker build constants, and the no-hardcoded-machine-path rule.

Split out of tests/test_config.py when rpgmaker/constants.py was split
(PLAN Phase 4): patching a name on the facade no longer reaches the code
that reads it, so each test now patches the module that owns the name.
"""

from rpgmaker import constants
from rpgmaker import settings


class TestMagicConstants:
    def test_rpgmv_header_length(self):
        assert len(constants.RPGMV_HEADER) == 16

    def test_nwjs_runtime_contains_exe(self):
        assert "Game.exe" in constants.NWJS_RUNTIME

    def test_no_hardcoded_tool_paths(self):
        # Machine paths must never live in the repo: the resolver probes for
        # them instead.  One file per responsibility can hold a literal, so
        # every module the split produced is checked rather than just one.
        for name in ("constants.py", "tool_registry.py", "settings.py",
                     "deliverables.py", "platform.py", "assets.py",
                     "workspace.py"):
            src = (settings.REPO_ROOT / "rpgmaker" / name).read_text(
                encoding="utf-8")
            assert "Program Files" not in src or "%ProgramFiles%" in src, name
            assert "DEFAULT_SEVENZ" not in src, name
            assert "DEFAULT_FFMPEG_DIR" not in src, name

