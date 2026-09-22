#!/usr/bin/env python3
"""Shared I/O boundary: how bytes become visible to a reader (core).

Why this exists
---------------
Phase 6 task 4 is "unify the I/O boundary: paths, encoding, JSON, atomic
write, backup, log context".  Before this module the repository had **three**
near-copies of "tolerate a BOM when loading JSON", a dozen hand-rolled
`json.dumps({"..."}, ensure_ascii=False, indent=1) + "\n"` blocks with
slightly different punctuation, and exactly **one** write that was atomic
(`rpgmaker/audio.py`, which needed it because a half-written `.ogg` is an
unplayable file).  The rest wrote straight over their target.

That last point is the failure this module exists for.  Every state file in
the translation flow - `pending.jsonl`, the library, `keys.jsonl`, `stats.json`
- is *read back by the next command in the chain*, and an interrupted writer
leaves a truncated file that parses as something plausible: a JSON file cut
mid-object raises, but a JSONL file cut mid-line silently loses exactly the
entries the translator had just spent hours on.  `rawlib.read_jsonl_report`
already carries the scar of the read side of this problem; this is the write
side.

The contract
------------
* :func:`write_text` and :func:`dump_json` **never leave a partially written
  target visible**: bytes go to a temporary file in the *same directory* as
  the target and are published with a single `os.replace`, which is atomic on
  both NTFS and POSIX filesystems.  The temporary file is removed on any
  failure, so a failed write leaves the previous content intact rather than a
  stray `.gt-tmp-*` file next to it.
* The temporary lands beside the target, *not* in the system temp directory.
  `os.replace` across filesystems raises `OSError: [Errno 18] Invalid
  cross-device link`, and `%TEMP%` is very often on another drive than the
  file being written - this is why the temp directory is not a parameter.
* Encoding is always explicit and never locale-dependent.  A UTF-8 file is
  written as UTF-8 with `newline="\\n"` regardless of platform, because these
  files are compared byte-for-byte by the build gates and shared with WSL.
* A **BOM is accepted on read and never written**.  Both halves matter: the
  BOM shows up because these files are hand-edited on Windows, and a writer
  that re-adds one changes the bytes of a file it was only supposed to edit
  (the reason `rpgmaker/plugincompat.py` keeps a comment about exactly this).
* Reading is tolerant, writing is exact.  `load_json` strips a BOM;
  `read_jsonl` skips blank lines and reports a bad line as a *failure* rather
  than silently dropping it (see `translation/rawlib.py` for why an empty
  result must not be distinguishable from a clean one).

Not in scope: `pathlib` adoption (task 6) and log context, which already has
its single entry point in `rpgmaker/logsetup.py` (`logsetup.phase`).
"""

import contextlib
import json
import os
import shutil
import tempfile

__all__ = [
    "BOM",
    "append_jsonl",
    "append_text",
    "backup_file",
    "dump_json",
    "load_json",
    "load_text",
    "read_jsonl",
    "write_text",
]

#: Stripped on read, never written.  Kept in one place because three modules
#: used to spell it as a literal "\ufeff" with three different compare orders.
BOM = "\ufeff"


def _prepare_target(path: str, ensure_parent: bool) -> str:
    """Validate a write target and return it as a `str`.

    `ensure_parent` is not a parameter of `os.replace` but of every call site:
    the alternative is each caller remembering `os.makedirs` first, and the
    ones that forget fail only on a fresh work directory.
    """
    text = os.fspath(path)
    parent = os.path.dirname(text)
    if parent and ensure_parent:
        os.makedirs(parent, exist_ok=True)
    return text


def _atomic(path: str, payload: str, encoding: str, durable: bool) -> None:
    """Publish `payload` at `path` with a single `os.replace`.

    The temp file is created in the target's own directory so the replace
    cannot cross a filesystem boundary, and it inherits the target's mode when
    the target already exists - a rewrite must not silently change permissions
    on someone else's file.

    `durable` additionally fsyncs the bytes before publishing.  Atomicity (a
    reader never sees a truncated file) is unconditional and is what the call
    sites need; crash durability is a different guarantee, and paying a
    `FlushFileBuffers` per file on Windows in a loop over hundreds of game
    data files is a real cost, so it is opt-in.
    """
    directory = os.path.dirname(path) or "."
    handle, tmp = tempfile.mkstemp(dir=directory, prefix=".gt-tmp-",
                                   suffix=os.path.basename(path))
    try:
        with os.fdopen(handle, "w", encoding=encoding, newline="\n") as f:
            f.write(payload)
            if durable:
                f.flush()
                os.fsync(f.fileno())
        with contextlib.suppress(OSError):
            # No existing target (a first write) or a filesystem that refuses
            # chmod: the temp keeps its 0600 default, which is not worth
            # failing a build over.  Windows takes its mode bits from the ACL.
            os.chmod(tmp, os.stat(path).st_mode)
        os.replace(tmp, path)
    except BaseException:
        # `BaseException`, not `Exception`: a KeyboardInterrupt mid-write is
        # exactly the interrupted-writer case this function exists to keep
        # clean, and it must not leave the temporary behind either.
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def load_text(path: str, encoding: str = "utf-8-sig") -> str:
    """Read a UTF-8 text file, tolerating a BOM (`utf-8-sig` strips it).

    `utf-8-sig` is a no-op on a file without one, so this is the safe default
    for the hand-edited files in a work directory.
    """
    with open(path, encoding=encoding, newline="") as handle:
        return handle.read()


