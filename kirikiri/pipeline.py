#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic KiriKiri (KAG3) port pipeline: probe -> unpack -> convert -> verify.

One command drives a whole game port, so a new title is "write a profile file,
run `port`" instead of re-deriving the flags every time.  **Every game-specific
value lives in an external profile JSON** - this module holds no game data, no
titles, no lab paths.

Usage:
    python kirikiri/pipeline.py probe   <source-dir> [--write-profile <json>]
    python kirikiri/pipeline.py unpack  <profile.json> [--force]
    python kirikiri/pipeline.py convert <profile.json> [--scenario-only]
    python kirikiri/pipeline.py verify  <build-dir> [--source <src-dir>] [--strict]
    python kirikiri/pipeline.py port    <profile.json> [--force] [--scenario-only]

Profile (JSON object; paths resolve as noted):
    {
      "code": "slot",                       # free-form, local only
      "source": "E:/Games/<title>",          # absolute, or repo-relative
      "archives": "auto",                    # or an explicit priority list
      "engine": ".tools/tyranoscript",       # repo-relative, or absolute
      "src": "src",                          # relative to the profile's dir
      "out": "out",                          # relative to the profile's dir
      "convert": {
        "fonts": ["docs/table/fonts/<font>.otf"],
        "video_dir": "media/webm",
        "state_overrides": "state/gallery-unlocked.json",
        "video_fit": "box",                  # box | fill
        "msg_style": "plate",                # plate | bare
        "title_jump": "first.ks:*start",     # or null (menu entry hidden)
        "asset_dirs": {"bg": "bgimage"},     # source folder -> data folder
        "fast_skip": false,
        "portrait": false
      }
    }

