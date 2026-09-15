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
- **patch 合并顺序**：多 xp3 必须按引擎优先级解包到同一工作目录，后解出的
  高优先级文件覆盖低优先级文件（原包不动）。不能只解 `scenario/`：补丁档案
  可能把覆盖脚本直接放在档案根目录。转换器会让根目录 `.ks` 覆盖同名
  `scenario/*.ks`，但前提是该补丁档案已经叠加进转换输入。若漏掉这一层，构建
  可以正常启动，却会悄悄退回原语言或旧剧情脚本。
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

## 3. 转换后常见缺口（实测清单）

首款游戏的实际转换暴露的缺口。**注意：下面三行曾被我误报为缺陷，现已推翻** ——
保留在此是为防止后人重走过去那条弯路。

| # | 缺口 | 实测规模 | 状态 |
| --- | --- | --- | --- |
| 1 | **动态引用的素材必须真实存在** | 无扩展名 133 处 + `&` 表达式 2851 处 | **真缺口**。不是语法问题，而是**提取范围**：`&f.t_voice[f.vnum]` 求值出无扩展名 KAG3 名，运行期靠 `__kag3_assets` 映射到实际文件；静态扫描没扒出来的文件就解析不到。→ 全量提取。 |
| 2 | **素材被复制三份** | 每图 3 份 | **真缺口，已修**。见 §3.2。 |
| 3 | **`.wmv`/`.mpg` 浏览器不能播** | 80 个 / 955 MB | **真缺口，已修**。见 §4。 |
| 4 | **点击推进被浮动层截断** | 全游戏每一幕 | **真缺口，已修**。见 §3.1。 |
| 5 | **注释行被拼进标签行 → 注释上屏为台词** | 有害行中 `;` 237 处 | **真缺口，已修**。见 §3.5。 |
| 6 | **`[button graphic=X]` 图片 404** | 70 处引用 / 8 个系统按钮 | **真缺口，已修**。见 §3.5。 |
| 7 | **文本越出消息窗、侵占右下角 UI** | 作者排版预算：每行 ≤28 字 / 3 行 | **真缺口，已修**。见 §3.5。 |
| — | ~~属性 `&表达式` 未展开~~ | 2851 | **不存在**（Tyrano 原生支持，见 §5.1） |
| — | ~~`[wt]` 未映射的未定义标签~~ | 273 | **不存在**（`tyrano.plugin.kag.tag.wt`，原生等 `is_trans`） |
| — | ~~KAG3 保留颜色名~~ | — | **不存在**（都是真实素材，见 §5.1） |

### 3.5 注释上屏 / 按钮图 404 / 文本越窗（试玩反馈第 2 批，已修）

#### 1) 注释被当台词

KAG3 里“整行 `;`”是注释，**Tyrano 解析器也忽略行首 `;`**
（`kag.parser.js`：`first_char === ";"` 直接跳过）。但**未被引号包裹的行中 `;`**
会被当正文。两处转换缺陷把注释行粘进了前一条标签行：

- 注入 `[freeimage layer=N]` 前缀（层替换语义，见 §3.1 相关说明）时用了
  `part.strip()`，**丢掉行尾换行**；
- `@tag` 语法分支用 strip 过的字符串重建，**同样丢行尾**。

两者都让下一行（常见是单独一行的 `;` 注释）被拼接，于是注释文本上屏。修复：

- 两处保留原行尾；
- 新增统一收口 `_finalize_output_lines()`：在**所有改写之后**（含 `[endif]`
  平衡修复重建的行）剥离 KAG3 的 `;` 注释尾巴，并**强制每个条目带回行尾**。

实测：有害“行中 `;`”旧构建 **237 处 → 0**；缺行尾条目 **0**。

**教训（两条）**：

- 用 `str.strip()` 重建“一行”字符串时必须把**行尾还回去**——否则拼出来的是
  把下一行吃掉的一行。
- 统计口径要和机制对应：`[iscript]` 代码块里的 `;` 是 TJS/JS 语句结束符
  （`ZoomRot.ks` 等文件里成片存在），**不是**注释；只统计代码块之外的行。

#### 2) 系统按钮图 404（右下角一排破图占位）

`[button graphic="history_bot"]` 的图实际在 `bgimage/HISTORY_bot.png`
（作者写小写、文件名大写），而 Tyrano 的按钮标签**自己拼 `./data/image/`**，
请求变成 `./data/image/history_bot` → 404 → 浏览器画破图占位符。

**关键结构事实（推翻我之前的说法）**：Tyrano 的顺序执行器
`nextOrder`（`kag.tag.js:462`）**直接调 `master_tag[name].start(pm)`**，
**不经过 `ftag.startTag`**。所以“在调度器上加一个钩子就覆盖所有标签”是**错的**；
可靠的两个层是 **`master_tag[name].start` 包装** 与 **转换期改写**。
（实测调用栈：`b.start ← nextOrder ← f.start ← nextOrder`。）

修复：

- **转换期**：`graphic=` 与 `storage=` 同样走 `_find_asset()`，产出
  `../bgimage/X.png`。Tyrano 的 `$.parseStorage` 会消掉 `..` 段
  （`libs.js` 自带示例：`$.parseStorage("../fgimage/foo.png", "image")` →
  `./data/fgimage/foo.png`），因此哪个标签前缀都落到真实文件；
- **运行期**：按钮包装器里保留一个兜底，但**委托同一个解析函数**
  （只覆盖运行期拼出来的 `graphic="&tf.x"`）。

实测：8 个系统按钮 `naturalWidth` 全部 > 0，**0 破损**。

#### 3) 文本越出消息窗、侵占右下角 UI

作者的排版预算是**每行 ≤28 字、一条 ≤3 行**（33112 显示行实测：中位 19 字、
p90 25、p99 28；≥30 字仅 0.2%）。Tyrano 的默认行框（约 1.6em）比 KAG3 高，
同样的 3 行在 Tyrano 下就会顶出窗口、压到右下角系统按钮上。

两层处理：

- **硬保证**：注入 `.message_inner{overflow:hidden}` —— 文本物理上不可能
  画到窗口外（这是“不侵占 UI”的兜底，不依赖任何尺寸假设）。
- **自动适配** `window.__kag3_fit_message(el)`：
  - **先看清层叠**：引擎把每条消息的 `font-size`/`line-height` 写成
    **`<span>` 的 inline 样式**（`kag.tag.js` 的 `[font]`/消息渲染），因此只改
    `.message_inner` **根本不会生效**。所以另有一条规则
    `.message_inner[data-kag3-fit]>p>span{font-size:inherit !important;…}`，
    **只对已标记的元素**开启继承 —— 未标记的消息保持引擎原样式**完全不变**。
  - 测量前先摘掉自己的标记与 inline 值；基准字号从 **span 的 inline 值**
    反推（并用 `data-kag3-k` 里记录的当前缩放把上一次的影响除掉），因此
    **每条消息自己的字号都被尊重**（大字号不会被上一条的缩放吞掉）。
  - 挤压：先换**单位化行高 `1.25`**（对齐 KAG3，且随字号等比缩放 ⇒ 收敛
    单调），仍超出则按 4% 步长等比缩字号，下限 0.72。
  - 由 **150ms 去抖的 MutationObserver** 触发——打字机每帧重写文本，逐帧测
    布局会强制每帧回流（§3.1 的 TMP 热路径教训同源）。
  - 几何全部读自元素自身的 computed style ⇒ **不硬编码任何游戏的窗口尺寸**。

合成同几何窗口的机制实测（823×99 / 28px 基线）：3 行 ×28 字 143px → **100px
（fits）**，字号 24.6px；超出作者预算的极端文本被 `overflow:hidden` 裁掉、
绝不越界；能装下的消息不动（返回 false）；长消息之后的短消息恢复 28px。

