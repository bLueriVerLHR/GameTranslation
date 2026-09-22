"""Parameterized text extraction for RPG Maker Unite games (Unity Mono).

Usage: python extract_game.py <game_dir> <out_dir>

UnityPy is imported inside main() so this module stays importable (and its
pure helpers testable) without the Unity toolchain installed.  A bundle that
cannot be read is reported at WARN level with its path - never skipped
silently, because a skipped bundle is untranslated story text.
"""
import collections
import json
import logging
import os
import re
import sys
from typing import Annotated

_HERE = os.path.dirname(os.path.abspath(__file__))
# Repo root, appended (not inserted) so a same-named sibling module in
# this directory still wins.
sys.path.append(os.path.dirname(_HERE))
from rpgmaker import cliutil, platform  # noqa: E402

log = logging.getLogger("unity.rmunite.extract_game")

# Deliberately NOT japanese_utils.KANA: this answers "does the string contain
# anything a translation could touch" (kana blocks + CJK ideographs + the
# half-width katakana range) for Unity serialized fields, where a line can be
# kanji-only.  japanese_utils.KANA is the narrower "still Japanese" residual
# matcher used by the QC tools; swapping them would change what gets
# extracted, so they stay separate.
KANA_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]")
TARGET = {"RPGMaker.Codebase.CoreSystem.Helper.SO.EventSO", "UnityEngine.UI.Text"}

SKIP_FIELDS = ("m_Script", "m_GameObject", "m_CorrespondingSourceObject",
               "m_PrefabInstance", "m_PrefabAsset",
               "m_ReflectionProbeBlendCullingGroup")


def is_japanese(s):
    return bool(s) and bool(KANA_RE.search(s))


def walk_collect(obj, path, out, classname):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SKIP_FIELDS:
                continue
            walk_collect(v, f"{path}.{k}", out, classname)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_collect(v, "%s[%d]" % (path, i), out, classname)
    elif isinstance(obj, str) and is_japanese(obj):
        s = obj.replace("\r\n", "\n").replace("\r", "\n")
        if s.strip():
            out.append({"class": classname, "field": path, "text": s})


def find_bundle_root(game_dir):
    """`<game>/<name>_Data/StreamingAssets/aa/StandaloneWindows64`, or None."""
    try:
        data_dirs = [d for d in os.listdir(game_dir) if d.endswith("_Data")]
    except OSError as exc:
        log.error("%s: cannot list game dir: %s", game_dir, exc)
        return None
    if not data_dirs:
        log.error("%s: no *_Data folder found - is this a Unity build?",
                  game_dir)
        return None
    return os.path.join(game_dir, data_dirs[0],
                        "StreamingAssets", "aa", "StandaloneWindows64")


def collect_bundles(root):
    """Every .bundle path under `root` (sorted for reproducible output)."""
    return sorted(os.path.join(dirpath, name)
                  for dirpath, _dirs, files in os.walk(root)
                  for name in files if name.endswith(".bundle"))


def _script_map(env, rel):
    """`{path_id: "Namespace.ClassName"}` from the bundle's MonoScripts."""
    smap = {}
    for obj in env.objects:
        if obj.type.name != "MonoScript":
            continue
        try:
            tt = obj.read_typetree()
        except Exception as exc:  # noqa: BLE001
            log.debug("%s: MonoScript path_id=%s unreadable: %s",
                      rel, obj.path_id, exc)
            continue
        cname = tt.get("m_ClassName")
        if cname:
            ns = tt.get("m_Namespace")
            smap[obj.path_id] = f"{ns}.{cname}" if ns else cname
    return smap


def _collect_bundle(env, rel, smap, stats, unique, rawf):
    """Walk one bundle's MonoBehaviours into `unique` + the raw jsonl."""
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tt = obj.read_typetree()
        except Exception as exc:  # noqa: BLE001
            log.debug("%s: MonoBehaviour path_id=%s unreadable: %s",
                      rel, obj.path_id, exc)
            continue
        script = tt.get("m_Script") or {}
        classname = smap.get(script.get("m_PathID"), "?")
        stats[classname] += 1
        recs = []
        walk_collect(tt, "", recs, classname)
        for r in recs:
            text = r["text"]
            if text not in unique:
                unique[text] = {"count": 0, "sources": []}
            u = unique[text]
            u["count"] += 1
            src = "{}@{}".format(r["class"], r["field"])
            if src not in u["sources"]:
                u["sources"].append(src)
            rawf.write(json.dumps({"bundle": rel,
                                   "path_id": obj.path_id,
                                   "class": r["class"],
                                   "field": r["field"],
                                   "text": r["text"]},
                                  ensure_ascii=False) + "\n")


