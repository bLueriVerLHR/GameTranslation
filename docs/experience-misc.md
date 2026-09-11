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

## 3. `process`/`require('fs')` 插件破坏浏览器/JoiPlay 构建

任何在加载或标题画面读 `process.mainModule.filename` 或 `require('fs')`
的插件在纯浏览器里抛异常，JoiPlay 下可能失败。真实命中：一个剧情/对话
插件（261 个地图文件在用 — 关键）和一个 DLC "APPLY PATCH" 标题按钮插件。
补丁 = `process` 未定义时回退 `window.location.pathname`，或 `process`
缺失时提前 `return false`。`rg` 每个构建的 `js/plugins/*.js` 里的
`process\.`，只 patch 可达路径（标题画面、加载时 IIFE），不碰 F 键背后的
开发工具函数。

## 4. MoviePicture 新浏览器白屏 = 自动播放策略

origin 无自动播放带声音权限、播放不在用户激活内时，`<video>.play()`
promise 以 `NotAllowedError` 拒绝。Chrome 正常（早期会话的 site
engagement），Edge 不行。修复：`Bitmap_Video.prototype.play` 在 catch
里 `muted=true` 重试再取消静音；`_createVideo` 设 `autoplay=false`
（浏览器自己的自动播放尝试不可 catch，会记未处理 rejection）。在大 MZ
repack 会话中该修复已应用（8 部电影随包）。

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
