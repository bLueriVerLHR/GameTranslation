# 实战笔记与坑（转换真实游戏学到的）

处理各种引擎/repack 风格的 RPG Maker MV/MZ 游戏时硬学到的教训。在下一款
游戏上跑流水线**之前**先读这篇。游戏身份刻意省略 — 教训按引擎与特征
写法记录。

## 0. Repacker 惯例

- repack 的 `.rar` 压缩包常**带密码**；解压用 `7z x -p<pass>`
  （见 `docs/workflow.md` §8 坑）。常见密码放在本地
  `docs/table/passwords.md`（gitignored）— 绝不入库。
- 布局：根目录 NW.js 运行时 + `www/`（MV）或根网页部署（MZ）。
  `detect.py` 自动找网页根。
- 某开发者的 MV 游戏**加密**资源（`.rpgmvp`/`.rpgmvo`，密钥在
  `data/System.json`）。它们跨游戏共享**公共资源库**（
  `img/faces/main_cha.png`、`img/tilesets/001_Particle.png`、`fsm_*`
  First Seed Material 套件）— 但每个游戏只带自己用到的子集，**所有被引用
  资源都在原文件里**。不要从另一款游戏拷贝资源来"修"缺失文件；下面的
  缺失文件报告是误报（见 §4）。
- repacker 有时留垃圾：ASCII 广告文件（`data/setting.json`，非合法
  JSON — 删）、`.url` 快捷方式、`Tool/` 目录、根 `翻译文件.json`
  （zh_CN 翻译）、`赠品/`（礼物）目录（用户想**保留**在构建里）。
- 目录命名 `<官方名>_JoiPlay`；剥掉**译者名**（有些 repacker 附加自己的
  名号），`System.json.gameTitle` 为空时设官方标题。

## 1. 流水线顺序 & 唯一要记住的

```
build → decrypt → audio → clean → verify → serve → compress
```

- 除非完全理解 `clean` 会删什么，**不要重跑已跑过的 `clean`**（见 §4）。
  先 `--dry-run`；它标出这些游戏的字体/图块时，别应用，并把已删的恢复。
- **serve 最后、compress 最后。** 先在浏览器里 HTTP 测，再打包。
- 源保持不动；工具库只写构建副本。

## 2. 本次会话的工具库补丁（已应用）

- **`decrypt.py`**：支持 MV `.rpgmvp→.png`、`.rpgmvo→.ogg`、
  `.rpgmvm→.webm`（16 字节 RPGMV 头 + 前 16 字节 XOR），不只 MZ `_`
  文件。解密只 XOR **前 16 字节** — 绝不整文件。
- **`verify.py`**：关键文件检查接受 MV 的 `js/rpg_core.js`（原来硬编码
  `rmmz_core.js`）。
- **`build.py`**：拷贝**所有根文件**（不只 `index.html`），`NWJS_RUNTIME`
  条目除外。有些游戏在网页根放必需数据（如换装数据 JSON）— 没有这个
  它们静默消失。
- **`serve.py`**：`Cache-Control: no-store`，测试时过期缓存的 404 不会
  遮蔽刚加入的资源。
- **`audio.py`**：跳过短于 1s 的文件。退化/空 SE（如 0.9ms 占位）算出
  巨大码率、被重编码，输出是坏 Ogg（"Error opening input: End of file"）
  顶掉好文件。
- **`clean.py`**：字体引用语料现在含 `css/` 与 `fonts/*.css`（MV 在
  `fonts/gamefont.css` 里声明 `@font-face`），字体名正则处理 **CJK
  文件名**（如 `ラノベPOP.ttf`），只考虑真字体扩展名（别删
  `gamefont.css`）。图块清理也保护语料里任何地方引用的名字。
- **`clean.py`（后续会话）**：含目录前缀的字体引用（FontLoad 插件在
  `js/plugins.js` 里写 `fonts/ship.otf`）现在按**basename**匹配 — 之前
  完整 token 永远不等于磁盘文件名，字体被删。

## 3. 这些游戏上 `clean` 很危险

