# KiriKiri → TyranoScript 转换调研（路线 B 深化）

调研目标：把 KiriKiri（吉里吉里 / KAG3）游戏转换为 **TyranoScript 项目**
的可行性与支持程度，产出物直接复用本仓库已验证的 `tyrano/` 构建 +
翻译工具链（`docs/tyrano.md`）。本文是 `docs/kirikiri-html.md` 路线 B
的深化调研（2026-08 复查），重点回答两件事：**支持程度**、**需要的软件**。

## 结论先行

- **没有现成的 KAG3→TyranoScript 自动转换器**（2026 复查确认），转换器
  必须自建；但 TyranoScript 引擎内部就是 KAG 插件架构，标签级映射为主，
  无需语法级重写。
- 支持程度分档（按游戏实际用到的 KAG3 特性）：
  - **A 档（推荐）**：标准 KAG3 标签 + `[if]/[eval]/[jump]` 表达式，正文
    在 `.ks` → 转换器可覆盖 ~九成，逐游戏少量调试。
  - **B 档（需裁剪）**：`iscript/endscript` 内嵌 TJS2 较多、或
    KAGEX3 扩展标签 → 需逐标签 shim/手译，成本陡增。
  - **C 档（不推荐）**：正文不在 `.ks`（`textrender.dll` 语法 /
    商业 SCN 格式）、编译型 `.ks`（`jk` 魔数）、重度插件 DLL →
    需专门解析器或反编译器，建议先走 JoiPlay 官方 KiriKiri 插件
    （路线 A）评估。
- 转换产物 = 标准 TyranoScript `data/` 布局 → 后续构建/音频/翻译/
  验证/交付全复用 `tyrano/pipeline.py`，无新基建。

## 1. 支持程度调研

### 1.1 现成工具盘点（结论：无可用转换器）

| 工具 | 性质 | 结论 |
| --- | --- | --- |
| TyranoStudio 官方 Script Converter | 纯文本→TyranoScript（按规则插标签） | 不解析 KAG3 标签，**不适用** |
| KS Converter（社区工具） | 纯文本→TyranoBuilder 脚本 | 不解析 KAG3，**不适用** |
| TSC（ウディタ2 工具） | txt→tyrano ks | 不解析 KAG3，**不适用** |
| 各类翻译工具（RuneTranslate 等） | KAG3 解析 + 翻译 | 只读解析，无转换产出，**不适用** |

TyranoScript 官方文档的 "KAG3/吉里吉里 compatible" 指**脚本风格亲缘**
（设计时参考吉里吉里 2 SDK），不是开箱即用的自动移植。

### 1.2 TyranoScript 引擎侧（转换目标的能力）

- 引擎自带 `tyrano/plugins/kag/` 插件目录（`kag.js` / `kag.parser.js` /
  `kag.tag.js` / `kag.tag_ext.js` / `kag.event.js` / `kag.rider.js` /
  `kag.audio.js` / `kag.tag_system.js`）——**引擎内核即 KAG 插件架构**。
- 语法亲缘度高（已验证同名同义）：`[tag attr=val]`、`*label` 跳转、
  `;` 注释、`#名前` 说话人缩写、`[jump]/[call]/[return]`、
  `[if]/[else]/[elsif]/[endif]/[ignore]/[endignore]`、
  `[macro]/[endmacro]`、`[chara_new]/[chara_show]/[chara_hide]/
  [chara_mod]/[chara_ptext]/[ptext]`、`[bg]/[bgm]/[playse]/[wait]`、
  `[l]/[r]/[p]/[s]/[cm]/[resetfont]/[font]/[position]/[layer]/
  [layopt]/[current]/[eval]/[label]`。
- 变量命名空间 `f./sf./tf.` 与 TJS2 一致；JS 可自由扩展。
- 存档默认 `configSave=webstorage`（浏览器 localStorage），天然适配
  JoiPlay。

### 1.3 KAG3 生态复杂度（转换难度的真实来源）

KAG3 由吉里吉里 2 SDK 的 `KAGParser.dll` 解析 `.ks`；常见变体：

1. **标准 KAG3**（KAGParser.dll）：绝大多数标签与 TyranoScript 同名，
   转换以属性级映射为主。**A 档**。
