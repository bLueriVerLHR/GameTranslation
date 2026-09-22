# 0004 KiriKiri 手机目标走 KAG3 → TyranoScript 转换

状态：已采纳（2026-09 定案）

## 背景

KiriKiri（吉里吉里）游戏是桌面引擎（`Game.exe` + `data.xp3`），Android 上
没有成熟的运行时。面向手机有三条候选路线：

- **路线 A**：JoiPlay 的 KiriKiri2 插件直接跑原版。
- **路线 B**：把 KAG3 脚本与素材转换为 TyranoScript（HTML5），交给 JoiPlay
  的 TyranoScript 插件跑。
- **路线 C**：移植到其他引擎（Ren'Py 等）。

## 决策

**手机目标走路线 B：`kirikiri/convert_kag.py`（KAG3 → TyranoScript）**，
桌面翻译仍另走 `patch.xp3`（引擎档案优先级 patch > 原档，同名文件先到先得，
**原包不动**）。**不做 Ren'Py 移植。**

理由：

- 路线 A 的插件成熟度不可控，遇到黑屏/缺插件时无补救手段；路线 B 的产物是
  纯 HTML5，构建行为完全在我们自己手里。
- KAG3 与 TyranoScript 同源（同为 KAG 系标签语法），标签语义、消息窗、选择
  肢、图层与音画时序都有对应关系，转换可保留原作阅读体验。
- Ren'Py 移植会重写整个剧情状态机与 UI，成本远高于标签映射。

## 实现约束

- 转换器按**多轮 pass** 组织（`kirikiri/kag/`：`tags` → `scenario` →
  `assets` → `shims` → `fonts` → `project`），不做一次性大转换；每个 pass
  有合成数据回归测试。
- 保留原作图层、排版、音画时序与交互体验；**先定位可复现差异**，再在工作
  副本验证；**未经运行验证不得声称恢复原作体验**。
- 无法等价实现的行为必须记录影响与取舍，**不能把空操作当成功**。
- 引擎改动一律限制在 CSS/JS 层（保持 WebView/JoiPlay 可运行）。

## 后果

- 指南 `docs/kirikiri-tyrano.md`；桌面翻译见 `docs/kirikiri.md`。
- 验证分两层：桌面浏览器回归 + Android JoiPlay 实机验收，**前者不能代替
  后者**；无法自动化的步骤必须停下请 owner 参与，不得假装完成。
