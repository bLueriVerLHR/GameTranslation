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
python3 tools/downscale_images.py <work>/build --glob "**/*.png"   # 超 4096 的贴图
python3 tyrano/pipeline.py localize-ui <work>/build --map tyrano/ui_lang_zh.json
python3 tyrano/pipeline.py verify  <work>/build --source <原版解包目录>
python3 tyrano/pipeline.py serve   <work>/build --test   # HTTP 冒烟
python3 tyrano/pipeline.py compress <work>/build -o <archives>/<Game>.7z
python3 tyrano/pipeline.py deliver <work>/build          # 写回存储侧
```

各步骤要点：

- **build**：解包 `resources/app.asar`（用 `asar` 包，纯 Python；
  不用重复造轮子也不需 Node.js；用官方 node 工具打的包（含 unpacked 条目）
  双向提取已验证字节一致），不
  重复造轮子）→ 剥 Electron 运行时（main.js/package.json/node_modules/
  pak/dll/ico）→ `Config.tjs` 里 `configSave=file` 改 `webstorage`
  （浏览器/WebView 存档必须走 localStorage，file 后端依赖 Node fs）。
- **audio**：`data/bgm` + `data/sound` 下所有 mp3 → Ogg Vorbis
  （q3），并**同步重写** scenario 里 `storage=`/`clickse=`/`enterse=`/
  `decidese=`/`cancelse=` 的 `.mp3` → `.ogg`。只有解析得到实际文件的
  引用才重写；dangling 引用保持原样并计数。

  **命令走的是 `tyrano/audio.py::convert()`（先重写引用、再转码），不是
  `convert_all()`。** 转码会删掉 mp3，所以顺序反了会把每一条引用都变成
  悬空——而 `verify` 当时的布局/音频/PNG 检查全绿，玩家听到的是**全程
  无声**。曾因 Typer 迁移把命令接线从 `convert()` 改成 `convert_all()` 而
  真实复现（单测全在库函数层，看不到命令接线）。

  **`--sample N` 只在副本上用**：它先重写**全部**可解析引用，却只转前 N
  个文件，真实构建上会留下半改状态。要测速就在临时目录单独跑几个文件。

  **m4a 不需要转**：Chromium/Android WebView 原生支持 m4a 里的
  AAC-LC，引擎用的 Howler 2.2.3 对 `m4a` 的判定是
  `canPlayType("audio/x-m4a;") || canPlayType("audio/m4a;") ||
  canPlayType("audio/aac;")`，前后两个在 Chromium 都返回非空——实测
  （浏览器里直接量）能播，所以只处理 mp3，不要顺手把 m4a 也重编码。

  ⚠️ **扩展名不可信**：repack 里常见 `.mp3` 文件名装着 PCM/WAV 数据
  （`pcm_s16le`/`pcm_f32le`/`pcm_s24le`）。按**内容**转码（ffmpeg 自己
  嗅探）结果正确，转完反而变成诚实的 ogg 且体积大减；不要按扩展名
  跳过或“修复”它们。

- **贴图上限**：`tools/downscale_images.py` 默认扫 `img/**/*.png`
  （RPG Maker 布局）。TyranoScript 的美术在 `data/{fgimage,bgimage,image}`
  下，要显式给 pattern：`--glob "**/*.png"`（`--dry-run` 先看报告）。
  超限的立绘/CG 在手机上渲染成黑块，属构建期强制步骤。

- **localize-ui**：`tyrano/lang.js` 是**引擎自己的玩家可见文案**——回标题
  确认框、无存档提示、脚本报错、补丁提示——它在 `data/scenario` 之外，
  任何 scenario 提取器都看不到。只改 `word` 块（`novel` 块是引擎图片
  文件名），**按键匹配**（`go_title`/`not_saved`…），未知键只报告不插入，
  其余条目逐字节不动。

  ```
  python3 tyrano/pipeline.py localize-ui <build> --dump ui_lang.ja.json   # 取出待译条目
  python3 tyrano/pipeline.py localize-ui <build> --map  ui_lang.zh.json   # 写回
  ```

  仓库自带引擎级映射 `tyrano/ui_lang_zh.json`（TyranoScript 6.00 的
  `word` 块），可直接跨游戏复用；缺的键会被报告。机械门禁会**逐条拒绝**
  不合格译文（占位符 `{ name }` 集合不一致、`\n` 个数不一致、残留假名、
  空值），且拒绝的条目保持原字节并让命令非零退出。

- **clean**：删 MTool 残留与桌面临时文件（`MTool挂载翻译.txt`/
  `翻译文件.json`/`winmm.dll` 等）——注意这些通常落在 **Electron 根目录**
  （构建来自 `app.asar`，本来就不含），所以 `clean` 报告 0 项是正常的，
  不代表漏了步骤。但 Electron 运行时里的 `preload.js` 曾经**漏剥**
  （只剥了 main.js/package.json），它 `require('electron')`，浏览器构建
  里是死文件，现已加入剥离清单。

- **打包前归档翻译 KV（打包规则）**：把译库 `<work>/translated.json`
  复制为**构建根目录的 `translation_kv.json`** 再打包，便于日后修改/重译
  （MZ 由 `bake_translation.py` 自动写，Tyrano 这边是手工一步）。
  顺序上它必须在 `clean` **之后**放：`clean` 会把「根目录无人引用的 json」
  当成 MTool 运行时字典清掉——唯一例外是 `translation_kv.json`（已列入
  保留清单，重跑 `clean` 不会再删）。引擎级 UI 映射（`tyrano/ui_lang_zh.json`）
  属仓库资产，**不**随包发，别往构建里拷。
- **fix-autoplay**（可选）：用 `[bgmovie]` 的游戏在浏览器/JoiPlay 下被
  自动播放策略拦截（`.play()` 抛 `NotAllowedError`，`wait_bgmovie`
  永久等待 → 标题卡死黑屏）。补丁把 `tyrano/plugins/kag/kag.tag_ext.js`
  里的 `.play()` 调用包上兜底：promise 被拒时挂一次性
  click/touchstart/keydown 监听，用户首次交互后重播。**幂等**：已打
  补丁的文件（含 `_p&&_p.catch` 标记）跳过；没有 `.play()` 调用的
  引擎版本是 no-op。不用 `[bgmovie]` 的游戏可跳过此步。
- **verify --source**：布局（index.html/tyrano/data）、存档后端、
  音频引用完整性（mp3 残留 + dangling）、**资源引用**（立绘/CG/背景/视频，
  按标签各自的资源目录解析、**大小写精确**）、PNG 4096 上限。`--source`
  指向**解包后未转换**的原始目录：源里本来就缺的引用（制作缺陷）
  降级为不报错——只把转换造成的丢失当回归。`--no-png` / `--no-assets`
  可按需跳过最后两项。

  资源引用为什么也要查：Windows 大小写不敏感，`storage="Chara/1/x.png"`
  指向 `chara/1/x.png` 在 PC 上正常、在 Android/JoiPlay 上是 404，而这类
  引用是流水线**从不重写**的——查不出来就会带着「PC 全绿、手机缺图」的
  构建出厂。裸文件名按标签的资源目录解析（`bg`→`bgimage`、
  `chara_*`/`tb_image_show`→`fgimage`、`playse`→`sound`、`playbgm`→`bgm`、
  `bgmovie`→`video`、`glyph`→`tyrano/images/system`），带 `data/` 的值按
  原样解析；表外的第三方插件标签只要落在任一标准资源目录就算通过（不臆造
  失败）。音频仍由音频检查负责，不重复报告。
- **serve --test**：HTTP 冒烟（PC 浏览器 file:// 会拦截 .ks 的 ajax
  加载，必须走 HTTP 试玩）。serve/compress/deliver 复用 RPG Maker
  流水线的引擎无关模块。

## 3. 翻译（JP → ZH）

> **三层范围，缺一层就会留下玩家可见日文**：① 剧本 `.ks`（下方提取规则）；
> ② **引擎 UI** `tyrano/lang.js`（`localize-ui` 步骤，见 §2）；
> ③ 游戏自己的 `[iscript]` 字符串（如配置画面 `tf.text_sample = '…'`）——
> 提取器有意不收 iscript（代码，不是文本），这类**极少但确实显示**的
> 字符串要在构建里单独确认（`rg` 找 `[iscript]` 里的引号日文），不要
> 因为“门禁全绿”就认为游戏里没有日文。

```
python3 tools/build_tyrano_translation.py <work>/build <work> \
    [--entry first.ks]          # 标准工作包（template/kinds/structure/context）
