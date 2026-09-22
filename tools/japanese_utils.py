#!/usr/bin/env python3
"""japanese_utils.py - DEPRECATED alias for `rpgmaker.japanese`.

Kept for one compatibility cycle so an existing ``import japanese_utils``
(which used to resolve because ``tools/`` was on ``sys.path``) keeps working.
New code imports ``from rpgmaker import japanese``.

This shim deliberately does **not** touch ``sys.path``: it resolves whenever
the repo root is importable, which is true in every supported invocation (the
pipeline entry points, the test suite's conftest, and the ``tools/*.py``
scripts that insert the repo root themselves).  Adding a path hack here would
re-introduce exactly the import magic the package boundary is removing.

Do not add behaviour here: this module must stay a pure re-export.
"""
import warnings

from rpgmaker.japanese import (  # noqa: F401
    KANA,
    KANA_BLOCKS,
    KANA_BLOCKS_HW,
    KANA_PURE_WORD,
)

warnings.warn(
    "tools.japanese_utils is deprecated; import rpgmaker.japanese instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["KANA", "KANA_BLOCKS", "KANA_BLOCKS_HW", "KANA_PURE_WORD"]
