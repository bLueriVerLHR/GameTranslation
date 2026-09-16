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
- File 块子块：`File` / `info` / `segm`（大小写敏感，`info` 小写！）/
  **`adlr`**（Adler-32，小写，**引擎强制要求**，见下）。
- **`adlr` 块不能缺**：krkrz 的 `tTVPXP3Archive::LoadIndex` 找不到 `adlr`
  子块就直接 `TVPReadError`，KAG 报「Script exception raised / Read error」，
  **游戏一个脚本都跑不到**；值是该条目**未压缩**内容的 Adler-32
  （`zlib.adler32(data)`），引擎把它交给游戏的解包过滤器当逐文件密钥。
  实测真作档案每个条目都有；xpacker 旧的写法（无 `adlr`、`info` 的
  arc size 写 0）自身能回读、但引擎拒收 —— **用自家 parser 自检是循环
  验证**，打包后必须用引擎实跑一次（见 §4）。
- `info` 字段序：flags(u32)、**org size**(i64)、**arc size**(i64)、
  name len(u16)、name(UTF-16LE)；raw 段两者相等。
- 段（segm）记录 28 字节：flags u32、start i64、org i64、arc i64；
  flags&7 = 0 raw / 1 zlib。
- 索引/段名可嵌套方括号 —— 解析用块边界，不靠正则扫描。

### 2.1 受保护变体：检测并明确拒绝（不静默产出垃圾）

少量商业发行版会带**受保护**档案：条目名被替换成一串无扩展名的连续
序号（如 `U+5000` 起的私用序列），载荷也不是可识别的文件。读它们的引擎
自带配套 loader，所以**游戏能跑**；但解包出来只是一堆匿名二进制，**不能
当转换输入**（脚本按逻辑名引用素材，名字没了就无从对应）。

`xp3tool.py` 的 `list`/`extract` 会先做体检，命中就拒绝（退出码 1）：

```
ERROR xp3tool: <path>: refusing to unpack - this archive looks like a protected
variant: 8357 of 8358 entry names carry no file extension and none of the 8
probed payloads shows a recognizable file signature or text. ...
```

判据（两段式，故意的）：

1. **名字扫描**（便宜）：`\.扩展名$` 的条目占比 < 5%，且条目数 ≥ 20
   （太少时比例无意义）。
2. **载荷抽样**（可翻案）：解 8 个小条目的内容，若**有任何一个**带已知
   magic（PNG/JPEG/OggS/RIFF/BM/gzip/zip/PSB/TJS/XP3）、能 zlib 解压、
   或是**严格 UTF-8**（≥95% 可打印且 ≥20% ASCII）文本，就判定为正常。

两条注意：

- **真名含日文/中文是正常的**（`画像/背景01.png`），判据只看「有没有
  扩展名」，绝不能只看「有没有 CJK」。实测 6 个正常档案（含 1249/1342、
   439/680 这种混排）全部放行。
- **不要用单字节编码（cp932）当「文本」证据**：cp932 几乎把每个字节都
  映成可打印字符，密文也能「解得很干净」——实测就是它把名字混淆 + 内容
  不透明的档案误判成正常。

诊断需要绕过体检时加 `--force`（只做 list/extract，不代表可转换）。

> 判定为受保护变体时，**不做**解密/改写：放弃该档案，改用未加密副本。
> 记录只需写「引擎 + 特征」（名字序号化 + 载荷不透明），不写来源渠道。

## 3. 提取（`tools/build_ks_translation.py`）

```
python3 tools/build_ks_translation.py <work>/game <work> [--entry start.ks]
```

产出与 RPG Maker / Wolf RPG **同一套标准工作包**（template.json /
kinds.json / structure.json / context.json + `scenario/` 拷贝），可直接走
统一 chunk 流程。规则：

- **键 = 整行**（`strip()` 后），行内 `[l]` 等格式标签与 `text="..."`
  属性原样保留在键里 —— 翻译即译行内日文片段、标签/属性一个字节不动
  （与 RPG Maker 控制码同一契约）。显示文本的识别范围是 **任何属性**
  （不只是字面 `text=`）：游戏自定义宏把可见字符串放在自己的参数名里
  （`[NAME_M n=".."]` 说话人名、`[SELECT_CENTER text=".." sel_1=".."]`
  选项提示与选项文字、`[title name=".."]` 窗口标题），只认 `text=` 会把这些
  行 **整行漏掉**（曾实测漏 19151 行 / 去重 57 个字符串，发布的构建里选项
  文字仍是日文）。两类属性 **永远不算**显示文本：① 代码属性
  `exp`/`js`/`script`/`eval`/`condition` —— 值是表达式，翻里面的字符串字面量
  会改坏比较（`[if exp="f.name=='ゆき'"]`）；② 引用属性
  `storage`/`target`/`file*`/`tag*`/`path`/`folder`/`url`/`src`/`id` ——
  KAG3 的文件名与标签名合法地含日文，翻一个就是改坏跳转。
- **旧规则产出的树要补翻**：宏参数里的日文写成外部 `{日文: 中文}` JSON，做
  属性级替换（`.tmp/archive/scripts/fix/ks_attr_translate.py`）——写回保持原编码，
  Shift-JIS 装不下中文时整文件转 UTF-16LE（引擎嗅探 BOM）并 WARN。
