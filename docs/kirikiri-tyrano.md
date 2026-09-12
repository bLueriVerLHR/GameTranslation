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
  此项未完成**；排查脚本在 `.tmp/trail_story.py`、`.tmp/catch_tag_error.py`。

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

### 4.5 已验证

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