**ASI 事故（留档）**：加这条 CSS 时漏了语句末尾的 `;`，JS 的自动分号插入把
`'…' (document.head…)` 解析成**对字符串的函数调用**，异常被外层
`try{}catch{}` 静默吞掉 ⇒ 整个样式块从未注入（实测 `data-kag3` 缺失、
`overflow` 计算值是 `visible`）。`node --check` **查不出来**（语法合法）。
教训：串接起来的语句必须以 `;` 结尾；这种“静默 catch”必须有一条断言级测试
（`test_injected_style_statement_is_terminated`）。

**实机数据（试玩构建进入剧情后实测 43 条真实消息）**：

- 真实消息窗尺寸（层坐标）：**1014 × 131**。
- **43/43 条消息 `scrollHeight ≤ clientHeight`，零溢出**（作者排版 ≤28 字/3 行，
  实测 30 字也装得下）。
- 因此自适应函数在正常播放中**不触发**（`changed=false`，字号/行高保持引擎
  原值）——正常对白**零视觉改动**。

**推论**：owner 看到的“文字顶出对话框、侵占右下角 UI”**真实成因就是 §3.5-1 的
注释粘连**（注释行比正文长得多，还会把两步内容连成一条）；本节的裁剪 + 自适应
是**不触发的保险丝**。

**测不到真几何的边界（已解决）**：把 `.layer` 强制 `display:block` 只能量到
Tyrano 的**默认**几何（918×598）；游戏自己的 `[position layer=messageN …]` 只在
场景流程里生效。当前做法：按标题菜单的真实动作进入剧情后再量（见 §3.6）。

**教训（层叠）**：第一版只改 `.message_inner`，合成测试没过 span 样式——
引擎内联在 `<span>` 上的字号把整条修复盖掉，**机制可测但真游戏不生效**。
模拟对象必须复现真实层叠（或直接读引擎源码确认样式写在哪里）。

### 3.6 自动化的“进入剧情”路径（验证用，已跑通）

KAG3 构建的自动化验证一直卡在“怎么从标题进剧情”：盲点中心坐标不可靠，而
**跳进场景中段不会恢复消息层可见性**（`[position layer=messageN]` 只在本场景
流程里生效）。跑通的路径：

1. 启动后**点游戏自己的 skip 按钮**（右下角，`[SYSTEM]` 宏生成的 `[button]`）：
   实测 **6 秒**到标题菜单；
2. 标题菜单是 KAG3 可点地图，区域可从运行时的
   `window.__kag3_maps.base.regionCanvas` 读出，再映射回客户端像素；
3. 区域→动作的对应写在标题图的 **`.ma`** 文件里（纯文本，行首 `;` 是注释），
   可离线读出来确认哪个区域是“开始游戏”、哪个是“结束”（后者别点，会退游戏）。

坐标映射要求：用**游戏画布矩形**（`#tyrano_base`）换算，不要用视口比例——
同一构建在 1000×629 窗口下视口是 1000×629，重启后变成 976×490（DPI 缩放），
同一比例会把按钮点偏（实测 x 算成 854，正确约 780）。

### 3.7 静默失效类缺陷：垫片遮蔽 + 运行期 API 面（试玩反馈第 3 批，已修）

这两类缺陷的共同点是**不报错、不崩、就是功能没了**。

#### 1) 空操作标签会静默关闭引擎功能（“引擎优先” pass）

垫片把 KAG3-only 标签注册为空操作，但如果某个名字**引擎也实现**，后注册的
空操作就赢了一一功能静默消失。实测本引擎被遮蔽的 **10 个**：
`bg`、`bgmopt`、`close`、`fadeinbgm`、`fadeoutse`、`ruby`、`style`、`wa`、`wb`、`wq`
（合计 134 处调用，其中 `style` 59 处关系选项排版、`bgmopt`/`fadeinbgm`/
`fadeoutse` 关系音频音量与淡入淡出）。

修法（两道）：

- **编译期**：`engine_tag_names(engine_dir)` 扫描引擎源码，把引擎已注册的名字
  从空操作名单里删掉（实测空操作 89 → 79），扫三种注册写法：
  `tyrano.plugin.kag.tag["x"]`、`tyrano.plugin.kag.tag.x`、`plugin.kag.tag["x"]`；
- **运行期**：注册前先查 `tyrano.plugin.kag.tag[name]`，已存在就跳过并记入
  `window.__kag3_shim_skipped`（新旧引擎都不会退回静默失效）。

**教训**：查“某个名字会不会被遮蔽”时必须把**所有注册写法**都扫到。
第一次只用两种正则，查出来“只有 10 个”；后来补上
`plugin.kag.tag[..]` 这种写法，才把 `playse`/`stopse`/`seopt` 这类音频标签
看全（结果是它们本来就没被遮蔽，但“查不到”与“不存在”必须区分开）。

#### 2) 运行期 API 面：不存在的 `kag.x()` 会让按钮“看着是坏的”

游戏自带 UI 的 `exp=` / iscript 调用了一堆 KAG3 运行期方法；**缺一个就抛错，
按钮就什么都不做**（owner 的原话：“点了没反应”）。系统化的查法：
枚举场景里所有 `kag.<方法>(` 调用点，与垫片对比，缺的打上。实测：

| 方法 | 调用次数 | 作用 |
| --- | --- | --- |
| `getBookMarkPageName` / `getBookMarkDate` | 65 / 60 | 存档界面显示 |
| **`skipToStop`** | **10** | **游戏自带快进按钮** |
| **`showHistoryByKey`** | **10** | **历史/回想按钮** |
| `saveBookMark` / `restoreBookMark` / `storeBookMark` | 8 | 存/读档 |
| `enterAutoMode` / `cancelAutoMode` / `goToStartWithAsk` | 6 | 自动/回标题 |
| `addPlugin` / `close` | 2 | 插件/退出 |

修法：`skipToStop` 真实实现（→ 开 skip）；其余给打印日志的 stub，
保证不抛错（存读档由引擎自己的菜单承担）。

#### 3) `kag.se[]` 必须是真音频通道

游戏的语音/音效系统从 iscript 驱动：`kag.se[0].setOptions(%[gvolume:80])` +
`kag.se[0].play(%[storage:'vo_xxx'])` + 到处判断 `kag.se[0].status == 'play'`。
原先垫片里 `kag.se` 是**空壳**（`play()` 什么都不做、`status` 恒为 `'stop'`）
⇒ **人声完全静音**。

现在每个通道背后是一个真的 `HTMLAudioElement`：storage 经资产映射解析
（实测 `se003` → `./data/sound/se003.wav`）、`gvolume` → volume、
`ended` → `status='stop'`、`loop` → `loop`。实测：
`readyState=4`、`duration=0.41s`、播到 `currentTime=0.405`、结束后 `status` 回 `stop`。

#### 4) 快进还必须跳过硬等待

引擎只在 `skippable === 'true'` 时丢掉等待（`[wait canskip=false]` 与 `[wt]`
都不丢），所以 skip 会在每一个硬等待上停住。现在 skip 开启时
`wait`/`wt`/`waittrig` 直接短路到 `nextOrder()`；正常播放不受影响。

#### 5) 未定义标签会让 Tyrano 弹 alert 阻塞整页（已修）

**症状**：从标题点“开始游戏”后页面再无响应，浏览器弹“网页无响应”，
反复弹窗，**完全没声音、不推进**。

**根因**：Tyrano 对未注册标签会走 `alert()`（阻塞 JS 单线程），所以一个
缺标签就能把整个页面卡死。而本次缺的正是 **[style]（全语料 59 处）**：

- 空操作名单原先是**手写列表**，漏了 `style`；
- 我把“引擎优先”改成“扫引擎源码差集”后，扫描匹配到了
  `kag.tag.js` 里**被注释掉的**定义：
  ```js
  //スタイル変更は未サポート
  /*
  tyrano.plugin.kag.tag["style"] = { ... };
  */
  ```
  → 误判为“引擎已实现” → 删掉空操作 → 运行时没人提供 `[style]` → 阻塞弹窗。

**修法（两道）**：

1. 扫描引擎标签前**先剥除 JS 注释**（含字符串/正则保护的小状态机），
   注释里的注册不算数；