Archive order for ``archives: "auto"`` is the engine's own priority order:
data.xp3, then patch.xp3 / update.xp3, then patch@r<rev>, then patch_append<n>,
then anything else by name.  Each archive is extracted **over** the previous
ones into one tree, which is what the engine does at runtime.
"""

import glob
import json
import logging
import os
import re
import sys
from typing import Annotated, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
sys.path.append(REPO_ROOT)

from kirikiri import xp3tool  # noqa: E402
from kirikiri.ks_extract import load_ks  # noqa: E402
from rpgmaker import cliutil  # noqa: E402

log = logging.getLogger("kirikiri.pipeline")

DEFAULT_ENGINE = os.path.join(".tools", "tyranoscript")
FONT_DIR = os.path.join("docs", "table", "fonts")
INDEX_FILE = "unpack-index.txt"

#: asset refs are relative to the build's data/ dir and usually omit the
#: extension; try the usual asset/scenario ones.
_REF_EXTS = ("", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ogg",
             ".wav", ".opus", ".m4a", ".mp3", ".mp4", ".webm", ".ks", ".tjs",
             ".txt", ".csv", ".asd", ".json")

#: basename index of one build, valid for a single missing_refs() run
_BASENAME_CACHE = None

#: asset references: KAG3 dialects use ``storage=`` for background/sound tags
#: and ``file=`` for the @-tag short form (`@cg file=BG11a02`, `@playBgm
#: file=BGM25`) - both must be checked, or a whole dialect goes unverified.
#: Values may be quoted or bare (`[cg file=BG11a02 zoom=32]`), and the @-tag
#: form is bare whenever the value has no spaces.
_REF_ATTR = re.compile(
    r'\b(?:storage|file)\s*=\s*(?:"([^"]*)"|([^\s\],\]]+))')
_DYNAMIC = re.compile(r"[&%$@{}\[\]*]")


# ---------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------

def list_archives(source):
    """Every *.xp3 in `source` (unsorted)."""
    try:
        names = os.listdir(source)
    except OSError as exc:
        raise FileNotFoundError("cannot list %s (%s)" % (source, exc))
    return [n for n in names if n.lower().endswith(".xp3")]


def archive_sort_key(name):
    """Priority rank of one archive name (lower = extracted first)."""
    low = name.lower()
    if low == "data.xp3":
        return (0, 0, "")
    if low in ("patch.xp3", "update.xp3"):
        return (1, 0, low)
    m = re.fullmatch(r"patch@r(\d+)\.xp3", low)
    if m:
        return (2, int(m.group(1)), "")
    m = re.fullmatch(r"patch_append(\d+)\.xp3", low)
    if m:
        return (3, int(m.group(1)), "")
    return (4, 0, low)


def order_archives(names):
    """Archive names in engine priority order (data first, patches over it)."""
    return sorted(names, key=archive_sort_key)


def probe_archive(path):
    """Inspect one archive: entries, name-extension ratio, usability verdict."""
    info = {"path": path, "name": os.path.basename(path),
            "size": os.path.getsize(path)}
    try:
        entries = xp3tool.open_xp3(path)
    except Exception as exc:                    # noqa: BLE001 - report verbatim
        info.update(verdict="error", detail=str(exc))
        return info
    reason = xp3tool.protected_variant_reason(path, entries)
    info.update(entries=len(entries),
                ext_ratio=round(xp3tool.name_extension_ratio(entries), 4),
                verdict="protected" if reason else "ok",
                detail=reason or "")
    return info


def probe_source(source):
    """probe_archive for every archive of a source dir, in engine order."""
    return [probe_archive(os.path.join(source, n))
            for n in order_archives(list_archives(source))]


def usable_archives(source):
    """(usable names, refusals) - refusals are (name, reason) pairs."""
    usable, refusals = [], []
    for info in probe_source(source):
        if info["verdict"] == "ok":
            usable.append(info["name"])
        elif info["verdict"] == "protected":
            refusals.append((info["name"], info["detail"]))
        else:
            refusals.append((info["name"],
                            "%s: %s" % (info["name"], info.get("detail", ""))))
    return usable, refusals


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def load_profile(path):
    """Read a profile and resolve its paths (see the module docstring)."""
    with open(path, encoding="utf-8-sig") as f:
        profile = json.load(f)
    slot = os.path.dirname(os.path.abspath(path))
    profile["_slot"] = slot

    def repo_path(value):
        if not value:
            return None
        # normpath keeps the reported/resolved path in one separator style even
        # when a profile mixes "media/webm" with an absolute root.
        return os.path.normpath(value if os.path.isabs(value)
                                else os.path.join(REPO_ROOT, value))

    def slot_path(value, default):
        value = value or default
        return (os.path.normpath(value) if os.path.isabs(value)
                else os.path.normpath(os.path.join(slot, value)))

    profile["_source"] = repo_path(profile.get("source"))
    profile["_engine"] = repo_path(profile.get("engine") or DEFAULT_ENGINE)
    profile["_src"] = slot_path(profile.get("src"), "src")
    profile["_out"] = slot_path(profile.get("out"), "out")
    profile["_archives"] = profile.get("archives") or "auto"
    conv = dict(profile.get("convert") or {})
    # Fill the documented defaults so a resolved profile is complete (a profile
    # only has to name what differs from the defaults).
    conv.setdefault("video_fit", "box")
    conv.setdefault("msg_style", "plate")
    conv.setdefault("title_jump", None)
    conv.setdefault("fast_skip", False)
    conv.setdefault("portrait", False)
    conv.setdefault("asset_dirs", None)
    for key in ("video_dir", "state_overrides"):
        conv[key] = repo_path(conv.get(key))
    if conv.get("fonts"):
        conv["fonts"] = [repo_path(p) for p in conv["fonts"]]
    profile["_convert"] = conv
    return profile


def default_fonts():
    """Project font policy: the packaged font under docs/table/fonts/.

    Missing local data is a WARN, never a silent no-op (AGENTS: mandatory steps
    that need gitignored data must say so).
    """
    font_dir = os.path.join(REPO_ROOT, FONT_DIR)
    found = sorted(glob.glob(os.path.join(font_dir, "*.otf"))
                   + glob.glob(os.path.join(font_dir, "*.ttf")))
    if not found:
        log.warning("no font under %s - the unified-font policy is NOT applied "
                    "(see docs/table/font_rollback.md)", FONT_DIR)
        return None
    return found[:1]


def archive_order(profile):
    """The archive list to unpack, honouring an explicit profile override."""
    explicit = profile["_archives"]
    if explicit != "auto":
        return list(explicit)
    return order_archives(list_archives(profile["_source"]))


# ---------------------------------------------------------------------------
# Unpack
# ---------------------------------------------------------------------------

def unpack(profile, force=False):
    """Extract every archive over one tree; returns (files, bytes) or None."""
    source, dest = profile["_source"], profile["_src"]
    names = archive_order(profile)
    if not names:
        log.error("%s: no *.xp3 archive found", source)
        return None
    if os.path.isdir(dest) and os.listdir(dest) and not force:
        log.info("%s already unpacked, keeping it (--force to redo)", dest)
        return _tree_size(dest)

    usable, refusals = usable_archives(source)
    if refusals:
        for name, reason in refusals:
            log.error("%s", reason)
        log.error("refusing to unpack %s: %d archive(s) are unusable "
                  "(pass --force only to inspect them, not to port)",
                  source, len(refusals))
        return None

    os.makedirs(dest, exist_ok=True)
    lines = ["# unpack order (engine priority: later archives override earlier)",
             "# %s" % source]
    total_files = total_bytes = 0
    for name in names:
        path = os.path.join(source, name)
        files, size = xp3tool.extract_all(path, dest)
        total_files += files
        total_bytes += size
        lines.append("%12d B  %6d entries  %s" % (size, files, name))
        log.info("%s: %d entries, %.1f MB", name, files, size / 1e6)
    with open(os.path.join(profile["_slot"], INDEX_FILE), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    log.info("unpacked %d entries (%d files in the tree) from %d archive(s)",
             total_files, _tree_size(dest)[0], len(names))
    return _tree_size(dest)


def _tree_size(root):
    files = size = 0
    for base, _dirs, names in os.walk(root):
        for name in names:
            files += 1
            try:
                size += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return files, size


# ---------------------------------------------------------------------------
# Convert
# ---------------------------------------------------------------------------

def convert_game(profile, scenario_only=False):
    """Run the KAG3 -> Tyrano converter with the profile's options."""
    from kirikiri.kag import convert       # lazy: keeps probing import-free

    conv = profile["_convert"]
    fonts = conv.get("fonts") or default_fonts()
    out_dir = profile["_out"]
    os.makedirs(os.path.dirname(out_dir) or ".", exist_ok=True)
    log.info("converting %s -> %s", profile["_src"], out_dir)
    return convert(
        unpacked=profile["_src"],
        engine=profile["_engine"],
        out_dir=out_dir,
        fonts=fonts,
        video_dir=conv.get("video_dir"),
        state_overrides_path=conv.get("state_overrides"),
        video_fit=conv.get("video_fit") or "box",
        msg_style=conv.get("msg_style") or "plate",
        title_jump=conv.get("title_jump"),
        asset_dirs=conv.get("asset_dirs"),
        fast_skip=bool(conv.get("fast_skip")),
        portrait=bool(conv.get("portrait")),
        scenario_only=bool(scenario_only or conv.get("scenario_only")),
    )


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def scenario_files(build):
    return sorted(glob.glob(os.path.join(build, "data", "scenario", "**", "*.ks"),
                            recursive=True))


