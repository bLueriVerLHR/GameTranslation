# 工具与依赖（参考）

本文件是「某个能力用哪个包、唯一入口在哪」的**唯一权威对照表**。规则本身
（同一能力只能有一个封装层，不得自己造轮子）写在 `AGENTS.md`；这里维护对照
表、保留的例外与安装清单。

## 1. 唯一入口对照表

| 能力 | 唯一入口 | 用的包 |
|---|---|---|
| 7z 打包/校验/解包（同侧） | `rpgmaker/archive.py` | `py7zr`（zstd；265 MB、3009 文件的树上实测 3.1s，`7z.exe` 5.3s，体积同为 251.7 MB，双向互读通过） |
| XP3 档案（KiriKiri）读写 | `kirikiri/xp3tool.py` 读取、`kirikiri/xp3pack.py` 写入 | 标准库 `zlib`、`struct`（进程内，无外部程序） |
| DXArchive（`.wolf`）解包 | `wolfrpg/dxarchive.py` | 标准库 `zlib`、`mmap`（进程内，`mmap` 只读映射） |
| Electron `app.asar` 解包 | `tyrano/asar.py` | `asar`（纯 Python；与官方 Node 工具互读，含 unpacked 条目的包双向提取字节一致） |
| JS 语法检查 | `rpgmaker/jssyntax.py` | `tree-sitter` + `tree-sitter-javascript`（58 个真实 JS 文件 × 4 种变体共 225 例，判定与 `node --check` 一致） |
| 字体合并 | `kirikiri/merge_font.py` | `fonttools`（可选 extra `[fonts]`） |
| 命令行 | 每个工具用 `rpgmaker/cliutil.py` 的 Typer 约定；入口包装 `pipeline.py`、`tyrano/pipeline.py` 用 `rpgmaker/cli.py` | `typer` |
| 外部进程执行 | `rpgmaker/proctools.py` | 标准库 `subprocess`（超时、UTF-8、统一失败信息） |
| 日志配置 | `rpgmaker/logsetup.py`（唯一入口，只能从 `main()` 调用） | 标准库 `logging` |
| 文本 / JSON / JSONL 读写 | `rpgmaker/io_boundary.py`（原子写、BOM 容错、两种字节精确 JSON 风格、备份） | 标准库 `json`、`tempfile` |
| 外部程序查找 | `rpgmaker/tool_registry.py` 的 `TOOLS` 与 `resolve_tool()` | 标准库 `shutil.which`、`glob`（全仓唯一一处） |
| 测试 | `tests/` | `pytest` + `pytest-xdist`（默认 `-n auto`）+ `pytest-cov` + `ruff` |

## 2. 仍然存在的例外

**Windows 侧桥接**仍调 Windows `7z.exe` 与 PowerShell（`rpgmaker/tool_registry.py`
的 `win7z`、`find_powershell`、`run_powershell`）。跨系统 CRITICAL 规则要求
「工具与其输入文件同侧」，见 `AGENTS.md`。

例外必须在代码注释里写明原因，并登记在本文件；不得悄悄新增第二个实现。
已被取代的命令行与外部程序对照见 `docs/reference/support-matrix.md` §8；删除
无调用者的解析器条目的规则见 `docs/experience-misc.md` §10.4。

## 3. 外部程序解析

解析顺序对每个程序一致：

```text
环境变量 → 机器配置的显式覆盖（支持通配）→ 常见安装位置探测 → PATH
```

`GT_NO_PROBE=1` 只关掉探测层，环境变量、配置与 PATH 仍然生效（用于封闭环境
与测试）。环境变量名与分级登记在 `TOOLS` 表里，只有一处。

`doctor`（`gt doctor`，底层 `python -m rpgmaker.doctor`）报告每个程序解析到
的路径、来源（`env`、`config`、`probe`、`path`）与分级：`required` 缺失是
`[MISS]`（退出码 1），其余是 `[WARN]`；`windows-bridge` 只在 WSL 上算致命，
其意义就是从 WSL 访问 Windows 侧。

## 4. 同侧门岗

档案层的 `create`、`verify`、`names`、`extract` 在打开后端之前统一调用
`platform.require_native_paths()`：不仅输入输出要同侧，还要与运行中的 Python
处理器同侧。相对路径与链接先解析，路径归属通过 `PathRef` 传递；文件名后缀
先规范化再检查，避免检查的路径与真正写入的路径不同。WSL 读取 Windows 档案后
写入本地目录同样被拒绝，应先搬运单个压缩包，或使用 Windows 桥接。

这是档案入口的保证，不代表其他尚未接入该边界的引擎工具已全部完成审计。

## 5. 需要安装什么

| 依赖 | 必要性 | 用途 |
|---|---|---|
| Python 3.14+ | 必需 | 全部工具；运行时、lint、类型检查与 CI 使用同一基线 |
| `typer` `py7zr` `asar` `tree-sitter` `tree-sitter-javascript` | 必需 | 见 §1 |
| `Pillow` / `numpy` / `numba` | 可选（`.[images]`） | 图像相关辅助；仓库内只有测试固件用 `Pillow` 生成 PNG |
| `UnityPy` | 可选（`.[unity]`） | Unity bundle 读取（RPG Maker Unite 提取） |
| `fonttools` | 可选（`.[fonts]`） | 中文字体与日文字体合并 |
| `pytest` `pytest-xdist` `pytest-cov` `ruff` `mypy` `hypothesis` `PyYAML` `uv` `pip` `setuptools` | 可选（`.[dev]`） | 测试、lint、类型检查与本地门禁 |
| Windows `7z.exe` | 仅 WSL→Windows 桥接 | `deliver` 写回存储侧（`win_7z`，环境变量 `SEVENZ_WIN`，配置键 `tools.win32.7z`） |
| PowerShell | 仅 WSL→Windows 桥接 | 执行 Windows 侧命令（环境变量 `POWERSHELL_EXE`） |
| `git` | 仅开发流程 | 仓库卫生与文档门禁；不参与工具运行 |
| ripgrep（`rg`） | 无需注册 | 仅人工与 agent 手动检索；工具库代码不调用它，注册表里也没有条目 |

依赖清单的唯一来源是 `pyproject.toml`，锁定版本在 `uv.lock`。
工具与包的对应关系以 §1 为准；某一能力若需要新依赖，先在本表登记再动代码。
