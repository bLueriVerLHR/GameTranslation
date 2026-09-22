#!/usr/bin/env python3
"""plugins_io.py - DEPRECATED alias for `rpgmaker.plugins_io`.

Kept for one compatibility cycle so an existing ``import plugins_io`` (which
used to resolve because ``tools/`` was on ``sys.path``) keeps working.  New
code imports ``from rpgmaker import plugins_io``.

This shim deliberately does **not** touch ``sys.path`` (see
``tools/japanese_utils.py`` for why).  Do not add behaviour here: this module
must stay a pure re-export.
"""
import warnings

from rpgmaker.plugins_io import (  # noqa: F401
    HEAD,
    JS_STR,
    dump_plugins_js,
    iter_literals,
    iter_plugin_strings,
    parse_plugins_js,
)

warnings.warn(
    "tools.plugins_io is deprecated; import rpgmaker.plugins_io instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["HEAD", "JS_STR", "parse_plugins_js", "dump_plugins_js",
           "iter_plugin_strings", "iter_literals"]
