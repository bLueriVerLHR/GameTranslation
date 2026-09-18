#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codes.py - control codes for RPG Maker text: parsing + derived inventory.

Two jobs, both mechanical (no language judgement):

``parse_codes(text)``
    Split a string into its control-code tokens, in order.  ``\\c[1]`` /
    ``\\px[200]`` / ``\\nc<name>`` / ``\\{`` / ``\\.`` are one token each.  The
    bake gate uses this to require that a translation carries *exactly* the
    code sequence of its source (same tokens, same order, same parameters) -
    text is free, codes are not.

``inventory(game_dir, counts)``
    Derive the code table from the game instead of hard-coding one: scan
    ``js/**/*.js`` for dispatch sites (``case 'X':`` - the engine's own
    ``processEscapeCharacter`` plus every plugin that extends it) and for
    plugin comment lines that document a code.  Merge that with the frequency
    counts observed in the game's data, and write ``control_codes.md``.

Why derived: the built-in dispatcher of a modern MV game only handles a few
codes (``C``/``I``/``{``/``}``); everything else comes from plugins whose codes
differ per game.  A hard-coded table would silently mis-describe them.
"""
import os
import re
from collections import Counter, defaultdict

__all__ = ["CODE_RE", "DISPATCH_RE", "KANA_RE", "KANA_LETTERS_RE", "CJK_RE",
           "TEXT_KEY_RE",
           "parse_codes", "code_key", "parse_code_sequence",
           "split_keep_codes", "parameter_of", "has_text_parameter",
           "scan_js", "inventory",
           "write_markdown"]

#: A **runtime text-table key** (``\T[id]``).  It is not an RPG Maker escape
#: code: some repacks replace every display string with a key and resolve it at
#: runtime - either MTool's "mount translation" mode (its own dictionary) or the
#: game's own multilingual plugin, which reads ``csv/UI.csv`` through Node's
#: ``fs``.  Neither runtime exists in a JoiPlay/browser build, so a key left in
#: display text is drawn verbatim (a title menu literally reading
#: ``\T[SIS1036]``).  ``tools/resolve_text_keys.py`` inlines them at build time,
#: ``tools/qc_build_kana.py`` fails the build when one survives.
#:
#: ``group(1)`` is the run of backslashes in front of the key: a key inside a
#: nested JSON parameter carries one escaping level per JSON.parse between the
#: file and the string the plugin renders (``\T[id]`` at the top level,
#: ``\\T[id]`` inside one JSON layer, ``\\\\T[id]`` inside two - a QuestSystem
#: ``QuestDatas`` blob does this).  Inlining must consume the **whole** run and
#: re-escape the text for ``len(run) // 2`` levels, or the nested JSON stops
#: parsing (``"Title":"\\药草采集"``: invalid escape) and the game dies with
#: ``SyntaxError: ... is not valid JSON`` at boot.
TEXT_KEY_RE = re.compile(r"(?<!\\)(\\+)(T\[([^\]\\]+)\])")

#: One control-code token: ``\name<...>`` / ``\name[...]`` / single-char form.
CODE_RE = re.compile(r"\\[A-Za-z]+(?:<[^<>]*>|\[[^\[\]]*\])?|\\[{}.|^!$~]")

#: A dispatcher arm in engine/plugin JS: ``case 'PX':`` / ``case '{':``.
DISPATCH_RE = re.compile(r"case\s+'([^']{1,3})'\s*:")

#: Kana (hiragana + katakana, including the prolonged-sound mark) **and the
#: halfwidth katakana letters**.  Halfwidth katakana matters: a line written
#: only in halfwidth (`ﾌﾞﾂﾌﾞﾂ……`) is still Japanese text, and without the class
#: it looks like "no kana" and is dropped as non-text (a real build lost those
#: lines that way).  The halfwidth punctuation (`｡｢｣､･`) and the halfwidth
#: prolonged-sound mark (`ｰ`, used as a dash decoration in the Chinese text)
#: are deliberately excluded.
KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff66-\uff6f\uff71-\uff9d]")

#: Kana **letters only** - the class for "is this string still Japanese?":
#: the kana-block punctuation and the voicing marks are excluded because
#: translated Chinese legitimately keeps them.  A moan line like ``「あ゛っ！``
#: becomes ``「啊゛！`` - the voice mark ``゛`` (U+309B) is part of the Chinese
#: text, the middle dot ``・`` (U+30FB) is used in Chinese lists, and
#: ``ー``/``〜`` are dashes; treating those as residue rejected 534 *translated*
#: values of one real MV harvest (873 hits on ``゛`` alone) and forced them
#: through the ``allow_kana.json`` allowlist for nothing.  Any real Japanese
#: sentence still contains a kana letter, so the gate keeps its teeth.
#: Same as ``tools/japanese_utils.py:KANA`` except for the halfwidth voicing
#: mark ``ﾞ`` (U+FF9E) - a mark, not a letter (that class keeps it because a
#: halfwidth-only line ``ﾌﾞﾂ`` is Japanese either way; there the letters decide).
#: ``KANA_RE`` stays the coarser block-range test (it decides "is this text
#: at all?" for code parameters and key candidates, where being permissive is
#: the safe direction).  tests/test_kana_ranges.py pins all of this.
KANA_LETTERS_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9d]")

#: Han characters (used to spot kanji-only UI labels such as "攻撃").
CJK_RE = re.compile(r"[\u3005\u3006\u3400-\u4dbf\u4e00-\u9fff]")

_SINGLE = "{}.|^!$~"


def parse_codes(text):
    """The control-code tokens of `text`, in order (parameters included)."""
    return CODE_RE.findall(text or "")


def code_key(token):
    """Dispatch key of a token: ``\\px[200]`` -> ``PX``, ``\\c[1]`` -> ``C``.

    Single-character escapes keep their literal character (``\\{`` -> ``{``).
    """
    body = token[1:] if token.startswith("\\") else token
    if body[:1] in _SINGLE:
        return body
    match = re.match(r"([A-Za-z]+)", body)
    return match.group(1).upper() if match else body


def parse_code_sequence(text):
    """``[(key, token), ...]`` - what the bake gate compares."""
    return [(code_key(tok), tok) for tok in parse_codes(text)]


def split_keep_codes(text):
    """``[(is_code, piece), ...]`` - the string split, codes kept as pieces.

    ``re.split`` drops its separators, so the pattern is wrapped in a capturing
    group here: a caller that rewrites the text segments (normalising, or
    masking) must not lose or alter a control code by accident.
    """
    if not text:
        return []
    parts = re.split("(%s)" % CODE_RE.pattern, text)
    return [(bool(index % 2), piece) for index, piece in enumerate(parts)]


def parameter_of(token):
    """The bracketed part of a token (``\\nc<name>`` -> ``name``), else None.

    Two parameter shapes mean two different things, and the gates must not
    confuse them:

    * a **numeric** parameter (``\\px[200]``, ``\\N[1]``, ``\\C[3]``) is an
      instruction argument - it must be reproduced byte for byte.
    * a **textual** parameter (``\\nc<チンピラ>``, a YEP name box) is displayed
      text: it is the name the player reads, so it must be translated.  A gate
      that demanded the whole token be identical would forbid translating it
      and leave Japanese names on screen.
    """
    for opener, closer in (("<", ">"), ("[", "]")):
        if token.endswith(closer) and opener in token:
            return token[token.index(opener) + 1:-1]
    return None


def has_text_parameter(token):
    """Does this code's parameter carry display text (kana or Han)?"""
    parameter = parameter_of(token)
    if parameter is None:
        return False
    return bool(KANA_RE.search(parameter) or CJK_RE.search(parameter))


def _js_files(game_dir):
    js_root = os.path.join(game_dir, "js")
    for root, dirs, files in os.walk(js_root):
        dirs[:] = [d for d in dirs if d not in ("libs", "node_modules")]
        for name in sorted(files):
            if name.endswith(".js"):
                yield os.path.join(root, name)


def scan_js(game_dir):
    """Dispatch sites and documentation snippets found in the game's JS.

    Returns ``{key: {"sites": ["js/rpg_windows.js:1234"], "docs": [...]}}``.
    A "doc" is a comment line that mentions the code (plugins document their
    codes in the header help block, which is where the author explains the
    parameter meaning).
    """
    found = defaultdict(lambda: {"sites": [], "docs": []})
    for path in _js_files(game_dir):
        rel = os.path.relpath(path, game_dir).replace(os.sep, "/")
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                for key in DISPATCH_RE.findall(line):
                    entry = found[key.upper()]
                    site = "%s:%d" % (rel, number)
                    if len(entry["sites"]) < 4:
                        entry["sites"].append(site)
                stripped = line.strip()
                if not (stripped.startswith("*") or stripped.startswith("//")):
                    continue
                for match in re.finditer(r"\\([A-Za-z]{1,4})", line):
                    key = match.group(1).upper()
                    doc = stripped.lstrip("*/ ").strip()
                    docs = found[key]["docs"]
                    if doc and doc not in docs and len(docs) < 2:
                        docs.append(doc)
    for key in found:
        found[key]["sites"] = sorted(set(found[key]["sites"]))
    return dict(found)


def inventory(game_dir, counts):
    """Merge observed code frequencies with the JS-derived dispatch table.

    `counts` is ``{token: frequency}`` (or ``{key: frequency}``); keys are
    normalised either way.
    """
    js = scan_js(game_dir)
    merged = {}
    for token_or_key, count in (counts or {}).items():
        key = code_key(token_or_key) if token_or_key.startswith("\\") \
            else token_or_key
        entry = merged.setdefault(key, {"count": 0, "tokens": Counter()})
        entry["count"] += int(count)
        entry["tokens"][token_or_key] += int(count)
    for key in js:
        merged.setdefault(key, {"count": 0, "tokens": Counter()})
    for key, entry in merged.items():
        info = js.get(key, {"sites": [], "docs": []})
        entry["sites"] = info["sites"]
        entry["docs"] = info["docs"]
        entry["documented"] = bool(info["sites"] or info["docs"])
    return merged


def _sample_tokens(entry, limit=3):
    return ", ".join("`%s`" % tok for tok, _ in entry["tokens"].most_common(limit))


def _clip(text, limit=120):
    """Trim a JS comment line: the table is read into a prompt, not archived."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def write_markdown(path, merged, total_keys=0):
    """Write the control-code table the subagent reads before translating."""
    rows = sorted(merged.items(),
                  key=lambda kv: (-kv[1]["count"], kv[0]))
    lines = [
        "# Control codes (derived from this game, not hard-coded)",
        "",
        "Every code below is meant to be copied **verbatim, unchanged, in the",
        "same order** into the translation.  Translate the text between codes;",
        "never translate, drop, reorder or retype a code.",
        "",
        "`documented` = a dispatch site or a comment line for this code was",
        "found in the game's own JS, so the meaning is the author's own words.",
        "",
        "| code | in data | sample | documented | meaning / source |",
        "|---|---|---|---|---|",
    ]
    for key, entry in rows:
        sample = _sample_tokens(entry) or ""
        sites = " ".join("`%s`" % site for site in entry["sites"][:2])
        docs = _clip(" / ".join(entry["docs"][:1]))
        meaning = " ".join(x for x in (sites, docs) if x) or "_(not found)_"
        lines.append("| `\\%s` | %d | %s | %s | %s |"
                     % (key, entry["count"], sample,
                        "yes" if entry.get("documented") else "**no**",
                        meaning.replace("|", "/")))
    unknown = [k for k, e in merged.items() if e["count"] and
               not e.get("documented")]
    lines += [
        "",
        "## Notes for the translator",
        "",
        "* A code counted above but marked `**no**` has no dispatch site and no",
        "  comment in the game's JS - treat it as opaque: copy it verbatim and",
        "  leave its parameters untouched.",
        "* Names and variables inside codes (`\\nc<name>`, `\\N[1]`, `\\V[12]`)",
        "  are **references**, not text: they resolve at runtime to a name from",
        "  the game's database or to a variable's value.  Do not translate the",
        "  reference itself; translate the name in the database entry (that key",
        "  is in `keys.jsonl` too, kind `db`).",
        "* Codes that only change presentation (size, colour, position, waits,",
        "  icons, sound) must be reproduced exactly, including their arguments.",
        "",
    ]
    if total_keys:
        lines.append("(inventory covers %d extracted keys)" % total_keys)
        lines.append("")
    if unknown:
        lines.append("Undocumented codes seen in data: %s"
                     % ", ".join("`\\%s`" % k for k in sorted(unknown)))
        lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path
