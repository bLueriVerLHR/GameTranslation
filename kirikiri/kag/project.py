"""Project assembly: engine skeleton, macros, state overrides, intent report.

Output-side work that is not about one scenario or one asset: copying the
engine tree, collecting the game's macros, reading the local state-override
JSON, and `write_intents()` -- the record of what every stubbed KAG3 tag was
supposed to do (owner directive: keep the intent, not just the no-op).
"""
import json
import logging
import os
import re
import shutil

from kirikiri.kag.tags import tag_intent
from kirikiri.ks_extract import detect_encoding

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

#: Engine-tree entries that are development / build scaffolding, not runtime
#: parts.  The engine source tree ships them (lint config, editor settings, the
#: release packaging script, the engine's own docs); a *game* build must not
#: carry them (owner: "packaging must not include development files").  Kept:
#: LICENCE.txt and readme.txt, which belong with a redistributed engine.
ENGINE_DEV_SKIP = {
    ".vscode", ".github", ".git", ".idea", "node_modules", "release",
    ".eslintrc.js", ".eslintrc.json", ".prettierignore", ".prettierrc.js",
    ".prettierrc.json", ".gitignore", ".gitattributes", ".editorconfig",
    ".babelrc", ".npmignore", "package.json", "package-lock.json",
    "doc.html", "jsconfig.json", "tsconfig.json", ".DS_Store",
}


def _copy_tree(src, dst, ignore_exts=()):
    """Copy an engine tree, leaving development scaffolding behind."""
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs
                   if d not in ("__pycache__",) and d not in ENGINE_DEV_SKIP]
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for f in files:
            if f in ENGINE_DEV_SKIP:
                continue
            if any(f.lower().endswith(e) for e in ignore_exts):
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(target, f))


def _collect_macros(unpacked):
    """Collect macro names defined in scenario/ so we know which tags are
    game-defined (not Tyrano built-ins) - informational only."""
    macros = set()
    scen = os.path.join(unpacked, "scenario")
    if os.path.isdir(scen):
        for fn in os.listdir(scen):
            if not fn.endswith(".ks"):
                continue
            raw = open(os.path.join(scen, fn), "rb").read()
            txt = raw.decode(detect_encoding(raw), errors="replace")
            for m in re.finditer(r"^\[macro name=(\S+?)([\s\]]|$)", txt, re.M):
                macros.add(m.group(1).lower())
    return macros


def _load_state_overrides(path):
    """Load optional runtime variable defaults from an external JSON file.

    Game-specific variable names belong in the external file, not in the
    converter.  Only Tyrano's three scenario-variable namespaces are accepted.
    """
    if not path:
        return {}
    try:
        # utf-8-sig: the override file is hand-edited on Windows, where editors
        # happily add a BOM; plain utf-8 turned that into a JSONDecodeError and
        # the converter exited 2 with a message about broken JSON.
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise ValueError("cannot read state overrides %s: %s" % (path, e)) from e
    if not isinstance(data, dict):
        raise ValueError("state overrides root must be an object: %s" % path)
    allowed = {"f", "sf", "tf"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError("unknown state override namespace(s) in %s: %s" %
                         (path, ", ".join(unknown)))
    for namespace, values in data.items():
        if not isinstance(values, dict):
            raise ValueError("state override namespace %s must be an object: %s" %
                             (namespace, path))
        bad = sorted(k for k in values if k in {"__proto__", "constructor", "prototype"})
        if bad:
            raise ValueError("unsafe state override key in %s.%s: %s" %
                             (path, namespace, ", ".join(bad)))
    return data


def _state_overrides_js(overrides):
    """Build a small runtime that keeps configured scenario defaults applied."""
    if not overrides:
        return ""
    payload = json.dumps(overrides, ensure_ascii=False, separators=(",", ":"))
    return """(function () {
  window.__kag3_state_overrides = %s;
  window.__kag3_apply_state_overrides = function () {
    var kag = window.TYRANO && window.TYRANO.kag;
    if (!kag || !kag.variable || !kag.stat) return false;
    var targets = { f: kag.stat.f, sf: kag.variable.sf, tf: kag.variable.tf };
    var source = window.__kag3_state_overrides;
    Object.keys(source).forEach(function (namespace) {
      var target = targets[namespace];
      if (!target) return;
      Object.keys(source[namespace]).forEach(function (key) {
        target[key] = JSON.parse(JSON.stringify(source[namespace][key]));
      });
    });
    return true;
  };
  window.setInterval(window.__kag3_apply_state_overrides, 100);
})();
""" % payload


def write_intents(out_dir, usage, shim_names, dropped=(), degraded=()):
    """Emit the machine-readable intent inventory into the built project.

    Hand-writing the real behaviour later starts from this file: every stubbed
    tag with its call count, arguments, examples and intended behaviour.
    """
    data = {
        "note": ("Conversion intent inventory. Every entry is a KAG3 construct the "
                 "converter did not implement (or deliberately dropped). Use it when "
                 "replacing a stub with real logic."),
        "stubbed_tags": [
            {
                "tag": n,
                "calls": (usage.get(n) or {}).get("count", 0),
                "arguments": sorted(((usage.get(n) or {}).get("attrs") or {}).keys()),
                "examples": (usage.get(n) or {}).get("examples", []),
                "intent": tag_intent(n, usage),
                "status": "no-op stub",
            }
            for n in sorted(shim_names)
        ],
        "dropped_tags": sorted(dropped),
        "degraded_files": sorted(degraded),
    }
    path = os.path.join(out_dir, "_kag3_intents.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return path
