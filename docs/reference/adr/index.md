# 架构决策记录（ADR）

这里记录**已经定案、且影响面较大**的技术选择：为什么这么做、放弃了什么、
以后要改需要动哪里。

规则：

- 一条决策一个文件，命名 `NNNN-短横线标题.md`，编号不回收、不重排。
- 只记录**决策与理由**，不记录实现细节（实现看代码与其 docstring）。
- 决策被推翻时**不删旧文件**：把「状态」改成 `被 NNNN 取代`，另写一篇
  新的，说明为什么改。这与 `docs/archive/` 的取舍一致——保留「为什么」比
  保留「现在是什么」重要。
- 长期经验教训（踩坑、失败模式）不写在这里，写 `docs/experience-*.md`。

| 编号 | 标题 | 状态 |
|---|---|---|
| 0001 | [进程内处理压缩包与媒体，不再调用 7z/ffprobe](0001-in-process-archive-media.md) | 已采纳 |
| 0002 | [跨系统文件归属：谁的文件谁处理](0002-cross-system-file-ownership.md) | 已采纳 |
| 0003 | [翻译 v2 单一写者 + 文件信箱](0003-single-writer-translation.md) | 已采纳 |
| 0004 | [KiriKiri 手机目标走 KAG3 → TyranoScript 转换](0004-kag3-to-tyrano.md) | 已采纳 |
| 0005 | [打包与包布局：wheel 必须覆盖公开入口](0005-packaging-and-layout.md) | 已采纳 |
| 0006 | [平台与配置拆分：`config.py` 只做兼容层](0006-platform-config-split.md) | 已采纳 |
