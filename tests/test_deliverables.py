#!/usr/bin/env python3
"""Deliverable and temp folders:
env -> machine deliverables -> probe -> default.

Split out of tests/test_config.py when rpgmaker/deliverables.py was split
(PLAN Phase 4): patching a name on the facade no longer reaches the code
that reads it, so each test now patches the module that owns the name.
"""

import json
import logging

from rpgmaker import deliverables
from rpgmaker import platform
from rpgmaker import settings
from rpgmaker import workspace

class TestDeliverable:
    """Single native-form path in deliverables; localized for the current platform."""

    _HOME = "/home/tester"

    def _cfg(self, monkeypatch, tmp_path, values):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps({"deliverables": values}),
                       encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
        monkeypatch.setattr(deliverables, "_home_dir", lambda: self._HOME)
        monkeypatch.delenv("GAMES_DIR", raising=False)
        monkeypatch.delenv("ARCHIVES_DIR", raising=False)

    def _isolate_probe(self, monkeypatch, tmp_path, ws_root=None,
                       roots=()):
        """Probe only the given roots, so the host's own Games folders never
        influence the assertion."""
        monkeypatch.delenv("GT_NO_PROBE", raising=False)
        monkeypatch.setattr(workspace, "workspace_root",
                            lambda: platform.posix(str(ws_root or tmp_path)))
        monkeypatch.setattr(deliverables, "_volume_roots",
                            lambda: [platform.posix(str(r)) for r in roots])
        monkeypatch.setattr(deliverables, "_home_dir", lambda: self._HOME)

    def test_games_native_form_localized(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"games": "D:/Games"})
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert deliverables.games_dir() == "/mnt/d/Games"

    def test_env_var_wins(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"games": "D:/Games"})
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        monkeypatch.setenv("GAMES_DIR", "/mnt/d/Other")
        assert deliverables.games_dir() == "/mnt/d/Other"

    def test_unconfigured_derives_default_from_workspace(self, monkeypatch,
                                                         tmp_path):
        # Nothing configured and nothing probed -> the workspace root beside
        # this checkout is the base, created on demand by deliver.
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(workspace, "workspace_root",
                            lambda: "/work/ws")
        monkeypatch.setattr(deliverables, "_volume_roots", list)
        assert deliverables.games_dir() == "/work/ws/Games"
        assert deliverables.archives_dir() == "/work/ws/GamesCompress"

    def test_workspace_sibling_folder_is_adopted(self, monkeypatch, tmp_path):
        # The documented layout: output lives beside the project, so an
        # existing <workspace>/Games is used without any configuration.
        self._cfg(monkeypatch, tmp_path, {})
        (tmp_path / "Games").mkdir()
        (tmp_path / "GamesCompress").mkdir()
        self._isolate_probe(monkeypatch, tmp_path)
        assert deliverables.games_dir() == platform.posix(str(tmp_path / "Games"))
        assert deliverables.archives_dir() == \
            platform.posix(str(tmp_path / "GamesCompress"))

    def test_probe_bases_put_the_workspace_first(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(workspace, "workspace_root", lambda: "/work/ws")
        monkeypatch.setattr(deliverables, "_volume_roots",
                            lambda: ["/mnt/c", "/mnt/d"])
        bases = deliverables.deliverable_bases()
        assert bases[0] == "/work/ws"
        assert bases[1:3] == ["/mnt/c", "/mnt/d"]
        assert bases[-1] == self._HOME
        assert len(bases) == len(set(bases))

    def test_existing_conventional_folder_on_a_volume_is_adopted(
            self, monkeypatch, tmp_path):
        # The probe also adopts a conventionally named folder on a volume
        # root, so an operator who keeps output outside the workspace is
        # picked up automatically.
        self._cfg(monkeypatch, tmp_path, {})
        (tmp_path / "Games").mkdir()
        self._isolate_probe(monkeypatch, tmp_path, ws_root=tmp_path / "other",
                            roots=(tmp_path,))
        assert deliverables.games_dir() == platform.posix(str(tmp_path / "Games"))

    def test_probe_ignores_missing_conventional_folder(self, monkeypatch,
                                                       tmp_path):
        monkeypatch.delenv("GT_NO_PROBE", raising=False)
        monkeypatch.setattr(workspace, "workspace_root", lambda: "/work/none")
        monkeypatch.setattr(deliverables, "_volume_roots", list)
        monkeypatch.setattr(deliverables, "_home_dir", lambda: self._HOME)
        assert deliverables.probe_deliverable("archives") is None
        assert deliverables.probe_deliverable("games") is None

    def test_temp_native_posix(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path, {"temp": "/tmp/gametrans"})
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert deliverables.temp_dir() == "/tmp/gametrans"

    def test_win_temp_localized(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"win_temp": "C:/Users/me/AppData/Local/Temp"})
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert deliverables.win_temp_dir() == "/mnt/c/Users/me/AppData/Local/Temp"

    def test_temp_nested_dict_persist_on_wsl(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"temp": {"persist": "/home/me/forge/tmp",
                            "tmpfs": "/tmp/gametrans",
                            "win32": "%LOCALAPPDATA%/Temp"}})
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert deliverables.temp_dir() == "/home/me/forge/tmp"

    def test_temp_nested_dict_win32_on_windows(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"temp": {"persist": "/home/me/forge/tmp",
                            "tmpfs": "/tmp/gametrans",
                            "win32": "C:/Temp"}})
        monkeypatch.setattr(platform, "is_wsl", lambda: False)
        assert deliverables.temp_dir() == "C:/Temp"

    def test_temp_nested_dict_win_temp_dir(self, monkeypatch, tmp_path):
        self._cfg(monkeypatch, tmp_path,
                  {"temp": {"persist": "/home/me/forge/tmp",
                            "tmpfs": "/tmp/gametrans",
                            "win32": "C:/Temp"}})
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert deliverables.win_temp_dir() == "/mnt/c/Temp"

    def test_temp_missing_nested_falls_back_to_legacy(self, monkeypatch,
                                                      tmp_path):
        self._cfg(monkeypatch, tmp_path, {})
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        assert deliverables.temp_dir() == "/tmp/gametrans"


