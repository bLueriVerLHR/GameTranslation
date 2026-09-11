# RPG Maker → JoiPlay 工作流

如何把 RPG Maker MZ/MV 游戏转换成 JoiPlay 兼容构建、压缩、测试、打包 —
用本工具库的 `pipeline.py` 命令行。

游戏特定特征（引擎+特征案例、体量、坑）**不写进本文件**，一律记录在
本地 `docs/table/<Game>/notes.md`（gitignored，不入库，仅 owner 维护）。

---

## 1. 环境要求

- Python 3.10+（命令里直接用 `python`）。
- ffmpeg / ffprobe（含 libvorbis）用于音频探测与重编码。
- 7-Zip-Zstandard 用于 `-m0=zstd` 压缩包（普通 7-Zip 不支持 zstd）。
- ripgrep（`rg`）用于快速内容搜索（如预扫插件）。
- PowerShell 5.1（无 `?.`、无 `&&`；用 `;` / `if ($?)`）。
- **工具解析（2026-08 重设，无需手工配置）**：所有外部程序由
  `rpgmaker/config.py` 的 `TOOLS` 表 + `resolve_tool()` 统一解析，顺序为
  **环境变量 → 本地配置覆盖（可选）→ 自动探测常见安装位置 → PATH**。
  探测覆盖 WinGet Packages / Scoop / Chocolatey / `Program Files`
  （`7-Zip*`、`Git`、`nodejs`）、各发行版 nvm 目录、POSIX 的
  `/usr/bin`、`/opt`、`~/.local/bin` 与项目内 `docs/table/3rd/`。
  新增一个程序 = 在 `TOOLS` 里加一条，不需要改其他文件。
- **本机环境配置是「可选覆盖层」**：本地私有文件
  `docs/table/env_config.json`（gitignored，不入库）**只用于覆盖**
  探测结果——写交付目录（成品游戏 / 压缩包 / 系统临时文件夹 / Windows
  侧临时目录）、工具路径、venv。文件不存在也能跑（探测 + 内置默认值
  接管），`pipeline.py doctor` / `doctor --json` 会打印每个程序实际
  解析到的路径与来源（`env` / `config` / `probe` / `path`）。
  `GT_NO_PROBE=1` 可关闭探测（锁定环境/CI）。**路径只存一份（原生
  形式）**：Windows 侧资源写 `D:/..`/`C:/..`，WSL 侧写 `/tmp/..`；代码
  按平台转换（`localize()`），绝不重复写同一路径。配置里的工具路径允许
  写 `*` 通配（WinGet 的版本/哈希目录），运行时按自然序取最新。
  Windows 侧临时目录用 `win_temp_dir()`（Windows 的 `%TEMP%`），**绝不
  放进 `games` / `archives`**。工具安装/下载由 owner 执行（如系统包
  管理器、`3rd/` 内二进制）。
