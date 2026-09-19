# 经验库 · 其他 / 杂项

> **先读这篇**：本文收录「服务 / 测试卫生、CG 解锁、浏览器 / JoiPlay 运行
> 兼容、工具补丁」等不归入前四类主题的实战经验（由原单文件经验库拆分
> 而来，原 §2-verify/serve、§6、§7.2、§7.3、§7.4、§8、§11-FOSSIL、
> §12.2、§13.4、§13.5）。其他主题经验见：
> [解密 / 解包 / Repacker 识别](experience-decrypt.md) ·
> [音频 / 清理 / 打包](experience-audio-clean.md) ·
> [翻译](experience-translation.md) ·
> [Tyrano](experience-tyrano.md) ·
> [经验库索引](experience.md)。

## 1. 工具补丁（已应用）

- **`verify.py`**：关键文件检查接受 MV 的 `js/rpg_core.js`（原来硬编码
  `rmmz_core.js`）。
- **`serve.py`**：`Cache-Control: no-store`，测试时过期缓存的 404 不会
  遮蔽刚加入的资源。

## 2. CG 解锁（"方案 2" — 烘焙进构建）

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

## 3. 插件破坏浏览器/JoiPlay 构建（加载期崩 / 启动门）

任何在加载或标题画面读 `process.mainModule.filename` 或 `require('fs')`
的插件在纯浏览器里抛异常，JoiPlay 下可能失败。真实命中：一个剧情/对话
插件（261 个地图文件在用 — 关键）和一个 DLC "APPLY PATCH" 标题按钮插件。
补丁 = `process` 未定义时回退 `window.location.pathname`，或 `process`
缺失时提前 `return false`。`rg` 每个构建的 `js/plugins/*.js` 里的
`process\.`，只 patch 可达路径（标题画面、加载时 IIFE），不碰 F 键背后的
开发工具函数。

### 3.1 模块顶层连环崩：一个插件的异常会带走另一个插件（2026-09）

同一种坑的**静默版本**，也是最难靠检查发现的一种：

- 一个已启用插件在**模块顶层**（列 0，加载即执行）读
  `process.versions['node-webkit']` → 浏览器/JoiPlay 里 `ReferenceError`，
  该行之后的顶层代码全部不执行。**游戏照常进标题、进地图**，所以
  `verify` 全绿、HTTP 冒烟全 200、音频全解码通过 —— 只有控制台能看到。
- 真正的损失在**第二个插件**上：第一个插件正是创建
  `DataManager._testExceptions` 的地方，而 `SRD_HUDMaker` 在自己顶层做
  `DataManager._testExceptions.push(...)` → 它也跟着死，于是
  `MapHUD/BattleHUD/Windows/Notes.json` 没进 `DataManager._databaseFiles`，
  **游戏内 HUD 静默消失**（PC 上原版 NW.js 有 `process`，所以只在转换后的
  构建/手机上出现）。
- 本次实测：修复前 `$dataMapHUD` 0 条，修复后 32 条；地图场景里
  HUD 正常显示。
- **工具化**：`pipeline.py compat`（见 [workflow.md](workflow.md) §4）
  内置这类形态的定点维修（一行进一行出、幂等、保留原编码/行尾）并对已
  启用插件做模块顶层 `process`/`require(` 预扫；`verify` 会把未处理项
  WARNING 报一次。**先跑 `compat` 再手改** —— 手工只 patch「看得见的那
  一处」，很容易漏掉依赖同一变量的第二个插件。
- **列 0 启发式在压缩成单行的插件上会假阳性（2026-09 实测）**：商业插件
  套件（VisuMZ/VisuStella 这类）把整个文件混淆压成**一行**，于是「列 0
  = 模块顶层」对整行都成立，`compat`/`verify` 会把函数体内部的
  `require('fs')`、`process.platform` 报成「load-time NW.js usage」。
  判定方法：把那行里命中的片段取出来看是不是在 `function(...){...}` 或
  `if (Utils.isOptionValid(...))` 之内 —— 函数体内（尤其带
  `isOptionValid` 守卫的）都是运行到那个功能才执行，**不需要**改；
  一个已启用插件只报 1~3 处且全部在函数体内时，可以放心当噪音处理
  （不要为了消警告去改混淆代码）。