两个已验证的失败，都是 `clean` 删掉了运行时加载但 `data/js` 里没引用的
资源：

1. **字体**：全部字体（含 `gamefont.css`）被删，因为 MV 的字体引用在
   `fonts/gamefont.css`，`_corpus_text` 没读它 — 且文件名正则匹配不了
   CJK 名。结果：回退字体渲染文本（Android 缺字形/方块）。**修复**：从
   源恢复字体，加上面的语料/正则修复。
2. **图块**：世界地图/换图块插件**动态**加载图块
   （`World_A1/A2/B/C`、`Inside_B`、`school_C/D`、
   `Tileset_Summer_Beach&Pool_A1/C`），即使 `Tilesets.json` 里没有。
   `clean` 删了它们 → "Failed to load: img/tilesets/World_A2.png"。
   语料检查**抓不到**（名字运行时拼出）。这类开发者的游戏**跳过 `clean`
   的图块部分** — 只省 ~4–25 MB。

安全做法：`clean --dry-run` 后，字体/图块被标出就**别应用**，并从源树
恢复文件（对 `img/`、`audio/`、`fonts/` 来说构建应是源的超集）。删
`img/` 下的 `.txt/.clip/.tmx/.bak` 垃圾永远安全。

## 4. "缺失资源"报告是 FALSE — HTTP 测试 bug，不是 repack 丢弃

早期笔记声称游戏请求从未随包的资源（运行时生成，`rg` 找不到），修复是
从同开发者另一款游戏拷贝：

- `img/faces/main_cha.png` → "从同开发者其他游戏拷贝"
- `img/tilesets/001_Particle.png` → "另一款游戏里有"
- `fsm_*` 图块 → "整套拷贝（199 文件 / ~105 MB）"

**全错。** "Failed to load" 错误是 HTTP serve bug 造成的（过期缓存的
404 / 复用端口上的残留服务器在服务旧目录 — 见 §8），不是真缺失。对照
最终构建验证：

- 两款游戏里都有 `img/faces/main_cha.png`。
- `Tilesets.json` + 地图 `tilesetId` 引用的每个图块在磁盘上都在（一款
  游戏 175 个引用全在；另一款 261 个全在）。
- `001_Particle.png` 只有其中一款引用，存在于它；另一款从不引用、不随
  包、也不需要。
- `fsm_*` 数量每款不同（86 vs 199），因为每款只带自己引用的文件。

**规则：相信原文件。** `verify`/浏览器报缺失资源时，先杀残留服务器、
禁用缓存重载、查磁盘路径。只有文件真从构建消失**且**被
`Tilesets.json`/地图/`js` 引用，才算 repack 丢弃。从来不需要跨游戏拷贝。

## 5. 长文件名（Android 解压失败）

有些 SE 把整句对话嵌在文件名里（一个 333 字节的 `.rpgmvo` 引用了整句）—
超过 255 字节组件上限，手机解压应用失败。

- 这些语音文件是**孤儿**（`data/js` 里没有任何引用）→ 安全改短 ASCII
  名或删除。
- 构建后总是扫 >200 字节的 basename：
  `[System.Text.Encoding]::UTF8.GetByteCount($_.Name)`。

## 6. CG 解锁（"方案 2" — 烘焙进构建）

对用开关挡住 CG 画廊的游戏，回想 / recollection 室把每个 CG 事件挡在
开关后面。从房间地图 + `System.json` 开关名找：

- 一个"全成人场景"总开关（每个 CG 事件都有页条件在它上面），
- 结局成就开关（BE1/BE2/TE/NE...）用于结局 CG，
- "回想室锁"开关锁房间出口 — 保持 OFF。

补丁 = 追加到 `js/main.js`（新游戏**和**读档都生效）：

