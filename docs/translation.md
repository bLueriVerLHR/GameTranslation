# RPG Maker 翻译指南（统一版）

本工具库唯一的翻译指南。它把经典全量翻译流程和残留补翻流程合并成
**一套工作流、一套参数**（2026-08 长程验证）：**每轮 10 个并行
subagent** 和 **按 90KB 上下文预算自动选档的大块**（典型约 11,000 字符/
块）。所有踩过的失败模式、QC 关卡、修复手法都记录在本文档——工具已加固、
prompt 契约已定稿，下面的数字都是实战验证过的。

涵盖：MZ/MV 静态翻译（`data/*.json`）、部分烘焙后的残留假名补翻、
插件参数文本、收尾（烘焙、QC、验证）。RPG Maker → JoiPlay 转换流水线本身
见 `docs/workflow.md`。

所有命令在终端（PowerShell / CMD）运行。需要 **Python 3.8+**（`python`
在 PATH 上）。

---

## 1. 整体原理

这些 MZ 游戏（多为日文，用 NW.js 打包成 `Game.exe`）在你能玩上翻译版
（例如 **JoiPlay**）之前有两道障碍：

1. **加密资源。** 图片/音频以 `*.png_`、`*.ogg_`、`*.m4a_` 存储。每个文件
   以固定 16 字节头 `RPGMV\x00\x00\x00\x00\x03\x01\x00\x00\x00\x00\x00`
   开头；有效载荷的前 16 字节用 `data/System.json`（`encryptionKey`）里的
   密钥做 XOR 加密。工具库解密每个这样的文件并清掉加密标志位
   （见 `docs/workflow.md`）。
2. **未翻译文本。** 游戏文本在 `data/*.json` 里。静态翻译把这些字符串就地
   替换，所以 PC **和** JoiPlay 上都是中文，无需运行时插件。

### 为什么 MTool/AI 运行时翻译文件不能静态烘焙

repack 游戏常带一个运行时替换字典如 `<title>.json`（1 万+ 条目）。它在
运行时有效（MTool hook 引擎替换最终显示的字符串），但与静态数据**结构
不兼容**：

- 对话按**每条事件命令一行**（code `401`）存储，而运行时字典的键是
  **用 `\n` 拼接的整条消息**（引擎显示时再重组）。拼接键永远匹配不上
  逐行静态数据。
- 字典还含**片段键**（助词、短感叹词），只对运行时匹配有意义。

直接把这类字典静态烘焙（旧的贪心片段回退）**会毁句子**：助词在词中被
替换，大多数行保持半日半中。所以：绝不直接烘焙运行时字典。**先提取静态
文本**，构建自己的逐行/逐消息模板，翻译它，再精确烘焙。

### 翻什么 / 不碰什么

| 范围 | 字段 / 事件码 |
|---|---|
| 整段对话消息 | 连续 `401`/`405` 命令，用 `\n` 拼接（块键） |
| 说话人名字框 | code `101`（第 4 个参数） |
| 选择肢 + 分支标签 | codes `102`、`402`（保持同步） |
| 选择帮助文本 | code `408` 注释（指令类行跳过） |
| 改名/昵称/简介命令 | codes `320`、`324`、`325` |
| 字符串变量 | code `122`（字符串操作数） |
| DB 文本 | `name`、`nickname`、`profile`、`description`、`message1..4`、`text` |
| `note` 字段 | 仅精确匹配（插件标签保持不动） |
| 系统 UI | `terms`、战斗 `message`、`commands`、装备/属性类型、`variables`、`switches` |
| 地图名、地图标题横幅、公共事件名 | `MapInfos.json`、地图 `displayName`、公共事件 `name` |
| 插件命令参数、脚本 | codes `356`、`357`、`657`、`355` — **绝不翻译** |

烘焙器**只精确匹配**（无贪心片段替换），所以被翻译的分支永远不会把片段
漏进另一个分支。

---

## 2. 工作流（提取 → 人名 → 分块 → 翻译 → 烘焙）

