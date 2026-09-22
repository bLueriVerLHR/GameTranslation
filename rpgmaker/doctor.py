#!/usr/bin/env python3
"""Environment self-check for the toolkit.

`pipeline.py doctor` (this module) prints a compact report of everything the
toolkit depends on and exits non-zero when something is missing:

  * external applications   driven by rpgmaker.tool_registry.TOOLS - the same
                            declarative table the resolver uses, so a new
                            tool shows up here without touching this file.
                            A missing tool is only a failure when it is
                            "required" for a build (see
                            rpgmaker.tool_registry.ToolStatus); anything else
                            is reported as [WARN] and does not change the
                            exit code
  * machine config          the local private config file, `.private/config/`
                            `environment.json` by default (optional override
                            layer; absent is normal and not a failure).  The
                            location comes from rpgmaker.settings.PRIVATE_PATHS
                            - see docs/reference/local-layout.md
  * deliverable folders     games / archives / temp (probed when unset,
                            created on demand)
  * workspace + private data the per-game work root and each logical local
                            resource, with the layout generation it resolved
                            through (current vs. legacy - a half-finished
                            migration is visible here, not later)

Each line is `[OK] <label>  <detail>  [<source>]`,
`[MISS] <label>  <detail>  -> <hint>` or
`[WARN] <label>  <detail>  -> <hint>`, so the report stays greppable; the
source tells where a path came from (env / config / probe / path), which is
the fastest way to explain a surprising binary.  A `[WARN]` means "absent but
not required for a build here", which is a different situation from a broken
toolkit and must not read the same.

`doctor --json` prints the same information as machine-readable JSON.

Exposed as plain functions (collect_checks / render / run) so the report
can be unit-tested with monkeypatched find_* resolvers.
"""
import json
import logging
import os
import sys
from collections import namedtuple

from . import deliverables, logsetup, platform, settings, tool_registry

log = logging.getLogger("rpgmaker.doctor")

Check = namedtuple("Check", ("label", "ok", "detail", "hint", "source"))

_DIR_CHECKS = [
    ("games_dir", "games_dir",
     "finished builds land here (deliver step); probed when unset, set "
     "deliverables.games in the local machine config to pin it"),
    ("archives_dir", "archives_dir",
     "finished archives land here (deliver step); probed when unset"),
    ("temp_dir", "temp_dir",
     "work copies live here; must exist and be writable (deliverables.temp)"),
]


def _tool_checks():
    """(label, resolver-name, hint, side) for every registered tool."""
    for tool in tool_registry.TOOLS:
        yield tool.key, tool.resolver, tool.hint, tool.side


def _is_fatal(label):
    """Whether a failing check with this label must fail the whole report.

    Two situations are deliberately separated: a tool that a build cannot do
    without, and everything else.  `ToolStatus` answers the build question,
    except for the Windows bridge: those binaries are only reachable from WSL
    (they process bytes the Windows side owns), so on the Windows side an
    absent `powershell.exe` is not a problem at all.

    Anything that is not a tool row - the machine config, the deliverable
    folders, the workspace root, the private locations - is always fatal.
    """
    tool = tool_registry.TOOLS_BY_KEY.get(label)
    if tool is None:
        return True
    if tool.status is tool_registry.ToolStatus.WINDOWS_BRIDGE:
        return platform.is_wsl()
    return tool.status.missing_is_fatal


def _blocking(checks):
    """Checks that failed and are required on this platform."""
    return [c for c in checks if not c.ok and _is_fatal(c.label)]


def _warnings(checks):
    """Checks that failed but do not block a build here."""
    return [c for c in checks if not c.ok and not _is_fatal(c.label)]


def _resolver(name):
    """Look a `find_*` resolver up by the name the tool table records."""
    return getattr(tool_registry, name)


def _dir_resolver(name):
    """Look a deliverable-folder resolver up.

    Kept separate from :func:`_resolver` because the two live in different
    modules now (`tool_registry` for programs, `deliverables` for folders) -
    and doctor monkeypatches whichever module actually reads the name.
    """
    return getattr(deliverables, name)


def _tool_source(tool_key):
    """Where the tool path came from (env/config/probe/path); best effort,
    only used for reporting."""
    try:
        _path, source = tool_registry.resolve_tool(tool_key, with_source=True)
        return source or "-"
    except (OSError, KeyError, ValueError):
        return "-"


def _env_config_status():
    """(ok, detail) for the gitignored machine config file.

    The file is an OPTIONAL override layer, so an absent file is reported as
    OK (probing and built-in defaults take over); a present-but-invalid file
    is a real failure.  Validation lives in `settings.load_machine_config()`,
    which rejects the whole file on any problem, so a half-applied config is
    impossible."""
    cfg = settings.load_machine_config()
    if not cfg.present:
        return True, "(absent) no overrides - probing + defaults in use"
    if not cfg.ok:
        return False, "(invalid) {}: {}".format(cfg.path, "; ".join(cfg.problems))
    return True, str(cfg.path)


