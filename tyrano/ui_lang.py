#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Localize the TyranoScript engine UI (``tyrano/lang.js``).

``tyrano/lang.js`` ships with every TyranoScript game and holds the engine's
own player-facing text - the confirm dialog when returning to the title, the
"no save data" notice, the script-error alerts.  It lives outside
``data/scenario``, so no scenario extractor ever sees it: a build whose
scenario is fully translated still shows Japanese in those dialogs.

Only the ``word`` block carries sentences; ``novel`` holds engine image
filenames and is never touched.  Entries are matched **by key**
(``go_title``, ``not_saved``, ...), not by their Japanese text, so a mapping
stays valid across engine revisions and only replaces what the file actually
has - unknown keys are reported, never inserted, and untouched entries keep
their bytes.

A mapping is a plain ``{key: translation}`` JSON file that can be passed to
other games (see ``ui_lang_zh.json`` next to this module for the TyranoScript
6.00 set).

Usage:
    python3 -m tyrano.ui_lang dump  <build|lang.js> [-o out.json]
    python3 -m tyrano.ui_lang apply <build|lang.js> --map ui_lang_zh.json
"""
import json
import logging
import os
import re
import sys
from collections import OrderedDict
from typing import Annotated, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("tyrano.ui_lang")

LANG_REL = os.path.join("tyrano", "lang.js")
DEFAULT_BLOCK = "word"

# One `key: "value"` entry of a lang.js block.  Values may span lines and
# may sit on the line *after* the colon (the stock file wraps its longest
# sentences that way), and may be single- or double-quoted (the stock file
# single-quotes exactly where the sentence contains a double quote), so the
# closing quote is a backreference and escapes are consumed first.  `lead`
# and `ws` stay inside the match so a rewrite reproduces the source layout
# byte for byte.
_ENTRY_RE = re.compile(
    r"(?P<lead>^|[{,\n])(?P<ws>[ \t\n]*)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<sep>[ \t]*:[ \t\n]*)"
    r"(?P<q>[\"'])(?P<val>(?:\\.|(?!(?P=q)).)*)(?P=q)",
    re.S | re.M)

# A line comment would break the entry regex, but lang.js blocks are plain
# data; refuse to touch a block containing one rather than mangling it.
_COMMENT_RE = re.compile(r"//|/\*")

# Placeholders such as "{ name }" are filled in by the engine at runtime.
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")

# Engine messages never need kana in Chinese; the strict class (includes the
# middle dot and the long-vowel mark) mirrors the MZ translation gate.
KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff66-\uff6f\uff71-\uff9d]")


def find_lang_file(path):
    """Accept either the build root or the lang.js path itself."""
    if os.path.isfile(path):
        return path
    candidate = os.path.join(path, LANG_REL)
    return candidate if os.path.isfile(candidate) else None


def read_lang(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _block_span(text, block):
    """Return (body_start, body_end) of `block`'s object literal, or None."""
    m = re.search(r"\b%s\s*:\s*\{" % re.escape(block), text)
    if not m:
        return None
    start = m.end()
    depth = 1
    # The block body is scanned with a minimal tokenizer: only its own
    # closing brace at depth 0 terminates it, so nested objects survive.
    i = start
    in_quote = None
    while i < len(text):
        ch = text[i]
        if in_quote:
            if ch == "\\":
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in "\"'":
            in_quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, i
        i += 1
    return None


def extract(path, block=DEFAULT_BLOCK):
    """OrderedDict key -> raw value (escapes exactly as written in the file)."""
    text = read_lang(path)
    span = _block_span(text, block)
    if not span:
        raise ValueError("%s: no '%s' block found" % (path, block))
    body = text[span[0]:span[1]]
    out = OrderedDict()
    for m in _ENTRY_RE.finditer(body):
        out[m.group("key")] = m.group("val")
    return out


def _quote_for(value, preferred):
    """Pick the quote character that needs no escaping, like the stock file."""
    for q in (preferred, '"' if preferred == "'" else "'"):
        if q not in value:
            return q
    return preferred


def check_value(old, new, key):
    """Return a problem string when `new` cannot replace `old`, else None."""
    if not new or not new.strip():
        return "empty translation"
    if "\r" in new:
        return "contains a carriage return"
    problems = []
    if sorted(_PLACEHOLDER_RE.findall(old)) != sorted(_PLACEHOLDER_RE.findall(new)):
        problems.append("placeholder mismatch (%s -> %s)"
                        % ("".join(_PLACEHOLDER_RE.findall(old)),
                           "".join(_PLACEHOLDER_RE.findall(new))))
    if old.count("\\n") != new.count("\\n"):
        problems.append("newline count %d -> %d"
                        % (old.count("\\n"), new.count("\\n")))
    if KANA_RE.search(new):
        problems.append("kana left: %s" % KANA_RE.search(new).group(0))
    return "; ".join(problems) if problems else None


