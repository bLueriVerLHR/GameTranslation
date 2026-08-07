#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Split the remaining-text template (STORY ORDER) into subagent chunks.

- chunks/chunk_NN.ja.txt     keys ONLY: one Japanese key per line, no quotes,
                             no JSON (escaping via tools/plain_io.py: \\n =
                             real newline, \\\\ = one literal backslash).
- chunks/chunk_NN.context.md rules (write-first zh.txt contract) + glossary +
                             carry-over + per-key context windows (the agent
                             sees the scene around each key)
- chunks/chunk_NN.meta.json  which maps/events the chunk spans (parallelism)

Agents write chunk_NN.zh.txt: one translation per line, 1:1 with ja.txt.
Merge with tools/merge_plain_chunks.py.

Chunks are processed IN ORDER: chunk N's context file ends with a carry-over
of the last dialogue lines of chunk N-1, so a linear scene keeps continuity
even when split across chunks.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402

NAMEISH = re.compile(
    r"^[A-Za-z0-9\u3040-\u30ff\u4e00-\u9fff\u00b7・〜\- ]{1,14}$")
CARRY_OVER = 8

RULES = """## Rules (write-first contract, mandatory)
- 执行顺序: 先写, 后思考, 再改 — 读完本文件与 chunk_NN.ja.txt 后, 第一动作就是
  Write chunk_NN.zh.txt 第一遍, 严禁在思考/计划里结束:
  1. Read these rules once, read chunk_NN.ja.txt once.
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
- Translate the Japanese (kana/kanji) in each key into natural, fluent Simplified Chinese.
- Many keys are MACHINE-TRANSLATION FRAGMENTS: a line may already contain Chinese;
  rewrite the WHOLE line so it becomes fully fluent Chinese, keeping the existing Chinese terms.
- If a key has NO kana (already fully Chinese), output it unchanged.
- Never translate plugin command args / script code.
- NO SPOILERS: never reveal foreshadowing/twists in the translation; keep suspense.
- After writing, count control codes in your values vs the keys: they MUST match exactly - do not trust your feeling, count them.
- Reply with ONE line only (counts), then done.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--max-chars", type=int, default=11000,
                    help="cap each chunk by total key char length (default "
                         "11000; the proven write-first size under the 90 KB "
                         "context budget)")
    ap.add_argument("--dict", default="",
                    help="MTool/AI translation dict (root <title>.json) for the "
                         "terminology glossary; optional, auto-detected from "
                         "template.json keys otherwise")
    ap.add_argument("--window", type=int, default=2,
                    help="context window radius around each key (default 2; "
                         "use 1 to shrink context.md when it exceeds the "
                         "~90 KB budget)")
    ap.add_argument("--truncate", type=int, default=45,
                    help="max chars per context transcript line (default 45)")
    args = ap.parse_args()

    work = os.path.abspath(args.work_dir)
    chunks_dir = os.path.join(work, "chunks")
    os.makedirs(chunks_dir, exist_ok=True)

    tmpl = plain_io.load_json(os.path.join(work, "template.json"))
    kinds = plain_io.load_json(os.path.join(work, "kinds.json"))
    ctx = plain_io.load_json(os.path.join(work, "context.json"))
    ordered = list(tmpl.keys())          # already in story order

    D = {}
    if args.dict and os.path.exists(args.dict):
        D = plain_io.load_json(args.dict)
    elif args.dict:
        print("WARN: --dict not found: %s" % args.dict)

    glossary = {}
    # Membership test against the whole template at once (C-level) instead of
    # O(dict x template) per-entry scans - critical for 30k+ key templates.
    joined_tmpl = "\x00".join(tmpl)
    for k, v in D.items():
        if not v or k == v or not NAMEISH.match(k) or len(k) > 14:
            continue
        if len(k) < 3 or len(v) < 2:
            continue
        if k in joined_tmpl:
            glossary[k] = v
    with open(os.path.join(work, "glossary.json"), "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=1)
    print("glossary entries:", len(glossary))

    # split in story order by char budget
    chunks = []
    cur, cur_size = [], 0
    for k in ordered:
        if cur and cur_size + len(k) > args.max_chars:
            chunks.append(cur)
            cur, cur_size = [], 0
        cur.append(k)
        cur_size += len(k)
    if cur:
        chunks.append(cur)

    # merge pass: greedy left-to-right, merge an adjacent chunk when the
    # combined size still fits the budget. Kills wasteful one-key chunks
    # (huge plugin-note leftovers) without ever exceeding the proven cap.
    merged = []
    for c in chunks:
        if merged and sum(map(len, merged[-1])) + sum(map(len, c)) <= args.max_chars:
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    chunks = merged

    # per-chunk carry-over (last lines of previous chunk, in story order)
    previous_tail = []
    for n, keys in enumerate(chunks, 1):
        carry = []
        if previous_tail:
            carry = previous_tail[:CARRY_OVER]
        tail = [k for k in keys if kinds.get(k) in ("block-line", "event-text")]
        previous_tail = tail[-CARRY_OVER:] if tail else previous_tail

        # which maps does this chunk cover?
        maps = []
        for k in keys:
            loc = ctx.get(k, {}).get("where", "")
            m = re.match(r"([^/]+)", loc)
            if m and m.group(1).strip() not in maps:
                maps.append(m.group(1).strip())

        base = os.path.join(chunks_dir, "chunk_%02d" % n)
        plain_io.save_lines(base + ".ja.txt", keys)
        with open(base + ".meta.json", "w", encoding="utf-8") as f:
            json.dump({"maps": maps}, f, ensure_ascii=False, indent=1)

        lines = [
            "# Chunk %02d - %d keys - translate ALL keys in ONE pass" % (n, len(keys)),
            "",
            "chunk_NN.ja.txt: %d keys (one per line).  Write chunk_NN.zh.txt:"
            % len(keys),
            "exactly %d lines, 1:1 in the same order." % len(keys),
            "",
            RULES,
            "",
        ]
        if carry:
            lines += ["## Carry-over: tail of the previous chunk (already translated - KEEP these translations consistent)", ""]
            lines += ["- %s" % t for t in carry]
            lines += [""]
        joined_keys = "\x00".join(keys)
        terms = sorted({v for g, v in glossary.items() if g in joined_keys})[:40]
        if terms:
            lines += ["## Known short-term translations (from the game's MTool dict - reuse for consistency, ignore if irrelevant)", ""]
            lines += ["- %s" % t for t in terms]
            lines += [""]
        lines += ["## Scene transcript (dialogue in story order; [K] = key to translate; | = context line)", ""]
        last_win = []
        win_cap = 2 * args.window + 1
        for k in keys:
            info = ctx.get(k, {})
            where = info.get("where", "")
            win = (info.get("window") or [])[:win_cap]
            lines.append("[K] %s   <= %s" % (k, where))
            for w in win:
                if w != k and w not in last_win:
                    lines.append("  | %s" % (w[:args.truncate]))
            last_win = [w for w in win if w != k]
        with open(base + ".context.md", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    print("chunks:", len(chunks))
    for n, keys in enumerate(chunks, 1):
        maps = plain_io.load_json(os.path.join(chunks_dir, "chunk_%02d.meta.json" % n))["maps"]
        print("chunk_%02d: %d keys, %d chars, maps=%s"
              % (n, len(keys), sum(len(k) for k in keys), maps[:3]))


if __name__ == "__main__":
    main()
