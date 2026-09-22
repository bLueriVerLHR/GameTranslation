#!/usr/bin/env python3
"""fontpolicy.py - whether the project font is applied, and on what evidence.

Split out of the former god-module ``rpgmaker/config.py`` (PLAN Phase 4).

:mod:`rpgmaker.assets` answers "which file".  This module answers the two
questions that must not be answered silently:

* **Should it be applied at all?**  Three policies, from
  ``docs/reference/local-layout.md`` section 5:

  ``required``
      the project standard CJK font is mandatory - this is the default for a
      build we translated ourselves and therefore built ourselves.  A missing
      font, a missing manifest or a checksum mismatch raises, so a
      half-fonted build can never be shipped by accident.
  ``auto``
      the game already ships a translation, so its own font is kept.  The
      manifest is inspected and reported on, but **nothing is written**; the
      only outcome is a warning.
  ``preserve``
      do not even look.  Neither the manifest nor the font directory is
      touched, so this policy cannot fail and cannot modify anything.

* **Is the registered asset the file the manifest describes?**  The manifest
  in ``.asset/fonts/manifest.json`` is the only authority for the logical id
  used by policies and CLI flags, and its ``sha256`` is what makes a swapped
  or truncated font file detectable (schema:
  ``docs/reference/schema/font-manifest.schema.json``).

Validation is hand-written rather than delegated to ``jsonschema``: the shape
is small and fixed, and a new runtime dependency to check six string fields
would be a poor trade (PLAN Phase 4 task 5 says the same about the machine
config).  The JSON schema stays the published contract for the file's author;
this module is what actually enforces it.

Implementation detail that matters: a font name is never a filename in the
repo.  The directory comes from the single private-layout mapping in
:mod:`rpgmaker.settings`, and the *id* comes from the manifest, so renaming a
font file on disk does not require a code change.
"""
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .settings import private_path

__all__ = [
    "DEFAULT_FONT_ID",
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "POLICIES",
    "FontDecision",
    "FontPolicyError",
    "FontRecord",
    "Manifest",
    "decide_font",
    "explicit_font",
    "load_manifest",
    "verify_font",
]

log = logging.getLogger("rpgmaker.fontpolicy")

#: Policy names accepted by ``--font-policy``.
POLICIES = ("required", "auto", "preserve")

#: The policy a build we translated ourselves uses unless told otherwise.
DEFAULT_POLICY = "required"

#: Logical id of the project standard Simplified-Chinese font.  This is a
#: *logical* name; the file it points at is a local private asset.
DEFAULT_FONT_ID = "common-zh"

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1

_REQUIRED_FIELDS = ("id", "file", "family", "purpose", "license", "sha256")
_OPTIONAL_FIELDS = ("postscript_name", "coverage", "size_bytes")
_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FontPolicyError(RuntimeError):
    """The policy demand cannot be met, so the caller must stop.

    Raised only for ``required``.  The message always names the file or the
    field that is wrong and where the font is expected, because the operator's
    next action is to go and provision it.
    """


@dataclass(frozen=True)
class FontRecord:
    """One validated manifest entry, with its resolved path."""

    id: str
    file: str
    family: str
    purpose: str
    license: str
    sha256: str
    path: Path
    postscript_name: str = ""
    coverage: dict = field(default_factory=dict)
    size_bytes: int = 0

    @property
    def covers_gb_simplified(self):
        """Tri-state: True, False, or None when the manifest does not say.

        ``None`` is reported as "unknown" rather than assumed True - the whole
        point of the field is to catch a font that renders Chinese as boxes.
        """
        value = self.coverage.get("covers_gb_simplified")
        return value if isinstance(value, bool) else None


@dataclass(frozen=True)
class Manifest:
    """The parsed font manifest, or why it could not be used.

    ``problems`` is empty exactly when the file is present, readable, of a
    known schema version, and every entry is well formed.  Each problem is a
    self-contained sentence with the offending field or line in it.
    """

    path: Path
    present: bool
    problems: tuple = ()
    fonts: dict = field(default_factory=dict)
    version: int = 0

    @property
    def ok(self):
        return self.present and not self.problems

    def get(self, font_id):
        return self.fonts.get(font_id)

    def describe(self):
        """One-line summary for ``doctor`` and for warning text."""
        if not self.present:
            return f"{self.path} not found"
        if self.problems:
            return "{} invalid: {}".format(self.path, "; ".join(self.problems))
        return "%s ok (%d font(s): %s)" % (
            self.path, len(self.fonts), ", ".join(sorted(self.fonts)) or "-")


