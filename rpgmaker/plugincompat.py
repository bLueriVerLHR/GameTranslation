#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plugincompat.py - browser/JoiPlay compatibility scan + repair for plugins.

Why this exists
---------------
The JoiPlay build strips the NW.js desktop runtime, so a plugin that touches an
NW.js-only global (``process``, ``require``) at MODULE SCOPE - i.e. while the
plugin file is still being loaded - throws in a plain browser/WebView, and
every top-level statement after that line never runs.  The game still boots, so
nothing else notices: ``verify`` sees a healthy build, the HTTP smoke test
answers 200, every audio file decodes.  The damage is silent and feature-shaped
("the HUD is missing in game, on the phone only").

The known repeat offender is the SRD "Super Tools Engine" plugin: its file reads
``process.versions['node-webkit']`` twice at load time, the second read kills
the plugin, and because that plugin is also what creates
``DataManager._testExceptions``, the *separate* plugin ``SRD_HUDMaker`` dies on
its own ``DataManager._testExceptions.push(...)`` line too.  Consequence: the
HUD data files (Windows/Notes/MapHUD/BattleHUD.json) are never registered in
``DataManager._databaseFiles`` and the in-game HUD silently disappears.

Two levels of handling, both limited to plugins that ``js/plugins.js`` actually
enables (a disabled plugin never executes, so it is never touched):

* ``REPAIRS`` - narrow, per-plugin rewrites of a *known* check into a guarded
  form.  One line in, one line out.  Idempotent: a line that already carries a
  guard (``GUARD_MARK``) is left alone, and the rewritten form no longer
  matches its own pattern, so re-running writes nothing.  This is deliberately
  a small explicit table, never a general JS rewriter.
* ``scan`` - advisory report of module-scope ``process`` / ``require(``
  references in enabled plugins (comments excluded, quoted strings respected).
  It never rewrites unknown plugin code; it names what a human must still look
  at, e.g. a plugin that reads ``process.mainModule.filename`` at load time.

Only the first matching rule is applied per line, and only to files that decode
as UTF-8 or CP932 - community plugin files are often Shift-JIS, and a blind
utf-8 read+write would corrupt them.

``js/plugins.js`` parsing is delegated to ``tools/plugins_io.py``, the
toolkit's single plugins.js parser (``tools/`` sits next to this package and is
importable in every supported invocation: pipeline entry, tools, tests).

Usage (pipeline command ``compat``, run it right after ``build``)::

    python pipeline.py compat <build-dir> [--dry-run] [--strict]
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

from tools import plugins_io

log = logging.getLogger("rpgmaker.plugincompat")

#: POSIX-style on purpose: they are joined onto a web root (Windows accepts
#: forward slashes) and they end up in log lines, which should not change
#: separator depending on the platform.
PLUGINS_JS = "js/plugins.js"
PLUGIN_DIR = "js/plugins"

#: A repaired line always carries this marker; the repair and the scan both use
#: it to recognise "already handled" text (that is what makes repair idempotent).
GUARD_MARK = "typeof process"

#: ``Repair.plugin`` value that matches every enabled plugin.  Used for the
#: checks that are not tied to one plugin file (a Steam build can put its boot
#: gate in any plugin).
ANY_PLUGIN = "*"

#: ``Repair.scope`` values.  ``module`` = a module-scope line at load time (the
#: NW.js crash class this module was built for); ``any`` = every line, needed by
#: checks that live inside a function but still abort the boot.
SCOPE_MODULE = "module"
SCOPE_ANY = "any"

#: Steam build boot gate, the usual shape of MV's Steam ownership check:
#: ``if (!<steam>.isSubscribedApp(<appid>)) throw ...`` inside the splash scene.
#: On desktop Steam this is a real ownership check; in a browser/WebView build
#: (no NW.js runtime, no Steam) the same call is a stub that can only answer
#: false, so the gate throws before the title screen and the build never boots.
#: Guarding on "Steam is actually running" keeps the desktop semantics intact
#: and lets a web build start.  ``isSteamRunning`` is probed with ``&&`` so an
#: object exposing only ``isSubscribedApp`` skips the gate instead of throwing.
_STEAM_OWNERSHIP_RE = re.compile(
    r"(?<![\w.$])if\s*\(\s*!\s*"
    r"(?P<obj>[\w$.]+)\.isSubscribedApp\s*\(\s*(?P<appid>\d+)\s*\)\s*\)")

#: NW.js-only global.  ``q`` is the quote character used around
#: ``node-webkit``; the repairs reuse that name inside their own patterns and
#: reference it by name (numeric groups would collide when concatenated).
_NWJS_VERSION = r"process\.versions\[(?P<q>['\"])node-webkit(?P=q)\]"
_NWJS_VERSION_RE = re.compile(_NWJS_VERSION)
_PROCESS_RE = re.compile(r"\bprocess\b")
_REQUIRE_RE = re.compile(r"\brequire\s*\(")
#: String literals, blanked before the generic `process`/`require` match so a
#: top-level `var s = "process";` is not reported.  The NW.js version check is
#: matched on the raw line, because its argument IS a string literal.
_STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")

