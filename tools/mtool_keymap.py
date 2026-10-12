#!/usr/bin/env python3
"""mtool_keymap.py - rebuild a Wolf RPG runtime dictionary (MTool format) from
better translations, with the game's own text as context.

Why this exists
---------------
A Wolf RPG game whose only translation is a machine-translated runtime
dictionary has two problems that cannot be fixed by editing that dictionary:
the keys are *runtime fragments* (one message window each) with no context,
and only part of the game was ever captured.  Rewriting it well needs, per
key, the **whole static field the fragment came from** (scene, neighbours,
terminology) - that field lives in the rewolf-trans patch tree.

What this tool does
-------------------
``build``   map every MTool key onto the rewolf patch tree (which field
            contains it, at which offsets, in which map/event) and write the
            keymap plus one record per host field.
``slice``   emit translation batches: one unit = one host field, listing the
            fragments that must come back translated.
``apply``   merge a translated batch into the work dir.  All-or-nothing: a
            single bad fragment (control code, newline count, kana residue)
            rejects the whole batch, so the stored state is never half good.
``gates``   coverage / control codes / newline parity / kana residue /
            conflicts - the five hard gates, exit non-zero when not green.
``export``  write the runtime dictionary (same key strings as the original),
            ready to drop next to the game executable.

The original dictionary's values are used for nothing but the key list: no
machine translation is ever copied forward.
"""
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Annotated

from rpgmaker import cliutil, io_boundary
from translation.codes import KANA_LETTERS_RE

__all__ = [
    "build_keymap", "parse_patch_text", "validate_fragment",
    "collect_codes", "scan_containers", "key_id",
]

WS_RE = re.compile(r"[\s\u3000]+")
#: Wolf control codes as they appear in the patch text.  In the data they are
#: stored doubled (``\\s[9]``); the patch keeps that doubling, so a token is a
#: run of backslashes plus the name and its bracketed parameter.
# runtime keys have no hosting field, so a batch chunks them into units this size
_RUNTIME_UNIT = 25
CODE_RE = re.compile(r"\\+[A-Za-z]+(?:<[^<>]{0,60}>|\[[^\[\]]{0,60}\])?")

BEGIN = "> BEGIN STRING"
END = "> END STRING"
CTX = "> CONTEXT"

#: Resource-looking values (``Picture/あ.png``) legitimately keep kana in the
#: file name; a Chinese sentence does not.  Deliberately narrow: an extension
#: is required, and whitespace or quotes disqualify the value, because `\w`
#: alone would match Japanese and turn the whole gate off.
RESOURCE_LIKE_RE = re.compile(r"^[^\s\u3000「『]+\.[A-Za-z0-9]{2,5}$")


def key_id(key: str) -> str:
    """Stable id of a dictionary key (the key string is the identity)."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def collect_codes(text: str) -> Counter:
    """Control-code tokens of `text` as a multiset."""
    return Counter(CODE_RE.findall(text or ""))


def validate_fragment(ja: str, zh: str) -> list[str]:
    """Problems that make a fragment unusable (empty list = acceptable)."""
    problems: list[str] = []
    if not zh or not zh.strip():
        problems.append("empty")
        return problems
    if collect_codes(ja) != collect_codes(zh):
        problems.append(f"control codes differ: {dict(collect_codes(ja))} -> {dict(collect_codes(zh))}")
    if (ja or "").count("\n") != (zh or "").count("\n"):
        problems.append(f"newline count {(ja or '').count(chr(10))} -> {(zh or '').count(chr(10))}")
    residue = KANA_LETTERS_RE.findall(zh or "")
    if residue and not RESOURCE_LIKE_RE.match((zh or "").strip()):
        problems.append("kana residue: {}".format("".join(sorted(set(residue)))))
    return problems


def bucket_of(ctx: str) -> str:
    """Coarse origin of a patch entry: DB / COMMONEVENT / MPS / OTHER."""
    if ctx.startswith("[NEW] DB:") or "/DB:" in ctx:
        return "DB"
    if "[NEW] COMMONEVENT:" in ctx:
        return "COMMONEVENT"
    if "[NEW] MPS:" in ctx:
        return "MPS"
    return "OTHER"


def scene_of(ctx: str) -> str:
    """Map / common-event id the entry belongs to (its scene)."""
    match = re.search(r"(?:MPS:|COMMONEVENT:)([^\s/]+)", ctx)
    return match.group(1) if match else ""


def parse_patch_text(text: str):
    """Yield ``(source, context)`` for every entry in one patch file.

    The patch format is ``BEGIN STRING / source lines / CONTEXT / translated
    lines / END STRING``: only the lines *before* the first CONTEXT are the
    source.  Keeping the split explicit matters because the slot after CONTEXT
    is where a translation already lives - reading it as source would make a
    translated tree look like it changed its own keys.
    """
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].startswith(BEGIN):
            index += 1
            source: list[str] = []
            ctx = ""
            seen_context = False
            while index < len(lines) and not lines[index].startswith(END):
                line = lines[index]
                if line.startswith(CTX):
                    ctx = line[len(CTX):].strip()
                    seen_context = True
                elif not line.startswith(">") and not seen_context:
                    source.append(line)
                index += 1
            yield "\n".join(source), ctx
        index += 1


def scan_containers(patch_dir: Path) -> list[dict]:
    """Every translatable static field of a rewolf patch tree."""
    containers: list[dict] = []
    for path in sorted(patch_dir.rglob("*.txt")):
        name = path.name
        if name.endswith("_Context.txt"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        risky = "_Danger" in name or "_Extra" in name
        for source, ctx in parse_patch_text(text):
            if not source.strip():
                continue
            containers.append({
                "container_id": len(containers),
                "file": path.name,
                "bucket": bucket_of(ctx),
                "scene": scene_of(ctx),
                "ctx": ctx,
                "risky_file": risky,
                "source": source,
            })
    return containers


def _trie_add(trie: dict, key: str) -> None:
    node = trie
    for char in WS_RE.sub("", key):
        node = node.setdefault(char, {})
    node["\x00"] = True


def build_keymap(mtool: dict, containers: list[dict]) -> dict:
    """Map every kana-bearing dictionary key onto its host field(s)."""
    keys = [k for k in mtool if KANA_LETTERS_RE.search(k) and len(k) >= 2]
    trie: dict = {}
    for key in keys:
        _trie_add(trie, key)

    spans: dict[int, list[tuple[int, int]]] = defaultdict(list)
    bounds: list[tuple[set, set]] = []
    for container in containers:
        source = container["source"]
        compact: list[str] = []
        starts: set[int] = set()
        ends: set[int] = set()
        position = 0
        for line in source.split("\n"):
            starts.add(position)
            for char in line:
                if not char.isspace():
                    compact.append(char)
                    position += 1
            ends.add(position)
        bounds.append((starts, ends))
        text = "".join(compact)
        index = 0
        size = len(text)
        while index < size:
            node = trie
            cursor = index
            while cursor < size:
                node = node.get(text[cursor])
                if node is None:
                    break
                cursor += 1
                if "\x00" in node:
                    spans[container["container_id"]].append((index, cursor))
            index += 1

    compact_keys: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        compact_keys[WS_RE.sub("", key)].append(key)

    records: dict[str, dict] = {}
    fragments_by_container: dict[int, list[dict]] = defaultdict(list)
    for container_id, found in spans.items():
        for start, end in found:
            text = WS_RE.sub("", containers[container_id]["source"])
            for key in compact_keys[text[start:end]]:
                starts, ends = bounds[container_id]
                record = {
                    "key": key,
                    "key_id": key_id(key),
                    "container": container_id,
                    "start": start,
                    "end": end,
                    "line_aligned": start in starts and end in ends,
                }
                fragments_by_container[container_id].append(
                    dict(record, ja=key))
                if key not in records:
                    records[key] = record

    for fragments in fragments_by_container.values():
        fragments.sort(key=lambda item: item["start"])
        for order, fragment in enumerate(fragments):
            fragment["index_in_field"] = order

    keyed: dict[str, dict] = {}
    for key, record in records.items():
        host = containers[record["container"]]
        keyed[key] = {
            "key": key,
            "key_id": record["key_id"],
            "bucket": host["bucket"],
            "kind": _kind_of(record, host),
            "scene": host["scene"],
            "ctx": host["ctx"],
            "container": record["container"],
            "start": record["start"],
            "end": record["end"],
            "line_aligned": record["line_aligned"],
            "risky_file": host["risky_file"],
            "occurrences": sum(1 for item in fragments_by_container[record["container"]]
                               if item["key"] == key),
        }
    return {
        "keys": keyed,
        "fragments_by_container": fragments_by_container,
        "total_keys": len(keys),
    }


def _unit_of(container: dict, fragments: list[dict], source_zh: str = "") -> dict:
    """One translation unit: a host field plus the fragments to translate.

    `fragments` come from the keymap (``key``) or from a container record
    (``ja``); both shapes are accepted so a caller cannot lose the source text.
    `source_zh` is the *already translated* whole field, when there is one: a
    sub-line fragment is a slice of that field (typically the text between two
    control codes - exactly what the engine displays), so its translation has
    to agree with the line it was cut from.
    """
    unit = {
        "unit_id": f"c{container['container_id']}",
        "bucket": container["bucket"],
        "scene": container["scene"],
        "ctx": container["ctx"],
        "source": container["source"],
        "fragments": [
            {"key_id": item["key_id"],
             "ja": item.get("ja") or item.get("key", ""),
             "start": item["start"], "end": item["end"],
             "line_aligned": item["line_aligned"]}
            for item in fragments
        ],
    }
    if source_zh:
        unit["source_zh"] = source_zh
    return unit


def _work_paths(work: str) -> dict:
    root = Path(work)
    return {
        "root": root,
        "keymap": root / "keymap.jsonl",
        "containers": root / "containers.jsonl",
        "state": root / "state.json",
        "skipped": root / "skipped.jsonl",
        "translated": root / "translated.jsonl",
        "batches": root / "batches",
    }


def _read_jsonl(path: Path) -> list[dict]:
    """Tolerant reader for the hand-appendable files in a work dir."""
    return io_boundary.read_jsonl(path)


def _fold(text: str) -> str:
    """Comparison form: NFKC (halfwidth katakana -> fullwidth), letters only.

    The dictionary holds the same Japanese term written several ways
    (``基本ピクチャ番号`` / ``基本ﾋﾟｸﾁｬ番号``); sharing one translation between them
    is correct, so they must not look like three unrelated sources.
    """
    return "".join(char for char in unicodedata.normalize("NFKC", text or "")
                   if char.isalnum())


def _is_subsequence(short: str, long: str) -> bool:
    """Are `short`'s characters present in `long` in order?"""
    cursor = iter(long)
    return all(char in cursor for char in short)


