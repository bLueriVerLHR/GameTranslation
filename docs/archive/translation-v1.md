# 附：v1 翻译流程（历史归档，勿照它执行）

> **本文件是历史归档，勿照它执行。** MZ/MV 翻译一律走 `docs/translation.md` 的
> v2（`translation/` 模块加 `MISSION.md` 加五道硬门禁）。本文件记录 v1 的
> 「切块 → 每块一个执行者 → 逐行 ja/zh 对齐 → 合并 → 烘焙」流程，供排查非 MZ
> 引擎（TyranoScript、Wolf RPG、KiriKiri）仍在用的 chunk 链时查阅。
>
> v1 的失败模式、QC 清单与术语审计已并入 `docs/translation-qc.md`，那些教训与
> 引擎无关，仍然有效；数据契约与门禁判据见 `docs/translation-data.md`。
>
> 下文的具体数字（字符数、成功率、块数）都是某一套条件下的历史标定值，换了
> 模型、运行环境或游戏体量就要重新测。

## 1. 整体原理

MZ/MV 的游戏文本在 `data/*.json` 里。静态翻译把这些字符串就地替换，引擎读到
的就是这份数据，不需要运行时插件。

### 为什么运行时翻译字典不能静态烘焙

repack 游戏常带一个运行时替换字典（如 `<title>.json`，1 万条以上）。它在运行时
有效（注入工具 hook 引擎，替换最终显示的字符串），但与静态数据结构不兼容：

- 对话按每条事件命令一行（码 `401`）存储，而运行时字典的键是用 `\n` 拼接的整条
  消息，引擎显示时再重组。拼接键永远匹配不上逐行静态数据。
- 字典还含片段键（助词、短感叹词），只对运行时匹配有意义。

直接把这类字典静态烘焙（旧的贪心片段回退）会毁句子：助词在词中被替换，大多数行
保持半日半中。所以绝不直接烘焙运行时字典，先提取静态文本，构建自己的逐行或逐消息
模板，翻译它，再精确烘焙。

### 翻什么、不碰什么

| 范围 | 字段或事件码 |
|---|---|
| 整段对话消息 | 连续 `401`/`405` 命令，用 `\n` 拼接成块键 |
| 说话人名字框 | 码 `101` 的第 4 个参数 |
| 选择肢与分支标签 | 码 `102`、`402`，保持同步 |
| 选择帮助文本 | 码 `408` 注释，指令类行跳过 |
| 改名、昵称、简介命令 | 码 `320`、`324`、`325` |
| 字符串变量 | 码 `122` 的字符串操作数 |
| DB 文本 | `name`、`nickname`、`profile`、`description`、`message1..4`、`text` |
| `note` 字段 | 仅精确匹配，插件标签保持不动 |
| 系统 UI | `terms`、战斗 `message`、`commands`、装备与属性类型、`variables`、`switches` |
| 地图名、地图标题横幅、公共事件名 | `MapInfos.json`、地图 `displayName`、公共事件 `name` |
| 插件命令参数与脚本 | 功能性部分绝不翻译：码 `356`/`657`、`357` 的日文命令名（`parameters[2]`，插件按名匹配）、含假名但不在引号内的脚本行。显示部分要译：`357` 参数对象里的假名字符串值、码 `122` 的脚本操作数（存进变量、之后经 `\V[n]` 显示的字符串字面量）、`355`/`655` 引号内含假名的脚本行（如 `BattleManager._logWindow.addText('...')`） |
| 数据库内战斗事件 | `Troops.json` 等 DB 文件里的 `pages[].list[]` 命令列表，与地图事件同规则 |

烘焙器只做精确匹配，没有贪心片段替换，所以被翻译的分支永远不会把片段漏进另一个
分支。

## 2. 工作流

### 第 1 步 — 提取与合并（`tools/build_translation.py`）

```bash
python -m tools.build_translation <game_dir> <work_dir>
```

遍历 `data/*.json`，在 `<work_dir>` 产出工作包：