- **工作流（2026-08 定案）**：源压缩包在存储侧（Windows），解压/处理/
  压缩在 WSL 侧完成；只做必要的跨系统搬运。**CRITICAL（MUST）——处理
  文件必须用「文件所在系统」的原生应用**：Windows 侧文件（`C:\`/`D:\`、
  WSL 里的 `/mnt/*`）一律用 Windows 侧应用处理（Windows `7z.exe`、
  `python.exe`、PowerShell，从 WSL 经 `powershell.exe` 调用、路径用
  Windows 格式）；WSL 侧文件（`/tmp` 等）才用 WSL 内工具。**禁止 WSL
  内 7zz 解压/压缩 Windows 侧文件，禁止 WSL 内 python 脚本直接操作
  Windows 侧文件** —— 曾因此发生电脑花屏事故（2026-08）。跨系统只
  搬运单个压缩包：
  1. 开工前先检查系统临时文件夹（`deliverables.temp`，WSL 侧）：已有该
     游戏的工作副本 → 直接基于它继续，不重复解压/复制；
  2. 没有 → 把源压缩包（`deliverables.archives`，Windows 侧）**单个文件
     复制**到系统临时文件夹，再在 WSL 侧解压；
  3. 在 WSL 侧处理（流水线/翻译等）；
  4. 收尾用 `pipeline.py deliver <成品目录>`：先在 WSL 侧压缩成本地 7z，
     再把压缩包**单个文件复制**到压缩包目录（`deliverables.archives`，
     覆盖旧包——通常就是源压缩包）；
  5. 删除成品目录（`deliverables.games`，Windows 侧）同名旧文件夹 + 从
     压缩包解压到成品目录：**必须用 Windows 侧工具完成**（经
     `powershell.exe` 调 Windows `7z.exe` / `Remove-Item`）；WSL 下
     `deliver` 的最后解压会用 WSL 内 7z 处理 Windows 侧文件（被禁），
     该步改由 Windows 侧命令执行。跨系统只搬运单个压缩包，避免大量
     小文件走 9P。

## 2. 一键流水线

整个转换是 `build → decrypt → audio → clean → verify`，然后**测** —
`serve --test` — 最后 `deliver` 写回存储侧（本地压缩 → 压缩包复制到
压缩包目录 → 解压到成品目录）。`decrypt` 只在 RPG Maker MZ/MV
且 **easy** 加密时是默认步骤；复杂/自定义加密游戏上它不改任何东西
（见 §4）。如果某步不会改变最终构建，跳过它。

```powershell
$tk  = "<本工具库路径>"                 # 如本仓库目录
$src = "C:\path\to\game"                 # 原版游戏目录 — 绝不修改
$out = "$env:LOCALAPPDATA\Temp\opencode\game"   # Temp 工作目录（之后可删）

python $tk\pipeline.py build   $src -o $out
python $tk\pipeline.py decrypt $out          # 仅 RPGM + easy 加密；否则跳过
python $tk\pipeline.py audio   $out          # 探测 + 重编码；收益最大
python $tk\pipeline.py clean   $out          # 垃圾文件 / 未用字体 / 未用图块
python $tk\pipeline.py verify  $out --source $src   # PNG 签名、JSON、音频引用、标志位
python $tk\pipeline.py serve   $out --test   # 关键文件 HTTP 冒烟测试
python $tk\pipeline.py compress $out -o "C:\path\to\deliverables\game.7z"
python $tk\pipeline.py deliver $out          # 写回存储侧（见 §6a）
```

`build`、`decrypt`、`audio` 在 asyncio + 线程池下并行（每步 `--workers N`，
默认 6/8/4）。`verify --source <原版>` 对照原版检查缺失音频引用：原版也缺
的是既有源怪癖 → 只警告不算失败 — 只有转换造成的丢失才失败。

`serve --test` 启动本地 HTTP 服务器，抓取 `index.html`、`js/main.js`、
`data/System.json`、一首 BGM、一张 CG，确认全部 200 后退出。压缩前在
浏览器里通过 HTTP 打开游戏 PC 试玩。**JoiPlay 本身才是真正的手机测试**
— 见 §7。

### 文件放哪（强制布局）

- **工作/解压文件放系统临时文件夹 — 绝不放原位。** 流水线绝不在原版游戏
  目录里或旁边解压/构建。工作副本在系统临时文件夹（如 Windows 的 `Temp`、
  Linux 的 `/tmp`；本机具体路径用 `python pipeline.py doctor` 看
  `temp_dir` 那一行），压缩包做完即可删除。
- **成品放专门交付目录，与其他游戏一致。** 最终交付物 — JoiPlay 目录
  `<Game>\` 与压缩包 `<Game>.7z` — 放本机交付目录，命名与其他转换过的
  游戏完全一致。候选顺序：环境变量（`GAMES_DIR`/`ARCHIVES_DIR`）→ 本地
  配置 `deliverables.games`/`archives` → **探测**已有惯例目录（先看工作区
  根，即本工具库的**同级目录**下的 `Games`/`GamesCompress`，再看各盘符根
  与家目录）→ 内置默认（同样是工作区根下的 `Games`/`GamesCompress`，按需
  创建）；用 `doctor` 确认实际落到哪里。写回用 `deliver`（§6）：压缩 →
  压缩包复制到压缩包目录 → 删除成品目录旧文件夹 → 解压到成品目录。原版
  游戏保持不动。
- **手机贴图限制（单一构建策略，2026-08 定案）。** Android
  WebView/PixiJS 把 WebGL 贴图限制在**每边 4096 像素**；任何超过 4096
  的 PNG（通常是竖版立绘）在手机上渲染成**黑块**，PC
  浏览器正常。约定：
  - **不再分高清/低清两套构建**，每个游戏只交付一个构建
    `<Game>` / `<Game>.7z`。
  - 构建内存在超过 4096 的 PNG 时，用 `tools/downscale_images.py
    <web_root>`（读 IHDR 头字节 16-23 预检，`--dry-run` 先看报告）就地
    缩放到 ≤4096（保持宽高比 + alpha，PNG），保证 Android 正常显示。
  - 大多数游戏没有超限图，跳过此步即可。
  - 曾试行运行时检测贴图上限并即时缩放（插件方案）以省去缩放步骤 —
    维护成本高于收益，已放弃，一律构建期缩放。

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

## 6. 打包（7z-zstd）与写回存储侧 — 最后一步

```powershell
python $tk\pipeline.py compress $out -o "C:\path\to\deliverables\game.7z"
```

运行 `7z a -t7z -m0=zstd -mx=15 -mmt=on <archive> <folder>` 再 `7z t`
确认 "Everything is Ok"。目标路径已有 `.7z` 时**先删** — `7z a` 是追加，
压在旧包上会双倍（旧 + 新条目）。**试玩之后再运行。**

写回 Windows 存储侧（WSL 下跨文件系统递归拷贝大量小文件很慢）用
`deliver` 一步完成：

```powershell
python $tk\pipeline.py deliver $out
```

它按解析出的交付目录执行（环境变量/本地配置/探测/默认，见 §1；跨系统只
搬运单个压缩包）：

1. 在平台内（临时目录）把成品压缩成 `<Game>.7z`（本地文件系统，快）；
2. 把压缩包**复制到压缩包目录**（`deliverables.archives`），覆盖旧包 —
   通常就是源压缩包；
3. 若成品目录（`deliverables.games`）已有同名 `<Game>\` 文件夹，**先删除**；
4. 再从压缩包目录的 7z **解压到成品目录**（解压只读一个文件 +
   顺序写小文件，比整棵树跨系统拷贝快得多）。

**WSL 下（CRITICAL，MUST）**：上面第 3/4 步处理的是 **Windows 侧文件**，
必须由 **Windows 侧工具**完成——不能靠 WSL 内 7z 操作 `/mnt/*` 文件
（WSL 内 python 的 `shutil.rmtree` 删 Windows 侧目录同样被禁）。
`rpgmaker/deliver.py` 已内置**自动桥接**：WSL 下对 `/mnt/*` 的删除与解压
自动改用 Windows 7z.exe / PowerShell `Remove-Item`（经 `powershell.exe`
调用，路径自动转 Windows 格式），压缩与压缩包复制照常走 WSL 侧；仅当
Windows 7z（由 `win_7z()` 解析：`SEVENZ_WIN` 环境变量 → 本地配置
`tools.win32.7z` → 探测 `Program Files`/`Programs` 下的 `7-Zip*`）缺失、
或 archive 与 dest 跨两侧混用时才拒绝。手动等价命令（路径用 Windows
格式）供参考：

```powershell
powershell.exe -NoProfile -Command "Remove-Item -Recurse -Force -LiteralPath '<games_dir>\<Game>'; & '<win7z>' x -y '-o<games_dir>' '<archives_dir>\<Game>.7z' '<Game>'"
```

（`<games_dir>`/`<archives_dir>`/`<win7z>` 用 `pipeline.py doctor` 打印的
实际值；`<Game>` 为成品目录名，与压缩包内根目录名一致。）

完成后 Temp 工作目录即可删除。

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
- 然后 `deliver`（本地压缩 → 复制压缩包到压缩包目录覆盖旧包 → 删除
  成品目录旧文件夹 → 解压到成品目录；含完整性测试）。

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
  `docs/experience-audio-clean.md` §6）。`data/` 里没有调用它的插件命令
  就删文件 + `plugins.js` 条目。
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
  `translate_rpgmaker.py --trs` 重新应用（或 `detect_trs` 自动检测）。
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
    `tools/translate_rpgmaker.py <build> <out> --trs <title>.json` 烘焙
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
- 原版游戏目录保持不动；只在系统临时文件夹的工作副本里操作（本机具体
  路径看 `pipeline.py doctor` 的 `temp_dir` 行）。
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
  `translate_rpgmaker.py`）还是 MTool 运行时字典（→ 静态 subagent 工作流，
  `docs/translation.md`）。
- 流水线后应用翻译：`translate_rpgmaker.py <built> <new>`（兼容静态字典）
  或 `bake_translation.py <built> <new> --trs translated.json --glossary
  glossary.json`（静态 subagent 工作流）会拷贝**已解密、已压缩**的构建、
  把字典烘焙进 `data/*.json`、应用**标准字体策略** — 无需重跑
  `build`/`audio`/`clean`。bake 现在：低于 `--min-coverage` 50% 拒绝
  （→ 改全量翻译，`--force` 覆盖）、自动剔除 identity 条目、
  自动检查 `<TE:>`/`<namePop:>` 引用对照事件名、自动在输出根归档
  `translation_kv.json`。然后重跑 `verify --source <原版>`、`serve
  --test`、**新端口** HTTP 试玩（同端口 origin 共享 localStorage）、
  再 `deliver`（写回存储侧：压缩 → 压缩包目录 → 成品目录）。注意：它用 `indent=2` 重写所有 `data/*.json`
  （无害），且需要手机上有 CJK 字体（回退列出系统字体；译文显示方块就
  打包一个）。

### 标准字体策略（owner 偏好, 2026-08 定案）

中文/拉丁 → 打包的中文字体（`--cjk-font` 指定）；**日文 → 打包的日文
fallback 字体**（`--jp-font` 指定；未配置时回退到游戏原始字体）。字体
解析顺序（环境无关，2026-08 更新）：`CJK_FONT_PATH` / `JP_FONT_PATH`
环境变量 → 本地 `docs/table/local_font_path.txt` 首/二行（支持相对
`docs/table/` 的路径）→ **自动发现 `docs/table/fonts/`**（`GlowSansSC*`
作中文、`GlowSansJ*` 作日文回退）→ 无字体时策略整体跳过。字体偏好
只存在本地 `docs/table/`（gitignored），仓库代码不含字体名。实现
（`translate_rpgmaker.py apply_font_policy`，幂等可重跑）：

- **MZ**（有 `js/rmmz_managers.js`）：`System.json`
  `advanced.mainFontFilename` 置空（引擎不再注册全范围 FontFace，杜绝
  FontFace 与 CSS @font-face 优先级歧义），`css/game.css` 的
  `rmmz-mainfont` 按 unicode-range 拆两张脸 — `U+3000-30FF, U+FF00-FFEF`
  （假名 + 日文标点）→ 日文 fallback 字体；其余（汉字/拉丁）→ 中文字体。
- **MV**（无 `rmmz_managers.js`）：`fonts/gamefont.css` 按 unicode-range
  拆分（假名/日文标点走日文 fallback 字体或原字体，汉字走中文字体）+
  `css/game.css` 追加 GameFont 回退块。MV 的 GameFont/YaHei 块**绝不
  追加到 MZ**（会覆盖 rmmz-mainfont 族，全游戏渲染成系统雅黑 — 已踩过）。
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
