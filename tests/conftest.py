"""Shared pytest fixtures and hermetic fake-tool environment wiring.

Synthetic builders live in tests.helpers and are imported normally. The only
fake executable is ffmpeg: Vorbis encoding still needs its CLI because PyAV
wheels lack libvorbis. Media probes use genuine generated/committed containers.
"""

import os

import pytest

from tests.helpers import fake_launcher, make_game, make_launcher


@pytest.fixture
def game_dir(tmp_path):
    """A synthetic MZ game; return (root, web_root)."""
    root = str(tmp_path / "game")
    web = make_game(root)
    return root, web


@pytest.fixture
def fake_tools(monkeypatch, tmp_path_factory):
    """Point FFMPEG at its fake launcher; return script names and workdir."""
    workdir = str(tmp_path_factory.mktemp("fake-tools"))
    mapping = {}
    for name, script in (("FFMPEG", "ffmpeg.py"),):
        launcher = fake_launcher(script, workdir)
        monkeypatch.setenv(name, launcher)
        mapping[os.path.splitext(script)[0]] = launcher
    mapping["dir"] = workdir
    for var in ("FAKE_HIGH_BITRATE", "FAKE_SMALL_OUTPUT", "GT_WORKERS"):
        monkeypatch.delenv(var, raising=False)
    return mapping


@pytest.fixture
def launcher_factory(tmp_path_factory):
    """Make arbitrary test scripts executable on the current platform."""
    workdir = str(tmp_path_factory.mktemp("launchers"))

    def make(script_path):
        return make_launcher(str(script_path), workdir)

    return make


@pytest.fixture(autouse=True)
def hermetic_resolution(monkeypatch):
    """Keep application/path resolution independent of the host machine."""
    from rpgmaker import deliverables

    monkeypatch.setenv("GT_NO_PROBE", "1")
    monkeypatch.setattr(deliverables, "_noted_defaults", set())
    yield