### 第 1 步 — 提取与合并（`tools/build_translation.py`）

```
python tools\build_translation.py <game_dir> <work_dir>
```

遍历 `data/*.json`，在 `<work_dir>` 产出工作包：

| 文件 | 内容 |
|---|---|
| `template.json` | 合并后的 `{key: ""}`，包含每个可翻译字符串 — 每个**消息块**一个键（连续 `401`/`405` 命令用 `\n` 拼接），另加选择肢、名字、帮助文本、DB/系统 UI、note、`displayName` |
| `kinds.json` | 键 → 种类（`block`、`choice`、`help`、`db-name`、`system`、`plugin`、…） |
| `structure.json` | 场景树：按故事顺序的地图 → 事件 → 有序块/选择肢（分支上下文） |
| `context.json` | 键 → `{"where": 位置, "window": ±2 句对话窗口}` — **上下文独立产物,不翻译**,分片时注入各 chunk 的 context.md |
| `names.json` | 候选角色名（名字位置 + 高频独立行） |
| `glossary.json` | 已确认的人名表（用 edit 工具维护）— 首次与 owner 商定后**只能用 edit 工具改** |
| `name_macros.json` | `\N[x]`/`\P[x]` → 角色名 宏对照表(控制码是替换引用,本身不译,名字在 DB 译) |

合并：相同字符串全局去重（在 6 张地图复用的阶段菜单消息是一个键）。
块给翻译者整条消息的上下文；烘焙器查同样的拼接字符串。

插件菜单文本：`js/plugins.js` 插件参数里含日文的字符串也提取
（kind `plugin`，`--no-plugins` 关闭），以便本地化插件菜单/UI；烘焙器
精确写回（见第 7b 步）。

### 第 2 步 — 定人名

把 `names.json` 整理进 `glossary.json`（`{"角色名": "中文名", ...}`），
翻译前与游戏 owner 确认。**首次协商后词表单 owner 维护：之后只能用 edit
工具修改**（agent 读各自 chunk context.md 里的词表快照；agent 并发写会
写坏）。同时检查人名变体（全名 vs 简称）和其他项目遗留数据（从未在事件
出现的角色 — 排除或映射为自身）。

人名控制码（`\N[1]` / `\P[1]` 与自定义 `\字母[..]` 码）是**宏，像
C++/LaTeX 替换引用** — agent 要"理解成角色 X 的名字"，但绝不翻译或改动
码本身；引用的名字在 DB 里译。`context.md` 给出宏对照表
（`\N[1] = 角色名 (词表: 中文名)`）。

### 第 3 步 — 分块（`tools/gen_translation_shards.py`）

```
python tools\gen_translation_shards.py <work_dir>                 # 默认 auto 选档
python tools\gen_translation_shards.py <work_dir> --target-chunks 55
python tools\gen_translation_shards.py <work_dir> --max-chars 11000 --window 1
```

**双文件块布局**（2026-08 定案）：

| 文件 | 内容 | 写入者 |
|---|---|---|
| `chunks/chunk_NN.ja.txt` | 仅键：**每行一个日文键**，无引号、非 JSON | 生成器，agent 绝不改动 |
| `chunks/chunk_NN.zh.txt` | **每行一个译文，与 ja.txt 逐行 1:1**（同顺序、同行数） | subagent |
| `chunks/chunk_NN.context.md` | 规则 + 写优先契约 + 语气 + 词表 + 人名宏表 + 逐键场景记录 | 生成器 |
| `chunks/chunk_NN.meta.json` | 覆盖的地图（并行度参考） | 生成器 |

转义（两个文件一致）：`\n` = 消息内的真实换行（多行块），`\\` = 单个
字面反斜杠（控制码前缀）。映射无歧义，含字面 `\n` 文本的键可安全往返。
上下文：`build_translation.py` 已提取 `context.json`（每键 ±2 行对话
窗口）；分块生成器把它打印成场景记录（`[K]` = 要译的键，`|` = 上下文
行），并把上一块的末尾对话行带进下一块（故事连续性）。词表与语气按块
注入 — 生成器绝不硬编码（绝不出现上一款游戏的语气；见 §3）。