def _is_one_term(sources: set) -> bool:
    """True when every source is just a spelling variant of the same term.

    ``基本ピクチャ番号`` / ``基本ﾋﾟｸﾁｬ番号`` / ``基本ピク番`` are one term: the
    first two fold together under NFKC, and the abbreviation is a subsequence
    of the full spelling.  Them sharing one translation is correct, not the
    collapse this check is looking for.
    """
    folded = sorted({_fold(source) for source in sources if _fold(source)}, key=len)
    if not folded or len(folded[0]) < 3:
        return False
    return all(_is_subsequence(item, folded[-1]) for item in folded)


def skip_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
             reason: Annotated[str, cliutil.Option(
                 help="why these keys are not translated")] = "editor metadata",
             where: Annotated[str, cliutil.Option(
                 "--where", help="regex: skip scope keys whose JA text matches")] = "",
             host_regex: Annotated[str, cliutil.Option(
                 "--host-regex", help="regex: skip keys whose hosting field matches "
                                      "(a piece of 'SE/x.mp3' is still a file name)")] = "",
             ctx_regex: Annotated[str, cliutil.Option(
                 "--ctx-regex", help="regex: skip keys whose command path matches")] = "",
             verbose: cliutil.Verbose = False,
             quiet: cliutil.Quiet = False,
             log_file: cliutil.LogFile = None) -> int:
    """Mark scope keys as deliberately untranslated (with a reason).

    Without this the coverage gate cannot tell "nobody looked at it yet" from
    "looked at it, decided the player never sees it" - and a gate that cannot
    tell those apart either blocks forever or passes on a half-done job.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("skip wolf keys", work=work)
    if not where and not host_regex and not ctx_regex:
        return cliutil.fail("pass --where / --host-regex / --ctx-regex naming the keys to skip")
    pattern = re.compile(where) if where else None
    host_pattern = re.compile(host_regex) if host_regex else None
    ctx_pattern = re.compile(ctx_regex) if ctx_regex else None
    paths = _work_paths(work)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    scope = set(state.get("scope_buckets") or [])
    kinds = set(state.get("scope_kinds") or ["whole-field", "line-aligned"])
    keymap = _read_jsonl(paths["keymap"])
    hosts = {record["container_id"]: record.get("source", "")
             for record in _read_jsonl(paths["containers"])}
    known = {record["key_id"] for record in _read_jsonl(paths["translated"])}
    known |= {record["key_id"] for record in _read_jsonl(paths["skipped"])}

    def matches(record: dict) -> bool:
        if pattern is not None and pattern.search(record["key"]):
            return True
        if host_pattern is not None:
            host = hosts.get(record.get("container"), "")
            if host and host_pattern.search(host):
                return True
        return ctx_pattern is not None and bool(ctx_pattern.search(record.get("ctx", "")))

    rows = [
        {"key_id": record["key_id"], "key": record["key"], "reason": reason}
        for record in keymap
        if (record["bucket"] in scope and record.get("kind") in kinds
            and record["key_id"] not in known and matches(record))
    ]
    if not rows:
        return cliutil.fail(f"no pending scope key matches {where!r}")
    with open(paths["skipped"], "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"skipped {len(rows)} key(s): {reason}")
    return 0


def _kind_of(record: dict, host: dict) -> str:
    """How the key sits in its host field.

    ``whole-field``: the key *is* the field - the unambiguous display unit,
    and the same translation serves both the runtime dictionary and a data
    rewrite.  ``line-aligned``: whole lines but not the whole field.
    ``sub-line``: a slice of a line (often a word) - the risky kind, because
    it is not a display unit by itself.
    """
    field = WS_RE.sub("", host.get("source", ""))
    key = WS_RE.sub("", record["key"])
    if key == field:
        return "whole-field"
    if record["line_aligned"]:
        return "line-aligned"
    return "sub-line"


def build_cmd(mtool: Annotated[str, cliutil.Argument(help="the game's runtime dictionary (MTool json)")],
              patch_dir: Annotated[str, cliutil.Argument(help="rewolf-trans patch tree (rewt-patch/)")],
              out_dir: Annotated[str, cliutil.Argument(help="work dir to write the keymap into")],
              verbose: cliutil.Verbose = False,
              quiet: cliutil.Quiet = False,
              log_file: cliutil.LogFile = None) -> int:
    """Map a runtime dictionary's keys onto the static game text."""
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("build wolf keymap", mtool=mtool, patch_dir=patch_dir,
                      out_dir=out_dir)
    dictionary = json.loads(Path(mtool).read_text(encoding="utf-8-sig"))
    containers = scan_containers(Path(patch_dir))
    result = build_keymap(dictionary, containers)
    paths = _work_paths(out_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    with open(paths["keymap"], "w", encoding="utf-8") as handle:
        for record in result["keys"].values():
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with open(paths["containers"], "w", encoding="utf-8") as handle:
        for container in containers:
            fragments = result["fragments_by_container"].get(
                container["container_id"], [])
            if not fragments:
                continue
            handle.write(json.dumps(dict(
                container,
                fragments=[dict(item) for item in fragments],
            ), ensure_ascii=False) + "\n")
    buckets = Counter(record["bucket"] for record in result["keys"].values())
    io_boundary.dump_json(paths["state"], {
        "version": 1,
        "patch_dir": str(patch_dir),
        "mtool": str(mtool),
        "dictionary_keys": len(dictionary),
        "kana_keys": result["total_keys"],
        "mapped_keys": len(result["keys"]),
        "containers": len(containers),
        "buckets": dict(buckets),
        "scope_buckets": [],
        "batches": [],
    })
    buckets_text = ", ".join(f"{name}={count}" for name, count in sorted(buckets.items()))
    print(f"mapped {len(result['keys'])} / {result['total_keys']} kana keys onto "
          f"{len(containers)} fields ({buckets_text})")
    return 0


def _reserved(state: dict) -> set:
    """Key ids already handed out in an unanswered batch.

    Without this, slicing twice in a row emits the same keys again: the
    batches are independent snapshots of "what is still pending", so a second
    slice before the first batch is answered duplicates the work.  That is not
    a theoretical worry - it wasted five parallel translation runs once.
    """
    return {key for keys in (state.get("in_flight") or {}).values() for key in keys}


def _release(state: dict, batch: str) -> int:
    """Drop one batch's reservation; returns how many keys were released."""
    flights = state.get("in_flight") or {}
    removed = flights.pop(str(batch), [])
    if flights:
        state["in_flight"] = flights
    else:
        state.pop("in_flight", None)
    return len(removed)


def release_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
                batch: Annotated[str, cliutil.Option(
                    help="batch file whose reservation to drop")] = "",
                verbose: cliutil.Verbose = False,
                quiet: cliutil.Quiet = False,
                log_file: cliutil.LogFile = None) -> int:
    """Drop a batch's key reservation so those keys can be sliced again."""
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("release wolf batch", work=work)
    paths = _work_paths(work)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    if not batch:
        flights = state.get("in_flight") or {}
        if not flights:
            return cliutil.fail("no batch is in flight")
        print("in flight:")
        for name, keys in sorted(flights.items()):
            print(f"  {name} ({len(keys)} keys)")
        return 0
    released = _release(state, batch)
    if not released:
        return cliutil.fail(f"{batch} has no reservation")
    io_boundary.dump_json(paths["state"], state)
    print(f"released {released} key(s) from {batch}")
    return 0


