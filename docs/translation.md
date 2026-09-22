# 翻译工作流 v2（现行，RPG Maker MZ/MV）

> 2026-09 定案并在真实作品上跑通（全量翻译 → 五道门禁全绿 → 烘焙 → 试玩 → 交付）。
> v2 取代 v1 的「切块 → 每块一个 subagent → 逐行对齐 → 合并 → 烘焙」管线；
> v1 的流程描述已移入 `docs/archive/translation-v1.md`（**历史归档，不要照它执行**），
> 它积累的失败模式与修复手法仍然有效，已并入 `docs/translation-qc.md`。

**本文件 = 怎么做（流程与命令）。** 相邻两册各管一件事：

| 想知道 | 看 |
|---|---|
| 键表/译文库/控制码/写回/提取范围/门禁定义 | `docs/translation-data.md` |
| 踩过的坑、QC 清单、故障排查 | `docs/translation-qc.md` |
| v1 流程与旧工具链 | `docs/archive/translation-v1.md` |
| 本地词表/语气/字体放哪 | `docs/reference/local-layout.md` |

## 1. 一条链、两个角色

| 角色 | 负责 | 不负责 |
|---|---|---|
| 主智能体（编排） | 机械活：提取键表、推导控制码表、转 JSON、跑五道硬门禁、烘焙、字体、交付 | 不做任何语言判断 |
| 翻译子智能体（**一个**） | 语义活：人名/语气草案与样章、分块翻译、二义记录、回改决定 | 不写 JSON、不做转义、不改构建 |
| 工具（`translation/`） | 以上两者之外的重复劳动 | — |

父子两界靠**文件信箱（持久状态✓ 断线/重开都不丢 ✓）+ harness 消息（即时问答 ✓）**。


## 2. 流水线（命令）

```
python -m translation.cli prepare <game_dir> <work_dir>      # 提取 keys.jsonl + 控制码表 + 骨架 + MISSION.md
                                                            # 可选 --note-tags A,B：把这两个插件 note 标签的载荷也提取（见下）
python -m translation.cli slice  <work_dir> --start N --count M --lean --out <file>   # 取一批（lean=无前后文）
python -m translation.cli slice  <work_dir> --count M --lean --todo --out <file>      # 只取还没译的键（预填后必用）
python -m translation.cli prefill <work_dir> <runtime.json> [--out <batch>]            # 从随包运行时字典精确匹配预填
python -m translation.cli append <work_dir> --batch <file> --fix-leading --note "..."  # 校验后原子追加
python -m translation.cli pending <work_dir> --id X --why "..."        # 安全记录待决（转义由工具做）
python -m translation.cli decide  <work_dir> --all-open --reason "..."  # 追加式裁定（历史保留）
python -m translation.cli to-json <work_dir>            # raw 译文库 → translated.json（**唯一转义点**）
python -m translation.cli gates   <work_dir>            # 五道硬门禁
python -m translation.cli rewrite <work_dir>            # 执行 rewrites.jsonl 全量回改
python -m translation.cli bake    <game_dir> <work_dir> [--font-only]  # 按 id 写回 + 统一字体 + KV 归档
```

### 预填（repack 自带运行时字典时先跑）

repack 常带一个运行时替换字典（`<title>.json`、`AI翻译.json`、`…翻译文件.json`…）。
**绝不直接烘焙**（键是运行时形态：控制码被剥、整条消息用 `\n` 拼接、还含片段键），
但值本身就是 owner 已经看过的译文，可以安全地用来**预填**：

```
python -m translation.cli prefill <work_dir> "<游戏目录>\<字典>.json"
python -m translation.cli append  <work_dir> --batch <work_dir>\prefill.batch.txt --fix-leading --note "harvest"
python -m translation.cli status  <work_dir>     # 看还剩多少
```

- 只做**精确匹配**：先整串、再「剥掉首尾控制码后」匹配（命中则把值重新包回
  那串控制码）；**绝不**做子串/逐步缩短的贪心匹配（那是毁句子的老路）。
  控制码夹在行中间、字典值自带控制码等情形各自单独计数，留给执行者。
- 预填结果写成**批次文件**而不是直写译文库：`append` 仍是唯一写入口，每个预填值
  跟手写的一样过五道门禁；会撞门禁的候选在 `prefill` 阶段就被剔除并分类报告
  （否则两万条的批次会因一条不合格而整体被拒）。
- 预填后执行者用 `slice --todo`（跳过已有译文的键）取活，不用自己数 `--start`。
- 报告里的 `harvested / missed / rejected_by` 就是「还剩多少活」的实话；
  `missed` 很多通常是字典覆盖不足或键形不同，不是脚本坏了。


## 3. 统一字体（交付硬要求）


按本地字体策略表（位置与 schema 见 `docs/reference/local-layout.md` §4–5）：MV 改 `fonts/gamefont.css` 单一 face → 简中字体（原字体保留）；
**并且必须一并查插件层**——真机上就撞到过：消息插件带按语言切换的字体参数
（`Font Name CH = "SimHei, Heiti TC, sans-serif"`），于是对白用系统黑体、界面用 GameFont，
看起来就是「两套字体」。CSS 层面的替换救不了它：字体名是插件参数。
还可能有插件 JS 里硬编码的 `font-family`（HUD 自建 HTML 的 CSS）。三处都要统一。


