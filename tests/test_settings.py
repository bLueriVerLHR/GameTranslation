#!/usr/bin/env python3
"""The local private-data layout and the
machine settings.

Split out of tests/test_config.py when rpgmaker/settings.py was split
(PLAN Phase 4): patching a name on the facade no longer reaches the code
that reads it, so each test now patches the module that owns the name.
"""

import json
import sys

import pytest

from rpgmaker import platform
from rpgmaker import settings

class TestPick:
    """Plain name -> value lookups (no per-key platform mapping anymore)."""

    def test_plain_value(self):
        assert settings.pick({"a": "x"}, "a") == "x"

    def test_missing_key(self):
        assert settings.pick({"a": "x"}, "b") is None

    def test_non_dict(self):
        assert settings.pick(None, "a") is None
        assert settings.pick("str", "a") is None


class TestSectionPlatform:
    """Platform-first sections: {wsl: {...}, win32: {...}}."""

    def test_wsl_subdict(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: True)
        sec = {"wsl": {"7z": "3rd/7zz"}, "win32": {"7z": "C:/7z.exe"}}
        assert settings.section_platform(sec) == {"7z": "3rd/7zz"}

    def test_win32_subdict(self, monkeypatch):
        monkeypatch.setattr(platform, "is_wsl", lambda: False)
        monkeypatch.setattr(sys, "platform", "win32")
        sec = {"wsl": {"7z": "3rd/7zz"}, "win32": {"7z": "C:/7z.exe"}}
        assert settings.section_platform(sec) == {"7z": "C:/7z.exe"}

    def test_plain_section_passthrough(self):
        assert settings.section_platform({"a": "x"}) == {"a": "x"}

    def test_empty_and_non_dict(self):
        assert settings.section_platform(None) == {}
        assert settings.section_platform("str") == {}
        assert settings.section_platform({"wsl": {}, "win32": {}}) == {}


class TestWin32Section:
    """Windows-only tools must be found regardless of the current platform."""

    def test_win32_subdict(self):
        sec = {"wsl": {"7z": "x"}, "win32": {"7z": "C:/7z.exe"}}
        assert settings.win32_section(sec) == {"7z": "C:/7z.exe"}

    def test_missing_and_non_dict(self):
        assert settings.win32_section({"wsl": {"7z": "x"}}) == {}
        assert settings.win32_section(None) == {}
        assert settings.win32_section("str") == {}


class TestExpand:
    def test_env_token(self, monkeypatch):
        monkeypatch.setenv("TESTVAR", "value")
        assert settings.expand_env("%TESTVAR%/x") == "value/x"

    def test_unknown_token_passthrough(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        assert settings.expand_env("%NO_SUCH_VAR%/x") == "%NO_SUCH_VAR%/x"

    def test_separators_normalized(self):
        assert settings.expand_env(r"C:\a\b") == "C:/a/b"


class TestLoadEnvConfig:
    """An invalid machine config contributes nothing and reports why."""

    def test_missing_file_is_empty(self, monkeypatch):
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE",
                            settings.REPO_ROOT / "does-not-exist.json")
        cfg = settings.load_machine_config()
        assert cfg.raw == {}
        assert cfg.present is False
        assert cfg.problems == ()

    def test_corrupt_file_reports_and_contributes_nothing(self, monkeypatch,
                                                          tmp_path):
        cfg_path = tmp_path / "env_config.json"
        cfg_path.write_text("{ not json", encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg_path)
        cfg = settings.load_machine_config()
        assert cfg.raw == {}
        assert cfg.present is True
        assert not cfg.ok
        assert any("invalid JSON" in p for p in cfg.problems)

    def test_unknown_section_invalidates_the_whole_file(self, monkeypatch,
                                                        tmp_path):
        # A typo would otherwise be an invisible no-op, so the file is
        # rejected as a whole rather than half-applied.
        cfg_path = tmp_path / "env_config.json"
        cfg_path.write_text(json.dumps({"deliverables": {"games": "/tmp/g"},
                                        "tols": {}}), encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg_path)
        cfg = settings.load_machine_config()
        assert cfg.raw == {}
        assert any("'tols'" in p for p in cfg.problems)

    def test_reads_platform_section(self, monkeypatch, tmp_path):
        cfg_path = tmp_path / "env_config.json"
        cfg_path.write_text(
            json.dumps({"tools": {"wsl": {"7z": "3rd/7zz"}}}),
            encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg_path)
        cfg = settings.load_machine_config()
        assert cfg.ok
        assert cfg.section("tools") == {"wsl": {"7z": "3rd/7zz"}}

    def test_newer_version_is_reported_not_honoured(self, monkeypatch,
                                                    tmp_path):
        cfg_path = tmp_path / "env_config.json"
        cfg_path.write_text(
            json.dumps({"version": settings.CONFIG_SCHEMA_VERSION + 1}),
            encoding="utf-8")
        monkeypatch.setattr(settings, "LOCAL_ENV_FILE", cfg_path)
        cfg = settings.load_machine_config()
        assert cfg.raw == {}
        assert any("newer than this build" in p for p in cfg.problems)


