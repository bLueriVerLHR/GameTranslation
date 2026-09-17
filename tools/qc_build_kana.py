#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kana-residue QC on a *baked* RPG Maker MZ/MV build - the acceptance check.

The five library gates run **before** baking and only see the strings the
extractor knows about.  This tool runs after baking and looks at the whole
``data/`` tree, so it also catches display text the extractor never collected
(a field that was wrongly classified as "not text" stays invisible to a gate
but shows up here).  A green gate report therefore never substitutes for it:

    PASS  <=>  no unexpected kana left in data/  AND  no %N parity break

Classification of what **must** be translated is deliberate:

* the residue class is *kana letters*; the prolongation mark ``ー``/``ｰ`` and
  the middle dot ``・`` are excluded, because translated Chinese text keeps
  them legitimately (spell names, loan words) and counting them buries the
  real misses;
* by-design skips: comment commands (108/408), commands whose string
  parameters are **payload rather than display text** (111 conditional
  branch, 355/655 script, 356/0 menu-command plugin text), the internal
  ``name`` of Animations/CommonEvents/MapInfos/Tilesets, and every ``note``
  field (it carries plugin commands, not prose);
* ``allow_kana.json`` from the translation workspace (author names, fixed
  spellings) is honoured when ``--work`` is given.

Plugin parameters (``js/plugins.js``) are reported as an **inventory**, never
as a pass/fail: builds that exclude them from translation by decision must
say how many strings that leaves, so the number is visible instead of implied
by a PASS.

Usage:
    python3 tools/qc_build_kana.py <build_dir> [--source JA_DIR] [--work WORK]
                                   [--limit N] [--json]