**分块尺寸（默认自动，大块没问题）：** 生成器二分搜索最大的
`--max-chars`，使块数 ≤ `--target-chunks` 且每个 `context.md` 低于
**`--context-budget-kb 90`** 预算（90KB+ 的 context 块是 flaky
no-file 失败的温床；密集块用 `--window 1`）。写优先契约下 **每块约
11,000 键字符是验证过的尺寸**（一个 3.6 万键 / 64.7 万字符的 MZ 任务按
4500→11000 跑了 145 块；一个 1 万键任务按 4500 跑了 43 块）。单个超长键
自成一块。显式 `--max-chars` / `--per-chunk` 覆盖 auto 选档。真正的约束
是上下文预算而不是模型 — 生成器会打印所选尺寸与预期上下文大小。

**对话连续性是硬验收标准 — 分片时强制、每次分片后检查：**

- 键保持**故事顺序**（MapInfos 顺序 → 地图 → 事件 → 页 → 命令位置 →
  CommonEvents → UI/DB 最后），绝不按字母/种类乱排 — 一个场景的对话
  不能散落到无关块。
- 每键的 context.md 窗口给 ±2 句相邻对话；块的场景记录去重。
- **Carry-over**：每个故事块的 `context.md` 以**上一个故事块的末尾 8 句
  对话**（`## Carry-over` 段）开头，线性场景跨块切开也能保持连贯 —
  全新 agent 不会盲译场景中段。全局/UI/DB 块不产生 carry。
- 相邻故事块**串行处理**；只有无叙事依赖的块（不同地图 / DB 文件）可并行。
- 分片后抽查相邻块衔接：块 N 的 `## Carry-over` 必须匹配块 N−1 的尾部 —
  对不上就是分片 bug。

### 第 3.5 步 — 并行度（固定，每轮 10 个）

**每轮 10 个并行 subagent — 验证过的稳定基线，不是上限。** 9-11 都验证
稳定；写优先 prompt 下首轮成功率 ~90%+，且**与并行度无关**（取决于
prompt，不是数量）。策略：

- **每轮 10 个 agent**（默认）；轮次不超过 ~11。
- **一次失败** → 在**同一个 subagent 会话**里重试（其上下文已加载；
  全新 agent 重读一切常再次失败）— "立即写文件" 恢复率 ~90%。
- **同一块反复失败** → 简化 prompt（去掉读上下文步骤，直接下令写文件）
  再试；同一会话失败 ≤2 次后搁置，留给编排者最后统一处理。
- **轮次间不向 owner 汇报** — 全部完成后再汇报。
- 无叙事依赖的块可并行；线性场景的相邻块按顺序处理（见连续性）。

### 第 4 步 — 启动 agent 前先量体量并协商

**绝不自行启动大型翻译任务。** 每个翻译任务必须先**量体量并与用户
商定**，之后才能启动第一个 subagent：

1. **测量**：跑 `extract_remaining_text.py <built> <work_dir>`（全量任务用
   `build_translation.py`），读 `template.json` 统计 — 键数与总键字符数。
2. **估算**：块数 ≈ `总字符 / ~11000`（auto 分片最终确认；生成器打印
   实际块数）。
3. **与用户协商**再跑 agent：给出键数、块估算、预计时长；确认范围
   （全部剩余 / 跳过 / 子集）。任务较大（约 10+ 块）且用户未明确要求全量
   翻译时，**先问** — 不要自动开始。
4. **>30 块 → 不要开始。** 块数超过 30 时任务是批处理：不要启动
   subagent。在 work 目录准备 `TRANSLATION_PROJECT.md` 状态文件（已完成
   步骤、剩余任务、下一步、并行策略），**等用户明确指示**再翻译。
5. 小任务（少量块）走同一流程，但协商只需一行。

失败后恢复 / 重分：

```
python tools\gen_translation_shards.py <work_dir> --resume --start 30
```

