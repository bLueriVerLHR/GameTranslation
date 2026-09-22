#!/usr/bin/env python3
"""Release-packaging rules for a converted KAG3 build.

Two owner requirements after the first real-device test:
  1. the ☰ control panel must sit in the TOP-LEFT (the game draws its own
     controls in the top-right corner and the two competed there);
  2. a build must not ship engine development scaffolding (`.vscode`, lint
     config, the engine's release script, its docs) - while keeping the engine
     licence/readme, which belong with a redistributed engine.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kirikiri.kag import project, shims  # noqa: E402


class TestMobilePanelPosition:
    def test_panel_is_anchored_top_left(self):
        text = shims.RUNTIME_SHIM_IIFE
        assert "position:fixed;left:10px;top:10px" in text
        assert "position:fixed;right:10px;top:10px" not in text

    def test_panel_actions_grow_rightwards(self):
        """A left-anchored panel must lay its buttons out to the right."""
        text = shims.RUNTIME_SHIM_IIFE
        assert "justify-content:flex-start" in text
        assert "justify-content:flex-end" not in text


class TestEngineScaffoldingIsNotCopied:
    def _engine(self, tmp_path):
        src = tmp_path / "engine"
        for rel in ("index.html", "tyrano/plugins/kag/kag.js",
                    "LICENCE.txt", "readme.txt", "tyrano/css/tyrano.css"):
            path = src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        for rel in (".vscode/settings.json", ".eslintrc.js", ".prettierrc.js",
                    ".prettierignore", ".gitignore", "package.json",
                    "release/build.py", "doc.html", "node_modules/dep.js"):
            path = src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        return src

    def test_dev_files_and_dirs_are_skipped(self, tmp_path):
        src = self._engine(tmp_path)
        dst = tmp_path / "out"
        project._copy_tree(str(src), str(dst))
        for rel in (".vscode", ".eslintrc.js", ".prettierrc.js",
                    ".prettierignore", ".gitignore", "package.json",
                    "release", "doc.html", "node_modules"):
            assert not os.path.exists(os.path.join(str(dst), rel)), rel

    def test_runtime_and_licence_files_are_kept(self, tmp_path):
        src = self._engine(tmp_path)
        dst = tmp_path / "out"
        project._copy_tree(str(src), str(dst))
        for rel in ("index.html", "LICENCE.txt", "readme.txt",
                    "tyrano/plugins/kag/kag.js", "tyrano/css/tyrano.css"):
            assert os.path.isfile(os.path.join(str(dst), rel)), rel

    def test_skip_set_keeps_licence_out_of_it(self):
        """Guards against someone adding LICENCE.txt/readme.txt to the skip set."""
        assert "LICENCE.txt" not in project.ENGINE_DEV_SKIP
        assert "readme.txt" not in project.ENGINE_DEV_SKIP
        assert "index.html" not in project.ENGINE_DEV_SKIP
        assert ".vscode" in project.ENGINE_DEV_SKIP
