# 经验库 · 翻译

> **先读这篇**：本文收录「翻译工作流、subagent 分块、烘焙、QC、补翻」相关
> 的实战经验（由原单文件经验库拆分而来，原 §7/§7.1/§7.5/§7.7/§7.8/§12/
> §13.1/§13.2/§13.3）。
> 其他主题经验见：
> [解密 / 解包 / Repacker 识别](experience-decrypt.md) ·
> [音频 / 清理 / 打包](experience-audio-clean.md) ·
> [Tyrano](experience-tyrano.md) ·
> [其他 / 杂项](experience-misc.md) ·
> [经验库索引](experience.md)。

统一翻译工作流详见 `docs/translation.md`；本文是实战中踩过的坑与结论。

## 1. 翻译（zh_CN 翻译文件.json）

- 用 `tools/translate_rpgmaker.py <src> <out> --trs 翻译文件.json`，或用其
  `translate_data` 直接烘焙进构建（只数据文件；JSON 写 `indent=2`、
  `ensure_ascii=False`、无 BOM）。
- 翻译后**打包 CJK 字体**，否则中文渲染方块。最佳做法：加
  `NotoSansSC.ttf`（OFL，google/fonts GitHub），按 `unicode-range` 拆
  `fonts/gamefont.css`，假名/ASCII 保留原字体、汉字用 Noto：
  ```css
  @font-face { font-family: GameFont; src: url("ラノベPOP.ttf");
      unicode-range: U+0020-00FF, U+3040-30FF; }
  @font-face { font-family: GameFont; src: url("NotoSansSC.ttf");
      unicode-range: U+3000-303F, U+4E00-9FFF, U+F900-FAFF, U+FF00-FFEF, U+20000-2FA1F; }
  ```
- `System.json.gameTitle` 为空时设官方名。

### 1.1 ExternMessage.js 游戏（MV）

- **对话在 `data/ExternMessage.csv`，不在 JSON。** 有些 MV 游戏带
  UTF-16LE `ExternMessage.csv`（列 `名前(ID),本文(body),...`）；事件只含
  指向它的 `\M[ID]` 引用。`translate_rpgmaker.py` 原本只烘焙 `data/*.json`
  → 开场场景保持日文，且贪心翻译器重写了 `\M[...]` 里的 ID，破坏 CSV
  查找。**修复（已应用于 `tools/translate_rpgmaker.py`）：** (1)
  `translate_text` 现在保护控制码括号（`\M[ID]`、`\V[1]`、`:name[...]`、
  …）— 只翻译它们之间的纯日文片段，`:name[NAME,FACE]` 的 NAME 部分除外
  （它是显示文本；已验证无 `:name` 参数与 CSV id 冲突）；(2) 新
  `translate_extern_csv` 逐行翻译 本文 列，ID 保持不动、保留
  UTF-16LE/BOM（或 utf-8-sig/cp932）+ CRLF。这类修复后从源重跑整条
  流水线 — 旧构建的 `\M[...]` 引用已损坏。
- **MV 字体回退 ≠ `css/game.css`。** MV 加载 `fonts/gamefont.css`；
  `add_cjk_font_fallback`（仅 MZ）没用，简体中文渲染方块。
  `add_mv_cjk_font(root, --cjk-font)` 打包 CJK ttf 并按 `unicode-range`
  拆 `gamefont.css`（假名/ASCII → 原字体，汉字 → 打包字体）。
  **2026-08 后默认拆分为**：假名/日文标点 → `--jp-font`（解析顺序：
  `JP_FONT_PATH` → `docs/table/local_font_path.txt` 第二行 → 自动发现
  `docs/table/fonts/`，未配置则回退游戏原字体），汉字/拉丁 → `--cjk-font`。
- **翻译后验证 CSV ID：** 地图 JSON 里每个 `\M[ID]` 必须在 CSV 的 名前
  列存在（排除既有缺失如 `\V[320`、`テスト`、单假名 — 源里本来就没有）。

### 1.2 MTool repack 可能带未翻译 `data/` + 根 `<title>.json`

一款 repack 正常 — 数据已翻译；另一款不是：repack 在游戏根带 MTool
字典、*数据文件仍是日文*；你必须自己烘焙：
`python tools\translate_rpgmaker.py <built> <out> --trs "<title>.json"`
（那次 7742 条）。它还向 `css/game.css` 追加 CJK 字体回退。之后重
verify + serve --test。别假设"repack = 已烘焙"。

