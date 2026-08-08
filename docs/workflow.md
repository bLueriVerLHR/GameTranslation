# RPG Maker → JoiPlay 工作流

如何把 RPG Maker MZ/MV 游戏转换成 JoiPlay 兼容构建、压缩、测试、打包 —
用本工具库的 `pipeline.py` 命令行。

本工作流覆盖的引擎/特征案例（不含游戏名）：

| 案例（引擎 + 特征） | 要点 |
| --- | --- |
| MZ、NW.js 根部署、纯 ogg 音频 | 纯 ogg 音频 — 压缩空间小 |
| MZ、NW.js 根部署、异步图片加载 | AsyncLoadImage fs 修复（选择场景） |
| MV、`www/` 部署、加密资源 | 加密 `.rpgmvo`/`.rpgmvp` 资源 |
| MZ、NW.js 根部署、加密 + CG 保无损 | 加密 `.ogg_`/`.png_`；CG 保无损 |
| MZ、NW.js 根部署、密码保护 RAR | 默认加密密钥；AI 翻译已烘焙 |
| MZ、NW.js 根部署、10GB+ 媒体重 | 加密 `.png_`；webm 电影全保留（事件都引用）— 媒体已压缩，压缩空间小 |
| MV、`www/` 部署、加密 + 剧情插件 | Saba_SimpleScenario `process` 修复；MoviePicture 自动播放修复；`clean` 字体匹配 bug 后恢复 3 个字体 |
| MV、`www/` 部署、加密 + DLC 补丁插件 | DLC 补丁插件 `process` 修复；22 个默认 MV 音频引用未随包（无害） |
| MZ、NW.js 根部署、加密 + MTool 字典 | MTool 翻译 `<title>.json` 已烘焙；无 `process` 插件 |
| MV、`www/` 部署、加密 + ExternMessage.csv 对话 | 根 `<title>.json` 已烘焙；**ExternMessage.csv 对话**（UTF-16LE，`\M[ID]` 引用受保护）；MV `gamefont.css` 拆分 + NotoSansSC 打包；嵌套 `www/www` 重复跳过 |
| MZ、NW.js 根部署、加密 + MTool 运行时字典 | 根 `<title>.json` 运行时字典（不可静态烘焙 — 重提取成静态模板，走 subagent 工作流，见 `docs/translation.md`） |
| MZ、NW.js 根部署、加密 + TemplateEvent 插件 | 静态翻译已烘焙；**TemplateEvent `<TE:name>` note 引用 vs 已译模板事件名**（移动锁死 — 已在 `bake_translation.py` 修复） |
| MZ、NW.js 根部署、MTool repack、无加密 | MTool 字典 harvest + **11,000 字符块的 subagent 补翻**（auto 选档）；harvest `is_name_line` 首行 bug 用逐行片段重建修复；identity 条目剔除 |

---

## 1. 环境要求

- Python 3.10+（命令里直接用 `python`）。
- ffmpeg / ffprobe（gyan.dev `ffmpeg-release-essentials` — 含 libvorbis）。
  默认路径 `%LOCALAPPDATA%\Temp\opencode\ffmpeg_x\...\bin\`；用 `FFMPEG` /
  `FFPROBE` 环境变量或 PATH 覆盖。
- 7-Zip-Zstandard（默认 `C:\Program Files\7-Zip-Zstandard\7z.exe`，或
  `SEVENZ` 环境变量 / PATH）用于 `-m0=zstd` 压缩包。
- ripgrep（`rg`）在 PATH 上，用于快速内容搜索（如预扫插件）。
- Everything（`es` CLI）在 PATH 上，用于跨盘即时文件名查找。
- PowerShell 5.1（无 `?.`、无 `&&`；用 `;` / `if ($?)`）。

## 2. 一键流水线

整个转换是 `build → decrypt → audio → clean → verify`，然后**测** —
`serve --test` — 最后才 `compress` 打包。`decrypt` 只在 RPG Maker MZ/MV
且 **easy** 加密时是默认步骤；复杂/自定义加密游戏上它不改任何东西
（见 §4）。如果某步不会改变最终构建，跳过它。

```powershell
$tk  = "<本工具库路径>"                 # 如本仓库目录
$src = "C:\path\to\game"                 # 原版游戏目录 — 绝不修改
$out = "$env:LOCALAPPDATA\Temp\opencode\game_JoiPlay"   # Temp 工作目录（之后可删）