#: Encodings a plugin file may use: UTF-8 (with and without BOM), plus cp932
#: for the (still common) Shift-JIS plugin file with Japanese comments.  A BOM
#: is preserved exactly as found - writing with "utf-8-sig" would *add* one to
#: a file that never had it.
_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class Repair:
    """One narrow, plugin-specific rewrite of a known NW.js-only check."""

    rule_id: str
    #: plugin base name (with or without the ".js" suffix), or ``ANY_PLUGIN``.
    plugin: str
    pattern: re.Pattern
    replacement: str
    why: str
    #: ``SCOPE_MODULE`` (default) or ``SCOPE_ANY``.
    scope: str = SCOPE_MODULE

    def applies_to(self, plugin_file):
        if self.plugin == ANY_PLUGIN:
            return True
        return _same_plugin(self.plugin, plugin_file)


REPAIRS = (
    Repair(
        rule_id="srd-super-tools-nwjs-if",
        plugin="SRD_SuperToolsEngine.js",
        pattern=re.compile(r"(?<![\w.$])if\s*\(\s*(?P<vw>" + _NWJS_VERSION + r")"),
        replacement=r'if(typeof process !== "undefined" && process.versions && \g<vw>',
        why="load-time NW.js version gate aborts the whole plugin outside NW.js",
    ),
    Repair(
        rule_id="srd-super-tools-nwjs-compare",
        plugin="SRD_SuperToolsEngine.js",
        pattern=re.compile(r"(?<![\w.$])" + _NWJS_VERSION +
                           r"\s*(?P<cmp>>=\s*(?P<q2>['\"])0\.13\.0(?P=q2))"),
        replacement=(r'((typeof process !== "undefined" && process.versions) ? '
                     r"process.versions[\g<q>node-webkit\g<q>] \g<cmp> : false)"),
        why="NW.js version read used as a value: keep the flag false outside NW.js",
    ),
    Repair(
        rule_id="steam-ownership-gate",
        plugin=ANY_PLUGIN,
        scope=SCOPE_ANY,
        pattern=_STEAM_OWNERSHIP_RE,
        replacement=(r'if (\g<obj>.isSteamRunning && '
                     r'\g<obj>.isSteamRunning() && '
                     r'!\g<obj>.isSubscribedApp(\g<appid>))'),
        why="Steam ownership gate can only answer false outside a Steam "
            "runtime and aborts the boot before the title screen",
    ),
)


@dataclass(frozen=True)
class Finding:
    """A module-scope NW.js-only reference that no repair rule covers."""

    plugin: str
    lineno: int
    text: str
    kind: str            # "nwjs-version" | "load-time-process" | "load-time-require"

    def __str__(self):
        return "%s:%d: %s" % (self.plugin, self.lineno, self.text)


@dataclass(frozen=True)
class Edit:
    """One applied (or, in --dry-run, one would-be) line rewrite."""

    plugin: str
    lineno: int
    rule_id: str
    before: str
    after: str


@dataclass
class Report:
    """What one ``run``/``repair`` pass did and what it could not do."""

    edits: list = field(default_factory=list)
    skipped: list = field(default_factory=list)    # (plugin, reason)
    findings: list = field(default_factory=list)

    @property
    def files_changed(self):
        return sorted({e.plugin for e in self.edits})


def _base(name):
    """Plugin base name: no directory, no ".js", case-folded."""
    base = os.path.basename(name).lower()
    return base[:-3] if base.endswith(".js") else base


def _same_plugin(a, b):
    return _base(a) == _base(b)


def enabled_plugins(web_root):
    """Plugin file names enabled in ``js/plugins.js``, in load order.

    ``status: false`` entries are skipped - they are never loaded, so repairing
    them would be dead work.  The ``.js`` suffix is added when the editor wrote
    the bare name (MV style; MZ writes it with the suffix).
    """
    path = os.path.join(web_root, PLUGINS_JS)
    if not os.path.isfile(path):
        log.warning("no %s under %s; nothing to scan", PLUGINS_JS, web_root)
        return []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    names = []
    for entry in plugins_io.parse_plugins_js(text):
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if entry.get("status") is False:
            continue
        names.append(name if name.lower().endswith(".js") else name + ".js")
    return names


def _strip_comments(line, in_block):
    """Return ``(code, in_block)`` with JS comments removed from one line.

    Quoted strings are respected, so a ``//`` inside a string is not a comment.
    ``in_block`` carries ``/* ... */`` state across lines.
    """
    out = []
    i, n = 0, len(line)
    quote = None
    while i < n:
        ch = line[i]
        if in_block:
            if line.startswith("*/", i):
                in_block = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if line.startswith("//", i):
            break
        if line.startswith("/*", i):
            in_block = True
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out), in_block


def _walk(text):
    """Yield ``(lineno, line, code)``; ``code`` is the comment-free line."""
    in_block = False
    for lineno, line in enumerate(text.splitlines(keepends=True), 1):
        code, in_block = _strip_comments(line, in_block)
        yield lineno, line, code


def _code_only(code):
    """The line with string-literal contents blanked out (for matching)."""
    return _STRING_RE.sub('""', code)


