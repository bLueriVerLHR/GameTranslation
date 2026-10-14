# TyranoScript / TyranoBuilder 翻译指南

TyranoScript（ティラノスクリプト）/ TyranoBuilder 是 HTML5 系视觉小说引擎：游戏
本体常以 Electron 桌面应用形式发布，打包在 `resources/app.asar` 内；也有直接以
HTML5 网页布局发布的发行版。本文件写解包、剧本翻译与写回、引擎 UI 本地化、
MTool 残留清理、打包交付。

## 1. 引擎识别

- Electron 打包：`<Game>.exe` + `resources/app.asar`（asar 是 Electron 的应用
  归档格式），Chromium 系的 pak/dll 在根目录，asar 内是标准 HTML5 布局
  （`index.html` + `data/` + `tyrano/`）。
- 纯网页发布：直接是 `index.html` + `data/` + `tyrano/`，没有 Electron 外壳。
- 场景脚本在 `data/scenario/*.ks`，TyranoBuilder 的编译产物，读入时按文件探测
  编码：
  - 正文在 `[tb_start_text mode=N]` 到 `[_tb_end_text]` 之间；
  - 说话人名行以 `#` 开头（`#つむぎ`），单独一个 `#` 表示无名字；
  - `text="..."` 属性出现在 glink、tb_ptext_show、p_notify、
    tb_alert_dialog 标签上，对应按钮、标题、通知。
- `Config.tjs` 里以 `;` 开头的是**有效配置行**，不是注释（KiriKiri 相反）。

## 2. 解包 app.asar

```bash
python3 -m tyrano.asar list <app.asar>
python3 -m tyrano.asar extract <app.asar> <out_dir>
```

- 归档访问走维护中的 PyPI `asar` 包（MIT，纯 Python），不需要 Node.js，也不经
  `npx @electron/asar`。
- 等价性是实测的：官方 Node 工具打的包（含 `--unpack` 条目）用该包提取逐字节
  一致，文件清单也一致。
- 体积：1.3 GB 的 asar 解出约 1.4 GB，工作目录要预留 2.5 GB 以上。`/tmp` 若是
  3.1 GB 的小容量 tmpfs 就放不下，工作目录换到大分区。

## 3. 剧本翻译

提取：

```bash
python3 tools/build_tyrano_translation.py <game_dir> <work_dir> \
    [--scenario-dir scenario] [--entry first.ks]
```

产出与 KiriKiri、Wolf RPG 同一套标准工作包（`template.json`、`kinds.json`、
`structure.json`、`context.json` 加 `scenario/` 拷贝），之后走统一 chunk 链：
`gen_translation_shards` → 分块翻译 → `merge_plain_chunks` →
`merge_translation` → `translated.json`。

提取规则：

- 键 = 去掉首尾空白的整行，标签原样保留在键里；翻译只改行内日文片段，标签一个
  字节不动。
- `[tb_start_text]` 块内提取 `#名字` 行与文本行（`[font color=..]正文[l][r]`
  这类整行一个键）。
- 块外只提取以 `[` 开头、以 `]` 结尾且带 `text="..."` 的行，例如
  `[glink ... text="戻る" ...]`。
- 不提取：注释行（`;` 开头）、空行、块内单独的 `#`、纯标签行、括号不平衡的行。
- `name="..."` 属性（如 `[ptext name="chara_name_area"]`）是元素标识符，不译。
- 说话人名是共享键：`#つむぎ` 出现几百次只占一个键，词表定名后一次替换全部
  生效。
- 故事序：从入口脚本（默认 `first.ks`）沿 `[call]`/`[jump]` 的 storage 引用做
  BFS；从未被引用的文件按排序追加。
- 写回保持原编码、缩进与行尾；原编码装不下译文时整文件转 UTF-8 并 WARN。

写回与假名 QC：

```bash
python3 tools/apply_tyrano_translation.py <work> [--scenario-dir DIR] [--out DIR]
python3 tools/qc_ks_kana.py <work>/patch
python3 tools/qc_ks_kana.py --values <work>/translated.json
```

`apply_tyrano_translation.py` 按 `structure.json` 的（文件，行号）整行替换，字典
未命中的行原样保留并计数。`qc_ks_kana.py` 报告残留假名的文件与行号，只查显示
文本：`*` 标签行、`;` 注释、`[iscript]`/`@iscript` 代码块、代码语句与变量引用
（`&f.名前`）一律跳过，因为 TyranoScript 合法允许日文标识符，不排除它们会把真
漏译淹掉。

翻译范围有三层，缺一层就会留下玩家可见日文：

1. 剧本 `.ks`，规则见上。
2. 引擎 UI `tyrano/lang.js`，见 §5。
3. 游戏自己的 `[iscript]` 字符串，例如配置画面的
   `tf.text_sample = '…'`。提取器有意不收 iscript（那是代码，不是文本），这类
   字符串极少但确实显示，要在构建里单独确认：用 `rg` 找 `[iscript]` 里的引号
   日文。门禁全绿不代表游戏里没有日文。

## 4. 外部字典路线

repack 常把译文放在游戏根目录的 `翻译文件.json`，靠 MTool hook 只在运行时替换
显示文本，静态数据里仍是原版日文。这类包不必从零翻：