2. **以语料为准兼容**：`collect_scene_tags()` 扫出场景里实际用到的标签，
   凡“既不是引擎实现、也不是游戏宏”的一律补上安全空操作 ->
   这类“缺标签 → 阻塞弹窗”**不可能再发生**（实测空操作 90 个）。

**实测**：修前“标题 → 剧情”4/4 阻塞；修后 **3/3 正常，0 个 alert**，
BGM 正常播放（`bgm005.ogg`，`AudioContext=running`）。

**教训**：

- 扫源码找“某功能是否存在”时，**注释里的代码是最阴的假阳性源**；
- 任何“未定义 X 就 alert”的框架里，缺项 = 页面全卡，因此“手写白名单”
  这种脆弱做法要换成“从语料反推 + 全面兼容”；
- Tyrano 自己的错误面板/`alert` 是**阻塞式**的，遇到“页面无响应 + 没声音”
  要优先怀疑“某个标签报了错”而不是音频。

#### 6) 引擎根本没有的标签：空操作会静默吞掉整个子系统（已修）

**症状**（试玩反馈）：人物被挤到画面外；场景卸下的人物不隐藏（残留）。

**根因**：Tyrano **完全没有 `[layopt]`**（`kag.*.js` 里没有该注册），而我把它
当“KAG3 专有标签”注册成了空操作。于是全语料的：

- `visible`（**2053 处**）不生效 -> 角色卸载、图层隐藏全部失效（人物残留）；
- `left`/`top`（**112 处**）不生效 -> 立绘层永远停在原点。游戏用
  `[layopt layer=lay_ch_left left=&f.left_x top=&f.left_y]`（{-200, 0, +200}）
  做三人站位，丢掉后左右两人直接被挤出画面。

**修法**：把 `layopt` 实现成**真实标签**（`visible`/`opacity`/`left`/`top`/
`index`，通过 `kag.layer.getLayer(layer, page)` 取到层元素），并保留
“引擎优先”守卫：若引擎自己实现了 layopt 则绝不覆盖。

**实测**（真实构建）：`layopt(-200,12)` -> `style.left=-200px; top=12px`；
`visible=false` -> `display:none`；截图里两侧人物完整入镜。

**普遍教训（写工具时反复出现）**：

- “KAG3 专有标签”必须是“**引擎确实没有**”的**实测结论**，不能靠印象；一个空操作
  就能静默吞掉整套图层/可见性语义，而它不会报错（比报错更难发现）。
- 判断一个标签是否存在，要扫**三种注册写法**并**先剥注释**（见 §5 第 5 条）。
- 反过来：能被“没实现就报错”暴露的标签反而是幸运的。

#### 7) 文字区要自己留出引擎控件的安全区（已修）

KAG3 用消息框的 `marginl/marginr/margint/marginb`
（`[position layer=message1 frame=name01_ti_N ...]`）保留右下角空间，
**Tyrano 不认这些参数**，于是长行一直排到右边缘、压在控件下面。

修法两道：

1. 游戏自带的那排 `[button]`（`name.ks`/`define2.ks`，70 处，无 `[endbutton]`）
   按默认**丢弃**（`--keep-game-buttons` 可保留）—— 它们正是压在文字上的那列，
   且它们的 `exp` 调的 `kag.*` 方法 Tyrano 没有（点了没反应），owner 也判定不必要；
2. 给消息文本加右下**安全区内边距**（`box-sizing:border-box` +
   `padding-right:190px` / `padding-bottom:44px`），让开 Tyrano 自己的控制条。

实测：40 字消息文本右边缘 **875** vs 控件起点 **942**（不再重叠），
`scrollHeight == clientHeight`（无溢出裁切）。

#### 8) 图层排序要靠层号（z-index），不能靠 DOM 顺序（已修）

**症状**（试玩）：立绘盖在文字上，把对话挡掉了。

**根因**：KAG3 的层叠由**层号**决定，Tyrano 由 **DOM 顺序**决定。精灵层因为原
层号带着 z-index **3000/4000/5000**，而文字所在的 `message0_back` 是 `auto` ✗
—— 于是立绘永远在文字之上。实测链条：
`.message_inner` -> `.message0_back` -> `root_layer_game`。

**修法**：所有消息页统一提到精灵层之上（同时作用于 `_fore` 与 `_back`，因为文字
实际在 `_back`）：

```css
#tyrano_base div[class*="message"][class*="_fore"],
#tyrano_base div[class*="message"][class*="_back"] { z-index: 8000 !important }
```

**实测**：自动化门禁（`tools/check_tyrano_build.py`）从 5/16 失败 -> **0/30 失败**。

#### 9) 不要靠“缩字号”把文字塞进窗口（已按 owner 要求改掉）

**症状**（试玩）：同一段话里字号忽大忽小，很难看。

**根因**：Tyrano 的消息正文默认字号比原作大（原作用 KAG3 `Config.tjs` 的
`defaultFontSize=22` / `defaultLineSpacing=6`，Tyrano 默认 ~28px/行高更大）——
每行装的字更少、行数更多，于是我之前写了个“超出就缩字号”的补丁，
补丁本身才是丑的根源。

**修法**（owner 的方案：固定宽度换行、不缩字号）：

- 消息正文统一用**原作的 KAG3 度量** `font-size:22px; line-height:28px`，
  换行点自然落到与原文一致的位置 —— 不需要任何缩放；
- “超框检测”（`__kag3_fit_message`）降级为**只报不调**（保留 `overflow:hidden`
  作为最后一道硬保险）；同一消息不得出现多种字号（已进自动化门禁）。

#### 10) 不要加多余的底衬（已按 owner 要求删掉）

游戏自己的消息框（`name01_ti_*` 帧图）现在能正常显示了，之前加的
半透明黑底衬是多余的，且会把游戏自带的底衬再压暗一层：

```css
.message_outer,.message_inner{background-color:transparent !important}
```

#### 11) 消息层排版：[position]/[locate]/[style] 家族与三个坑（已修）

这三类标签原先都是空操作，直接造成 owner 反馈的排版问题（名字位置不对、
选项不换行/文字消失、底衬重复）。实现要点与**坑**：

1. **绝不能移动消息层**。KAG3 的 `[position layer=message1 frame=... top=599]`
   是**名字框自身帧图的原点**，Tyrano 已经自己摆好了消息窗。把 left/top 套上去
   会把整层推出画面（实测窗口跑到视口 y=1087，而页面只有 800px 高），
   `overflow:hidden` 再把里面的东西全部剪掉 —— 这就是“**选项文字消失**”的真正原因。
   本实现只取 `frame`（帧图）、`color/opacity`（底衬色）、`margin*`（文字内缩）。
2. **`[ch]` 组合出来的消息不能被硬裁剪**。消息窗高仅 113px，而选项行距约 80px
   （★ 光标另占行），后面的选项全被 `overflow:hidden` 剪掉。修法：`[ch]` 写入的
   窗口加 `kag3ch-msg` 类，只对这类窗口 `overflow:visible`；普通对白仍保留硬裁剪。
3. **`[r]` 必须让 `[ch]` 追加的文字换行**。引擎的 `[r]` 只作用于它自己的文本模型，
   所以提示语和第一个选项本来挤在同一行。修法：包一层 `[r]` 置 `__kag3_break`
   标记，`[ch]` 遇标记新起段落（owner：“第一个选项不要和描述放在同一行”）。
   另外：**空 run 不得新建段落**（否则每项多占一行，行距翻倍）。
4. **不要自己加底衬**。`frameColor/frameOpacity` 现在能正常渲染，
   再加一层 `rgba(0,0,0,.5)` 就是两层底衬（owner：“双层底衬”）。
   反面也一样：不能顺手写 `background-color:transparent !important` ——
   那会把游戏自带的底衬一并覆盖（owner：“删除多了，两层底衬都没了”）。

**实测**（真实构建，选项场景 `*s08a_0016`）：提示语与三个选项各自成行、
全部在窗口内可见、底衬只有游戏自带那一层（`rgb(38,85,121)`）；
对白窗口位置正常（`message0` 回到视口内）+ 名字框在其上方。

#### 12) `[position]` 定义的是「消息窗」，不是「图层」（已修）