字体策略（`required` / `auto` / `preserve`、字体清单与校验、已有翻译默认
保留原字体）见 `docs/reference/local-layout.md` §4–5；本地字体策略表给出
各引擎的具体改动点。

## 4. 未来改进方向（TODO — 2026-08 定案，下款游戏开工前实现）

以下三条已在 2026-08 某 MZ 全量翻译会话中验证必要性与收益（实测数据
见各条），作为**下一款游戏翻译的默认流程目标**。实现后同步更新本文档与
`AGENTS.md` 对应章节。

### 4.1 UI/DB 键提取时去重（省 ~85% 的重复翻译）

- **问题**：`build_translation.py` 的 structure 层按位置生成键，同一
  文本（多为 UI 词条/选择肢/短提示，如状态词、开关名等短标签）在
  每个出现位置各算一键，全部重复翻译。实测：58,307 个位置里只有
  8,578 个唯一文本，**49,729 次翻译是浪费的**（占总量 ~85%）。
- **方案**：`build_translation.py` 生成 structure 时对 `db`/`ui`/
  `choice` 类按键文本合并（同文本 → 单键 + 记录全部出现位置）；
  **剧情 `block` 键保持每处独立**（同句台词在不同场景语境不同，
  禁止合并 — 与 §4 对话连续性一致）。
- **写回安全**：bake 按文本精确匹配，单键译文自动覆盖所有位置，无
  丢失风险。
- **副作用**：chunk 数大幅下降（本作 128 → 预计 ~50），翻译耗时减半。
- **注意**：合并只影响提取层；`context.json` 的 where 记录多个位置，
  UI chunk 的场景标注以位置列表为准。

### 4.2 变量/人名宏占位符化（消灭"数斜杠"错误）

- **问题**：`\N[x]`/`\P[x]`/`\V[x]` 等宏嵌在键里，agent 必须数反斜杠、
  merge 必须 diff 控制码 token；长键（`【\N[1]】\F[57]\AA[F]「…」`）
  极易数错，且部分游戏曾因此产生错误。
- **方案**：分块写 `ja.txt` 时**仅对变量/人名宏**（`\N`/`\P`/`\V`）
  抽成占位符（如 `\N[1]` → `§N1§`，`\V[3]` → `§V3§`），**其余控制码
  原样保留**（占位符用 `§…§` 前缀标记避免与键内字面 `{..}` 冲突）；
  `merge_plain_chunks.py` 按出现顺序还原；QC 从"数斜杠"变成"数占位符"。
- **范围收敛**：只抽变量/人名宏（角色名引用、数值变量），`\F`/`\AA`/
  `\FH` 等自定义码不动 — 改动面小、还原逻辑简单。

### 4.3 UI 定名正确性（按游戏内玩法含义定名，非字面直译）

- **问题**：UI 键太短、无上下文，agent 只能字面翻译，**选不对游戏内
  的正确名字**。实例：某词的日文直译是"保存"，但该游戏为了游戏性把它
  做成了"使用保存药水"这一动作（物品/事件里使用）— 直译导致玩家看到
  的错误名。
- **方案（两层）**：
  1. **玩法大纲 `outline.md`**：从 `context.json` 的 where 位置 +
     MapInfos 地图名 + 事件名统计**自动生成**，owner 补充一两句玩法
     要点（如"保存需要消耗保存药水"）；注入每个 UI chunk 的 context，
     让定名与翻译 agent 都理解游戏机制。
  2. **UI 术语骨架 `ui_skeleton.json`**：提取后先跑一轮**带大纲的
     定名轮**（小量 subagent），为高频 UI/DB 键定"游戏内正确中文名"；
     `merge_translation.py` 以 prefilled 最高优先级加载骨架，翻译
     agent 只能沿用不能改 — 选对名字从"碰运气"变成"有机制保证"。
- **验收**：UI chunk 的值与骨架零冲突；游戏内高频界面词（菜单/物品/
  状态/事件结果提示）抽样核对与玩法机制一致。

## 5. 归档指引

- v1 的**流程**（切块 → 每块一个 subagent → 逐行对齐 → 合并 → 烘焙）：
  `docs/archive/translation-v1.md`。**不得再用于 MZ 翻译**；非 MZ 引擎
  （Tyrano / Wolf / KiriKiri）的提取/写回链仍按各自指南执行。
- v1 的**失败模式、QC 关卡、术语审计、故障排查**：已并入
  `docs/translation-qc.md`（仍然有效，按引擎无关的教训阅读）。
- v1 的**补翻链**（`extract_remaining_text.py` → `gen_completion_shards.py`
  → merge → bake）：见归档；当前 MZ 补翻优先用 v2 的 `prefill` +
  `slice --todo` + `append`。