2. **KAGEX3**（`KAGParserEx.dll` / `KAGEnv*.tjs`，wtnbgo 扩展）：
   新增一批扩展标签，需单独映射。**A→B 档**。
3. **textrender.dll / texttagconverter.tjs**：正文用 TextRender 专用
   语法写在 `.ks` 之外，需先还原成 KAG 标签。**B 档**。
4. **商业 SCN 格式**（M2 的 SCN 解析器）：正文在 `.ks` 之外的 SCN
   文件，`scenario/*.ks` 只承担菜单/UI 角色。**C 档**——需移植 SCN
   解析器，成本不可控。
5. **编译型 `.ks`**（`jk` 魔数）：KAGParser 编译的字节码，无现成
   可靠反编译。**C 档**。
6. **乱序/压缩 `.ks`**（krkr2html / `x` 前缀签名等）：可用
   KirikiriDescrambler 还原为明文。**A 档（前提工具到位）**。
7. **编译型 `.tjs`**（TJS2100 字节码）：TJS2 反编译工具成功率有限
   （Furikiri 约 20%；较新的 Python 实现声称覆盖编译器全部模式并在
   完整游戏上验证）。**遇编译 .tjs 时 B→C 档**。
8. **插件 DLL**（krkr 插件无 HTML 等价物）：`windowEx`/`layerEx` 等
   需裁剪或 shim。**按游戏实际使用量定档**。

### 1.4 素材支持程度