KAG3 里这三行是一个整体含义：
```
[position layer=message1 frame="name01_ti_N" left=0 top=599 marginl=-4 marginr=0]
```
= “在这里画这个窗口，用这张帧图，文字按这些内缩”。

**坑（两个试玩事故同源）**：我第一版把底衬色刷在了**图层**上，而 Tyrano 的消息层
是全屏（1024×768）的 div，于是：

- 整个场景背景被盖住（owner：“背景全没了”）；
- 名字没有自己的框，`[style align=center]` 就在 790px 宽的整层里居中
  （owner：“人名还是居中的状态”）。

**修法**：帧图与底衬色只作用于层内的**消息窗元素**（`.message_outer`），
按帧图自然尺寸定大小、按 `left/top` 定位；**绝不给图层刷底色**。

**同时修掉一个隐形 bug**：`__kag3_asset_path` 只存在于 runtime shim 的闭包里，
而自动生成的标签垫片是**另一个脚本**，看不到它 —— 所以 `[position frame=]`
一直解析失败、帧图从未绘制过。现已 `window.__kag3_asset_path = ...` 暴露出去，
`[position]` 与 `[button]` 共用同一个解析器（实测：`name01_ti_0` ->
`../bgimage/name01_ti_0.png`）。

#### 13) 转换必须保留「意图」（owner 指令，2026-09）

> “你要在转换的时候，将所有意图都保留下来，即便是空函数，也需要标注意图，
> 方便后续撕写一样的逻辑。”

第一阶段转换必然会把很多 KAG3 构图留成空操作（或者直接丢弃）。**但“留下
空操作”不等于“留下信息”** —— 没注释的空操作会让后续手写变成猜谜。

现在每处未实现都带四件东西：

| 字段 | 含义 |
|---|---|
| `calls` | 全语料调用次数（0 表示本作未用到） |
| `arguments` | 实际传过的参数名（按出现次数） |
| `examples` | 1-3 条**逐字**调用点（`文件:行`） |
| `intent` | 这个标签应该做什么（人工策展表，未收录的则根据调用点生成） |

产物分两份：

1. **生成的垫片脚本里**逐条注释（空操作定义正上方）—— 读 JS 就能看到意图；
2. **输出根目录 `_kag3_intents.json`** —— 机器可读清单，包含全部 stub、
   被丢弃的标签（如 `button`）、被降级（iscript 注释掉）的 25 个文件。

实测本作：**90 个 stub 全部带意图文案**（33 个有真实调用点，57 个本作未用到）；
例如：

```
// [t_bmp] -- KAG3 tag, NOT implemented by TyranoScript: 748 call site(s).
//   arguments seen: bmp_c, bmp_l, bmp_r, place
//   example: scenario/newgame.ks:193: [T_BMP bmp_l="a_t003d" place=0]
//   INTENT: display a character sprite: choose the left/centre/right layer
//           from place= and draw bmp_l/bmp_c/bmp_r on it
```

**这条规则适用于后续所有新增/修改**：任何“暂时不实现”只能以带 `intent` 的
形式存在；没有意图文案的空函数/空标签视为缺陷。

### 3.4 可读性与快进（试玩反馈，已修）

1. **消息窗底衬**：KAG3 游戏普遍把消息窗做成**透明美术**直接压在 CG 上，
   台词直接落在画面上，可读性差。`RUNTIME_SHIM_IIFE` 注入一条 CSS：
   ```css
   .message_outer{background-color:rgba(0,0,0,.5) !important}
   ```
   `.message_outer` 是**兄弟节点**（不是 `.message_inner` 的父节点，实测
   `children()` 为空），台词窗口与名字板各是一个 message 层，所以一条规则
   同时覆盖两者；实测不透明度与范围都正好（名字层报出的 box 是 760x498，
   但实际只画出一条窄带，不会糊掉半屏）。

2. **字体统一**：`--font <otf>` 把字体拷进 `tyrano/fonts/`、追加
   `@font-face` 到 `tyrano/css/font.css`、并把字体族**前置**到
   `data/system/Config.tjs` 的 `;userFace=`。
   实测：本项目 105324 行场景里 **`face=` 属性 0 处**，所以 `userFace`
   就是唯一入口；而模板首位是 `Quicksand`（纯拉丁字体），汉字/假名逐字
   回退到系统字体 —— 这正是「字体不统一」的机制。前置后实测
   `getComputedStyle` 为 `"Glow Sans SC", Quicksand, ...` 且
   `document.fonts.check(...)` 为 **true**（已加载）。

3. **快进（skip）**：
   - 引擎语义：`config.skipSpeed` 是**每行一次**的超时（`kag.tag.js`：显示
     全部字符后 `setTimeout(nextOrder, skipSpeed)`），不是每字符；模板值 30ms
     把快进上限压在 ~33 行/秒。转换器改写为 `;skipSpeed = 10;`。
   - **shim 自己的等待也必须认 skip**：Tyrano 在 skip 下直接丢弃可跳过的
     等待（`kag.tag.js`：`if (is_skip && pm.skippable === "true") nextOrder()`），
     而本仓库的 `[kagwaitskip]` 原先**不看 `is_skip`**，于是快进时每个
     `[wait]/[wm]/[wt]` 都走满时长 —— 这是「快进很慢」的主因，已补同样的
     早退。
   - **已装备的点击等待不会再检查 `is_skip`**：`[l]`/`[p]` 只在**标签启动时**
     判断一次，所以停在点击等待时按 skip 看起来毫无反应，必须再点一下
     （实测：开 skip 后 6 秒推进 0 个标签）。`--fast-skip` 装一个 30ms 的
     驱动器补上这一段：仅在「画面中心点一下本来就能推进」（顶层元素是
     `layer_event_click`）时才推进，因此**选择肢/菜单不会被跳过**。
     实测同一场景：0 → **6 秒推进 100 个标签**。
   - 注意 **skip 模式下点击 = 停止快进**（`kag.key_mouse.js`：`if (is_skip)
     setSkip(false); return true;`），不是推进 —— 与驱动器互补，不是 bug。

### 3.3 被推翻：`[p]`/`[er]` 曾被当成空操作（勿重走）

**下面的推断是错的，保留以免后人重走。** `[p]`（改页点击等待）与
`[er]`（擦除消息层文字）**都是 Tyrano 原生标签**（`tyrano/plugins/kag/`
`kag.tag.js`）；本仓库的 no-op shim **也没有**注册它们。两个方向都实测过：
探测到 `p:tag` / `er:tag` 来自**引擎自身**；按「shim 名单 ∩ 引擎实际注册
标签」扫出的真遮蔽集合只有 `bg / bgmopt / close / fadeinbgm / fadeoutse /
ruby / style / wa / wb / wq` 十个，`p` 与 `er` 都不在里面。

所以「推进线程没实现」这条不成立 —— 真实原因是 §3.1 的浮动层截断。

教训：`SHIM_TAG_NAMES` 上方那句注释
（"KAG3-only tags that Tyrano does not implement"）是**断言而非事实**。
判断某个 shim 是否遮蔽了引擎实现，必须拿**引擎实际注册的标签集合**去求
交集，不能读注释、也不能只看单次探测结果。

_以下为当时（错误）的记录：_

已实测的事实（都是可复现的观测，不是推测）：

- 本作的推进宏是 `[macro name=T_NEXT]`，宏体为
  `[eval AutoModeCheck()] [if…] [VO_S] [p] [RVO_S] [er] [eval …]`；
  **`[p]`/`[er]` 才是 KAG3 的“点击等待”**，`[s]` 并不参与。
- 转换树里 `[T_NEXT]` 仍为**字面 12053 处**（不展开宏），而 `[p]` /
  `[er]` 只剩宏定义里的 8 / 90 处（Tyrano 不执行 `[macro]` 块，不会到达）。
- 生成的 shim 把 `[p]`/`[er]` 注册成了**空操作**（探测：`p:tag`、`er:tag`，
  即 `master_tag` 里有，行为是 `nextOrder()`）。→ **全游戏没有任何点击等待**。
