# 同侧处理用进程内库，不拼外部程序命令行

状态：已采纳

## 背景

工具链原先依赖外部程序完成同侧工作：`7z.exe` 打包/校验/解包、`ffprobe`
探测媒体、`ffmpeg` 转码视频、`node` 检查 JavaScript。三个问题：

1. **跨系统陷阱**：在 WSL 里调用 `7z.exe` 处理 `/mnt/*` 上的 Windows 侧文件
   会破坏文件系统一致性（见 [cross-system-file-ownership.md](cross-system-file-ownership.md)）。
2. **环境依赖**：CI 与新环境要额外安装 ffprobe、ffmpeg、node 才能跑测试。
3. **解析脆弱**：手拼 argv 再解析 stdout 依赖外部程序输出格式的稳定性。

## 决策

同一能力只允许**一个封装层**，并优先使用维护中的包，在进程内完成：

| 能力 | 唯一入口 | 依赖包 |
|---|---|---|
| 7z 打包/校验/解包（同侧） | `rpgmaker/archive.py` | `py7zr`（zstd） |
| Electron `app.asar` 解包 | `tyrano/asar.py` | `asar` |
| JS 语法检查 | `rpgmaker/jssyntax.py` | `tree-sitter` + `tree-sitter-javascript` |

实测依据：

- py7zr 3.1s，`7z.exe` 5.3s（265 MB / 3009 文件），体积相同（251.7 MB），
  双向互读通过。
- tree-sitter 与 `node --check` 在 58 个真实 JS 文件 × 4 种变体共 225 例上
  判定一致。
- `asar` 与官方 Node 工具互读：含 unpacked 条目的包提取字节一致。

## 保留的例外

**Windows 侧桥接**仍调用 Windows `7z.exe` 与 PowerShell：跨系统规则要求处理
Windows 侧文件时使用该侧的原生程序。例外必须在代码注释里写明原因，并登记在
`docs/reference/tooling.md`；不得悄悄新增第二个实现。

## 后果

- 打包、解包、asar 读取、JS 检查全部进程内，CI 不需要 Node.js。
- 新代码不得再拼 `7z`/`node` 之类的 argv、解析其 stdout，也不得另写
  `shutil.which`；外部程序的解析只有 `rpgmaker/tool_registry.py` 一处。
