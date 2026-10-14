# 支持矩阵（参考）

本文件是**现状清单**，回答「支持什么、用什么命令、处于什么状态」。代码侧
的权威是 `rpgmaker/inventory.py` 的 `MODULES` 与 `ENGINE_CAPABILITIES`，由
`tests/test_inventory.py` 守卫；本文件与代码不一致视为缺陷。

## 1. 状态口径

| 状态 | 含义 |
|---|---|
| `stable` | 有统一入口、有测试、已在真实游戏上跑通 |
| `experimental` | 能跑，但边界未验证，或只在个别样本上验证过 |
| `manual` | 没有仓库内入口，由操作员按需手工执行 |
| `local-only` | 依赖不入库的本地私有数据（词表、字体、密码），干净检出无法跑 |
| `deprecated` | 仍可用，但已被替代，只保留一个兼容周期 |
| `superseded` | 已被替代；替代物记在 `rpgmaker/inventory.py` 的 `replacement` 字段，且该目标必须真实存在 |

## 2. 已验证层次

| 层次 | 含义 |
|---|---|
| `unit` | 单元测试 |
| `contract` | 合成数据回归或契约测试 |
| `build` | 真实游戏目录上的产物检查（解包、写回、打包交付） |
| `browser` | 浏览器自动化冒烟 |
| `device` | 实机验收：在真实设备上运行产物 |

层次按能力评定，同一种能力在不同引擎上可以停在不同层次。只写跑过的层次：
浏览器冒烟不算实机验收。

## 3. 引擎支持

**没有任何引擎声明运行时转换能力。** 各引擎都在原地翻译，产物运行在原平台
上；`build`、`decrypt`、`audio`、`serve` 一类步骤不属于任何引擎的能力。

| 引擎 | 识别特征 | 能力目标 | 入口 | 状态 | 已验证层次 |
|---|---|---|---|---|---|
| RPG Maker MZ/MV | `index.html` + `js/` + 数据目录（`data/` 或 `data_encrypted/`）；MV 常用 `www/` | 还原打包数据、提取文本、翻译写回、插件参数文本、烘焙、打包交付 | `gt`（定义在 `rpgmaker/cli.py`；`pipeline.py` 是包装） | `stable` | unit, contract, build |
| TyranoScript / TyranoBuilder | `data/scenario/*.ks` + `tyrano/`；Electron 部署带 `app.asar` | 解包 `app.asar`、提取文本、翻译写回、引擎 UI 本地化、打包交付 | `gt-tyrano`（`rpgmaker/cli.py:tyrano_main`；`tyrano/pipeline.py` 是包装） | `stable` | unit, contract, build |
| KiriKiri / KAG3 | `*.xp3` + `Game.exe`，无 `index.html` | 解包 `xp3`、提取 `.ks` 文本、写回 `patch.xp3` | `python -m kirikiri.xp3tool`、`python -m kirikiri.xp3pack`；提取与写回由 `tools/build_ks_translation.py`、`tools/apply_ks_translation.py` 完成 | `experimental` | unit, contract |
| Wolf RPG（ウディタ） | `Data.wolf`、`Game.exe` 与 `Data/` 下的 `.wolf` | 解包 `.wolf`、提取文本、写回补丁 | `python -m wolfrpg.dxarchive`；提取与写回由 `tools/build_wolf_translation.py`、`tools/apply_translation_to_patch.py` 完成 | `experimental` | unit |
| Unity Mono（含 RPG Maker Unite） | `<Game>_Data/` + `Managed/` | 提取文本、运行时注入译文 | `python -m unity.rmunite.extract_game`、`python -m unity.rmunite.prefill`；插件 `unity/rmunite/RMUniteTranslation_plugin.cs` | `experimental` | unit, device |
| Unity IL2CPP + Addressables | `GameAssembly.dll` + `StreamingAssets/aa/**/*.bundle` | 提取文本、MelonLoader 运行时 hook | 无仓库内入口，流程见 `docs/engines/unity-il2cpp.md` | `manual` | device |

**硬边界**：`gt unpack-data` 与 `gt clean` 只适用于 RPG Maker MZ/MV；Tyrano
的清理走 `gt-tyrano clean`。`doctor`、`compress`、`deliver` 与引擎无关。
Unity 与 Wolf RPG 也不走 `gt` 的引擎专用命令，它们各自的清理与放置见
`docs/engines/unity.md` 与 `docs/wolfrpg.md`。