- 反向事实（以免误判）：**Tyrano 原生支持宏** ——`stat.map_macro` 实测
  230 项且含 `T_NEXT`；分派顺序是先 `master_tag` 再 `map_macro`；
  **未定义标签不会停流程**（`kag.error("undefined_tag")` 后仍
  `nextOrder()`）。因此“`[T_NEXT]` 未注册为空操作”本身不是卡死原因。
- 实测卡点：正常进入剧情后，钩住 `kag.ftag.startTag` 记录的标签轨迹
  终止于 **某个宏文件里的一个 `text` 标签**，之后再无任何标签，且
  `is_wait=false`、`nextOrder()` 手调不动 —— 形态像异常从 `startTag`
  冒出（此版本 Tyrano 自带的 try/catch 被注释掉了）。**异常本身尚未抓到，
  此项未完成**；排查脚本在 `.tmp/archive/scripts/diag/trail_story.py`、
`.tmp/archive/scripts/diag/catch_tag_error.py`。

### 3.1 点击推进被浮动层截断（已修）

**症状**：剧情能显示第一行，之后**怎么点都不走**——无标签执行、无报错、
`nextOrder()` 手调也不动、`is_wait=false`。owner 手动试玩报的就是这个。

**根因（引擎结构 + 实测 DOM）**：Tyrano 的 `[button]` 把按钮放进**浮动层**
`.layer_free`，该层 `z-index:999999`、覆盖整个 canvas，高出点击事件层
`.layer_event_click`（`z-index:9999`）；而 Tyrano 的“点击推进”恰好**绑在
`.layer_event_click` 上**（`kag.key_mouse.js`）。两层是**兄弟**，事件不会横向
传递，所以：**任何点击的目标都是浮动层 → 推进监听器永远收不到**。
KAG3 游戏的 UI（系统菜单/存读档/回想...）几乎全是 `[button]`，所以这
affect 每一幕，不只是菜单。

实测 DOM 证据（停顿当时）：
```
.layer_event_click  z-index 9999    kids=0  html=""
.layer_free         z-index 999999  kids=8  HISTORY_bot.png 等按钮
点击点自下而上: layer_free → layer_event_click → message_inner ...
```

**修法**（`RUNTIME_SHIM_IIFE` 注入一条 CSS，避开初始化时序竞争）：
```css
.layer_free    { pointer-events: none !important }   /* 层本身不拦截 */
.layer_free > *{ pointer-events: auto !important }   /* 里面的按钮仍然可点 */
```
修后点击目标变为 `.layer_event_click`，实测 **26/26 次点击各推进一行**。

**排查教训（重要）**：**不能用 `current_order_index` 判断“有没有推进”**。
本作的推进宏 `[T_NEXT]` 定义在 `define.ks`，每执行一行台词都会重新进入
同一个宏体，于是 index 每次都回到**同一个值**（2655）——据此会误判成
“完全卡死”。可靠观测量是：**执行过的标签计数**、**对话框实际文字**、
**点击目标元素**。同一次排查中还有两个**无效判据**要记住：`is_wait`
（`waitClick()` 根本不设它）与 `stat.stack`（宏栈是命名栈，用
`getStack("macro")`）。

### 3.2 素材冗余（已修）

同一个文件被写入 `bgimage/`+`fgimage/`+`image/` 三份，因为不同标签去不同
目录（`[image]` 等同背景图取 `bgimage/`，`[chara_*]` 取 `fgimage/`）。

**先度量再动手**：把三份与一份分别打成 7z 对比（zstd 并**不会**自动去重）：

| 树 | 原始 | 7z 成品 |
| --- | --- | --- |
| 1 份 | 5.89 MB | **4.57 MB** |
| 3 份 | 17.68 MB | **13.45 MB** |

→ **75% 的重复字节能活过压缩**，冗余是真交付体积。（本构建实测：
663.5 MB → 606.1 MB，重复组 222 → 22。）

修法：每份素材只写一次（规范目录），运行期把 storage 解析成
**`../<规范目录>/<文件>`**。这套能通用的**根据是一个实测结论**：
**浏览器会规范化 URL 里的点段**：

```
请求 ./data/fgimage/../bgimage/telop1.png
服务端实际收到 /data/bgimage/telop1.png   ← 已实测
```

所以无论标签往前面拼哪个 `data/<folder>/`（包括像 `[image]` 那样手工
拼接字符串、不走 `parseStorage` 的代码）都能落到唯一那份。覆盖面上再加一道：
在 `kag.ftag.startTag` 上挂**一个中央钩子**解析 `storage`/`graphic`，
避免“逐标签列表漏掉下一个带 storage 的标签”。

验证方式是看**服务端请求日志的 404**（客观判据，比肉眼看图可靠）。

## 4. 影片：转码 + KAG3 视频标签映射（已跑通）

### 4.1 为什么必须重编码

游戏影片是 **wmv3（WMV9）**，浏览器不能解。实测：1024×768、yuv420p
（无 alpha）、29.97fps、~7.5 Mbps。

### 4.2 选 VP9 而不是 AV1

目标是要在 Android 的 WebView / JoiPlay 里放，**VP9 解码在 Android 上远
比 AV1 普及**。本机实测（crf 32、cpu-used 4、row-mt）：

| 编码器 | 体积 | 速度 |
| --- | --- | --- |
| **libvpx-vp9** | 2.58 → **0.59 MB（22.9%）** | 3.6x 实时 |
| av1_nvenc（GPU） | 0.55 MB | 7.5x 实时 |

全量 80 个文件（约 18 分钟视频）：**955 MB → 198 MB（20.8%）、156 秒**。
所以选 VP9 代价很小。

```bash
# 1) 转码（可重跑：已存在的输出跳过；每个输出都用 ffprobe 自检）
python3 tools/transcode_video.py <game>.xp3 <cache_dir>
# 2) 构建时指定缓存目录
python3 kirikiri/convert_kag.py <unpacked> <engine> <out> --video-dir <cache_dir>
```

### 4.3 两个必须知道的坑

1. **游戏影片不在图片目录里**：KAG3 把 `.wmv` 放在 `others/`，而素材复制
   是按目录映射的 → **影片根本不会被装进构建**。`_convert_videos()`
   改成按扩展名全树扫描。
2. **没有 WebM 对应物时不能默默丢弃**：应原样拷贝并 WARN（宁可交一个
   浏览器放不了的文件，也不要静默丢掉一个场景的演出）。

### 4.4 KAG3 视频标签 → Tyrano `[layermode_movie]`

KAG3 把播放拆成一串共享状态的标签；Tyrano 没有等价序列，但
**`[layermode_movie]` 正好做了最难的部分**（把 `<video>` 以混合模式合成进
图层栈）。所以 shim 里做了个状态机：

```
[video top/left/width/height/loop/mode]   记录几何与循环
[videolayer channel/page/layer]           记录目标图层
[preparevideo]                            空操作
[openvideo storage=X]                     记文件（经 __kag3_videos 映射到 .webm）
[wv]                                      播放前=等就绪；播放后=等结束
[playvideo]                               发出一次 layermode_movie（不等）+ 修几何
[stopvideo] / [clearvideolayer]           停并移除元素
```

要点：

- `layermode_movie` **自己**会在 URL 前拼 `./data/video/`，所以传**裸文件名**。
- `[playvideo]` 不等待（KAG3 语义如此），要等用 `[wv]`。
- **`[wv]` 绝不能永久阻塞**：没有影片、已结束、或循环影片时必须能前进；
  循环影片额外允许点击跳过。一个永不完成的等待看起来与构建损坏一模一样。
- 这些标签**不能再注册成 no-op**：后来的注册会盖掉真实实现，功能静默失效。
  `_shim_js()` 会把 `VIDEO_TAGS` 从 no-op 列表里排除。

### 4.5 用外部状态覆盖打开 Gallery

部分 KAG3 游戏用系统变量控制 CG、动画和场景回放是否出现。转换器不应写死
某款游戏的变量名；把需要固定的默认值写进本地 JSON，再通过
`--state-overrides` 注入：

```json
{
  "sf": {
    "gallery_open": 1,
    "animation_open": 1
  }
}
```

