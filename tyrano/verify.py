#!/usr/bin/env python3
"""Verify a built TyranoScript JoiPlay folder.

Checks the essentials for the game to actually run in JoiPlay / a browser:
  - index.html + tyrano/ engine + data/ present
  - save backend is webstorage (not the Node-fs file backend)
  - scenario .ks references resolve to existing audio files
    (after the ogg conversion only .ogg refs may point at .ogg files)
  - every referenced audio file exists on disk (source-aware optional)
  - every image/video reference resolves with the exact case it is written
    in (Android file systems are case-sensitive, Windows is not)
  - PNG dimensions within the Android WebGL 4096 limit
"""
import logging
import os
import re
import struct
from typing import Annotated

from rpgmaker import cliutil, platform
from rpgmaker import constants as rpg_constants

from .tyrano_extract import load_ks, split_tag_attrs

log = logging.getLogger("tyrano.verify")

AUDIO_REF = re.compile(r'\b(?:storage|clickse|enterse|decidese|cancelse)=(")([^"]*\.(?:mp3|ogg|m4a|wav))(")')
AUDIO_DIRS = ("data/bgm", "data/sound")

# --- image / video references -------------------------------------------
# The pipeline never rewrites these, but a dangling or wrong-case reference
# breaks the build just the same: Android/JoiPlay file systems are
# case-sensitive, so a reference Windows happily resolves
# (storage="Chara/1/Saya1-1.png" against chara/1/saya1-1.png) is a 404 on the
# phone while `verify` stayed green.  Measured on a real Electron-packaged
# TyranoBuilder game: 341 asset references, every one of which resolved to a
# single consistent folder per tag.
#
# Values that already carry a path ("data/..." or "./data/...") are used as
# written; a bare name resolves against the tag's own asset folder.
TAG_ASSET_DIR = {
    "bg": "data/bgimage",
    "image": "data/image",
    "graph": "data/image",
    "button": "data/image",
    "tb_replay_image_button": "data/image",
    "chara_new": "data/fgimage",
    "chara_show": "data/fgimage",
    "chara_mod": "data/fgimage",
    "chara_face": "data/fgimage",
    "chara_hide": "data/fgimage",
    "tb_image_show": "data/fgimage",
    "playbgm": "data/bgm",
    "playse": "data/sound",
    "bgmovie": "data/video",
    # glyph images ship with the engine, not with the game
    "glyph": "tyrano/images/system",
}

# Search order for a tag this table does not know (third-party plugin tags):
# a value found in one of these folders is accepted, so the check never
# invents a failure for a tag it has never seen.
ASSET_BASE_DIRS = ("fgimage", "bgimage", "image", "bgm", "sound", "video")

# Attributes that carry a file reference.  An allowlist rather than "any
# value ending in an asset extension": engine help strings
# (text=".../data/image/my_image.png") are display text, not lookups.
ASSET_ATTRS = ("storage", "graphic", "line")

ASSET_REF_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                 ".mp4", ".webm")

TAG_SPAN = re.compile(r"\[([a-z_]+)\b([^\]]*)\]")


def _rel(path, root):
    return os.path.relpath(path, root)


def check_layout(web_root):
    return [f"missing {name}" for name in ("index.html", "tyrano", "data")
            if not os.path.exists(os.path.join(web_root, name))]


def check_save_backend(web_root):
    cfg = os.path.join(web_root, "data", "system", "Config.tjs")
    if not os.path.isfile(cfg):
        return ["missing data/system/Config.tjs"]
    with open(cfg, encoding="utf-8-sig") as f:
        text = f.read()
    m = re.search(r"configSave\s*=\s*(\w+)", text)
    if not m:
        return ["no configSave= line in data/system/Config.tjs"]
    if m.group(1) != "webstorage":
        return [f"configSave={m.group(1)} (needs webstorage for JoiPlay)"]
    return []


def _audio_exists(web_root, ref):
    return any(os.path.isfile(os.path.join(web_root, base, ref)) for base in AUDIO_DIRS)


def _audio_refs(web_root):
    """Yield every (file, ref) audio reference in the scenario tree.

    Comment lines are skipped: KAG3 comments are `;`-prefixed and a commented
    reference is not a runtime lookup.  Measured false positive: a game ships
    `;[playbgm storage="bgm004.wav"]` in config.ks while the real file is
    bgm004.ogg, which failed the delivery gate for a build that is fine.
    """
    scenario = os.path.join(web_root, "data", "scenario")
    if not os.path.isdir(scenario):
        return
    for dp, _dn, fns in os.walk(scenario):
        for fn in sorted(fns):
            if not fn.lower().endswith(".ks"):
                continue
            path = os.path.join(dp, fn)
            text, _enc = load_ks(path)
            for line in text.splitlines():
                if line.lstrip().startswith(";"):
                    continue
                for m in AUDIO_REF.finditer(line):
                    yield path, m.group(2)


