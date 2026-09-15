#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace.py - the translation workspace skeleton and the subagent's MISSION.

The parent (orchestrator) prepares the *mechanical* half of a workspace: the
extracted key list, the derived control-code table, the name candidates and
the empty state files.  The subagent owns the *semantic* half.

`MISSION.md` is the hard-coded half of the subagent's prompt: the workflow and
the specific rules are written down (they are the contract), while every
language decision - word choice, register, sentence shape - is deliberately
left to the translator.  It is written in Chinese because it is prompt content
for a Chinese translation task, not code.
"""
import io
import json
import os

from . import rawlib

__all__ = ["STATE_FILES", "scaffold", "mission_text", "status_summary"]

#: The five files the subagent maintains; the parent only ever reads them.
STATE_FILES = {
    # Empty on purpose: everything before the first `@@@id@@@` header must stay
    # comment-free so no value can ever be mistaken for a note.  The format is
    # documented in MISSION.md instead.
    "translations.raw.txt": "",
    "progress.jsonl": None,
    "pending.jsonl": None,
    "rewrites.jsonl": None,
    "memory.md": (
        "# 记忆（上下文压缩前必须先把结论写在这里）\n\n"
        "## 已见剧情 / 人物关系\n\n## 术语与专有名词（含决定理由）\n\n"
        "## 已定的语气与文风\n\n## 后续需要留意的伏笔\n"),
    "decisions.md": (
        "# 已定译法（每条形如：术语/人名 -> 译文 —— 理由/出处）\n\n"
        "## 人名与称呼\n\n## 术语\n\n## 语气与文风\n\n## 成人内容处理\n"),
}


def _template(name):
    body = STATE_FILES.get(name)
    return body if body else ""


def scaffold(work_dir, stats=None):
    """Create the workspace skeleton (idempotent: never overwrites content).

    Returns the list of files that were created.  Existing files are left
    untouched so a resumed run cannot lose the subagent's work.
    """
    created = []
    for name in ("keys.jsonl", "control_codes.md", "names_candidates.json",
                 "stats.json") + tuple(STATE_FILES):
        path = os.path.join(work_dir, name)
        if os.path.isfile(path):
            continue
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_template(name))
        created.append(name)
    for extra in ("allow_kana.json",):
        path = os.path.join(work_dir, extra)
        if not os.path.isfile(path):
            with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"items": [], "note": (
                    "白名单：译文里确实需要保留假名的条目，每项 "
                    '{"match": "字面串或 re:正则", "reason": "为什么"}')},
                    handle, ensure_ascii=False, indent=1)
                handle.write("\n")
            created.append(extra)
    if stats is None:
        path = os.path.join(work_dir, "stats.json")
        if os.path.isfile(path):
            with io.open(path, encoding="utf-8") as handle:
                stats = json.load(handle)
    mission = os.path.join(work_dir, "MISSION.md")
    with io.open(mission, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(mission_text(work_dir, stats or {}))
    if "MISSION.md" not in created:
        created.append("MISSION.md(rewritten)")
    return created


def mission_text(work_dir, stats=None):
    """The subagent's task order: workflow and rules hard-coded, wording free."""
    stats = stats or {}
    keys = stats.get("keys") or 0
    kinds = stats.get("by_kind") or {}
    kind_line = ", ".join("%s %d" % (k, v) for k, v in sorted(kinds.items()))
    codes = stats.get("codes") or {}
    code_top = ", ".join("\\%s %d" % (k, v) for k, v in
                         list(codes.items())[:8])
    return """# 翻译任务书（MISSION）

你是**本次翻译的唯一负责人**：从工作区取出待译内容，翻译，产出可直接烘焙的译文库。
主智能体只做机械收尾（转 JSON、跑门禁、烘焙），**不做任何语言判断**：所有措辞、语气、
句式由你决定。

## 0. 硬规则（违反即返工）

1. **只写译文库 `translations.raw.txt`**（追加写入），以及你自己的状态文件（见 §3）。
   **不要写、不要改 `keys.jsonl`**，也不要输出 JSON —— JSON 转义是主智能体的活，你写的
   一切保持原样（真换行就是真换行，反斜杠就是反斜杠）。
2. **控制码一字不动**：`\\c[1]`、`\\px[200]`、`\\nc<名字>`、`\\{`、`\\.` 等是引擎指令，
   必须原样、同序、同参数出现在译文里。数量/顺序/参数不一致 = 门禁失败。
3. **原文是键，译文是值**：值必须是中文译文，**不得把日文原文当译文交上去**（除白名单，
   见 §5）。不确定就写进 `pending.jsonl`，不要留日文。
4. **id 不许改、不许造**：只能使用 `keys.jsonl` 里给的 id。
5. **不许虚报**：没翻完就说没翻完，坏了就说坏了。门禁会数出来。
6. **小块推进**：一次只处理一小块（一个场景里的 20~40 条），翻完立刻落盘，再继续下一块。
   不要一次性翻一大段（会超输出上限，也会丢上下文）。
7. **记忆先落盘再压缩**：上下文吃紧时，先把结论写进 `memory.md`，再继续。

## 1. 输入（工作区里）

- `keys.jsonl`：待译清单，**按故事顺序排列**，每行一条：
  `id`（唯一键，写译文库时用）、`seq`（故事序）、`kind`（map/common/troop/db/ui/plugin）、
  `where`（人可读位置）、`ja`（原文，控制码字面）、`speaker`、`prev`/`next`（同场景前后文窗口）。
  - `prev`/`next` 只是**上下文**，不是要翻的内容；要翻的只有 `ja`。
- `control_codes.md`：本作控制码表（从游戏自身 JS 推导，含派发位置与作者注释）。
- `names_candidates.json`：人名候选（含出现次数与来源）。**人名译名必须先定草案**（§4）。
- `stats.json`：本次提取的统计（键数、按类型分布、控制码频次、被跳过的项）。

规模参考：本次共 **%(keys)d** 条（%(kinds)s）；高频控制码：%(codes)s。

## 2. 译文库格式（唯一的产出）

```
@@@data/Map003.json#events[2].pages[0].list[7].parameters[0]@@@
这是译文，可以在这里换行，
\\c[1]控制码原样照抄\\c[0]。
@@@<下一个 id>@@@
...
```

- 头行下面到下一个头行之间的**全部内容**都是这条的译文；空行也算内容。
- 译文里**不得出现以 `@@@` 开头的行**。
- 追加写：翻完一条（或一小块）就追加，别攒着。断点 = 最后一个完整头行。

## 3. 你的状态文件（内存靠不住，落盘为权威）

| 文件 | 何时写 | 内容 |
|---|---|---|
| `translations.raw.txt` | 每翻完一小块 | 译文本体（§2） |
| `progress.jsonl` | 每翻完一小块 | `{"seq": 1234, "id": "...", "at": "场景描述"}` |
| `memory.md` | 压缩上下文前、每幕结束时 | 已见剧情/人物关系/术语/口气/伏笔 |
| `decisions.md` | 每次定下译法 | 人名、术语、语气、成人内容处理（附理由） |
| `pending.jsonl` | 遇到二义/不确定 | `{"id": "...", "ja": "...", "candidates": [...], "why": "...", "status": "open"}`（追加式：同一 id 后写的一条覆盖前面的状态，所以解决时再追加一条 `status: resolved` 即可，不用改旧行） |
| `rewrites.jsonl` | 决定回改前文时 | `{"old": "...", "new": "...", "reason": "...", "ids": [...]?}`（**由工具执行全量替换**） |

## 4. 工作流程（照做）

1. **侦察**：读 `control_codes.md`、`stats.json`、`names_candidates.json`，抽查若干场景的
   `ja` 与 `prev`/`next`，写出**人名/称谓/语气/文风草案**。
2. **样章**：挑一小段含人名、称呼、术语与成人场景的内容，按草案译出样章。
   **把草案 + 样章交给主智能体与 owner 拍板**（这是唯一必须等的环节）；拍板结论写入
   `decisions.md`。**没拍板不要全量开工。**
3. **分块翻译**：按故事顺序推进，一小块一个场景；用 `prev`/`next` 维持对话连贯
   （人称、指代、语气不跳）。相邻场景必须按顺序处理，不要跳着翻。
4. **回改**：后面发现新事实（人名写法、身份、伏笔）要改前面时，**只写 `rewrites.jsonl`**，
   不自己全库扫。工具会执行并给出影响面报告。
5. **二义与不确定**：写 `pending.jsonl`，**不要停**；到场景边界/每完成若干块，把未决清单
   汇总发一条消息给主智能体。主智能体能自决的当场答，需要 owner 的集中呈报。
6. **交付**：全部翻完后自查一遍（覆盖率、控制码、假名残留、pending 是否清零），
   然后通知主智能体跑门禁。

## 5. 门禁（主智能体跑，全绿才烘焙）

1. **覆盖**：`keys.jsonl` 每条都要有非空译文。
2. **控制码**：每条译文的控制码序列与原文**逐字一致**（数量/顺序/参数）。
3. **假名残留**：译文里的假名必须写进 `allow_kana.json` 白名单并附理由
   （拟声词、注册商标、必须保留的固定写法等）。
4. **待决清零**：`pending.jsonl` 每条都要有结论（`status` = resolved/decided/wontfix）。

## 6. 允许你自由发挥的部分

用词、语感、句子长短、口语与书面语的取舍、敬语层级、拟声词写法、场景气氛 —— 这些是
翻译的核心判断，**由你决定**；一旦定下就写进 `decisions.md` 并保持一致。规则只约束
「怎么交付」，不约束「怎么翻」。
""" % {"keys": keys, "kinds": kind_line or "-", "codes": code_top or "-"}