def _fonts_dir(fonts_dir=None):
    return Path(fonts_dir) if fonts_dir else private_path("fonts")


def _entry_string_problems(where, entry):
    """Required fields present as non-empty strings + no unknown fields."""
    problems = [f"{where}.{name} is missing or not a non-empty string"
                for name in _REQUIRED_FIELDS
                if not isinstance(entry.get(name), str)
                or not entry[name].strip()]
    problems.extend(f"{where}.{name} is not a known field (additionalProperties "
                    "is false in the schema)"
                    for name in entry
                    if name not in _REQUIRED_FIELDS
                    and name not in _OPTIONAL_FIELDS)
    return problems


def _entry_format_problems(where, entry):
    """Field shapes: id pattern, sha256 hex, bare filename, positive size."""
    problems = []
    font_id = entry.get("id")
    if isinstance(font_id, str) and font_id and not _ID_RE.match(font_id):
        problems.append(f"{where}.id {font_id!r} does not match the logical-id pattern "
                        "(lowercase words joined by '-')")
    sha = entry.get("sha256")
    if isinstance(sha, str) and sha and not _SHA256_RE.match(sha):
        problems.append(f"{where}.sha256 {sha!r} is not lowercase hex sha256")
    filename = entry.get("file")
    if isinstance(filename, str) and filename and (
            Path(filename).is_absolute() or "/" in filename or "\\" in filename):
        problems.append(f"{where}.file {filename!r} must be a bare filename relative to "
                        "the font directory")
    size = entry.get("size_bytes")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool)
                             or size < 1):
        problems.append(f"{where}.size_bytes must be a positive integer")
    return problems


def _entry_coverage_problems(where, coverage):
    """The optional `coverage` object: known keys, boolean values."""
    if coverage is None:
        return []
    if not isinstance(coverage, dict):
        return [f"{where}.coverage is not an object"]
    return [f"{where}.coverage.{name} is not a boolean"
            for name in ("covers_gb_simplified", "covers_japanese_kana")
            if coverage.get(name) is not None
            and not isinstance(coverage[name], bool)]


def _entry_problems(index, entry):
    """Validate one manifest entry; returns a list of problem strings."""
    where = "fonts[%d]" % index
    if not isinstance(entry, dict):
        return [f"{where} is not an object"]
    problems = _entry_string_problems(where, entry)
    problems.extend(_entry_format_problems(where, entry))
    problems.extend(_entry_coverage_problems(where, entry.get("coverage")))
    return problems


