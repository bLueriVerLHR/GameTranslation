# GameTranslation

面向 **JP→ZH 翻译** 的本地工具库：解包游戏数据、提取文本、翻译与烘焙、
清理、打包交付。代码主要由 **DeepSeek V4 Flash** 生成，人工编写的比例很低。

先看 **[docs/index.md](docs/index.md)**：那里按「要做什么」分流到对应
文档。本文件只回答「这工具能做什么、怎么跑起来、去哪看细节」。

## 能做什么

| 目的 | 引擎 | 入口 | 做法见 |
| --- | --- | --- | --- |
| 还原 launcher 打包的数据库、翻译与烘焙、清理、打包交付 | RPG Maker MZ/MV 网页版 | `pipeline.py`（= `gt`） | [docs/workflow.md](docs/workflow.md)、[docs/translation.md](docs/translation.md) |
| 解包 `app.asar`、`.ks` 翻译与写回、引擎 UI 本地化、清理、打包交付 | TyranoScript / TyranoBuilder | `tyrano/pipeline.py`（= `gt-tyrano`） | [docs/tyrano.md](docs/tyrano.md) |
| 解包 `data.xp3`、`.ks` 翻译、写回 `patch.xp3`、字体合并 | KiriKiri2 / krkrz / KAG3 | `kirikiri/` | [docs/kirikiri.md](docs/kirikiri.md) |
| 解包、文本提取、翻译与补丁写回 | Wolf RPG（ウディタ） | `wolfrpg/dxarchive.py` | [docs/wolfrpg.md](docs/wolfrpg.md) |
| 文本提取、翻译、运行时 hook 注入 | Unity（Mono / IL2CPP / RM Unite） | `unity/rmunite/` | [docs/engines/unity.md](docs/engines/unity.md)、[unity-il2cpp.md](docs/engines/unity-il2cpp.md)、[unity-rmunite.md](docs/engines/unity-rmunite.md) |

**权威定义不在这里**：每个引擎支持什么、处于什么状态、哪些步骤需要人工
验收，看 **[docs/reference/support-matrix.md](docs/reference/support-matrix.md)**。

**硬边界**：Unity 与 Wolf RPG **绝不走** RPG Maker 流水线，也绝不解密/
重编码；KiriKiri 不使用 RPG Maker 专用命令。每个引擎只做「解包 → 提取 →
翻译 → 写回 → 打包交付」，**不做任何运行时转换或移植**。

## 快速开始

工作副本放系统临时目录，成品放交付目录；**绝不修改原版游戏目录**。

```powershell
$tk   = "<本工具库路径>"
$src  = "C:\path\to\game"          # 原版目录：只读，绝不直接改
$work = Join-Path $env:TEMP 'game' # 工作副本：复制一份到这里干活，可随时删

python $tk\pipeline.py doctor                # 列出每个外部程序解析到的路径与来源
python $tk\pipeline.py unpack-data $work     # 仅 launcher 打包件：还原 <Game>.exe 里的 data/
python $tk\pipeline.py clean    $work        # 删除广告文件、注入残留、无用字体与图块
python $tk\pipeline.py compress $work        # 打包 7z-zstd（进程内，写完自校验）
python $tk\pipeline.py deliver  $work        # 本地压缩 → 复制压缩包 → 解压到成品目录
```

- `clean --dry-run` 只报告不删除；`compress --level N` 调压缩级别。
- `deliver` 是收尾一步，按顺序做四件事：本地压缩 → 复制压缩包到压缩包目录
  （覆盖旧包）→ 删除成品目录里的旧文件夹 → 解压到成品目录，含压缩包完整
  性测试。
- `unpack-data` 只对 launcher（Enigma Virtual Box）打包过的发布版有意义：
  这类目录磁盘上没有 `data/`，数据在 `<Game>.exe` 的 PE 段（`.enigma1` /
  `.enigma2`）里。
- TyranoScript 用 `tyrano\pipeline.py`（= `gt-tyrano`），并多一条
  `localize-ui`（引擎自带文案 `tyrano/lang.js`）。
- 并行度默认按机器自动调优（`rpgmaker/runtime.py`），可用 `GT_WORKERS`
  环境变量覆盖。
- 外部程序路径不需要手工维护：`pipeline.py doctor --json` 给出机器可读
  报告。本机环境覆盖是**可选层**，没有它也能跑。

**跨系统铁律（CRITICAL）**：处理文件必须用**文件所在系统**的原生应用。
Windows 侧文件（`/mnt/*`）一律用 Windows 的 `7z.exe` / PowerShell，从 WSL
经 `powershell.exe` 调用；WSL 内 7zz / python 直接操作 Windows 侧文件被
禁止。跨系统只搬运**单个压缩包**；`deliver` 已内置自动桥接。背景与后果见
[docs/reference/adr/cross-system-file-ownership.md](docs/reference/adr/cross-system-file-ownership.md)。

## 翻译（JP → ZH）

