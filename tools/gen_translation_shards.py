#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_translation_shards.py - Split a build_translation.py work package into
translation chunks for dedicated subagents.

Layout (read by the agent workflow):
  chunks/chunk_NN.ja.txt       keys ONLY: one Japanese key per line, no
                               quotes, no JSON (escaping via tools/plain_io.py:
                               \\n = real newline inside the message, \\\\ = one
                               literal backslash).  NEVER touched by agents.
  chunks/chunk_NN.zh.txt       translations: one per line, 1:1 with ja.txt,
                               written by the translating subagent.
  chunks/chunk_NN.context.md   rules + batch-append contract + tone + glossary
                               + name-macro table + per-key scene windows +
                               carry-over of the previous chunk's tail.
  chunks/chunk_NN.meta.json    which maps/events the chunk spans (parallelism)

Chunk 00 = global UI/DB/choices/plugin params (terminology base), then story
maps in MapInfos order grouped by cumulative block count.  Consecutive story
chunks carry the previous chunk's last dialogue lines, so a linear scene
split across chunks keeps continuity.

Usage:
    python gen_translation_shards.py <work_dir> [--per-chunk N] [--max-chars N]
                                     [--start N] [--resume]
                                     [--target-chunks N] [--context-budget-kb N]

Sizing: with --per-chunk N chunks are capped by KEY COUNT; with --max-chars N
chunks are capped by the TOTAL CHAR LENGTH of their keys (long keys consume
more translation budget than short ones, so length-based bucketing keeps
every chunk's workload similar). --max-chars wins over --per-chunk. A single
key longer than the cap gets its own chunk. Default (no sizing flag): AUTO
sizing with the 90 KB context budget — see below.

AUTO SIZING (default; proven on a 36k-key MZ job, 4500 -> 11000 chars): pass
--target-chunks N (and optionally --context-budget-kb, default 90) to pick
--max-chars automatically.  The script estimates each chunk's context.md size
(fixed rules/tone/glossary prefix + per-key scene-transcript lines) and
binary-searches the largest max-chars that keeps the chunk count <= N AND the
largest chunk's context under the budget (90KB+ context.md chunks are the
flaky no-file failures).  If both constraints cannot be met it picks the best
compromise and prints the actual chunk count.  When only --context-budget-kb
is given it picks the largest chunks that fit the budget.

