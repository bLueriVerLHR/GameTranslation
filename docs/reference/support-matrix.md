# 支持矩阵（参考）

本文件是**现状清单**，不是目标。它回答「现在到底支持什么、用什么命令、
处于什么状态」，避免后来者靠读代码或猜名字来判断。

状态口径：

| 状态 | 含义 |
|---|---|
| `stable` | 有流水线入口、有测试、已在真实游戏上跑通 |
| `experimental` | 能跑但边界未验证，或只在个别样本上验证过 |
| `manual` | 没有流水线入口，由 owner 按需手工调用 |
| `local-only` | 依赖不入库的本地私有数据（词表/字体/密码），干净检出无法跑 |
| `deprecated` | 仍可用但已被替代，只保留一个兼容周期 |
| `superseded` | 已被替代，替代物记录在 `inventory.py`（逐引擎的工具走本行，归档目录已删） |

「已验证层次」列区分证据强度：`unit`（单元测试）、`contract`（合成数据
回归/契约测试）、`build`（真实构建产物检查）、`browser`（浏览器自动化
冒烟）、`device`（Android 实机验收）。

---

## 1. 引擎支持

| 引擎 | 识别特征 | 目标 | 流水线入口 | 状态 | 已验证层次 |
|---|---|---|---|---|---|
| RPG Maker MZ/MV（HTML5） | `index.html` + `js/` + `data/` | JoiPlay 可玩构建 | `pipeline.py` | `stable` | unit, contract, build, browser, device |
| TyranoScript / TyranoBuilder | `app.asar`（Electron）或 `data/scenario/*.ks` + `tyrano/` | JoiPlay 构建 + 翻译 | `tyrano/pipeline.py` | `stable` | unit, contract, build, browser |
| KiriKiri / KAG3 | `*.xp3` + `Game.exe`，无 `index.html` | 手机：KAG3→Tyrano 转换；桌面：`patch.xp3` | `kirikiri/pipeline.py` | `experimental` | unit, contract, build, browser |
| Wolf RPG（ウディタ） | `Data.wolf` / `Game.exe` + `.wolf` 资源 | 仅翻译 + 解包/回写 | 无流水线，`wolfrpg/dxarchive.py` | `experimental` | unit |
| Unity Mono（含 RPG Maker Unite） | `<Game>_Data/` + `Managed/` | 仅翻译（BepInEx + Harmony） | 无流水线，`unity/rmunite/` | `experimental` | unit, device |
| Unity IL2CPP + Addressables | `GameAssembly.dll` + `StreamingAssets/aa/*.bundle` | 仅翻译（MelonLoader 运行时 hook） | 无仓库内流水线 | `manual` | device |

**硬边界**：Unity 与 Wolf RPG **绝不走** RPG Maker 流水线
（`build`/`decrypt`/`audio`/`clean`/`verify` 对它们无意义且会破坏目录）。
KiriKiri 也**不得**走 RPG Maker 专用流水线。

---

## 2. 能力 × 引擎

`✔` = 有实现；`—` = 不适用（不是缺陷，是设计）；`?` = 未验证。

| 能力 | RPG Maker | Tyrano | KiriKiri | Wolf | Unity |
|---|---|---|---|---|---|
| 探测/识别 | ✔ | ✔ | ✔ | ✔ | ✔ |
| 解包引擎档案 | — (无档案) | ✔ asar | ✔ xp3 | ✔ wolf | ✔ bundle 读取 |
| 压缩包解压（7z/zip） | ✔ | ✔ | ✔ | ✔ | ✔ |
| 解密（easy only） | ✔ | — | — | — | — |
| 文本提取 | ✔ | ✔ | ✔ | ✔ | ✔ |
| 翻译写回 | ✔ | ✔ | ✔ | ✔ | ✔（运行时字典） |
| 音频转换 | ✔ | ✔ | ? | — | — |
| 媒体探测/校验 | ✔ | ✔ | ✔ | ✔ | — |
| 构建手机产物 | ✔ | ✔ | ✔（转 Tyrano） | — | — |
| 静态验证 | ✔ | ✔ | ✔ | — | — |
| HTTP 试玩服务器 | ✔ | ✔ | ✔ | — | — |
| 打包交付 | ✔ | ✔ | ✔ | — | — |
| 桌面补丁注入 | — | — | ✔ patch.xp3 | — | ✔ hook |

---

## 3. 公开 CLI 入口

三个公开入口，其余都是维护脚本：

| 入口 | 模块 | 用途 |
|---|---|---|
| `gt` | `rpgmaker.cli:main` | RPG Maker 流水线（也是 `pipeline.py` 的实现） |
| `gt-tyrano` | `rpgmaker.cli:tyrano_main` | Tyrano 流水线（也是 `tyrano/pipeline.py` 的实现） |
| `python -m translation.cli` | `translation/cli.py` | v2 翻译流程（提取/切片/落盘/门禁/烘焙） |

非 RPG Maker 引擎的入口是**模块级**的，没有 console script：
`python -m kirikiri.pipeline`、`python -m wolfrpg.dxarchive` 等。

### 3.1 `gt` 命令

