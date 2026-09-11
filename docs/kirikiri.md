# KiriKiri（吉里吉里）翻译指南

KiriKiri / krkrz 引擎游戏（`Game.exe` + `data.xp3` 等）的 JP→ZH 翻译流程：
**解包 → 提取 → 分块 → subagent 翻译 → 合并 → 写回补丁 → 打包
patch.xp3**。翻译通过 patch.xp3 叠加实现，**不动原档、不做 Ren'Py 移植**
（旧 JoiPlay 移植方向已废弃，历史工具链不再维护）。

## 1. 引擎识别

- 目录：`Game.exe` + 若干 `.xp3`（`data.xp3` / `patch.xp3` / `update.xp3`），
  常带 `version.dll` / `krkr*.dll`。
- xp3 魔数 `XP3\r\n \n\x1a\x8b\x67\x01`（11 字节，不是 `XP3\x00\x01`）。
- 场景脚本在 `scenario/*.ks`；编码按文件探测（UTF-16LE/BE BOM、
  UTF-8、Shift-JIS 依次尝试）。
- **档案加载优先级：patch.xp3 > update.xp3 > data.xp3** —— 同名文件
  先到先得，翻译就是往 patch.xp3 里放改过的 scenario 文件。

## 2. 解包（`kirikiri/xp3tool.py`）

```
python3 kirikiri/xp3tool.py list <game>/data.xp3
python3 kirikiri/xp3tool.py extract <game>/data.xp3 <work>/game
```

若游戏自带 patch.xp3 / update.xp3，**解到同一个目录里覆盖**（高优先级
版本在低优先级之上，等价引擎行为）：

```
python3 kirikiri/xp3tool.py extract <game>/patch.xp3 <work>/game
```

格式要点（解析器已验证，勿改字节逻辑）：

- 索引指针：位置 11 起多个 int64；**0x80 块 = 间接跳转**（读取块 +9 的
  下一指针）。
- 索引块 flag：0=RAW（int64 size）、1=ZLIB（int64 csize + int64 usize +
  zlib 流）、0x80 = CONTINUE。
- File 块子块：`File` / `info` / `segm`（大小写敏感，`info` 小写！）。
- 段（segm）记录 28 字节：flags u32、start i64、org i64、arc i64；
  flags&7 = 0 raw / 1 zlib。
- 索引/段名可嵌套方括号 —— 解析用块边界，不靠正则扫描。

## 3. 提取（`tools/build_ks_translation.py`）

```
python3 tools/build_ks_translation.py <work>/game <work> [--entry start.ks]
```

产出与 RPG Maker / Wolf RPG **同一套标准工作包**（template.json /
kinds.json / structure.json / context.json + `scenario/` 拷贝），可直接走
统一 chunk 流程。规则：

- **键 = 整行**（`strip()` 后），行内 `[l]` 等格式标签与 `text="..."`
  属性原样保留在键里 —— 翻译即译行内日文片段、标签/属性一个字节不动
  （与 RPG Maker 控制码同一契约）。这同时覆盖对白、名字窗（`[name
  text=".."]`）、消息窗（`[wm2 text=".."]`）、选择肢（`[select_caption
  text=".."]`）。
- **`*` 标签行、`;` 注释行、`@` 纯命令行、未配对方括号的行一律不提取**
  （防止改坏跳转目标与宏）。
- 判定可译：行体内或 `text=".."` 属性里有日文（假名或汉字）。纯汉字行
  （如 `text="雪風"`）也会被提取 —— 名字窗靠它译。
- **故事顺序**：从入口脚本（默认 `start.ks`）沿 `[call storage=..]` /
  `[jump storage=..]` 引用 BFS 追踪；`[next]` 视为接续全部剩余文件；
  从未被引用的孤立文件按排序追加。`@bg storage="bg1"` 这类**素材引用
  不追踪**（storage 属性只有 call/jump 里才是场景文件）。