def check_audio_refs(web_root, source=None):
    """Every audio ref in the scenario must point at an existing file.

    With `source` (the original game folder), refs that are missing in
    BOTH the build and the original are downgraded to warnings - a source
    defect is not a conversion regression."""
    missing = []
    mp3_refs = 0
    for path, ref in _audio_refs(web_root):
        if ref.endswith(".mp3"):
            mp3_refs += 1
        if not _audio_exists(web_root, ref):
            missing.append(f"{_rel(path, web_root)}: {ref}")
    if source:
        source_missing = {ref for _p, ref in _audio_refs(source)
                          if not _audio_exists(source, ref)}
        mp3_refs = sum(1 for _p, ref in _audio_refs(web_root)
                       if ref.endswith(".mp3") and ref not in source_missing)
        missing = [m for m in missing if m.split(": ", 1)[1] not in source_missing]
    problems = ["%d mp3 refs left after conversion" % mp3_refs] \
        if mp3_refs else []
    problems += [f"dangling audio ref {m}" for m in missing[:10]]
    if len(missing) > 10:
        problems.append("...and %d more" % (len(missing) - 10))
    return problems


def _resolve_ref(root, rel):
    """Resolve `rel` under `root` component by component, case-sensitively.

    Returns ``(state, real_rel)``.  `state` is "file" when the path exists
    exactly as written, "case" when only a different case matches (fine on
    Windows, 404 on Android) and "missing" when nothing matches.

    `os.path.isfile` cannot be used for this: on Windows it answers True for
    a case-mismatched path, which is exactly the defect being looked for.
    """
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts:
        return "missing", rel
    current = root
    real = []
    for part in parts:
        try:
            names = os.listdir(current)
        except OSError:
            return "missing", rel
        if part in names:
            real.append(part)
        else:
            actual = {n.lower(): n for n in names}.get(part.lower())
            if actual is None:
                return "missing", rel
            real.append(actual)
        current = os.path.join(current, real[-1])
    if not os.path.isfile(current):
        return "missing", rel
    real_rel = "/".join(real)
    return ("file" if real_rel == "/".join(parts) else "case"), real_rel


def _ref_status(root, tag, value):
    """``(state, real_rel)`` for one asset reference, as the engine looks it up."""
    norm = value[2:] if value.startswith("./") else value
    if norm.startswith("data/"):
        return _resolve_ref(root, norm)
    base = TAG_ASSET_DIR.get(tag)
    candidates = [f"{base}/{norm}"] if base else [
        f"data/{d}/{norm}" for d in ASSET_BASE_DIRS]
    miss = ("missing", candidates[0])
    for candidate in candidates:
        state, real = _resolve_ref(root, candidate)
        if state == "file":
            return state, real
        if state == "case" and miss[0] == "missing":
            miss = (state, real)
    return miss


def _asset_refs(web_root):
    """Yield (file, tag, attr, value) for every image/video reference.

    Comment lines are skipped for the same reason as in `_audio_refs`: a
    commented reference is not a runtime lookup.
    """
    scenario = os.path.join(web_root, "data", "scenario")
    if not os.path.isdir(scenario):
        return
    for dp, _dn, fns in os.walk(scenario):
        for fn in sorted(fns):
            if not fn.lower().endswith(".ks"):
                continue
            path = os.path.join(dp, fn)
            text, _enc = load_ks(path)
            for line in text.splitlines():
                if line.lstrip().startswith(";"):
                    continue
                for tag, body in TAG_SPAN.findall(line):
                    for attr, value in split_tag_attrs(body):
                        if attr not in ASSET_ATTRS or not value:
                            continue
                        ext = os.path.splitext(value)[1].lower()
                        if ext in ASSET_REF_EXT:
                            yield path, tag, attr, value


