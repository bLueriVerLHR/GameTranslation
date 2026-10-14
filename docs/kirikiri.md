# KiriKiri（吉里吉里）翻译指南

KiriKiri / krkrz 引擎游戏（`Game.exe` + `data.xp3` 等）的 JP→ZH 翻译链：解包 →
提取 → 分块翻译 → 合并 → 写回 patch.xp3。译文通过 patch.xp3 叠加在原始档案之上
生效，原档不作任何改动。

## 1. 引擎识别

- 目录：`Game.exe` 加若干 `.xp3`（XP3，KiriKiri 的资源归档格式：`data.xp3`、
  `patch.xp3`、`update.xp3`），常带 `version.dll`、`krkr*.dll`。
- xp3 魔数 `XP3\r\n \n\x1a\x8b\x67\x01`（11 字节，不是 `XP3\x00\x01`）。
- 场景脚本在 `scenario/*.ks`；编码按文件探测（UTF-16LE/BE BOM、UTF-8、
  Shift-JIS 依次尝试）。
- 档案加载优先级 `patch.xp3 > update.xp3 > data.xp3`：同名文件先到先得，所以
  翻译就是往 patch.xp3 里放改过的 scenario 文件。

## 2. 解包

```bash
python3 kirikiri/xp3tool.py list <game>/data.xp3
python3 kirikiri/xp3tool.py extract <game>/data.xp3 <work>/game
```

游戏自带 patch.xp3 或 update.xp3 时，解到同一个目录里覆盖（高优先级版本盖在低
优先级之上，等价引擎行为）：

```bash
python3 kirikiri/xp3tool.py extract <game>/patch.xp3 <work>/game
```

格式要点（解析器已用真实档案验证，勿改字节逻辑）：

- 索引指针：位置 11 起多个 int64；`0x80` 块是间接跳转，真实指针在块内 +9 处。
- 索引块 flag：`0` = RAW（int64 size）、`1` = ZLIB（int64 csize + int64 usize +
  zlib 流）、`0x80` = CONTINUE。
- File 块子块：`File`、`info`、`segm`（大小写敏感，`info` 是小写）、`adlr`。
- `adlr` 块不能缺：krkrz 的 `tTVPXP3Archive::LoadIndex` 找不到该子块就直接
  抛 `TVPReadError`，KAG 报「Script exception raised / Read error」，游戏一个
  脚本都跑不到。值是该条目未压缩内容的 Adler-32（`zlib.adler32(data)`），引擎
  把它交给游戏的解包过滤器当逐文件密钥。实测真实档案每个条目都有；xpacker 的旧
  写法（无 `adlr`、`info` 的 arc size 写 0）自身能回读，但引擎拒收，所以用自家
  解析器自检是循环验证，打包后必须用引擎实跑一次（见 §6）。
- `info` 字段序：flags(u32)、org size(i64)、arc size(i64)、name len(u16)、
  name(UTF-16LE)；raw 段两者相等。
- 段（segm）记录 28 字节：flags u32、start i64、org i64、arc i64；`flags & 7`
  为 0 表示 raw，1 表示 zlib。
- 索引名与段名可以嵌套方括号，解析按块边界走，不靠正则扫描。

## 3. 受保护变体：检测并拒绝

少量商业发行版带受保护档案：条目名被替换成一串无扩展名的连续序号（如 `U+5000`
起的私用区序列），载荷也不是可识别的文件。读它们的引擎自带配套 loader，所以游戏
能跑；但解包出来只是一堆匿名二进制，不能当提取输入，因为脚本按逻辑名引用素材，
名字没了就无从对应。

`xp3tool.py` 的 `list`/`extract` 先做体检，命中就拒绝非零退出：

```
ERROR xp3tool: <path>: refusing to unpack - this archive looks like a protected
variant: 8357 of 8358 entry names carry no file extension and none of the 8
probed payloads shows a recognizable file signature or text. ...
```