def _fragment_count(units: list[dict]) -> int:
    """How many fragments a candidate batch carries (the real size cap)."""
    return sum(len(unit["fragments"]) for unit in units)


def slice_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
              buckets: Annotated[str, cliutil.Option(
                  help="comma-separated buckets to translate")] = "DB,COMMONEVENT",
              kinds: Annotated[str, cliutil.Option(
                  help="comma-separated key kinds (whole-field,line-aligned,sub-line)"
              )] = "whole-field,line-aligned",
              units: Annotated[int, cliutil.Option(
        help="max fragments per batch (a unit never carries more)")] = 12,
              offset: Annotated[int, cliutil.Option(help="skip this many units")] = 0,
              out: Annotated[str, cliutil.Option(help="batch file")] = "",
              verbose: cliutil.Verbose = False,
              quiet: cliutil.Quiet = False,
              log_file: cliutil.LogFile = None) -> int:
    """Emit one translation batch (units = host fields, with their fragments)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("slice wolf batch", work=work, out=out or work)
    paths = _work_paths(work)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    wanted = {item.strip() for item in buckets.split(",") if item.strip()}
    wanted_kinds = {item.strip() for item in kinds.split(",") if item.strip()}
    done = {record["key_id"] for record in io_boundary.read_jsonl(paths["translated"])}
    done |= {record["key_id"] for record in io_boundary.read_jsonl(paths["skipped"])}
    reserved = _reserved(state)
    keymap = io_boundary.read_jsonl(paths["keymap"])
    translated_text = {record["key_id"]: record["zh"]
                       for record in io_boundary.read_jsonl(paths["translated"])}
    # container -> the key id of its whole-field entry, so a sub-line batch can
    # carry the line's existing translation as reference
    whole_key = {record["container"]: record["key_id"] for record in keymap
                 if record.get("kind") == "whole-field"}
    containers = {record["container_id"]: record
                  for record in io_boundary.read_jsonl(paths["containers"])}
    by_container: dict[int, list[dict]] = defaultdict(list)
    for record in keymap:
        if record["bucket"] in wanted and record.get("kind", "whole-field") in wanted_kinds:
            by_container[record["container"]].append(record)
    chosen: list[dict] = []
    skipped = 0
    for container_id in sorted(by_container):
        pending = [record for record in by_container[container_id]
                   if record["key_id"] not in done
                   and record["key_id"] not in reserved]
        if not pending:
            continue
        if skipped < offset:
            skipped += 1
            continue
        host = containers.get(container_id, {})
        whole_text = translated_text.get(whole_key.get(container_id, ""), "")
        # container -1 = runtime key: no hosting field, so chunk them instead of
        # emitting thousands of fragments into a single unit
        size = min(_RUNTIME_UNIT, units) if container_id < 0 else len(pending)
        ordered = sorted(pending, key=lambda item: item["start"])
        for start in range(0, len(ordered), size):
            chunk = ordered[start:start + size]
            chosen.append(_unit_of(
                {"container_id": container_id,
                 "bucket": chunk[0]["bucket"],
                 "scene": chunk[0]["scene"],
                 "ctx": chunk[0]["ctx"],
                 "source": host.get("source", "")},
                chunk,
                source_zh=whole_text))
            if _fragment_count(chosen) >= units:
                break
        if _fragment_count(chosen) >= units:
            break
    payload = {"version": 1, "buckets": sorted(wanted),
               "kinds": sorted(wanted_kinds), "units": chosen}
    out_path = Path(out) if out else paths["batches"] / f"batch-{len(state['batches']):04d}.json"
    io_boundary.dump_json(out_path, payload)
    keys = sum(len(unit["fragments"]) for unit in chosen)
    state["scope_buckets"] = sorted(set(state.get("scope_buckets", [])) | wanted)
    state["scope_kinds"] = sorted(set(state.get("scope_kinds", [])) | wanted_kinds)
    state["batches"].append(str(out_path))
    if keys:
        flights = state.setdefault("in_flight", {})
        flights[str(out_path)] = [fragment["key_id"] for unit in chosen
                                  for fragment in unit["fragments"]]
    io_boundary.dump_json(paths["state"], state)
    print(f"{out_path}: {len(chosen)} units / {keys} fragments")
    return 0


def apply_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
              batch: Annotated[str, cliutil.Argument(help="translated batch file")],
              allow_kana_in_codes: Annotated[bool, cliutil.Option(
                  "--allow-kana-in-codes", help="accept kana that sits inside a "
                                                 "control-code parameter (ruby "
                                                 "readings), recorded per row")] = False,
              verbose: cliutil.Verbose = False,
              quiet: cliutil.Quiet = False,
              log_file: cliutil.LogFile = None) -> int:
    """Store a translated batch - every fragment must pass the gates."""
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("apply wolf batch", work=work, batch=batch)
    paths = _work_paths(work)
    payload = json.loads(Path(batch).read_text(encoding="utf-8"))
    keymap = {record["key_id"]: record for record in _read_jsonl(paths["keymap"])}
    existing = _read_jsonl(paths["translated"])
    known = {record["key_id"] for record in existing}
    # a decided-skip key is not translated on purpose: its answer in the batch is
    # irrelevant, and demanding a translation would contradict the skip
    decided_skip = {record["key_id"] for record in _read_jsonl(paths["skipped"])}
    honoured = 0
    seen: set[str] = set()
    rows: list[dict] = []
    problems: list[str] = []
    kana_in_code: list[str] = []
    for unit in payload.get("units", []):
        for fragment in unit["fragments"]:
            fragment_id = fragment.get("key_id", "")
            if fragment.get("zh") is None:
                continue
            if fragment_id in seen:
                problems.append(f"{fragment_id}: duplicate in batch")
                continue
            if fragment_id in decided_skip:
                honoured += 1
                continue
            seen.add(fragment_id)
            source = fragment.get("ja") or keymap.get(fragment_id, {}).get("key", "")
            found = validate_fragment(source, fragment["zh"])
            if allow_kana_in_codes and fragment["zh"] and kana_inside_codes_only(fragment["zh"]):
                found = [item for item in found if not item.startswith("kana")]
                kana_in_code.append(fragment_id)
            problems.extend(f"{fragment_id}: {problem}" for problem in found)
            rows.append({"key_id": fragment_id, "zh": fragment["zh"],
                         "unit_id": unit.get("unit_id", ""), "key": source,
                         **({"note": fragment["note"]} if fragment.get("note") else {}),
                         **({"kana_in_code": True} if fragment_id in kana_in_code else {})})
    if problems:
        for problem in problems[:20]:
            print(f"REJECT {problem}")
        return cliutil.fail(f"{len(problems)} fragment(s) failed; nothing written")
    if not rows:
        return cliutil.fail("batch contains no translated fragment")
    with open(paths["translated"], "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    # storing a batch resolves its reservation, so the keys cannot be sliced again
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    stored_ids = {row["key_id"] for row in rows}
    flights = state.get("in_flight") or {}
    for name in list(flights):
        flights[name] = [key for key in flights[name] if key not in stored_ids]
        if not flights[name]:
            del flights[name]
    if flights:
        state["in_flight"] = flights
    else:
        state.pop("in_flight", None)
    io_boundary.dump_json(paths["state"], state)
    print(f"stored {len(rows)} fragment(s) ({len(known)} already known)"
          + (f"; kana-inside-code accepted on {len(kana_in_code)}" if kana_in_code else "")
          + (f"; {honoured} decided-skip key(s) left out" if honoured else ""))
    return 0


def _align_backslash_runs(ja: str, zh: str) -> str:
    """Give the value's control codes the same backslash run as the source.

    Wolf stores codes doubled (``\\\\f[30]``); a translator who writes the
    single-backslash form the *engine* uses produces a correct-looking string
    that fails the code gate.  Renaming the run (and nothing else) is lossless:
    the code name, its parameters and the text are untouched.
    """
def _align_backslash_runs(ja: str, zh: str) -> str:
    """Give the value's control codes the same backslash run as the source.

    Wolf stores codes doubled (``\\\\f[30]``); a translator who writes the
    single-backslash form produces a string that reads correctly and still
    fails the code gate.  The tokens are spliced in by **position** (right to
    left) rather than by ``str.replace``: ``\\i[403]`` is a substring of
    ``\\\\i[403]``, so replacing text-wise corrupts an already-fixed token
    (it turned one into three backslashes when this used replace).
    """
    ja_tokens = [(m.start(), m.end(), m.group(0)) for m in CODE_RE.finditer(ja or "")]
    zh_tokens = [(m.start(), m.end(), m.group(0)) for m in CODE_RE.finditer(zh or "")]
    if not ja_tokens or len(ja_tokens) != len(zh_tokens):
        return zh
    for (_js, _je, source), (_zs, _ze, target) in zip(ja_tokens, zh_tokens, strict=True):
        if _code_name(source) != _code_name(target):
            return zh
    fixed = zh
    for (_js, _je, source), (start, end, _target) in reversed(
            list(zip(ja_tokens, zh_tokens, strict=True))):
        fixed = fixed[:start] + source + fixed[end:]
    return fixed


def _code_name(token: str) -> str:
    """``\\\\f[30]`` and ``\\f[30]`` are the same code: compare names."""
    match = re.match(r"\\+([A-Za-z]+)", token or "")
    return match.group(1) if match else (token or "")


def kana_inside_codes_only(zh: str) -> bool:
    """Is every kana in `zh` inside a control-code token?

    A ruby/reading parameter (``\\r[漢字,よみ]``) carries displayed Japanese
    kana that cannot be removed without changing the code token, and the code
    token cannot change without breaking the code gate.  When the two rules
    genuinely collide, the caller has to opt in explicitly - this predicate is
    what makes the opt-in narrow instead of a hole in the gate.
    """
    without_codes = CODE_RE.sub("", zh or "")
    return bool(KANA_LETTERS_RE.search(zh or "")) and not KANA_LETTERS_RE.search(without_codes)


def _restore_line_breaks(ja: str, zh: str) -> str:
    """Put back leading/trailing newlines the source had and the value lost.

    Dialogue fragments are routinely split so that the line break lives at the
    start or the end of the fragment; a translator writing the fragment on its
    own drops it.  Restoring it is mechanical and lossless - the text is not
    touched - but only when the difference is exactly explainable that way: a
    value whose *interior* line structure differs is still rejected, because
    that is a real layout change, not a dropped edge.
    """
    if zh is None:
        return zh
    missing = (ja or "").count("\n") - (zh or "").count("\n")
    if missing <= 0:
        return zh
    fixed = zh
    if (ja or "").startswith("\n") and not fixed.startswith("\n"):
        fixed = "\n" + fixed
        missing -= 1
    if missing > 0 and (ja or "").endswith("\n") and not fixed.endswith("\n"):
        fixed = fixed + "\n" * missing
        missing = 0
    return fixed if missing == 0 else zh


def answer_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
               batch: Annotated[str, cliutil.Argument(help="batch file produced by slice")],
               answers: Annotated[str, cliutil.Argument(
                   help="translations: 'id<TAB>text' / JSONL, or one value per line "
                        "with --positional")],
               positional: Annotated[bool, cliutil.Option(
                   "--positional", help="the file holds one translation per line, in the "
                                        "batch's fragment order (no ids to retype)")] = False,
               fix_newlines: Annotated[bool, cliutil.Option(
                   "--fix-newlines", help="restore leading/trailing newlines the source "
                                         "had (text untouched; interior line breaks are "
                                         "still a failure)")] = False,
               allow_kana_in_codes: Annotated[bool, cliutil.Option(
                   "--allow-kana-in-codes", help="accept kana that sits inside a "
                                                  "control-code parameter (ruby "
                                                  "readings), recorded per row")] = False,
               note: Annotated[str, cliutil.Option(
                   help="recorded in the stored rows, for the audit trail")] = "",
               verbose: cliutil.Verbose = False,
               quiet: cliutil.Quiet = False,
               log_file: cliutil.LogFile = None) -> int:
    """Fill a batch from a file of translations and store it in one step.

    Three shapes, all mechanical: ``id<TAB>text`` per line, one JSON object
    per line (the only shape that can carry a real newline in a value), or -\n    with ``--positional`` - one value per line in the batch's own fragment
    order.  Positional exists because retyping a 16-hex-digit id per key is
    pure overhead when the batch already fixes the order; the count must match
    exactly, so a dropped line is an error and never a silent shift.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("answer wolf batch", work=work, batch=batch, answers=answers)
    payload = json.loads(Path(batch).read_text(encoding="utf-8"))
    pending = [fragment for unit in payload["units"]
               for fragment in unit["fragments"] if "zh" not in fragment]
    lines = [line for line in Path(answers).read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    table: dict[str, str] = {}
    if positional:
        # Either a JSON array of strings (multi-line values survive) or one
        # value per line.  The count must match, so a dropped line is an error.
        if lines and lines[0].lstrip().startswith("["):
            try:
                values = json.loads(Path(answers).read_text(encoding="utf-8"))
            except ValueError as error:
                return cliutil.fail(f"{answers}: not valid JSON ({error})")
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                return cliutil.fail(f"{answers}: expected a JSON array of strings")
        else:
            values = lines
        if len(values) != len(pending):
            return cliutil.fail(f"--positional needs exactly one value per fragment: "
                                f"batch has {len(pending)}, file has {len(values)}")
        for fragment, value in zip(pending, values, strict=True):
            table[fragment["key_id"]] = value
    else:
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith("{"):
                # JSONL: the only shape that can carry a real newline in a value
                try:
                    record = json.loads(line)
                except ValueError as error:
                    return cliutil.fail(f"{answers}:{number}: not valid JSON ({error})")
                fragment_id = str(record.get("id", record.get("key_id", ""))).strip()
                value = record.get("zh")
                if not fragment_id or not isinstance(value, str):
                    return cliutil.fail(
                        f"{answers}:{number}: expected an object with 'id' and 'zh'")
                table[fragment_id] = value
                continue
            if "\t" not in line:
                return cliutil.fail(f"{answers}:{number}: expected 'id<TAB>text' "
                                    f"(use one JSON object per line for multi-line values)")
            fragment_id, _, value = line.partition("\t")
            table[fragment_id.strip()] = value
    filled = 0
    repaired = 0
    for unit in payload["units"]:
        for fragment in unit["fragments"]:
            value = table.pop(fragment["key_id"], None)
            if value is None or not value.strip():
                continue
            if fix_newlines:
                restored = _restore_line_breaks(fragment["ja"], value)
                if restored != value:
                    repaired += 1
                    value = restored
            aligned = _align_backslash_runs(fragment["ja"], value)
            if aligned != value:
                repaired += 1
                value = aligned
            fragment["zh"] = value
            filled += 1
    unknown = sorted(table)
    if unknown:
        return cliutil.fail(f"{len(unknown)} answer id(s) are not in this batch: "
                            f"{', '.join(unknown[:5])}")
    missing = [fragment["key_id"] for unit in payload["units"]
               for fragment in unit["fragments"] if "zh" not in fragment]
    if missing:
        return cliutil.fail(f"{len(missing)} fragment(s) left untranslated in this batch "
                            f"(e.g. {', '.join(missing[:5])})")
    if note:
        for unit in payload["units"]:
            for fragment in unit["fragments"]:
                fragment["note"] = note
    batch_path = Path(str(batch) + ".filled.json")
    io_boundary.dump_json(batch_path, payload)
    code = apply_cmd(work, str(batch_path), allow_kana_in_codes=allow_kana_in_codes,
                     verbose=verbose, quiet=quiet, log_file=log_file)
    if code != 0:
        return code
    print(f"filled {filled} fragment(s) from {answers}"
          + (f"; restored line breaks on {repaired}" if repaired else ""))
    return 0


def _font_gaps(font_path: Path, values: dict) -> list[str]:
    """Characters used by the stored values that the build font cannot draw.

    A codepoint outside the font's cmap renders as a blank box on screen, which
    is invisible in every other check here.  Control characters (newline, tab,
    carriage return) are not glyphs and are skipped.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:                                    # pragma: no cover
        return ["fontTools is not installed: cannot verify glyph coverage"]
    font = TTFont(str(font_path), lazy=True)
    cmap = set(font.getBestCmap())
    offenders: dict[str, list[str]] = defaultdict(list)
    for key, value in values.items():
        for char in value:
            if char in "\n\t\r":
                continue
            if ord(char) not in cmap:
                offenders[char].append(key)
    return [f"{char!r} U+{ord(char):04X} in {len(keys)} value(s) e.g. {keys[0]}"
            for char, keys in sorted(offenders.items(), key=lambda kv: -len(kv[1]))]


def gates_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
              font: Annotated[str, cliutil.Option(
                  "--font", help="TTF/OTF of the build font: fail on any character "
                                 "it cannot draw")] = "",
              json_out: Annotated[str, cliutil.Option("--json", help="write the report as JSON")] = "",
              verbose: cliutil.Verbose = False,
              quiet: cliutil.Quiet = False,
              log_file: cliutil.LogFile = None) -> int:
    """Check coverage / codes / newlines / kana residue / conflicts."""
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("wolf gates", work=work, json_out=json_out or work)
    paths = _work_paths(work)
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    scope = set(state.get("scope_buckets") or [])
    kinds = set(state.get("scope_kinds") or ["whole-field", "line-aligned"])
    keymap = _read_jsonl(paths["keymap"])
    translated = _read_jsonl(paths["translated"])
    in_scope = [record for record in keymap
                if record["bucket"] in scope
                and record.get("kind") in kinds]
    by_id = {record["key_id"]: record for record in in_scope}
    done: dict[str, str] = {}
    conflicts: list[str] = []
    bad: list[str] = []
    exceptions: list[str] = []
    for record in translated:
        record_id = record["key_id"]
        if record_id not in by_id:
            continue
        if record_id in done and done[record_id] != record["zh"]:
            conflicts.append(f"{record_id}: {done[record_id]!r} vs {record['zh']!r}")
        done[record_id] = record["zh"]
        if record.get("kana_in_code"):
            # an explicit, recorded exception: the kana sits inside a ruby
            # parameter, where "keep the code verbatim" and "no kana" collide.
            # It was accepted with a flag and is auditable per row, so the gate
            # reports it instead of failing on it.
            exceptions.append(record_id)
            continue
        bad.extend(f"{record_id}: {problem}"
                   for problem in validate_fragment(by_id[record_id]["key"], record["zh"]))
    translate = {record["key_id"]: record["zh"] for record in _read_jsonl(paths["translated"])}
    skipped = {record["key_id"] for record in _read_jsonl(paths["skipped"])}
    missing = [record["key_id"] for record in in_scope
               if record["key_id"] not in translate and record["key_id"] not in skipped]
    unrenderable: list[str] = []
    if font:
        unrenderable = _font_gaps(Path(font), translate)
    report = {
        "scope_buckets": sorted(scope),
        "scope_kinds": sorted(kinds),
        "scope_keys": len(in_scope),
        "translated": len(translate),
        "skipped": len(skipped),
        "missing": len(missing),
        "conflicts": conflicts,
        "invalid": bad,
        "kana_in_code": exceptions,
        "font": font,
        "unrenderable": unrenderable,
    }
    if json_out:
        io_boundary.dump_json(json_out, report)
    if not in_scope:
        # A gate that passes because nothing was in scope is a false pass:
        # the operator must slice at least one batch first.
        return cliutil.fail("nothing in scope (run `slice --buckets ...` first)")
    for name in ("scope_keys", "translated", "skipped", "missing"):
        print(f"{name:<12} {report[name]}")
    if conflicts:
        print(f"conflicts: {len(conflicts)} (e.g. {conflicts[0]})")
    if exceptions:
        print(f"kana inside code (recorded exception): {len(exceptions)}")
    if bad:
        print(f"invalid: {len(bad)} (e.g. {bad[0]})")
    if missing:
        for record_id in missing[:5]:
            print("  missing {} {!r}".format(record_id, by_id[record_id]["key"][:40]))
    if unrenderable:
        print(f"characters the font cannot draw: {len(unrenderable)}")
        for item in unrenderable[:10]:
            print("  " + item)
    ok = not (missing or conflicts or bad or unrenderable)
    print("gates: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else cliutil.fail("gates not satisfied")


def _structure_score(ja: str, zh: str) -> int:
    """How well a value keeps the source's own bracket structure.

    A fragment translated on its own tends to grow the brackets its *neighbour*
    carries (``（`` on the left, ``）`` on the right), so the same source ends up
    with two values and the runtime dictionary - which is keyed by source text -
    can only hold one.  The source's own bracket counts are the tie-breaker a
    human would use, and they are checkable without judgement calls.
    """
    score = 0
    for opener, closer in (("（", "）"), ("「", "」"), ("『", "』"), ("<", ">")):
        if ja.count(opener) == zh.count(opener) and ja.count(closer) == zh.count(closer):
            score += 1
    return score


def resolve_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
                report: Annotated[str, cliutil.Option(
                    "--report", help="write the losing values here (JSONL)")] = "",
                dry_run: Annotated[bool, cliutil.Option(
                    "--dry-run", help="report the choices without rewriting")] = False,
                verbose: cliutil.Verbose = False,
                quiet: cliutil.Quiet = False,
                log_file: cliutil.LogFile = None) -> int:
    """Collapse duplicate values for one key: the dictionary holds exactly one.

    The runtime dictionary is keyed by the source string, so when two batches
    stored different values for the same key only one can ever be shown. Rather
    than letting "last writer wins" decide silently, pick the winner by an
    explicit rule and keep the losers in a report.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("resolve wolf duplicates", work=work, report=report or work)
    paths = _work_paths(work)
    keymap = {record["key_id"]: record for record in _read_jsonl(paths["keymap"])}
    rows = _read_jsonl(paths["translated"])
    kind_rank = {"whole-field": 3, "line-aligned": 2, "sub-line": 1, "runtime": 0}
    grouped: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for row in rows:
        if row["key_id"] not in grouped:
            order.append(row["key_id"])
        grouped[row["key_id"]].append(row)
    kept: list[dict] = []
    losers: list[dict] = []
    for record_id in order:
        group = grouped[record_id]
        values = {row["zh"] for row in group}
        if len(values) == 1:
            kept.append(group[-1])
            continue
        source = keymap.get(record_id, {}).get("key", "")
        kind = kind_rank.get(keymap.get(record_id, {}).get("kind", ""), 0)
        winner = max(group, key=lambda row: (
            _structure_score(source, row["zh"]),
            kind,
            sum(1 for other in group if other["zh"] == row["zh"]),
        ))
        kept.append(winner)
        losers.extend(
            {"key_id": record_id, "ja": source, "kept": winner["zh"],
             "dropped": row["zh"], "reason": "bracket structure of the source"}
            for row in group if row["zh"] != winner["zh"])
    print(f"keys {len(order)}; kept one value each; dropped {len(losers)} duplicate value(s)")
    if report and losers:
        with open(report, "w", encoding="utf-8") as handle:
            for row in losers:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"wrote {report}")
    if dry_run:
        return 0
    if losers:
        with open(paths["translated"], "w", encoding="utf-8") as handle:
            for row in kept:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


