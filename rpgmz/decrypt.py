#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decrypt RPGMaker encrypted assets (16-byte RPGMV header + XOR on the first
16 bytes) in place, dropping the trailing underscore, and clear the
hasEncrypted* / encryptionKey flags in data/System.json.

Easy vs complex:
- "easy"  = every encrypted asset carries the standard 16-byte RPGMV header
  (stock MZ/MV encryption). All files decrypt cleanly.
- "complex" = any asset lacks the header (custom/plugin runtime decryption,
  e.g. Aqua.js AES). Those files are LEFT as-is and System.json flags are NOT
  cleared, so the game's own runtime decryption keeps working on JoiPlay too.

Only in the easy case are the encryption flags cleared: clearing them on a
complex game would make the engine try to load plaintext files that are still
encrypted and break startup.
"""
import json
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

from . import config

log = logging.getLogger("rpgmz.decrypt")

DEFAULT_WORKERS = 8


def load_encryption_key(web_root):
    """Read encryptionKey from data/System.json -> bytes (16) or None."""
    path = os.path.join(web_root, "data", "System.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8-sig") as f:
            sys_json = json.load(f)
        key = sys_json.get("encryptionKey") or ""
        b = bytes.fromhex(key)
        return b if len(b) == 16 else None
    except Exception:
        return None


# MV encrypted-extension -> standard extension after decryption.
MV_EXT_TO_STANDARD = {
    ".rpgmvp": ".png",
    ".rpgmvo": ".ogg",
    ".rpgmvm": ".webm",
}


def _decrypt_to(path, key, new_path):
    """Strip the 16-byte RPGMV header + XOR the first 16 bytes, write `new_path`.

    Returns True on success. Files without the RPGMV header (custom/plugin
    encryption) are left untouched and return False - the game's own runtime
    decryption still needs them.
    """
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 16 or data[:16] != config.RPGMV_HEADER:
        return False
    body = bytearray(data[16:])
    for i in range(min(16, len(body))):
        body[i] ^= key[i]
    with open(new_path, "wb") as f:
        f.write(bytes(body))
    os.remove(path)
    return True


def _iter_encrypted_files(web_root):
    """Yield (src, dst) pairs for every encrypted-looking asset under
    img/, audio/ and movies/.

    MZ encrypted files end with `_` (`foo.png_` -> `foo.png`); MV encrypted
    files carry a non-standard extension (`.rpgmvp` -> `.png`).
    """
    for sub in ("img", "audio", "movies"):
        base = os.path.join(web_root, sub)
        if not os.path.isdir(base):
            continue
        for dp, _dn, fns in os.walk(base):
            for fn in fns:
                path = os.path.join(dp, fn)
                if fn.endswith("_"):
                    yield path, path[:-1]
                else:
                    ext = os.path.splitext(fn)[1].lower()
                    std = MV_EXT_TO_STANDARD.get(ext)
                    if std:
                        yield path, os.path.splitext(path)[0] + std


def _decrypt_jobs(web_root, key, workers):
    """Decrypt every encrypted asset in parallel. Returns (decrypted, skipped)."""
    jobs = list(_iter_encrypted_files(web_root))
    if not jobs:
        return 0, 0
    decrypted = 0
    skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ok in ex.map(lambda j: _decrypt_to(j[0], key, j[1]), jobs):
            if ok:
                decrypted += 1
            else:
                skipped += 1
    return decrypted, skipped


def decrypt_data_encrypted(web_root, key):
    """Decrypt an MZ `data_encrypted/` folder into `data/`.

    MZ games with `hasEncryptedData` ship the DB JSONs (and sometimes
    ExternMessage.csv) encrypted under `data_encrypted/` using the same
    RPGMV-header + first-16-bytes-XOR scheme. They are decrypted into `data/`
    with their original names, then the folder is removed, so the engine (with
    `hasEncryptedData` cleared) loads them from `data/`.

    If the files do NOT carry the RPGMV header (custom/plugin encryption, e.g.
    a DataEncryption.js DRM plugin that decrypts at runtime), the folder is
    left untouched - JoiPlay still runs the plugin and loads it normally.

    Returns (decrypted, custom_kept).
    """
    src = os.path.join(web_root, "data_encrypted")
    dst = os.path.join(web_root, "data")
    if not os.path.isdir(src):
        return 0, 0
    if not os.path.isdir(dst):
        os.makedirs(dst)
    decrypted = 0
    copied = 0
    for fn in sorted(os.listdir(src)):
        path = os.path.join(src, fn)
        if not os.path.isfile(path):
            continue
        out = os.path.join(dst, fn)
        if fn.endswith("_"):
            out = out[:-1]
            ok = _decrypt_to(path, key, out)
        else:
            ext = os.path.splitext(fn)[1].lower()
            std = MV_EXT_TO_STANDARD.get(ext)
            ok = False
            if std:
                ok = _decrypt_to(path, key, os.path.splitext(out)[0] + std)
            if not ok:
                ok = _decrypt_to(path, key, out)
        if ok:
            decrypted += 1
        else:
            shutil.copy2(path, out)
            copied += 1
    if copied == 0:
        shutil.rmtree(src)
        log.info("decrypted %d data_encrypted files -> data/", decrypted)
    else:
        log.warning(
            "data_encrypted left as-is (%d standard, %d custom-encrypted kept)",
            decrypted, copied)
    return decrypted, copied


def decrypt_tree(web_root, key=None, workers=DEFAULT_WORKERS):
    """Decrypt encrypted assets under img/, audio/, movies/ and data_encrypted/.

    Handles MZ (`*.png_`, `*.ogg_`) and MV (`*.rpgmvp`, `*.rpgmvo`,
    `*.rpgmvm`) forms, renaming MV assets to their standard extension.
    `key` may be given explicitly (hex) when System.json hides the key
    (custom runtime-decryption, e.g. Aqua.js AES).

    Returns (decrypted, skipped). `skipped` counts files that look encrypted
    but do NOT carry the RPGMV header - they are left as-is (complex game).
    """
    if not key:
        key = load_encryption_key(web_root)
    if not key:
        log.warning("no usable encryptionKey in data/System.json; nothing to decrypt")
        return 0, 0

    decrypted, skipped = _decrypt_jobs(web_root, key, workers)
    d_dec, d_kept = decrypt_data_encrypted(web_root, key)
    decrypted += d_dec
    skipped += d_kept
    if skipped:
        log.warning("skipped %d files without RPGMV header "
                    "(custom/plugin encryption) - left as-is", skipped)
    log.info("decrypted %d assets (%d left as-is)", decrypted, skipped)
    return decrypted, skipped


def clear_encryption_flags(web_root):
    """Set hasEncryptedImages/Audio = False and empty encryptionKey in System.json.
    Writes UTF-8 **without BOM** (a BOM breaks JSON.parse in the engine).

    Only call this on an EASY game: every encrypted asset was really
    decrypted. Clearing the flags on a complex game makes the engine load
    still-encrypted files as plaintext and the game fails to start.
    """
    path = os.path.join(web_root, "data", "System.json")
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8-sig") as f:
            sys_json = json.load(f)
    except Exception:
        log.warning("data/System.json is not plain JSON (custom runtime-decryption, e.g. "
                    "Aqua/AES plugins); leaving it untouched")
        return

    changed = False
    for flag in ("hasEncryptedImages", "hasEncryptedAudio", "hasEncryptedData"):
        if sys_json.get(flag):
            sys_json[flag] = False
            changed = True
    if sys_json.get("encryptionKey"):
        sys_json["encryptionKey"] = ""
        changed = True

    if changed:
        with open(path, "w", encoding="utf-8", newline="") as f:
            json.dump(sys_json, f, ensure_ascii=False, separators=(",", ":"))
        log.info("cleared encryption flags in data/System.json")


def decrypt_and_clear(web_root, key=None, workers=DEFAULT_WORKERS):
    """Decrypt assets and clear System.json encryption flags.

    Flags are cleared only when every encrypted asset was decrypted (easy
    case). On a complex game (any file left as-is), System.json is left
    untouched so the game's own runtime decryption keeps working.
    """
    decrypted, skipped = decrypt_tree(web_root, key, workers=workers)
    if skipped:
        log.warning("complex encryption detected (%d files left as-is); "
                    "System.json flags kept so the game still loads", skipped)
        return decrypted, skipped
    clear_encryption_flags(web_root)
    return decrypted, skipped