## 2. 静态 subagent 翻译工作流（全量批次）

- **MTool 运行时字典不可静态烘焙。** 一款游戏带根 `<title>.json`
  （10,191 键），键是 `\n` 拼接的整条消息（引擎显示时重组）+ 片段键。
  静态烘焙（旧贪心回退）毁句子、菜单帮助文本没翻。修复是静态工作流 —
  `build_translation.py`（提取、块合并模板）→ `glossary.json` →
  `gen_translation_shards.py` → subagent → `bake_translation.py`
  （只精确匹配）。完整指南 `docs/translation.md`。
- **消息块修多行上下文。** 连续 `401`/`405` 命令是一条消息：`\n` 拼成
  单翻译键，烘焙器拼接同一段、按命令拆回值（短值 `""` 行补齐；多余行
  追加命令）。
- **块尺寸与并行度遵循统一长程参数**（见 `docs/translation.md`）：auto
  分块配 90KB 上下文预算（标定值约 11,000 字符/块）、默认每轮 10 个
  subagent（受 harness 上限约束）。旧的"450-530 键会死、块保持 100-160
  键、2-3 个 agent 当节奏"指引**已过时**；**"写优先"也已被分批追加
  契约取代**（见 `docs/translation.md` 第 5 步与
  `tools/gen_translation_shards.py` 的 RULES）——修 no-file 失败的是 prompt
  契约本身，而不是把块变小。失败后 `--resume --start N` 重分。
- **LLM 输出卫生：** (1) 修复遍历：双重转义非法转义、转义游离引号；
  (2) agent 偶尔改键（丢字符、键内译词）— 按编辑距离 ≤3 补到最近的多余
  键；(3) 值行数归一化到键（补 `""`）；(4) 合并并断言每个模板键都在。
- **跨分块术语一致性：** 维护 `terms.json` 日志；每个 agent 汇报决策，
  之后每个 prompt 带上累积日志。每个 prompt 强制确认过的角色词表；尽早
  发现人名变体（全名 vs 简称）并加入。
- **游戏 owner 语气指令进每个 chunk 上下文：** 成人场景遵循 owner 认可
  的语气（词表留本地，见 `docs/translation.md` §6）；剧情/揭示保持悬念；
  一行会溢出消息窗口时紧凑措辞。

## 3. 残留翻译批次（当时用 write-first；现已改为分批追加）

> **契约变更提醒**：本节写于 write-first 时代（"立即写第一遍 → 读回 → 再
> Write 改进"）。当前契约是**分批追加 + 每批自检**（见 `AGENTS.md`、
> `docs/translation.md` 第 5 步、`tools/gen_translation_shards.py` 的
> RULES）——旧契约在 700+ 行大块上失败率高。本节保留的是那一次会话的
> **教训**（假名残留检测、CommonEvents 顶层列表、值卫生修复），这些仍然
> 有效。

这次会话用 16 块 subagent 批次（补 2102 键）翻译了 AI 字典烘焙构建里的
残留日文。三个硬教训：

- **用假名量残留，不用字典查。** 烘焙后构建是中文；对照日文字典报
  "100% missing" 无意义。正确残留检测器是**最终**构建文本位置上跑假名
  正则（`[\u3040-\u30ff]`）。同时把假名标点从计数排除（`ー・゛゜` 与
  拟声词里风格保留的小 tsu/ya 类助词没问题；`ちゃん`/`ん` 后缀与
  `っ`/`ぁ`/`ぃ` 是可接受的中文游戏风格）。
- **CommonEvents.json 是顶层 LIST — 只在"dict with `events`"上分支的
  文本源 walker 会静默漏掉它全部对话。** 第一次报 166 行残留；真实
  1851（~33k 字符）。修复：元素带 `list` 键的顶层列表在 db walker 之前
  走事件 walker。任何补丁后总重跑检测器并 diff 计数。