判据分两段：

1. 名字扫描（代价低）：`\.扩展名$` 的条目占比低于 5%，且条目数不少于 20（太少
   时比例无意义）。
2. 载荷抽样（可翻案）：解 8 个小条目的内容，只要有任何一个带已知 magic
   （PNG/JPEG/OggS/RIFF/BM/gzip/zip/PSB/TJS/XP3）、能 zlib 解压、或是严格
   UTF-8（95% 以上可打印且 20% 以上 ASCII）文本，就判定为正常。

两条注意：

- 真名含日文或中文是正常的（`画像/背景01.png`），判据只看有没有扩展名，不能只
  看有没有 CJK。实测 6 个正常档案（含 1249/1342、439/680 这种混排）全部放行。
- 不要用单字节编码（cp932）当文本证据：cp932 几乎把每个字节都映成可打印字符，
  密文也能解得很干净，实测就是它把名字混淆、内容不透明的档案误判成正常。

诊断需要绕过体检时加 `--force`，它只影响 `list`/`extract`，不代表可以提取。判定
为受保护变体时不作解密或改写，改用未加密副本；记录只写「引擎 + 特征」（名字
序号化、载荷不透明）。

## 4. 提取

```bash
python3 tools/build_ks_translation.py <work>/game <work> \
    [--scenario-dir scenario] [--entry start.ks]
```

产出与 TyranoScript、Wolf RPG 同一套标准工作包（`template.json`、`kinds.json`、
`structure.json`、`context.json` 加 `scenario/` 拷贝），之后走统一 chunk 链。

- 键 = 整行（`strip()` 之后），行内 `[l]` 等格式标签与 `text="..."` 属性原样保留
  在键里，翻译即译行内日文片段、标签与属性一个字节不动。
- 显示文本的识别范围是**任何属性**，不只是字面 `text=`：游戏自定义宏把可见
  字符串放在自己的参数名里（`[NAME_M n=".."]` 说话人名、
  `[SELECT_CENTER text=".." sel_1=".."]` 选项提示与选项文字、
  `[title name=".."]` 窗口标题），只认 `text=` 会把这些行整行漏掉，实测漏
  19151 行、去重后 57 个字符串，发布的构建里选项文字仍是日文。
- 两类属性永远不算显示文本：① 代码属性 `exp`/`js`/`script`/`eval`/
  `condition`，值是表达式，翻里面的字符串字面量会改坏比较
  （`[if exp="f.name=='ゆき'"]`）；② 引用属性 `storage`/`target`/`file*`/
  `tag*`/`path`/`folder`/`url`/`src`/`id`，KAG3 的文件名与标签名合法地含日文，
  翻一个就是改坏跳转。
- `*` 标签行、`;` 注释行、代码块（`[iscript]`/`@iscript` 到 `[endscript]`/
  `@endscript`）、未配对方括号的行一律不提取，防止改坏跳转目标与宏；代码块未
  闭合时报 WARN 并带文件名，而不是静默丢文本。
- 代码块整块不提取，两种方言都要认：KAG3 的短标签方言把 `[iscript]` 写成
  `@iscript`（`@cg file=..`、`@playbgm ..` 同理），只认方括号形式会把整块 TJS
  当台词提取。实测一款 KAG3 游戏有 1556 行落在代码块内、其中 429 行含日文
  （绝大多数是插件注释与日文标识符），而且 QC 共用同一 helper，于是提取端把代码
  当文本、QC 端把标识符报成残留，两头都错。`kirikiri/ks_extract.py` 的
  `iter_candidate_lines` 统一判定并覆盖三个边界：单行
  `[iscript]..[endscript]` 不吞掉后文、注释里的 `;[iscript]` 不会开启代码块、
  代码块未闭合时报 WARN。
- 短标签方言的行不按属性拆分（只有方括号形式走标签与属性解析），整行当正文，
  所以带日文的资源行（如 `@cg file=背景.png`）会被当作待译行。这类行的属性名与
  文件名都不能译，只有行里其它日文片段可以改。