def load_json(path: str):
    """Load JSON, tolerating a UTF-8 BOM that Windows editors add.

    Raises `OSError` if unreadable and `json.JSONDecodeError` if malformed;
    neither is swallowed here, because "file is missing" and "file is
    damaged" mean different things to a caller and only the caller can decide
    which is recoverable.
    """
    with open(path, encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_text(path, text, *, encoding: str = "utf-8", ensure_parent: bool = True,
               durable: bool = False) -> str:
    """Write `text` atomically as LF-terminated UTF-8.  Returns the path."""
    target = _prepare_target(path, ensure_parent)
    _atomic(target, text, encoding, durable)
    return target


def append_text(path, text, *, encoding: str = "utf-8",
                ensure_parent: bool = True) -> str:
    """Append `text` to a file, creating it if needed.  Returns the path.

    Deliberately **not** atomic: an append is the one write whose atomicity
    the filesystem already gives us for free below the buffer size, and the
    translation library is appended to once per translated key - copying the
    whole file per key would turn a linear flow into a quadratic one.  Callers
    that need an all-or-nothing rewrite want :func:`write_text` instead.
    """
    target = _prepare_target(path, ensure_parent)
    with open(target, "a", encoding=encoding, newline="\n") as handle:
        handle.write(text)
    return target


def dump_json(path, payload, *, indent: int | None = 1, sort_keys: bool = False,
              trailing_newline: bool | None = None, compact: bool = False,
              ensure_parent: bool = True, durable: bool = False) -> str:
    """Write JSON atomically, in one of the repository's two byte-exact styles.

    * pretty (default): `indent=1`, one trailing newline.
    * `compact=True`: `separators=(",", ":")`, no trailing newline - the style
      of the files that are *shipped inside the game* (`js/plugins.js`,
      `data/System.json`), whose exact bytes several tests pin.

    `ensure_ascii=False` in both: escaping non-ASCII would turn every Chinese
    string into `\\uXXXX` in a file a human is expected to read and diff.
    """
    if compact:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                          sort_keys=sort_keys)
        text = body + "\n" if trailing_newline else body
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=indent,
                          sort_keys=sort_keys)
        if trailing_newline is None or trailing_newline:
            text += "\n"
    return write_text(path, text, ensure_parent=ensure_parent, durable=durable)


def read_jsonl(path) -> list:
    """Read JSONL into a list of objects; a missing file is an empty list.

    A malformed line **raises** `ValueError` naming `path:line`, rather than
    being skipped: a caller that silently gets fewer records than the file has
    cannot tell "nothing to do" from "the file is damaged", which is how a
    broken state file turns into a false pass.  `translation/rawlib.py`
    keeps a tolerant variant for the one file a human appends to by hand.
    """
    if not os.path.isfile(path):
        return []
    records = []
    with open(path, encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError as error:
                raise ValueError(
                    f"{path}:{number}: bad JSON line ({error})") from error
    return records


def append_jsonl(path, record) -> str:
    """Append one object as a single LF-terminated line.  Returns the path."""
    return append_text(path, json.dumps(record, ensure_ascii=False) + "\n")


def backup_file(source, backup_root, rel=None) -> str | None:
    """Copy `source` into `backup_root/rel` once; return the relative path.

    The first copy wins.  The backup exists to make a patch reversible, so the
    value that must survive is the *original* - overwriting it on a second
    pass would replace the pre-patch content with post-patch content and
    silently destroy the only way back.
    """
    relative = rel if rel is not None else os.path.basename(os.fspath(source))
    source = os.fspath(source)
    if not os.path.isfile(source):
        return None
    target = os.path.join(os.fspath(backup_root), relative)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    if not os.path.isfile(target):
        shutil.copyfile(source, target)
    return relative
