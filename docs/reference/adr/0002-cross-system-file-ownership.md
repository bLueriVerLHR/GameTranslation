# 0002 跨系统文件归属：谁的文件谁处理

状态：已采纳（2026-08 定案，事故驱动）

## 背景

本项目同时运行在 WSL（ext4）与纯 Windows（NTFS）两侧：源压缩包与交付成品
在 Windows 侧，处理在 WSL 侧。两侧二进制不通用，而 `/mnt/c`、`/mnt/d` 是
9P 挂载，行为与本地文件系统不同。

**事故（2026-08）**：曾有 agent 用 WSL 内的 7zz / Python 直接解压和读写
Windows 侧（`/mnt/*`）的文件，造成本机**花屏**的严重显示故障。

## 决策

核心判据：**工具与其输入文件必须在同一平台**。跨系统只允许「搬运」**单个
压缩包**，一切「处理」（解压/压缩/脚本读写）都在文件所在侧完成。

- Windows 侧路径（`C:\`、`D:\`，WSL 里显示为 `/mnt/c`、`/mnt/d`）→ 一律用
  Windows 侧应用；从 WSL 调用统一走 `powershell.exe`，路径用 Windows 格式。
- WSL 侧路径（`/tmp`、`/home` 等 ext4）→ 才允许用 WSL 内的工具。
- **MUST NOT**：WSL 内 `7zz` 解压/压缩 Windows 侧文件；WSL 内 Python 脚本
  直接操作 Windows 侧文件（含 `shutil.rmtree` 与读写）。
- 违反即停止并上报 owner。

实现上，`rpgmaker/deliver.py` 内置**自动桥接**：WSL 下对 `/mnt/*` 的删除
与解压自动改用 Windows 7z.exe / PowerShell `Remove-Item`（经
`powershell.exe`，路径自动转换），无需手工介入；仅当 Windows 7z 缺失、或
同一 7z 命令的输入跨两侧混用时报错。

## 后果

- 工作流固定为：Windows 侧压缩包 → 单个文件复制到系统临时目录 → WSL 侧
  解压/处理 → WSL 侧压缩成品 → 单个文件复制回 Windows 交付目录 → Windows
  侧解压。避免大量小文件走 9P。
- `rpgmaker/platform.py` 提供 `is_wsl` / `platform_key` / `is_windows_side` /
  `to_windows_path` / `to_wsl_path` / `localize`（以及同侧写入门岗
  `check_same_side` / `PathRef`），`rpgmaker/tool_registry.py` 提供 `win_7z` /
  `run_powershell`——两者合起来是跨系统判定的唯一入口（
  重构：这些函数原来都在 `rpgmaker/config.py`，该模块已拆分并退化为
  re-export 兼容层，见 ADR-0006）。
- 路径配置**只存一份原生形式**（Windows 侧写 `D:/..`，WSL 侧写 `/tmp/..`），
  需要时由 `localize()` 转换，绝不写两份。
