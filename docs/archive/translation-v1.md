# 附：v1 翻译流程（已退役 — **历史归档，不要照它执行**）

> ⚠️ **MZ/MV 翻译一律走 `docs/translation.md` 的 v2**（`translation/` 模块 +
> MISSION.md + 五道门禁）。本文件是 v1（切块 → 每块一个 subagent → 逐行
> ja/zh 对齐 → 合并 → 烘焙）的流程归档，只在排查**非 MZ 引擎**（Tyrano /
> Wolf / KiriKiri）的 chunk 链时查阅。
>
> v1 积累的失败模式、QC 清单、术语一致性审计已并入
> `docs/translation-qc.md`（那些教训与引擎无关，仍然有效）；
> 数据契约与门禁定义见 `docs/translation-data.md`。
>
> 下文的具体数字（字符数、成功率、块数）都是**某一套条件下的历史标定
> 值**，换了模型、harness 或游戏体量就要重新测。


本工具库唯一的翻译指南。**当前流程 = 本文上半部分的 v2**（一个翻译执行者 /
单写者 + 文件信箱 + 五道硬门禁）；下文保留 **v1 切块流程** 的完整教训
（**已退役，仅作历史参考**）：v1 按 90KB 上下文预算自动选档切块（标定值
约 11,000 字符/块）。所有踩过的失败模式、QC 关卡、修复手法都记录在本文档。
下文的具体数字（字符数、成功率）都是**某一套条件下的历史标定值**，换了
模型、harness 或游戏体量就要重新测（生成器会打印实际的块数与 context 大小）。

涵盖：MZ/MV 静态翻译（`data/*.json`）、部分烘焙后的残留假名补翻、
插件参数文本、收尾（烘焙、QC、验证）。RPG Maker → JoiPlay 转换流水线本身
见 `docs/workflow.md`。Wolf RPG（ウディタ）翻译走同一条 chunk/subagent
管线，但**提取/回写/编码完全不同**，见 `docs/wolfrpg.md`（含
`tools/build_wolf_translation.py` 与 `tools/apply_translation_to_patch.py`）。
KiriKiri（吉里吉里）同理走统一管线 + 独立提取/写回/patch.xp3 打包，
见 `docs/kirikiri.md`（含 `tools/build_ks_translation.py` /
`tools/apply_ks_translation.py` / `tools/qc_ks_kana.py`）。

本指南的命令同时给出 Windows（PowerShell / CMD，`python`）与 WSL/POSIX
（bash，`python3`）两种写法；路径分隔符按所在平台写。需要 **Python 3.10+**
（与 `pyproject.toml` 的 `requires-python` 一致），解释器用项目 venv：
POSIX 为 `.venv/bin/python`，Windows 为 `.venv\Scripts\python.exe`。

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
| 插件命令参数、脚本 | 功能性部分绝不翻译：codes `356`/`657`、`357` 的日文命令名（`parameters[2]`，插件按名匹配）、含假名但不在引号内的脚本行。**显示部分要译**（见下）：`357` 参数 dict 里的假名字符串值、code `122` 脚本操作数（存进变量的字符串字面量）、`355`/`655` 引号内含假名的脚本行（如 `BattleManager._logWindow.addText('...')`） |
| 数据库内战斗事件 | `Troops.json` 等 DB 文件里的 `pages[].list[]` 命令列表（与地图事件同规则） |

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

**位置感知键（2026-08 定案 — 不去重）：** 同一原文出现在不同位置
（地图/事件/页/命令索引，或 DB 条目的字段路径）时，除了首个出现的
**裸键**（原文），每个后续位置生成独立键 `原文\x1f<loc>`（loc = 稳定
遍历路径，如 `Map001.json#ev0#pg1#c12`、`Skills.json[16]#message1`、
`js/plugins.js#插件名#参数名`）。原因：同一句话在不同场景的语境不同，
意思可能不同，必须允许按位置分别翻译。规则：

- 裸键保留（向后兼容：旧字典 / bake 回退路径）；loc 键优先匹配。
- **人名/称呼类短键**（≤14 字符、无控制码、纯名字）**不生成 loc 变体**
  — 它们按词表统一翻译，不是语境敏感文本（一个角色名在数千处出现时
  不必拆成数千个键）。
- 翻译 agent 在 ja.txt 里看到带 `\x1f` 位置后缀的键行：**整个行是键**，
  译文只译分隔符之前的日文正文，位置标记绝不写进译文。
- 烘焙器 `exact_loc()`：先查 `原文\x1f<loc>`（位置专用译文），再回退
  裸键 `原文`（共享译文）— 老字典无需重译。
- 位置键是**能力**而非义务：默认预填裸键译文；某位置语境确实不同时，
  单独改那个 loc 键即可，其他位置不受影响。