- 判据仍然只是启发式（列 0 = 模块顶层）：缩进在函数体里的 `process` 用法
  （如 `if(!Utils.isNwjs()) return;` 之后）**不需要**改，`compat` 也不会碰。

### 3.2 Steam 版构建的启动门：卡在标题之前（2026-09）

- **特征**：游戏根目录带 NW.js 运行时，`www/lib/` 下有 `greenworks*.node`
  与 `steam_api*.dll`（Steam 集成 SDK），`js/plugins.js` 里已启用 Steam
  集成插件。转换后浏览器/JoiPlay **到不了标题画面**，页面上是
  “Steam failed to initialize.”（或引擎自绘的错误框）。
- **根因**：Steam 发行版在闪屏 → 标题之间做一次所有权校验
  `if (!X.isSubscribedApp(<appid>)) throw ...`，而它写在**闪屏插件的函数体
  里**（不是模块顶层）—— 所以 `compat` 原来的列 0 预扫看不到它，`verify`
  也不会报。转换后既没有 NW.js 运行时也没有 Steam，那个调用是桩函数、
  只能返回 false → 直接抛错。
- **工具化**：`compat` 的 `steam-ownership-gate` 规则（`SCOPE_ANY`，任意
  插件）改写成「仅当 Steam 真的在运行时才校验」，桌面 Steam 版语义不变。
  定位手法：`rg -n 'isSubscribedApp|Steam failed' js/plugins/*.js`，再按栈帧
  找到抛错那一行。
- **`www/lib/` 不用删**：那几 MB 的 Steam SDK 只在 `Utils.isNwjs()` 为真时被
  `require`，浏览器下永不加载；删了也无害，但没必要为此动插件资源树。
- 同类问题：某些构建把**成就/云存档**当启动前置；只要它也在启动路径上，
  同样会用桩函数的值做分支，症状一样（白屏/卡住），处理方式相同。

## 4. MoviePicture 新浏览器白屏 = 自动播放策略

origin 无自动播放带声音权限、播放不在用户激活内时，`<video>.play()`
promise 以 `NotAllowedError` 拒绝。Chrome 正常（早期会话的 site
engagement），Edge 不行。修复：`Bitmap_Video.prototype.play` 在 catch
里 `muted=true` 重试再取消静音；`_createVideo` 设 `autoplay=false`
（浏览器自己的自动播放尝试不可 catch，会记未处理 rejection）。在大 MZ
repack 会话中该修复已应用（8 部电影随包）。

**MZ 侧仍无工具，是手工补丁（2026-09 提醒）**：Tyrano 有
`fix-autoplay`，MZ 只在会话里手改过 `js/plugins/MoviePicture.js`。
判据：`js/plugins.js` 里 `MoviePicture` 为 `status: true` **且**
`data/` 里有插件指令引用 `Movies/` 下的影片名 —— 两者都成立才需要改
（改了没用到无害，没改到用到就是白屏）。改完用 `jssyntax.parse_errors()`
确认语法仍然干净（插件是别人写的，手改易碰坏配套逻辑）。

（TyranoScript 的 `[bgmovie]` 有同样问题，见 [Tyrano](experience-tyrano.md)
§1。）

## 5. 过期 per-origin Web Storage

`127.0.0.1:8100` 是所有游戏共享的一个 origin；localStorage/IndexedDB
（存档、插件偏好）在 Ctrl+Shift+R 后存活并在游戏间泄漏。每款试玩用
**新端口**。见 workflow.md §8。

## 6. 服务/测试卫生

- **总在固定端口服务，一次一款游戏。** 杀掉残留服务器（复用端口上的
  残留服务器在服务改名/旧目录，返回像游戏 bug 的 404）。
- `serve --test` 曾有 bug：空生成器上的 `all(...)` 返回 True，所有请求
  都失败也打印 "ALL 200 OK"。已在 `serve.py` 修 — 任何非 200 或失败请求
  现在都失败测试。拿不准仍用 `Invoke-WebRequest` 直接验真实 URL。