def _private_layout_checks():
    """One row per logical private location: resolved path + where it came
    from.  A half-finished migration (data still under the legacy tree) is
    visible here instead of surfacing later as "the font policy silently did
    not apply"."""
    checks = []
    for row in settings.migration_status():
        source = row["source"]
        if source == "current":
            ok, note = True, "current layout"
        elif source == "legacy":
            # Readable and working, so not a failure - but the operator is
            # mid-migration and should know which key has not moved yet.
            ok, note = True, "legacy layout (still under the old tree)"
        else:
            ok, note = True, "(absent) not provisioned"
        checks.append(Check(
            "private:{}".format(row["key"]), ok, "{} - {}".format(row["path"], note),
            "a gitignored local resource; state the logical location, never "
            "a literal path (see docs/reference/local-layout.md)", source))
    return checks


def _workspace_check():
    """Where per-game work would be created, and how it was chosen."""
    from . import workspace

    root = workspace.default_workspaces_root()
    source = "env" if os.environ.get("GT_WORK_ROOT") else "default"
    return Check(
        "workspace root", True, str(root),
        "per-game work lives here; override with --work-dir or GT_WORK_ROOT "
        "(see docs/reference/local-layout.md)", source)


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
        "machine config", ok, detail,
        "optional override layer for deliverable paths and tool locations; "
        "absent is fine - probing and defaults take over", "file"))
    for label, fname, hint in _DIR_CHECKS:
        d = _dir_resolver(fname)()
        ok = os.path.isdir(d) or deliverables.creatable(d)
        detail = d if os.path.isdir(d) else f"{d} (created on demand)"
        checks.append(Check(label, ok, detail, hint, "resolved"))
    checks.append(_workspace_check())
    checks.extend(_private_layout_checks())
    return checks


def render(checks):
    """Render the report as a list of lines (one per check + a summary).

    `[MISS]` marks a check that must be fixed; `[WARN]` marks a tool that is
    simply not installed and is not needed for a build on this platform.  The
    two used to render identically, which made an ordinary machine look broken.
    """
    lines = []
    for c in checks:
        tag = "OK" if c.ok else "MISS" if _is_fatal(c.label) else "WARN"
        line = "[%s] %-16s %s" % (tag, c.label, c.detail)
        if c.ok:
            line += f"  ({c.source})"
        else:
            line += f"  -> {c.hint}"
        lines.append(line)
    ok = sum(1 for c in checks if c.ok)
    lines.append("%d/%d checks OK" % (ok, len(checks)))
    warned = _warnings(checks)
    if warned:
        lines.append("%d not required for a build here: %s"
                     % (len(warned), ", ".join(c.label for c in warned)))
    return lines


def as_json(checks):
    """Machine-readable form: the same rows the text report renders.

    This payload is a **stable interface**: `python pipeline.py doctor
    --json` is what other tooling reads, so the shape below is pinned by
    `tests/test_doctor.py::TestJsonReport`.  ``checks`` is a list of objects
    with ``label``/``ok``/``detail``/``hint``/``source``; ``tools`` rows add
    ``key``/``path``/``status``/``purpose``; ``private`` carries the
    local-layout migration state per logical location.  ``ok`` ignores
    ``warnings`` because those are tools a build does not need here; ``warnings``
    names their labels so a caller can still surface them.  Adding a key is a
    compatible change, renaming or dropping one is not.
    """
    return json.dumps({
        "ok": not _blocking(checks),
        "checks": [c._asdict() for c in checks],
        "tools": tool_registry.probe_report(),
        "private": settings.migration_status(),
        "warnings": [c.label for c in _warnings(checks)],
    }, indent=2, ensure_ascii=False)


def run(argv=None):
    """Run the self-check and return the exit code (0 = nothing blocking, 1 =
    something required is missing/broken). `--json` switches to the
    machine-readable report."""
    # The report contains CJK (local paths, game names in config overrides),
    # so a redirected cp1252 console killed the tool at the exact moment it
    # was reporting a problem.  Doctor may be run before anything else is
    # usable, so it repairs the streams itself instead of relying on a CLI
    # framework wrapper (its `main()` calls sys.exit directly).
    logsetup.ensure_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    as_machine = "--json" in argv
    checks = collect_checks()
    if as_machine:
        print(as_json(checks))
    else:
        for line in render(checks):
            print(line)
    return 1 if _blocking(checks) else 0


def main(argv=None):
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