def revise_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
               answers: Annotated[str, cliutil.Argument(
                   help="JSONL of {\"id\": ..., \"zh\": ...} replacements")],
               upsert: Annotated[bool, cliutil.Option(
                   "--upsert", help="also insert ids that are not stored yet "
                                    "(used for derived values)")] = False,
               verbose: cliutil.Verbose = False,
               quiet: cliutil.Quiet = False,
               log_file: cliutil.LogFile = None) -> int:
    """Replace already-stored values (gated, so a fix cannot break a string).

    A value that passed the gates last week can still be wrong: a glossary
    decision may have landed later, or the consistency check may have found
    the same term rendered two ways.  Editing the state file by hand would
    bypass every check, so the correction goes through the same validation as
    a fresh batch - and it is recorded as a revision, not a silent overwrite.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("revise wolf translations", work=work, answers=answers)
    paths = _work_paths(work)
    keymap = {record["key_id"]: record for record in _read_jsonl(paths["keymap"])}
    stored = _read_jsonl(paths["translated"])
    wanted: dict[str, str] = {}
    for number, line in enumerate(
            Path(answers).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        record = json.loads(line)
        fragment_id = str(record.get("id", record.get("key_id", ""))).strip()
        value = record.get("zh")
        if not fragment_id or not isinstance(value, str):
            return cliutil.fail(f"{answers}:{number}: expected an object with 'id' and 'zh'")
        wanted[fragment_id] = value
    known = {record["key_id"] for record in stored}
    unknown = sorted(set(wanted) - known)
    if unknown and not upsert:
        return cliutil.fail(f"{len(unknown)} id(s) are not stored yet: {', '.join(unknown[:5])}"
                            " (pass --upsert to insert them)")
    problems = [f"{fragment_id}: {problem}"
                for fragment_id, value in wanted.items()
                for problem in validate_fragment(
                    keymap.get(fragment_id, {}).get("key", ""), value)]
    if problems:
        for problem in problems[:20]:
            print(f"REJECT {problem}")
        return cliutil.fail(f"{len(problems)} revision(s) failed; nothing written")
    newly = 0
    for fragment_id in unknown:
        stored.append({"key_id": fragment_id, "zh": wanted[fragment_id],
                       "key": keymap.get(fragment_id, {}).get("key", ""),
                       "derived": True})
        newly += 1
    revised = 0
    for record in stored:
        if (record["key_id"] in wanted
                and record["zh"] != wanted[record["key_id"]]):
            record["revised_from"] = record["zh"]
            record["zh"] = wanted[record["key_id"]]
            revised += 1
    io_boundary.write_text(paths["translated"], "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in stored))
    print(f"revised {revised} value(s) of {len(wanted)} requested"
          + (f"; inserted {newly}" if newly else ""))
    return 0


def normalize_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
                  symbols: Annotated[str, cliutil.Argument(
                      help="JSON {\"from\": \"to\"} symbol substitutions")],
                  verbose: cliutil.Verbose = False,
                  quiet: cliutil.Quiet = False,
                  log_file: cliutil.LogFile = None) -> int:
    """Replace symbols the project font cannot draw, from an explicit table.

    The font is the authority on what renders: a character outside its cmap is
    a blank box on the player's screen.  Which *substitute* to use is a
    judgement call, so the mapping lives in a reviewable JSON file next to the
    glossary instead of inside this tool.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("normalize wolf symbols", work=work, symbols=symbols)
    paths = _work_paths(work)
    table = json.loads(Path(symbols).read_text(encoding="utf-8"))
    if not isinstance(table, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in table.items()):
        return cliutil.fail(f"{symbols}: expected a flat object of string -> string")
    stored = _read_jsonl(paths["translated"])
    changed = 0
    counts = Counter()
    for record in stored:
        value = record["zh"]
        fixed = value
        for old, new in table.items():
            if old in fixed:
                counts[old] += fixed.count(old)
                fixed = fixed.replace(old, new)
        if fixed != value:
            record["zh"] = fixed
            changed += 1
            record.setdefault("symbol_normalized", True)
    if not changed:
        print("nothing to normalize")
        return 0
    io_boundary.write_text(paths["translated"], "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in stored))
    summary = ", ".join(f"{ch}x{n}" for ch, n in counts.most_common())
    print(f"normalized {changed} value(s): {summary}")
    return 0


def import_keys_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
                    mtool: Annotated[str, cliutil.Argument(
                        help="the game's runtime dictionary (source of the keys)")],
                    where: Annotated[str, cliutil.Option(
                        "--where", help="regex: adopt keys whose JA text matches")] = ".",
                    every: Annotated[bool, cliutil.Option(
                        "--all", help="also adopt keys without kana (kanji-only "
                                       "labels): they are in the dictionary because "
                                       "the game displayed them")] = False,
                    verbose: cliutil.Verbose = False,
                    quiet: cliutil.Quiet = False,
                    log_file: cliutil.LogFile = None) -> int:
    """Adopt dictionary keys that have no static source text at all.

    Some runtime strings never appear in the extracted data: the game composes
    them (a date plus a label) or they sit inside a command the extractor does
    not parse.  The runtime dictionary still holds them, which is proof the
    player sees them, so they are translated from the key text itself.
    They join the keymap as ``kind=runtime`` in a ``RUNTIME`` bucket.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("import runtime keys", work=work, mtool=mtool)
    paths = _work_paths(work)
    pattern = re.compile(where)
    known = {record["key"] for record in io_boundary.read_jsonl(paths["keymap"])}
    dictionary = json.loads(Path(mtool).read_text(encoding="utf-8-sig"))
    adopted = 0
    with open(paths["keymap"], "a", encoding="utf-8") as handle:
        for key in dictionary:
            if key in known or not key_id(key):
                continue
            if not every and not KANA_LETTERS_RE.search(key):
                continue
            if not pattern.search(key):
                continue
            handle.write(json.dumps({
                "key": key, "key_id": key_id(key), "bucket": "RUNTIME",
                "kind": "runtime", "scene": "", "ctx": "[RUNTIME]",
                "container": -1, "start": 0, "end": len(key),
                "line_aligned": True, "risky_file": False, "occurrences": 1,
            }, ensure_ascii=False) + "\n")
            adopted += 1
    if not adopted:
        print("nothing to adopt (all matching keys are already mapped)")
        return 0
    print(f"adopted {adopted} runtime key(s) as kind=runtime, bucket=RUNTIME")
    return 0


def adopt_fields_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
                     verbose: cliutil.Verbose = False,
                     quiet: cliutil.Quiet = False,
                     log_file: cliutil.LogFile = None) -> int:
    """Adopt host fields of untranslated fragments as translatable units.

    A fragment (the text between two control codes of a field) is what the
    engine displays, but it is a slice - translating slices gives half
    sentences.  Where the dictionary has no whole-line key, the *field* is the
    only coherent unit, so it is adopted here as a normal ``whole-field`` unit
    and its fragments are derived from the result afterwards.
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("adopt wolf host fields", work=work)
    paths = _work_paths(work)
    keymap = io_boundary.read_jsonl(paths["keymap"])
    stored = {record["key_id"] for record in io_boundary.read_jsonl(paths["translated"])}
    containers = {record["container_id"]: record
                  for record in io_boundary.read_jsonl(paths["containers"])}
    whole = {record["container"]: record["key_id"] for record in keymap
             if record.get("kind") == "whole-field"}
    pending_hosts = {record["container"] for record in keymap
                     if record.get("kind") == "sub-line"
                     and record["key_id"] not in stored}
    adopted = 0
    with open(paths["keymap"], "a", encoding="utf-8") as handle:
        for container_id in sorted(pending_hosts):
            if whole.get(container_id) in stored:
                continue
            host = containers.get(container_id)
            if not host or not host["source"].strip():
                continue
            handle.write(json.dumps({
                "key": host["source"],
                "key_id": key_id(host["source"]),
                "bucket": host["bucket"], "kind": "whole-field",
                "scene": host["scene"], "ctx": host["ctx"],
                "container": container_id, "start": 0,
                "end": len(WS_RE.sub("", host["source"])),
                "line_aligned": True, "risky_file": host["risky_file"],
                "occurrences": 1, "adopted_field": True,
            }, ensure_ascii=False) + "\n")
            adopted += 1
    print(f"adopted {adopted} host field(s) as whole-field units")
    return 0