- no-cache 处理器意味着加资源后普通刷新即可。
- 工具路径已不再写在文档/代码里：所有外部程序由 `rpgmaker/config.py` 的
  `TOOLS` 表解析（环境变量 → 本地配置 → 探测 → PATH）。需要知道某个程序
  实际在哪里时跑 `python pipeline.py doctor`（列出每个程序解析到的路径与
  来源），不靠猜、也不靠搜盘。
- PowerShell 坑：`Start-Process -ArgumentList` 弄坏带空格参数；传单个
  预引号字符串（`'serve "' + $folder + '" -p 8100'`）并含脚本路径。

### 6.1 长驻 serve 与 PowerShell 坑（补充）

- **`Start-Process -ArgumentList` 对含 `～`（全角波浪号）的路径失效：**
  进程启动即退（无日志）。同一命令换成
  `cmd /c start /b python <pipeline> serve "<path>" -p <port>` 正常。
  另一款路径无此字符则 `Start-Process` 正常 — 症状不固定，启动失败后
  先在前台跑一次看是否端口冲突，再换 `cmd /c start /b`。
- **测试后服务器必须按端口杀干净：**
  `Get-NetTCPConnection -State Listen | Where LocalPort -in 8101,8102`
  再 `Stop-Process`，防复用端口残留服务器服务旧目录（老坑重犯）。
- **`rpgmaker/serve.py` 的 `start_server()` 用 daemon 线程，主进程一退
  线程即死** — 后台 `nohup python -c "start_server(...)"` 起来的是个空壳，
  端口根本没监听。必须用阻塞的 `serve()`（serve_forever）做常驻。
- 绑 `0.0.0.0` 时 WSL 局域网地址（`ip -4 addr` 的 eth1）可直连；本机
  curl 被 7890 代理截获（502）是代理行为，加 `--noproxy '*'` 验证。

## 7. FOSSIL（MV→MZ 互操作）入口必须跳过 setup 块

浏览器/JoiPlay 里 FOSSIL 的插件模式 setup（作为普通插件用原装
`js/main.js` 入口加载）XHR 加载 index.html 并调 `writeNewIndexFile` →
`require("fs")` → 浏览器里 `Uncaught ReferenceError: require is not
defined`，游戏静默运行**无** MV 兼容注入（战斗插件降级）。修复 = 作者
文档化的 "skip setup" 路径：把 `index.html` 指向 `js/plugins/FOSSIL.js`
作为唯一入口脚本（替换 `js/main.js` 并保留 `js/` 前缀 — FOSSIL 自己的
`writeNewIndexFile` 做 `replace("main.js", "plugins/FOSSIL.js")`），于是
`typeof(scriptUrls) == "undefined"`、FOSSIL 接管 main（内联脚本定义
`scriptUrls` 自身、加载核心脚本、patch PluginManager）。无 fs/重定向。
控制台显示 `FOSSIL is now running as main.` 修复后重新打包。
FOSSIL/fix-load-failed 的 `process` 路径是 NW.js-only 死分支，不动。

## 8. config 层两个交付阻塞 bug（已修复 + 单测）

- `deliverables.temp` 改为嵌套 `{persist, tmpfs, win32}` 后，
  `temp_dir()`/`win_temp_dir()` 把 dict 传给 re.sub 崩溃。
  修复：`_deliverable` 跳过非标量，新增 `_temp_dir_cfg()` 按平台取子键
  （WSL→persist，Windows→win32），兼容旧平铺格式。
- `tools.win32.*` 配置含 `%ProgramFiles%` 等 WSL 无法展开的 token 时，
  `_win_tool` 拿到非空但不可用的路径直接返回 None（默认路径从不尝试）。
  修复：解析失败回退默认路径。
- 两个 bug 都让 `deliver` 直接崩 — 集成测试 `test_integration.py` 在
  修复前是红着的（Python 3.14 下同样复现），修完 375 测试全绿。

## 10. 再去掉三个外部程序（2026-09）