- **`*` 标签行、`;` 注释行、`@` 纯命令行、未配对方括号的行一律不提取**
  （防止改坏跳转目标与宏）。
- **代码块整块不提取，两种方言都要认**：KAG3 的短标签方言把
  `[iscript]` 直接写成 `@iscript`（`@cg file=..`、`@playbgm ..` 同理），
  只认方括号形式就会把整块 TJS 当台词提取 —— 实测一款 KAG3 游戏有
  **1556 行落在代码块内、429 行含日文**（绝大多数是插件注释与日文
  标识符），且 QC 共用同一 helper，于是提取端把代码当文本、QC 端把
  标识符报成残留，两头都错。`kirikiri/ks_extract.py::iter_candidate_lines`
  现在统一判定（提取器与 QC 共用），并覆盖三个边界：单行
  `[iscript]..[endscript]` 不吞掉后文、`;[iscript]`（注释里写标签）不会
  开启代码块、代码块未闭合时报 WARN（带文件名）而非静默丢文本。
- **代码块里的字符串字面量是真缺口，不要假装没有**：同一款游戏代码块内
  只有 17 处含日文字面量 —— 15 处是插件的开发者警告（`eximage`/`exmove`
  宏误用诊断，正常游玩看不到）+ 2 处音量菜单标签（`音量(&O)` 等）。
  整块跳过不丢对白；若某款游戏把 UI 文本写在 `.tjs` 里，需要单独一轮
  代码内字符串的定点处理，别放宽提取规则。
- 判定可译：行体内或**任一显示属性**里有日文（假名或汉字）。纯汉字行
  （如 `text="雪風"`）也会被提取 —— 名字窗靠它译；**QC 要用假名正则**
  `[\u3040-\u30ff]`，中文与日文共用 CJK 汉字区，按汉字查会全部误报。
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

### 4.1 patch.xp3 的容器契约（不遵守 = 游戏启动即报错）

- **条目就在档案根，不要建 `scenario/` 子目录**：引擎按**文件名**查表
  （`TVPExtractStorageName` 后的自动搜索路径表），`patch.xp3` 默认只把
  根目录条目登记进去，所以 `patch.xp3` 里放 `Room.ks`（而不是
  `scenario/Room.ks`）才能覆盖 `data.xp3` 的 `scenario/Room.ks`。
  想让 patch 保留目录结构，必须在 patch 里额外放一个根目录 `Config.tjs`
  注册 `Storages.addAutoPath(System.exePath + "patch.xp3>scenario/")`
  —— 不改 `Config.tjs` 的话子目录条目**永远不被读到**。
  （剧本内的 `[call storage=x.ks]` 是裸文件名，靠引擎的 `scenario/`
  自动路径找到，与 patch 的布局无关。）
- **每个 File 块必须有 `adlr` 子块**（未压缩内容的 Adler-32）；缺了引擎
  抛 `TVPReadError`，游戏显示「Script exception raised / Read error」
  后直接停住（实跑确认）。`xp3pack.py` 已写该块，`xp3tool.py` 会在缺失时
  WARN，`xp3pack.verify` 会把缺失/错值的 Adler-32 当失败。
- **打包后必须实跑验证**：`xp3pack.verify` 用的是仓库自己的 parser，与
  写入端同为一家，**只能防内部不一致**；引擎是否接受只能靠真跑。
  最小验法：放两三行带中文的**标记补丁**进 `patch.xp3`，启动游戏确认
  ①不报错 ②标记文字真的上屏（证明覆盖生效）③中文不是方块（证明字体）。
  实测该验法一次回答上面三个问题（首次跑通的补丁就是这样验的）。
- **中文渲染**：游戏字体（如 MS Gothic）本身没有 GB 汉字时，Windows 的
  GDI 字体回退仍能把简体汉字画出来（假名/拉丁走原字体）—— 先实拍确认；
  若要统一字体，走 patch 根目录的 `Config.tjs` 改 `;userFace = "<字体名>"`
  （引擎裸名查 `Config.tjs` 时 patch 根优先），前提是该字体在系统里。
  注意 KAG3 的设置会被存档变量文件的 `chdefaultFace` 覆盖 —— 改字体后
  要先删存档里的那一行或重开存档。

## 5. QC（`tools/qc_ks_kana.py`）

```
python3 tools/qc_ks_kana.py <work>/patch        # 补丁树假名残留（文件:行）
python3 tools/qc_ks_kana.py --values <translated.json>   # 字典值残留
```

- 残留判定用**假名**（含半角片假名），汉字不算（中文/日文共享 CJK 块，
  按汉字查会全部误报）。
- **只查可译的显示文本**：`*` 标签行、`;` 注释、`[iscript]`/
  `@iscript`/`[tb_start_tyrano_code]` 代码块、代码语句，以及变量引用
  （`&f.名前`、`f.ほめ会話番号 = ...`）一律跳过（与提取器共用
  `iter_candidate_lines`，两边对「什么算文本」的判定必须一致）。
  TyranoScript 合法允许
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