- **修 subagent "思考模式死亡"的修复真有效 — 先写。** 114 个硬键块用旧
  "读 → 翻 → 最后写" prompt 失败 3 次（agent 烧光思考预算、无文件结束）。
  新 prompt 契约，16 块验证（14 首试 OK，2 个可恢复格式滑落）：
  1. 读规则一次，读块键一次。
  2. **立即**写 `chunk_NN.zh.txt` 第一遍（拿不准：最佳猜测 + `【?】`）。
  3. 读回，再 Write 一次改进。
  4. 最终回复 = 路径 + 条目数。
  "文件存在前绝不结束。先写，后润色。"（此契约下块可以很大 — 约
  9k-11k 字符 — 每轮 10 个 agent。）两个格式滑落：`===KEY===` 分隔符丢
  （120 行仍与键 1:1 → 按行重建 plain）和一个多行键里字面 `\n` 文本写成
  真实换行。
- **补丁前 agent 值卫生修复遍历（mandatory）：** (1) agent 转义控制码
  （`\\C[27]`）— 折叠双反斜杠；(2) 剥离 `【?...】` 不确定标注；(3) 检查
  控制码 token 序列键值两侧；缺 `\C` 对是外观性的（默认色），保留；
  (4) 盯重度损坏键上的幻觉值（2102 里有 2 个完全离题）— 目检码不匹配
  列表。**任何值修复后，构建里是旧值，按键匹配的补丁不会重新生效：
  用 旧→新 值映射反向补。**
- **启动 agent 前必须对照烘焙字典查术语**（第一次词表猜了角色名一个
  读法；烘焙 AI 字典用另一个，游戏内标题第三个）。先 grep 根翻译 JSON
  找每个角色名。
- **姿势/动画名消歧：** 对成人姿势/表情类动画标签（技术消歧样例），作者
  意图在事件正文（跑哪些图）与同族其他标签（表情类 = 表情）之间。别从
  无上下文假名猜；无法确定就保留构建里的假名（姿势名编辑器不可见）并向
  用户标记。
- **手工兜底：** subagent 在同一块反复死亡时，编排者可以手工翻（3k
  字符块完全可行），用脚本生成 plain 文件 — 脚本为每个键前置字节精确的
  前导空白；没有 agent 能可靠复现 `\u3000` 缩进。

### 3.1 TemplateEvent `<TE:name>` note 引用 vs 已译事件名

症状：翻译构建启动、地图渲染，但**玩家永远无法移动**。`canMove()` 保持
false，因为 `$gameMap.isEventRunning()` 恒 true；地图解释器空闲
（`running=false`、`index 0/0`），但 `isAnyEventStarting` 为 true，事件 1
每帧卡在 `_starting=true`。

根因：**TemplateEvent.js** 把 Note 含 `<TE:name>` 的事件替换成模板事件，
在模板地图（插件参数 `TemplateMapId`）里**按名查找**：

    generateTemplateId: templateId = findMetaValue(event, 'TE')
        -> searchDataItem($dataTemplateEvents, 'name', templateId)

模板地图持有短"setup-and-erase"模板列表（5 条命令 vs 原 23 条）。翻译
把模板地图的事件**名**译成中文，但每个 Note 的 `<TE:マップ初期処理>`
保持原样 → 按名查找失败 → 模板永不应用 → 原无条件 autorun 事件（永不
自我擦除）每帧重触发 → `isEventRunning()` 恒 true → 移动锁死。

诊断路径（已验证）：关键运行时差异不在数据结构或插件文件（除译文字符串
外字节一致），而在**运行时状态** — 对比构建间的
`Game_Event._erased/_starting/_pageIndex`。原版事件 `erased: true`（模板
列表跑完擦除）；翻译构建永远 `erased: false, pageIndex: 0, trigger: 3`。
记录 `interp.setup listLen` / `EVENT.start` / `eraseEvent` 的 trace 插件
显示原版用 `listLen=5`（模板）setup 事件，翻译构建总用 `listLen=23`
（原版）。

修复（已烘焙进 `tools/bake_translation.py`）：翻译事件 Note 里的
`<TE:name>` 引用与事件名同步 — `_translate_note_refs()` 用同一精确匹配
字典改写 `<TE:ja>` → `<TE:zh>`（跳过 `\v[1]` 类控制码引用）。从干净源
副本重烘焙；旧构建上的手工 note 编辑会被之后的烘焙覆盖。

同一会话还修了：`bake_translation.py` 曾以 `encoding="utf-8-sig"`
（写时加 BOM）写所有 `data/*.json` — 全部改为纯 `utf-8`（System.json
里的 BOM 破坏引擎 `JSON.parse`）。

