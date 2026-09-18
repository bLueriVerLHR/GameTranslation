# 经验库 · 音频 / 清理 / 打包

> **先读这篇**：本文收录「音频重编码、clean 清理、打包 / 交付、repack 垃圾
> 与广告清理」相关的实战经验（由原单文件经验库拆分而来，原 §0-垃圾/命名、
> §2-build/audio/clean、§3、§5、§7.6、§9、§9-大小写、§12.1）。
> 其他主题经验见：
> [解密 / 解包 / Repacker 识别](experience-decrypt.md) ·
> [翻译](experience-translation.md) ·
> [Tyrano](experience-tyrano.md) ·
> [其他 / 杂项](experience-misc.md) ·
> [经验库索引](experience.md)。

## 1. Repacker 垃圾文件与目录命名

- repacker 有时留垃圾：ASCII 广告文件（`data/setting.json`，非合法
  JSON — 删）、`.url` 快捷方式、`Tool/` 目录、根 `翻译文件.json`
  （zh_CN 翻译）、`赠品/`（礼物）目录（用户想**保留**在构建里）。
- 目录命名 `<官方名>`（单一构建，无 `_LowRes` 变体 — 2026-08 起统一为
  构建期缩放策略）；剥掉**译者名**（有些 repacker 附加自己的名号），
  `System.json.gameTitle` 为空时设官方标题。

会话规模参考（一个大 MZ NW.js MTool repack，约 5.4 GB → 3.52 GB，双卷
密码 RAR）：**无加密**（System.json 无标志/密钥）→ `decrypt` 跳过；
音频 −427 MB（重编码 5614 文件），clean −26 MB，74 个未用图块。无超过
4096 的 PNG → 不做缩放（`tools/downscale_images.py`）。

## 2. 工具补丁（已应用）

- **`build.py`**：拷贝**所有根文件**（不只 `index.html`），`NWJS_RUNTIME`
  条目除外。有些游戏在网页根放必需数据（如换装数据 JSON）— 没有这个
  它们静默消失。
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
- **`media.py`（2026-09）**：PyAV 开容器一律带
  `metadata_errors="replace"`。有些日本同人游戏的 Ogg 用 **Shift-JIS 写
  Vorbis 注释**，PyAV 按 UTF-8 解码标记值会抛 `UnicodeDecodeError` —
  完全正常的音频被当成坏文件（probe 报 error、`verify --decode` 报
  3/365 错误，音频步骤也只能 keep 不动）。标记里只用得上
  LOOPSTART/LOOPLENGTH（ASCII），替换不可解码字节是安全的；修后
  `verify --decode` 0/365。单测用真 Ogg 固件改写注释值 + 重算页 CRC
  复现（`tests/test_media.py`）。

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

## 4. 长文件名（Android 解压失败）

有些 SE 把整句对话嵌在文件名里（一个 333 字节的 `.rpgmvo` 引用了整句）—
超过 255 字节组件上限，手机解压应用失败。

- 这些语音文件是**孤儿**（`data/js` 里没有任何引用）→ 安全改短 ASCII
  名或删除。
- 构建后总是扫 >200 字节的 basename：
  `[System.Text.Encoding]::UTF8.GetByteCount($_.Name)`。

## 5. 从不随包的默认 MV 音频名无害

`System.json` 在游戏换自定义音效后仍列原装名（`Attack3`、`Collapse1..4`、
`Equip1`、`Run`、`Ship1/2/3`、`Victory1`）；verify 报"缺失"但它们从未
随包。MV 静默播放缺失 SE。不是 bug。

## 6. Repacker 广告壳插件

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

## 7. 文件大小写坑（2026-08，MZ repack）

- **症状**：试玩报 `Failed to load img/system/Window.png`，但文件明明在
  （小写 `window.png`）。Windows 开发机上一切正常。
- **根因**：MZ 引擎固定 `ImageManager.loadSystem("Window")` 加载大写
  `Window.png`；repacker 在 Windows（NTFS 大小写不敏感）打包时把文件
  打成小写 `window.png`。Windows 上跑没事，**Linux/Android 文件系统
  大小写敏感 → 加载失败**。