原则不变（一个能力一个入口 + 用现成包），这轮把剩下能进程内做的都做了；
每一条都先量后改，不靠印象。

### 10.1 视频转码 → PyAV（VP9 + Opus）

`tools/transcode_video.py` 原调 ffmpeg CLI（`-c:v libvpx-vp9 -crf N -b:v 0
-row-mt 1 -cpu-used N -deadline good -c:a libopus -b:a 96k -ac 2`）。PyAV 的
wheel **有** libvpx-vp9 与 libopus，所以整段可以进程内。在真实样本上与 CLI
输出对比（同一组参数）：

| 样本 | 帧数/末时间戳 | 音频采样数 | 亮度 PSNR vs 原片 |
|---|---|---|---|
| 100 MB / 106 s | 3188 / 106.340 s（两者相同） | 完全相同 | CLI 40.6 / PyAV 40.9 dB |
| 7.8 MB / 7.9 s | 224 / 7.441 s（相同） | 完全相同 | CLI 42.0 / PyAV 41.9 dB |
| 10.5 MB / 10 s | 300 / 9.977 s（相同） | 完全相同 | CLI 42.7 / PyAV 42.4 dB |

帧数/时间戳/音频采样数完全一致，PSNR 差 ±0.3 dB。**已知取舍：同一参数下
视频码流大约 6%**（7.9 s 样本上 1651 kB vs 1560 kB；试过的 libvpx 选项组合
都落在那里，只有 `cpu-used 0` 更小但要慢约 3 倍）。要体积就降 `--crf` 或
`cpu_used`。

踩坑（都记在 `rpgmaker/media.py` 的文档串里）：

- **重采样后的音频帧仍带着源时间基**（毫秒），直接丢给 Opus 编码器会
  `EINVAL`，或报 `Frame.pts (4464) != expected (0)`；把 `frame.pts` 置 None
  让编码器自己编号（CLI 内建 fifo 做的事）。
- 视频帧的 pts **不用**手动换算：直接传就能与 CLI 输出逐帧对齐（实测）。
- 合成空白帧测不出 CRF 是否生效（大小几乎一样）——要带细节/噪声的源。

### 10.2 app.asar → `asar` 包（去掉 Node.js + npx）

`npx @electron/asar` 需要 Node.js，还可能在冷 cache 时下载包。PyPI 的
`asar`（纯 Python，MIT）实测：**用官方 node 工具打的包（含 `--unpack`
条目）提取结果字节一致**，文件表也一致（node CLI 在 Windows 上会输出反斜杠
路径，包返回正斜杠，已归一）。回归固件 `tests/fixtures/tiny_app.asar` 就是
用官方 node 工具打的（933 B），以保证测试读的是**外部产生的真包**。

### 10.3 JS 语法检查 → tree-sitter（去掉 `node --check`）

`tools/check_iscript_js.py` 原来每块写临时 .js 再 `node --check`。改用
`tree-sitter` + `tree-sitter-javascript`（进程内，**不执行**代码）：

- 等价性实测：58 个真实 JS（TyranoScript 运行库，含混淆压缩的）× 4 种
  变体（原样/截断/删括号/插入 `setter(x){…}`）= **225 例判定与 node 完全
  一致**（含故意弄坏的）。判定口径：树中出现任何 ERROR 或缺 token 即视为
  不通过（tree-sitter 是容错解析器，不能只根据顶层错误）。
- 报错文案变了：由 `SyntaxError: …` 变为 `line N:M: unexpected '…'` /
  `missing '…'`（附坏片段），实测对已知回归文件的定位仍然到位。

### 10.4 顺手清掉的死依赖

`ffprobe` 已无任何生产代码调用，于是删掉 `config.find_ffprobe`、`TOOLS`
里的 ffprobe 条目、`tests/fake_tools/ffprobe.py` 与相关的 monkeypatch，
`doctor` 从 13 项变 11 项。**判据：没有任何生产调用者的 finder/工具条目就是
死代码**，不要因为「以后可能用」留着。

## 9. 工具链改用现成包（2026-09 重构）

