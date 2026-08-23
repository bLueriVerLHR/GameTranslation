# 经验库 · Tyrano

> **先读这篇**：本文收录「TyranoScript / TyranoBuilder」相关的实战经验
> （由原单文件经验库拆分而来，原 §7.3.1、§10-KAG3 移植）。
> 完整构建/翻译指南见 `docs/tyrano.md`。其他主题经验见：
> [解密 / 解包 / Repacker 识别](experience-decrypt.md) ·
> [音频 / 清理 / 打包](experience-audio-clean.md) ·
> [翻译](experience-translation.md) ·
> [其他 / 杂项](experience-misc.md) ·
> [经验库索引](experience.md)。

## 1. TyranoScript `[bgmovie]` 自动播放策略卡死

TyranoScript 引擎的 `[bgmovie]` 在 `tyrano/plugins/kag/kag.tag_ext.js`
里直接 `video.play()`，被拒后 `wait_bgmovie` 永久等待 → 标题黑屏冻结
（PC 浏览器和 JoiPlay 都可能复现，取决于该 origin 的播放权限历史）。
修复已固化进 `tyrano/pipeline.py fix-autoplay`（幂等、可逆）：`play()`
promise 被拒时挂一次性 click/touchstart/keydown 监听，首次用户交互后
重播并移除监听。验证方式：把真实交付构建里手工打的补丁反解成原始文件，
用模块重打，`cmp` 与交付构建字节一致。注意 minified 文件里
`video2.play()j_video2.css` 无分号（ASI），替换时保留该特征。

## 2. KAG3 → TyranoScript 移植：停车标签与可点击地图（KiriKiri 引擎移植）

- **KAG3 `[s]` 不是点击等待**：本作（改版 KAG3 系统）的 `s` 处理器是
  `inSleep=true; return -1` = 场景结束，点击不做任何事；流程恢复只靠
  `window.process()/goToLabel`、链接、地图。移植到 Tyrano 时若映射成 `[l]`
  （点击推进），标题/菜单死区点击会误推进、串标签。正确做法：自定义
  `[kag3stop]` = stronglyStop + hideEventLayer（事件层隐藏，点击无效），
  地图/链接/jump 不依赖流程状态照常工作。转换期需确认目标游戏所有 `[s]`
  后跟的是标签/endmacro（抽样全量统计，而不是凭经验）。
- **KAG3 可点击地图的生命周期**：地图挂在图层上，`window.process()`/jump
  **不清地图**；只有「该图层加载新图片」（`loadImages` →
  `clearProvinceActions`）或显式 `[mapdisable]` 才清。挂接方式有两种：
  显式 `[mapaction]`，以及 loadImages 的**自动挂接**（`X.ma` 与图片同名时
  自动加载）。移植时若在跳转时清地图，标题 hover（onenter → process 跳转）
  会把地图清掉 → 之后点击全部失效。按原语义只在该图层换图/显式 disable 时清。
- **`[s]` 等标签映射的正则要保行尾**：`re.sub(r'^\[s\]\s*$', ...)` 的 `\s*$`
  会吞掉 `\r\n`，下一行标签被并到上一行（`[s]` + `*label` → `[kag3stop]*label`，
  标签行变成文本）。改成 `r'^\[s\](\s*)$'` + lambda 保留 group(1)。
- **KAG3 `[ch]` 是正文渲染标签**：名字窗、选择肢文字、菜单项全靠它
  （`[ch text=%n]`、`[ch text=&sentaku[0].txt]`）。移植时转发给目标引擎的
  文本标签（Tyrano 的 text 标签自己 nextOrder，shim 不要再推进）。no-op
  shim 会让名字/选择肢/菜单文字全部空白——这类"看似无害"的 no-op 名单要
  逐个核对用途。
- **右击推进的屏幕**：`[rclick jump=true storage=X target=Y]` 驱动的屏
  （coming soon/lineup 等）在移动端没有右击会卡死。移植时实现 rclick 标签
  + 触摸兜底（无活动地图时左键也触发）。
