#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification: PNG signatures, JSON parse, referenced audio exists,
System.json flags, decode integrity, and key-file presence."""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from . import audio as audio_mod
from . import media
from . import plugincompat
from . import runtime

log = logging.getLogger("rpgmaker.verify")


def _iter_png_files(web_root):
    img_dir = os.path.join(web_root, "img")
    for dp, _dn, fns in os.walk(img_dir):
        for fn in fns:
            if fn.lower().endswith(".png"):
                yield os.path.join(dp, fn)


PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPEG_SIG = b"\xff\xd8\xff"


def _check_png_signature(p):
    """Classify a .png file by magic bytes.

    Returns None for a real PNG, ("jpeg", p) when the file holds JPEG data,
    or ("bad", p) for anything else (corruption/truncation).

    Some engines ship photographic assets as JPEG bytes under a .png name;
    browsers decode images by content sniffing (magic bytes), not by URL
    extension, so such files load fine and must not fail verification.
    """
    with open(p, "rb") as f:
        sig = f.read(8)
    if sig == PNG_SIG:
        return None
    if sig[:3] == JPEG_SIG:
        return ("jpeg", p)
    return ("bad", p)


def verify_pngs(web_root, workers=None):
    """Check every img/**/*.png signature in parallel (I/O-bound reads).

    `workers=None` auto-tunes from the machine (see runtime.py).
    """
    workers = runtime.resolve_workers("png", workers, path=web_root)
    files = list(_iter_png_files(web_root))
    bad, jpeg = [], []
    if files:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for res in ex.map(_check_png_signature, files):
                if res is None:
                    continue
                (jpeg if res[0] == "jpeg" else bad).append(res[1])
    if bad:
        log.error("bad PNG signatures: %d (first: %s)", len(bad), bad[:3])
    else:
        log.info("PNG signatures OK (%d files)", len(files))
    if jpeg:
        log.warning(
            "JPEG-content .png files: %d (first: %s) - known engine practice, "
            "not corruption; browsers decode them by content sniffing, "
            "kept as-is", len(jpeg), jpeg[:3])
    return bad


def verify_data_json(web_root):
    bad = []
    skipped = []
    data_dir = os.path.join(web_root, "data")
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(data_dir, fn), encoding="utf-8-sig") as f:
                json.load(f)
        except (OSError, ValueError) as e:
            # Non-JSON data files are expected when a plugin (e.g. Aqua.js +
            # CryptoJS AES) decrypts data at runtime - the file is encrypted.
            # OSError covers file I/O, ValueError covers JSONDecodeError and
            # UnicodeDecodeError (binary/encrypted bytes).
            with open(os.path.join(data_dir, fn), "rb") as f:
                head = f.read(1)
            if head in (b"{", b"["):
                bad.append((fn, str(e)))
            else:
                skipped.append(fn)
    if skipped:
        log.warning("data JSON skipped (custom runtime-decryption): %s", skipped)
    if bad:
        log.error("data JSON errors: %s", bad)
    else:
        log.info("all data/*.json parse OK%s",
                 " (with %d custom-encrypted skipped)" % len(skipped) if skipped else "")
    return bad


def verify_system_flags(web_root):
    path = os.path.join(web_root, "data", "System.json")
    if not os.path.isfile(path):
        return ["System.json missing"]
    try:
        with open(path, encoding="utf-8-sig") as f:
            s = json.load(f)
    except (OSError, ValueError):
        log.warning("System.json not plain JSON (custom runtime-decryption); flags check skipped")
        return []
    issues = []
    if s.get("hasEncryptedImages") or s.get("hasEncryptedAudio"):
        issues.append("encryption flags still set")
    if s.get("encryptionKey"):
        issues.append("encryptionKey still set")
    # BOM check
    with open(path, "rb") as f:
        head = f.read(3)
    if head == b"\xef\xbb\xbf":
        issues.append("System.json has UTF-8 BOM (breaks JSON.parse)")
    log.info("System.json flags %s", "OK" if not issues else issues)
    return issues


def _source_has_audio(source_dir, folder, name):
    """True if `folder/name` exists in the ORIGINAL game (any extension form:
    .ogg, .ogg_, .m4a, .m4a_, .rpgmvo ...). If the reference is missing from
    the source too, it is a pre-existing source quirk, not a build failure."""
    if not source_dir:
        return True  # no source given -> treat as build failure
    base = os.path.join(source_dir, "audio", folder)
    if not os.path.isdir(base):
        return False
    for fn in os.listdir(base):
        stem, ext = os.path.splitext(fn)
        if stem == name:
            return True
    return False


def verify_audio_refs(web_root, source_dir=None):
    """Check that every audio name referenced in System.json exists on disk.

    A reference missing BOTH here and in `source_dir` is a pre-existing source
    quirk (the engine silently skips missing ME/BGM) -> warning only. A
    reference present in the source but missing in the build is a real error.
    """
    path = os.path.join(web_root, "data", "System.json")
    missing = []
    preexisting = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            s = json.load(f)
    except (OSError, ValueError):
        log.warning("System.json not plain JSON (custom runtime-decryption); "
                    "audio refs check skipped")
        return missing

    def check(name, folder):
        if not name:
            return
        if not os.path.isfile(os.path.join(web_root, "audio", folder, name + ".ogg")):
            if _source_has_audio(source_dir, folder, name):
                missing.append((folder, name))
            else:
                preexisting.append((folder, name))

    for key, folder in [("titleBgm", "bgm"), ("battleBgm", "bgm"),
                        ("gameoverMe", "me"), ("defeatMe", "me"),
                        ("victoryMe", "me")]:
        a = s.get(key)
        if a:
            check(a.get("name"), folder)
    for a in s.get("sounds", []):
        if a:
            check(a.get("name"), "se")
    for v in ("boat", "ship", "airship"):
        a = s.get(v, {}).get("bgm")
        if a:
            check(a.get("name"), "bgm")
    if preexisting:
        log.warning("audio refs missing in the SOURCE too (harmless, engine skips "
                    "silently): %s", preexisting)
    log.info("audio refs %s (%d missing)",
             "OK" if not missing else "MISSING", len(missing))
    return missing


def verify_decode(web_root, workers=None, sample=None):
    """Decode every audio file with PyAV (in-process). Returns errors.

    Replaces `ffmpeg -v error -i <f> -f null -`: PyAV raises inside the
    decode loop on truncated/corrupt data, which is the signal the CLI's exit
    code used to carry - and no external binary is needed.

    `workers=None` auto-tunes from the machine (see runtime.py).
    """
    workers = runtime.resolve_workers("decode", workers, path=web_root)
    errors = []
    files = list(audio_mod.iter_audio_files(web_root))
    if sample:
        files = files[:sample]

    def work(p):
        ok, reason = media.decode_ok(p)
        return p, "" if ok else reason

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for p, err in ex.map(work, files):
            if err:
                errors.append((p, err[:200]))
    log.info("decode check: %d/%d errors", len(errors), len(files))
    return errors


def verify_plugin_compat(web_root):
    """Advisory: a plugin can break at LOAD time in a browser/JoiPlay (no
    NW.js `process`/`require`) while every other check stays green, and the
    game then boots with a feature silently missing.  Reported, never a
    failure - untangling arbitrary plugin code needs a human."""
    findings = plugincompat.scan(web_root)
    if findings:
        plugins = sorted({f.plugin for f in findings})
        log.warning("plugin compat: %d module-scope NW.js reference(s) in enabled "
                    "plugin(s) %s (run `pipeline.py compat %s` to repair/inspect): %s",
                    len(findings), ", ".join(plugins), web_root,
                    "; ".join(str(f) for f in findings[:5]))
    else:
        log.info("plugin compat: no module-scope NW.js references in enabled plugins")
    return findings


def verify_key_files(web_root):
    is_mv = os.path.exists(os.path.join(web_root, "js", "rpg_core.js"))
    core = "js/rpg_core.js" if is_mv else "js/rmmz_core.js"
    required = ["index.html", "js/main.js", core, "js/plugins.js",
                "data/System.json", "audio", "img"]
    missing = [r for r in required if not os.path.exists(os.path.join(web_root, r))]
    # MV fallback for main.js
    if "js/main.js" in missing and os.path.exists(os.path.join(web_root, "js", "rpg_core.js")):
        missing.remove("js/main.js")
    log.info("key files %s", "OK" if not missing else "missing: %s" % missing)
    return missing


def verify_all(web_root, decode=False, sample=None, source_dir=None, workers=None):
    """Run every verification step; return a list of problem groups (empty = pass).

    `workers=None` auto-tunes PNG signature and decode parallelism from the
    machine (see runtime.py).
    """
    issues = []
    for fn in (verify_data_json, verify_system_flags, verify_key_files):
        res = fn(web_root)
        if res:
            issues.append(res)
    res = verify_pngs(web_root, workers=workers)
    if res:
        issues.append(res)
    res = verify_audio_refs(web_root, source_dir=source_dir)
    if res:
        issues.append(res)
    verify_plugin_compat(web_root)
    if decode:
        errs = verify_decode(web_root, workers=workers, sample=sample)
        if errs:
            issues.append(["%d decode errors" % len(errs)])
    if issues:
        log.error("VERIFY FAILED: %d problem groups", len(issues))
    else:
        log.info("VERIFY PASSED")
    return issues