"""
import json
import logging
import os
import re
import sys
from typing import Annotated, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402
from translation import mvkeys  # noqa: E402

log = logging.getLogger("qc_build_kana")

#: Kana *letters* only: hiragana, katakana (without ー and ・), halfwidth
#: katakana letters.  See the docstring for why the mark/dot stay out.
KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fd"
                  r"\uff66-\uff6f\uff71-\uff9d]")
PLACEHOLDER = re.compile(r"%\d")

#: Command codes that never carry display text.
COMMENT_CODES = (108, 408)
#: Command codes whose string parameters are logic payload or raw script.
LOGIC_CODES = (111, 355, 356, 655)
#: Fields that hold editor-internal names (never shown to the player).
INTERNAL_NAME_FIELDS = frozenset([
    ("Animations.json", "name"), ("CommonEvents.json", "name"),
    ("MapInfos.json", "name"), ("Tilesets.json", "name"),
])
#: Every ``note`` field is a skip: plugin commands, not prose.
NOTE_FIELD = "note"


def load_allow_list(work_dir):
    """``allow_kana.json`` entries from the translation workspace."""
    if not work_dir:
        return []
    path = os.path.join(work_dir, "allow_kana.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        log.warning("allow_kana.json unreadable (%s) - ignoring it", exc)
        return []
    return [item["match"] for item in data.get("items", []) if item.get("match")]


def is_allowed(text, allow_list):
    """Does an allow-list entry cover this string?  (substring or ``re:``)"""
    for pattern in allow_list:
        if pattern.startswith("re:"):
            if re.search(pattern[3:], text):
                return True
        elif pattern in text:
            return True
    return False


def params_of(command):
    """Parameters of either command shape (``[401, 0, "x"]`` or object)."""
    if isinstance(command, dict):
        return command.get("parameters") or []
    if isinstance(command, (list, tuple)) and len(command) >= 3:
        return list(command[2:])
    return []


def walk_strings(node, trail, code=None):
    """Every string under ``node``, as ``(trail, text, enclosing code)``."""
    found = []
    if isinstance(node, str):
        found.append((trail, node, code))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(walk_strings(item, "%s[%d]" % (trail, index), code))
    elif isinstance(node, dict):
        for key, item in node.items():
            found.extend(walk_strings(item, "%s.%s" % (trail, key), code))
    return found


def walk_document(node, trail=""):
    """Strings of a data file, tagging those inside an event command list.

    Command parameters are tagged with their code so the by-design rules can
    see the context (a comment command's text versus a dialogue line); every
    other string is reported with ``code=None`` and classified on its field.
    """
    found = []
    if isinstance(node, dict):
        for key, item in node.items():
            path = "%s.%s" % (trail, key) if trail else key
            if key == "list" and isinstance(item, list):
                for index, command in enumerate(item):
                    code = mvkeys.command_code(command)
                    for position, value in enumerate(params_of(command)):
                        found.extend(walk_strings(
                            value, "%s.list[%d].parameters[%d]"
                            % (path, index, position), code))
            else:
                found.extend(walk_document(item, path))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(walk_document(item, "%s[%d]" % (trail, index)))
    elif isinstance(node, str):
        found.append((trail, node, None))
    return found


def field_name(trail):
    """The last field of a trail, with list indexes flattened away."""
    return re.sub(r"\[\d+\]", "[]", trail).split(".")[-1]


def classify(file_name, trail, text, code, allow_list):
    """``"allowed"`` / ``"by-design"`` / ``"unexpected"`` for one residue hit."""
    if is_allowed(text, allow_list):
        return "allowed"
    if code is not None and (code in COMMENT_CODES or code in LOGIC_CODES):
        return "by-design"
    field = field_name(trail)
    if (file_name, field) in INTERNAL_NAME_FIELDS or field == NOTE_FIELD:
        return "by-design"
    return "unexpected"


def source_strings(source_dir, file_name):
    """``{trail: text}`` of the Japanese original, for %N parity."""
    path = os.path.join(source_dir, "data", file_name)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        log.warning("source %s unreadable (%s)", file_name, exc)
        return {}
    return {trail: text for trail, text, _code in walk_document(document)}


def scan(build_dir, source_dir=None, work_dir=None, plugin_scan=True):
    """Scan a baked build; returns the finding structure of :func:`report`."""
    data_dir = os.path.join(build_dir, "data")
    if not os.path.isfile(os.path.join(data_dir, "System.json")):
        raise FileNotFoundError(
            "not an MZ/MV build (no data/System.json): %s" % build_dir)
    allow_list = load_allow_list(work_dir)
    findings = {"unexpected": [], "by_design": [], "allowed": [],
                "placeholder": [], "files": 0, "strings": 0}
    for file_name in sorted(os.listdir(data_dir)):
        if not file_name.endswith(".json"):
            continue
        path = os.path.join(data_dir, file_name)
        try:
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, ValueError) as exc:
            findings.setdefault("unreadable", []).append((file_name, str(exc)))
            log.warning("%s: unreadable (%s)", file_name, exc)
            continue
        findings["files"] += 1
        strings = walk_document(document)
        findings["strings"] += len(strings)
        for trail, text, code in strings:
            if not KANA.search(text):
                continue
            bucket = classify(file_name, trail, text, code, allow_list)
            entry = (file_name, trail, text, code)
            findings["by_design" if bucket == "by-design" else
                     "allowed" if bucket == "allowed" else
                     "unexpected"].append(entry)
        if source_dir:
            original = source_strings(source_dir, file_name)
            for trail, text, _code in strings:
                key = original.get(trail)
                if key is None or not PLACEHOLDER.search(key):
                    continue
                if sorted(PLACEHOLDER.findall(key)) != sorted(PLACEHOLDER.findall(text)):
                    findings["placeholder"].append((file_name, trail, key, text))
    if plugin_scan:
        findings["plugins"] = scan_plugins(build_dir)
    return findings


def scan_plugins(build_dir):
    """Count kana strings inside js/plugins.js parameters (inventory only).

    Plugin parameters are excluded from translation by decision on some
    builds (they mix asset names, identifier keys the plugin looks up by name
    and large configuration blobs).  They are never counted as a residue hit
    here, but the count is reported so the exclusion stays visible.
    """
    path = os.path.join(build_dir, "js", "plugins.js")
    if not os.path.isfile(path):
        return {"strings": 0, "samples": []}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        log.warning("js/plugins.js unreadable (%s)", exc)
        return {"strings": 0, "samples": []}
    match = re.search(r"var\s+\$plugins\s*=\s*(\[.*?\]);", text, re.S)
    if not match:
        log.warning("js/plugins.js: $plugins array not found")
        return {"strings": 0, "samples": []}
    try:
        plugins = json.loads(match.group(1))
    except ValueError as exc:
        log.warning("js/plugins.js: $plugins unparsable (%s)", exc)
        return {"strings": 0, "samples": []}
    samples = []
    for index, plugin in enumerate(plugins):
        for name, value in (plugin.get("parameters") or {}).items():
            if isinstance(value, str):
                values = [value]
            elif isinstance(value, list):
                values = [item for item in value if isinstance(item, str)]
            else:
                values = []
            for item in values:
                if KANA.search(item):
                    samples.append(("js/plugins.js#[%d].parameters.%s"
                                    % (index, name), item))
    return {"strings": len(samples), "samples": samples}


def report(findings, limit=25, stream=None):
    """Print the human report; returns the number of problems found."""
    stream = stream or sys.stdout
    unexpected = findings["unexpected"]
    placeholders = findings["placeholder"]
    stream.write("data/: %d file(s), %d string(s) scanned\n"
                 % (findings["files"], findings["strings"]))
    stream.write("kana residue: %d unexpected, %d by-design, %d allowed\n"
                 % (len(unexpected), len(findings["by_design"]),
                    len(findings["allowed"])))
    for file_name, trail, text, code in unexpected[:limit]:
        stream.write("   UNEXPECTED %s (code %s) %s\n"
                     % (file_name, code, trail[-60:]))
        stream.write("      %s\n" % repr(text[:90]))
    if len(unexpected) > limit:
        stream.write("   ... %d more\n" % (len(unexpected) - limit))
    stream.write("placeholder (%%N) mismatches: %d\n" % len(placeholders))
    for file_name, trail, japanese, translated in placeholders[:limit]:
        stream.write("   %s %s\n      ja=%s\n      zh=%s\n"
                     % (file_name, trail[-60:], repr(japanese[:70]),
                        repr(translated[:70])))
    plugins = findings.get("plugins")
    if plugins is not None:
        stream.write("plugin parameters (js/plugins.js, excluded by policy): "
                     "%d kana string(s)\n" % plugins["strings"])
        for where, text in plugins["samples"][:limit]:
            stream.write("   INFO %s = %s\n" % (where, repr(text[:70])))
    for file_name, message in findings.get("unreadable", []):
        stream.write("   UNREADABLE %s: %s\n" % (file_name, message))
    problems = len(unexpected) + len(placeholders) \
        + len(findings.get("unreadable", []))
    stream.write("\n%s\n" % ("PASS" if not problems else "REVIEW NEEDED"))
    return problems


def cmd(build_dir: Annotated[str, cliutil.Argument(
            help="baked MZ/MV build (web root) to scan")],
        source: Annotated[Optional[str], cliutil.Option(
            "--source", help="Japanese original build, for %N parity")] = None,
        work: Annotated[Optional[str], cliutil.Option(
            "--work", help="translation workspace, for allow_kana.json")] = None,
        limit: Annotated[int, cliutil.Option(
            "--limit", help="samples printed per section")] = 25,
        as_json: Annotated[bool, cliutil.Option(
            "--json", help="machine-readable output")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Scan a baked build for Japanese residue and %N parity breaks."""
    cliutil.setup_logging(verbose, quiet, log_file)
    try:
        findings = scan(build_dir, source, work)
    except FileNotFoundError as exc:
        return cliutil.fail(str(exc))
    if as_json:
        print(json.dumps(findings, ensure_ascii=False, indent=1))
        problems = len(findings["unexpected"]) + len(findings["placeholder"]) \
            + len(findings.get("unreadable", []))
    else:
        problems = report(findings, limit)
    log.info("kana residue: %d unexpected, %d by-design; %d placeholder mismatch(es)",
             len(findings["unexpected"]), len(findings["by_design"]),
             len(findings["placeholder"]))
    return 1 if problems else 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="qc_build_kana.py")


if __name__ == "__main__":
    raise SystemExit(main())
