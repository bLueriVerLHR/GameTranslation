# 运行验证与 WSL 互操作

画面验证用当前环境提供的**浏览器自动化能力**（打开/点击/推进/截图一体），
本仓库不自带窗口截图工具。本文件只保留**跨系统调用**（WSL → Windows）的前提与排障 ——
凡从 WSL 经 `powershell.exe` 调 Windows 原生工具（`deliver` 的桥接等）
都依赖它。

## 前提：WSL 互操作可用

`powershell.exe` 能执行即正常。

**互操作失效的症状**：`powershell.exe: cannot execute binary file:
Exec format error`，且 `/proc/sys/fs/binfmt_misc/` 下没有 `WSLInterop`
条目。修复（需提权，`sudo` 会提示输入口令）：

```bash
sudo sh -c 'printf ":WSLInterop:M::MZ::/init:P\n" > /proc/sys/fs/binfmt_misc/register'
```

持久化（防重启后丢失）：

```bash
sudo sh -c 'printf ":WSLInterop:M::MZ::/init:P\n" > /etc/binfmt.d/wsl-interop.conf'
sudo systemctl start systemd-binfmt
```

（`P` 标志是 WSL 官方 `/init` 自身写入的写法；`UTF-8` 等长标志串会被内核以
`Invalid argument` 拒绝。）

## 排查

| 现象 | 处理 |
|---|---|
| `cannot execute binary file: Exec format error` | 用上面两条命令重建 binfmt 条目（先 register 立即生效，再写 `/etc/binfmt.d/` 持久化） |
| 重启后再次失效 | 确认 `/etc/binfmt.d/wsl-interop.conf` 已写入且 `systemd-binfmt` 已启动 |

互操作相关逻辑：`rpgmaker/config.py` 的 `find_powershell()`（Windows 侧
程序解析）；`rpgmaker/deliver.py` 的自动桥接（WSL 下对 `/mnt/*` 的删除/
解压改走 Windows 7z.exe 与 PowerShell）。