（已被任意 `chunks/*.zh.txt` 覆盖的键跳过；剩余键重新分块，从 `--start`
编号。）

### 第 5 步 — 专用 subagent 翻译

每块一个 subagent。有效的 prompt 模式（写优先契约，每个 prompt 原样）：

- 读规则 + `chunk_NN.ja.txt` **一次**。
- **先 Write `chunk_NN.zh.txt`**（每行一个译文，与 ja.txt 逐行 1:1）—
  文件存在前绝不"思考模式"结束。**先写, 后思考, 再改**：第一动作就是
  Write，再读回、用第二次 Write 润色。最终回复 = 文件路径 + 条目数。
- 值必须是译文（绝不把日文键抄进值），保持与键**相同数量的 `\n` 转义**
  （消息窗口行数），所有控制码原样保留（`\N[x]`/`\P[x]` 是人名**宏** —
  理解为角色名，绝不译码）。
- 严格遵循词表；跟随共享术语日志。
- 只要求一行回复（计数）— 冗长汇报引诱 agent 卡住。

维护**团队术语日志**（`terms.json`）：每个 agent 汇报术语决策；你把它
追加进之后每个 prompt，保证整游戏一致。语气由游戏 owner 预先设定
（本地 `docs/table/` 每游戏 `tone.md` — 成人词表不入公开仓库，见 §6）：
- 成人场景 → 遵循 owner 认可的语气（文雅古风、流畅可读；核心名词遵循
  本地词表）；
- 剧情/揭示场景 → 保持悬念，绝不剧透伏笔/反转；
- 长度 → 保持原意；一行会溢出消息窗口时用更紧凑的说法。

### 第 6 步 — QC、修复、合并

```
python tools\merge_plain_chunks.py <work_dir> [--strict]
python tools\merge_translation.py  <work_dir> --chunks chunks_translated.json
                                   [--prefilled prefilled.json] [--sweep sweep.json]
```

1. `merge_plain_chunks.py` 把每个 `ja.txt`+`zh.txt` 对合并成
   `chunks_translated.json` 并逐块 QC：行数不匹配、值里残留假名（剥离
   控制 token）、控制码 token diff、空值、`【?】` 不确定标记、双反斜杠。
   （`--strict` 有任何问题就失败。）
2. `merge_translation.py` 叠加 `--prefilled`（MTool 精确命中）并应用
   `--sweep` 术语规则（最长优先，防 substring bomb）→ 最终
   `translated.json`；断言每个模板键都在。
3. agent 偶尔丢键/改键（转义反斜杠、编辑距离 ≤3）— 1:1 行布局下错误行数
   立刻被抓；修 zh.txt 行再合并。之后做值卫生：折叠双反斜杠、剥离
   `【?...】`、diff 控制 token。

### 第 7 步 — 烘焙（`tools/bake_translation.py`）

```
python tools\bake_translation.py <built_joiplay> <out_dir> --trs translated.json --glossary glossary.json
```

- 拷贝已构建（已解密、已压缩）的 JoiPlay 目录，无需重跑
  `build`/`audio`/`clean`。
- **只精确匹配。** 对每段连续 `401`/`405` 命令用 `\n` 拼接、查块、把译文
  拆回各命令 — 短译文用 `""` 行补齐（没有命令保留日文），长译文追加命令。
  逐行精确匹配是回退。然后处理其他码（`102`/`402`/`101`/`122`/`320`/
  `324`/`325`/`408`）、DB `DISPLAY_KEYS`、`note`（精确）、`System.json`
  UI 字段、地图 `displayName`、事件名、`MapInfos` 名。
- **插件参数**：精确匹配 `js/plugins.js` 里含日文的字符串并写回
  （解析 → 替换 → 序列化；解析失败降级为字面量文本替换）。
