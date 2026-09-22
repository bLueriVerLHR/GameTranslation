#!/usr/bin/env python3
"""workspace.py - where per-game working state lives.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).
This module owns exactly one responsibility: resolving the directory that
holds a game's in-progress work.

Per ``docs/reference/local-layout.md`` the order is:

    1. an explicit ``--work-dir`` on the command line
    2. ``GT_WORK_ROOT`` (one directory holding several workspaces)
    3. the system temporary directory (``<system temp>/GameTranslation/…``)
    4. the repo's ``.tmp/workspaces/`` - only when explicitly configured

Steps 3 and 4 are deliberately in that order: the system temp directory is
the documented home for work copies, and ``.tmp/`` is a fallback so a run
does not silently start copying multi-gigabyte trees onto the repo's volume.
A workspace is disposable state, not a deliverable - nothing here ever
deletes anything (``gt workspace clean`` is an explicit, dry-run-by-default
operation).
"""
import logging
import os
import tempfile
from pathlib import Path

from .settings import REPO_ROOT

__all__ = [
    "WORKSPACE_DIRNAME",
    "WORKSPACE_SCHEMA_VERSION",
    "default_workspaces_root",
    "resolve_workspace_dir",
    "workspace_root",
]

log = logging.getLogger("rpgmaker.workspace")

#: Subdirectory created under the system temp dir / GT_WORK_ROOT.
WORKSPACE_DIRNAME = "GameTranslation"

#: ``workspace.json`` schema version written by new workspaces.
WORKSPACE_SCHEMA_VERSION = 1


def workspace_root() -> str:
    """The directory that holds this checkout.

    Deliverables belong next to the sources, so the tool library's own parent
    directory is both the first probe base and the default output root: they
    live beside the repo (``<workspace>/Games``, ``<workspace>/GamesCompress``)
    instead of somewhere machine-specific.
    """
    return str(REPO_ROOT.parent)


def default_workspaces_root():
    """Directory holding per-game workspaces when nothing is configured.

    ``<GT_WORK_ROOT>`` when set, else ``<system temp>/GameTranslation``.
    Returns a ``Path``; the directory is not created here - a caller that
    needs it creates it, so merely importing this module never touches disk.
    """
    override = os.environ.get("GT_WORK_ROOT")
    if override:
        return Path(override).expanduser()
    return Path(tempfile.gettempdir()) / WORKSPACE_DIRNAME


def resolve_workspace_dir(name, explicit=None, repo_fallback=False):
    """Resolve the directory for one game's work.

    ``explicit`` (a ``--work-dir``) wins outright.  Otherwise the directory is
    ``<workspaces root>/<name>``.  ``repo_fallback=True`` opts into the
    repo-local ``.tmp/workspaces/`` layout instead of the temp directory, and
    exists so the documented step 4 is an explicit choice rather than a
    silent default - a large work copy must not land on the repo volume just
    because the temp directory was unwritable.

    Never creates the directory and never raises: a caller that needs the
    path either creates it or reports it.
    """
    if explicit:
        return Path(explicit).expanduser()
    root = (REPO_ROOT / ".tmp" / "workspaces" if repo_fallback
            else default_workspaces_root())
    return root / name
