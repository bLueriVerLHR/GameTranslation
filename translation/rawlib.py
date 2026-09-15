#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rawlib.py - the raw translation library, rewrites, and the four hard gates.

The translation subagent never touches JSON: it appends *raw* text to one file
(design: `.tmp/TRANSLATION_WORKFLOW_V2.md`).  Escaping happens here and only
here, in :func:`to_json` - a JSON encoder already knows how to escape real
newlines and backslashes, so the subagent never has to.

Library format (append-only, one file, zero escaping)::

    @@@data/Map003.json#events[2].pages[0].list[7].parameters[0]@@@
    raw translation, real newlines, control codes copied literally
    @@@<next id>@@@
    ...

Everything between a header line and the next header line is the value - no
quoting, no continuation markers, no line-count contract.  The only rule is
that no value may contain a line starting with ``@@@`` (guaranteed by the
extractor: no extracted source string starts that way).

Operations:

``read_library`` / ``write_library`` / ``append_block``  - IO (last wins per id)
``apply_rewrites``   - execute the subagent's decided rewrites (old -> new)
``to_json``          - raw library + keys.jsonl -> translated.json (escaping)
``run_gates``        - the four hard gates; baking is refused unless all pass
"""
import io
import json
import os
import re
from collections import OrderedDict

from . import mvkeys
from .codes import (KANA_RE, has_text_parameter, parameter_of, parse_codes,
                    parse_code_sequence, split_keep_codes)

__all__ = ["HEADER_RE", "read_library", "write_library", "append_block",
           "read_jsonl", "append_jsonl", "apply_rewrites", "to_json",
           "run_gates", "gate_markdown", "code_problems", "readable_text",
           "kana_problem", "validate_blocks", "append_batch", "leading_codes",
           "fix_leading_codes"]

#: ``@@@<id>@@@`` on a line of its own; the id may contain anything but ``@``.
HEADER_RE = re.compile(r"^@@@([^@\n]+?)@@@[ \t]*$")

LIBRARY_NAME = "translations.raw.txt"
GATE_ORDER = ("coverage", "control_codes", "kana", "pending")


def read_library(path):
    """Parse the library into ``OrderedDict(id -> text)``; later blocks win."""
    values = OrderedDict()
    current = None
    chunks = []
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            bare = line.rstrip("\n").rstrip("\r")
            match = HEADER_RE.match(bare)
            if match:
                if current is not None:
                    values[current] = "\n".join(chunks).strip("\n")
                current = match.group(1)
                chunks = []
                continue
            if current is not None:
                chunks.append(bare)
            elif bare.strip() and not bare.lstrip().startswith("#"):
                # Before the first header only blank lines and ``#`` notes are
                # tolerated; anything else means the file is not a library (a
                # value silently swallowed here would be lost work).
                raise ValueError("%s:%d: text before the first @@@id@@@ header"
                                 % (path, number))
    if current is not None:
        values[current] = "\n".join(chunks).strip("\n")
    return values


def write_library(path, values):
    """Rewrite the whole library from ``{id: text}`` (used after rewrites)."""
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        for key, text in values.items():
            handle.write("@@@%s@@@\n%s\n" % (key, text))
    return path


def append_block(path, key_id, text):
    """Append one translated block (the subagent's only write operation)."""
    if "@@@" in key_id:
        raise ValueError("id must not contain '@@@': %r" % key_id)
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write("@@@%s@@@\n%s\n" % (key_id, text))
    return path


def read_jsonl(path):
    """Read a JSONL file as a list of objects (missing file -> [])."""
    if not os.path.isfile(path):
        return []
    out = []
    with io.open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as error:
                raise ValueError("%s:%d: bad JSON line (%s)"
                                 % (path, number, error))
    return out


def append_jsonl(path, record):
    """Append one object to a JSONL file (one line, UTF-8, LF)."""
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def apply_rewrites(work_dir, report_path=None):
    """Apply ``rewrites.jsonl`` to the library; report every affected key.

    A rewrite is ``{"old": ..., "new": ..., "reason": ..., "ids": [...]?}``:
    with ``ids`` the substitution is limited to those keys, without it every
    value containing ``old`` is updated (the whole-library case).  The library
    is rewritten in place and the impact report is returned, so the change is
    auditable long after the subagent's reasoning is gone.
    """
    library_path = os.path.join(work_dir, LIBRARY_NAME)
    values = read_library(library_path)
    rewrites = read_jsonl(os.path.join(work_dir, "rewrites.jsonl"))
    applied = []
    for index, rule in enumerate(rewrites):
        old, new = rule.get("old"), rule.get("new")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ValueError("rewrites.jsonl[%d]: needs non-empty 'old'/'new'"
                             % index)
        scope = rule.get("ids")
        targets = [k for k in (scope or values) if k in values]
        hits = []
        for key in targets:
            text = values[key]
            if old in text:
                values[key] = text.replace(old, new)
                hits.append(key)
        if hits:
            write_library(library_path, values)
        applied.append({
            "old": old, "new": new, "reason": rule.get("reason") or "",
            "scope": "ids" if scope else "all",
            "affected": len(hits),
            "ids": hits[:50],
        })
    report = {"rules": len(rewrites), "changed_keys":
              len({k for entry in applied for k in entry["ids"]}),
              "applied": applied}
    out = report_path or os.path.join(work_dir, "rewrite_report.json")
    with io.open(out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return report


def to_json(work_dir, out_path=None):
    """Turn the raw library into JSON - the one place escaping happens.

    Writes ``translated.json`` (``{source text: translation}``, the shape a
    bake step consumes) and ``translated_ids.json`` (``{id: translation}``,
    full fidelity for the gates).  Conflicting translations of the same source
    string are reported, not hidden.
    """
    keys = mvkeys.load_keys(work_dir)
    values = read_library(os.path.join(work_dir, LIBRARY_NAME))
    by_id = OrderedDict()
    by_text = OrderedDict()
    conflicts = []
    for entry in keys:
        text = values.get(entry["id"])
        if text is None or not text.strip():
            continue
        by_id[entry["id"]] = text
        source = entry["ja"]
        if source in by_text and by_text[source] != text:
            conflicts.append({"ja": source, "kept": by_text[source],
                              "other": text, "id": entry["id"]})
            continue
        by_text[source] = text
    out_dir = os.path.dirname(out_path) if out_path else work_dir
    json_path = out_path or os.path.join(work_dir, "translated.json")
    ids_path = os.path.join(out_dir, "translated_ids.json")
    for path, payload in ((json_path, by_text), (ids_path, by_id)):
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    report = {"keys": len(keys), "translated": len(by_id),
              "unique_sources": len(by_text), "conflicts": conflicts[:50],
              "translated_json": json_path, "translated_ids": ids_path}
    with io.open(os.path.join(work_dir, "to_json_report.json"), "w",
                 encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return report


def _allowlist(work_dir):
    path = os.path.join(work_dir, "allow_kana.json")
    if not os.path.isfile(path):
        return []
    with io.open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    items = data.get("items") if isinstance(data, dict) else data
    return [item for item in (items or []) if isinstance(item, dict)
            and item.get("match")]


def _kana_allowed(text, items):
    for item in items:
        match = item["match"]
        if match.startswith("re:"):
            if re.search(match[3:], text):
                return item
        elif match in text:
            return item
    return None


def code_problems(source_text, target_text):
    """Differences between two control-code sequences, as messages.

    Codes are compared one by one; the only tolerated difference is inside a
    *textual* parameter - a name box (``\\nc<チンピラ>``) shows a name to the
    player, so it must be translated, while a numeric argument (``\\px[200]``)
    must survive byte for byte.  The bracket shape is checked either way.
    """
    source = parse_code_sequence(source_text)
    target = parse_code_sequence(target_text)
    if [key for key, _ in source] != [key for key, _ in target]:
        return ["code sequence: %s -> %s"
                % ([tok for _, tok in source], [tok for _, tok in target])]
    problems = []
    for (_, source_token), (_, target_token) in zip(source, target):
        if source_token == target_token:
            continue
        if has_text_parameter(source_token) \
                and parameter_of(target_token) is not None:
            continue
        problems.append("code parameter: %s -> %s"
                        % (source_token, target_token))
    return problems


def leading_codes(text):
    """The control-code prefix of `text` (the codes before any visible text)."""
    out = []
    for is_code, piece in split_keep_codes(text):
        if is_code:
            out.append(piece)
        elif piece:
            break
    return "".join(out)


def fix_leading_codes(source, target):
    """Prepend the source's leading codes when the translation omitted them.

    A continuation line repeats the source's leading codes (``\\px[200]``, a run
    of ``\\{`` size switches), and forgetting one is the most common mechanical
    slip of a long run - it says nothing about the translation, so the tool
    fixes it instead of the translator.

    Two cases are deliberately left alone: a translation that already starts
    with *some* code (only validation may judge whether it is the right one),
    and a prefix whose parameter carries **text** - a name box must be
    translated, and copying the source's Japanese name back would be worse than
    the missing code it was meant to fix.
    """
    prefix = leading_codes(source)
    if not prefix or leading_codes(target):
        return target
    if any(has_text_parameter(token) for token in parse_codes(prefix)):
        return target
    return prefix + target


def readable_text(text):
    """What a player actually reads: text between codes + text parameters."""
    parts = [piece for is_code, piece in split_keep_codes(text) if not is_code]
    parts += [parameter_of(token) for token in parse_codes(text)
              if has_text_parameter(token)]
    return "\n".join(piece for piece in parts if piece)


def kana_problem(text, items):
    """Kana left in the readable part of `text`, unless the allowlist covers it."""
    visible = readable_text(text)
    if not KANA_RE.search(visible):
        return None, None
    item = _kana_allowed(visible, items)
    if item:
        return None, item
    return visible, None


def validate_blocks(work_dir, values):
    """Check a batch of translations against the key list before writing it.

    Returns ``[(id, problem), ...]`` - empty means the batch is clean.  Used by
    ``append_batch`` so a bad batch is rejected *before* it reaches the library
    (the library is append-only; a half-written batch is hard to unwind).
    """
    keys = {entry["id"]: entry for entry in mvkeys.load_keys(work_dir)}
    items = _allowlist(work_dir)
    problems = []
    for key_id, text in values.items():
        entry = keys.get(key_id)
        if entry is None:
            problems.append((key_id, "unknown id (not in keys.jsonl)"))
            continue
        if not text.strip():
            problems.append((key_id, "empty translation"))
            continue
        for message in code_problems(entry["ja"], text):
            problems.append((key_id, message))
        residue, _allowed = kana_problem(text, items)
        if residue:
            problems.append((key_id, "kana residue: %s" % residue[:40]))
    return problems


def append_batch(work_dir, batch_path, note=None, fix_leading=False):
    """Validate a batch file and append it to the library (all or nothing).

    The batch file has the library format (``@@@id@@@`` + raw translation), so
    a batch is just a fragment of the library.  Nothing is written when any
    block fails validation: the caller gets every problem and the library stays
    exactly as it was.  With ``fix_leading`` a missing leading control code is
    restored from the source first (see ``fix_leading_codes``).
    """
    values = read_library(batch_path)
    if not values:
        return {"added": 0, "fixed": 0,
                "problems": [("", "batch file is empty")]}
    keys = {entry["id"]: entry for entry in mvkeys.load_keys(work_dir)}
    fixed = 0
    if fix_leading:
        for key_id, text in list(values.items()):
            entry = keys.get(key_id)
            if entry is None:
                continue
            restored = fix_leading_codes(entry["ja"], text)
            if restored != text:
                values[key_id] = restored
                fixed += 1
    problems = validate_blocks(work_dir, values)
    if problems:
        return {"added": 0, "fixed": fixed, "problems": problems}
    library = os.path.join(work_dir, LIBRARY_NAME)
    with io.open(library, "a", encoding="utf-8", newline="\n") as handle:
        for key_id, text in values.items():
            handle.write("@@@%s@@@\n%s\n" % (key_id, text))
    if note:
        append_jsonl(os.path.join(work_dir, "progress.jsonl"),
                     {"note": note, "added": len(values),
                      "fixed_leading": fixed,
                      "ids": [key for key in list(values)[:3]]})
    return {"added": len(values), "fixed": fixed, "problems": []}


def _gate_coverage(keys, values):
    missing = [entry["id"] for entry in keys
               if not (values.get(entry["id"]) or "").strip()]
    return {
        "name": "coverage",
        "ok": not missing,
        "total": len(keys),
        "missing": len(missing),
        "detail": missing[:50],
    }


def _gate_codes(keys, values):
    """The code sequence of a translation must match its source."""
    mismatch, translated_parameters = [], 0
    for entry in keys:
        text = values.get(entry["id"])
        if not text:
            continue
        problems = code_problems(entry["ja"], text)
        if not problems:
            if any(source_token != target_token for (_, source_token),
                   (_, target_token)
                   in zip(parse_code_sequence(entry["ja"]),
                          parse_code_sequence(text))):
                translated_parameters += 1
            continue
        mismatch.append({"id": entry["id"], "where": entry["where"],
                         "reason": problems[0].split(":")[0],
                         "problems": problems,
                         "source": [tok for _, tok in
                                    parse_code_sequence(entry["ja"])],
                         "target": [tok for _, tok in
                                    parse_code_sequence(text)]})
    return {
        "name": "control_codes",
        "ok": not mismatch,
        "checked": sum(1 for entry in keys if values.get(entry["id"])),
        "mismatched": len(mismatch),
        "translated_parameters": translated_parameters,
        "detail": mismatch[:50],
    }


def _gate_kana(keys, values, items):
    """Kana left in the readable parts of a translation.

    Readable parts are the text between codes **plus** any textual code
    parameter (a name box shows its parameter to the player).  Numeric code
    arguments and the code itself are never read as prose.
    """
    allowed, residue = [], []
    for entry in keys:
        text = values.get(entry["id"])
        if not text:
            continue
        visible, item = kana_problem(text, items)
        if item:
            allowed.append({"id": entry["id"], "match": item["match"],
                            "reason": item.get("reason") or ""})
        elif visible:
            residue.append({"id": entry["id"], "where": entry["where"],
                            "text": visible})
    return {
        "name": "kana",
        "ok": not residue,
        "allowed": len(allowed),
        "residue": len(residue),
        "detail": residue[:50],
    }


#: Statuses that count as closed for the pending gate.
CLOSED_STATUS = ("resolved", "decided", "wontfix")


def _gate_pending(work_dir):
    """Every open question must have a conclusion.

    pending.jsonl is append-only like the library, so the *last* entry for an
    id wins: appending ``{"id": ..., "status": "resolved"}`` closes the
    earlier ``open`` entry for that id instead of requiring an edit.
    """
    entries = read_jsonl(os.path.join(work_dir, "pending.jsonl"))
    latest = OrderedDict()
    for item in entries:
        key = (item.get("id") or item.get("question") or item.get("why")
               or json.dumps(item, ensure_ascii=False, sort_keys=True))
        latest[key] = item
    open_items = [item for item in latest.values()
                  if (item.get("status") or "open") not in CLOSED_STATUS]
    return {
        "name": "pending",
        "ok": not open_items,
        "entries": len(entries),
        "open": len(open_items),
        "detail": [item.get("id") or item.get("question") for item in
                   open_items][:50],
    }


def run_gates(work_dir, out_path=None):
    """Run the four hard gates.  Baking is refused unless all of them pass."""
    keys = mvkeys.load_keys(work_dir)
    values = read_library(os.path.join(work_dir, LIBRARY_NAME))
    items = _allowlist(work_dir)
    gates = [_gate_coverage(keys, values), _gate_codes(keys, values),
             _gate_kana(keys, values, items), _gate_pending(work_dir)]
    report = {
        "ok": all(gate["ok"] for gate in gates),
        "keys": len(keys),
        "translated": sum(1 for entry in keys if values.get(entry["id"])),
        "gates": gates,
    }
    path = out_path or os.path.join(work_dir, "gate_report.json")
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return report


def gate_markdown(report):
    """Human summary of a gate report (also what gets shown to the owner)."""
    lines = ["# Gate report", "",
             "**%s** - %d/%d keys translated" % (
                 "ALL PASS" if report["ok"] else "FAILED",
                 report["translated"], report["keys"]), "",
             "| gate | result | detail |", "|---|---|---|"]
    for gate in report["gates"]:
        if gate["name"] == "coverage":
            detail = "%d missing" % gate["missing"]
        elif gate["name"] == "control_codes":
            detail = "%d of %d mismatched" % (gate["mismatched"],
                                              gate["checked"])
        elif gate["name"] == "kana":
            detail = "%d residue, %d allowlisted" % (gate["residue"],
                                                     gate["allowed"])
        else:
            detail = "%d open of %d" % (gate["open"], gate["entries"])
        lines.append("| %s | %s | %s |"
                     % (gate["name"], "PASS" if gate["ok"] else "**FAIL**",
                        detail))
    lines.append("")
    return "\n".join(lines)