- **排查**：`rg -n 'loadSystem\\("([^"]+)"\\)' js/*.js` 列引擎引用，
  与 `img/system/` 实际文件名逐字比对。
- **修复**：补正确大小写的副本（`cp window.png Window.png`）；**删除
  错误大小写的文件**（只留引擎引用的大小写），否则归档内同名双文件
  在 Windows 解压时（NTFS 不敏感）互相覆盖，交付目录残留错误大小写。
- **预防**：打包前对 `img/`、`audio/` 与引擎引用/数据引用做
  大小写敏感的存在性检查；交付后在**归档内** `7zz l | grep -i` 复查
  同名文件。

## 8. 压缩包与 repack 垃圾（补翻会话，两款各一坑）

- **RAR5 AES 密码按推广文件识别：** 一款密码不在本地表，但包里带
  推广 `.txt` — owner 指出该渠道固定密码，已补进
  `docs/table/passwords.md`（此处不写具体值）。压缩包密码常与推广
  文件名绑定，遇到陌生密码先看根目录推广文件问 owner。
- **内嵌 `cn.rar` 不是汉化包：** 另一款包内嵌 `cn.rar`，名字像汉化包，
  实际是推广包（内含"卸载类"exe 推广，密码同发布渠道，见本地
  密码表）。先 `7z l -p<pass>` 看内容再决定删不删 — 别被文件名误导。
- **MTool 注入残留同上：** `与工具一同启动.bat`/`从游戏中移除工具文件.bat`/
  `Tool/`/根 `<title>.json` 字典 — `build` 不拷贝根级文件，天然不进
  JoiPlay 构建；但字典要留作 prefill 源（从源目录读，不拷进构建）。
- **广告文件：** 根目录推广文本（广告/推广渠道类 `.txt`）、推广 `.url`
  均在网页根外，build 自动排除；渠道说明 `.txt` 一并留在源目录，不进
  构建即可，无需手工删。

## 9. 扩展名不可信：`.mp3` 里装着 PCM

一个 repack 的 `data/sound` 下 68 个 `.mp3` 里有 **26 个实际是 PCM/WAV**
（PyAV 探到 `pcm_s16le` ×22 / `pcm_f32le` ×3 / `pcm_s24le` ×1），文件名
却一律是 `.mp3`——典型的自制音效包直接改扩展名。

- **按内容转码**：ffmpeg / PyAV 按容器嗅探，把 `.mp3` 转 ogg 完全正常
  （转完反而成了诚实的 `.ogg`），而且 PCM 源转 Vorbis 后**体积大减**
  （实测 8.2 MB → 0.35 MB）。不要按扩展名跳过，也不要“修复”文件名——
  引用里写的就是那个名字。
- **探真实编码时别把“解码器名”当“格式不符”**：PyAV 对 MP3 报的是
  `mp3float` / `mp3`（取决于构建），不是 `mp3`。把 `mp3float` 当成
  “扩展名与内容不符”会得到假报告；判据是“这个解码器对不对得上这个
  容器”，不是字符串相等。
- 同类坑在视频/图片上也存在（`.png` 装 JPEG 等）；抽查用**内容**，
  随机采样而不是定点看同一个已知正确的文件。

## 10. `m4a` 不要顺手重编码（先量编解码器支持）

TyranoScript 游戏的 `data/sound` 里可能混着 `.m4a`（AAC-LC ×26），而
音频步骤只处理 mp3。**不要想当然地扩成“mp3 和 m4a 都转”**——先在
目标运行环境里量一下：

- 引擎用的是 **Howler 2.2.3**，它对 `m4a` 的判定是
  `canPlayType("audio/x-m4a;") || canPlayType("audio/m4a;") ||
  canPlayType("audio/aac;")`；
- 在 Chromium（桌面 / Android WebView 同代码）里实测：`audio/x-m4a;` →
  `"maybe"`、`audio/aac;` → `"probably"` ⇒ 判定为真，**m4a 能播**。
- 结论：保留 m4a、只转 mp3 是最小改动且正确；重编码 AAC→Vorbis 是
  有损代际损失，白做。

判据可以一行量完（浏览器里 `new Audio().canPlayType(...)`），比猜快；
换引擎版本时重测一次即可。

