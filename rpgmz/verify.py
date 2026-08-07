#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verification: PNG signatures, JSON parse, referenced audio exists,
System.json flags, decode integrity, and key-file presence."""
import json
import logging
import os
import subprocess

from . import config
from . import audio as audio_mod

log = logging.getLogger("rpgmz.verify")

BENIGN_DECODE = re_ignore = (
    "Application provided invalid, non monotonically increasing dts to muxer"
)


def verify_pngs(web_root):
    bad = []
    img_dir = os.path.join(web_root, "img")
    for dp, _dn, fns in os.walk(img_dir):
        for fn in fns:
            if not fn.lower().endswith(".png"):
                continue
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                bad.append(p)
    if bad:
        log.error("bad PNG signatures: %d (first: %s)", len(bad), bad[:3])
    else:
        log.info("PNG signatures OK (%d files)", _count_png(img_dir))
    return bad


def _count_png(root):
    n = 0
    for _dp, _dn, fns in os.walk(root):
        n += sum(1 for f in fns if f.lower().endswith(".png"))
    return n


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
        except Exception as e:
            # Non-JSON data files are expected when a plugin (e.g. Aqua.js +
            # CryptoJS AES) decrypts data at runtime - the file is encrypted.
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
    except Exception:
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
    except Exception:
        log.warning("System.json not plain JSON (custom runtime-decryption); audio refs check skipped")
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


def verify_decode(web_root, workers=4, sample=None):
    """Full ffmpeg decode of every audio file. Returns list of real errors."""
    ffmpeg = config.find_ffmpeg()
    errors = []
    files = list(audio_mod.iter_audio_files(web_root))
    if sample:
        files = files[:sample]

    def work(p):
        r = subprocess.run([ffmpeg, "-v", "error", "-i", p, "-map", "0:a:0",
                            "-f", "null", "-"],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return p, r.stderr.strip()[:200]
        bad = [ln for ln in r.stderr.splitlines()
               if any(k in ln for k in ("invalid data", "error while decoding",
                                        "Header missing", "Unable to"))]
        return p, " | ".join(bad) if bad else ""

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for p, err in ex.map(work, files):
            if err:
                errors.append((p, err))
    log.info("decode check: %d/%d errors", len(errors), len(files))
    return errors


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


def verify_all(web_root, decode=False, sample=None, source_dir=None):
    issues = []
    for fn in (verify_pngs, verify_data_json, verify_system_flags,
               verify_key_files):
        res = fn(web_root)
        if res:
            issues.append(res)
    res = verify_audio_refs(web_root, source_dir=source_dir)
    if res:
        issues.append(res)
    if decode:
        errs = verify_decode(web_root, sample=sample)
        if errs:
            issues.append(["%d decode errors" % len(errs)])
    if issues:
        log.error("VERIFY FAILED: %d problem groups", len(issues))
    else:
        log.info("VERIFY PASSED")
    return issues
