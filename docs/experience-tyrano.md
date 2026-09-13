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
- **多标签行不能只按标签重建**：正文可能夹在 `[font]`、`[r]`、`[l]` 等
  标签之间。扫描器必须保留每个标签的源区间，只改写区间本身，再把间隙正文
  原样拼回。引号内的 `]` 与转义括号也要纳入测试。
- **`@tag` 与 `[tag]` 必须经过同一转换路径**：先把行首语法规范化，再执行
  资源路径、等待和标签语义改写；提前返回会造成两种写法行为分裂。
- **相邻标签分隔符要在解析前规范化**：部分 KAG3 脚本用 `]\[` 连接标签。
  Tyrano 会把反斜杠当转义并把后一个标签显示成正文，严重时还会留下未闭合的
  条件块。只删除紧跟 `]` 且紧邻 `[` 的反斜杠，不能吞普通正文转义。
- **选择文字应写入当前链接 span**：Tyrano 的链接标签会创建活动 span；
  `[ch]` 若另建平级 span 或段落，显示文本与点击目标会分离，并可能在重复进入
  时留下重叠区域。使用当前消息层、当前段落和当前 span，选择结束后按引擎
  生命周期清理。
- **音频异步回调必须校验播放实例**：复用声道时，旧元素的 `ended`、`error`
  或 `play()` 拒绝可能晚于新声音到达。回调只有在元素仍是声道当前实例时才能
  修改状态；播放前先设状态，并覆盖同步抛错与 Promise 拒绝两条失败路径。
- **增量转换仍要重建资产索引**：`--scenario-only` 会保留输出目录中的图片、
  音频与地图文件。若只从精简源目录生成运行时映射，省略扩展名的引用会退回
  Tyrano 默认文件夹并产生 404。增量模式须把现有 `data/` 资产合并进映射，
  且图片在同名地图描述文件之前取得基础名优先级。
- **全屏点击捕获必须先排除控制界面**：可点击地图常在 document 捕获阶段处理
  事件；若命中后停止传播，后加的手机工具栏即使层级最高也收不到点击。命中
  测试应把工具栏、按钮和表单控件识别为界面元素，让事件继续到目标控件；工具栏
  自己处理后再停止传播，避免同时推进剧情或触发地图。