```js
(function() {
    var UNLOCK_SWITCHES = [1571, 1572, 1573, 1574, 1575, 1577];
    function applyUnlock() {
        if (window.$gameSwitches && $gameSwitches.setValue) {
            for (var i = 0; i < UNLOCK_SWITCHES.length; i++)
                $gameSwitches.setValue(UNLOCK_SWITCHES[i], true);
        }
    }
    var _setupNewGame = DataManager.setupNewGame;
    DataManager.setupNewGame = function() {
        _setupNewGame.apply(this, arguments); applyUnlock();
    };
    var _loadGame = DataManager.loadGame;
    DataManager.loadGame = function(savefileId) {
        var ok = _loadGame.apply(this, arguments);
        if (ok) applyUnlock();
        return ok;
    };
})();
```

挑 ID 前先在 `System.json.switches[]` 里验证开关名，以及每个 CG 事件页
条件在哪些开关上。开结局开关有良性副作用（只变环境 BGM）。

- 另一款游戏用同模式，但主开关与换装解锁开关不同 — 同流程、逐游戏 ID。
- **坑：** 从 PowerShell 用**双引号**字符串追加这个补丁会把
  `$gameSwitches` 插值成空、弄坏补丁（`if (window. && .setValue)`）。
  用 here-string / 单引号文本或 write 工具写，压缩前确认 `$gameSwitches`
  还在。

## 7. 翻译（zh_CN 翻译文件.json）

- 用 `tools/translate_rpgmz.py <src> <out> --trs 翻译文件.json`，或用其
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

### 7.1 ExternMessage.js 游戏（MV）

- **对话在 `data/ExternMessage.csv`，不在 JSON。** 有些 MV 游戏带
  UTF-16LE `ExternMessage.csv`（列 `名前(ID),本文(body),...`）；事件只含
  指向它的 `\M[ID]` 引用。`translate_rpgmz.py` 原本只烘焙 `data/*.json`
  → 开场场景保持日文，且贪心翻译器重写了 `\M[...]` 里的 ID，破坏 CSV
  查找。**修复（已应用于 `tools/translate_rpgmz.py`）：** (1)
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
- **翻译后验证 CSV ID：** 地图 JSON 里每个 `\M[ID]` 必须在 CSV 的 名前
  列存在（排除既有缺失如 `\V[320`、`テスト`、单假名 — 源里本来就没有）。

### 7.2 `process`/`require('fs')` 插件破坏浏览器/JoiPlay 构建

任何在加载或标题画面读 `process.mainModule.filename` 或 `require('fs')`
的插件在纯浏览器里抛异常，JoiPlay 下可能失败。真实命中：一个剧情/对话
插件（261 个地图文件在用 — 关键）和一个 DLC "APPLY PATCH" 标题按钮插件。
补丁 = `process` 未定义时回退 `window.location.pathname`，或 `process`
缺失时提前 `return false`。`rg` 每个构建的 `js/plugins/*.js` 里的
`process\.`，只 patch 可达路径（标题画面、加载时 IIFE），不碰 F 键背后的
开发工具函数。

### 7.3 MoviePicture 新浏览器白屏 = 自动播放策略

origin 无自动播放带声音权限、播放不在用户激活内时，`<video>.play()`
promise 以 `NotAllowedError` 拒绝。Chrome 正常（早期会话的 site
engagement），Edge 不行。修复：`Bitmap_Video.prototype.play` 在 catch
里 `muted=true` 重试再取消静音；`_createVideo` 设 `autoplay=false`
（浏览器自己的自动播放尝试不可 catch，会记未处理 rejection）。

### 7.4 过期 per-origin Web Storage

`127.0.0.1:8100` 是所有游戏共享的一个 origin；localStorage/IndexedDB
（存档、插件偏好）在 Ctrl+Shift+R 后存活并在游戏间泄漏。每款试玩用
**新端口**。见 workflow.md §8。

### 7.5 MTool repack 可能带未翻译 `data/` + 根 `<title>.json`

一款 repack 正常 — 数据已翻译；另一款不是：repack 在游戏根带 MTool
字典、*数据文件仍是日文*；你必须自己烘焙：
`python tools\translate_rpgmz.py <built> <out> --trs "<title>.json"`
（那次 7742 条）。它还向 `css/game.css` 追加 CJK 字体回退。之后重
verify + serve --test。别假设"repack = 已烘焙"。