- context.json 窗口 = 相邻可译行的**标签剥离后**的正文（供 agent 看语境）。
- 体量协商、分片、subagent 翻译、合并 —— 全走 `docs/translation.md`
  的统一流程，无需任何 KiriKiri 专用步骤。

## 4. 写回与打包（`tools/apply_ks_translation.py`）

```
python3 tools/apply_ks_translation.py <work> --pack patch.xp3
```

- 按 structure.json 的 (文件, 行号) **整行替换**：保留行首缩进与行尾
  符；字典未命中的行原样保留并计数（含文件:行定位日志）。
- **编码**：文件保持原编码写回；**Shift-JIS 编不下中文时整文件转
  UTF-16LE**（引擎按 BOM 嗅探，无碍）并 WARN 提示。UTF-16 原文件写回
  时 Python 自动补 BOM（原无 BOM 也无妨）。
- `--pack patch.xp3` 调用 `kirikiri/xp3pack.py` 打包：raw 段 + zlib
  索引 + 写完自校验（用 xp3tool 解析器回读比对）。patch.xp3 放到
  Game.exe 旁即可，引擎自动叠加。
- 交付约定同其他引擎：成品目录 + 压缩包，绝不改原版游戏目录。

## 5. QC（`tools/qc_ks_kana.py`）

```
python3 tools/qc_ks_kana.py <work>/patch        # 补丁树假名残留（文件:行）
python3 tools/qc_ks_kana.py --values <translated.json>   # 字典值残留
```

- 残留判定用**假名**（含半角片假名），汉字不算（中文/日文共享 CJK 块，
  按汉字查会全部误报）。
- **只查可译的显示文本**：`*` 标签行、`;` 注释、`[iscript]`/
  `[tb_start_tyrano_code]` 代码块、代码语句，以及变量引用
  （`&f.名前`、`f.ほめ会話番号 = ...`）一律跳过。TyranoScript 合法允许
  日文标识符，不排除它们会把真漏译淹掉。
  **实测**：一款**已完整翻译**的 Tyrano 构建（8012 行可译）用旧口径报
  `834 residual (10.4%)`，逐条归因后 **767 条（92%）是变量名与代码**，
  真实漏译≈0；同一构建修正后报 `0 residual`，而未翻译的引擎样本剧本仍
  报 `97.3%`（拦得全对白）。据此改动前：一个不知情的 agent 会去"修"这些
  残留，把脚本引用改坏。
- 残留的每一行都报 `文件:行号` 与片段；若命中落在 `target="*..."` 里，
  **那是跳转目标，绝不能翻**（翻了会改坏跳转），先查清再动。
- 全假名残留归零 = 全部可译行都已译。

## 6. 字体（中文方块）

KiriKiri 走系统字体（GDI/DirectWrite）：游戏配置的日文字体缺 GB 汉字 →
方块。常见解法：给系统/游戏安装**合并中文字体**
（`kirikiri/merge_font.py <中文字体> <日文字体> <out.ttf>`，中文在前，
字形优先级归中文；日文字体补齐中文字体缺的汉字），或按游戏调整
config.tjs 的 Font 设置。**每个游戏的具体做法不同，跑通的方案记入
`docs/table/<Game>/notes.md`（不入库）。**

## 7. 与 Wolf RPG 流程的异同

| 环节 | Wolf RPG | KiriKiri |
|---|---|---|
| 容器 | `.wolf`（DXArchive v8） | `.xp3`（krkrz） |
| 文本载体 | 补丁 .txt（rewolf-trans 格式） | 场景 .ks 原文件 |
| 注入方式 | rewolf-trans 补丁目录回写 | **patch.xp3 覆盖 scenario/** |
| 编码 | 引擎数据内声明（SJIS/UTF-8） | 每文件 BOM/内容探测 |
| 键粒度 | 整条消息（含真实换行） | 整行（标签内嵌） |

两者共用：标准工作包 → 统一 chunk/subagent 翻译 → translated.json →
写回 → QC 假名残留。
