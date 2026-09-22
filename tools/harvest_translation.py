#!/usr/bin/env python3
"""
harvest_translation.py - Harvest a runtime MTool/AI translation dict into the
extracted template (build_translation.py) so it can be baked statically.

MTool runtime dicts key on DISPLAYED text: control codes are stripped, the
inline speaker-name line (line 1 of a message block) is dropped, notes are
keyed from "<SG説明:" onward, and messages broken by line-wrap appear as
per-line fragments.  That layout is incompatible with the per-line static
data, but the VALUES are exactly what the game owner already approved, so we
re-join them into template keys with an exact-match harvest:

   for each template key, in order:
     1. exact match in the dict
     2. control codes stripped, match
     3. blocks: drop the speaker-name first line, match the rest
        (a first line is a speaker name ONLY when it is short pure
        kana/kanji + optional honorific after stripping codes — dialogue
        lines without corner brackets are never dropped as names)
     4. blocks: match each body line as a fragment, join the values
     5. event-text keys wrapped in double quotes: match the inner text
     6. notes: match from the first "<SG説明" tag onward

Keys with no match are written to <work_dir>/missing.json for AI translation.

Usage:
    python harvest_translation.py <work_dir> <mtool_dict.json> --out translated.json
"""
import json
import logging
import os
import re
import sys
from typing import Annotated


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root: rpgmaker/
sys.path.insert(0, _HERE)                   # sibling tools
import ctrl_codes  # noqa: E402
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("harvest")

# Multi-letter control codes too: \FX[F]\FFFFF[1000Kenji_0004] must strip
# fully, not just \F + residue (the block-prefix class).
CODE_RE = re.compile(r"\\[A-Za-z]+(\[[^\]]*\])?")


def strip_codes(s):
    return CODE_RE.sub("", s).strip()


def leading_codes(s):
    m = re.match(r"^((?:\\[A-Za-z]+\[[^\]]*\])+)", s)
    return m.group(1) if m else ""


def trailing_codes(s):
    m = re.search(r"((?:\\[A-Za-z]+\[[^\]]*\])+)$", s)
    return m.group(1) if m else ""


# A real speaker-name first line: pure kana/kanji (optional honorific suffix),
# no corner brackets, no punctuation, no control codes (codes stripped first:
# \C[3]<name> is still a name), short.  Anything else — dialogue without 「」,
# FX/code-prefixed dialogue — is BODY text: treating it as a dropped "name"
# leaves the first dialogue line untranslated inside the prefilled block value
# (MZ job 2026-08: 2,187 partial blocks; fix = drop those block keys so the
# per-line fragment path / missing keys cover every line).
NAME_LINE = re.compile(r"^(?:[\u3040-\u30ff\u4e00-\u9fff]|・)+"
                       r"[さんちゃん君様先生嬢ぽ]?$")


def is_name_line(line):
    if not line or "\u300c" in line or "\u300d" in line:
        return False
    stripped = strip_codes(line).strip()
    return bool(stripped) and len(stripped) <= 14 \
        and NAME_LINE.match(stripped) is not None


def split_block(k):
    lines = k.split("\n")
    if len(lines) > 1 and is_name_line(lines[0]):
        return lines[0], lines[1:]
    return None, lines