- 代码块里的字符串字面量是真缺口，不假装没有：同一款游戏代码块内只有 17 处含
  日文字面量，其中 15 处是插件的开发者警告（宏误用诊断，正常游玩看不到），2 处
  是音量菜单标签（`音量(&O)` 一类）。整块跳过不丢对白；某款游戏把 UI 文本写在
  `.tjs` 里时需要单独一轮代码内字符串的定点处理，不要放宽提取规则。
- 判定可译：行体内或任一显示属性里有日文（假名或汉字）。纯汉字行
  （`text="雪風"`）也会被提取，名字窗靠它译；QC 要用假名正则
  `[\u3040-\u30ff]`，中文与日文共用 CJK 汉字区，按汉字查会全部误报。
- 故事顺序：从入口脚本（默认 `start.ks`）沿 `[call]`/`[jump]` 的 storage 引用
  BFS 追踪；`[next]` 视为接续全部剩余文件；从未被引用的孤立文件按排序追加。
  `@bg storage="bg1"` 这类素材引用不追踪，storage 属性只有出现在 call 或 jump
  里才是场景文件。
- `context.json` 的窗口是相邻可译行剥离标签后的正文，供翻译时看语境。
- 旧规则产出的树要补翻时，把宏参数里的日文整理成外部 `{日文: 中文}` JSON 做属性
  级替换。写回保持原编码；Shift-JIS 装不下中文时整文件转 UTF-16LE（引擎按 BOM
  嗅探）并 WARN。

体量协商、分片、分块翻译、合并全走 `docs/translation.md` 的统一流程，KiriKiri
没有专用步骤。

## 5. 写回与打包

```bash
python3 tools/apply_ks_translation.py <work> --pack patch.xp3
```

- 按 `structure.json` 的（文件，行号）整行替换：保留行首缩进与行尾符；字典未
  命中的行原样保留并计数，日志带文件与行号定位。
- 编码：文件保持原编码写回；Shift-JIS 装不下中文时整文件转 UTF-16LE 并 WARN。
  UTF-16 原文件写回时 Python 自动补 BOM，原文件无 BOM 也无妨。
- 选项：`--scenario-dir` 指定要改的 scenario 树（默认 `<work>/scenario`），
  `--out` 指定改后目录（默认 `<work>/patch`），`--pack patch.xp3` 相对
  `<work>` 输出压缩包。
- `--pack` 调用 `kirikiri/xp3pack.py` 打包：raw 段加 zlib 索引，写完自校验（用
  xp3tool 的解析器回读，比对文件名、大小与 Adler-32）。
- patch.xp3 放到 `Game.exe` 旁即可，引擎自动叠加。
- 交付约定同其他引擎：成品目录加压缩包，绝不改原版游戏目录。

## 6. patch.xp3 的容器契约

不遵守契约的表现是游戏启动即报错。

- 条目放在档案根，不要建 `scenario/` 子目录。引擎按文件名查表
  （`TVPExtractStorageName` 之后的自动搜索路径表），patch.xp3 默认只把根目录
  条目登记进去，所以里面放 `Room.ks`（而不是 `scenario/Room.ks`）才能覆盖
  data.xp3 的 `scenario/Room.ks`。想让 patch 保留目录结构，必须在 patch 里额外
  放一个根目录 `Config.tjs` 注册
  `Storages.addAutoPath(System.exePath + "patch.xp3>scenario/")`；不改
  `Config.tjs` 的话子目录条目永远不被读到。剧本内的 `[call storage=x.ks]` 是裸
  文件名，靠引擎的 `scenario/` 自动路径找到，与 patch 的布局无关。
- 每个 File 块必须有 `adlr` 子块（未压缩内容的 Adler-32）。缺了引擎抛
  `TVPReadError`，游戏显示「Script exception raised / Read error」后直接停住
  （实跑确认）。`xp3pack.py` 会写该块，`xp3tool.py` 在缺失时 WARN，
  `xp3pack.verify` 把缺失或错值的 Adler-32 当失败。