With --resume: keys already covered by any chunks/*.zh.txt (line count ==
ja.txt line count) are skipped, and only the remaining keys are re-split into
fresh chunks numbered from --start.  Keeps story-map order.

Tone: the game-owner tone/character/terminology block is injected from
`<work_dir>/tone.md` when present. Without tone.md a neutral fallback is used
— never a hardcoded previous-game tone (see docs/translation.md).

Glossary: `<work_dir>/glossary.json` {name/term: translation} — negotiated
once with the game owner, afterwards maintained ONLY through the edit tool
(agents never write it; every shard reads a snapshot of it).
"""
import glob
import json
import os
import re
import sys
import types
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_io  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rpgmaker import cliutil  # noqa: E402

GLOBAL_KINDS = {"db-name", "db-description", "db-message1", "db-message2",
                "db-message3", "db-message4", "system", "note", "help",
                "choice", "event-name", "displayName", "event-text", "plugin",
                "db", "cdb"}

CARRY_OVER = 8

DEFAULT_CONTEXT_BUDGET_KB = 90  # max context.md size per chunk (KB)

NEUTRAL_TONE = """## Tone (from the game owner)
- Faithful to the original (忠于原文): translate the meaning faithfully, do not invent or censor.
- Translate into natural, fluent Simplified Chinese the way a native speaker would write it.
- Story/reveal scenes: keep suspense, do NOT spoil foreshadowing or twists.
- Length: keep the original meaning; if the translation would clearly overflow the message window (4 lines per window), shorten it with a more compact phrasing.
"""

RULES = """## Rules (batch-append contract, mandatory)
- 执行顺序: 先写, 后思考, 再改 — 但整块必须拆成小批, 严禁一次性 Write
  全文件, 严禁在思考/计划里结束:
  1. Read these rules once, read chunk_NN.ja.txt once.
  2. Translate IN BATCHES: each batch ~100-130 lines. Write chunk_NN.zh.txt
     with the FIRST batch (Write tool), then APPEND each following batch to
     the file end with the edit tool (oldString = current last line,
     newString = last line + new batch). Each batch must be 1:1 with the
     corresponding ja batch.
  3. SELF-CHECK after EVERY batch: read back the zh.txt segment and verify
     line count, literal \\n count, control codes (preserved, same count),
     no kana residue. Fix within the batch before continuing.
  4. After all batches: read back the whole file, final line count MUST
     equal chunk_NN.ja.txt line count.
  5. Final reply = file path + entry count ONLY.
- zh.txt format: EXACTLY ONE TRANSLATION PER LINE, SAME ORDER and SAME LINE
  COUNT as chunk_NN.ja.txt (line N of zh.txt = translation of line N of
  ja.txt).  No quotes, no JSON, no ===KEY=== separators.
- 转义规则 (ja 与 zh 完全一致): 文件里的 \\n 代表消息里的一个真实换行 (多行消息的分行);
  \\\\ 代表单个反斜杠 (控制码前缀)。保持与 key 相同的 \\n 数量 (消息窗口行数)。
- 控制码是宏, 不是文本: 所有反斜杠控制码 (\\N[x] 角色名引用、\\P[x] 队员名、
  \\V[x] 变量、\\I[x] 图标、\\C[xx] 颜色, 以及任何 \\字母[x] / \\单个符号 形式的
  自定义码) 一律原样保留, 绝不翻译、绝不改动方括号里的内容 (人名宏对照见下方
  Name macros 表)。
- 值必须是译文: 不得把日文原文写进值里 (值 == 键原文 = 不合格输出)。
- 位置后缀: 键行末尾可能出现分隔符 (\x1f 不可见字符) 加位置标记 (如
  Map001.json#ev0#pg0#c1)。整个键行(含后缀)是键, 译文只译分隔符之前的
  日文正文, 不要把位置标记写进译文。同一日文原文在不同位置的键可能分别
  出现, 按各自场景语境翻译 (场景记录在下方)。
- 键内嵌的字面文本必须保留: 全角空格 \\u3000 缩进、句末标点都要保留原样。
- Translate the Japanese (kana/kanji) in each key into natural, fluent Simplified Chinese.
- If a key has NO kana (already fully Chinese), output it unchanged.
- Never translate plugin command args / script code.
- NO SPOILERS: never reveal foreshadowing/twists in the translation; keep suspense.
- After writing, count control codes in your values vs the keys: they MUST match exactly - do not trust your feeling, count them.
"""


def load_tone(work):
    """Load the game-specific tone/characters block from work/tone.md.
    Missing file -> neutral fallback (never a previous game's tone)."""
    tone_path = os.path.join(work, "tone.md")
    if os.path.exists(tone_path):
        with open(tone_path, encoding="utf-8-sig") as f:
            tone = f.read().strip()
        if tone:
            return tone + "\n"
    return NEUTRAL_TONE


def load_glossary(work):
    path = os.path.join(work, "glossary.json")
    if not os.path.exists(path):
        return {}
    return plain_io.load_json(path)


def load_name_macros(work):
    path = os.path.join(work, "name_macros.json")
    if not os.path.exists(path):
        return {}
    return plain_io.load_json(path)


def load_context(work):
    path = os.path.join(work, "context.json")
    if not os.path.exists(path):
        return {}
    return plain_io.load_json(path)


def done_keys(chunks_dir):
    """Keys already translated: every zh.txt with the same line count as its
    ja.txt contributes its (unescaped) keys."""
    done = set()
    for p in sorted(glob.glob(os.path.join(chunks_dir, "chunk_*.ja.txt"))):
        m = re.search(r"chunk_(\d+)\.ja\.txt$", p)
        if not m:
            continue
        num = int(m.group(1))
        keys, vals = plain_io.load_pair(chunks_dir, num)
        if keys is None:
            continue
        if len(vals) == len(keys):
            done.update(keys)
    return done


def transcript(keys, ctx, truncate=45, window=2):
    """Scene transcript lines for the chunk: [K] = key to translate, | =
    context line (from context.json windows), deduplicated.  Every output
    line is ONE physical line: keys and windows with embedded newlines are
    shown escaped (\\n) so the written context.md size matches the estimator
    (a raw multi-line key would otherwise expand to many physical lines and
    blow past the context budget)."""
    def flat(s):
        return s.replace("\r", "").replace("\n", "\\n")
    out = []
    win_cap = 2 * window + 1
    last_win = []
    for k in keys:
        info = ctx.get(k, {})
        where = info.get("where", "")
        win = (info.get("window") or [])[:win_cap]
        out.append("[K] %s   <= %s" % (flat(k), where))
        for w in win:
            if w != k and w not in last_win:
                out.append("  | %s" % flat(w)[:truncate])
        last_win = [w for w in win if w != k]
    return out


def _collect_context(work, args):
    """Load the work package (template/kinds/structure + tone/glossary/
    macros/context), create the chunks dir and apply --resume filtering.
    Returns (tpl, kinds, structure, glossary, macros, ctx, tone, chunks_dir)."""
    tpl = plain_io.load_json(os.path.join(work, "template.json"))
    kinds = plain_io.load_json(os.path.join(work, "kinds.json"))
    structure = plain_io.load_json(os.path.join(work, "structure.json"))
    glossary = load_glossary(work)
    macros = load_name_macros(work)
    ctx = load_context(work)
    tone = load_tone(work)

    chunks_dir = os.path.join(work, args.out_dir)
    os.makedirs(chunks_dir, exist_ok=True)

    if args.resume:
        done = done_keys(chunks_dir)
        tpl = {k: v for k, v in tpl.items() if k not in done}
        print("resume: %d keys already translated, %d remaining"
              % (len(done), len(tpl)))
    return tpl, kinds, structure, glossary, macros, ctx, tone, chunks_dir


def _collect_keys(tpl, kinds, structure):
    """Classify template keys: GLOBAL_KINDS first (sorted), then per-map
    scene keys in story order (dedup keep-first), then orphan keys that no
    map references.  Returns (global_keys, map_keys, n_orphan)."""
    # global chunk
    global_keys = [k for k in tpl if kinds.get(k) in GLOBAL_KINDS]
    global_keys.sort(key=lambda k: (-len(k), k))

    # per-map block keys, story order, dedup keep-first
    map_keys = []      # (map_label, key)
    seen = set()
    for m in structure["maps"]:
        if isinstance(m["id"], int):
            label = "Map%03d" % m["id"]
        else:
            label = str(m["id"])
        keys = []
        for ev in m.get("items", []):
            # MZ layout: event -> items; Wolf RPG layout: flat key items
            if "key" in ev:
                it = ev
                k = it.get("key")
                if k and k in tpl and k not in seen and k not in global_keys:
                    keys.append(k)
                    seen.add(k)
                continue
            for it in ev.get("items", []):
                k = it.get("key")
                if k and k in tpl and k not in seen and k not in global_keys:
                    keys.append(k)
                    seen.add(k)
        if keys:
            map_keys.append((label, keys))

    # keys missing from both the global set and the scene tree (orphan
    # blocks, e.g. duplicates that no map references) still get translated
    covered = set(global_keys)
    for _l, ks in map_keys:
        covered.update(ks)
    orphan = [k for k in tpl if k not in covered]
    n_orphan = 0
    if orphan:
        map_keys.append(("Orphan", orphan))
        n_orphan = len(orphan)
        print("orphan keys: %d" % n_orphan)
    return global_keys, map_keys, n_orphan


def _emit_chunks(chunks_dir, args, global_keys, map_keys, tone, glossary,
                 macros, ctx):
    """Write the global chunk (key-count capped) then the story chunks in
    story order (auto --max-chars buckets, or legacy --per-chunk pieces),
    each carrying the previous chunk's dialogue tail for continuity.
    Returns the next chunk number."""
    num = args.start
    if global_keys:
        # Global/DB/UI texts are short one-liners; cap them by KEY COUNT
        # (transcript lines make long context files) so no chunk's context.md
        # grows past the agent budget.
        num = _write_split(chunks_dir, num, {k: "" for k in global_keys},
                           "remaining global texts",
                           args.global_per_chunk, 0, tone,
                           glossary, macros, ctx, args)

    # story chunks (a single map with more keys than the cap is split into
    # consecutive sub-chunks so no chunk ever exceeds the agent budget).
    # Dialogue continuity is MANDATORY: chunks are split in story order and
    # every story chunk's context.md opens with the previous chunk's last
    # CARRY_OVER dialogue keys, so a linear scene split across chunks keeps
    # continuity (a fresh agent otherwise translates mid-scene blind).
    prev_keys = []
    if args.max_chars:
        for groups in build_buckets(map_keys, args.max_chars):
            keys = [k for _l, ks in groups for k in ks]
            num = _write_map_chunk(chunks_dir, num, groups, tone,
                                   glossary, macros, ctx, args, prev_keys)
            prev_keys = keys
    else:
        cur, acc = [], 0
        for label, keys in map_keys:
            pieces = [keys[i:i + args.per_chunk]
                      for i in range(0, len(keys), args.per_chunk)]
            for piece in pieces:
                cur.append((label, piece))
                acc += len(piece)
                if acc >= args.per_chunk:
                    num = _write_map_chunk(chunks_dir, num, cur, tone,
                                           glossary, macros, ctx, args,
                                           prev_keys)
                    prev_keys = [k for _l, ks in cur for k in ks]
                    cur, acc = [], 0
        if cur:
            num = _write_map_chunk(chunks_dir, num, cur, tone,
                                   glossary, macros, ctx, args, prev_keys)
    return num


def cmd(work_dir: Annotated[str, cliutil.Argument(
            help="translation work dir (template.json / context.json "
            "inside it)")],
        per_chunk: Annotated[int, cliutil.Option(
            "--per-chunk", help="cap chunks by key count instead of total "
            "key char length (legacy; disables auto sizing)")] = 0,
        max_chars: Annotated[int, cliutil.Option(
            "--max-chars", help="cap chunks by total key char length instead "
            "of key count (single overlong key gets its own chunk; disables "
            "auto sizing)")] = 0,
        start: Annotated[int, cliutil.Option(
            "--start", help="first chunk number")] = 0,
        resume: Annotated[bool, cliutil.Option(
            "--resume", help="skip keys already covered by chunks/*.zh.txt")] \
        = False,
        out_dir: Annotated[str, cliutil.Option(
            "--out-dir", help="chunk subdirectory (default: chunks)")] = \
        "chunks",
        window: Annotated[int, cliutil.Option(
            "--window", help="context window radius per key (default 2)")] = 2,
        truncate: Annotated[int, cliutil.Option(
            "--truncate", help="max chars per context transcript line")] = 45,
        target_chunks: Annotated[int, cliutil.Option(
            "--target-chunks", help="auto: pick --max-chars for about N "
            "story+global chunks (0 = off)")] = 0,
        global_per_chunk: Annotated[int, cliutil.Option(
            "--global-per-chunk", help="cap GLOBAL/DB/UI chunks by key count "
            "(default 600; short keys, transcript lines dominate the "
            "context)")] = 600,
        context_budget_kb: Annotated[int, cliutil.Option(
            "--context-budget-kb", help="auto: keep every chunk's "
            "context.md under this many KB (default 90; 90KB+ chunks are "
            "flaky)")] = DEFAULT_CONTEXT_BUDGET_KB,
        verbose: cliutil.Verbose = False,
        quiet: cliutil.Quiet = False,
        log_file: cliutil.LogFile = None) -> int:
    cliutil.setup_logging(verbose, quiet, log_file)

    # The writers/estimators below take the parsed options as one object and
    # mutate it (auto sizing rewrites max_chars), and the tests build the same
    # shape with a stub, so keep that contract instead of threading a dozen
    # parameters through every helper.
    args = types.SimpleNamespace(
        work_dir=work_dir, per_chunk=per_chunk, max_chars=max_chars,
        start=start, resume=resume, out_dir=out_dir, window=window,
        truncate=truncate, target_chunks=target_chunks,
        global_per_chunk=global_per_chunk,
        context_budget_kb=context_budget_kb)

    work = os.path.abspath(args.work_dir)
    tpl, kinds, structure, glossary, macros, ctx, tone, chunks_dir = \
        _collect_context(work, args)
    global_keys, map_keys, _n_orphan = _collect_keys(tpl, kinds, structure)

    # auto sizing (DEFAULT): binary-search the largest --max-chars that keeps
    # the chunk count <= --target-chunks and every context.md under
    # --context-budget-kb (90KB+ context chunks are the flaky no-file
    # failures).  Explicit --max-chars / --per-chunk disable it.
    if not args.max_chars and not args.per_chunk:
        args.max_chars, n_chunks, mx, warn = _auto_sizing(
            map_keys, global_keys, ctx, tone, glossary, macros, args)
        print("auto sizing: max_chars=%d -> %d chunks, max context ~%.1fKB%s"
              % (args.max_chars, n_chunks, mx / 1024,
                 " (WARN: %s)" % warn if warn else ""))
    if not args.max_chars and not args.per_chunk:
        args.per_chunk = 450  # fallback: no story maps -> legacy key-count cap

    num = _emit_chunks(chunks_dir, args, global_keys, map_keys, tone,
                       glossary, macros, ctx)
    print("wrote chunks %02d..%02d into %s" % (args.start, num, chunks_dir))
    return 0


def _split_by_len(keys, max_chars):
    """Greedily bucket ordered keys so each bucket's total char length stays
    <= max_chars; a key longer than the cap forms its own bucket."""
    buckets, cur, cur_len = [], [], 0
    for k in keys:
        if cur and cur_len + len(k) > max_chars:
            buckets.append(cur)
            cur, cur_len = [], 0
        cur.append(k)
        cur_len += len(k)
    if cur:
        buckets.append(cur)
    return buckets


def _write_split(chunks_dir, num, chunk, title, cap,
                 max_chars=0, tone="", glossary=None, macros=None, ctx=None,
                 args=None):
    """Write a chunk, splitting into consecutive numbered pieces <= cap
    (key count) or <= max_chars (total char length)."""
    keys = list(chunk.keys())
    if max_chars:
        part = 0
        for bucket in _split_by_len(keys, max_chars):
            sub = {k: "" for k in bucket}
            num = _write(chunks_dir, num, sub, "%s [part %d]" % (title, part),
                         tone, glossary, macros, ctx, args)
            part += 1
        return num
    if len(keys) <= cap:
        return _write(chunks_dir, num, chunk, title, tone,
                      glossary, macros, ctx, args)
    part = 0
    for i in range(0, len(keys), cap):
        sub = {k: "" for k in keys[i:i + cap]}
        num = _write(chunks_dir, num, sub, "%s [part %d]" % (title, part),
                     tone, glossary, macros, ctx, args)
        part += 1
    return num


def _glossary_block(glossary):
    if not glossary:
        return ("## Glossary (mandatory)\n"
                "  (empty - 尚无词表: 人名/术语按直觉翻译, 保持全文前后一致)\n")
    lines = ["## Glossary (mandatory) - translate these EXACTLY"]
    lines += ["  %s -> %s" % (k, v) for k, v in glossary.items()]
    return "\n".join(lines) + "\n"


def _macro_block(macros, glossary):
    """Name-macro table: \\N[1] -> <actor-name> (glossary: <zh-name>).  The
    code is a macro (C++/LaTeX style substitution) - never translated; the
    raw name is shown so the agent understands the character."""
    if not macros:
        return "## Name macros (control codes)\n  None detected.  Any \\N[x] / \\P[x] / custom codes are macros - keep them verbatim.\n"
    lines = ["## Name macros (control codes = substitution references, NEVER translate them)"]
    for code, name in sorted(macros.items()):
        tr = glossary.get(name, "")
        lines.append("  %s = %s%s" % (code, name, "  (词表: %s)" % tr if tr else ""))
    return "\n".join(lines) + "\n"


def _ctx_prefix(num, title, nkeys, tone, glossary, macros, labels, carry):
    """Fixed context.md prefix: header + rules + tone + glossary + macros +
    carry-over + map list (shared by the writer and the auto-size estimator)."""
    lines = ["# Translation chunk %02d - %s" % (num, title),
             "",
             "chunk_NN.ja.txt: %d keys (one per line).  Write chunk_NN.zh.txt:"
             % nkeys,
             "exactly %d lines, 1:1 in the same order." % nkeys,
             "",
             RULES,
             "",
             tone.rstrip() + "\n" if tone else "",
             _glossary_block(glossary or {}),
             _macro_block(macros or {}, glossary or {}),
             ]
    if carry:
        lines += ["## Carry-over: this chunk continues right after the "
                  "previous chunk's dialogue (scene continuity - the lines "
                  "below are the previous chunk's tail, translated or not, "
                  "keep names/terms/flow consistent with them)", ""]
        for c in carry:
            flat = c.replace("\n", " / ").replace("\r", "")
            lines.append("  %s" % (flat if len(flat) <= 45
                                   else flat[:45] + "…"))
        lines += [""]
    if labels:
        lines += ["## Maps in this chunk", "  " + ", ".join(labels), ""]
    return lines


def _write(chunks_dir, num, chunk, title, tone,
           glossary=None, macros=None, ctx=None, args=None, carry=None):
    keys = list(chunk.keys())
    base = os.path.join(chunks_dir, "chunk_%02d" % num)
    plain_io.save_lines(base + ".ja.txt", keys)

    labels = []
    for k in keys:
        where = (ctx.get(k, {}) or {}).get("where", "")
        m = re.match(r"([^/]+)", where)
        if m and m.group(1).strip() not in labels:
            labels.append(m.group(1).strip())

    lines = _ctx_prefix(num, title, len(keys), tone, glossary, macros,
                        labels, carry)
    lines += ["## Scene transcript (dialogue in story order; [K] = key to translate; | = context line)", ""]
    lines += transcript(keys, ctx or {}, getattr(args, "truncate", 45),
                        getattr(args, "window", 2))
    with open(base + ".context.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(base + ".meta.json", "w", encoding="utf-8") as f:
        json.dump({"maps": labels}, f, ensure_ascii=False, indent=1)
    print("chunk %02d: %d keys (%s)" % (num, len(keys), title))
    return num + 1


def build_buckets(map_keys, max_chars):
    """Story-order greedy buckets by total key char length (the exact rules of
    the --max-chars path): every bucket stays <= max_chars total key chars, a
    single overlong key forms its own bucket, consecutive keys of one map are
    grouped.  Returns a list of group lists [(label, [keys])]."""
    buckets, cur, cur_len = [], [], 0
    for label, keys in map_keys:
        for k in keys:
            if cur_len and cur_len + len(k) > max_chars:
                buckets.append(cur)
                cur, cur_len = [], 0
            if not cur or cur[-1][0] != label:
                cur.append((label, []))
            cur[-1][1].append(k)
            cur_len += len(k)
    if cur:
        buckets.append(cur)
    return buckets


def _chunk_context(keys, ctx, tone, glossary, macros, args):
    """Estimated context.md size (chars) for a chunk with these keys: fixed
    prefix (rules/tone/glossary/macros) + scene transcript lines."""
    prefix = _ctx_prefix(0, "x", len(keys), tone, glossary, macros, [], None)
    tr = transcript(keys, ctx or {}, getattr(args, "truncate", 45),
                    getattr(args, "window", 2))
    head = "## Scene transcript (dialogue in story order; [K] = key to translate; | = context line)"
    # count UTF-8 BYTES, not code points: the context-budget threshold is a
    # real file size (90KB+ context.md chunks are the flaky no-file
    # failures), and Japanese-heavy transcript lines encode to ~2-3x their
    # char count.  A char-based estimate silently allows ~250KB files.
    def b(s):
        return len(s.encode("utf-8")) + 1
    return sum(b(l) for l in prefix) + len(head) + 2 + sum(b(l) for l in tr)


def _auto_sizing(map_keys, global_keys, ctx, tone, glossary, macros, args):
    """Pick --max-chars automatically: binary-search the largest value whose
    chunk count stays <= --target-chunks AND whose largest chunk context.md
    stays under --context-budget-kb (90KB+ context chunks are the flaky
    no-file failures).  Returns (max_chars, chunk_count, max_context_chars,
    warning).

    Performance note (review §4.2 "prefix sum + binary locate"): the search
    below already runs a BOUNDED number of full linear scans (two binary
    searches over max_chars, ~log2(60000/1000) ~ 6 iterations each).  A
    prefix-sum + bisect rewrite was NOT applied: build_buckets() must keep
    consecutive keys of one map grouped (a label change forces a bucket
    break), so bucket boundaries depend on the map labels, not just key
    lengths - a pure cumulative-size bisect would change the chunking and
    is protected against by test_random_build_buckets_constraints.  Measured
    on a 30k-key / 60-map job the whole sizing runs in ~0.6s, well below the
    per-invocation budget, so the added complexity is not justified."""
    if not map_keys:
        return 0, 0, 0, "no story maps"
    lo, hi = 1000, 60000
    budget = args.context_budget_kb * 1024 if args.context_budget_kb else 0

    def count_for(mc):
        n = len(build_buckets(map_keys, mc))
        if global_keys:
            n += (len(global_keys) + args.global_per_chunk - 1) \
                // args.global_per_chunk
        return n

    def ctx_for(mc):
        best = 0
        for groups in build_buckets(map_keys, mc):
            keys = [k for _l, ks in groups for k in ks]
            best = max(best, _chunk_context(keys, ctx, tone, glossary,
                                            macros, args))
        if global_keys:
            # the writer caps global chunks by KEY COUNT (global_per_chunk),
            # not by chars - mirror that split exactly so the estimate
            # matches what will actually be written.
            for i in range(0, len(global_keys), args.global_per_chunk):
                part = list(global_keys)[i:i + args.global_per_chunk]
                best = max(best, _chunk_context(part, ctx, tone, glossary,
                                                macros, args))
        return best

    a = None  # smallest mc keeping chunk count <= target (most chunks allowed)
    if args.target_chunks:
        l, h = lo, hi
        while l <= h:
            mid = (l + h) // 2
            if count_for(mid) <= args.target_chunks:
                a, h = mid, mid - 1
            else:
                l = mid + 1
    b = None  # largest mc keeping max context <= budget
    if budget:
        l, h = lo, hi
        while l <= h:
            mid = (l + h) // 2
            if ctx_for(mid) <= budget:
                b, l = mid, mid + 1
            else:
                h = mid - 1

    if a is not None and b is not None:
        mc, warn = min(a, b), ""
    elif a is not None:
        mc, warn = a, "context budget %.0fKB exceeded by the chosen sizing" \
                      % (budget / 1024)
    elif b is not None:
        mc = b
        warn = ("target %d chunks unreachable (too many keys)" % args.target_chunks
                if args.target_chunks else "")
    else:
        mc = lo
        warn = "neither chunk-count nor context budget satisfiable"
    return mc, count_for(mc), ctx_for(mc), warn


def _write_map_chunk(chunks_dir, num, groups, tone, glossary, macros,
                     ctx, args, prev_keys=None):
    chunk = {}
    labels = []
    for label, keys in groups:
        labels.append(label)
        for k in keys:
            chunk[k] = ""
    carry = None
    if prev_keys:
        # tail of the previous chunk: dialogue-ish keys only, capped
        carry = [k for k in prev_keys if _is_dialogue(k, ctx)][-CARRY_OVER:]
    return _write(chunks_dir, num, chunk,
                  "story maps: " + ", ".join(labels), tone,
                  glossary, macros, ctx, args, carry)


def _is_dialogue(k, ctx):
    """Dialogue-ish keys keep continuity: blocks, single lines, choices,
    speaker-ish names (anything with a map/event where)."""
    where = (ctx.get(k, {}) or {}).get("where", "")
    return bool(where) and not where.startswith(("System.json", "Actors",
                                                 "Classes", "Skills",
                                                 "Items", "Weapons",
                                                 "Armors", "Enemies",
                                                 "States", "Animations",
                                                 "Tilesets", "Troops",
                                                 "MapInfos", "CommonEvents "
                                                 "name"))


app = cliutil.command_app(cmd, help=__doc__)


def main(argv=None) -> int:
    return cliutil.run(app, argv, prog="gen_translation_shards.py")


if __name__ == "__main__":
    raise SystemExit(main())
