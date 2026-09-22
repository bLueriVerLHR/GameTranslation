#!/usr/bin/env python3
"""proctools.py - the single place external programs are executed.

Every call site needs the same four things, and each one used to get them
differently:

  * a TIMEOUT - `npx`, `7z`, `node` and `powershell` can hang forever in an
    unattended pipeline run
  * UTF-8 decoding with ``errors="replace"`` - the host locale codec
    (cp932/cp1252 on Windows) raised UnicodeDecodeError on non-ASCII tool
    output, which turned a diagnostic line into a crash
  * a failure message that names the program, the exit code and the output
    tail, so no caller has to re-format it
  * list-form argv (never ``shell=True``) so paths with spaces stay safe

Usage::

    from rpgmaker import proctools
    proc = proctools.run(cmd, timeout=600, label="7z")
    proc = proctools.run(cmd, check=False)     # inspect returncode yourself

`check=True` (the default) raises RuntimeError; a missing program still
raises FileNotFoundError unchanged, so the resolver's install hint
(`rpgmaker.tool_registry.find_7z()` etc.) remains the message the user sees.
"""
import logging
import subprocess

log = logging.getLogger("rpgmaker.proctools")

# Unattended default: long enough for a real 7z/npx job, short enough that a
# hang is reported instead of blocking the run forever.
DEFAULT_TIMEOUT = 900
OUTPUT_TAIL = 2000
# text=True + explicit encoding: never let the locale codec decide.
DECODE = {"encoding": "utf-8", "errors": "replace"}

def argv_text(cmd):
    """The command as one readable line (for messages and DEBUG logs)."""
    return " ".join(str(c) for c in cmd)


def tail(proc, limit=OUTPUT_TAIL):
    """stderr when it carries content, else stdout, truncated to `limit`."""
    return (((proc.stderr or "").strip() or (proc.stdout or "").strip())
            [-limit:])


def run(cmd, *, timeout=DEFAULT_TIMEOUT, check=True, label=None, cwd=None,
        errors="replace"):
    """Run `cmd` (list form) and return the CompletedProcess.

    timeout=None waits forever - correct for intentional long jobs such as a
    video re-encode.  A timeout raises subprocess.TimeoutExpired (it already
    names the command and the limit); a non-zero exit with `check` raises
    RuntimeError naming the program, its exit code, the argv and the tail.
    `errors` defaults to "replace" so odd tool output cannot raise; a caller
    that parses binary-ish paths (git ls-files) may ask for
    "surrogateescape" instead.
    """
    cmd = list(cmd)
    name = label or (cmd[0] if cmd else "command")
    log.debug("run: %s", argv_text(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=cwd, encoding="utf-8", errors=errors)
    if check and proc.returncode != 0:
        raise RuntimeError("%s failed (exit %d): %s\n%s"
                           % (name, proc.returncode, argv_text(cmd),
                              tail(proc)))
    return proc