- 打包后必须实跑验证：`xp3pack.verify` 用的是仓库自己的解析器，与写入端同源，
  只能防内部不一致，引擎是否接受只能靠真跑。最小验法是放两三行带中文的标记补丁
  进 patch.xp3，启动游戏确认三件事：不报错、标记文字真的上屏（覆盖生效）、中文
  不是方块（字体可用）。
- 中文渲染：游戏字体（如 MS Gothic）本身没有 GB 汉字时，Windows 的 GDI 字体
  回退仍能画出简体汉字，假名与拉丁走原字体，先实拍确认。要统一字体的话，在
  patch 根目录放 `Config.tjs` 改 `;userFace = "<字体名>"`（引擎查裸名
  `Config.tjs` 时 patch 根优先），前提是该字体在系统里。KAG3 的设置会被存档
  变量文件的 `chdefaultFace` 覆盖，改字体后要先删存档里的那一行或重开存档。

## 7. QC

```bash
python3 tools/qc_ks_kana.py <work>/patch
python3 tools/qc_ks_kana.py --values <translated.json>
```

- 残留判定用假名（含半角片假名），汉字不算：中文与日文共用 CJK 块，按汉字查会
  全部误报。
- 只查可译的显示文本：`*` 标签行、`;` 注释、`[iscript]`/`@iscript`/
  `[tb_start_tyrano_code]` 代码块、代码语句，以及变量引用（`&f.名前`、
  `f.ほめ会話番号 = ...`）一律跳过，与提取器共用 `iter_candidate_lines`，两边
  对「什么算文本」的判定必须一致。TyranoScript 合法允许日文标识符，不排除它们
  会把真漏译淹掉。
- 实测对比：一款已完整翻译的 Tyrano 构建（8012 行可译）用旧口径报
  `834 residual (10.4%)`，逐条归因后 767 条（92%）是变量名与代码，真实漏译约
  0；同一构建修正后报 0 残留，而未翻译的引擎样本剧本仍报 97.3%。旧口径报出的
  残留不能当漏译逐条修：那 767 条是变量名与代码，改一处就改坏脚本引用。
- 残留的每一行都报 `文件:行号` 与片段；命中落在 `target="*..."` 里时，那是跳转
  目标，绝不能翻，先查清再动。
- 全假名残留归零表示全部可译行都已译。

## 8. 字体

KiriKiri 走系统字体（GDI/DirectWrite）：游戏配置的日文字体缺 GB 汉字时显示方块。
常见解法是给系统或游戏装一款合并中文字体：

```bash
python3 kirikiri/merge_font.py <中文字体> <日文字体> <out.ttf> [--upm 2048]
```

中文字体放在前，所以两者都覆盖的码位以中文字形为准；日文字体补齐中文字体缺的
汉字。两个输入先统一到 2048 units-per-em 再合并。字体注册方式逐游戏不同，跑通的
方案记入该游戏的本地工作区笔记（见 `docs/reference/local-layout.md`）。

## 9. 与 Wolf RPG 流程的异同

| 环节 | Wolf RPG | KiriKiri |
|---|---|---|
| 容器 | `.wolf`（DXArchive v8） | `.xp3`（krkrz） |
| 文本载体 | 补丁 .txt（rewolf-trans 格式） | 场景 .ks 原文件 |
| 注入方式 | rewolf-trans 补丁目录回写 | patch.xp3 覆盖 scenario/ |
| 编码 | 引擎数据内声明（SJIS/UTF-8） | 每文件 BOM 与内容探测 |
| 键粒度 | 整条消息（含真实换行） | 整行（标签内嵌） |

两者共用：标准工作包 → 统一 chunk 链翻译 → `translated.json` → 写回 → 假名
残留 QC。