def check_asset_refs(web_root, source=None):
    """Every image/video reference must resolve with the exact case written.

    Audio is deliberately excluded: `check_audio_refs` owns it and knows
    about the mp3 -> ogg rewrite.  With `source`, only regressions are
    reported - a reference that is broken in the original too is a source
    defect, not something the conversion caused (same rule as audio).
    """
    missing, miscase = {}, {}
    checked = 0
    for path, tag, attr, value in _asset_refs(web_root):
        key = (tag, attr, value)
        if key in missing or key in miscase:
            continue
        checked += 1
        state, real = _ref_status(web_root, tag, value)
        if state == "file":
            continue
        if source is not None and _ref_status(source, tag, value)[0] != "file":
            continue
        where = _rel(path, web_root)
        if state == "case":
            miscase[key] = (f"{where}: {tag} {attr}=\"{value}\" resolves only "
                            f"as {real} (ok on Windows, 404 on Android)")
        else:
            missing[key] = f"{where}: {tag} {attr}=\"{value}\""
    cases, gone = list(miscase.values()), list(missing.values())
    problems = [f"asset ref case mismatch {c}" for c in cases[:10]]
    problems += [f"dangling asset ref {m}" for m in gone[:10]]
    hidden = max(0, len(cases) - 10) + max(0, len(gone) - 10)
    if hidden:
        problems.append("...and %d more" % hidden)
    if cases or gone:
        log.warning("assets: %d refs checked, %d dangling, %d case-only",
                    checked, len(gone), len(cases))
    return problems


def _png_size(path):
    """(w, h) from the IHDR header, or None when it is not a PNG header.

    A file with the PNG signature but a truncated header (interrupted copy)
    must be reported as unreadable - this function's job is to find bad
    images, so it must not crash on one.
    """
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or len(head) < 24:
        return None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def _has_png_signature(path):
    """Cheap signature probe used only for a file whose header was
    unreadable, to tell a truncated PNG from a non-PNG with a .png name."""
    try:
        with open(path, "rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def check_png_limits(web_root):
    """Android WebView textures cap at PNG_MAX_DIMENSION px per side; report
    over-limit.  A file that carries the PNG signature but no readable IHDR
    (interrupted copy / truncation) is reported too - it renders broken on
    every platform, and silently skipping it made this check blind."""
    limit = rpg_constants.PNG_MAX_DIMENSION
    over = []
    broken = []
    count = 0
    for dp, _dn, fns in os.walk(web_root):
        for fn in fns:
            if not fn.lower().endswith(".png"):
                continue
            path = os.path.join(dp, fn)
            size = _png_size(path)
            if size is None:
                if _has_png_signature(path):
                    broken.append(_rel(path, web_root))
                continue
            count += 1
            w, h = size
            if w > limit or h > limit:
                over.append("%s (%dx%d)" % (_rel(path, web_root), w, h))
    log.info("png: %d checked, %d unreadable", count, len(broken))
    problems = [f"png unreadable: {b}" for b in broken[:10]]
    problems += ["png over %d: %s" % (limit, o) for o in over[:10]]
    return problems


def verify(web_root, source=None, check_png=True, check_assets=True):
    """Return the list of problems (empty = OK).  `source` is an optional
    original game folder whose asset tree supplements the built one."""
    # AGENTS.md CRITICAL: reading is covered too - the archived gate on
    # `archive.names`/`verify` is precedent, and the point is that no
    # processor touches the other side's bytes, not just that it writes none.
    own = platform.require_native_paths("verify tyrano build", web_root=web_root,
                                        source=source or web_root)
    web_root = str(own["web_root"])
    source = None if source is None else str(own["source"])
    problems = []
    problems += check_layout(web_root)
    problems += check_save_backend(web_root)
    problems += check_audio_refs(web_root, source=source)
    if check_assets:
        problems += check_asset_refs(web_root, source=source)
    if check_png:
        problems += check_png_limits(web_root)
    if problems:
        log.warning("verify: %d problems", len(problems))
    else:
        log.info("verify: OK")
    return problems


def cmd(web_root: Annotated[str, cliutil.Argument(help="built game folder")],
        source: Annotated[str | None, cliutil.Option(
            "--source", help="original game folder (audio existence fallback)"
        )] = None,
        no_png: Annotated[bool, cliutil.Option(
            "--no-png", help="skip the PNG size check")] = False,
        no_assets: Annotated[bool, cliutil.Option(
            "--no-assets", help="skip the image/video reference check")] = False,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    """Verify a built TyranoScript folder (problems are printed, one per line)."""
    cliutil.setup_logging(verbose, quiet, log_file)
    problems = verify(web_root, source=source, check_png=not no_png,
                      check_assets=not no_assets)
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        return 1
    return 0


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="verify.py")


if __name__ == "__main__":
    raise SystemExit(main())