- **覆盖率闸门（2026-08）**：拷贝前先只读扫描，统计游戏里含假名的显示
  字符串被字典命中的比例（`coverage: N hit / M missed = X%`）。低于
  `--min-coverage`（默认 0.5）烘焙**拒绝** — 低覆盖烘焙 = 半日半中 +
  污染后续补翻（部分块值、半翻场景）。正确路线是全量翻译
  （`extract_remaining_text.py` → chunks → merge → 再 bake）；有意的
  阶段一 harvest 烘焙用 `--force`。
- **identity 条目自动剔除**：`v == k`（假名键 shadow 逐行 fallback）的
  字典条目加载时删除（某 MZ 任务：删了 123 条）。
- **名称引用检查**：`<TE:name>`/`<namePop:name>` 引用与字典同步，且结尾
  把每个引用对照游戏事件名 — dangling 引用（含因带控制码被跳过翻译的
  引用）逐一 WARN。
- **translation_kv.json** 自动归档进 `out_dir`（烘焙字典，
  `--no-kv` 关闭）— 无需手工改名。
- 向 `css/game.css` 追加 CJK 字体回退。

然后重跑 `verify --source <原版>`、`serve --test`、**新端口** HTTP 试玩
（同端口 origin 共享 localStorage），再 `compress`。

### 第 7b 步 — 菜单/插件文本与人名宏

- **插件 UI**：`build_translation.py` 提取 `js/plugins.js` 插件参数里含
  日文的字符串（kind `plugin`）。它们先进全局块（术语基础）。烘焙时只
  整串精确替换 — 功能性值（数字、布尔、文件名）不含日文，永不触碰。
  菜单文本在插件 JS 数据文件（非参数）里的游戏超出范围 — 那需要运行时
  方案。
- **人名宏**：`\N[x]`/`\P[x]`（与自定义 `\字母[..]` 人名码）是替换引用，
  不是可译文本 — 解析为 `Actors.json` 里翻译过的角色名。无需额外烘焙。

---

## 2b. 补翻残留片段（MTool 片段污染）

当随包的 MTool 字典**比游戏构建旧**，或 MTool 的片段替换留下半行时，
静态烘焙过的构建仍含假名片段。用同一套 subagent 工作流修复，但只翻译
**剩余键** — 绝不重跑全量模板（已翻译的中文行不得重译）。

脚本（通用，游戏无关）：

```
python tools\extract_remaining_text.py <built_joiplay> <work_dir>
python tools\gen_completion_shards.py <work_dir> [--max-chars 11000] [--dict <title>.json]
python tools\merge_plain_chunks.py <work_dir> --strict
python tools\merge_translation.py <work_dir> --chunks chunks_translated.json
python tools\bake_translation.py <built_joiplay> <out_dir> --trs <work_dir>\translated.json
```

`extract_remaining_text.py` 遍历 `data/*.json`，保留仍含假名的**逐行/逐字段
EXACT 键**（与 `bake_translation.py` 查的完全一致）— 假名正则
`[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]`。注意：`\u3000-\u303f` 绝不
能进"假名"正则 — 它会匹配 `。「」`（已翻译中文里也有），把模板灌满几万
假键。它还写 `context.json`（故事顺序 + ±2 窗口）、`name_macros.json`，
并提取残留插件参数文本。

**note 字段过滤（自动）**：带插件标签（`<recipe> {"material": ...}`、
`<拡張説明:...>`、任意 `<[A-Za-z_@][^>]*>`）或纯内嵌 JSON 的 `note` 是
**功能性插件数据，不是显示文本** — 从模板排除、构建里保持原样（配方里的
材料名来自已翻译的物品 DB）。只有无标签的叙事型 note 才翻译。

`gen_completion_shards.py` 用同样的块格式与尺寸（默认 `--max-chars
11000`），结尾做**合并遍历**：相邻块合并后仍不超上限的就贪心合并（左到
右），几个巨键不会产生浪费的单键块 — 同时单块上限（可靠性约束）永不被
突破。

故事顺序分块、carry-over、上下文预算、无剧透规则与第 3 步完全一致。

---

## 3. QC 现实与失败目录（踩过的一切）

### QC 清单（每关都跑）

1. **逐块**：每个 agent 返回后立即 `merge_plain_chunks.py` — 行数 ≠ 键数
   = 丢行/并行，当场定位。
