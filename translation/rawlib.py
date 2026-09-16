#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rawlib.py - the raw translation library, rewrites, and the five hard gates.

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
``run_gates``        - the five hard gates; baking is refused unless all pass
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
           "read_jsonl", "read_jsonl_report", "append_jsonl", "apply_rewrites",
           "to_json", "run_gates", "gate_markdown", "code_problems",
           "line_problems", "structure_problems", "readable_text",
           "kana_problem", "validate_blocks",
           "append_batch", "leading_codes", "fix_leading_codes"]

#: ``@@@<id>@@@`` on a line of its own; the id may contain anything but ``@``.
HEADER_RE = re.compile(r"^@@@([^@\n]+?)@@@[ \t]*$")

LIBRARY_NAME = "translations.raw.txt"
GATE_ORDER = ("coverage", "control_codes", "kana", "line_breaks", "pending")


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


def read_jsonl_report(path):
    """Read JSONL tolerantly: ``(records, errors)`` instead of raising.

    State files are written by hand by the translator (``pending.jsonl`` is the
    one that keeps growing), and a single unescaped backslash used to crash the
    whole finishing chain - gates and status both - which is a silly way to lose
    a run.  A broken line is skipped here and reported as
    ``(line number, message)`` so the caller can turn it into a **failure**
    rather than a false pass: skipping quietly would hide an open question.
    """
    records, errors = [], []
    if not os.path.isfile(path):
        return records, errors
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError as error:
                errors.append((number, str(error)))
    return records, errors