| 文件 | 内容 |
|---|---|
| `template.json` | 合并后的 `{key: ""}`，每个可翻译字符串一条；每个消息块一个键（连续 `401`/`405` 用 `\n` 拼接），另加选择肢、名字、帮助文本、DB 与系统 UI、note、`displayName` |
| `kinds.json` | 键到种类的映射（`block`、`choice`、`help`、`db-name`、`system`、`plugin` 等） |
| `structure.json` | 场景树：按故事顺序的地图 → 事件 → 有序块与选择肢（含分支上下文） |
| `context.json` | 键到 `{"where": 位置, "window": ±2 句对话窗口}` 的映射，是独立产物、不翻译，分片时注入各块的 `context.md` |
| `names.json` | 候选角色名（名字位置加高频独立行） |
| `glossary.json` | 已确认的人名表，首次协商后只用编辑工具改 |
| `name_macros.json` | `\N[x]`/`\P[x]` 到角色名的宏对照表；控制码是替换引用，本身不译，名字在 DB 里译 |

合并规则：相同字符串全局去重（在 6 张地图复用的阶段菜单消息只占一个键）。

**位置感知键（不去重）。** 同一原文出现在不同位置（地图、事件、页、命令索引，或
DB 条目的字段路径）时，除首个出现的**裸键**（原文）外，每个后续位置生成独立键
`原文\x1f<loc>`，其中 `loc` 是稳定遍历路径，如 `Map001.json#ev0#pg1#c12`、
`Skills.json[16]#message1`、`js/plugins.js#插件名#参数名`。同一句话在不同场景的
语境可能不同，必须允许按位置分别翻译。规则：

- 裸键保留（旧字典与烘焙回退路径仍用它），loc 键优先匹配。
- 人名与称呼类短键（14 字符以内、无控制码、纯名字）不生成 loc 变体：它们按词表
  统一翻译，不是语境敏感文本。
- 翻译执行者在 ja.txt 里看到带 `\x1f` 位置后缀的键行，整个行就是键；译文只译
  分隔符之前的日文正文，位置标记绝不写进译文。
- 烘焙器 `exact_loc()` 先查 `原文\x1f<loc>`，再回退裸键，所以老字典无需重译。
- loc 键是能力而非义务：默认预填裸键译文，某位置语境确实不同时单独改那个 loc
  键，其他位置不受影响。
- loc 只在 `build_translation.py` 与 `bake_translation.py` 之间双向重建，分片与
  合并流程透明，因为键就是字符串。

插件菜单文本：`js/plugins.js` 里含日文的插件参数字符串也会提取（kind
`plugin`，`--no-plugins` 关闭），以便本地化插件菜单与 UI；烘焙器精确写回，见
第 7b 步。

### 第 2 步 — 定人名

把 `names.json` 整理进 `glossary.json`（`{"角色名": "中文名", ...}`），翻译前
确认。词表单人维护，之后只用编辑工具修改，因为各执行者读的是自己
`context.md` 里的词表快照，并发写会写坏。同时检查人名变体（全名与简称）和其他
项目遗留数据（从未在事件里出现的角色，排除或映射为自身）。

人名控制码（`\N[1]`、`\P[1]` 与自定义的 `\字母[..]`）是宏，像 C++ 或 LaTeX 的
替换引用：要理解成角色 X 的名字，但绝不翻译或改动码本身；引用的名字在 DB 里译。
`context.md` 给出宏对照表（`\N[1] = 角色名 (词表: 中文名)`）。

### 第 3 步 — 分块（`tools/gen_translation_shards.py`）

```bash
python -m tools.gen_translation_shards <work_dir>
python -m tools.gen_translation_shards <work_dir> --target-chunks 55
python -m tools.gen_translation_shards <work_dir> --max-chars 11000 --window 1
```

双文件块布局：

| 文件 | 内容 | 写入者 |
|---|---|---|
| `chunks/chunk_NN.ja.txt` | 仅键，每行一个日文键，无引号、非 JSON | 生成器，执行者绝不改动 |
| `chunks/chunk_NN.zh.txt` | 每行一个译文，与 ja.txt 逐行 1:1（同顺序、同行数） | 翻译执行者 |
| `chunks/chunk_NN.context.md` | 规则、分批追加契约、语气、词表、人名宏表、逐键场景记录 | 生成器 |
| `chunks/chunk_NN.meta.json` | 覆盖的地图，供并行度参考 | 生成器 |

两个文件用同一套转义：`\n` 表示消息内的真实换行（多行块），`\\` 表示单个字面
反斜杠（控制码前缀）。映射无歧义，含字面 `\n` 文本的键可以安全往返。