| 素材 | KiriKiri 侧 | TyranoScript 侧 | 转换 | 难度 |
| --- | --- | --- | --- | --- |
| 图片 | jpg/png/**tlg**（TLG5/6/0，LZSS/Golomb） | png/jpg | tlg→png | 中（需解码器，见 §2） |
| 音频 | ogg（引擎原生）、mp3/wav | ogg 默认 | ogg 保留、mp3→ogg | 低（复用 `tyrano/audio.py`） |
| 视频 | wmv/mpg（要 krmovie.dll）、avi | mp4/webm | ffmpeg 直接转（原生支持）；amv（AlphaMovie 插件格式）需专用解码器 | 低（ffmpeg） |
| 字体 | 系统字体/合并字体 | @font-face | 复用 `kirikiri/merge_font.py` 思路 | 低 |

### 1.5 脚本转换要点（自建 `kirikiri/convert_kag.py` 时）

- **标签映射表**：同名标签直通；差异集中在默认值/单位（`[quake]`
  时间单位：KAG3 字符单位 vs ms）、`[trans]/[wt]` 过渡、
  `[movie]/[bgmovie]` 视频、`[image]/[freeimage]`、`[drawtext]`、
  `[cl]` 字色等。
- **表达式**：`[eval exp="..."]` / `[if exp="..."]` / `[jump target=..`
  `cond=..]` 里的 TJS2 表达式 → JS。要点：`!==`→`!=`、`&&`→`and`、
  `++`→`+= 1`、`f.xxx`→`f["xxx"]`、变量字典缺失返回 0 的 dict 子类
  语义。
- **`iscript/endscript` 内嵌 TJS2**：最重的一块，按游戏评估——能转则
  转、不能则 shim 注释（本地已有一款游戏的 Ren'Py 移植经验可参考其
  变量/表达式语义）。
- **patch 合并顺序**：多 xp3 解包到同一目录覆盖时保持优先版本文件顺序
  （原包不动）。
- **编码**：UTF-16LE/BE、Shift-JIS、UTF-8 按文件探测
  （`kirikiri/ks_extract.py`），写回 UTF-8（TyranoScript 标准）。
- **坑（按游戏实测记录，不入库）**：`cond` 属性几乎所有标签可用、
  时间单位差异、插件 DLL 无等价物、textrender 语法正文。

## 2. 需要的软件

### 2.1 已具备（本机/仓库）

| 软件 | 用途 | 现状 |
| --- | --- | --- |
| Python 3.10+（项目 `.venv`） | 转换器主体、脚本转换 | ✅ 已装（3.14） |
| Pillow | 图片缩放/重采样（`tools/downscale_images.py`） | ✅ 已装（12.3） |
| ffmpeg/ffprobe（libvorbis） | mp3/wav→ogg 重编码（`tyrano/audio.py`） | ✅ 已装 |
| Node.js + npx（`@electron/asar`） | TyranoScript 构建（解包 asar） | ✅ 已装（v24） |
| 7-Zip-Zstandard（`docs/table/3rd/`） | 压缩打包 | ✅ 已装 |
| ripgrep | 快速检索 | ✅ 已装 |
| `kirikiri/` 工具包 | xp3 解包/打包、.ks 解析、字体合并 | ✅ 仓库内 |
| `tyrano/` 工具链 | 构建/音频/验证/交付 | ✅ 仓库内 |
| 中文字体（`docs/table/fonts/`） | 汉化显示 | ✅ 本机 |

### 2.2 需要安装/获取（按游戏需要选用）

| 软件 | 用途 | 获取方式 | 何时必需 |
| --- | --- | --- | --- |
| **TLG 解码器** | tlg5/tlg6/tlg0→png（LZSS/Golomb 解压） | 三选一：GARbro（Windows GUI，含 TLG5 编码）；`arc_unpacker`（跨平台 CLI，tlg2png 已并入）；自写解码（参考 krkrz `LoadTLG.cpp` / GARbro `ImageTLG.cs`） | **A 档游戏含 tlg 素材时必需**（jpg/png 游戏可跳过） |
| **KirikiriDescrambler**（KirikiriTools 发布页） | 乱序/压缩 `.ks` 还原为明文 | Windows 二进制 | 遇乱序 `.ks` 时 |
| **TJS2 反编译器**（社区 Python 实现） | 编译 `.tjs`（TJS2100）→ 源码 | GitHub | 遇编译 `.tjs` 时（成功率有限，需评估） |
| **AMV 视频解码器**（AlphaMovie 插件格式，带 alpha 通道） | amv→mp4/webm | `xmoezzz/amv_decoder`（Rust）或 `xmoeproject/AlphaMovieDecoder` | 仅含 amv 视频的游戏（krkrz 官方格式清单里**没有 kmv**，wmv/mpg/avi 都是 ffmpeg 原生支持的） |
| 浏览器（本机已有） | serve 试玩验证 | 无需安装 | — |

> 无其他强制依赖。转换器本体只需 Python 标准库 + 仓库既有工具；
> TLG 解码器是唯一的"必装候选"，具体按首款目标游戏的实际素材定。

### 2.3 TyranoScript 引擎源码（转换骨架 + 本地运行时，已就位）

`kirikiri/convert_kag.py` 的 `engine` 参数需要一个 **TyranoScript 引擎
源码树**（含 `index.html`、`tyrano/`、`data/system/Config.tjs`），
转换器从中复制引擎骨架并把转换结果写进 `data/`。

| 项 | 值 |
| --- | --- |
| 来源 | `https://github.com/ShikemokuMK/tyranoscript`（官方 OSS 引擎，非 TyranoBuilder） |
| 本地位置 | `.tools/tyranoscript/`（仓库内，**已 gitignore，不入库**） |
| 获取 | `git clone --depth 1 --single-branch <url> .tools/tyranoscript` |

该目录**一物两用**：

1. **转换输入的引擎骨架** — `convert_kag.py <unpacked> .tools/tyranoscript <out>`；
2. **本地运行时（"模拟器"）** — 需要验证转换结果时，把转换出的
   `data/` 套在干净的引擎骨架上跑（引擎与数据分离），从而区分
   "引擎行为问题"与"转换数据问题"，不依赖原游戏的 Electron 打包环境。

网络受限时 GitHub 直连会间歇失败（重试即可，或走本机代理
`http://127.0.0.1:7890`）。

运行时验证（OCR/视觉复核）用 `visual-check`：
`tyrano/pipeline.py serve` 起服务 → headless 浏览器截图 → 读图。
注意转换出的构建**没有 `js/`**，因此不能用 `pipeline.py serve`。

## 3. 转换后常见缺口（实测清单，按影响排序）

首款游戏的实际转换暴露了一批**系统性**缺口，它们不会报错，只会让画面
变空。按“出现次数 × 影响”排序（数字来自一款真实 KAG3 游戏的实测）：

| # | 缺口 | 实测规模 | 后果 |
| --- | --- | --- | --- |
| 1 | **属性 `&表达式` 未展开** | 2851 处 | 最严重。KAG3 的 `attr="&expr"` 语义是**求值后代入**，Tyrano 无此语法 → 字面量存储名 → 素材解析失败。典型：`[START_MPEG file="&mpglist[0][1].mpeg_file"]`、`[playse storage="&f.t_voice[f.vnum]"]`。**文件都在，但永远读不到**。 |
| 2 | **`[wt]` 未映射** | 273 处 | 既不在 `SHIM_TAG_NAMES`、也不是 Tyrano 原生标签 → 未定义标签。KAG3 的 `[wt]`=等转场结束；应映射为等待或空操作（后续一般有 `[wait]` 兑底）。 |
| 3 | **KAG3 保留颜色名** | 少量 | `[image storage="black"]`/`wh` 被当成文件名 → 404。应生成/映射纯色图而非发请求。 |
| 4 | **素材被复制三份** | — | `_asset_map` 把同一图写进 `bgimage/`+`fgimage/`+`image/`（实测每图 3 份）。源素材 298 MB 时会膨胀到 ~900 MB，需按引用解析后只放一份（或建索引 + 单副本）。 |

### 已修：getter 贪婪正则吞掉 setter 块

`tjs2js` 的 property 转换曾用贪婪正则 `getter\s*...\{(.*)\}` 抽取
getter 体，把紧跟的 `setter(x){...}` **一并吞入**，于是 JS 里同时出现
原始 TJS `setter(ma){`（**非法语法**）和正确的 `set: function`。

- 症状：脚本运行到该文件**直接停住**（服务端日志表现为“请求停在这个
  文件之后再无任何请求”，且 CPU 空闲、CDP 不响应——很像是卡死）。
- 修法：`_tjs_property()` 用**配对花括号**抽取（`_brace_body`），不再
  吞入后续块，也不截断 getter 体内的 `if/for`。已加 4 个回归测试。

### 排障方法（这套很有用，值得沿用）

1. **看服务端请求日志定“死在哪”**：页面卡住时 CDP 常无法作答（渲染主
   线程忙/阻塞），但 HTTP 请求流仍然可见——最后一个成功的请求就是卡点
   的上一个文件。用带时间戳的日志服务器（或 `tyrano/pipeline.py serve`
   的日志）。
2. **用 `--no-diagnostics` 区分“页面卡”与“采集器忙”**：CDP 域的
   `enable` 会在页面忙碌时超时，去掉它再 `--eval` 常能确认页面其实活着。
3. **测 CPU 区分自旋与阻塞**：自旋→CPU 高；阻塞/卡在等待→CPU 空闲。
4. **确认是引擎还是转换数据**：把转换出的 `data/` 套在**干净引擎骨架上
   跑**（见 §2.3），两边对照即可定位责任方。
5. **`[iscript]` 块的语法错误最难发现**（不报错、只是不再前进）：用
   `tools/check_iscript_js.py <scenario_dir>` 一次扫完全部块（内部走
   `node --check`），直接点名文件与 `SyntaxError`。实测：坏构建报
   `anime_init.ks: Unexpected identifier 'setter'`，修好后 84 个块 0 错。
   注意它**只能抓不合法语法**——恰好合法但错误的产物（如前面有逗号时，
   泄漏的 `setter(x){...}` 会被当成 ES6 方法简写，属性访问器静默缺失）
   要在转换器自己的单测里拦（`tests/test_tjs2js.py` 已断言转换后不得
   残留原始 `setter(`）。

## 4. 建议路线（与 `docs/kirikiri-html.md` 一致）

1. **先用路线 A**（JoiPlay 官方 KiriKiri 插件）验证游戏可玩性；
2. **A 档游戏才建转换器**：解包 → 统计标签分布 → 标签映射表 →
   脚本转换 → 素材转换 → `tyrano/pipeline.py` 构建 → serve 试玩 →
   翻译（复用统一 chunk 流程）；
3. 转换器范围**先收窄到首款游戏的标签子集**，逐步通用化。