python $tk\pipeline.py build   $src -o $out
python $tk\pipeline.py decrypt $out          # 仅 RPGM + easy 加密；否则跳过
python $tk\pipeline.py audio   $out          # 探测 + 重编码；收益最大
python $tk\pipeline.py clean   $out          # 垃圾文件 / 未用字体 / 未用图块
python $tk\pipeline.py verify  $out --source $src   # PNG 签名、JSON、音频引用、标志位
python $tk\pipeline.py serve   $out --test   # 关键文件 HTTP 冒烟测试
python $tk\pipeline.py compress $out -o "C:\path\to\deliverables\game_JoiPlay.7z"
```

`build`、`decrypt`、`audio` 在 asyncio + 线程池下并行（每步 `--workers N`，
默认 6/8/4）。`verify --source <原版>` 对照原版检查缺失音频引用：原版也缺
的是既有源怪癖 → 只警告不算失败 — 只有转换造成的丢失才失败。

`serve --test` 启动本地 HTTP 服务器，抓取 `index.html`、`js/main.js`、
`data/System.json`、一首 BGM、一张 CG，确认全部 200 后退出。压缩前在
浏览器里通过 HTTP 打开游戏 PC 试玩。**JoiPlay 本身才是真正的手机测试**
— 见 §7。

### 文件放哪（强制布局）

- **工作/解压文件放 Temp 目录 — 绝不放原位。** 流水线绝不在原版游戏目录
  里或旁边解压/构建。工作副本在 Temp 路径（如
  `%LOCALAPPDATA%\Temp\opencode\<Game>_JoiPlay\`），压缩包做完即可删除。
- **成品放专门交付目录，与其他游戏一致。** 最终交付物 — JoiPlay 目录
  `<Game>_JoiPlay\` 与压缩包 `<Game>_JoiPlay.7z` — 放同一个固定目录，
  命名与其他转换过的游戏完全一致。原版游戏保持不动。
- **高清 vs 低清（手机贴图限制）。** Android WebView/PixiJS 把 WebGL
  贴图限制在**每边 4096 像素**；任何超过 4096 的 PNG（通常是竖版立绘，
  如 2160x4237）在手机上渲染成**黑块**，PC 浏览器正常。约定：
  - `<Game>_JoiPlay` / `<Game>_JoiPlay.7z` = 高清构建，图片不动（PC 与
    未来设备可用）。
  - `<Game>_JoiPlay_LowRes` / `<Game>_JoiPlay_LowRes.7z` = **独立兄弟
    构建**，所有超过 4096 的 PNG 缩放到 ≤4096（保持宽高比 + alpha，
    PNG）。其余完全一致。
  - 只有确实存在超过 4096 的 PNG 时才做 LowRes（扫 IHDR 头字节 16-23，
    无需完整解码）。绝不覆盖高清目录；原版保持高清母版。
  - 记录：一款游戏 30 张 2160x4237 竖版立绘（缩放后 2088x4095）在
    JoiPlay 里造成黑块；2026-08 修复。

## 3. 引擎检测

`detect.py` 找出网页根目录：

- **MZ 根部署**：游戏根目录有 `index.html` + `js/`（NW.js 打包 MZ 的常态）。
- **MV**：通常是 `www/` 子目录，含 `index.html` + `js/rpg_core.js`。
- 如果根目录本身就是网页根，原样使用。

`pipeline build` 打印检测到的引擎与网页根。

## 4. 步骤细节

### build — 剥离 NW.js 运行时

JoiPlay 的 RPG Maker 插件只需要网页文件：`index.html`、`css/ data/
dataEx/ effects/ fonts/ icon/ img/ js/ audio/`（MV 加 `movies/`）。桌面
NW.js 运行时纯属浪费，不拷贝。编辑器/repack 垃圾（`img/` 下
`.txt/.clip/.tmx/.bak`）之后在 `clean` 里删。

拷贝并行（asyncio + 线程池，默认 6 worker）：每个网页目录和根文件由自己
的 worker 拷贝，构建速度受磁盘带宽而非单线程限制。

### decrypt — 加密资源（easy vs complex）

`decrypt` 是**默认步骤，仅当它能解密一切时**：引擎必须是 RPG Maker
MZ/MV **且**每个加密资源都带标准 RPGMV 头（"easy" 加密）。它绝不碰不带
头的文件；复杂/自定义加密游戏上它什么都不动 — 所以这类游戏上跑它不改变
任何东西，跳过即可。总原则：如果解密不会改变游戏在 JoiPlay 下的运行
方式，就不运行。

MZ（`*.png_`、`*.ogg_`）与 MV（`*.rpgmvp`、`*.rpgmvo`、`*.rpgmvm` —
分别图片、音频、电影；MV 解密后改回标准扩展名）用同一方案：

- 文件 = **16 字节头** `52 50 47 4D 56 00 00 00 00 03 01 00 00 00 00 00`
  （`RPGMV\0\0\0\0\0x03\0x01`...）
- 后面是真实数据，其**前 16 字节用密钥 XOR**
- 密钥 = `data/System.json` 的 `encryptionKey`（32 字符 hex → 16 字节）

`decrypt` 原地并行解密（默认 8 worker），去掉尾下划线（MZ）让 JoiPlay
能加载，并清掉 `System.json` 的 `hasEncryptedImages` / `hasEncryptedAudio`
/ `encryptionKey`。JSON **不带 UTF-8 BOM** 写出 — PowerShell
`Set-Content -Encoding UTF8` 加的 BOM 会破坏引擎 `JSON.parse`
（真实踩过的 bug）。

**`data_encrypted/`：** `hasEncryptedData` 的 MZ 游戏把 DB JSON（有时含
`ExternMessage.csv`）以同方案加密放在 `data_encrypted/`。`decrypt` 把它
们按原名解密进 `data/` 并删除该目录，引擎（标志位已清）从 `data/` 加载。
若它们不带 RPGMV 头（自定义/插件加密），目录原样保留、标志位保持。

**`--key <hex>`：** 对 `System.json` 藏起 `encryptionKey` 的游戏（自定义
运行时解密，如 AES 插件）的显式密钥覆盖 — JSON 键缺失或不可读时手动传。

**Easy vs complex（easy-only 规则）：** 每个文件先查 RPGMV 头。带头的
是 "easy" — 干净解密。**不**带头（自定义/插件运行时解密，如 AES 插件，
或 `data_encrypted/` 里非标准的文件）的是 "complex" — **原样保留**。
加密标志位**只在所有加密资源真的被解密时**才清（easy 情形）。复杂游戏上
保持标志位，引擎自己的运行时解密在 JoiPlay 下继续工作 — 清掉会让引擎把
仍加密的文件当明文加载，游戏启动失败。`decrypt` 日志报
`decrypted N assets (M left as-is)`。

### audio — 收益最大

`audio` 先用 ffprobe 探测每个文件，再只重编码有帮助的。探测（8 worker）
与编码（4 worker）在线程池上运行、由 asyncio 汇总，ffprobe/ffmpeg 持续
并行：

| 条件 | 动作 |
|---|---|
| 立体声 & 码率 > 112 kbps（音乐） | `libvorbis -q:a 3`，保持采样率/声道 |
| 单声道 & 码率 > 64 kbps（语音/音效） | `-ar 32000 -ac 1 libvorbis -q:a 2` |
| 低于阈值 | 保留原文件 |

- 总是 `-map 0:a:0` — 许多 MZ BGM 内嵌封面 **mjpeg 视频流**，否则会被
  带进输出。
- 循环标签（`LOOPSTART`/`LOOPLENGTH` Vorbis 注释）用 ffprobe 读、重编码
  时重新注入。游戏无循环标签时保持整文件循环默认。
- 只在更小时覆盖；绝不转 Opus（用 `stbvorbis`/`vorbisdecoder.js` 的 MZ
  只能解 **Vorbis**）。
- 先用 `--sample N` 在少量文件上试策略，`--probe-only --report file.csv`
  只查码率不动文件。

记录：一款游戏音频 **1889 MB → 471 MB**（全部 4028 个文件之后解码干净）。

### clean — 只做安全删除

只删可证明未用的，绝不碰 CG：

- **`img/` 里的非 PNG**（`.txt/.clip/.tmx/.bak`）— 运行时不加载。
- **未用字体** — 文件名（不区分大小写）出现在 `data/` 或 `js/` 里就保留；
  被引用但磁盘大小写不同（如 `onryou.TTF` vs 引用的 `onryou.ttf`）**改名
  为被引用名**，Android 大小写敏感文件系统才找得到。省 ~90–100 MB。
- **未用图块** — 对照 `Tilesets.json` 的 `tilesetNames`（不区分大小写，
  保留 `name_2` 类前缀变体）。省 ~36 MB。

`img/pictures` 的 CG 刻意不碰：有些游戏用变量动态拼 CG 文件名
（`'0306_PartsFace_' + n + '_L'`），"到处没引用"的扫描不可信。

先 `clean --dry-run` 预览再删。

### verify — 打包前必做

- 每个 PNG 以 `\x89PNG\r\n\x1a\n` 签名开头。
- 每个 `data/*.json` 可解析。
- `System.json` 加密标志位已清、文件无 BOM。
- `System.json` 引用的每个音频名（标题/战斗 BGM、ME、SE、载具 BGM）在
  磁盘上存在 `.ogg`。带 `verify --source <原版>` 时，**原版也缺**的引用
  报无害警告（既有源怪癖，引擎静默播放）而不是失败 — 只有转换造成的
  丢失才失败。
- 关键文件存在：`index.html`、`js/main.js`（或 `rpg_core.js`）、
  `js/plugins.js`、`data/System.json`、`audio/`、`img/`。
- `verify --decode` 额外对每个音频文件完整 ffmpeg 解码（过滤无害的
  "non monotonically increasing dts" muxer 警告）。

## 5. JoiPlay 专项修复

### AsyncLoadImage.js / PluginUtils.js fs 问题（异步图片加载的 MZ 游戏）
症状：JoiPlay 里选择场景（与任何 `ImageManager.loadSystemAsync(...)`）
报 "failed to load img/system/choice_bg_normal.png" 之类，即使 PNG 存在。
根因：这些插件把加载挡在 `require('fs').accessSync("img/xxx.png")`
相对路径检查后面；JoiPlay 的 `require('fs')` shim 解析不佳。修复（在
JoiPlay 副本 `js/plugins/AsyncLoadImage.js` 里）：删掉 `fileExists()`
检查，总是加载：

```js
ImageManager.loadBitmapFromUrlAsync = function(url) {
    return new Promise((resolve, reject) => {
        const cache = url.includes("/system/") ? this._system : this._cache;
        if (!cache[url] || !cache[url]._baseTexture) {
            const bitmap = Bitmap.load(url);          // 与其他图片同一路径
            cache[url] = bitmap;
            bitmap.addLoadListener(() => resolve(bitmap));
            bitmap.addErrorListener(() => reject(bitmap));
        } else {
            resolve(cache[url]);
        }
    });
};
```

`PluginUtils.js` 有类似的 `fs.accessSync` 检查，只用于翻译/语音*可用性* —
误判导致回退而非崩溃。留着。

### 字体文件名大小写
插件引用 `onryou.ttf` 而文件是 `onryou.TTF` 时，Windows 上没事（大小写
不敏感），Android 上可能失败。`clean` 自动归一化。

### 存档目录
本地 `save/` 目录不拷贝；JoiPlay 管理自己的存档。

### 画廊 / 回想モード解锁（可选）

有些游戏把 CG 画廊/回想室挡在进度后面。可选工作流
`tools/unlock_gallery.py` 自动处理常见"全 CG 标志"情形：

```
python tools\unlock_gallery.py <built>          # 检测 + 应用
python tools\unlock_gallery.py <built> --dry-run   # 只报告
python tools\unlock_gallery.py <built> --switches 45,1   # 覆盖检测
```

原理：按名字找画廊地图（回想/ギャラリー/回忆/画廊/album/…），扫该地图
事件页条件，挑出**全解锁开关** — 挡住最多画廊条目的开关，优先名字带
開放/解放/open/unlock 的。安全规则：也挡住画廊地图**外**事件的开关被
拒绝（强制它会改变正常游戏）。然后写 `js/plugins/GalleryUnlock.js`
（启动时开开关：新游戏与每次读档）并注册进 `js/plugins.js`。删插件文件
+ 条目即可恢复普通解锁。

**只有游戏需要时才用。** 有些游戏自带简单全解锁（回想室通关后全开）—
先试玩；画廊正常游玩就能全开就跳过此工具。另注意有些游戏在
"移動禁止" 类开关打开时限制移动（由移动禁止插件驱动）— 那是正常游戏
行为，不是要修的。

游戏**没有任何**全解锁标志（只有逐 CG 开关，或插件/存档式画廊）时，
工具报告并什么都不做 — 别发明标志，保留原解锁机制。只在
`verify` 之后的翻译/最终构建上运行。

## 6. 打包（7z-zstd）— 最后一步

```powershell
python $tk\pipeline.py compress $out -o "C:\path\to\deliverables\game_JoiPlay.7z"
```

运行 `7z a -t7z -m0=zstd -mx=15 -mmt=on <archive> <folder>` 再 `7z t`
确认 "Everything is Ok"。目标路径已有 `.7z` 时**先删** — `7z a` 是追加，
压在旧包上会双倍（旧 + 新条目）。**试玩之后再运行。** 压缩包直接写进
交付目录；把成品 `<Game>_JoiPlay\` 目录也移过去（Temp 工作目录即可删除）。

### 6a. 压缩前清理（mandatory）

**最后**压缩，且目录干净后：

- 删除广告/推广文件（推广/注册链接类文案 — 具体文件名见本地
  `docs/table/ad_keywords.md`）。
- 删除不必要的外部工具脚本：MTool 注入残留 —
  `与工具一同启动.bat`、`从游戏中移除工具文件.bat`、`winmm.dll`、
  `version.dll`、`injectPath`，以及游戏本身不引用的根 `<title>.json`
  运行时字典（先 `rg -l "<title>" js index.html` 确认）。
- 若游戏已翻译（数据已静态烘焙成中文），把翻译 KV（烘焙用的
  `translated.json` 或等价 {ja→zh} 字典）归档进游戏根目录
  **`translation_kv.json`**，后续修改/重译从同一 KV 起步。未翻译游戏
  不带此文件。
- 然后 `compress`（替换旧包 + 完整性测试）。

## 7. 手机上运行

1. Android 安装 JoiPlay + RPG Maker 插件。
2. 解压 `.7z`（JoiPlay 的 zip 解压器或 ZArchiver）。
3. `+ → Add Game → select index.html`（MV 用 `www/index.html`）。
4. 桌面构建的存档**不**继承。

## 8. 坑回顾

- 密码保护 RAR：`7z x` 交互式提示会挂起命令行。用 `-p<pass>` 传密码。
  不带密码文件名可见（`7z l` 可用），但解压失败。常见密码见本地
  `docs/table/passwords.md`（gitignored）。
- **Repacker 广告壳插件：** 每个构建都扫 —
  `rg -l "axios|pako|_0x[0-9a-f]{4,}" js/plugins/*.js`。命中通常是假
  "插件"纯广告代码（内联 axios + pako + 混淆载荷；见
  `docs/experience.md` §9）。`data/` 里没有调用它的插件命令就删文件 +
  `plugins.js` 条目。
- RPG Maker MZ 默认加密密钥 `d41d8cd98f00b204e9800998ecf8427e`
  （空字符串 MD5）非常常见 — `decrypt` 当普通密钥处理。
- MTool repack 垃圾：repack 在游戏根目录带 `Dictionaries/`、`MTool/`、
  `locales/`、`swiftshader/`（`build` 自动跳过 — 不在 `WEB_DIRS`）。
  根级 repack 文件 — `reo.json`、`与工具一同启动.bat`、
  `从游戏中移除工具文件.bat`、推广 `.txt`、隐藏标记文件（13 字节、
  推广内容）— 是真垃圾：引擎不加载，可以从 JoiPlay 副本删除。
- **翻译文件不是垃圾。** MTool/AI 翻译文件以几个常见名字出现：
  `AI翻译.json`、`翻译.json`，或 `<游戏名>/<文件名>.json`（游戏名目录里的
  `.json`）。留在 JoiPlay 副本 — 几 MB，引擎忽略，之后还能用
  `translate_rpgmz.py --trs` 重新应用（或 `detect_trs` 自动检测）。
  只有你故意不要翻译时才删。
- 画廊 / 回想モード解锁是**可选**功能。有全解锁标志就 `tools/unlock_gallery.py`
  （见 §5）在最终构建上应用。没有这种标志的游戏（插件/存档/逐条目解锁）
  别管 — 核心游戏没它也能跑，玩家正常游玩解锁。
- 开发者工具插件残留：`Text2Frame` 带一个 `require('fs')/require('path')`
  插件，其 `IMPORT_MESSAGE_TO_EVENT` 命令指向**未随包**的
  `text/message.txt`，活在不可达的开发事件（"テキストコピペ用" 地图）。
  对话已烘焙进事件。patch 前先查可达性 — 引用文件不随包就是死代码，
  插件可以不管。
- **`process`/`require('fs')` 插件在浏览器 + JoiPlay 崩溃：** 任何在加载
  或标题画面读 `process.mainModule.filename` 或 `require('fs')` 的插件在
  纯浏览器里抛 `process is not defined` / `require is not defined`，JoiPlay
  下可能失败。真实命中：`Saba_SimpleScenario.js`（整个剧情/对话系统 —
  把 `SCENARIO_PATH`/`DATA_PATH` 都改成 `process` 未定义时回退
  `window.location.pathname`）与 `Wataridori_AddFileSystem.js`（DLC
  "APPLY PATCH" 标题命令 — `checkAddCommandEnable()` 用
  `typeof process === 'undefined' → return false` 守护；补丁通常已应用，
  按钮是死重）。每个构建预扫：`rg -n "process\." js/plugins/*.js`，
  只 patch 真正执行到的路径（标题画面、加载时 IIFE），不碰 F 键背后的
  开发工具函数。
- **MoviePicture 自动播放 = 新浏览器白屏：** 插件 `<video>.play()` 在
  origin 无自动播放带声音权限、播放不在用户激活窗口内时被拒
  （`NotAllowedError`）— 显示为白色视频画面。双源修复：(1)
  `Bitmap_Video.prototype.play` 在 `promise.catch` 里 `muted=true` 重试
  再 `.then` 取消静音；(2) `_createVideo` 设 `autoplay=false` 去掉不可
  catch 的浏览器自动播放尝试。Chrome 常正常（该 origin 有早期会话的
  "site engagement"）；新浏览器（Edge）patch 前失败。
- **Web Storage 按 origin 隔离，Ctrl+Shift+R 不清：** 所有游戏共用
  `127.0.0.1:8100` 同一 origin，上一款游戏的 localStorage / IndexedDB
  （RPG Maker 存档、插件偏好）泄漏进下一款。刷新永远不清。修复：每款
  游戏**新端口**（新 origin）服务，或 DevTools → Application → Clear
  site data。`serve --test` 可留在 8100；长驻 `serve` 试玩每款游戏用
  新端口。
- **带已烘焙翻译的 MTool repack 数据仍是日文：** 有些 repack 在游戏根
  目录带 `<game title>.json`（MTool 字典）— `build` 会拷贝（根文件），
  但**数据在你翻译前保持日文**。两种情况：
  - 字典是**静态、逐行键**模板 → 用旧版
    `tools/translate_rpgmz.py <build> <out> --trs <title>.json` 烘焙
    （写进 `data/*.json`，向 `css/game.css` 加 CJK 字体回退）。
  - 字典是 **MTool 运行时替换文件**（键是 `\n` 拼接的整条消息 + 片段键）
    → **不可静态烘焙**；贪心片段回退会毁句子（「のはいいが」→「的
    いいが」）。用静态工作流：`tools/build_translation.py` → 词表 →
    `tools/gen_translation_shards.py` → subagent →
    `tools/bake_translation.py`（见 `docs/translation.md`）。
  字典文件本身可留在构建根目录（引擎忽略）。
- **从不随包的默认 MV 音频名无害：** `System.json` 常仍列着原装 MV 名
  （`Attack3`、`Collapse1..4`、`Equip1`、`Run`、`Ship1/2/3`、`Victory1`、
  …），游戏换自定义音效后还在。verify 报"缺失"但它们从未随包 — MV
  静默播放缺失 SE。`verify --source <原版>` 自动变成警告；别"修"。
- 用 `stbvorbis` 的游戏绝不把 `.ogg` 重编码成 Opus — 保持 Vorbis。
- 解密只 XOR **前 16 字节** — 全文件解密是错的。
- 除非插件保证 `.ogg`，别删 `.m4a`；有些游戏把 `audioFileExt()` 硬编码
  成 `rmmz_managers.js` 里的 `.ogg`。
- `System.json`（或任何 JSON）里的 UTF-8 BOM 破坏 `JSON.parse`。
- 原版游戏目录保持不动；只在 Temp 副本工作
  （`%LOCALAPPDATA%\Temp\opencode\<Game>_JoiPlay\`）。
- CG 图片珍贵 — `clean` 绝不碰 `img/pictures`。
- 别过度修插件：只 patch JoiPlay 里真正坏的。
- **翻译决策规则（问一次，然后行动）：**
  1. 用户要求翻译了吗？→ 应用。
  2. 没要求 → 检查翻译文件（`detect_trs` 优先级：`<*>翻译.json`、
     `AI*.json`、`<游戏目录名>.json`、剩下的唯一根 `.json`）。
  3. 有 → 用户禁止翻译吗？
  4. 没禁止 → 加载并应用翻译。
  有翻译文件时绝不问"你要翻译吗" — 文件在场就是意图。都没有就先
  `serve` 试玩检查，再问。找到文件后判断是静态逐行键模板（→ 旧版
  `translate_rpgmz.py`）还是 MTool 运行时字典（→ 静态 subagent 工作流，
  `docs/translation.md`）。
- 流水线后应用翻译：`translate_rpgmz.py <built> <new>`（兼容静态字典）
  或 `bake_translation.py <built> <new> --trs translated.json --glossary
  glossary.json`（静态 subagent 工作流）会拷贝**已解密、已压缩**的构建、
  把字典烘焙进 `data/*.json`、应用**标准字体策略** — 无需重跑
  `build`/`audio`/`clean`。bake 现在：低于 `--min-coverage` 50% 拒绝
  （→ 改全量翻译，`--force` 覆盖）、自动剔除 identity 条目、
  自动检查 `<TE:>`/`<namePop:>` 引用对照事件名、自动在输出根归档
  `translation_kv.json`。然后重跑 `verify --source <原版>`、`serve
  --test`、**新端口** HTTP 试玩（同端口 origin 共享 localStorage）、
  再 `compress`（替换旧包）。注意：它用 `indent=2` 重写所有 `data/*.json`
  （无害），且需要手机上有 CJK 字体（回退列出系统字体；译文显示方块就
  打包一个）。

### 标准字体策略（owner 偏好, 2026-08 定案）

中文/拉丁 → 打包的中文字体（默认得意黑，`--cjk-font` 指定，缺省读
`CJK_FONT_PATH` / 本地 `docs/table/local_font_path.txt`）；**日文 →
游戏原始字体**（游戏自带的字体文件）。实现（`translate_rpgmz.py
apply_font_policy`，幂等可重跑）：

- **MZ**（有 `js/rmmz_managers.js`）：`System.json`
  `advanced.mainFontFilename` 置空（引擎不再注册全范围 FontFace，杜绝
  FontFace 与 CSS @font-face 优先级歧义），`css/game.css` 的
  `rmmz-mainfont` 按 unicode-range 拆两张脸 — `U+3000-30FF, U+FF00-FFEF`
  （假名 + 日文标点）→ 游戏原字体；其余（汉字/拉丁）→ 中文字体。
- **MV**（无 `rmmz_managers.js`）：`fonts/gamefont.css` 按 unicode-range
  拆分（假名/ASCII 保留原字体，汉字走中文字体）+ `css/game.css` 追加
  GameFont 回退块。MV 的 GameFont/YaHei 块**绝不追加到 MZ**（会覆盖
  rmmz-mainfont 族，全游戏渲染成系统雅黑 — 已踩过）。
- 无 `--cjk-font` 时策略整体跳过（游戏保持原字体）。

## 9. Unity 游戏（流水线之外）

Unity 游戏（`<Game>.exe` + `<Game>_Data/` + `globalgamemanagers`，无
`index.html`/`js/`）**不是 RPG Maker**：流水线步骤全不适用，JoiPlay 也
无法运行。处理规则：

- **范围：仅翻译。** 检查 `BepInEx\config\AutoTranslatorConfig.ini`
  （`Language=`、`FromLanguage=ja`）查正文翻译，`BepInEx\plugins\*Json\`
  下的 JSON 语言包查 mod 新增文本。只有用户要求才碰翻译。
- **交付：解压到 Unity 游戏目录**（先 Temp 再移动；剥掉 repack 的双重
  嵌套目录）。无 decrypt/audio/clean/verify/compress 步骤。
- **广告清理：** 删除根推广文件（推广文案等）；保留版本/更新说明 readme。
- **病毒检查：** BepInEx DLL 清单只允许标准 BepInEx/XUnity 组件 + 已知
  mod DLL；exe 签名（无签名正常）；可选 `Start-MpScan -ScanType
  CustomScan -ScanPath <dir>` — 注意 `Get-MpThreatDetection` 返回全部
  历史，按路径过滤。

Unity 引擎的翻译方案（Mono 用 AutoTranslator、IL2CPP + Addressables 用
MelonLoader 运行时 hook、RPG Maker Unite 用 BepInEx + Harmony）见
`AGENTS.md` 的引擎专项章节。
