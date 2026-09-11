# 截图验证流程（窗口级）

运行验证需要精确截取**指定 app 的窗口**（而非整屏）时使用本流程：
`tools/wsl_capture.py`（WSL 侧 CLI 包装）+ `tools/capture_window.ps1`
（Windows 侧捕获脚本，窗口级、被遮挡也能截）。

## 前提

- WSL 互操作可用（`powershell.exe` 能执行）。
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

  （`P` 标志是 WSL 官方 `/init` 自身写入的写法；`UTF-8` 等长标志串会被
  内核以 `Invalid argument` 拒绝。）

## 用法

```bash
# 截取指定进程的窗口（最常用）
python tools/wsl_capture.py --process GamePro

# 多窗口进程按标题子串过滤（更精准）
python tools/wsl_capture.py --process EditorPro --title 確認

# 指定输出目录/文件名
python tools/wsl_capture.py --process GamePro \
  --dir /mnt/c/Users/<user>/Pictures --out shot.png

# 整屏兜底（窗口定位失败时）
python tools/wsl_capture.py --full --dir /mnt/c/Users/<user>/Pictures

# 其他选项
#   --no-force-visible  不移动窗口（保留原位）
#   --no-window-only    改截屏幕区域（PrintWindow 黑屏时）
#   --width 1280 --height 720   缩放输出
```

成功时打印**WSL 侧**文件路径；退出码 `0` 成功 / `1` 无窗口或失败 /
`2` 互操作缺失或参数错误。

## 机制

1. **互操作检查**：`WSLInterop` binfmt 条目缺失时直接给出修复命令。
2. **自动部署**：`capture_window.ps1` 幂等复制到 Windows `%TEMP%`
   （`deliverables.win_temp`），避免经 UNC 路径加载脚本的信任问题。
3. **窗口定位**：按进程名枚举顶层可见窗口；`--title` 子串过滤；多候选
   取面积最大者。**同名的所有进程都参与匹配**（Chromium/Electron 这类
   多进程应用，拥有窗口的不一定是返回的第一个 PID；旧版只取首个 PID，
   对这类应用会误报 `no visible window`）；无 `--title` 时优先带标题的
   窗口（多进程应用的辅助窗口无标题）。
4. **前置处理**：最小化窗口先还原；窗口超出可视区（对话框按钮常被顶出
   屏幕底部）时自动 `MoveWindow` 移入屏幕内。
5. **捕获**：`PrintWindow`（先 `PW_RENDERFULLCONTENT=2` 后降级 0）抓窗口
   自身像素——被其他窗口遮挡依然正确；不支持时降级整屏拷贝
   `CopyFromScreen`。
   **注意（已实测）**：PrintWindow 对遮挡的 Chromium 窗口能拿到正确
   画面（含窗口边框），但对**已最小化/从未合成**的窗口无能为力；
   Chromium 网页内容的可靠路径是 CDP 截图（见 `visual-check` 技能），
   且被遮挡时需先发一个真实点击唤醒合成器。
6. **输出**：UTF-8 输出绝对路径（非 ASCII 目录名可存活 WSL 往返），
   包装器转回 WSL 路径并校验文件存在。

## 与 vision-analyzer 配合

主模型不支持图片输入；截图后把返回的 WSL 路径交给 vision-analyzer
子代理分析：

```
Task(description="分析截图", prompt="读取 <截图路径>，报告画面内容…",
     subagent_type="vision-analyzer")
```

## 排查

| 现象 | 处理 |
|---|---|
| `exit 2` + WSLInterop 提示 | 按提示执行修复命令后重试 |
| `exit 1` no visible window | 进程名写错 / 窗口在托盘 / **多个同名进程时用 `--title` 收窄** |
| 黑图 | PrintWindow 不支持该应用 → `--no-window-only` 或 `--full`；窗口被遮挡/未合成时也会黑（点击唤醒或让窗口可见） |
| 画面被裁/偏位 | 加 `--no-force-visible` 保留原位置再截 |
| 旧版 WSL 交互工具冲突 | 本工具自包含，不依赖其他截图脚本 |

## 测试

```bash
.venv/bin/python -m pytest tests/test_wsl_capture.py -q
```

用 `tests/fake_tools/fake_powershell.py`（由平台适配 launcher 包装后经
`POWERSHELL_EXE` 注入；Windows 用 `.cmd` shim，POSIX 直接执行）+ 临时目录
`win_temp`，全流程无外部依赖，两种平台都可跑。