## 4. 能力 × 引擎

`✔` = 该引擎声明此能力；`—` = 不声明（设计如此，不是缺陷）。单元格给出实现
位置。词表来自 `rpgmaker/inventory.py` 的 `CAPABILITIES`。

| 能力 | RPG Maker | Tyrano | KiriKiri | Wolf | Unity |
|---|---|---|---|---|---|
| `detect` 识别引擎与游戏根目录 | ✔ `rpgmaker/detect.py` | ✔ | ✔ | ✔ | ✔ |
| `unpack` 解包引擎档案 | —（无档案） | ✔ `tyrano/asar.py` | ✔ `kirikiri/xp3tool.py` | ✔ `wolfrpg/dxarchive.py` | ✔ `unity/rmunite/extract_game.py` |
| `adpack` 打包件处理（还原 `<Game>.exe` 内数据、清理广告与工具残留） | ✔ `unpack-data`、`clean` | — | — | — | — |
| `extract_text` 提取可译文本 | ✔ `python -m translation.cli prepare` | ✔ `tools/build_tyrano_translation.py` | ✔ `tools/build_ks_translation.py` | ✔ `tools/build_wolf_translation.py` | ✔ `unity/rmunite/extract_game.py` |
| `apply_translation` 写回译文 | ✔ `python -m translation.cli bake` | ✔ `tools/apply_tyrano_translation.py` | ✔ `tools/apply_ks_translation.py` | ✔ `tools/apply_translation_to_patch.py` | ✔ 运行时 hook |
| `package` 打包归档 | ✔ `compress`、`deliver` | ✔ `gt-tyrano compress`、`gt-tyrano deliver` | ✔ `kirikiri/xp3pack.py` | — | — |
| `inject` 运行时注入 | — | — | ✔ `patch.xp3` | — | ✔ BepInEx + Harmony、MelonLoader |

**失效关闭**：引擎不在上表时，任何能力都不声明，调用方必须显式报出「不支持」，
不得静默继续（`inventory.supports()`）。

## 5. 公开 CLI 入口

三个公开入口，其余入口是模块级的：

| 入口 | 模块 | 子命令 |
|---|---|---|
| `gt` | `rpgmaker.cli:main` | `unpack-data`、`clean`、`doctor`、`compress`、`deliver` |
| `gt-tyrano` | `rpgmaker.cli:tyrano_main` | `clean`、`localize-ui`、`compress`、`deliver` |
| `python -m translation.cli` | `translation/cli.py` | `prepare`、`extract`、`scaffold`、`codes`、`slice`、`prefill`、`append`、`to-json`、`rewrite`、`gates`、`pending`、`decide`、`status`、`bake` |

`python pipeline.py` 与 `python tyrano/pipeline.py` 是同样两个入口的包装，命令
定义只有 `rpgmaker/cli.py` 一份。

### 5.1 `gt` 命令

| 命令 | 作用 |
|---|---|
| `unpack-data` | 从 `<Game>.exe` 的 Enigma Virtual Box 容器里还原 `data/`；`--dry-run` 只列文件 |
| `clean` | 删除图片垃圾、未用字体与未用图块；`--dry-run` 只报告 |
| `doctor` | 环境自检：外部程序解析结果、机器配置、交付目录与私有位置；`--json` 给机器可读报告 |
| `compress` | 打包为 7z-zstd 归档，并做归档完整性测试 |
| `deliver` | 写回存储侧：本地压缩、复制归档、删除成品目录旧文件夹、解压到成品目录 |

### 5.2 `gt-tyrano` 命令

| 命令 | 作用 |
|---|---|
| `clean` | 删除 MTool 残留与桌面运行时垃圾 |
| `localize-ui` | 本地化引擎自身 UI 文案（`tyrano/lang.js`）；`--dump` 导出、`--map` 应用 |
| `compress` | 打包为 7z-zstd 归档，并做归档完整性测试 |
| `deliver` | 写回存储侧，与 `gt deliver` 同一实现 |

### 5.3 模块级入口

没有 console script，用 `python -m <模块>` 启动：