def _scan_bundles(bundle_files, root, unique, stats, raw_path, unitypy):
    """Extract every bundle; returns the list of unreadable ones.

    `unitypy` is passed in (not imported here) so the CLI can validate the
    input path and fail fast *before* the heavy optional dependency loads.
    """
    skipped = []
    with open(raw_path, "w", encoding="utf-8") as rawf:
        for idx, bf in enumerate(bundle_files):
            rel = os.path.relpath(bf, root)
            if idx % 500 == 0:
                log.info("[%d/%d] %s (unique=%d)", idx, len(bundle_files), rel,
                         len(unique))
            try:
                env = unitypy.load(bf)
            except Exception as exc:  # noqa: BLE001
                # External parser boundary: UnityPy.load on a malformed or
                # unsupported bundle can raise any of its internal errors
                # (zlib, struct, IndexError, ValueError...). Keep extracting
                # the rest, but record it: a silently skipped bundle is
                # untranslated text with no trace.
                skipped.append(rel)
                log.warning("%s: bundle unreadable, NOT extracted: %s: %s",
                            rel, type(exc).__name__, exc)
                continue
            _collect_bundle(env, rel, _script_map(env, rel), stats, unique,
                            rawf)
    return skipped


def _write_outputs(out_dir, unique, sel, meta):
    """Write the meta/template/texts JSON, then the class breakdown."""
    with open(os.path.join(out_dir, "keys_target_meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "translated_template.json"), "w",
              encoding="utf-8") as f:
        json.dump(dict.fromkeys(sel, ""), f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "texts_ja.json"), "w",
              encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=1)
    print("saved keys_target_meta.json / translated_template.json / "
          "texts_ja.json")
    tc = collections.Counter()
    for u in sel.values():
        for s in u["sources"]:
            tc[s.split("@")[0]] += 1
    print("=== target class breakdown ===")
    for c, n in tc.most_common():
        print("  %5d  %s" % (n, c))


def cmd(game_dir: Annotated[str, cliutil.Argument(
            help="Unity game directory (holding <name>_Data/)")],
        out_dir: Annotated[str, cliutil.Argument(
            help="output directory for the extracted text")],
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    # AGENTS.md CRITICAL: UnityPy reads under game_dir and this process writes
    # the output tree, so both must be on this processor's side.  Gated before
    # find_bundle_root (which walks the tree) and before the heavy import.
    own = platform.require_native_paths("extract unity game",
                                        game_dir=game_dir, out_dir=out_dir)
    game_dir, out_dir = str(own["game_dir"]), str(own["out_dir"])

    # Validate the input before importing the heavy optional dependency, so a
    # wrong path fails fast with a clear message on any machine.
    root = find_bundle_root(game_dir)
    if not root:
        return 2

    import UnityPy  # noqa: PLC0415 - optional heavy dependency, CLI path only

    os.makedirs(out_dir, exist_ok=True)

    stats = collections.Counter()
    unique = collections.OrderedDict()
    raw_path = os.path.join(out_dir, "extract_raw.jsonl")
    bundle_files = collect_bundles(root)
    log.info("%d bundle(s) under %s", len(bundle_files), root)

    skipped = _scan_bundles(bundle_files, root, unique, stats, raw_path,
                            UnityPy)

    if skipped:
        log.warning("%d of %d bundle(s) skipped - their text is NOT in the "
                    "output: %s", len(skipped), len(bundle_files),
                    ", ".join(skipped[:10]) +
                    (" ..." if len(skipped) > 10 else ""))

    print("total MB records: %d" % sum(stats.values()))
    print("unique texts (all): %d" % len(unique))

    # filter to target classes
    sel = {t: u for t, u in unique.items()
           if any(s.startswith(tuple(TARGET)) for s in u["sources"])}
    print("unique target texts: %d" % len(sel))
    total_chars = sum(len(t) for t in sel)
    print("target chars: %d" % total_chars)

    meta = {t: {"count": u["count"], "sources": u["sources"]}
            for t, u in sel.items()}
    _write_outputs(out_dir, unique, sel, meta)
    return 1 if skipped else 0


# argparse showed the module docstring as the description; a single-command
# Typer app renders the command's docstring, so point it at the same text
# instead of keeping a second copy in sync.
cmd.__doc__ = __doc__

app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="extract_game.py")


if __name__ == "__main__":
    raise SystemExit(main())