class Harvester:
    """Map template keys onto the runtime dict's entries.

    Holds the runtime dict (`runtime`) and its code-stripped index (`snorm`) so
    the lookup helpers can be methods instead of closures.
    """

    def __init__(self, runtime, kinds):
        self.runtime = runtime
        self.kinds = kinds
        self.snorm = {}
        for k, v in runtime.items():
            stripped = strip_codes(k)
            # A key that is nothing but control codes strips to "":
            # registering it under the empty key let ANY code-only key borrow
            # its value.  Such an entry is not usable as a strip-match source,
            # so it is skipped.
            if stripped:
                self.snorm.setdefault(stripped, v)

    def lookup(self, text):
        """The dict value for `text`, exact first, then code-stripped."""
        value = self.runtime.get(text)
        if isinstance(value, str) and value:
            return value
        value = self.snorm.get(strip_codes(text))
        if isinstance(value, str) and value:
            return value
        return None

    @staticmethod
    def with_codes(before, value, after):
        """Wrap a translation in the key's leading/trailing control codes.

        Values that already carry codes (MTool/AI dicts often keep them) are
        returned as they are - adding the key's codes again duplicated them,
        and the extra pair then showed up as a control-code diff in QC.
        """
        if ctrl_codes.CTRL_TOKEN.search(value):
            return value
        return before + value + after

    def rebuild_name(self, name_line):
        """Replace the speaker name inside a block's first line."""
        name = strip_codes(name_line)
        value = self.lookup(name)
        if value and name in self.runtime or (value and not any(
                c.isalpha() and ord(c) < 128 for c in name)):
            return (name_line.replace(name, value) if name in name_line
                    else name_line)
        return name_line

    def _strip_match(self, key):
        """`(value, how)` from a code-stripped match, or `(None, None)`."""
        stripped = self.snorm.get(strip_codes(key))
        if not (isinstance(stripped, str) and stripped):
            return None, None
        if "\n" in key:
            return stripped, "strip"
        before, after = leading_codes(key), trailing_codes(key)
        return self.with_codes(before, stripped, after), "strip"

    def _block_match(self, key):
        """`(value, how)` for a multi-line block key, or `(None, None)`.

        Tries the whole block body, then the per-line fragment match (every
        body line must be present in the dict).
        """
        name_line, body = split_block(key)
        rest = "\n".join(body)
        rest_value = self.snorm.get(strip_codes(rest))
        if isinstance(rest_value, str) and rest_value:
            if name_line is not None:
                return (self.rebuild_name(name_line) + "\n" + rest_value,
                        "drop-name")
            return rest_value, "strip"
        body_stripped = [strip_codes(line) for line in body if line.strip()]
        if body_stripped and all(self.snorm.get(b) for b in body_stripped):
            lines = [self.rebuild_name(name_line)] if name_line is not None else []
            lines += [self.snorm[b] for b in body_stripped]
            return "\n".join(lines), "fragment"
        return None, None

    def _quoted_match(self, key):
        """`(value, how)` for a quoted `event-text` key, or `(None, None)`."""
        inner = key[1:-1]
        inner_value = self.snorm.get(strip_codes(inner))
        if not (isinstance(inner_value, str) and inner_value):
            return None, None
        # Style switches inside the quotes belong to the value: the lookup
        # dropped them (it matches on stripped text), so they are put back
        # instead of shipping a code-less string.
        before, after = leading_codes(inner), trailing_codes(inner)
        return '"' + self.with_codes(before, inner_value, after) + '"', "quoted"

    def _note_match(self, key):
        """`(value, how)` for a `note` key carrying the plugin marker."""
        index = key.find("<SG説明")
        if index < 0:
            return None, None
        note_value = self.snorm.get(strip_codes(key[index:]))
        if not (isinstance(note_value, str) and note_value):
            return None, None
        # key[:index] is literal text that belongs in the value, and it
        # already carries whatever leading codes the note has: prepending
        # leading_codes(key[:index]) duplicated them.
        return key[:index] + note_value, "note"

    def value_for(self, key):
        """`(value, how)` for one template key; `(None, None)` when missing."""
        exact = self.runtime.get(key)
        if isinstance(exact, str) and exact:
            return exact, "exact"
        value, how = self._strip_match(key)
        if value is None and "\n" in key:
            value, how = self._block_match(key)
        if value is None and self.kinds.get(key, "?") == "event-text" \
                and len(key) >= 2 and key.startswith('"') and key.endswith('"'):
            value, how = self._quoted_match(key)
        if value is None and self.kinds.get(key, "?") == "note":
            value, how = self._note_match(key)
        return value, how


def cmd(work_dir: Annotated[str, cliutil.Argument(help="translation work dir")],
        dict_path: Annotated[str, cliutil.Argument(
            help="MTool/AI runtime translation JSON")],
        out: Annotated[str, cliutil.Option(
            "--out", help="output harvested translation JSON")] = "translated.json",
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    # Configure logging here, never at import time: a module-level call
    # rewrites the root logger for whatever imported this file (tests too)
    # and turns a later configuration into a silent no-op.
    cliutil.setup_logging(verbose, quiet, log_file)

    work = os.path.abspath(work_dir)
    with open(os.path.join(work, "template.json"), encoding="utf-8-sig") as fh:
        template = json.load(fh)
    with open(os.path.join(work, "kinds.json"), encoding="utf-8-sig") as fh:
        kinds = json.load(fh)
    with open(dict_path, encoding="utf-8") as fh:
        runtime = json.load(fh)
    log.info("template %d keys, dict %d entries", len(template), len(runtime))

    harvester = Harvester(runtime, kinds)

    translated = {}
    missing = {}
    stats = {"exact": 0, "strip": 0, "drop-name": 0, "fragment": 0,
             "quoted": 0, "note": 0, "miss": 0}
    for key in template:
        value, how = harvester.value_for(key)
        if value is None:
            missing[key] = ""
            stats["miss"] += 1
        else:
            translated[key] = value
            stats[how] += 1

    out_path = os.path.join(work, out)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(translated, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(work, "missing.json"), "w", encoding="utf-8") as fh:
        json.dump(missing, fh, ensure_ascii=False, indent=2)
    log.info("harvested %d / %d keys: %s", len(translated), len(template), stats)
    log.info("missing %d -> %s", len(missing),
             os.path.join(work, "missing.json"))
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="harvest_translation.py")


if __name__ == "__main__":
    raise SystemExit(main())