上下文：`build_translation.py` 已提取 `context.json`（每键 ±2 行对话窗口），分片
生成器把它打印成场景记录（`[K]` 是要译的键，`|` 是上下文行），并把上一块的末尾
对话行带进下一块。词表与语气按块注入，生成器绝不硬编码。

分块尺寸：默认自动选档，生成器二分搜索最大的 `--max-chars`，使块数不超过
`--target-chunks` 且每个 `context.md` 低于 `--context-budget-kb 90` 的预算
（90KB 以上的 context 块是 flaky 无文件失败的温床，密集块用 `--window 1`）。
分批追加契约下每块约 11,000 键字符是验证过的尺寸（多款任务按 4500 到 11000
实测）。单个超长键自成一块。显式 `--max-chars` 或 `--per-chunk` 覆盖自动选档。
真正的约束是上下文预算而不是模型，生成器会打印所选尺寸与预期上下文大小。

对话连续性是硬验收标准，分片时强制、每次分片后检查：

- 键保持故事顺序（MapInfos 顺序 → 地图 → 事件 → 页 → 命令位置 →
  CommonEvents → UI/DB 最后），绝不按字母或种类乱排。
- 每键的 context 窗口给 ±2 句相邻对话，块的场景记录去重。
- 每个故事块的 `context.md` 以 `## Carry-over` 段开头，内容是上一个故事块的末尾
  8 句对话，线性场景跨块切开也能保持连贯。
- 相邻故事块必须串行处理，不分发给多个写者（v2 起只有一个执行者）。
- 分片后抽查相邻块衔接：块 N 的 `## Carry-over` 必须匹配块 N−1 的尾部，对不上
  就是分片故障。

### 第 4 步 — 启动执行者前先量体量并协商

v1 不在未协商的情况下启动大型翻译任务。流程是：

1. **测量**：跑 `extract_remaining_text.py <built> <work_dir>`（全量任务用
   `build_translation.py`），读 `template.json` 统计键数与总键字符数。
2. **估算**：块数约等于总字符除以 11,000，最终以生成器打印的块数为准。
3. **协商**：给出键数、块估算与预计时长，确认范围（全部剩余、跳过、子集）。
4. 块数超过 30 时把任务当批处理：先不启动执行者，在 work 目录准备
   `TRANSLATION_PROJECT.md` 状态文件（已完成步骤、剩余任务、下一步），等明确
   指示再翻译。
5. 小任务走同一流程，协商只需一行。

失败后重分：

```bash
python -m tools.gen_translation_shards <work_dir> --resume --start 30
```

已被任意 `chunks/*.zh.txt` 覆盖的键跳过，剩余键重新分块，从 `--start` 编号。

### 第 5 步 — 分块翻译

每块一个执行者。有效的提示词模式是分批追加契约：整块拆成小批，每批约 100 到 130
行，边写边自检，取代一次性写全文件（700 行以上的大块首轮失败率高）。

- 读规则与 `chunk_NN.ja.txt` 一次。
- 分批写 `chunk_NN.zh.txt`（每行一个译文，与 ja.txt 逐行 1:1）：第一批创建文件，
  后续每批追加到文件末尾，每批的译文行数与该批 ja 行数一致。文件存在前不结束。
- 每批自检一次：读回 zh.txt 对应段，核对行数、字面 `\n` 数量、控制码原样且数量
  一致、无假名残留；出错在批内修正。全部批次完成后读回全文核对行数。
- 值必须是译文，绝不把日文键抄进值；保持与键相同的 `\n` 转义数量（消息窗口
  行数）；控制码原样保留（`\N[x]`/`\P[x]` 是人名宏，理解为角色名，绝不译码）。
- 严格遵循词表，跟随共享术语日志。
- 只要求一行回复（计数），冗长汇报会引诱执行者卡住。

团队术语日志 `terms.json` 记录每个执行者汇报的术语决策，并追加进之后每个提示词，
保证整游戏一致。语气按游戏预先设定（本地 `tone.md`，成人词表不入公开仓库）。
成人场景遵循已认可的语气，核心名词遵循本地词表；剧情与揭示场景保持悬念，不剧透
伏笔与反转；长度上保持原意，一行会溢出消息窗口时用更紧凑的说法。

### 第 6 步 — QC、修复、合并

```bash
python -m tools.merge_plain_chunks <work_dir> [--strict]
python -m tools.merge_translation  <work_dir> --chunks chunks_translated.json \
                                    [--prefilled prefilled.json] [--sweep sweep.json]
```

