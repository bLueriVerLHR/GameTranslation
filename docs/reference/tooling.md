# 工具与依赖（参考）

本文件是「某个能力用哪个包、唯一入口在哪」的**唯一权威对照表**。规则本身
（mandatory：同一能力只能有一个封装层，不得自己造轮子）写在 `AGENTS.md`；
这里只维护这张表和例外说明。

## 唯一入口对照表

| 能力 | 唯一入口 | 用的包 |
|---|---|---|
| 7z 打包/校验/解包（同侧） | `rpgmaker/archive.py` | `py7zr`（zstd；实测比 `7z.exe -mmt` 快 1.7x、体积相同、互读通过） |
| 媒体探测/解码检查 | `rpgmaker/media.py` | `av`（PyAV）——**不再需要 ffprobe** |
| 视频转码（VP9+Opus WebM） | `rpgmaker/media.py::transcode_to_webm` | `av`（libvpx-vp9 + libopus，**不再需要 ffmpeg CLI**；实测帧数/时间戳/音频采样数与 CLI 完全一致、PSNR 差 ±0.3 dB，视频码流大约 6%） |
| Electron app.asar 解包 | `tyrano/asar.py` | `asar`（纯 Python；**不再需要 Node.js/npx**；用官方 node 工具打的包（含 unpacked 条目）双向提取字节一致） |
| JS 语法检查 | `rpgmaker/jssyntax.py` | `tree-sitter` + `tree-sitter-javascript`（**不再需要 `node --check`**；58 个真实 JS 文件 × 4 种变体共 225 例判定与 node 完全一致） |
| 命令行 | 每个工具用 `rpgmaker/cliutil.py` 的 Typer 约定（禁止 argparse）；入口包装 `pipeline.py` / `tyrano/pipeline.py` 用 `rpgmaker/cli.py` | `typer` |
| 外部进程执行 | `rpgmaker/proctools.py` | 标准库 `subprocess`（超时 + UTF-8 + 统一失败信息） |
| 日志配置 | `rpgmaker/logsetup.py`（唯一入口，只能从 `main()` 调用） | 标准库 `logging` |
| 文本/JSON/JSONL 读写 | `rpgmaker/io_boundary.py`（原子写、BOM 容错、两种字节精确 JSON 风格、备份） | 标准库 `json`/`tempfile` |
| 外部程序查找 | `rpgmaker/tool_registry.py::TOOLS` + `resolve_tool()` | 标准库 `shutil.which`/`glob`（**全仓唯一一处**） |
| HTTP 服务（试玩） | `rpgmaker/serve.py` | 标准库 `http.server` |
| 测试 | `tests/` | `pytest` + `pytest-xdist`（默认 `-n auto`）+ `pytest-cov` + `ruff` |

## 仍然存在的例外（已在代码注释里写明原因）

- **Vorbis 音频编码**仍调 ffmpeg CLI：PyAV 的 wheel 不含 libvorbis，而
  q2/q3 是实测验证过的移动端配方，**重构不得静默改质量**。这是
  `rpgmaker/audio.py` 唯一调 ffmpeg 的地方。
- **Windows 侧桥接**仍调 Windows `7z.exe` 与 PowerShell：跨系统 CRITICAL
  规则要求「工具与其输入文件同侧」，见 `AGENTS.md`。
- **窗口截图**用 PowerShell PrintWindow（Win32 API，跨系统必须由 Windows
  侧执行）；优先用 harness 的浏览器自动化，见 `docs/screenshot.md`。

探测/解码/视频转码/asar/JS 语法检查已全部改为进程内实现。

档案层的 `create` / `verify` / `names` / `extract` 在打开后端之前统一调用
`platform.require_native_paths()`：不仅输入输出要同侧，还要与当前 Python
处理器同侧。相对路径和链接先解析，路径归属通过 `PathRef` 传递；文件名后缀
先规范化再检查，避免检查的路径与真正写入的路径不同。WSL 读取 Windows
档案后写入本地目录同样被拒绝，应先搬运单个压缩包，或使用 Windows 桥接。
这是档案入口的保证，不代表其他尚未接入该边界的引擎工具已全部完成审计。

## 外部依赖（需要安装什么）

| 依赖 | 必要性 | 用途 |
|---|---|---|
| Python 3.10+ | 必需 | 全部工具 |
| `typer` `py7zr` `av` `asar` `tree-sitter` `tree-sitter-javascript` | 必需 | 见上表 |
| `Pillow` / `numpy` | 可选（`.[images]`） | 图像步骤 |
| `fonttools` | 可选（`.[fonts]`） | 字体合并 |
| `ffmpeg`（含 libvorbis） | 必需（唯一 `required`） | Vorbis 编码（见上）；缺了 `doctor` 报 `[MISS]` |
| Windows `7z.exe` | 仅 WSL→Windows 桥接 | `deliver` 写回存储侧（`win_7z`，环境变量 `SEVENZ_WIN`） |
| `node` | 仅一个测试 | `tests/test_kag_audio_runtime.py` 在真 JS 运行时观察音频脚本行为（没装则跳过）；**工具链本身不再调 node/npx** |
| `git` | 仅开发流程 | 仓库卫生/文档门禁；不参与转换 |
| ripgrep（`rg`） | 无需注册 | 仅人工/agent 手动检索；工具库代码不调用它，**注册表里也没有条目** |

`doctor` 按 `tool_registry.ToolStatus` 分级报告：`required` 缺失是 `[MISS]`
（退出码 1），其余是 `[WARN]`（不影响退出码）；`windows-bridge` 只在
WSL 上算致命（桥接的意义就是从 WSL 访问 Windows 侧）。

**不再需要**：`ffprobe`、`node`/`npx`（工具链侧）、同侧 `7z.exe`（py7zr 进程内）。
退役对照见 `docs/reference/support-matrix.md` §6；删除无调用者的解析器条目
的规则见 `docs/experience-misc.md` §10.4。