教训：翻译时**扫描插件里按名称查找的模式**（`<TE:`、`@command` 名引用、
`PluginManagerEx.findMetaValue`）— 任何按显示名解析实体的插件（模板
事件、气泡名、`callEventByName`、选择帮助标签）在查找只有一侧被翻译时
坏掉。

## 4. 两款部分汉化 MV repack 的补翻批次（2026-08）

两款 MV `www/` 部署、easy 加密、**部分汉化**的 repack（正文/DB 大部分
已译，System UI/事件名/开关变量/少量对话残留日文）走完整流水线 +
残留补翻。规模极小：每款仅 1 个 chunk（一款 453 键/7.8k 字符，另一款
650 键/8k 字符）— 补翻剩余量可以用 1-2 个 subagent 一次完成，无需
多轮。

- **两款均已汉化但残留形态不同，补翻前先量。** 一款自带 MTool 字典
  （1,032 键，354 命中残留模板 → 直接做 `--prefilled`，剩余 ~99 键
  subagent 译）；另一款是公开汉化版，残留全在 UI/事件名/开关变量。
  `extract_remaining_text.py` 是唯一可靠的量尺。
- **题材术语统一（owner 定案，本地 adult 词表已记录）：** 成人题材的
  主动/被动类词 → 按统一术语表处理。补翻 agent 会把这类词整串留在
  译文里（视为专名），QC 假名残留检测会抓到 — 用 `--sweep` 或修复遍历
  统一，而不是依赖 agent。
- **谜题暗号词豁免：** 一款的 DB description 里有一组假名暗号（变位词
  谜题答案，如 5 个假名词），翻译会破坏谜题 — 记录到
  `docs/table/<Game>/notes.md` 豁免清单，QC 接受残留。
- **插件 note 功能性标签豁免：** `<モーション変更:guard>` 类
  `<插件标签>` 是功能引用不是显示文本 — 保留，记入豁免清单。
- **修复遍历：** 残留假名行里除豁免外全是题材术语串 — 机械替换两个
  题材术语后全部清零。double-backslash 告警要逐条看：插件参数
  JSON 值里键本身含 `\\C[16]`（字面转义控制码），值保持一致就是正确，
  不是污染。
- **烘焙覆盖闸门验证：** 两款分别 83.8% / 89.8% 覆盖 — 补翻块小所以
  达标；`--min-coverage` 默认 0.5 没触发。
- **交付：** 两款都无 >4096 PNG（无需缩放），`translation_kv.json`
  已随包归档，压缩包 `7z t` 完整性测试 OK。

## 5. 大型 MZ 插桩游戏的翻译会话（2026-08）

### 5.1 分块工具的估算 bug（已修复 + 单测）

- **多行键膨胀**：`[K]` 行打印含真实换行的键时展开成多物理行，context.md
  实测为估算 2.3 倍。修复：transcript 输出一律把 `\n` 转义为字面 `\\n`
  （与 ja.txt 转义一致，且让估算可精确）。
- **字符 vs 字节**：估算按 Python 字符数，预算阈值是文件字节数 — 日文
  content 的 UTF-8 字节为字符数 2~2.5 倍，90KB 预算下实测 219KB。
  修复：`_chunk_context` 按 UTF-8 字节计。
- **全局块切分不一致**：估算按字符切全局键，实际写入按键数（600）切 —
  巨型插件键会把首块撑到 294KB。修复：估算镜像写入器的按键数切分。
- 三处修复后 auto sizing 从"20 块 220KB"变为诚实的"40 块 ≤93KB"。
- 教训：新的工具修完必须在本游戏数据上跑一遍验证估算==实际，再启动
  subagent；此前"误差 <3%"的说法只在短键游戏上成立。

### 5.2 插件参数巨型 JSON（>300 字符的 kind=plugin 键）

- 18 个键占 20.6 万字符（最大 83KB）：技能动画表、菜单模板等。
  整串翻译不可行 → 从模板剔除，走 `plugin_json_leaves.py`：
  extract（204 叶子）→ 叶子翻译（1 个 subagent）→ rebuild（23 个 blob
  变更）→ `plugin_blobs_translated.json` 后合并覆盖进 translated.json
  （blob 重建必须覆盖模板整串译文）。