def terms_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
              glossary: Annotated[str, cliutil.Argument(
                  help="workspace glossary.json ({section: {ja: zh}})")],
              ignore: Annotated[str, cliutil.Option(
                  "--ignore", help="JSONL of {term, key_id, reason} pairs accepted "
                                   "as false positives")] = "",
              json_out: Annotated[str, cliutil.Option("--json", help="write the report as JSON")] = "",
              limit: Annotated[int, cliutil.Option(help="max problems to print")] = 20,
              verbose: cliutil.Verbose = False,
              quiet: cliutil.Quiet = False,
              log_file: cliutil.LogFile = None) -> int:
    """Check stored translations against the workspace glossary.

    Two failure modes the five hard gates cannot see, both of which are exactly
    what made the machine translation unusable:

    * a source term that *has* a decided translation but whose value does not
      use it (the same word rendered three ways across batches);
    * the same short Chinese value reused for unrelated source strings (the
      machine translation collapsed `君が`/`あなた`/`お前` into one word).
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("check wolf terms", work=work, glossary=glossary,
                      ignore=ignore or work, json_out=json_out or work)
    ignored = {(record.get("term"), record.get("key_id"))
               for record in (io_boundary.read_jsonl(ignore) if ignore else [])}
    ignored_values = {record.get("zh")
                      for record in (io_boundary.read_jsonl(ignore) if ignore else [])
                      if record.get("zh")}
    paths = _work_paths(work)
    payload = json.loads(Path(glossary).read_text(encoding="utf-8"))
    table = {ja: zh for section, entries in payload.items() if section != "meta"
             for ja, zh in entries.items()}
    keymap = {record["key_id"]: record for record in _read_jsonl(paths["keymap"])}
    stored = _read_jsonl(paths["translated"])
    drift: list[dict] = []
    for record in stored:
        source = keymap.get(record["key_id"], {}).get("key", record.get("key", ""))
        value = record["zh"]
        # Only the *longest* matching term is checked: a shorter term that is a
        # prefix of a longer one is a different word (`カフェ` 咖啡店 vs
        # `カフェイン値` 咖啡因值, `配信` 直播 vs `配信者` 主播).  Comparing
        # every substring match reported those as drift and made the gate
        # cry wolf, which is how a gate gets ignored.
        matches = [ja for ja in table if ja and ja in source]
        if not matches:
            continue
        longest = max(len(ja) for ja in matches)
        for ja in [term for term in matches if len(term) == longest]:
            zh = table[ja]
            if zh in value or (ja, record["key_id"]) in ignored:
                continue
            drift.append({"key_id": record["key_id"], "term": ja,
                          "expected": zh, "ja": source[:60], "zh": value[:60]})
    collapsed: dict[str, set] = defaultdict(set)
    for record in stored:
        source = keymap.get(record["key_id"], {}).get("key", "")
        if 0 < len(record["zh"]) <= 8:
            collapsed[record["zh"]].add(_fold(source))
    merged = [{"zh": value, "sources": sorted(sources)[:6], "count": len(sources)}
              for value, sources in collapsed.items()
              if len(sources) >= 3 and not _is_one_term(sources)
              and value not in ignored_values]
    report = {"translated": len(stored), "glossary_terms": len(table),
              "accepted_false_positives": len(ignored) + len(ignored_values),
              "term_drift": drift, "merged_values": merged}
    if json_out:
        io_boundary.dump_json(json_out, report)
    print(f"translated {len(stored)}; glossary terms {len(table)}")
    print(f"term drift: {len(drift)} (source uses a term whose translation is missing)")
    for item in drift[:limit]:
        print(f"  {item['key_id']} {item['term']}->{item['expected']}: {item['zh']!r} (ja {item['ja']!r})")
    print(f"short value reused for >=3 different sources: {len(merged)}")
    for item in merged[:5]:
        print(f"  {item['zh']!r} x{item['count']} {item['sources'][:3]}")
    return 0 if not drift and not merged else 1


def export_cmd(work: Annotated[str, cliutil.Argument(help="work dir")],
               mtool: Annotated[str, cliutil.Argument(help="original dictionary (key order/source)")],
               out: Annotated[str, cliutil.Argument(help="dictionary to write")],
               allow_partial: Annotated[bool, cliutil.Option(
                   "--allow-partial", help="keep untranslated keys as-is")] = False,
               verbose: cliutil.Verbose = False,
               quiet: cliutil.Quiet = False,
               log_file: cliutil.LogFile = None) -> int:
    """Write the runtime dictionary: same keys, our translations where we have them.

    A key the operator deliberately decided not to translate (a resource path, an
    event-name argument the engine resolves by name) is a *decision*, not an
    omission, so it does not block the export - it is counted and reported.
    Only keys with no decision at all still refuse to ship, which is the
    difference between "finished" and "nobody looked at it".
    """
    cliutil.setup_logging(verbose, quiet, log_file)
    cliutil.own_paths("export wolf dictionary", work=work, mtool=mtool, out=out)
    paths = _work_paths(work)
    translated = {record["key_id"]: record["zh"] for record in _read_jsonl(paths["translated"])}
    decided = {record["key_id"] for record in _read_jsonl(paths["skipped"])}
    original = json.loads(Path(mtool).read_text(encoding="utf-8-sig"))
    out_dict: dict[str, str] = {}
    replaced = skipped_kept = undecided = 0
    for key, value in original.items():
        identifier = key_id(key)
        ours = translated.get(identifier)
        if ours is not None:
            out_dict[key] = ours
            replaced += 1
        else:
            out_dict[key] = value
            if identifier in decided:
                skipped_kept += 1
            else:
                undecided += 1
    if undecided and not allow_partial:
        return cliutil.fail(f"{undecided} key(s) have no decision at all "
                            f"({replaced} translated, {skipped_kept} deliberately skipped); "
                            "translate or skip them, or pass --allow-partial")
    io_boundary.dump_json(Path(out), out_dict, compact=True)
    print(f"wrote {out}: {replaced} replaced, {skipped_kept} deliberately skipped, "
          f"{undecided} undecided")
    if skipped_kept:
        print("  deliberately skipped keys keep the game's original value on purpose; "
              "see skipped.jsonl for the reason of each")
    return 0


app = cliutil.app(help=__doc__)
app.command("build")(build_cmd)
app.command("slice")(slice_cmd)
app.command("release")(release_cmd)
app.command("apply")(apply_cmd)
app.command("answer")(answer_cmd)
app.command("skip")(skip_cmd)
app.command("terms")(terms_cmd)
app.command("normalize")(normalize_cmd)
app.command("import-keys")(import_keys_cmd)
app.command("adopt-fields")(adopt_fields_cmd)
app.command("revise")(revise_cmd)
app.command("resolve")(resolve_cmd)
app.command("gates")(gates_cmd)
app.command("export")(export_cmd)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="mtool_keymap.py")


if __name__ == "__main__":
    raise SystemExit(main())