def append_jsonl(path, record):
    """Append one object to a JSONL file (one line, UTF-8, LF)."""
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def safe_replace(text, old, new):
    """Replace ``old`` with ``new`` once, idempotently.

    When ``old`` occurs inside ``new`` (``杂鱼`` -> ``杂鱼剑``) a plain
    :meth:`str.replace` is *not* idempotent: re-applying the same rule to an
    already-updated value yields ``杂鱼剑剑``.  Occurrences already in the new
    form are protected with a sentinel character for the duration of the
    replacement, so a second run is a no-op.  Rules where ``new`` is a
    substring of ``old`` (``嫩穴摹本`` -> ``嫩穴``) stay plain replacements -
    there the already-converted text no longer matches ``old`` at all, so
    protecting it would silently block the conversion.
    """
    if old == new or old not in new:
        return text.replace(old, new)
    sentinel = "\x00"
    while sentinel in text or sentinel in new or sentinel in old:
        sentinel += "\x00"
    return (text.replace(new, sentinel).replace(old, new)
            .replace(sentinel, new))


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
        matched = 0
        for key in targets:
            text = values[key]
            if old not in text:
                continue
            matched += 1
            updated = safe_replace(text, old, new)
            if updated != text:
                values[key] = updated
                hits.append(key)
        if hits:
            write_library(library_path, values)
        applied.append({
            "old": old, "new": new, "reason": rule.get("reason") or "",
            "scope": "ids" if scope else "all",
            "affected": len(hits),
            "already_up_to_date": matched - len(hits),
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


def line_problems(source_text, target_text):
    """A value whose explicit line breaks differ from its source.

    MZ window text and DB descriptions use real ``\\n`` as *author* line
    breaks (one per window line, deliberate layout), so a value carrying fewer
    breaks is a silently truncated translation.  Neither the kana gate nor the
    control-code gate can see that - the missing line is simply gone, which is
    exactly how 42 skill descriptions lost their second line in a real run.
    """
    source_lines = source_text.count("\n")
    target_lines = target_text.count("\n")
    if source_lines == target_lines:
        return []
    return ["line breaks: source %d -> value %d" % (source_lines, target_lines)]


def _shape_of(payload):
    """Recursive signature: containers exact, string leaves type-only."""
    if isinstance(payload, dict):
        return ("dict", tuple(sorted(
            (key, _shape_of(value)) for key, value in payload.items())))
    if isinstance(payload, list):
        return ("list", tuple(_shape_of(item) for item in payload))
    if isinstance(payload, str):
        return ("str", _json_shape(payload))
    return ("scalar", payload)


def _json_shape(text):
    """Structural signature of `text` when it is JSON, else ``None``.

    Plugin command arguments are JSON held in *strings*, often nested twice:
    ``['{"label": "戦う", "switchId": "0"}']`` is a JSON list whose items are
    JSON objects serialised as strings.  A translation may rewrite the strings
    inside, but every list, object, key and number has to survive: a lost
    bracket makes the plugin's ``JSON.parse`` throw and the event stops right
    there (the player gets a choice window that never appears).

    String leaves are compared by *type only* - that is the part being
    translated - but a string leaf that is itself ``{...}``/``[...]`` is decoded
    and compared structurally too, so the nesting is checked as well.  Text
    that merely starts with a bracket without being JSON yields ``None`` (no
    check), which keeps ordinary dialogue out of this gate.
    """
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        return None
    return _shape_of(payload)


def structure_problems(source_text, target_text):
    """A JSON-valued parameter whose structure the translation broke.

    Only JSON *containers* are judged: when the source is not JSON there is
    nothing to protect, and a value that stopped parsing is reported once
    instead of as a long shape diff.
    """
    source_shape = _json_shape(source_text)
    if source_shape is None:
        return []
    target_shape = _json_shape(target_text)
    if target_shape is None:
        return ["JSON structure: value no longer parses as JSON"]
    if target_shape != source_shape:
        return ["JSON structure: shape differs from the source"]
    return []


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
        for message in structure_problems(entry["ja"], text):
            problems.append((key_id, message))
        for message in line_problems(entry["ja"], text):
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
            problems = structure_problems(entry["ja"], text)
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


def read_pending(work_dir):
    """Collapse ``pending.jsonl`` to the latest entry per key (last wins).

    Returns ``(latest, entries, errors)``.  ``pending.jsonl`` is append-only,
    so appending ``{"id": ..., "status": "resolved"}`` closes the earlier
    ``open`` entry for that id instead of requiring an edit.  Every consumer
    (the pending gate and ``status``) reads through this helper, so their
    counts cannot drift apart.
    """
    records, errors = read_jsonl_report(os.path.join(work_dir,
                                                     "pending.jsonl"))
    latest = OrderedDict()
    for item in records:
        key = (item.get("id") or item.get("question") or item.get("why")
               or json.dumps(item, ensure_ascii=False, sort_keys=True))
        latest[key] = item
    return latest, len(records), errors


def pending_open(latest):
    """Open questions among the collapsed pending records."""
    return [item for item in latest.values()
            if (item.get("status") or "open") not in CLOSED_STATUS]


def _gate_pending(work_dir):
    """Every open question must have a conclusion.

    See :func:`read_pending` for the last-wins collapse.  Lines that cannot be
    parsed fail the gate (they may hold an unreviewed question).
    """
    latest, entries, errors = read_pending(work_dir)
    open_items = pending_open(latest)
    return {
        "name": "pending",
        "ok": not open_items and not errors,
        "entries": entries,
        "open": len(open_items),
        "unparsable": len(errors),
        "detail": (["line %d: %s" % (number, message)
                    for number, message in errors[:5]]
                   + [item.get("id") or item.get("question")
                      for item in open_items][:50]),
    }


def _gate_lines(keys, values):
    """Every value keeps its source's explicit line breaks (no silent loss)."""
    mismatched = []
    for entry in keys:
        text = values.get(entry["id"])
        if not text:
            continue
        for message in line_problems(entry["ja"], text):
            mismatched.append({"id": entry["id"], "where": entry["where"],
                               "reason": message, "source": entry["ja"][:80],
                               "value": text[:80]})
    return {
        "name": "line_breaks",
        "ok": not mismatched,
        "checked": sum(1 for entry in keys if values.get(entry["id"])),
        "mismatched": len(mismatched),
        "detail": mismatched[:50],
    }


def run_gates(work_dir, out_path=None):
    """Run the hard gates.  Baking is refused unless all of them pass."""
    keys = mvkeys.load_keys(work_dir)
    values = read_library(os.path.join(work_dir, LIBRARY_NAME))
    items = _allowlist(work_dir)
    gates = [_gate_coverage(keys, values), _gate_codes(keys, values),
             _gate_kana(keys, values, items), _gate_lines(keys, values),
             _gate_pending(work_dir)]
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
        elif gate["name"] == "line_breaks":
            detail = "%d of %d values differ from the source line count" % (
                gate["mismatched"], gate["checked"])
        else:
            detail = "%d open of %d" % (gate["open"], gate["entries"])
            if gate.get("unparsable"):
                detail += ", %d unparsable" % gate["unparsable"]
        lines.append("| %s | %s | %s |"
                     % (gate["name"], "PASS" if gate["ok"] else "**FAIL**",
                        detail))
    lines.append("")
    return "\n".join(lines)
