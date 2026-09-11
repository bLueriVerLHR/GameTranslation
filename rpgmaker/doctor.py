#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Environment self-check for the toolkit.

`pipeline.py doctor` (this module) prints a compact report of everything the
toolkit depends on and exits non-zero when something is missing:

  * external applications   driven by rpgmaker.config.TOOLS - the same
                            declarative table the resolver uses, so a new
                            tool shows up here without touching this file
  * machine config          docs/table/env_config.json (optional override
                            layer; absent is normal and not a failure)
  * deliverable folders     games / archives / temp (probed when unset,
                            created on demand)

Each line is `[OK] <label>  <detail>  [<source>]` or
`[MISS] <label>  <detail>  -> <hint>`, so the report stays greppable; the
source tells where a path came from (env / config / probe / path), which is
the fastest way to explain a surprising binary.

`doctor --json` prints the same information as machine-readable JSON.

Exposed as plain functions (collect_checks / render / run) so the report
can be unit-tested with monkeypatched find_* resolvers.
"""
import json
import logging
import os
import sys
from collections import namedtuple

from . import config

log = logging.getLogger("rpgmaker.doctor")

Check = namedtuple("Check", ("label", "ok", "detail", "hint", "source"))

_DIR_CHECKS = [
    ("games_dir", "games_dir",
     "finished builds land here (deliver step); probed when unset, set "
     "deliverables.games in env_config.json to pin it"),
    ("archives_dir", "archives_dir",
     "finished archives land here (deliver step); probed when unset"),
    ("temp_dir", "temp_dir",
     "work copies live here; must exist and be writable (deliverables.temp)"),
]


def _tool_checks():
    """(label, resolver-name, hint, side) for every registered tool."""
    for tool in config.TOOLS:
        yield tool.key, tool.resolver, tool.hint, tool.side


def _resolver(name):
    return getattr(config, name)


def _tool_source(tool_key):
    """Where the tool path came from (env/config/probe/path); best effort,
    only used for reporting."""
    try:
        _path, source = config.resolve_tool(tool_key, with_source=True)
        return source or "-"
    except (OSError, KeyError, ValueError):
        return "-"


def _env_config_status():
    """(ok, detail) for the gitignored machine config file.

    The file is an OPTIONAL override layer, so an absent file is reported as
    OK (probing and built-in defaults take over); a present-but-corrupt file
    is a real failure and is parsed here rather than through
    config._load_env_config(), which swallows JSON/IO errors by design."""
    if not config.LOCAL_ENV_FILE.is_file():
        return True, "(absent) no overrides - probing + defaults in use"
    try:
        data = json.loads(config.LOCAL_ENV_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "(unreadable) %s" % config.LOCAL_ENV_FILE
    if not isinstance(data, dict):
        return False, "(unreadable) %s" % config.LOCAL_ENV_FILE
    return True, str(config.LOCAL_ENV_FILE)


def collect_checks():
    """Run every environment check; returns a list of Check namedtuples."""
    checks = []
    for label, fname, hint, side in _tool_checks():
        p = _resolver(fname)()
        missing = "(not configured)" if side == "win32" else "(not found)"
        checks.append(Check(label, bool(p), p or missing, hint,
                            _tool_source(label) if p else "-"))
    ok, detail = _env_config_status()
    checks.append(Check(
        "env_config.json", ok, detail,
        "optional override layer for deliverable paths and tool locations; "
        "absent is fine - probing and defaults take over", "file"))
    for label, fname, hint in _DIR_CHECKS:
        d = _resolver(fname)()
        ok = os.path.isdir(d) or config._creatable(d)
        detail = d if os.path.isdir(d) else "%s (created on demand)" % d
        checks.append(Check(label, ok, detail, hint, "resolved"))
    return checks


def render(checks):
    """Render the report as a list of lines (one per check + a summary)."""
    lines = []
    for c in checks:
        tag = "OK" if c.ok else "MISS"
        line = "[%s] %-16s %s" % (tag, c.label, c.detail)
        if c.ok:
            line += "  (%s)" % c.source
        else:
            line += "  -> %s" % c.hint
        lines.append(line)
    ok = sum(1 for c in checks if c.ok)
    lines.append("%d/%d checks OK" % (ok, len(checks)))
    return lines


def as_json(checks):
    """Machine-readable form: the same rows the text report renders."""
    return json.dumps({
        "ok": all(c.ok for c in checks),
        "checks": [c._asdict() for c in checks],
        "tools": config.probe_report(),
    }, indent=2, ensure_ascii=False)


def run(argv=None):
    """Run the self-check and return the exit code (0 = all OK, 1 = any
    missing/failing). `--json` switches to the machine-readable report."""
    argv = list(sys.argv[1:] if argv is None else argv)
    as_machine = "--json" in argv
    checks = collect_checks()
    if as_machine:
        print(as_json(checks))
    else:
        for line in render(checks):
            print(line)
    return 0 if all(c.ok for c in checks) else 1


def main(argv=None):
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