class TestPrivateLayout:
    """The logical-name mapping is the only place that knows the layout."""

    def test_current_layout_wins_when_it_exists(self, tmp_path):
        (tmp_path / ".asset" / "fonts").mkdir(parents=True)
        (tmp_path / "docs" / "table" / "fonts").mkdir(parents=True)
        got = settings.private_path("fonts", repo_root=tmp_path)
        assert settings.posix(got) == settings.posix(
            tmp_path / ".asset" / "fonts")

    def test_legacy_layout_is_a_read_only_fallback(self, tmp_path):
        legacy = tmp_path / "docs" / "table" / "fonts"
        legacy.mkdir(parents=True)
        got = settings.private_path("fonts", repo_root=tmp_path)
        assert settings.posix(got) == settings.posix(legacy)

    def test_missing_legacy_resolves_to_the_current_layout(self, tmp_path):
        got = settings.private_path("fonts", repo_root=tmp_path)
        assert settings.posix(got) == settings.posix(
            tmp_path / ".asset" / "fonts")

    def test_locations_without_a_legacy_spelling_never_fall_back(
            self, tmp_path):
        (tmp_path / "docs" / "table" / "secrets").mkdir(parents=True)
        got = settings.private_path("secrets", repo_root=tmp_path)
        assert settings.posix(got) == settings.posix(
            tmp_path / ".private" / "secrets")

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError, match="unknown private location"):
            settings.private_path("no-such-location")

    def test_migration_status_reports_each_source(self, tmp_path):
        (tmp_path / "docs" / "table" / "fonts").mkdir(parents=True)
        (tmp_path / ".private" / "secrets").mkdir(parents=True)
        by = {row["key"]: row
              for row in settings.migration_status(repo_root=tmp_path)}
        assert set(by) == set(settings.PRIVATE_PATHS)
        assert by["fonts"]["source"] == "legacy"
        assert by["fonts"]["legacy_available"] is True
        assert by["secrets"]["source"] == "current"
        assert by["dictionaries"]["source"] == "missing"
        for row in by.values():
            assert set(row) == {"key", "path", "source", "legacy_available"}

    def test_all_legacy_spellings_stay_under_the_legacy_root(self):
        for key, loc in settings.PRIVATE_PATHS.items():
            assert loc.current.startswith((".private/", ".asset/", ".tools/")), key
            if loc.legacy:
                assert loc.legacy.startswith("docs/table/"), key

    def test_no_module_concatenates_the_legacy_directory(self):
        # The whole point of the mapping: the physical layout is spelled in
        # exactly one file, so moving the private data is a data edit.
        src = (settings.REPO_ROOT / "rpgmaker").glob("*.py")
        offenders = []
        for path in src:
            if path.name in ("config.py", "settings.py"):
                continue
            text = path.read_text(encoding="utf-8")
            if '"docs"' in text and '"table"' in text:
                offenders.append(path.name)
        assert offenders == []