class TestCreatable:
    def test_existing_dir(self, tmp_path):
        assert deliverables.creatable(str(tmp_path))

    def test_missing_leaf_under_existing_dir(self, tmp_path):
        assert deliverables.creatable(str(tmp_path / "a" / "b"))

    def test_blocked_by_a_file_ancestor(self, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        assert deliverables.creatable(str(blocker / "games")) is False


class TestDefaultNote:
    """The 'we derived this folder' note is informational and once-only."""

    @staticmethod
    def _cfg(monkeypatch, tmp_path):
        cfg = tmp_path / "env_config.json"
        cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
        monkeypatch.setattr(deliverables, "_home_dir", lambda: "/home/tester")
        monkeypatch.delenv("GAMES_DIR", raising=False)

    def test_default_notes_once_for_derived_default(self, monkeypatch,
                                                    tmp_path, caplog):
        self._cfg(monkeypatch, tmp_path)
        monkeypatch.setattr(workspace, "workspace_root", lambda: "/work/ws")
        monkeypatch.setattr(deliverables, "_volume_roots", list)
        with caplog.at_level(logging.INFO, logger="rpgmaker.deliverables"):
            deliverables.games_dir()
            deliverables.games_dir()
        notes = [r.message for r in caplog.records
                 if "deliverables.games" in r.message]
        assert len(notes) == 1
        assert all(r.levelno == logging.INFO for r in caplog.records)

    def test_no_note_when_configured(self, monkeypatch, tmp_path, caplog):
        cfg = tmp_path / "env_config.json"
        cfg.write_text(json.dumps(
            {"deliverables": {"games": "/tmp/somewhere"}}), encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg)
        monkeypatch.delenv("GAMES_DIR", raising=False)
        with caplog.at_level(logging.INFO, logger="rpgmaker.deliverables"):
            assert deliverables.games_dir() == "/tmp/somewhere"
        assert not [r for r in caplog.records
                    if "deliverables.games" in r.message]

    def test_no_note_when_env_set(self, monkeypatch, tmp_path, caplog):
        self._cfg(monkeypatch, tmp_path)
        monkeypatch.setenv("GAMES_DIR", "/tmp/from-env")
        with caplog.at_level(logging.INFO, logger="rpgmaker.deliverables"):
            assert deliverables.games_dir() == "/tmp/from-env"
        assert not [r for r in caplog.records
                    if "deliverables.games" in r.message]