| 命令 | 作用 | 备注 |
|---|---|---|
| `build` | 剥桌面运行时，产出 web 构建 | |
| `compat` | 插件加载期崩溃的定点维修 + 预扫 | |
| `decrypt` | RPGMV easy 加密解密 | 仅 MZ/MV easy；其他原样保留 |
| `audio` | 压缩音频 | |
| `clean` | 清理广告/MTool 残留 | |
| `verify` | 静态验证（`--source` 做源感知音频引用检查） | |
| `serve` | HTTP 试玩服务器 | 手机试玩必须 `--host 0.0.0.0` |
| `compress` | 打包 7z（zstd） | |
| `deliver` | 压缩 → 复制压缩包 → 解压到成品目录 | 含跨系统桥接 |
| `unpack-data` | 还原打包件 `data/` | |
| `doctor` | 打印每个外部程序解析到的路径与来源 | 排查「工具找不到」先跑它 |

### 3.2 `gt-tyrano` 命令

`build` / `audio` / `clean` / `fix-autoplay` / `localize-ui` / `verify` /
`serve` / `compress` / `deliver`。

### 3.3 `python -m translation.cli` 命令

`prepare` / `slice` / `append` / `pending` / `decide` / `status` /
`rewrite` / `to-json` / `gates` / `bake`。详见 `docs/translation.md`。

### 3.4 `python -m kirikiri.pipeline` 命令

`probe` / `unpack` / `convert` / `verify` / `port`。详见
`docs/kirikiri-tyrano.md`。

---

## 4. 外部依赖

| 依赖 | 类型 | 用在哪 | 缺失时 |
|---|---|---|---|
| `7z`（Windows 侧） | 必需 | 跨系统删除/解压、`deliver` | 报错拒绝（不静默） |
| `py7zr` | 必需（pip） | 同侧打包/校验/解包 | 报错 |
| `av`（PyAV） | 必需（pip） | 媒体探测、视频转码 | 报错 |
| `ffmpeg` CLI | 必需 | **仅** Vorbis 编码（PyAV wheel 不含 libvorbis） | 音频转换报错 |
| `typer` | 必需（pip） | 全部 CLI | 报错 |
| `tree-sitter` + `tree-sitter-javascript` | 必需（pip） | JS 语法检查 | 报错 |
| `asar` | 必需（pip） | Tyrano `app.asar` 解包 | Tyrano 解包报错 |
| `UnityPy` | 可选（`[unity]`） | Unity bundle 读取 | Unity 提取报错 |
| `fonttools` | 可选（`[fonts]`） | 字体合并/子集化 | 字体合并报错 |
| Node.js / `npx` | **已不需要** | — | 无影响（已改纯 Python） |
| `ffprobe` | **已删除** | — | 无影响（已由 PyAV 取代） |

RPG 引擎本体（用于 KAG3 转换的回归测试）放在本地 `.tools/`，不入库。

---

## 5. 本地私有数据（干净检出不存在）

| 数据 | 用途 | 缺失时行为 |
|---|---|---|
| 每游戏词表/语气/经验 | 翻译上下文 | **WARN** 并说明缺失 |
| 通用名词表 | 翻译风格定案 | **WARN** 并说明缺失 |
| 压缩包密码表 | 解压受保护档案 | **WARN** 并说明缺失 |
| 统一字体 + 字体策略表 | 汉化构建字体统一 | **WARN**，字体策略标记为「未应用」（不静默） |
| 本机环境覆盖（交付目录等） | 路径解析 | 回落到探测 + 内置默认，无需 WARN |

**规则**：任何 mandatory 步骤若只有私有数据才能完成，必须 WARN 并说明缺了
什么，**不得静默降级成空操作**。测试套件**不得**依赖这些数据——需要时
自建临时 fixture。

---

## 6. 已废弃 / 已替代

| 项 | 状态 | 替代 | 说明 |
|---|---|---|---|
| `argparse` 命令行 | `superseded` | `rpgmaker/cliutil.py`（Typer） | 曾 53 文件 / 223 个 `add_argument` |
| `ffprobe` | `superseded` | `rpgmaker/media.py`（PyAV） | 探测/解码全部进程内 |
| `node --check` | `superseded` | `rpgmaker/jssyntax.py` | tree-sitter |
| `npx asar` | `superseded` | `tyrano/asar.py` | 纯 Python |
| `7z.exe -mmt`（同侧打包） | `deprecated` | `rpgmaker/archive.py`（py7zr） | 实测快 1.7x，体积相同 |
| `ffmpeg` CLI 转码 | `deprecated` | `rpgmaker/media.py::transcode_to_webm` | 仅 Vorbis 编码例外 |
| 窗口截图自建工具 | `superseded` | 浏览器自动化 + 读图 | 归档目录 Phase 8 已删；政策见 `docs/screenshot.md` |
| v1 翻译流程（切块→多 agent→merge） | `superseded` | translation v2 | 工具仅供非 MZ 引擎提取/写回 |

---

## 7. 维护方式

- 本文件描述**现状**。改变现状（新增引擎、退役命令）必须同步改本文件，
  否则视为未完成。
- 新增引擎支持时，至少补三行：识别特征、流水线入口、已验证层次。
- 「已验证层次」只能写跑过的：浏览器冒烟不等于 Android 实机验收。
- 不要在这里写具体游戏名、本机路径、密码或私有数据文件名。