- loc 只在 build_translation.py 与 bake_translation.py 之间双向重建，
  gen/merge 流程透明（键就是字符串）。

（若日后需要整块"语境不同则分译、相同则共享"，在分块后对 loc 键做
上下文差异检测再决定 agent 任务分配。）
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
| `chunks/chunk_NN.context.md` | 规则 + 分批追加契约 + 语气 + 词表 + 人名宏表 + 逐键场景记录 | 生成器 |
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
no-file 失败的温床；密集块用 `--window 1`）。分批追加契约下 **每块约
11,000 键字符是验证过的尺寸**（多款任务按 4500→11000 实测）。单个超长键
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
- 相邻故事块**必须串行处理**；不把块分发给多个写者（v2：单译者）。
- 分片后抽查相邻块衔接：块 N 的 `## Carry-over` 必须匹配块 N−1 的尾部 —
  对不上就是分片 bug。

### 第 3.5 步 — 不再按块并行分发（见 v2）

v1 的「每轮 10 个并行 subagent」教条已删除：翻译走本文上半部分的 **v2**
（一个翻译执行者 / 单写者，磁盘状态为权威）。v1 时代的失败重试心得
仍然适用：同一个执行者内重试优先；连续失败先简化 prompt（去掉读上下文
步骤，直接下令写）；需要 owner 决策时才中途交流。

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
   步骤、剩余任务、下一步），**等用户明确指示**再翻译。
5. 小任务（少量块）走同一流程，但协商只需一行。

失败后恢复 / 重分：

```
python tools\gen_translation_shards.py <work_dir> --resume --start 30
```

（已被任意 `chunks/*.zh.txt` 覆盖的键跳过；剩余键重新分块，从 `--start`
编号。）

### 第 5 步 — 专用 subagent 翻译

每块一个 subagent。有效的 prompt 模式（分批追加契约，每个 prompt
原样）——**2026-08 定案：整块拆成小批，每批约 100-130 行，边写边自检**，
取代旧的一次性 Write 全文件（700+ 行大块首轮失败率高）：

- 读规则 + `chunk_NN.ja.txt` **一次**。
- **分批 Write `chunk_NN.zh.txt`**（每行一个译文，与 ja.txt 逐行 1:1）：
  第一批用 Write 创建文件，后续每批用 edit 追加到文件末尾（oldString =
  当前最后一行，newString = 最后一行 + 新批译文）；每批译文行数与该批
  ja 行数一致。文件存在前绝不"思考模式"结束。**先写, 后思考, 再改**，
  但以批为单位推进。
- **分步自检（每批一次）**：读回 zh.txt 对应段核对 ① 行数 ② 字面 `\n`
  数量 ③ 控制码原样且数量一致 ④ 无假名残留；出错立即在批内修正。
  全部批次完成后最终读回全文核对行数。
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
   `translated.json`；断言每个模板键都在。**`merge_translation.py` 的所有
   文件参数（`--chunks`/`--prefilled`/`--sweep`/`--out`）都相对
   `<work_dir>` 解析**（与 `<work_dir>` 中存放的模板/分片一致），与当前
   工作目录无关。
3. agent 偶尔丢键/改键（转义反斜杠、编辑距离 ≤3）— 1:1 行布局下错误行数
   立刻被抓；修 zh.txt 行再合并。之后做值卫生：折叠双反斜杠、剥离
   `【?...】`、diff 控制 token。

### 第 7 步 — 烘焙（`tools/bake_translation.py`）

```
python tools\bake_translation.py <built_joiplay> <out_dir> --trs translated.json --glossary glossary.json
```

- 拷贝已构建（已解密、已压缩）的 JoiPlay 目录，无需重跑
  `build`/`audio`/`clean`。
- **运行期文本键落地**：有些 repack 的 `data/*.json` 里不是文本而是键
  （`\T[键]`，靠 MTool 运行时字典或游戏自带 CSV 文本表在运行时解析，
  网页构建两者都没有）。烘焙末尾自动调
  `tools/resolve_text_keys.py` 把它们落成真文本（表格 `cn` 列 → 字典术语 →
  字典日文对译 → 日文回退 → 保留并报告），`--no-text-keys` 关闭。
  详见 `docs/experience-translation.md` §11。
- **只精确匹配。** 对每段连续 `401`/`405` 命令用 `\n` 拼接、查块、把译文
  拆回各命令 — 短译文用 `""` 行补齐（没有命令保留日文），长译文追加命令。
  逐行精确匹配是回退。然后处理其他码（`102`/`402`/`101`/`122`/`320`/
  `324`/`325`/`408`）、DB `DISPLAY_KEYS`、`note`（精确）、`System.json`
  UI 字段、地图 `displayName`、事件名、`MapInfos` 名。
