"""Shared pytest fixtures: synthetic games and launcher helpers.

Synthetic builders live in tests.helpers and are imported normally. Path and
tool resolution is pinned to the checkout so a run cannot depend on the host
machine's applications or private data.
"""

import os

import pytest

from tests.helpers import make_game, make_launcher


@pytest.fixture
def game_dir(tmp_path):
    """A synthetic MZ game; return (root, web_root)."""
    root = str(tmp_path / "game")
    web = make_game(root)
    return root, web


@pytest.fixture
def fake_tools(tmp_path_factory):
    """Neutral environment for tests that must not read the host's tools."""
    workdir = str(tmp_path_factory.mktemp("fake-tools"))
    mapping = {"dir": workdir}
    for var in ("GT_WORKERS",):
        os.environ.pop(var, None)
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