```bash
python3 kirikiri/convert_kag.py <unpacked> <engine> <out> \
  --state-overrides <local-state.json>
```

JSON 根对象只接受 `f`、`sf`、`tf` 三个命名空间，每个命名空间的内容必须是
对象。运行时会周期性重放这些值，因此它适合“始终开放”之类的固定策略；
不要把页码、临时选择或播放位置放进去。游戏专属变量表保存在本地工作目录或
`docs/table/`，不提交到公开仓库。

### 4.6 已验证

驱动 `[video]→[videolayer]→[openvideo]→[playvideo]` 后：

```
GET /data/video/a_ev001a.webm  ->  200
video: readyState=4, paused=false, 1024x768, currentTime 5.89 -> 10.03
```

即真正取到、解码成功、实时播放。

### 4.6 几何保真（已修）

KAG3 的 `[video width=800 height=600]` 是把影片放进一个 800×600 的框，
1024×768 的片子按比例缩放进去。但 Tyrano 的 `[layermode_movie]` 在应用
`width`/`height` **之后**又强制 `min-width/min-height: 100%` —— 显式尺寸
被静默盖掉，影片占满整个画布。**实测**（在页面里量元素）：

| | 元素尺寸 | `min-width/height` |
| --- | --- | --- |
| 修正前 | **1024×768**（= 画布） | `100%` |
| 修正后 | **800×600**（= KAG3 的框） | `0px` |

修法：`playvideo` 发出 `layermode_movie` 后立即将其元素的
`min-width/min-height` 置 0，并设 `object-fit: contain`（按比例适配，
而不是拉伸）—— 与 KAG3 把画格缩放进框的行为一致。

**已验证**：重建后量到元素直接就是 800×600（先前的“手动修正”已成空操作）。
但**精确的画面合成仍取决于真实场景的图层/混合状态**，单独驱动标签无法
复现 —— 这一条需真实场景端到端才能定论。

### 4.7 影片音量与铺满（试玩反馈第 4 批，已修）

两个独立缺陷，都会让“动画鉴赏”看起来像坏了：

**（1）Tyrano 的影片层默认静音。** 引擎 `kag.tag.js` 里：

```js
if (pm.volume != "") { video.volume = parseFloat(parseInt(pm.volume) / 100); }
else { video.volume = 0; }            // ← 不传 volume = 静音
```

KAG3 的 `[playvideo]` 没有 volume 参数（本作的 `[video]` 标签也不带），
shim 因此从不传 volume —— 影片**一直静音播放**，玩家只听到还在放的 BGM，
很自然会得出“背景音没卸载”的结论。修法：shim 的 `[video]` 记录可选
`volume`，`[playvideo]` 默认补 `volume='100'`（游戏显式指定则透传）。

**实测（页面上量元素）**：修正前 `video.volume = 0`；修正后 `= 1`、
`muted=false`、`paused=false`。

**（2）影片框只占画布一部分。** §4.6 的默认（`box`）忠实还原 KAG3 的
`[video width=800 height=600]` 盒子；但本作的画布是 1024×768，于是影片
只占 78% 宽高，右/下露出黑底。试玩反馈明确要求铺满，所以加了构建开关：

```bash
--video-fit fill     # 影片缩放到整个游戏画布，object-fit 保持画面比例
```

4:3 的片子配 4:3 画布时 `contain` **不产生黑边**（等比放大到满幅）。
默认仍是 `box`（KAG3 语义），按游戏偏好选择。

**实测**：`fill` 下 `<video>` 元素尺寸 = 画布尺寸（833×625 的 CSS 像素，
即 1024×768 缩放后），`style.objectFit=contain`、`left/top=0`。

### 4.8 鉴赏回放：BGM 语义与退出按钮（试玩反馈第 4 批，已修）

**BGM“不换”的真相（先别急着改引擎）**：本作 11 个场景回放里有 6 个
**开场曲就是图库/菜单用的那首**（脚本里写死 `[BGM bgm="bgm010"]`），
动画幻灯片脚本（`112.ks`）同理 —— 原作也是“同一首继续”。真正能改进的
只有一点：Tyrano 对**同一 storage** 的 `[playbgm]` 走跳过路径，于是回放
开场曲**无缝接着放**，玩家完全听不出“回放开始了”。修法：垫片在
**回放模式**（`tf.now_pv == 1`）下若 storage 与当前曲目同名（按 stem
比较，因为两侧分别是裸名与 `../bgm/x.ogg`），先清掉 `stat.current_bgm`
让引擎走完整播放路径 —— 音乐先停再从 0:00 起，与原作听感一致。
`target=se`（`[playse]` 内部就是调 `[playbgm]`）必须排除。

**实测**：pv 模式下重放同一曲目 → Howler 实例数 1→2（走了完整播放
路径）；pv=0 对照组不新增实例。

**退出按钮（做在手机控制面板里）**：游戏在回放开始时用 `[rclick call=false
jump=false enabled=true]` **主动解除**右键返回，手机端又没有右键 —— 回放中途
无路可退。实现方式：在垫片自己的紧凑控制面板（`#kag3-mobile-panel`：☰ +
SAVE/LOAD/LOG/AUTO/SKIP/HIDE）里加一个 **`GALLERY`** 条目：

- 只在高 `tf.now_pv == 1` **且**游戏注册过 `*return*` 类返回标签时出现
  （`[rclick jump=true target="*return_seen"]` 是游戏的“回图库”处理器）；
- **不能做成独立浮动按钮**：它会在右上角与菜单键（☰）重叠（owner 看图
  发现）—— 放进同一行由 flex 排版，天然不重叠，也符合“进菜单里用”的要求；
  面板每 500ms 同步一次可见性（回放可能不是由面板操作启动的）；
- 点击时**先清空 `stat.stack` 的 call/macro/if 帧再跳转** —— KAG3 的
  右键跳转等于 `process()`（整场景切换），不是嵌套 `[call]`；不清帧会
  在栈底留下回放的悬挂帧；
- 跳转后手动复位 `tf.now_pv=0` / `sf.seenflg=0`：正常路径里这两个值由
  我们跳过的清理代码复位（PV_START 尾巴与 `seen_set.ks` 的
  `sf.seenflg=0`），不复位会让按钮一直显示、并让图库的存读档按钮消失
  （`SYSMENU` 分支看 `seenflg`）。

**实测**：回放中展开面板后 `GALLERY` 位于 [1167,66]（☰ 在 [1208,10]，
不重叠）；点击后 `sc=seen.ks`、`pv=0`、`seenflg=0`、call/macro 栈均为 0、
条目自动隐下去（`display:none`）。

**回放 BGM 的淡出重叠（owner 反馈「有点迷惑」，已修）**：Tyrano 的
`stopbgm` 走淡出分支时**先把对象从 `kag.tmp.map_bgm[buf]` 删掉**
（`kag.tag_audio.js` `delete target_map[key]`）再 `fade()`；下一个
`[playbgm]` 的 `case "bgm"` 因此找不到旧对象可停 → 旧曲继续淡出整个
`time`（游戏是 3 s）与新曲**叠加**。KAG3 只有一个 BGM 槽，新 `[playbgm]`
会把淡出中的旧曲直接掐掉。垫片补救：包 `master_tag['stopbgm'].start`
**在引擎删引用之前**把即将被淡出的 Howl 对象记下来（只记
`target=bgm`，`[stopse]` 一律不记；`buf_all` 时记整张表），再在
`master_tag['playbgm'].start` 里（非 `se`）`stop()+unload()` 掉这些遗留
对象 —— 记的是**对象**而非名字，所以绝不会误杀 SE/语音；没有后续
`[playbgm]` 时淡出照常走完（游戏自己的时序不变）。**实测（合成复现
`[playbgm]→[fadeoutbgm 3000]→[playbgm 新曲]`）**：修复前 `t+500ms` 起
2 个 howl 同时在播（旧曲 v0.70→0.47 递减 + 新曲 v1）；修复后全程 ≤1，
调用栈显示 `stop bgm001 @ _pb.start` 发生在下一首开播之前。