def storage_refs(build):
    """{ref: [file:line, ...]} for every static asset reference (storage/file)."""
    refs = {}
    for path in scenario_files(build):
        try:
            text, _enc = load_ks(path)
        except OSError as exc:
            log.warning("%s: unreadable (%s)", path, exc)
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            for m in _REF_ATTR.finditer(line):
                ref = (m.group(1) or m.group(2) or "").strip()
                if not ref or _DYNAMIC.search(ref):
                    continue                    # runtime-computed target
                refs.setdefault(ref, []).append(
                    "%s:%d" % (
                        os.path.relpath(path, build).replace(os.sep, "/"), idx))
    return refs


def _resolve_with_exts(base, ref):
    """True when `ref` (extension usually omitted) exists somewhere under base."""
    target = os.path.join(base, *ref.split("/"))
    return any(os.path.exists(target + ext) for ext in _REF_EXTS)


def _basename_index(data_dir):
    """{lowercased file name: True} for the whole build tree (cached)."""
    global _BASENAME_CACHE
    if _BASENAME_CACHE is None:
        index = set()
        for _base, _dirs, names in os.walk(data_dir):
            index.update(n.lower() for n in names)
        _BASENAME_CACHE = index
    return _BASENAME_CACHE


def resolve_ref(build, ref):
    """True when an asset reference resolves under the build's data/ dir.

    Path-shaped refs (`bgimage/x`, `bgimage/x.png`) are resolved as paths; a
    bare id (`BG11a02`, `RIA000001`) is accepted when a file of that name with
    any known extension exists anywhere in the tree, because those dialects map
    ids to folders through their own tables (`*.csv` / `*.ams`) which a build
    check cannot replay.
    """
    data_dir = os.path.join(build, "data")
    if _resolve_with_exts(data_dir, ref):
        return True
    if "/" in ref or os.path.splitext(ref)[1]:
        return False
    index = _basename_index(data_dir)
    return any((ref + ext).lower() in index for ext in _REF_EXTS if ext)