# → gen_translation_shards → subagent 分块翻译（非 MZ 引擎仍用 chunk 工具链）
# → merge_plain_chunks → merge_translation → translated.json
python3 tools/apply_tyrano_translation.py <work>          # 写回 <work>/patch/
```

**外部字典（MTool 运行时机翻）路线**：repack 常把译文放在游戏根目录的
`翻译文件.json`，由 MTool hook **只在运行时**替换显示文本 —— 浏览器/JoiPlay
构建里它根本不会生效（构建是原版日文）。这类包不必从零翻，但有两条路：

1. **正规翻译链**（上）：工作包全量翻一遍，译文进 v2 门禁；
2. **直接烘焙外部字典**：

```
python3 tools/bake_tyrano_dict.py <work> <dict.json> \
    [--min-coverage 0.5] [--force] [--report r.json]   # → <work>/translated.json
python3 tools/apply_tyrano_translation.py <work>        # → <work>/patch/
python3 tools/qc_ks_kana.py <work>/patch                # 独立假名残留门禁
```

`bake_tyrano_dict.py` 的要点（都是实测出来的，不是推测）：

- 工作包的键是**带标签的整行**，字典的键是**渲染后的文本**，所以烘焙 =
  重建整行：标签逐字节保留、文本段换成译文（`apply_tyrano_translation.py`
  就是整行替换）。
- 文本有两种形态，只处理第一种会留下**可见日文**：行内文本段
  （`[font color=red]本文[l]`）与块标签的 `text="..."` 属性
  （`[glink text="始めから" ...]` —— 标题按钮就在这里）。实测某游戏
  3 个标题按钮就属于后者。
- 逐条门禁：译文非空、无换行、无假名残留、重建后**单位前后字节不变**、
  重建行仍只有一个文本单位。不合格的条目保留原日文行并计数，不猜。
- 覆盖率低于 `--min-coverage`（默认 0.5）拒绝写盘：半汉化会污染后续
  补翻（与 MZ 侧 bake 同一门槛）；`--force` 用于刻意的阶段式 harvest。
- identity 条目（`v == k` **且含假名**）自动剔除，否则它会 shadow 掉真正的
  译文。
- **字典路径一律命令行传入**：游戏专属数据绝不进仓库。

**字体（汉化必须过）**：构建期把项目标准中文字体接进 Tyrano 的改动点是
`tyrano/css/font.css`（`@font-face`）与 `data/system/Config.tjs` 的
`;userFace=`（注意 Config.tjs 里 `;` 是**有效配置行**）。游戏自带的
`tyrano.css` 里还是日文字体栈（`@ＭＳ 明朝` / `Yu Gothic` / `Meiryo`），
不接字体会导致中文落在系统回退字体上、字形不统一。本地字体策略表
（`docs/reference/local-layout.md` §5）缺失时**必须 WARN**，不得当成已应用。

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