**实验文字样式**（试玩反馈，开关式）：`--msg-style bare` 去掉**两层**消息
底衬——主对白窗（`message0`）与名字框（`message1`）——改给文字加描边 +
阴影；对白文字额外 0.8 不透明度（名字短且承载说话人，不改）。默认仍是
`plate`。**注意：只压游戏底衬不足以“看不出底衬”**——垫片自己还给消息框加了
一层半透明底板 + 大范围投影（`.message_outer.kag3-dialog-frame` 的
`background:rgba(5,8,14,.78)` 与 `box-shadow:0 -14px 34px`），`bare` 必须把这
两项一起清掉（用 `#tyrano_base` 提优先级），否则 owner 仍会看到“阴影”
（实测：只压 background 时 `box-shadow` 仍是 `rgba(0,0,0,.48) 0 -14px 34px`）。
**关键**：底衬**不是层 div 的样式**，`[position frame=...]` 贴在
消息层**内层 `.message_outer`** 上（`kag.tag.js:3208`
`j_message_outer.css("background-image", ...)`，frame 颜色同处），所以规则
必须同时覆盖 `.message_outer`（层 div 那条留着做兜底）。**绝不要用
`img{display:none}` 去底衬**：消息层里还住着引擎的「点击继续」箭头
（`system/nextpage.gif`，`.img_next`），会一起被隐藏。实测：`.message_outer`
的底衬背景与投影均被清空，`__dev.msg()` 在候选框内不再返回任何绘制元素。

**消息层对齐的作用域（试玩反馈，已修）**：KAG3 的 `[style align=..]` 是按
`[current]` 指定的消息层作用域生效的。本作 `SELECT_CLEAR` 宏会在
`[cm][MES_SIZE]` 之后发一条 `[style align=center]`，此时 `current` 仍是
`message0`（对白层）**且该层没有文本**——这条对齐实际是给紧随其后写出的
**说话人名字**用的。垫片原先直接写 `getMessageInnerLayer()`，把 `center`
写进了对白层内层，于是**选项之后每一句对白都继承居中**（jQuery `.css` 调用
栈定位到 `kag.tag_kag3shim.js` 的 `[style]` 包装）。修法：对齐请求落在
「当前为空的 `message0`」时先挂起（`__kag3_pending_align`），由紧随其后的
`[ch]` 应用到真正写入的那一层——对白保持左对齐、名字仍居中。实测：选完
选项 `message0 = left`、`message1` 内联 `center`，再推进两句仍 `left`。
选项提示行也改为左对齐（源码宏本身是
`[position ...][style align=left][locate x=-30 y=5][ch]`，与其选项行一致）。

### 4.9 跨场景点击泄漏（试玩反馈：进画廊自动进第一个 CG / 进回放第一句被跳过）

**症状**：从菜单进鉴赏后自动进入第一个 CG；进回想后第一句对白被自动跳过。

**根因**：KAG3 的 `[jump]` 是 `process()`，**同步**执行；触发跳转的那一次点击事件
这时还没走完它的传播路径，新场景已经把点击层 / `[p]`/`[s]` 配好了 —— 同一个
点击被新画面又消费了一遍（“自动点了一下”）。**A/B 实测（跳转与点击同一个 tick）**：

| 情形 | 结果 |
|---|---|
| 关掉冷却（= 修复前） | 第一句被跳过，流程还多走了两步（停在 `name.ks:827`） |
| 冷却生效（修复后） | 停在第一句（`define.ks:3392`，首句仍在） |
| 冷却窗口之后的正常点击 | 正常推进到下一句 |

**修法**：垫片在 `[jump]`/`[call]` 开始时给一个 **300 ms 点击冷却**
（`window.__kag3_click_lock_until`），冷却期内 `document` 的**捕获 + 冒泡**
双击监听器都 `stopImmediatePropagation()`（捕获那个先于地图引擎\*的惰性钩子注册，
所以地图点击的那一次也归它管）；同时在新场景开头清掉继承来的“点击已发生”
状态（`cancelWeakStop()` / `is_click_text`），以免新画面的第一个 `[p]`/`[s]`
被半个点击直接满足。代价：切场景后 300 ms 内的点击被丢弃——这是可接受的，
也是让“进图库就是进图库”成立的必要代价。

\* 地图引擎的点击钩子是在第一次 `[mapaction]` 时才装的，所以要保证本冷却的捕获
监听器**先**注册（放在 `runtime_shim.js` 顶部）。

## 5. 经验：已推翻的判断 / 测试陷阱 / 排障

### 5.1 已在实测中被推翻的**四个**初始判断（勿重蹈）

**共同病根**：这四个都是**从“我的探测没覆盖到”推出“引擎缺失”**，而不是
从运行时行为得出结论。下面每一条都附上了正确的判定方法。

0. **“KAG3 保留颜色名会 404”—— 错。** `clear`/`wh`/`black` 都是真实素材
   （`fgimage/clear.tlg`、`rule/WH.PNG`）。看上去未解析是因为我的探测：
   抽取时 `--skip .tlg` 把 `clear.tlg` 漏了，且搜索目录列表漏了 `rule/`。
   → **正确判定**：先在档案清单里搜一下有没有同名文件。

1. **“属性 `&表达式` 未展开是最大缺口”—— 错。** Tyrano 原生支持
   `attr="&expr"`。实测三形式对照（同场景、同一素材）：
   `storage="telop1.png"`→200；**`storage="&f.img"`→200（求值成功）**；
   `storage="%f.img"`→空名不解析。`_find_asset` 对 `&...` **原样透传**，
   正是对的。**不需要为它加任何转换逻辑**。

1. **“属性 `&表达式` 未展开是最大缺口”—— 错。** Tyrano 原生就支持
   `attr="&expr"` 求值。实测三形式对照（同一场景、同一素材）：
   `storage="telop1.png"`→200；**`storage="&f.img"`→200（求值成功）**；
   `storage="%f.img"`→空名不解析。`_find_asset` 对 `&...` **原样透传**，
   正是对的。**不需要为它加任何转换逻辑**。
2. **“`anime_init.ks` 之后卡住 = 转换缺陷”—— 错。** 那是**测试方法
   问题**：构建执行到 `[playse]` 时在等玩家点击解锁音频（见下），而自动
   化测试没发过手势。表现与真缺陷**完全一样**（无请求、无报错、CPU 空闲），
   极易误判。

3. **“属性 `&表达式` 未展开是最大缺口”—— 错。** 见上第 1 条。

4. **“`[wt]` 是未定义标签（273 处）”—— 错。** `[wt]` 是 Tyrano **原生
   标签**（`tyrano.plugin.kag.tag.wt`：`is_trans` 为真时 `weaklyStop()`，
   否则 `nextOrder()`），语义与 KAG3 完全一致。我误报的原因：我的
   “原生标签发现”正则不完整，于是把一个已存在的标签归入“缺失”。
   → **正确判定**：直接在引擎源码里搜 `tyrano.plugin.kag.tag.<名>`；
   或在完整跑一遍的运行时日志里确认没有 undefined_tag。

### 5.2 测试陷阱：`[playse]`/`[playbgm]` 在等一个真实手势（务必知道）

Tyrano 的 `playbgm.start`：

```js
if ($.userenv() === "pc") {
  if (this.kag.tmp.ready_audio) { this.play(pm); }
  else { if (!can_ignore_in_no_ready) this.waitClick(pm); }   // 等点击
}
```

场景里的 `[playse]`（`stop=false`）必须等点击才能解锁（浏览器自动播放
策略）。`play()` 内部又是 **`audio_obj.once("play", ... next())`** —— 标签
在音频**真正开始播放**时才前进。所以：

- 无手势 → 停在 `[playse]`，**连音频请求都不会发**；
- 发一次点击 → `ready_audio=true`，音频加载并播放，脚本继续。

**实测验证**：点击后场景一路跑到标题菜单（服务端日志依次出现
`sound/rin_title.wav` → `fgimage/TITLE2.MA` → `bgimage/title2.png` →
`fgimage/title2_P.png` → `fgimage/TITLE.MA`），标题画面渲染正常。