def missing_refs(build, source=None):
    """Refs that do not resolve; a source tree splits them into conversion gaps.

    Returns (missing, gaps) where `gaps` are the refs the *source* game has but
    the build does not (i.e. the converter dropped an asset), while the rest are
    dangling in the original game too.
    """
    global _BASENAME_CACHE
    _BASENAME_CACHE = None
    missing, gaps = [], []
    for ref, where in sorted(storage_refs(build).items()):
        if resolve_ref(build, ref):
            continue
        missing.append({"ref": ref, "where": where[:4]})
        if source and _resolve_with_exts(source, ref):
            gaps.append(ref)
    return missing, gaps


def verify_build(build, source=None, strict=False):
    """Structural + translation-status check of a converted build.

    Hard failures (always non-zero): missing index.html, no scenarios, iscript
    JavaScript that does not parse.  Warnings (non-zero only with `strict`):
    kana left in display text (expected before translation), unresolved storage
    references, refs the source has but the build lost.
    """
    from tools import check_iscript_js, qc_ks_kana

    problems = []
    if not os.path.isfile(os.path.join(build, "index.html")):
        problems.append("no index.html in %s" % build)
    scenarios = scenario_files(build)
    if not scenarios:
        problems.append("no data/scenario/**/*.ks in %s" % build)
    for problem in problems:
        log.error("%s", problem)
    if problems:
        return 1

    scenario_root = os.path.join(build, "data", "scenario")
    total_lines, kana_lines = qc_ks_kana.scan_tree(scenario_root)
    checked, js_problems = check_iscript_js.scan_tree(scenario_root, limit=0)

    missing, gaps = missing_refs(build, source)
    log.info("verify: %d scenarios, %d display lines (%d with kana), "
             "%d iscript blocks, %d distinct storage refs",
             len(scenarios), total_lines, kana_lines, checked,
             len(storage_refs(build)))
    if kana_lines:
        log.warning("%d display line(s) still carry kana "
                    "(untranslated or half-translated)", kana_lines)
    for item in missing[:20]:
        log.warning("missing storage ref %s (%s)", item["ref"],
                    ", ".join(item["where"]))
    if len(missing) > 20:
        log.warning("... and %d more missing refs", len(missing) - 20)
    if source:
        if gaps:
            log.warning("%d ref(s) exist in the source but not in the build "
                        "(conversion gaps): %s", len(gaps), ", ".join(gaps[:10]))
        else:
            log.info("no conversion gap: every source-side ref resolves")

    hard = bool(js_problems)
    soft = bool(kana_lines or missing)
    if hard or (strict and soft):
        log.error("verify failed (%s)", "iscript JS" if hard else "strict")
        return 1
    log.info("verify OK%s", "" if not soft else " (with warnings)")
    return 0


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_probe(source: Annotated[str, cliutil.Argument(help="game folder holding *.xp3")],
              write_profile: Annotated[Optional[str], cliutil.Option(
                  "--write-profile", metavar="JSON",
                  help="write a profile skeleton for this game")] = None,
              as_json: Annotated[bool, cliutil.Option(
                  "--json", help="print the probe result as JSON")] = False,
              verbose: cliutil.Verbose = False,
              quiet: cliutil.Quiet = False,
              log_file: cliutil.LogFile = None) -> int:
    """Report which archives a game has and whether they can be unpacked."""
    cliutil.setup_logging(verbose, quiet, log_file)
    if not os.path.isdir(source):
        return cliutil.fail("not a folder: %s" % source, 2)
    try:
        infos = probe_source(source)
    except FileNotFoundError as exc:
        return cliutil.fail(str(exc))
    if not infos:
        return cliutil.fail("no *.xp3 archive found in %s" % source)

    if as_json:
        print(json.dumps({"source": source, "archives": infos},
                         ensure_ascii=False, indent=2))
    else:
        log.info("%s: %d archive(s)", source, len(infos))
        for info in infos:
            if info["verdict"] == "ok":
                log.info("  %-28s ok        %5d entries, ext(%.0f%%) %.1f MB",
                         info["name"], info["entries"],
                         info["ext_ratio"] * 100, info["size"] / 1e6)
            elif info["verdict"] == "protected":
                log.warning("  %-28s PROTECTED (cannot be a port input)",
                            info["name"])
            else:
                log.error("  %-28s unreadable: %s", info["name"],
                          info.get("detail", ""))
    if write_profile:
        skeleton = {
            "code": os.path.basename(os.path.normpath(source)),
            "source": source.replace("\\", "/"),
            "archives": "auto",
            "engine": DEFAULT_ENGINE.replace("\\", "/"),
            "src": "src",
            "out": "out",
            "convert": {
                "fonts": [os.path.join(FONT_DIR, "<font>.otf").replace("\\", "/")],
                "video_dir": None,
                "state_overrides": None,
                "video_fit": "box",
                "msg_style": "plate",
                "title_jump": None,
                "fast_skip": False,
                "portrait": False,
            },
        }
        with open(write_profile, "w", encoding="utf-8", newline="\n") as f:
            json.dump(skeleton, f, ensure_ascii=False, indent=2)
            f.write("\n")
        log.info("wrote profile skeleton %s", write_profile)

    bad = [i for i in infos if i["verdict"] != "ok"]
    return 0 if not bad else 1