2. **补丁前值卫生**：折叠双反斜杠（`\\C[27]` → `\C[27]`）、剥离
   `【?...】` 不确定标记、diff 控制码 token 键值两侧、剔除 identity
   条目（`v == k`）。
3. **合并后终检**（`final_qc.py`）：identity 值、双反斜杠、空值、全键序。
4. **最终构建上的残留假名**：`extract_remaining_text.py` 跑在**烘焙后**的
   成品上，目标 ≤ 手指数量的有意保留行。walker 必须让顶层列表 JSON
   （CommonEvents.json）走事件 walker，否则静默漏掉全部对话。
5. **豁免清单**：作者/品牌名、拟声词、游戏内标签（如场景/分类标签）、
   数字 — 预先商定，记录在 work 目录。

### 失败模式与手术级修复

| 症状 | 根因 | 修复 |
|---|---|---|
| agent 空返回 / 无文件 | 思考预算耗尽"思考模式"结束 | **恢复同一会话**，下令"立即写文件"。文件存在前绝不结束；prompt 原样写优先契约 |
| 值 = 键原文 + 译文（全块 mismatch） | agent 把键抄进了值 | `fix_key_prefix.py`：剥 `v[len(k):].lstrip("\n")`（机械、幂等） |
| 字面 `\n` vs 真实换行 | agent 把键内嵌 `\n` 写成真实换行 | `fix_literal_nl.py`（单行键：`v.replace("\n", "\\n")`）/ `fix_dbl_nl.py` |
| 键尾 `\n` 丢失 | DB 描述丢尾部换行 | 把键尾 `\n` 补回值尾 |
| `===KEY===` 分隔符全丢 | agent 写成一个大 blob | 仅当行数 == 键数且无多行键时按行重建 1:1 |
| **静默漏键错位（最危险）** | agent 跳过一个键，之后每个值都错位一格 | 把 `keys[i]` 与 `entries[i]` 并排打印，找到错位起点与缺失键，在准确索引插入译文，**丢弃所有先前错插的条目**（后续移位会变成毒丸） |
| 控制码整块丢失且声称保留 | agent 自述不可信 | `\TA_` 类码总在行首 → 机械前缀补回；QC 必须 diff 控制 token；prompt 要写"数码，别信感觉" |
| `\N[1]` 被硬编码成人名 | agent 写角色名代替宏 | 恢复宏（每行只补缺失数量） |
| `\RB[a,b]` 注音参数被译 → QC 误报 | 参数被合理翻译 | QC 改用**签名**比较（token 名 + 参数个数，忽略参数内容），且**排序后比较**（agent 偶尔重排码序，渲染安全） |
| `【原文】` 被误报为 `【?】` | 游戏文本合法用括号 | UNCERTAIN 正则只匹配 `【...?...】` |
| 幻觉添加行（`<hideIfOwned>` 类） | agent 脑补内容 | 值行数归一化到键（补 `""`、截断多余） |
| 值含假名片段 | 部分翻译 | 真翻译，绝不做字符替换（`clean_kana_ticks.py` 对日文有破坏性 — ん→嗯、ッ→!；只能跑在中文带尾缀残留的值上，绝不碰真实日文片段，绝不碰 kind=plugin） |
| 语境误译（【?】或可疑措辞） | agent 缺场景上下文 | 去 `data/` 定位键（地图/CommonEvents 相邻 `401` 行），读前后 5 行，手工定稿 |
| 脚本跑两遍 / 二次污染 | 修复脚本跑两次 | 修复脚本必须幂等或只跑一次 |

### 编排者的坑（同样记录）

- 任何修复脚本跑两遍 = 双重污染。
- 修错位时先把 `keys[i]`/`entries[i]` 并排打印，确认错位起点**和**缺失键
  再动手；"先插了再说"会把文件搞得更乱。