- 插件 JSON 的功能键（`位置X`/`テキスト名`/`条件`/`アニメ名` 等）必须
  保持日文；叶子收集只取 VALUE，但最终 kana 残留扫描会报这些"键里的
  假名" — 属正常，勿修。
- 字体名/样本文件名字面值（`07鉄瓶ゴシック.woff`、`サンプル/一言_1`）
  必须进 `--exempt`，否则叶子翻译改坏引用。
- 事件 note 带插件标签（`<BFC_座標:...>`/`<CounterExt:...>`）是功能数据，
  从模板剔除，bake 后保持原样。

### 5.3 code 357 插件命令消息正文不在全量提取范围

- Money Get!/Item Get! 等弹窗正文在 357 命令的 `parameters[3].message`
  dict 与 122/355 脚本字符串里，`build_translation.py` 不提取 →
  第一遍 bake 后残留 ~789 条。用 `extract_remaining_text.py` 补翻
  （~311 键 / 5 块）即可，覆盖率从 93.9% → 99.7%。
- 顺序：全量 bake → 补翻 → 合并 dict → 在原始 build 上重 bake（不要
  在已烘焙目录上叠加）。

## 6. 大 MZ MTool-repack 转换的翻译要点（全流水线 + 全翻译）

完整会话记录见 [音频/清理/打包](experience-audio-clean.md)（工具加固部分
也见此处）；翻译侧关键点（原 experience.md §11 的翻译部分）：

- **MTool 字典 harvest：** 14,092 模板键 → 8,402 预填（exact 3427 /
  strip 1366 / drop-name 2937 / fragment 672）。剩余补翻模板是**逐行片段
  粒度**（13,589 键 / 63.8 万字符 — 比缺失的 5,690 个*块*还多，设计如此）。
- **块尺寸二分搜索（更大的块）：** 先确定性量 context.md 尺寸（12000
  字符 → 90KB+ context，超预算；11000 → `--window 1` 下最大 ~92KB），
  再 agent 探针：8000（2/2 首试）、10000（2/2）、11000（3/4，同会话恢复
  后 4/4）、12000（1/2）。**选 11000 字符 / `--window 1` → 55 块**（4500
  默认下是 142 块）。密集块（90KB+ context）是 flaky 的 — 总是 no-file
  失败。注意：长控制码行（`\FX[F]\FFFFF[1000Kenji_0004]` 前缀）游戏里
  context.md 预算按字符更吃紧。
- **新 harvest bug 类（大）：** `split_block` 的 `is_name_line` 把任何
  不带「」的首行当人名行。这游戏块以对话 + 说话人码开头，2,187 个预填
  块值保留首行日文（"drop-name" 且名字行没译）。60% 烘焙烘焙了这些部分
  值 → `extract_remaining_text` 正好把那些行当片段抓出 → agent 翻译 →
  修复是机械的：**从字典丢部分块键，发逐行片段条目**（块值第 1+ 行，
  第 0 行已由 chunks 覆盖）。2,187 全修，0 丢 line0。
- **字典里的 identity 条目（v == k）SHADOW 逐行 fallback。** 带 identity
  预填值的块键 → 块查找赢 → 两行保持日文，尽管有合法逐行片段翻译
  （第 1 行纯汉字，连假名残留扫描都看不见）。修复：**从最终字典删每个
  v==k 条目**（删 123 条；全是豁免类）再重烘焙。残留 24 → 21，真未译行
  消失。
- **`clean_kana_ticks.py` 对日文文本有破坏性**（词中 ん→嗯、ッ→!）。
  只能跑在"中文带尾缀残留"的值上；chunk 输出与 prefilled 分开跑，
  kind!=plugin / v!=k / 様-值守护，绝不跑含真日文片段的值（那要真翻译，
  不是字符替换）。它还会弄坏功能性插件参数字符串（kind=plugin）— 总是
  跳过。
- **残留验收：** 剩 21 键全豁免（7 个 CV/画师 様 名、4 个纯呻吟行、
  9 个功能性插件字符串、1 个编辑器内部标签）。

### 6.1 同一会话的工具加固（harvest / bake / shards）