def apply_map(path, mapping, block=DEFAULT_BLOCK, dry_run=False):
    """Replace values by key.  Returns a report dict.

    Entries whose translation fails the mechanical gate are refused (the file
    keeps the original bytes for that entry) so a bad mapping can never ship
    a broken engine message.
    """
    text = read_lang(path)
    span = _block_span(text, block)
    if not span:
        raise ValueError("%s: no '%s' block found" % (path, block))
    head, body, tail = text[:span[0]], text[span[0]:span[1]], text[span[1]:]
    if _COMMENT_RE.search(body):
        raise ValueError("%s: '%s' block contains a comment; refusing to "
                         "rewrite it" % (path, block))
    applied, refused, edits = [], [], []
    seen = set()
    for m in _ENTRY_RE.finditer(body):
        key = m.group("key")
        seen.add(key)
        if key not in mapping:
            continue
        old = m.group("val")
        new = mapping[key]
        if old == new:
            continue
        problem = check_value(old, new, key)
        if problem:
            refused.append("%s: %s" % (key, problem))
            continue
        q = _quote_for(new, m.group("q"))
        # The gate pinned the placeholder and \n shape, so the value goes in
        # verbatim between unescaped quotes.
        edits.append((m.start(), m.end(),
                      "%s%s%s%s%s%s%s" % (m.group("lead"), m.group("ws"),
                                          key, m.group("sep"), q, new, q)))
        applied.append(key)
    missing = [k for k in mapping if k not in seen]
    for start, end, replacement in reversed(edits):
        body = body[:start] + replacement + body[end:]
    report = {"applied": applied, "missing": missing, "refused": refused,
              "total": len(mapping)}
    if applied and not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            f.write(head + body + tail)
    return report


def _resolve(path):
    lang = find_lang_file(path)
    if not lang:
        raise FileNotFoundError("no %s under %s" % (LANG_REL, path))
    return lang


def cmd_dump(game: Annotated[str, cliutil.Argument(
        help="build folder or a path to tyrano/lang.js")],
        out: Annotated[Optional[str], cliutil.Option(
            "-o", "--out", help="write the Japanese strings as JSON")] = None,
        block: Annotated[str, cliutil.Option(
            "--block", help="lang.js block to read")] = DEFAULT_BLOCK,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """List the engine UI strings that need translating."""
    cliutil.setup_logging(verbose, quiet, log_file)
    lang = _resolve(game)
    strings = extract(lang, block)
    kana = OrderedDict((k, v) for k, v in strings.items() if KANA_RE.search(v))
    log.info("%s: %d entries in '%s', %d need translating",
             lang, len(strings), block, len(kana))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(kana, f, ensure_ascii=False, indent=4)
            f.write("\n")
        log.info("wrote %s", out)
    else:
        for key, val in kana.items():
            print("%s\t%s" % (key, val))
    return 0


def cmd_apply(game: Annotated[str, cliutil.Argument(
        help="build folder or a path to tyrano/lang.js")],
        mapping: Annotated[str, cliutil.Option(
            "--map", help="JSON {key: translation} to apply")] = None,
        block: Annotated[str, cliutil.Option(
            "--block", help="lang.js block to rewrite")] = DEFAULT_BLOCK,
        dry_run: Annotated[bool, cliutil.Option(
            "--dry-run", help="report only, write nothing")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Apply a {key: translation} JSON to the engine UI strings."""
    cliutil.setup_logging(verbose, quiet, log_file)
    lang = _resolve(game)
    if not mapping:
        return cliutil.fail("--map is required")
    with open(mapping, encoding="utf-8") as f:
        table = json.load(f)
    report = apply_map(lang, table, block=block, dry_run=dry_run)
    log.info("%s: %d applied, %d not in this lang.js, %d refused",
             lang, len(report["applied"]), len(report["missing"]),
             len(report["refused"]))
    for key in report["missing"]:
        log.warning("no such key in lang.js: %s", key)
    for item in report["refused"]:
        log.error("refused: %s", item)
    if report["refused"]:
        return cliutil.fail("%d entries refused; lang.js left unchanged for "
                            "them" % len(report["refused"]))
    return 0


app = cliutil.app(help=__doc__)
app.command(name="dump", help="list the engine UI strings")(cmd_dump)
app.command(name="apply", help="apply a {key: translation} JSON")(cmd_apply)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="ui_lang.py")


if __name__ == "__main__":
    raise SystemExit(main())