```bash
python3 tools/bake_tyrano_dict.py <work> <dict.json> \
    [--min-coverage 0.5] [--force] [--report r.json]
python3 tools/apply_tyrano_translation.py <work>
python3 tools/qc_ks_kana.py <work>/patch
```

烘焙要点：

- 工作包的键是带标签的整行，字典的键是渲染后的文本，所以烘焙等于重建整行：标签
  逐字节保留，文本段换成译文。
- 文本有两种形态，只处理第一种会留下可见日文：行内文本段
  （`[font color=red]本文[l]`）与块标签的 `text="..."` 属性
  （`[glink text="始めから" ...]`，标题按钮就在后者）。实测一款游戏三个标题
  按钮属于第二种形态。
- 实测一款 Electron 打包的 TyranoBuilder 游戏，2344 个带文本的键每个只含一个
  文本单位，所以重建是精确的而不是猜测。含多个文本单位的键一律拒绝，不猜译文
  该落在哪个标签或属性边界之间。
- 逐条门禁：译文非空、无换行、无假名残留、重建后标签序列与原文一致、剥掉标签
  后等于译文。不合格的条目保留原日文行并计数。
- 覆盖率低于 `--min-coverage`（默认 0.5）拒绝写盘：半汉化会污染后续补翻，
  与 MZ 侧烘焙同一门槛；`--force` 用于刻意的阶段式收割。
- identity 条目（键与值相同且含假名）自动剔除，否则它会遮蔽真正的译文。
- 字典路径一律命令行传入，游戏专属数据不进仓库。

## 5. 引擎 UI 本地化

`tyrano/lang.js` 装的是引擎自己的玩家可见文案：回标题的确认框、无存档提示、
脚本报错、补丁提示。它在 `data/scenario` 之外，任何 scenario 提取器都看不到，
剧本翻完的构建仍会在这些对话框里显示日文。

```bash
python3 tyrano/pipeline.py localize-ui <build> --dump ui_lang.ja.json
python3 tyrano/pipeline.py localize-ui <build> --map  ui_lang.zh.json
```

- 只改 `word` 块；`novel` 块是引擎图片文件名，绝不触碰。
- 条目按键匹配（`go_title`、`not_saved` 等），不按日文文本匹配，所以映射表跨
  引擎修订仍然有效，且只替换文件里确实存在的键：未知键只报告、不插入，未触及的
  条目保持原字节。
- 映射表是 `{key: 译文}` 的 JSON，可跨游戏复用。仓库自带
  `tyrano/ui_lang_zh.json`，是 TyranoScript 6.00 的 `word` 块。
- 机械门禁逐条拒绝不合格译文：占位符 `{ name }` 集合不一致、`\n` 个数不一致、
  残留假名、空值、含回车。被拒条目保持原字节，并让命令以非零码退出。
- 映射表属仓库资产，不随包发。

## 6. 字体

中文构建必须统一字体，否则中文落在系统回退字体上、字形不统一。TyranoScript 的
改动点是 `tyrano/css/font.css` 的 `@font-face` 与 `data/system/Config.tjs` 的
`;userFace=`（注意 `;` 是有效配置行）。游戏自带的 `tyrano.css` 里是日文字体栈
（`@ＭＳ 明朝`、`Yu Gothic`、`Meiryo`），不接字体就会回退。字体策略与字体清单
见 `docs/reference/local-layout.md` §4–5；本地字体策略表缺失时必须 WARN，不得
当成已应用。

## 7. 清理

```bash
python3 tyrano/pipeline.py clean <游戏目录> [--dry-run]
```

- 删 MTool 注入残留：`winmm.dll`、`version.dll`、`与工具一同启动.bat`、
  `从游戏中移除工具文件.bat`、`启动游戏.bat`、`移除工具文件.bat`、
  `MTool挂载翻译.txt`、`MTool_Config.exe`、`MTool_Game.exe`、
  `MTool_Game.exe_LAA_BAK`、`injectPath/`。
- 删 MTool 写在游戏旁的存档残留 `_sf.sav`、`_tyrano_data.sav`。
- 删根目录的运行时替换字典 json（游戏标题名那种），只在没有任何文件引用它时
  删。
- `package.json` 与 `translation_kv.json` 在保留清单里，不会被删。
- 这些残留通常落在 Electron 根目录；如果构建来自 `app.asar`，它本来就不含这些
  文件，`clean` 报告 0 项属正常，不代表漏了步骤。

## 8. 打包与交付

```bash
python3 tyrano/pipeline.py compress <构建目录> [-o <压缩包>.7z] [--level 15]
python3 tyrano/pipeline.py deliver <成品目录> [--archive <本地压缩包>.7z] [--name <交付名>]
```

- `compress` 产 7z-zstd 压缩包并做完整性测试。
- `deliver` 走本地压缩 → 复制压缩包到压缩包目录 → 删除成品目录旧文件夹 → 解压
  到成品目录。
- 打包前把译库复制为构建根目录的 `translation_kv.json`（打包规则）：`clean`
  会删根目录无人引用的 json，而该文件在保留清单里，所以重跑 `clean` 也不会删它。
- 命令由 `rpgmaker/cli.py` 的 tyrano 应用定义（`clean`、`localize-ui`、
  `compress`、`deliver`），`python3 tyrano/pipeline.py` 是保留的入口。