RPG Maker MZ/MV 的现行流程只有一条：**单一写者 + 文件信箱 + 五道硬门禁**
（[docs/translation.md](docs/translation.md)）：

```bash
python -m translation.cli prepare <game_dir> <work_dir>   # 键表 + 控制码表 + 骨架 + MISSION.md
python -m translation.cli slice   <work_dir> --start N --count M --lean --out <file>
python -m translation.cli append  <work_dir> --batch <file> --fix-leading --note "..."
python -m translation.cli gates   <work_dir>              # 五道硬门禁全绿才能 bake
python -m translation.cli bake    <game_dir> <work_dir>   # 按 id 写回 + 统一字体 + KV 归档
```

- 其余子命令：`pending` / `decide` / `status` / `rewrite` / `to-json`。
- 数据契约（键表、译文库、门禁口径）见
  [docs/translation-data.md](docs/translation-data.md)；真机踩过的坑与故障
  排查见 [docs/translation-qc.md](docs/translation-qc.md)。
- 非 MZ 引擎（Tyrano / Wolf / KiriKiri）沿用各自引擎指南里的提取/写回链。
- **清除 MTool 机翻，自己翻译**；翻译前先量体量并取得 owner 授权。
- v1 的「切块 → 每块一个 subagent → 按行合并」已退役
  （[docs/archive/translation-v1.md](docs/archive/translation-v1.md)，
  不要照它执行）。
- 每游戏资料（词表、语气、笔记）**不入库**，只存在本地私有数据目录，位置
  与边界见 [docs/reference/local-layout.md](docs/reference/local-layout.md)。

## 环境要求

- **Python 3.14+**（不支持 3.10 / 3.12）。开发环境按锁文件安装：

  ```bash
  python -m pip install uv
  uv sync --locked --python 3.14 --extra images --extra unity --extra fonts --extra dev
  ```

  `.venv/` 不入库；原 Python 被移除或升级跨版本时，应备份后重建，不能仅改
  `pyvenv.cfg`。普通使用者用 `pip install -e ".[images,unity,fonts]"`。
- **外部程序只有 Windows 侧的 `7z.exe` 与 PowerShell**（仅跨系统桥接，只在
  WSL 侧需要），外加开发流程用的 `git`。其余能力都在进程内实现：7z 走
  `py7zr`、`app.asar` 走 `asar`、JS 语法检查走 `tree-sitter`，**不需要
  Node.js / npx / ffprobe**。完整表格见
  [docs/reference/tooling.md](docs/reference/tooling.md)。
- 外部程序解析顺序为 环境变量 → 本地配置覆盖 → 探测常见安装位置 → PATH，
  实现在 `rpgmaker/tool_registry.py`；`doctor` 按 `ToolStatus` 分级把缺失分成
  `[MISS]` 与 `[WARN]`。

## 开发与门禁

贡献流程、分支命名与提交规则见 [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
与 [AGENTS.md](AGENTS.md)。合并前门禁全绿：

```bash
<venv-python> -m tools.check_all              # 本地门禁总入口
<venv-python> -m tools.check_all --coverage   # 追加串行覆盖率测量与下限门禁
```

`tools/check_all.py` 按依赖顺序跑 hygiene / compile / lint / docs / tests /
types / skips 等门禁，缺失的依赖会被点名，不做静默跳过。单独跑某一道：

```bash
<venv-python> -m pytest tests/                        # 单元 + 集成（默认 -n auto）
<venv-python> -m ruff check .                         # lint（规则钉在 pyproject.toml）
<venv-python> -m pytest tests/test_repo_hygiene.py -q # 公开仓库卫生（禁本机路径等）
<venv-python> -m tools.check_docs                     # 目录树一致性 + 文档门禁
```

改依赖要跑 `uv lock` 并提交 `uv.lock`（`uv lock --check` 是 `lock` 门禁，
对应 `tests/test_lockfile.py`）；新增公开入口或包内资源要同步
`pyproject.toml` 与 `tests/test_wheel_contents.py`。测试不需要外部工具：
合成语料由 `tests/helpers.py` 构造，真容器固件在 `tests/fixtures/`（清单与
sha256 见 `tests/fixtures/MANIFEST.json`）；打包与解包都在进程内
（`py7zr`），`tests/test_integration.py` 跑 clean → compress → 解压 →
deliver 全链。

## 目录与本地私有数据

目录树见 **[docs/reference/repo-layout.md](docs/reference/repo-layout.md)**
（唯一权威，`tools/check_docs.py` 用它做一致性检查）。设计决策见
[docs/reference/adr/](docs/reference/adr/)；踩坑经验见
[docs/experience.md](docs/experience.md)。

**词表、密码、打包字体、每游戏资料一律不入库**（本地私有目录与系统临时
文件里的工作区），干净检出不存在它们；缺失时相关步骤按规则 **WARN 并
跳过，不静默降级**。布局、迁移与字体策略见
[docs/reference/local-layout.md](docs/reference/local-layout.md)。