- PowerShell 转义：用 `python -c "..."` 写正则会二次转义 `\`；诊断一律
  写成 .py 文件。
- `re.sub` 替换串含 `\N` 会报 bad escape；用 `lambda m: ...`。
- plain 文件重写格式：条目间 `\n===KEY===\n` — 用
  `"===KEY===\n".join(parts)` 构建，不是 `MARK + "\n".join(...)`
  （会毁文件）。

### QC 现实（来自补翻实战）

- 第一道 QC 门永远是**行数**；其他都是次要。
- agent 写原始 `\C[27]`（单反斜杠）→ 文件里是单个 `\` 而应为 `\\` —
  卫生遍历折叠/反转义它。
- agent 偶尔**整条丢掉含原始控制码的键**（`\C[14]`）— 行数不匹配会抓；
  手工补。
- `\n` 行数必须与键完全一致。
- 必须**保持原样**（绝不翻译、绝不"修复"）的假名误报：
  - 控制码参数：`\fn[字体名]` 字体名、`\F1[n]`、`\C[xx]`；
  - note 里的插件标签参数（`<拡張説明:…>` 分类参数、`<反転なし>`、
    `<一時自動蘇生>`）；
  - **音频/头像文件名**：codes `250`/`241`/`249` 的 SE/BGM/ME
    `parameters[0].name`、地图 `bgm`/`bgs` 的 `name`、code `101`
    `parameters[0]` 的头像文件名；
  - 消音 gag 标记（`■ィ■■`）和故意的 mojibake gag。
- 烘焙后重扫对话行（401/405，剥离控制参数）。

---

## 4. 术语一致性手册

### 4.1 MTool 字典内部不一致（预填前必须先审计）

随包字典经常自相矛盾（一个物品/地点/角色有 2-4 种译法）。用字典预填前
审计：同一日文键族的不同译文（同一物品名三种译法、一个条目音译另一个
意译），每族定一个（语义匹配或最高频），其余用 sweep 统一。常见分歧类：
品牌/药名（Z / X 后缀）、食物、地名、带敬语的名字。还要检查**作者自身
的不一致**：同一角色全文两种写法 — 按 owner 确认的词表统一。

### 4.2 Substring bomb（sweep 规则）

目标串是另一条规则目标的前缀时产生垃圾：`色经验值→色色经验值` 会命中
已 sweep 出的 `色色经验值` → `色色色经验值`。规则：任何目标包含另一规则
目标的替换必须顺序敏感或整词匹配；sweep 后全库搜目标串确认无畸形产物。

### 4.3 Identity 值（value == key）

中日同形汉字（主人公/命中率/防御力/就寝前）可接受；日文特有词必须翻
（茶臼位、逆向正常位、普通防具、BGS音量）。场景/开关/变量名也在模板里
（如体位名）— 别因为像"内部标签"就跳过。

---

## 5. 按名称查找的引用只翻一边会坏

**烘焙后必须检查按名称查找的引用成对翻译。** 按**显示名**解析实体的插件
标签，在被引名翻译了而引用没翻（或反之）时坏掉：

- `<TE:name>`（TemplateEvent）— 事件 note 带模板名；模板地图的事件名被
  翻译 → 按名查找失败 → 无条件 autorun 事件永不擦除 →
  `isEventRunning()` 恒 true → **玩家永远无法移动**。
- `<namePop:name>` 气泡名、`callEventByName`、
  `searchDataItem(...,'name',...)`、BalloonPlus 气泡名、MPP_ChoiceEX
  标签文本。

`bake_translation.py` 用字典同步 `<TE:>`/`<namePop:>` 引用
（`_translate_note_refs()`，跳过含控制码的引用），结尾自动把每个引用对照
游戏事件名 — dangling 引用（含因带控制码被跳过翻译的）WARN。其他插件：
`rg` 扫按名称查找的模式，两侧一致地翻译。

---

## 6. 每游戏资料留本地（不进公开仓库）

每游戏翻译资料 — `glossary.json`、`tone.md`、`notes.md` 与成人词表 — 在
`docs/table/`，该目录 **gitignored 且绝不推送**（游戏名与成人词汇不进入
公开仓库）。work 目录副本（`<work_dir>/glossary.json`、`<work_dir>/tone.md`）
是活文件；项目收尾时同步到本地 `docs/table/` 每游戏子目录。**翻译会话开始
前先查 `docs/table/<Game>/`**：存在每游戏子目录就加载其 `glossary.json` /
`tone.md` / `notes.md` 进工作流（并用它们种子化 work 目录）；本地目录是
既往游戏术语的权威仓库。通用教训写在本指南。

---

## 7. 故障排查

| 症状 | 修复 |
|---|---|
| subagent 无返回 / 无输出文件 | **恢复同一会话**并下令立即写文件 — 新 agent 常以同样方式失败。块过大就重分剩余键更小：`gen_translation_shards.py <work_dir> --resume --start N`（auto 选档，或 `--context-budget-kb 60` 收紧上下文） |
| 上下文文件过大 → agent 反复卡住 | 压缩：`--window 1`、45 字符截断、窗口去重、context 词表上限 ~40 条；`context.md` ≤ ~90 KB（90KB+ 密集 = no-file 失败） |
| zh.txt 行数 ≠ ja.txt 行数 | agent 丢行/并行。修 zh.txt 行（绝不碰 ja.txt），重跑 `merge_plain_chunks.py`。丢含控制码的键（`\C[14]`）同样表现 — 手工补 |
| zh.txt 含原始 `\C[27]`（单反斜杠） | 按转义规则字面反斜杠必须写 `\\`；修该行再合并 |
| 输出缺某些键 | 1:1 行布局下缺键 = 行数不匹配（上条）。否则块被拆到多个 zh 文件 — 每块独立合并 |
| 消息窗口文本溢出 | 值行数多于键 → 追加命令；少 → 补空行。翻译时保持行数相等 |
| 中文显示方块 | 烘焙器向 `css/game.css` 追加 CJK 字体回退。仍不行就装 CJK 字体（微软雅黑 / Noto Sans CJK） |
| 实际是文件名/标签的"残留假名" | `\fn[字体名]`、SE/BGM/ME `parameters[0].name`（codes 250/241/249）、地图 `bgm`/`bgs` 的 `name`、code 101 `parameters[0]` 头像文件名、note 插件标签参数 — 绝不翻译；假名检查前先剥离控制 token（见 §2b） |
| 插件参数里的菜单文本没翻 | 只有 `build_translation.py` 没带 `--no-plugins` 且字符串含日文时才提取（kind `plugin`）；重跑提取、翻译、重烘焙。插件命令参数（codes `356`/`357`/`657`/`355`）仍绝不静态翻译 |
| 选择肢失效（分支走错） | codes `102` 与 `402` 共享键，两侧自动同步 |
| 翻译后玩家无法移动（`isEventRunning()` 恒 true、事件 `_starting` 卡住） | **TemplateEvent `<TE:name>` note 引用失配。** 用 `bake_translation.py` 重新烘焙（它同步 `<TE:>` 引用并对 dangling 引用 WARN）— 见 §5 |
| `\N[1]` 类名字保持日文 | 那是宏：显示文本来自 `Actors.json` — 角色 `name` 必须翻译（是普通 DB 键）。码本身绝不译 |

---

## 8. 备注

- 只翻译 `data/*.json`（外加 `js/plugins.js` 里含日文的插件参数字符串）；
  其余 `js/plugins.js` 结构不动。事件 `note` 字段只翻功能性引用内部：
  `<TE:name>`/`<namePop:name>` 引用与字典同步（跳过含控制码的引用），
  note 其余内容保持不动。
- 烘焙器用 `indent=2` 重写所有 `data/*.json`（无害）。
- 原版游戏保持不动；在 Temp 目录工作
  （`%LOCALAPPDATA%\Temp\opencode\`），成品放交付目录
  （见 `docs/workflow.md`）。
- 若之后修复了值，构建里已经是旧值 — 按键匹配的补丁不会重新生效；
  用 旧→新 值映射反向打补丁。