| 入口 | 子命令或参数 |
|---|---|
| `python -m translation.cli` | 翻译 v2 全流程，见 `docs/translation.md` |
| `python -m kirikiri.xp3tool` | `list`、`extract` |
| `python -m kirikiri.xp3pack` | `<in_dir> <out.xp3>` |
| `python -m kirikiri.merge_font` | 中文字体与日文字体合并（`maintenance`，依赖本地字体数据） |
| `python -m wolfrpg.dxarchive` | `<archive> <out_dir>` |
| `python -m tyrano.asar` | `list`、`extract` |
| `python -m unity.rmunite.extract_game` | `<game_dir> <out_dir>` |
| `python -m unity.rmunite.prefill` | `<work_dir> <game_key>` |
| `python -m rpgmaker.doctor` | 环境自检（`gt doctor` 的底层实现） |

各引擎的提取与写回还有 `tools/` 下的维护脚本，逐个入口记录在
`rpgmaker/inventory.py` 的 `entry` 字段。

## 6. 外部程序

外部程序全部登记在 `rpgmaker/tool_registry.py` 的 `TOOLS` 表，只有三条：

| 程序 | 分级 | 用途 | 缺失时 |
|---|---|---|---|
| PowerShell | `windows-bridge` | 从 WSL 执行 Windows 侧操作（`deliver`、归档处理） | WSL 下致命，Windows 下不影响运行 |
| Windows 侧 `7z.exe` | `windows-bridge` | 经 PowerShell 解压或删除 Windows 侧（`/mnt/*`）的档案 | WSL 下致命 |
| `git` | `dev-only` | 版本控制与仓库卫生门禁 | 开发流程报出；工具运行不需要它 |

`doctor` 按 `ToolStatus` 分级报告：`required` 缺失是 `[MISS]`（退出码 1），
其余是 `[WARN]`（不影响退出码）。解析顺序、环境变量与覆盖项见
`docs/reference/tooling.md`。

Python 包依赖只有 `pyproject.toml` 一份清单（必需 `typer`、`py7zr`、`asar`、
`tree-sitter`、`tree-sitter-javascript`，可选 `[images]`、`[unity]`、`[fonts]`、
`[dev]`）；「能力 → 唯一入口 → 依赖包」对照见 `docs/reference/tooling.md`。

## 7. 本地私有数据

| 数据 | 用途 | 缺失时行为 |
|---|---|---|
| 每游戏词表、语气、经验 | 翻译上下文 | **WARN** 并说明缺失 |
| 通用名词表 | 翻译风格决策 | **WARN** 并说明缺失 |
| 压缩包密码表 | 解压受保护档案 | **WARN** 并说明缺失 |
| 统一字体（`.asset/fonts` + `manifest.json`） | 汉化构建字体统一 | `required` 策略下失败；`auto` 只报告，标为「未应用」 |
| 字体路径覆盖文件 | 点名清单外的字体 | 回落到注册字体目录 |
| 本机环境覆盖（交付目录、工具路径覆盖） | 路径与工具解析 | 回落到探测与内置默认，无需 WARN |

**规则**：任何 mandatory 步骤若只有私有数据才能完成，必须 WARN 并说明缺了
什么，不得静默降级成空操作。测试套件不得依赖这些数据，需要时自建临时 fixture。
布局与解析顺序见 `docs/reference/local-layout.md`。

## 8. 已替代项（退役对照）

| 项 | 状态 | 替代 |
|---|---|---|
| `argparse` 命令行 | `superseded` | `rpgmaker/cliutil.py`（Typer） |
| `node --check` | `superseded` | `rpgmaker/jssyntax.py`（tree-sitter） |
| `npx asar` | `superseded` | `tyrano/asar.py`（`asar` 包） |
| 同侧 `7z.exe -mmt` | `deprecated` | `rpgmaker/archive.py`（py7zr） |
| 自建窗口截图工具 | `superseded` | 浏览器自动化截图，政策见 `docs/screenshot.md` |
| v1 翻译流程（切块 → 多 agent → merge） | `superseded` | translation v2 |

自建窗口截图工具与其归档目录已删除，理由记在 `CHANGELOG.md` 的「删除」一节。
模块级弃用对象的登记与可删除条件见 `docs/reference/deprecation-policy.md`。
已移除的运行期转换能力是一项已采纳决策：项目范围只做解包、翻译、插件翻译
与烘焙，记录在 `docs/reference/adr/translation-only-scope.md`。

## 9. 维护方式

- 本文件描述**现状**。新增引擎或退役命令必须同步改本文件，否则视为未完成。
- 新增一行至少给三样：识别特征、入口、已验证层次。
- 「已验证层次」只能写跑过的层次。
- 不写具体游戏名、本机路径、密码或私有数据文件名。