def load_manifest(fonts_dir=None):
    """Read and validate ``.asset/fonts/manifest.json``; never raises.

    Callers decide whether an unusable manifest is fatal: it is for the
    ``required`` policy and merely reportable for ``auto``.  Returning a
    report instead of raising is what lets ``doctor`` describe the problem
    without a traceback.
    """
    path = _fonts_dir(fonts_dir) / MANIFEST_NAME
    if not path.is_file():
        return Manifest(path=path, present=False)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        return Manifest(path=path, present=True,
                        problems=(f"cannot be read ({error})",))
    except ValueError as error:
        return Manifest(path=path, present=True,
                        problems=(f"is not valid JSON ({error})",))

    problems = []
    if not isinstance(raw, dict):
        return Manifest(path=path, present=True,
                        problems=("the root is not an object",))
    version = raw.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        problems.append("schema_version is missing or not an integer")
        version = 0
    elif version != MANIFEST_SCHEMA_VERSION:
        problems.append("schema_version %s is not the supported version %d"
                        % (version, MANIFEST_SCHEMA_VERSION))
    entries = raw.get("fonts")
    fonts = {}
    if not isinstance(entries, list):
        problems.append("fonts is missing or not an array")
        entries = []
    for index, entry in enumerate(entries):
        entry_problems = _entry_problems(index, entry)
        problems.extend(entry_problems)
        if isinstance(entry, dict) and not entry_problems:
            font_id = entry["id"]
            if font_id in fonts:
                problems.append("fonts[%d].id %r is a duplicate"
                                % (index, font_id))
                continue
            fonts[font_id] = FontRecord(
                id=font_id, file=entry["file"], family=entry["family"],
                purpose=entry["purpose"], license=entry["license"],
                sha256=entry["sha256"],
                path=path.parent / entry["file"],
                postscript_name=entry.get("postscript_name") or "",
                coverage=entry.get("coverage") or {},
                size_bytes=entry.get("size_bytes") or 0)
    return Manifest(path=path, present=True, problems=tuple(problems),
                    fonts=fonts, version=version)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_font(record, check_checksum=True):
    """Check that a manifest entry's file is really on disk and unchanged.

    Returns ``None`` when the record is usable, else a problem sentence naming
    the file.  A checksum mismatch means the font was replaced or truncated,
    which is exactly the case the manifest exists to catch - so it is reported
    like a missing file, not downgraded to a note.
    """
    if not record.path.is_file():
        return f"font file missing: {record.path} (manifest id {record.id!r})"
    if not check_checksum:
        return None
    try:
        actual = _sha256(record.path)
    except OSError as error:
        return f"cannot read font file {record.path} ({error})"
    if actual != record.sha256:
        return (f"checksum mismatch for {record.path} (manifest id {record.id!r}): manifest says "
                f"{record.sha256}, the file is {actual} - re-register the font or restore the "
                "file")
    return None


@dataclass(frozen=True)
class FontDecision:
    """What the bake step should do about the project font, and why.

    ``apply`` False with ``warnings`` is the honest outcome of ``auto``: the
    build proceeds with the game's own font and the operator is told what was
    not applied.  A ``required`` demand that cannot be met never gets here - it
    raises instead, because a warning that a delivery-critical step did nothing
    is the silent degradation the project rules forbid.

    ``source`` says which of the resolution steps answered, so a build log
    shows *why* this font was chosen: an explicit path, the operator's
    environment/override file, or the registered manifest.
    """

    policy: str
    apply: bool
    font_id: str = ""
    path: str = ""
    source: str = ""
    warnings: tuple = ()
    detail: str = ""

    @property
    def files(self):
        return (self.path,) if self.path else ()


def _resolve(policy, font_id, fonts_dir, check_checksum):
    """Shared body of :func:`decide_font`; returns ``(record, problem)``."""
    manifest = load_manifest(fonts_dir)
    if not manifest.ok:
        return None, manifest.describe()
    record = manifest.get(font_id)
    if record is None:
        known = ", ".join(sorted(manifest.fonts)) or "(none)"
        return None, (f"font id {font_id!r} is not registered in {manifest.path} (registered: {known})")
    problem = verify_font(record, check_checksum=check_checksum)
    if problem:
        return None, problem
    return record, None


def _operator_choice():
    """A font the operator named outside the manifest, or ``(None, '')``.

    ``CJK_FONT_PATH`` and the local font-paths file are explicit operator
    configuration, so they outrank the registered directory - and being
    outside the manifest they carry no checksum to verify.  The manifest stays
    the authority for the directory it describes.
    """
    from . import assets

    env = os.environ.get("CJK_FONT_PATH")
    if env and os.path.isfile(env):
        return env, "CJK_FONT_PATH"
    paths = assets.read_font_paths()
    if paths:
        return paths[0], "the local font-paths file"
    return None, ""


