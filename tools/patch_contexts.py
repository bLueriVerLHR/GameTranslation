#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_contexts.py - Inject the game-specific Tone block into chunk context
files and upgrade their Rules to the write-first zh.txt contract.

Consolidated from the long-run session patch_contexts.py (docs/translation.md):
the tone must NEVER be hardcoded in gen_translation_shards.py; it lives
in <work>/tone.md (or --tone FILE) and is applied here to ALREADY-GENERATED
chunks.

Rules upgrade: replaces the old "Output: chunk_NN.translated.json" block with
the write-first contract (write chunk_NN.zh.txt first, one translation per
line, 1:1 with chunk_NN.ja.txt - proven 2026-08, experience.md 7.2).

Usage:
    python tools\\patch_contexts.py <work_dir> [--tone tone.md]
"""
import argparse
import glob
import json
import os
import re

NEUTRAL_TONE = """## Tone (from the game owner)
- Faithful to the original (忠于原文): translate the meaning faithfully, do not invent or censor.
- Translate into natural, fluent Simplified Chinese the way a native speaker would write it.
- Story/reveal scenes: keep suspense, do NOT spoil foreshadowing or twists.
- Length: keep the original meaning; if the translation would clearly overflow the message window (4 lines per window), shorten it with a more compact phrasing.
"""

RULES_NEW = """## Rules (write-first contract, mandatory)
- 执行顺序: 先写, 后思考, 再改 — 读完本文件与 chunk_NN.ja.txt 后, 第一动作就是
  Write chunk_NN.zh.txt 第一遍, 严禁在思考/计划里结束:
  1. Read the rules once, read chunk_NN.ja.txt once.
  2. IMMEDIATELY write chunk_NN.zh.txt with a first-pass translation for ALL keys
     (unsure: best guess + 【?】marker). Never end before the file exists.
  3. Read it back, improve with a second Write.
  4. Final reply = file path + entry count ONLY.
- zh.txt format: EXACTLY ONE TRANSLATION PER LINE, SAME ORDER and SAME LINE
  COUNT as chunk_NN.ja.txt (line N of zh.txt = translation of line N of
  ja.txt).  No quotes, no JSON, no ===KEY=== separators.
- 转义规则 (ja 与 zh 完全一致): 文件里的 \\n 代表消息里的一个真实换行 (多行消息的分行);
  \\\\ 代表单个反斜杠 (控制码前缀)。保持与 key 相同的 \\n 数量 (消息窗口行数)。
- 控制码是宏, 不是文本: 所有反斜杠控制码 (\\N[x] 角色名引用、\\P[x] 队员名、
  \\V[x] 变量、\\I[x] 图标、\\C[xx] 颜色, 以及任何 \\字母[x] / \\单个符号 形式的
  自定义码) 一律原样保留, 绝不翻译、绝不改动方括号里的内容。
- 值必须是译文: 不得把日文原文写进值里 (值 == 键原文 = 不合格输出)。
- 键内嵌的字面文本必须保留: 全角空格 \\u3000 缩进、句末标点都要保留原样。
- Translate the Japanese (kana/kanji) in each key into natural, fluent Simplified Chinese.
- Many keys are MACHINE-TRANSLATION FRAGMENTS: a line may already contain Chinese;
  rewrite the WHOLE line so it becomes fully fluent Chinese, keeping the existing Chinese terms.
- If a key has NO kana (already fully Chinese), output it unchanged.
- Never translate plugin command args / script code.
- NO SPOILERS: never reveal foreshadowing/twists in the translation; keep suspense.
- After writing, count control codes in your values vs the keys: they MUST match exactly - do not trust your feeling, count them.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_dir")
    ap.add_argument("--tone", default="", help="tone block file (default: <work>/tone.md)")
    args = ap.parse_args()

    work = os.path.abspath(args.work_dir)
    tone_path = args.tone or os.path.join(work, "tone.md")
    if os.path.exists(tone_path):
        tone = open(tone_path, encoding="utf-8-sig").read().strip() + "\n"
    else:
        tone = NEUTRAL_TONE
        print("WARN: no tone file at %s, using neutral tone" % tone_path)

    patched = 0
    skipped = 0
    for p in sorted(glob.glob(os.path.join(work, "chunks", "*.context.md"))):
        with open(p, encoding="utf-8") as f:
            text = f.read()

        # 1) upgrade the Rules block (replace Output line + drop old format lines)
        i = text.find("## Rules")
        j = text.find("\n## ", i + 1) if i >= 0 else -1
        if i < 0:
            skipped += 1
            continue
        end = j if j > i else len(text)
        text = text[:i] + RULES_NEW + "\n" + text[end:]

        # 2) replace/insert the Tone block before the glossary-ish section
        pat_old = "## Tone (from the game owner)"
        i = text.find(pat_old)
        j = text.find("\n## ", i + 1) if i >= 0 else -1
        anchor = None
        for sec in ("## Glossary (mandatory)", "## Known short-term translations",
                    "## Carry-over", "## Scene transcript"):
            a = text.find(sec)
            if a >= 0:
                anchor = a
                break
        if i >= 0 and j > i:
            text = text[:i] + tone + "\n" + text[j:]
        elif anchor is not None:
            text = text[:anchor] + tone + "\n" + text[anchor:]
        else:
            text = text.rstrip() + "\n\n" + tone + "\n"

        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        patched += 1

    print("patched %d context files (skipped %d)" % (patched, skipped))


if __name__ == "__main__":
    main()