1. `merge_plain_chunks.py` 把每对 ja.txt 与 zh.txt 合并成
   `chunks_translated.json`，并逐块 QC：行数不匹配、值里残留假名（先剥离控制
   token）、控制码 token diff、空值、`【?】` 不确定标记、双反斜杠。`--strict`
   表示有任何问题就失败。
2. `merge_translation.py` 叠加 `--prefilled`（MTool 精确命中）并应用 `--sweep`
   术语规则（最长优先，防 substring bomb），得到最终 `translated.json`，并断言
   每个模板键都在。
3. 合并偶尔会丢键或改键（转义反斜杠、编辑距离不超过 3 时），1:1 行布局下错误
   行数立刻会被抓到：修 zh.txt 的行再合并。之后做值卫生：折叠双反斜杠、剥离
   `【?...】`、diff 控制 token。

`merge_translation.py` 的所有文件参数（`--chunks`、`--prefilled`、`--sweep`、
`--out`）都相对 `<work_dir>` 解析，与当前工作目录无关，这样模板与分片始终在同一
个目录里。

### 第 7 步 — 烘焙（`tools/bake_translation.py`）

```bash
python -m tools.bake_translation <game_dir> <out_dir> \
    --trs translated.json --glossary glossary.json
```

- 拷贝游戏目录再写回，不必重跑其他流水线步骤。
- 运行期文本键落地：有些 repack 的 `data/*.json` 里不是文本而是键（`\T[键]`，
  靠运行时字典或游戏自带 CSV 文本表在运行时解析，静态构建里两者都没有）。烘焙
  末尾自动调 `tools/resolve_text_keys.py` 把它们落成真文本（表格 `cn` 列 →
  字典术语 → 字典日文对译 → 日文回退 → 保留并报告），`--no-text-keys` 关闭。
- 只精确匹配：对每段连续 `401`/`405` 命令用 `\n` 拼接、查块、把译文拆回各命令，
  短译文用 `""` 行补齐（没有命令保留日文），长译文追加命令。逐行精确匹配是
  回退。然后处理其他码（`102`、`402`、`101`、`122`、`320`、`324`、`325`、
  `408`）、DB 的 `DISPLAY_KEYS`、`note`（精确）、`System.json` 的 UI 字段、地图
  `displayName`、事件名、`MapInfos` 名。
- 插件参数：精确匹配 `js/plugins.js` 里含日文的字符串并写回（解析、替换、
  序列化；解析失败时降级为字面量文本替换）。
- 覆盖率闸门：拷贝前先只读扫描，统计 v2 键表（`translation.mvkeys.keys_of`，即
  翻译被要求覆盖的那套串）被字典覆盖的比例
  （`coverage: N/M keys translated = X%`）。低于 `--min-coverage`（默认 0.5）
  时烘焙拒绝写盘，因为低覆盖烘焙会得到半日半中的构建并污染后续补翻；有意的阶段
  式收割用 `--force`。不要用烘焙遍历时的 hit 与 miss 当口径：遍历既查整块拼接键
  （先试 `行1\n行2`，再逐行回退），也查 mvkeys 有意跳过的非显示串（动画名、事件
  名等），分母因此包含翻译流程根本不拥有的串，一款 MZ 游戏键表覆盖 80% 却只报
  7.3%，完整翻译会被永久拒绝。
- identity 条目（键与值相同且含假名）在加载字典时自动剔除，否则它会遮蔽逐行
  回退。
- 名称引用检查：`<TE:name>`/`<namePop:name>` 引用与字典同步，结尾把每个引用对照
  游戏事件名，dangling 引用（含因带控制码被跳过翻译的引用）逐一 WARN。
- 自动归档 `translation_kv.json` 到输出目录（即烘焙字典，`--no-kv` 关闭），无需
  手工改名。
- 应用标准字体策略（`--cjk-font` 中文字体加 `--jp-font` 日文 fallback，见
  `docs/reference/local-layout.md` §4–5）。

### 第 7b 步 — 菜单与插件文本、人名宏

- 插件 UI：`build_translation.py` 提取 `js/plugins.js` 插件参数里含日文的字符串
  （kind `plugin`），它们先进入全局块作为术语基础。烘焙时只做整串精确替换，
  功能性值（数字、布尔、文件名）不含日文，永不触碰。菜单文本写在插件 JS 数据
  文件（不是参数）里的游戏超出范围，那需要运行时方案。