- `harvest_translation.py`：`is_name_line` 只在首行剥离控制码后（
  `\C[3]角色名` 仍算）是短纯假名/汉字 + 可选敬语时才当说话人名 —
  FX/码前缀的对话行永不被当名字丢弃，所以 drop-name 路径不可能在预填
  块值里留日文首行。同时：`CODE_RE` 现在完整剥离多字母码
  （`\FX[F]\FFFFF[1000Kenji_0004]`），匹配 MTool 剥离显示的字典键。
- `bake_translation.py`：覆盖率闸门（低于 --min-coverage 0.5 拒绝烘焙并
  指引全量翻译，--force 覆盖）；identity 条目（v==k 带假名）自动剔除；
  <TE:>/<namePop:> dangling 引用自动检查；translation_kv.json 自动归档。
- `gen_translation_shards.py`：auto 选档现在是默认
  （--target-chunks N / --context-budget-kb 90 二分搜索，上下文估算误差
  <3%）。
- 会话工具修复：`harvest_translation.py` 用纯 `utf-8` 读工作文件但
  `build_translation.py` 写 `utf-8-sig`（BOM）— 读改为 `utf-8-sig`。
  `bake_translation.py` 在 `parameters` 为空的 401/405 命令上崩（块写
  路径）— 写前像逐行路径那样归一化为 `[""]`。
- 游戏根的奖励 ZIP 不是垃圾 — 删除前检查是不是游戏官方通关特典（游戏内
  NPC 经 `<namePop:…>` note 引用）。名字引用在对应地图 patch 成译名并
  记录进 translation_kv.json（namePop Lv<N> 标签保持原样）。
- 自带全解锁 NPC 的游戏不需要 `unlock_gallery.py`。

### 6.2 harvest / 分块 QC 的几处静默错译源（2026-09，已修复 + 单测）

这一轮给此前 0% 覆盖的分块/收割/QC 工具补了单测，写测试时逐条查出来
的——都属于「不报错但结果错」的类型：

- **只有控制码的字典键不能当“剥码匹配”的来源**：`harvest_translation.py`
  用 `strip_codes(key)` 建反向索引，而 `\N[1]` 这类键剥完是空串 →
  任何“只有控制码”的模板键都会借到它的值（还把开关包两次）。
  修复：剥完为空（或本来就是空）的条目不入索引，这类键归入 missing。
- **值已自带控制码时不要再用键的码包裹**：字典的值常自带 `\C[3]`，
  再前置/后置键的前导/尾随码就成了 `\C[3]\C[3]…`，且会被 QC 判为
  控制码差异。修复：值里已出现控制码就原样采用（不再包裹）。
- **引号内文本路径丢码**：键 `"\C[3]こんにちは"` 走“引号内匹配”时，
  重建的值只有引号、丢了引号内的 `\C[3]`——直接出货就是丢样式码的文本。
  修复：与单行路径一致地补回引号内的前导/尾随码。
- **note 前缀重复**：`<SG説明` 之前的字面前缀本身已含前导码，旧代码
  又拼了一次 `leading_codes(k[:i])` → `\C[3]\C[3]…`。修复：只保留
  字面前缀（它就是原文里那一段）。
- **分块 QC 的 KEY ORDER 检查是死代码**：`order_diff` 只在键集合不等时
  才有值，而那种情况已由 missing/extra 报告覆盖 → “键全在但顺序全乱”
  会被静默放过（ja/zh 契约是逐行的，顺序错位是真的缺陷）。修复：比较
  两侧共享键的**位置序**，报出第一处错位。
- **补键报告被丢弃**：`issues` 在 `patch_altered_keys` 之后被 `validate`
  的返回值直接覆盖，于是“修好了 N 个键”永不打印，修过的块看起来是干净
  的。修复：两份报告合并输出（修好仍然算“有改动”，应当可见）。
- **补翻块生成器里的死代码**：“贪心装包后再合并相邻小块”永远不会触发
  （非末块已是极大的，再加下一个键必然超预算）。删除，并用不变量测试
  （`test_no_chunk_may_be_extended`）钉住“块已极大”，防止回归。

同时纠正一处误读：`chunk_NN.meta.json` 的 `maps` 取自 `where`（人类可读
位置串 `"<地图名> / EV%03d <事件名>"`，DB 键则是文件名），所以取第一个
`/` 之前的部分得到的正是**地图名**；不要拿 `loc`（`file#ev0#pg0#c0`）去
印证它。