因此：**验证“能否播放”必须发一次真实点击**（`visual-check` 技能的
手势阶梯默认会发，但“先截图看是否空白”那一步不会）—— 自动化测试里
必须显式发一个早期手势，否则会把正常构建误判为卡死。注意 `--mute-audio`
**不影响**解锁与播放（Howler 照常跑，只是没声音），所以静音测试是安全的。

### 5.3 已修：getter 贪婪正则吞掉 setter 块

`tjs2js` 的 property 转换曾用贪婪正则 `getter\s*...\{(.*)\}` 抽取
getter 体，把紧跟的 `setter(x){...}` **一并吞入**，于是 JS 里同时出现
原始 TJS `setter(ma){`（**非法语法**）和正确的 `set: function`。

- 症状：脚本运行到该文件**直接停住**（服务端日志表现为“请求停在这个
  文件之后再无任何请求”，且 CPU 空闲、CDP 不响应——很像是卡死）。
- 修法：`_tjs_property()` 用**配对花括号**抽取（`_brace_body`），不再
  吞入后续块，也不截断 getter 体内的 `if/for`。已加 4 个回归测试。

### 5.4 已修：TLG 解码 R/B 通道序错（全库图片红蓝互换）

**最隐蔽的一类 bug：契约与实现不一致。** TLG 像素在缓冲里是 `B,G,R,A`
（GARbro 的解码器保持该布局，并靠 `PixelFormats.Bgra32` 把它交给下游）。
本仓库的解码器同样产出 `B,G,R,A`，但 `decode()` 的文档写的是
**“Output: RGBA bytes”**，`decode_to_png()` 又直接把这些字节交给 Pillow
的 `"RGBA"` —— 于是**蓝色被当成红色**，全部转出的图片红蓝互换。

- 症状：人物立绘肤色发蓝；同一幅画的事件静帧偏蓝，而该事件的预渲染影片
  （**由 ffmpeg 解码，与 TLG 解码器完全无关**）是粉红/暖色。
- 为什么测试没拦住：`tests/test_tlg.py` 的 GARbro fixture 测试**自己做了
  补偿**（注释写着 “decoder output is BGRA bytes”，代码里手工 `row[x+2],
  row[x+1], row[x]`）。**一处产物与一处补偿互相抵消 = 绿灯，而真实消费者
  （Pillow）拿到的是错序字节。** 看到“某个测试为了通过而手工交换通道/翻转
  行序/减偏移”时，就该核对**被消费的那一侧**的契约，而不是继续信任测试。
- 修法：新增 `_swap_rb()`（自逆），在 `decode()` 唯一返回点归一化一次；
  混合路径把 `load_base` 的 RGBA 先归一化回内部布局再混合。一处覆盖
  TLG5/TLG6 × 纯 Python/numba 全部路径。
- 独立判据（三个，缺一不可）：
  1. GARbro 导出的 4 组真实 `.tlg/.bmp` **直通**比较（补偿已删，回归即红）；
  2. 同一幅画“静帧 vs 预渲染影片帧”的色调方向一致（**跨解码器对照**）；
  3. 第三方 Python 解码器（与本实现无渊源）在同一文件上给出互逆的通道序
     —— 这一条把“我们两个实现谁对”变成可判定问题，而不是互相背书。
- **缓存盲区（顺带修掉）**：构建幂等缓存只比源/目标 mtime，**看不见
  解码器自身改动** —— 修好解码器后旧 PNG 被静默跳过（实测确实如此，
  手工删才重转）。现在图片目标在解码器源码更新时一并失效。
  **规则：任何“产物只由代码内容决定”的缓存，键里必须含那份代码。**

### 5.5 排障方法（这套很有用，值得沿用）

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

## 6. 建议路线（与 `docs/kirikiri-html.md` 一致）

1. **先用路线 A**（JoiPlay 官方 KiriKiri 插件）验证游戏可玩性；
2. **A 档游戏才建转换器**：解包 → 统计标签分布 → 标签映射表 →
   脚本转换 → 素材转换 → `tyrano/pipeline.py` 构建 → serve 试玩 →
   翻译（复用统一 chunk 流程）；
3. 转换器范围**先收窄到首款游戏的标签子集**，逐步通用化。

### 6.1 多轮构造（像编译器那样分 pass，不要再“一把梭”）

反复出现的教训：**一行行字符串改写 + 事后补洞**会持续冒出静默失效
（行尾丢失、层叠被盖、空操作遮蔽引擎、缺失的运行期 API）。改为先**建中间
表示**再序列化，并把“不允许存在的情况”变成**构建闸门**：

| pass | 做什么 | 产物 |
| --- | --- | --- |
| 0 盘点 | 全语料标签/`kag.*` 调用点/引擎注册标签（三种写法）/素材清单 | 覆盖表：每个 KAG3 标签 → 引擎有 / 垫片 / 需移植 |
| 1 词法 | `.ks` → 逻辑行 + 标签流（不丢行尾、不跨界注释）+ 宏体 + iscript 块 | 标签流（结构化） |
| 2 语义 | 变量/图层/页数据流：哪些层动态、每层每页装什么、几何宏、存储是静态还是算出来的 | 图层/存储依赖图 |
| 3 解析 | 每个 storage/graphic → 唯一规范素材（静态在编译期定，算出来的用运行期表） | 解析表 |
| 4 API 面 | 每个 `kag.*` 调用点必须有实现或**有记录的 stub** | 无未解析方法（闸门） |
| 5 序列化 | 生成 TyranoScript + 垫片（带不变量） | 构建产物 |
| 6 验证 | iscript/shim 语法、进剧情路径、标签/行计数、**语音真播放**、**快进速率**、404 清单、QC | 验证报告 |

**构建闸门（构建失败优于静默失效）**：

> **现状（2026-09）**：转换器已按上表的关注点拆成 `kirikiri/kag/`
> （`tags.py` 对应 pass 0、`scenario.py` pass 1-2、`assets.py` pass 3、
> `shims.py` pass 5 + `js/` 垫片源码，另有 `fonts.py`/`project.py`/`cli.py`），
> `kirikiri/convert_kag.py` 保留为兼容层与 CLI 入口（命令不变）。
> 但代码**仍是一趟字符串改写**：上面的多轮中间表示与闸门尚未实现，
> 拆分只是把各关注点分到不同文件，便于下一步逐个改造成 pass。
>
> **素材 pass 已并行**（2026-09）：TLG/BMP/区域图转换是纯 Python CPU 活，
> 跑在 worker **进程**里（线程会被 GIL 串行化）——实测 824 个作业落在
> 16 个进程上，全量转换从 ~11 分钟降到 **87 秒**，产物与串行版本逐字节相同
> （sha256 清单比对）。默认并行度 = 本机**物理核心数**（见
> `rpgmaker/runtime.py`），`--workers 1` 回退串行、`--workers N` 手动指定。

- 垫片不允许遮蔽引擎标签（编译期差集 + 运行期复查）；
- 不允许存在未处理的 `kag.*` 调用点；
- 写入的每一行必须带行尾（`_finalize_output_lines` 不变量 + 测试）；
- 音频/语音必须实测能加载（探针：播一个真实语音文件并断言
  `readyState`/`duration`），不能只看“标签存在”；
- skip 速率必须实测（在剧情场景里数 `nextOrder`/秒），不能靠猜。

### 6.2 允许的“魔改 Tyrano”优先事项

改动一律限制在 CSS/JS 层（保持 WebView/JoiPlay 可运行），优先级：

1. **`[image]` 的“替换”语义**（与 KAG3 一致）：现在靠在场景文本里逐行改写
   成 `[freeimage] + [image]`（2551 处）；更干净的做法是只在一处覆盖
   `master_tag.image`，让场景文本保持原样。
2. **`[history]` / backlog**：引擎无此标签，而 KAG3 游戏的历史界面依赖它。
3. **存/读档**：KAG3 书签 API 与引擎的存档系统不同构；优先用引擎自己的
   存读档界面（游戏自带的那排按钮可不开）。
