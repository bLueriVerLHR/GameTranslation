# TyranoScript / TyranoBuilder 指南（JoiPlay 构建 + 翻译）

TyranoScript（ティラノスクリプト）/ TyranoBuilder 引擎游戏——HTML5 系
视觉小说引擎，常以 Electron 桌面应用形式发布（游戏本体在
`resources/app.asar` 内），也可直接作为 HTML5 网页运行。**JoiPlay
官方支持 TyranoBuilder / HTML5 游戏**（1.10.065+ 还专门适配了
Electron 目录结构），所以本引擎走 **JoiPlay 可玩构建 + 翻译** 双路线
（不同于 Unity/Wolf/KiriKiri 的"仅翻译"）。

## 1. 引擎识别

- Electron 打包：`<Game>.exe` + `resources/app.asar`（Chromium 系
  pak/dll 在根目录），内部是标准 HTML5 布局（`index.html` + `data/` +
  `tyrano/`）。
- 纯网页发布：直接是 `index.html` + `data/` + `tyrano/`，无 Electron
  外壳。
- 场景脚本在 `data/scenario/*.ks`（UTF-8，TyranoBuilder 编译产物）：
  - 正文在 `[tb_start_text mode=N] ... [_tb_end_text]` 块内；
  - 说话人名行以 `#` 开头（`#つむぎ`），单独 `#` 表示无名字；
  - `text="..."` 属性出现在 glink / tb_ptext_show / p_notify /
    tb_alert_dialog 标签上（按钮、标题、通知）。
- 引擎默认 `mediaFormatDefault=ogg`（Config.tjs 里 `;` 开头才是有效
  配置行，不是注释！），但脚本直接引用 `storage="xxx.mp3"`——音频
  播放按脚本写的扩展名来，**转格式必须同步改脚本引用**。

## 2. 构建（`tyrano/pipeline.py`）

工作目录按惯例放系统临时文件夹（WSL 侧 ext4）；注意 asar 解包后
通常 ≥1.3GB，`/tmp` 若为小容量 tmpfs 要换到大分区工作目录。

```
python3 tyrano/pipeline.py build   <game_dir> -o <work>/build
python3 tyrano/pipeline.py audio   <work>/build          # mp3 → ogg + 改脚本引用
python3 tyrano/pipeline.py clean   <work>/build          # 删 MTool 残留
python3 tyrano/pipeline.py fix-autoplay <work>/build     # [bgmovie] 自动播放补丁（幂等）
python3 tyrano/pipeline.py verify  <work>/build --source <原版解包目录>
python3 tyrano/pipeline.py serve   <work>/build --test   # HTTP 冒烟
python3 tyrano/pipeline.py compress <work>/build -o <archives>/<Game>.7z
python3 tyrano/pipeline.py deliver <work>/build          # 写回存储侧
```

各步骤要点：

- **build**：解包 `resources/app.asar`（用 `npx @electron/asar`，不
  重复造轮子）→ 剥 Electron 运行时（main.js/package.json/node_modules/
  pak/dll/ico）→ `Config.tjs` 里 `configSave=file` 改 `webstorage`
  （浏览器/WebView 存档必须走 localStorage，file 后端依赖 Node fs）。
- **audio**：`data/bgm` + `data/sound` 下所有 mp3 → Ogg Vorbis
  （q3），并**同步重写** scenario 里 `storage=`/`clickse=`/`enterse=`/
  `decidese=`/`cancelse=` 的 `.mp3` → `.ogg`。只有解析得到实际文件的
  引用才重写；dangling 引用保持原样并计数。
- **fix-autoplay**（可选）：用 `[bgmovie]` 的游戏在浏览器/JoiPlay 下被
  自动播放策略拦截（`.play()` 抛 `NotAllowedError`，`wait_bgmovie`
  永久等待 → 标题卡死黑屏）。补丁把 `tyrano/plugins/kag/kag.tag_ext.js`
  里的 `.play()` 调用包上兜底：promise 被拒时挂一次性
  click/touchstart/keydown 监听，用户首次交互后重播。**幂等**：已打
  补丁的文件（含 `_p&&_p.catch` 标记）跳过；没有 `.play()` 调用的
  引擎版本是 no-op。不用 `[bgmovie]` 的游戏可跳过此步。
- **verify --source**：布局（index.html/tyrano/data）、存档后端、
  音频引用完整性（mp3 残留 + dangling）、PNG 4096 上限。`--source`
  指向**解包后未转换**的原始目录：源里本来就缺的引用（制作缺陷）
  降级为不报错——只把转换造成的丢失当回归。
- **serve --test**：HTTP 冒烟（PC 浏览器 file:// 会拦截 .ks 的 ajax
  加载，必须走 HTTP 试玩）。serve/compress/deliver 复用 RPG Maker
  流水线的引擎无关模块。

## 3. 翻译（JP → ZH）

```
python3 tools/build_tyrano_translation.py <work>/build <work> \
    [--entry first.ks]          # 标准工作包（template/kinds/structure/context）
# → gen_translation_shards → 10 并行 subagent（分批追加契约）
# → merge_plain_chunks → merge_translation → translated.json
python3 tools/apply_tyrano_translation.py <work>          # 写回 <work>/patch/
```

提取规则（键 = **去首尾空白的整行**，标签原样保留，只翻日文片段）：

- `[tb_start_text]` 块内：`#名字` 行（说话人名）、文本行
  （`[font color=..]正文[l][r]` 这类整行一个键）。
- 块外：glink / tb_ptext_show / p_notify / tb_alert_dialog 等带
  `text="..."` 的行（`[glink ... text="戻る" ...]` 整行一个键）。
- 不提取：注释（`;`）、空行、单独 `#`、`[position]`/`[layopt]` 等纯
  配置行、括号不平衡的行。
- `name="..."` 属性（`[ptext name="chara_name_area"]`）是元素标识符，
  **不译**。
- 说话人名是共享键（如 `#つむぎ` 出现几百次只占一个键），词表定名
  后一次替换全部生效。
- 编码 UTF-8 写回；保留缩进与行尾。

## 4. 坑（真实游戏验证）

- **asar 解包体积大**：1.3GB 的 asar 解出 ~1.4GB；临时目录要预留
  2.5GB+。`/tmp` tmpfs 只有 3.1GB 时放不下，工作目录改用大分区。
- **Config.tjs 的 `;` 是有效配置行**，不是注释（KiriKiri 相反）。
- **源游戏本身可能缺音频**：引用存在但 asar 里没打包（如大小写不
  匹配 `Buy_Item.mp3` vs `Buy_item.mp3`）——引擎静默失败，不算转换
  回归，verify 用 `--source` 降级。
- **引擎默认 ogg**：`mediaFormatDefault=ogg` 已是默认，mp3 → ogg
  与引擎预期一致；改脚本引用即可，无需动 Config。
- **视频**：`[bgmovie]` 引用 mp4，Android WebView 原生支持 h264，
  不需要转换。
- **`[bgmovie]` 卡标题黑屏 = 自动播放策略**：浏览器/WebView 在无用户
  激活时拒绝 `<video>.play()`（`NotAllowedError`），`wait_bgmovie`
  永久等待。修复已固化进 `fix-autoplay` 构建步骤（见上）——`play()`
  被拒时挂一次性交互监听、首次点击/触摸/按键后重播。手工打补丁时
  注意：minified 文件里 `video2.play()` 后**没有分号**（ASI），替换
  片段时不要把分号吃掉。