def status_summary(work_dir):
    """One-glance progress: translated keys, open questions, gate state."""
    from . import mvkeys
    keys_path = os.path.join(work_dir, "keys.jsonl")
    if not os.path.isfile(keys_path):
        return {"ready": False, "reason": "keys.jsonl missing (run extract)"}
    keys = mvkeys.load_keys(work_dir)
    values = rawlib.read_library(os.path.join(work_dir, rawlib.LIBRARY_NAME))
    ids = {entry["id"] for entry in keys}
    translated = sum(1 for key in ids if (values.get(key) or "").strip())
    progress = rawlib.read_jsonl(os.path.join(work_dir, "progress.jsonl"))
    pending = rawlib.read_jsonl(os.path.join(work_dir, "pending.jsonl"))
    open_pending = [item for item in pending
                    if (item.get("status") or "open") not in ("resolved",
                                                             "decided",
                                                             "wontfix")]
    report = {"ready": True, "keys": len(keys), "translated": translated,
              "percent": round(100.0 * translated / max(1, len(keys)), 2),
              "library_blocks": len(values),
              "unknown_ids": len([k for k in values if k not in ids]),
              "progress_marks": len(progress),
              "pending": len(pending), "pending_open": len(open_pending)}
    gate_path = os.path.join(work_dir, "gate_report.json")
    if os.path.isfile(gate_path):
        with io.open(gate_path, encoding="utf-8") as handle:
            report["last_gates_ok"] = json.load(handle).get("ok")
    return report