原则：同一个能力只留一个封装层，且优先用维护中的包（AGENTS.md
「功能优先用现成包」规则表）。

### 9.1 打包：py7zr（唯一入口 `rpgmaker/archive.py`）

create / verify / names / extract 四个函数，同侧工作全部在进程内完成；
`extract()` 直接拒绝 Windows 侧目标（跨系统 CRITICAL 规则，交给
`deliver` 的 7z.exe 桥）。**实测**（265 MB / 3009 文件，zstd level 15）：

| 引擎 | 耗时 | 体积 | 互读 |
|---|---|---|---|
| `7z.exe a -t7z -m0=zstd -mmt=on` | 5.3 s | 251.7 MB | — |
| py7zr（`FILTER_ZSTD`） | **3.1 s** | 251.7 MB | `7z.exe t` 通过（`Method = ZSTD`） |

坑：

- py7zr 把方法名报作 **`ZStandard`**（7z.exe 显示 `ZSTD`）—— 断言时
  必须两种都接受，否则测试假失败。
- py7zr 没有 `-mmt` 对应物（`mp=True` 只影响解包）；实测单进程已快过
  `-mmt=on`，所以 `threads` 参数现在只做兼容。
- 完整性校验用 `testzip()`（逐成员 CRC）：坏档案仍必须 ERROR + 非零退出码
  （曾经只是 INFO 且返回值被丢弃 → 坏档案 exit 0）。

### 9.2 媒体：PyAV（唯一入口 `rpgmaker/media.py`）

`probe()` / `probe_video()` / `decode_ok()` / `has_codec()`，**不再需要
ffprobe**。实测（2 s/44.1 kHz 立体声，libvorbis）：duration 2.002902
(ffprobe) vs 2.0 (PyAV，末包取整)，size/codec/channels/sample_rate 完全一致。

- **真 bug**：旧探测只让 ffprobe 报 `format=...tags`，而
  `LOOPSTART/LOOPLENGTH` 通常是 **stream 级** Vorbis comment（本流水线自己
  的 `-metadata:s:a:0` 就写在那里）→ **重新编码会丢循环点**。PyAV 同时读
  容器与流标签，回归用真 Ogg 固件（`tests/fixtures/sine_loop.ogg`）。
- PyAV 的 wheel **不含 libvorbis**（只有实验性原生 `vorbis` 编码器），
  所以 **Vorbis 编码仍用 ffmpeg CLI**；VP9/Opus 视频编码同理（已验证的
  移动端配方）。这两处保留 CLI 的理由写在模块文档串里。
- 测试不再用假 ffprobe：需要真容器的地方用固件，策略测试直接注入探测结果。

### 9.3 CLI / 进程 / 日志 / 测试

- `rpgmaker/cli.py`：Typer 定义两个应用（RPG Maker / Tyrano），
  `pipeline.py`、`tyrano/pipeline.py` 退化成包装；入口 `gt` / `gt-tyrano`。
  两个入口曾各自抄一遍 serve/compress/deliver 与 `smoke_test`，现已共用。
- `rpgmaker/proctools.py`：外部进程唯一入口（默认 900 s 超时、UTF-8
  `replace`、失败信息带程序名/退出码/输出尾部）；缺程序仍抛
  `FileNotFoundError`（保留 resolver 的安装提示）。
- `rpgmaker/logsetup.py`：唯一日志配置（时间戳 + 等级 + logger 名）；
  **禁止 import 期配置**（会改写整个进程 root logger 并让后续配置静默失效）。
- 测试：`pytest-xdist` 默认并行（1163 用例 27.8 s → 11.2 s）；
  `-p no:xdist` 会与 `addopts = "-n auto"` 冲突，串行请用 `-n 0`。
- Typer 的退出约定：**成功也会走 `SystemExit(0)`**，所以包装函数
  （`cli._run`）把 0 吞掉、非零上抛——测试才能断言「成功返回 / 失败 SystemExit」。
- `pip install -e ".[unity]"` 会顺带装 `attrs`（UnityPy 的依赖）；
  我们自己的代码仍然不用 attrs/pydantic（数据不可信的降级设计）。