- 人名宏：`\N[x]`、`\P[x]` 与自定义的人名码是替换引用，不是可译文本，解析为
  `Actors.json` 里翻译过的角色名，无需额外烘焙。

## 3. 补翻残留片段（MTool 片段污染）

随包的 MTool 字典比游戏构建旧时，或片段替换留下半行时，静态烘焙过的构建仍含假名
片段。用同一套执行者工作流修复，但只翻译剩余键，绝不重跑全量模板（已翻译的中文
行不得重译）：

```bash
python -m tools.extract_remaining_text <built> <work_dir>
python -m tools.gen_completion_shards <work_dir> [--max-chars 11000] [--dict <title>.json]
python -m tools.merge_plain_chunks <work_dir> --strict
python -m tools.merge_translation <work_dir> --chunks chunks_translated.json
python -m tools.bake_translation <built> <out_dir> --trs <work_dir>/translated.json
```

`extract_remaining_text.py` 遍历 `data/*.json`，保留仍含假名的逐行或逐字段精确
键（与 `bake_translation.py` 查的完全一致），假名正则
`[\u3041-\u3096\u30a1-\u30fa\uff71-\uff9e]`（与 `rpgmaker.japanese.KANA` 同类）。
注意 `\u3000-\u303f` 绝不能进假名正则：它会匹配 `。「」`（已翻译的中文里也有），
把模板灌满几万假键。它还写 `context.json`（故事顺序加 ±2 窗口）与
`name_macros.json`，并提取残留的插件参数文本。

补翻覆盖的位置（与烘焙器同步）：

- `357` 插件命令参数对象里的假名字符串值（`text`、`shopName` 等显示字段）。
  `parameters[2]` 的日文命令名是功能键，绝不提取。
- 码 `122` 的脚本操作数（`operandType == 4`）：存进变量、之后经 `\V[n]` 显示的
  字符串字面量。
- 码 `355`/`655` 且引号内含假名的脚本行（战斗日志 `addText('...')` 等）；仅注释
  或标识符含假名的脚本行不提取。
- `Troops.json` 等 DB 文件内嵌的 `pages[].list[]` 战斗事件命令列表。

这些键是 JS 字面量：翻译只动引号内的内容，引号、转义（`\\n` 仍是双反斜杠转义
序列）与引号外的代码必须与键逐字节一致。功能键豁免走 `--exempt`（插件按名查找的
命令名或标签字符串，译了会导致运行时查找失败）。

note 字段过滤（自动）：带插件标签（`<recipe> {"material": ...}`、
`<拡張説明:...>`、任意 `<[A-Za-z_@][^>]*>`）或纯内嵌 JSON 的 `note` 是功能性
插件数据，不是显示文本，从模板排除、构建里保持原样（配方里的材料名来自已翻译的
物品 DB）。只有无标签的叙事型 `note` 才翻译。

`gen_completion_shards.py` 用同样的块格式与尺寸（默认 `--max-chars 11000`），
结尾做合并遍历：相邻块合并后仍不超上限的就贪心合并（从左到右），几个巨键不会
产生浪费的单键块，同时单块上限永不被突破。故事顺序分块、carry-over、上下文
预算、无剧透规则与第 3 步一致。

## 4. 每游戏资料的存放

v1 把每游戏翻译资料（`glossary.json`、`tone.md`、`notes.md` 与成人词表）放在
仓库内的每游戏子目录（目录名与游戏名相同），那些目录 gitignored。该布局已废弃，
现在的位置与解析顺序见 `docs/reference/local-layout.md`：每游戏资料放工作区
（系统临时目录），长寿命的通用词表、密码与字体放 `.private/` 与 `.asset/`。

## 5. 备注

- 只翻译 `data/*.json`，外加 `js/plugins.js` 里含日文的插件参数字符串；其余
  `js/plugins.js` 结构不动。事件 `note` 字段只翻功能性引用内部：
  `<TE:name>`/`<namePop:name>` 引用与字典同步（跳过含控制码的引用），note 其余
  内容保持不动。
- 烘焙器用 `indent=2` 重写所有 `data/*.json`，无害。
- 原版游戏保持不动，工作在临时目录的工作区里做，成品放交付目录（见
  `docs/workflow.md`）。
- 值修复后，构建里已经是旧值，按键匹配的补丁不会重新生效；用旧值到新值的映射
  反向打补丁。