- **插件参数**：精确匹配 `js/plugins.js` 里含日文的字符串并写回
  （解析 → 替换 → 序列化；解析失败降级为字面量文本替换）。
- **覆盖率闸门（2026-09 订正口径）**：拷贝前先只读扫描，统计 **v2
  键表**（`translation.mvkeys.keys_of`，即译者被要求覆盖的那套串）被字典
  覆盖的比例（`coverage: N/M keys translated = X%`）。低于
  `--min-coverage`（默认 0.5）烘焙**拒绝** — 低覆盖烘焙 = 半日半中 +
  污染后续补翻（部分块值、半翻场景）。正确路线是全量翻译
  （`extract_remaining_text.py` → chunks → merge → 再 bake）；有意的
  阶段一 harvest 烘焙用 `--force`。
  **不要用 bake 遍历时的 hit/miss 当口径**（2026-08 旧写法）：遍历既查
  「整块拼接键」（bake 先试 `行1\n行2`、再逐行回退），也查 mvkeys 有意
  跳过的非显示串（动画名、事件名等），分母因此包含翻译流程根本不拥有的
  串 —— 一款 MZ 游戏键表覆盖 80% 却只报 7.3%，完整翻译会被永久拒绝。
- **identity 条目自动剔除**：`v == k`（假名键 shadow 逐行 fallback）的
  字典条目加载时删除（某 MZ 任务：删了 123 条）。
- **名称引用检查**：`<TE:name>`/`<namePop:name>` 引用与字典同步，且结尾
  把每个引用对照游戏事件名 — dangling 引用（含因带控制码被跳过翻译的
  引用）逐一 WARN。
- **translation_kv.json** 自动归档进 `out_dir`（烘焙字典，
  `--no-kv` 关闭）— 无需手工改名。
- 应用**标准字体策略**（`--cjk-font` 中文字体 + `--jp-font` 日文
  fallback；见 `docs/workflow.md`「标准字体策略」）。

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

**补翻覆盖的新位置（2026-08 起，与烘焙器同步）**：

- `357` 插件命令参数 dict 里的假名字符串值（`text`/`shopName` 等显示
  字段 — DTextPicture 文本、日志窗行、店名…）。`parameters[2]` 日文命令
  名是功能键，绝不提取。
- code `122` 的脚本操作数（operandType==4）：存进变量、之后经 `\V[n]`
  显示的字符串字面量（如 `'処女'`、`'11位 上位ランカー'`）。
- codes `355`/`655` 且**引号内**含假名的脚本行（战斗日志
  `addText('...')` 等）；仅注释/标识符含假名的脚本不提取。
- `Troops.json` 等 DB 文件内嵌的 `pages[].list[]` 战斗事件命令列表。

这些键是 JS 字面量：翻译只动引号内内容，引号、转义（`\\n` 仍是双反斜杠
转义序列）、引号外代码必须与键逐字节一致。功能键豁免仍走
`--exempt`（如插件按名查找的命令/标签字符串，译了会导致运行期查找失败）。

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


## 每游戏资料留本地（历史做法）

> 已被 `docs/reference/local-layout.md` 取代：每游戏资料现在放**工作区**
> （系统临时目录），长寿命的通用词表/密码/字体放 `.private/`、`.asset/`。
> 下节保留为迁移背景。


每游戏翻译资料 — `glossary.json`、`tone.md`、`notes.md` 与成人词表 — 在
`docs/table/`，该目录 **gitignored 且绝不推送**（游戏名与成人词汇不进入
公开仓库）。work 目录副本（`<work_dir>/glossary.json`、`<work_dir>/tone.md`）
是活文件；项目收尾时同步到本地 `docs/table/` 每游戏子目录。**翻译会话开始
前先查 `docs/table/<Game>/`**：存在每游戏子目录就加载其 `glossary.json` /
`tone.md` / `notes.md` 进工作流（并用它们种子化 work 目录）；本地目录是
既往游戏术语的权威仓库。通用教训写在本指南。

---

## 备注（v1 时代）

- 只翻译 `data/*.json`（外加 `js/plugins.js` 里含日文的插件参数字符串）；
  其余 `js/plugins.js` 结构不动。事件 `note` 字段只翻功能性引用内部：
  `<TE:name>`/`<namePop:name>` 引用与字典同步（跳过含控制码的引用），
  note 其余内容保持不动。
- 烘焙器用 `indent=2` 重写所有 `data/*.json`（无害）。
- 原版游戏保持不动；在 Temp 目录工作
  （系统临时目录下的工作区），成品放交付目录
  （见 `docs/workflow.md`）。
- 若之后修复了值，构建里已经是旧值 — 按键匹配的补丁不会重新生效；
  用 旧→新 值映射反向打补丁。