### 7.6 从不随包的默认 MV 音频名无害

`System.json` 在游戏换自定义音效后仍列原装名（`Attack3`、`Collapse1..4`、
`Equip1`、`Run`、`Ship1/2/3`、`Victory1`）；verify 报"缺失"但它们从未
随包。MV 静默播放缺失 SE。不是 bug。

### 7.7 静态 subagent 翻译工作流（全量批次）

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
  分块配 90KB 上下文预算（约 11,000 字符/块）、写优先契约下每轮 10 个
  subagent。旧的"450-530 键会死、块保持 100-160 键、2-3 个 agent 当
  节奏"指引**已过时** — 修 no-file 失败的是写优先 prompt（不是块变小）。
  失败后 `--resume --start N` 重分。
- **LLM 输出卫生：** (1) 修复遍历：双重转义非法转义、转义游离引号；
  (2) agent 偶尔改键（丢字符、键内译词）— 按编辑距离 ≤3 补到最近的多余
  键；(3) 值行数归一化到键（补 `""`）；(4) 合并并断言每个模板键都在。
- **跨分块术语一致性：** 维护 `terms.json` 日志；每个 agent 汇报决策，
  之后每个 prompt 带上累积日志。每个 prompt 强制确认过的角色词表；尽早
  发现人名变体（全名 vs 简称）并加入。
- **游戏 owner 语气指令进每个 chunk 上下文：** 成人场景遵循 owner 认可
  的语气（词表留本地，见 `docs/translation.md` §6）；剧情/揭示保持悬念；
  一行会溢出消息窗口时紧凑措辞。

### 7.8 残留翻译批次（write-first 修复）

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
- **姿势/动画名消歧：** 对 `腰振り(左スパ)` 类标签，作者意图在事件正文
  （跑哪些图）与同族其他标签（アへ顔/キス顔 = 表情）。别从无上下文假名
  猜；无法确定就保留构建里的假名（姿势名编辑器不可见）并向用户标记。
- **手工兜底：** subagent 在同一块反复死亡时，编排者可以手工翻（3k
  字符块完全可行），用脚本生成 plain 文件 — 脚本为每个键前置字节精确的
  前导空白；没有 agent 能可靠复现 `\u3000` 缩进。

## 8. 服务/测试卫生

- **总在固定端口服务，一次一款游戏。** 杀掉残留服务器（复用端口上的
  残留服务器在服务改名/旧目录，返回像游戏 bug 的 404）。
- `serve --test` 曾有 bug：空生成器上的 `all(...)` 返回 True，所有请求
  都失败也打印 "ALL 200 OK"。已在 `serve.py` 修 — 任何非 200 或失败请求
  现在都失败测试。拿不准仍用 `Invoke-WebRequest` 直接验真实 URL。
