# 0001 进程内处理压缩包与媒体

状态：已采纳（2026-09 定案）

## 背景

工具链原先大量依赖外部程序：`7z.exe` 打包/校验/解包、`ffprobe` 探测媒体、
`ffmpeg` 转码视频。这带来三个问题：

1. **跨系统陷阱**：在 WSL 里调 `7z.exe` 处理 `/mnt/*` 上的 Windows 侧文件，
   曾经导致本机显示故障（见 ADR 0002 与 AGENTS.md 的 CRITICAL 规则）。
2. **环境依赖**：CI 与新人环境必须额外安装 ffprobe/ffmpeg/7z 才能跑测试。
3. **解析脆弱**：手拼 argv + 解析 stdout 是人类错误的温床，且各工具输出
   格式不稳定。

## 决策

同一个能力只允许**一个封装层**，并优先使用维护中的 Python 包，进程内完成：

| 能力 | 唯一入口 | 用的包 |
|---|---|---|
| 7z 打包/校验/解包（同侧） | `rpgmaker/archive.py` | `py7zr`（zstd） |
| 媒体探测/解码检查 | `rpgmaker/media.py` | `av`（PyAV） |
| 视频转码（VP9+Opus WebM） | `rpgmaker/media.py::transcode_to_webm` | `av` |
| Electron `app.asar` 解包 | `tyrano/asar.py` | `asar`（纯 Python） |
| JS 语法检查 | `rpgmaker/jssyntax.py` | `tree-sitter` + `tree-sitter-javascript` |

实测依据：

- py7zr 3.1s vs `7z.exe` 5.3s（265MB / 3009 文件），体积相同（251.7MB），
  双向互读通过。
- PyAV 转码与 ffmpeg CLI 帧数/时间戳/音频采样数完全一致，PSNR 差 ±0.3 dB。
- tree-sitter 与 `node --check` 在 58 个真实 JS 文件 × 4 种变体共 225 例上
  判定完全一致。
- `asar` 纯 Python 包与官方 node 工具打的包（含 unpacked 条目）双向提取
  字节一致。

## 有意保留的例外

- **Vorbis 编码**仍调 ffmpeg CLI：PyAV 的 wheel 不含 libvorbis，而 q2/q3
  是实测验证过的移动端配方；重构不得静默改质量。
- **Windows 侧桥接**仍调 Windows `7z.exe` 与 PowerShell（跨系统规则）。
- **窗口截图**用 PowerShell `PrintWindow`（Win32 API，必须由 Windows 侧执行）。

例外必须有**代码注释说明原因**，并写进 `docs/reference/tooling.md`；不许
悄悄新增第二个实现。

## 后果

- 探测/解码/视频转码/asar/JS 检查全部进程内，CI 不再需要 node/ffprobe。
- `ffmpeg` 只在 `audio` 步骤需要；Windows `7z.exe` 只在跨系统桥接需要。
- 新代码不得再拼 ffprobe/7z/node 的 argv、解其 stdout，或另写一份
  `shutil.which`。
