#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Environment self-check for the RPG Maker -> JoiPlay toolkit.

`pipeline.py doctor` (this module) prints a compact report of everything the
toolkit depends on and exits non-zero when something is missing:

  * native tool binaries  ffmpeg / ffprobe / 7z / rg / git / npx
                          (resolved through config.find_*)
  * Windows-side tools    win_7z / win_ffmpeg / win_rg (used to process
                          files stored on the Windows side, see the
                          AGENTS.md cross-system CRITICAL rule)
  * machine config        docs/table/env_config.json readable
  * deliverable folders   games / archives / temp exist

Each line is `[OK] <label>  <detail>` or `[MISS] <label>  <detail>  hint`,
so the report stays greppable.  Exit code: 0 when every check passes, 1
when any check is missing/failing (pipeline.py doctor propagates it).

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

Check = namedtuple("Check", ("label", "ok", "detail", "hint"))

# (label, resolver, hint-on-missing). Resolvers are looked up lazily inside
# collect_checks() so monkeypatching config.find_* is honored per run.
_TOOL_CHECKS = [
    ("ffmpeg", "find_ffmpeg",
     "audio re-encode (audio.py) will fail; install ffmpeg with libvorbis "
     "or set FFMPEG / config tools.<platform>.ffmpeg"),
    ("ffprobe", "find_ffprobe",
     "audio probing (audio.py) will fail; ships with ffmpeg, or set FFPROBE"),
    ("7z", "find_7z",
     "compress / deliver need 7-Zip-Zstandard (-m0=zstd); set SEVENZ or "
     "config tools.<platform>.7z"),
    ("rg", "find_rg",
     "fast content search in builds (clean/verify); optional, degrades to "
     "a Python fallback"),
    ("git", "find_git",
     "repo versioning / hygiene; only needed for the dev workflow, not for "
     "conversion"),
    ("npx", "find_npx",
     "TyranoScript builds unpack app.asar via npx @electron/asar; only "
     "needed for tyrano games (Node.js required)"),
]

_WIN_CHECKS = [
    ("win_7z", "win_7z",
     "Windows-side 7z used by deliver to process /mnt/* files (CRITICAL "
     "cross-system rule); install 7-Zip-Zstandard on Windows or set "
     "SEVENZ_WIN"),
    ("win_ffmpeg", "win_ffmpeg",
     "Windows-side ffmpeg for Windows-side files; only needed when files "
     "are processed on the Windows side"),
    ("win_rg", "win_rg",
     "Windows-side ripgrep; optional"),
]

_DIR_CHECKS = [
    ("games_dir", "games_dir",
     "finished builds land here (deliver step); create it or point "
     "deliverables.games elsewhere in env_config.json"),
    ("archives_dir", "archives_dir",
     "finished archives land here (deliver step); create it or point "
     "deliverables.archives elsewhere"),
    ("temp_dir", "temp_dir",
     "work copies live here; must exist and be writable (deliverables.temp)"),
]


def _resolver(name):
    return getattr(config, name)


def _env_config_status():
    """(ok, detail) for the gitignored machine config file. Parses the file
    directly instead of config._load_env_config() because that helper
    silently swallows JSON/IO errors (returns {}), which would mask a
    corrupt config here."""
    if not config.LOCAL_ENV_FILE.is_file():
        return False, "(missing) %s" % config.LOCAL_ENV_FILE
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
    for label, fname, hint in _TOOL_CHECKS:
        p = _resolver(fname)()
        checks.append(Check(label, bool(p), p or "(not found)", hint))
    for label, fname, hint in _WIN_CHECKS:
        p = _resolver(fname)()
        checks.append(Check(label, bool(p), p or "(not configured)", hint))
    ok, detail = _env_config_status()
    checks.append(Check(
        "env_config.json", ok, detail,
        "machine config with deliverable paths; missing -> built-in "
        "defaults used (may point at non-existent dirs)"))
    for label, fname, hint in _DIR_CHECKS:
        d = _resolver(fname)()
        checks.append(Check(label, os.path.isdir(d), d, hint))
    return checks


def render(checks):
    """Render the report as a list of lines (one per check + a summary)."""
    lines = []
    for c in checks:
        tag = "OK" if c.ok else "MISS"
        line = "[%s] %-16s %s" % (tag, c.label, c.detail)
        if not c.ok:
            line += "  -> %s" % c.hint
        lines.append(line)
    ok = sum(1 for c in checks if c.ok)
    lines.append("%d/%d checks OK" % (ok, len(checks)))
    return lines


def run(argv=None):
    """Run the self-check and return the exit code (0 = all OK, 1 = any
    missing/failing). argv is accepted for CLI-style entry (no options)."""
    checks = collect_checks()
    for line in render(checks):
        print(line)
    return 0 if all(c.ok for c in checks) else 1


def main(argv=None):
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