def decide_font(policy=DEFAULT_POLICY, font_id=DEFAULT_FONT_ID,
                fonts_dir=None, font_path=None, check_checksum=True):
    """Apply the font policy; raises :class:`FontPolicyError` for ``required``.

    Only ``required`` can return ``apply=True``.  ``auto`` is report-only by
    definition: it describes the font it *would* use and warns when the
    manifest cannot vouch for Chinese coverage, but it never writes a file, so
    the policy cannot silently replace a font a shipped translation depends on.

    Resolution order for the two working policies: explicit ``font_path`` ->
    the operator's environment/override file -> the registered manifest.  A
    ``required`` demand that none of them satisfies raises instead of
    warning, because a delivery-critical step that did nothing must not look
    like success.
    """
    if policy not in POLICIES:
        raise ValueError("unknown font policy {!r} (expected one of {})".format(policy, ", ".join(POLICIES)))
    if policy == "preserve":
        return FontDecision(
            policy=policy, apply=False,
            detail="preserve: the game's own font is kept and no font file is "
                   "inspected or written")

    if font_path:
        if Path(font_path).is_file():
            return _report(policy, FontDecision(
                policy=policy, apply=True, path=str(font_path),
                source="explicit path",
                detail=f"applying the font given on the command line: {font_path}"))
        problem = f"the given font file does not exist: {font_path}"
        return _unsatisfied(policy, problem, fonts_dir)

    chosen, source = _operator_choice()
    if chosen:
        return _report(policy, FontDecision(
            policy=policy, apply=True, path=chosen, source=source,
            detail=f"applying the font named by {source}: {chosen}"))

    record, problem = _resolve(policy, font_id, fonts_dir, check_checksum)
    if problem is not None:
        return _unsatisfied(policy, problem, fonts_dir)
    warnings = _coverage_warnings(record)
    return _report(policy, FontDecision(
        policy=policy, apply=True, font_id=record.id, path=str(record.path),
        source="registered manifest", warnings=warnings,
        detail=f"applying registered font {record.id!r} from {record.path}"))


def _coverage_warnings(record):
    """Warn when the manifest cannot vouch for the glyphs a Chinese build needs.

    ``covers_gb_simplified`` is tri-state on purpose: ``None`` (the manifest
    does not say) is reported as unknown rather than assumed good, because the
    symptom of getting it wrong is every Chinese character rendering as a box.
    """
    if record.covers_gb_simplified is None:
        message = (f"font {record.id!r} does not declare coverage.covers_gb_simplified - "
                   "Chinese rendering cannot be vouched for")
    elif record.covers_gb_simplified is False:
        message = (f"font {record.id!r} declares coverage.covers_gb_simplified: false - "
                   "Chinese characters may render as boxes")
    else:
        return ()
    log.warning("%s", message)
    return (message,)


def _report(policy, decision):
    """Turn an applicable decision into what the *policy* allows.

    ``auto`` keeps everything the resolution found - the path is useful in a
    report and in ``doctor`` - but drops the licence to write.
    """
    if policy == "required":
        return decision
    detail = (f"auto: {decision.detail}, but the game's own font is kept (auto is "
              "report-only)")
    return FontDecision(policy=policy, apply=False, font_id=decision.font_id,
                        path=decision.path, source=decision.source,
                        warnings=tuple(decision.warnings) + (detail,),
                        detail=detail)


def _unsatisfied(policy, problem, fonts_dir):
    """No usable font: fatal for ``required``, a warning for ``auto``."""
    if policy == "required":
        raise FontPolicyError(
            f"font policy 'required' cannot be satisfied: {problem}. Register the "
            f"font in {_fonts_dir(fonts_dir)} (see docs/reference/local-layout.md sections 4-5), "
            "name one with --cjk-font, set CJK_FONT_PATH, or run with "
            "--font-policy auto/preserve to keep the game's own font.")
    warning = (f"font policy 'auto': the project font was not applied - {problem}")
    log.warning("%s", warning)
    return FontDecision(policy=policy, apply=False, warnings=(warning,),
                        detail=warning)


def explicit_font(path):
    """A decision for an explicitly given font file, skipping the manifest.

    Naming a file on the command line is an explicit override; validating it
    against a manifest written for a different path would only produce a
    misleading failure.  Existence is still checked, because a typo's next
    symptom would otherwise be a game that silently kept its old font.
    """
    if not path or not Path(path).is_file():
        raise FontPolicyError(f"font file not found: {path!r}")
    return FontDecision(policy="explicit", apply=True, path=str(path),
                        source="explicit path",
                        detail=f"applying explicitly given font {path}")
