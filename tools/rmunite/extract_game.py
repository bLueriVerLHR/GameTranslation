"""Parameterized text extraction for RPG Maker Unite games (Unity Mono).
Usage: python extract_game.py <game_dir> <out_dir>"""
import os
import sys
import json
import re
import collections
import UnityPy

GAME = sys.argv[1]
OUT_DIR = sys.argv[2]
data_dirs = [d for d in os.listdir(GAME) if d.endswith("_Data")]
if not data_dirs:
    sys.exit("no *_Data folder found in %s" % GAME)
BUNDLE_ROOT = os.path.join(GAME, data_dirs[0],
                           "StreamingAssets", "aa", "StandaloneWindows64")
os.makedirs(OUT_DIR, exist_ok=True)

KANA_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]")
TARGET = {"RPGMaker.Codebase.CoreSystem.Helper.SO.EventSO", "UnityEngine.UI.Text"}

def is_japanese(s):
    return bool(s) and bool(KANA_RE.search(s))

def walk_collect(obj, path, out, classname):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("m_Script", "m_GameObject", "m_CorrespondingSourceObject",
                     "m_PrefabInstance", "m_PrefabAsset", "m_ReflectionProbeBlendCullingGroup"):
                continue
            walk_collect(v, f"{path}.{k}", out, classname)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_collect(v, f"{path}[{i}]", out, classname)
    elif isinstance(obj, str):
        if is_japanese(obj):
            s = obj.replace("\r\n", "\n").replace("\r", "\n")
            if s.strip():
                out.append({"class": classname, "field": path, "text": s})

def main():
    stats = collections.Counter()
    unique = collections.OrderedDict()
    raw_path = os.path.join(OUT_DIR, "extract_raw.jsonl")

    bundle_files = []
    for root, dirs, files in os.walk(BUNDLE_ROOT):
        for f in files:
            if f.endswith(".bundle"):
                bundle_files.append(os.path.join(root, f))

    with open(raw_path, "w", encoding="utf-8") as rawf:
        for idx, bf in enumerate(bundle_files):
            rel = os.path.relpath(bf, BUNDLE_ROOT)
            if idx % 500 == 0:
                print(f"[{idx}/{len(bundle_files)}] {rel} (unique={len(unique)})", flush=True)
            try:
                env = UnityPy.load(bf)
            except Exception:
                continue
            smap = {}
            for obj in env.objects:
                if obj.type.name == "MonoScript":
                    try:
                        tt = obj.read_typetree()
                        cname = tt.get("m_ClassName")
                        ns = tt.get("m_Namespace")
                        if cname:
                            smap[obj.path_id] = f"{ns}.{cname}" if ns else cname
                    except Exception:
                        pass
            for obj in env.objects:
                if obj.type.name != "MonoBehaviour":
                    continue
                try:
                    tt = obj.read_typetree()
                except Exception:
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
                    src = f"{r['class']}@{r['field']}"
                    if src not in u["sources"]:
                        u["sources"].append(src)
                    rawf.write(json.dumps({"bundle": rel, "path_id": obj.path_id,
                                           "class": r["class"], "field": r["field"],
                                           "text": r["text"]}, ensure_ascii=False) + "\n")

    print(f"total MB records: {sum(stats.values())}")
    print(f"unique texts (all): {len(unique)}")

    # filter to target classes
    sel = {}
    for t, u in unique.items():
        if any(s.startswith(tuple(TARGET)) for s in u["sources"]):
            sel[t] = u
    print(f"unique target texts: {len(sel)}")
    total_chars = sum(len(t) for t in sel)
    print(f"target chars: {total_chars}")

    meta = {t: {"count": u["count"], "sources": u["sources"]} for t, u in sel.items()}
    with open(os.path.join(OUT_DIR, "keys_target_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    tmpl = {t: "" for t in sel}
    with open(os.path.join(OUT_DIR, "translated_template.json"), "w", encoding="utf-8") as f:
        json.dump(tmpl, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "texts_ja.json"), "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=1)
    print("saved keys_target_meta.json / translated_template.json / texts_ja.json")

    # class breakdown of targets
    tc = collections.Counter()
    for t, u in sel.items():
        for s in u["sources"]:
            tc[s.split("@")[0]] += 1
    print("=== target class breakdown ===")
    for c, n in tc.most_common():
        print(f"  {n:5d}  {c}")

if __name__ == "__main__":
    main()
