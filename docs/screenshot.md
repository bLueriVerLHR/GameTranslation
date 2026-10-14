# 运行验证与 WSL 互操作

画面验证用运行环境提供的**浏览器自动化能力**（打开、点击、推进、填表、截图
一体）；仓库不自带窗口截图工具。截图后用可用的视觉路径读图，无法自动化的
步骤停下请 owner 手动完成，并明确记为「未验证」。

跨系统调用（WSL → Windows）的前提与排障也记在本文件：凡从 WSL 经
`powershell.exe` 调 Windows 原生工具（`deliver` 的桥接等）都依赖它。

## 1. 画面验证

- 用浏览器自动化打开页面，先取一次可交互元素快照，再用当前快照里的引用
  操作；页面变化后重新取快照。
- 只做只读读取来判断状态（例如读取引擎对象的字段），不要为了观察而改写
  引擎方法。
- 无法用自动化完成的步骤，交给 owner 手动执行，并在报告里写明哪一步没有
  验证过。

## 2. RPG Maker 页面的推进与输入

MV/MZ 只在**每帧轮询**一次输入，合成的瞬时事件很容易被吞。三条实测结论：

- **按键事件必须带 `keyCode`**。引擎用 `Input.keyMapper[event.keyCode]`
  映射按键；某些自动化通道发出的 `keydown` 到页面时 `keyCode` 是 `0`、
  `code` 是空串 —— 页面确实收到了事件（自己挂的 `keydown` 监听器会触发），
  但引擎当它不存在。判定：先挂一个
  `document.addEventListener('keydown', e => console.log(e.key, e.keyCode))`，
  看 `keyCode` 是否是 0。是 0 就**不要**再用键盘推进，改用鼠标。
- **鼠标按下与松开要拉开到 200~300ms**。一次帧轮询里同时发生
  `mousedown` 与 `mouseup`，引擎可能只看到最终状态，`isTriggered()` 与
  `isReleased()` 都不会置位 —— 表现为「点了没反应」。按住再松开就正常。
- **页面刚打开后的第一次点击可能只用于取得焦点**。标题画面点不动时，原坐标
  再点一次即可。

**不要用「绑定原型方法」的方式给引擎打探针**：
`Window_Message.prototype.update.bind(Window_Message.prototype)` 这类写法会把
`this` 固定成原型对象，`this.children` 变 `undefined`，帧里抛异常，**主循环
直接停住**（画面停在最后一帧，看起来就像「输入没反应」）。要查状态，用只读的
`eval --stdin` 读 `SceneManager._scene`、`Input._currentState`、
`$gameMap._interpreter._waitMode`；要计时就自己起一个 `requestAnimationFrame`
计数器，不要改引擎方法。

推进对话的可靠做法（canvas 坐标要按设备像素比换算）：

```text
mouse move <x> <y>  →  mouse down  →  wait 250  →  mouse up  →  wait 1200
```

`x`、`y` 由 `canvas.getBoundingClientRect()` 加 `Graphics` 坐标换算得出
（对话框窗口位置可用 `eval` 读 `SceneManager._scene._commandWindow`）。

## 3. WSL 互操作的前提

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

`P` 标志是 WSL 官方 `/init` 自身写入的写法；`UTF-8` 等长标志串会被内核以
`Invalid argument` 拒绝。

## 4. 排查

| 现象 | 处理 |
|---|---|
| `cannot execute binary file: Exec format error` | 用 §3 的两条命令重建 binfmt 条目（先 `register` 立即生效，再写 `/etc/binfmt.d/` 持久化） |
| 重启后再次失效 | 确认 `/etc/binfmt.d/wsl-interop.conf` 已写入且 `systemd-binfmt` 已启动 |

## 5. 互操作相关逻辑

- `rpgmaker/tool_registry.py` 的 `find_powershell()`：Windows 侧程序解析。
- `rpgmaker/deliver.py` 的自动桥接：WSL 下对 `/mnt/*` 的删除与解压改走
  Windows `7z.exe` 与 PowerShell。