def cmd_unpack(profile: Annotated[str, cliutil.Argument(help="profile JSON")],
               force: Annotated[bool, cliutil.Option(
                   "--force", help="re-extract even when src/ already exists")] = False,
               verbose: cliutil.Verbose = False,
               quiet: cliutil.Quiet = False,
               log_file: cliutil.LogFile = None) -> int:
    """Unpack every archive of a game into the profile's src/ tree."""
    cliutil.setup_logging(verbose, quiet, log_file)
    prof = _read(profile)
    if prof is None:
        return 2
    return 0 if unpack(prof, force=force) is not None else 1


def cmd_convert(profile: Annotated[str, cliutil.Argument(help="profile JSON")],
                scenario_only: Annotated[bool, cliutil.Option(
                    "--scenario-only", help="re-run the scenario pass only")] = False,
                verbose: cliutil.Verbose = False,
                quiet: cliutil.Quiet = False,
                log_file: cliutil.LogFile = None) -> int:
    """Convert the unpacked tree into a TyranoScript project (profile's out/)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    prof = _read(profile)
    if prof is None:
        return 2
    if not os.path.isdir(prof["_src"]):
        return cliutil.fail("not unpacked yet: %s (run unpack first)" % prof["_src"])
    return convert_game(prof, scenario_only=scenario_only)


def cmd_verify(build: Annotated[str, cliutil.Argument(help="built Tyrano folder")],
               source: Annotated[Optional[str], cliutil.Option(
                   "--source", metavar="DIR",
                   help="unpacked source tree, to tell conversion gaps apart")] = None,
               strict: Annotated[bool, cliutil.Option(
                   "--strict", help="warnings fail too")] = False,
               verbose: cliutil.Verbose = False,
               quiet: cliutil.Quiet = False,
               log_file: cliutil.LogFile = None) -> int:
    """Check a converted build: structure, kana, storage refs, iscript JS."""
    cliutil.setup_logging(verbose, quiet, log_file)
    if not os.path.isdir(build):
        return cliutil.fail("not a folder: %s" % build, 2)
    return verify_build(build, source=source, strict=strict)


def cmd_port(profile: Annotated[str, cliutil.Argument(help="profile JSON")],
             force: Annotated[bool, cliutil.Option(
                 "--force", help="re-unpack even when src/ exists")] = False,
             skip_unpack: Annotated[bool, cliutil.Option(
                 "--skip-unpack", help="reuse the existing src/ tree")] = False,
             scenario_only: Annotated[bool, cliutil.Option(
                 "--scenario-only", help="re-run the scenario pass only")] = False,
             strict: Annotated[bool, cliutil.Option(
                 "--strict", help="verify warnings fail too")] = False,
             verbose: cliutil.Verbose = False,
             quiet: cliutil.Quiet = False,
             log_file: cliutil.LogFile = None) -> int:
    """Unpack, convert and verify one game in a single run."""
    cliutil.setup_logging(verbose, quiet, log_file)
    prof = _read(profile)
    if prof is None:
        return 2
    if not skip_unpack:
        if unpack(prof, force=force) is None:
            return 1
    elif not os.path.isdir(prof["_src"]):
        return cliutil.fail("no source tree at %s" % prof["_src"])
    code = convert_game(prof, scenario_only=scenario_only)
    if code:
        return code
    return verify_build(prof["_out"], source=prof["_src"], strict=strict)


def _read(profile_path):
    """load_profile with a friendly failure; None = bad profile (exit 2)."""
    try:
        return load_profile(profile_path)
    except FileNotFoundError:
        cliutil.fail("no such profile: %s" % profile_path, 2)
        return None
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        cliutil.fail("%s: bad profile (%s)" % (profile_path, exc), 2)
        return None


app = cliutil.app(help=__doc__)
app.command(name="probe")(cmd_probe)
app.command(name="unpack")(cmd_unpack)
app.command(name="convert")(cmd_convert)
app.command(name="verify")(cmd_verify)
app.command(name="port")(cmd_port)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="pipeline.py")


if __name__ == "__main__":
    raise SystemExit(main())