- no-cache 处理器意味着加资源后普通刷新即可。
- 工具路径：命令里直接用 `python`；ffmpeg 在
  `%LOCALAPPDATA%\Temp\opencode\ffmpeg_x\...\bin\`（见
  `rpgmz/config.py`），7z = `C:\Program Files\7-Zip-Zstandard\7z.exe`，
  ripgrep（`rg`）与 Everything（`es`）在 PATH。
- PowerShell 坑：`Start-Process -ArgumentList` 弄坏带空格参数；传单个
  预引号字符串（`'serve "' + $folder + '" -p 8100'`）并含脚本路径。

## 9. Repacker 广告壳插件

值得扫的 repack 模式：**长得正常但是纯广告代码的假插件**，如
`js/plugins/La_ExtraParameterFormulark.js`（`plugins.js` 里
`"status": true`，描述为"仓库"功能插件）。

- **结构：** 几行无害 var（`EnemyBookNum = 1;`），然后内联 **axios**
  HTTP 客户端（游戏从不需要）、内联 **pako** zlib（载荷解压）、
  obfuscator.io 式混淆代码（`_0x` hex 变量、
  `["constructor"](...)['apply'](...)` 动态调用、`\u007a\u0069\u007a\u0023`
  类字符串转义）。
- **检测：** `rg -l "axios|pako|_0x[0-9a-f]{4,}" js/plugins/*.js` — 常规
  插件之外的命中就是壳。也扫 `data/` 有没有插件命令真正调用它（这个零
  调用 — 纯壳，整体删除安全）。
- **反调试：** 用户报 DevTools 被挡（"debug 阻止溯源"）。静态
  `rg "debugger"` 找不到 — 混淆层运行时才发。信 axios/pako/_0x 扫描，
  不信 debugger 扫描。
- **删除：** 删插件文件 + 从 `js/plugins.js` 去掉条目（JSON 解析重写
  `$plugins` 数组）。
- 广告代码不在这里的其他位置（这次全干净）：`index.html`、
  `js/main.js`、APK 壳 `assets/web/main.html`（仅键盘/localStorage 桥）、
  APK `www/` 与 PC `www/` 字节一致。根级广告文件（广告配置、推广文案 —
  见本地广告关键词表）在网页根外，从不进 JoiPlay 构建。
- 删插件后 compress 前重跑 `verify` + `serve --test`。

## 10. TemplateEvent `<TE:name>` note 引用 vs 已译事件名

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

## 11. 一个大 MZ MTool-repack 转换（全流水线 + 全翻译）

一个大 MZ NW.js MTool repack（约 5.4 GB → 3.52 GB，双卷密码 RAR）上跑
全流水线 + 全翻译。关键记录：

- **无加密**（System.json 无标志/密钥）→ `decrypt` 跳过；音频 −427 MB
  （重编码 5614 文件），clean −26 MB，74 个未用图块。
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
- **本次会话工具修复：** `harvest_translation.py` 用纯 `utf-8` 读工作
  文件但 `build_translation.py` 写 `utf-8-sig`（BOM）— 读改为
  `utf-8-sig`。`bake_translation.py` 在 `parameters` 为空的 401/405 命令
  上崩（块写路径）— 写前像逐行路径那样归一化为 `[""]`。
- **游戏根的奖励 ZIP 不是垃圾** — 删除前检查是不是游戏官方通关特典
  （游戏内 NPC 经 `<namePop:…>` note 引用）。名字引用在对应地图 patch
  成译名并记录进 translation_kv.json（namePop Lv<N> 标签保持原样）。
- **自带全解锁 NPC 的游戏**不需要 `unlock_gallery.py`。
- **残留验收：** 剩 21 键全豁免（7 个 CV/画师 様 名、4 个纯呻吟行、
  9 个功能性插件字符串、1 个编辑器内部标签）。
- MoviePicture 自动播放修复已应用（8 部电影随包）；FOSSIL/fix-load-failed
  `process` 路径是 NW.js-only 死分支，不动。无超过 4096 的 PNG → 不做
  LowRes。
- **浏览器/JoiPlay 里 FOSSIL（MV→MZ 互操作）入口必须跳过 setup 块。**
  FOSSIL 的插件模式 setup（作为普通插件用原装 `js/main.js` 入口加载）
  XHR 加载 index.html 并调 `writeNewIndexFile` → `require("fs")` → 浏览器
  里 `Uncaught ReferenceError: require is not defined`，游戏静默运行**无**
  MV 兼容注入（战斗插件降级）。修复 = 作者文档化的 "skip setup" 路径：
  把 `index.html` 指向 `js/plugins/FOSSIL.js` 作为唯一入口脚本（替换
  `js/main.js` 并保留 `js/` 前缀 — FOSSIL 自己的 `writeNewIndexFile`
  做 `replace("main.js", "plugins/FOSSIL.js")`），于是
  `typeof(scriptUrls) == "undefined"`、FOSSIL 接管 main（内联脚本定义
  `scriptUrls` 自身、加载核心脚本、patch PluginManager）。无 fs/重定向。
  控制台显示 `FOSSIL is now running as main.` 修复后重新打包。

工具加固（同一会话）：2,187 部分块类现在修在工具里，不手工：
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