def _module_scope(code):
    """True when the line's first code character sits at column 0.

    Everything indented lives inside a function/block, which cannot run at load
    time unless something else calls it - the crash class this module hunts is
    module-scope code, so indented lines are out of scope on purpose.
    """
    return bool(code) and not code[0].isspace()


def _read_text(path):
    """Return ``(text, encoding)``, or ``(None, None)`` when undecodable.

    The returned encoding is what the file must be written back with: it keeps
    a BOM only when the file already had one.
    """
    with open(path, "rb") as f:
        raw = f.read()
    attempts = ("utf-8-sig", "utf-8") if raw.startswith(_BOM) else ("utf-8",)
    for enc in attempts + ("cp932",):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None, None


def _plugin_paths(web_root):
    """Yield ``(plugin_file_name, path)`` for every enabled plugin on disk."""
    for name in enabled_plugins(web_root):
        path = os.path.join(web_root, PLUGIN_DIR, name)
        if os.path.isfile(path):
            yield name, path
        else:
            log.warning("plugin %s is enabled in %s but %s is missing",
                        name, PLUGINS_JS, os.path.join(PLUGIN_DIR, name))


def scan(web_root):
    """Advisory scan: module-scope NW.js-only references in enabled plugins.

    Returns a list of :class:`Finding`.  Repaired lines are not reported (they
    carry ``GUARD_MARK``), so a clean run after ``repair`` returns only what a
    human still has to decide about.
    """
    findings = []
    for name, path in _plugin_paths(web_root):
        text, _enc = _read_text(path)
        if text is None:
            log.warning("%s is neither UTF-8 nor CP932; scan skipped", path)
            continue
        for lineno, _line, code in _walk(text):
            if GUARD_MARK in code or not _module_scope(code):
                continue
            if _NWJS_VERSION_RE.search(code):
                kind = "nwjs-version"
            elif _PROCESS_RE.search(_code_only(code)):
                kind = "load-time-process"
            elif _REQUIRE_RE.search(_code_only(code)):
                kind = "load-time-require"
            else:
                continue
            findings.append(Finding(name, lineno, code.strip(), kind))
    return findings


def _repair_text(plugin, text, rules):
    """Apply the first matching rule per line -> (text, edits).

    ``SCOPE_MODULE`` rules only see module-scope lines; ``SCOPE_ANY`` rules see
    every line (a boot gate inside a function is just as fatal).
    """
    out = []
    edits = []
    for lineno, line, code in _walk(text):
        if code.strip() and GUARD_MARK not in code:
            at_module_scope = _module_scope(code)
            for rule in rules:
                if rule.scope != SCOPE_ANY and not at_module_scope:
                    continue
                new_line, count = rule.pattern.subn(rule.replacement, line)
                if count:
                    edits.append(Edit(
                        plugin, lineno, rule.rule_id,
                        line.rstrip("\r\n"), new_line.rstrip("\r\n")))
                    line = new_line
                    break
        out.append(line)
    return "".join(out), edits


def repair(web_root, dry_run=False):
    """Repair known NW.js-only checks, then scan for what is left.

    Writes only the files that actually change, keeps each file's original
    encoding and line endings, and never touches a disabled plugin.  With
    ``dry_run`` the report holds the edits that *would* be made.
    """
    report = Report()
    for name, path in _plugin_paths(web_root):
        rules = [r for r in REPAIRS if r.applies_to(name)]
        if not rules:
            continue
        text, enc = _read_text(path)
        if text is None:
            report.skipped.append((name, "neither UTF-8 nor CP932"))
            log.warning("%s is neither UTF-8 nor CP932; left untouched", path)
            continue
        new_text, edits = _repair_text(name, text, rules)
        if not edits:
            continue
        report.edits.extend(edits)
        for edit in edits:
            log.info("%s/%s:%d: %s -> %s", PLUGIN_DIR, name, edit.lineno,
                     edit.before.strip(), edit.after.strip())
        if not dry_run:
            with open(path, "w", encoding=enc, newline="") as f:
                f.write(new_text)
    report.findings = scan(web_root)
    return report


def run(web_root, dry_run=False, strict=False):
    """``repair`` + the standard log summary.  Returns the :class:`Report`.

    ``strict`` only affects the log line: the caller decides the exit code
    (``compat --strict`` fails when anything is left for a human).
    """
    report = repair(web_root, dry_run=dry_run)
    verb = "would guard" if dry_run else "guarded"
    if report.edits:
        log.info("%s %d NW.js-only site(s) in %d enabled plugin file(s): %s",
                 verb, len(report.edits), len(report.files_changed),
                 ", ".join(report.files_changed))
    elif report.skipped:
        log.warning("nothing repaired: %s",
                    ", ".join("%s (%s)" % s for s in report.skipped))
    else:
        log.info("plugin compat: no known browser/JoiPlay plugin breakage found")
    for finding in report.findings:
        log.warning("load-time NW.js usage left in an enabled plugin (%s) - "
                    "review it by hand: %s", finding.kind, finding)
    if report.findings and strict:
        log.error("compat --strict: %d load-time NW.js reference(s) unhandled",
                  len(report.findings))
    return report
