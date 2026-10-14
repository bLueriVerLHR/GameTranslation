# 架构决策记录（ADR）

本目录记录影响面较大的技术选择：决定了什么、放弃了什么、改动时要注意
什么。

## 规则

- 一条决策一个文件，文件名是决策的短横线描述
  （`single-writer-translation.md`），不加编号；改名等于改标题，所有引用
  一并更新。
- 只记录**决策与理由**，不记录实现细节（实现看代码与其 docstring）。
- 决策被推翻时**不删旧文件**：把状态改成「已被 `<文件名>` 取代」，另写一篇
  说明为什么改。保留「为什么」比保留「现在是什么」重要。
- 长期经验教训（踩坑、失败模式）不写在这里，写 `docs/experience-*.md`。

## 决策清单

| 决策 | 状态 |
|---|---|
| [项目范围：只做解包、翻译、插件翻译与烘焙](translation-only-scope.md) | 已采纳 |
| [跨系统文件归属：谁的文件谁处理](cross-system-file-ownership.md) | 已采纳 |
| [同侧处理用进程内库，不拼外部程序命令行](in-process-archive-handling.md) | 已采纳 |
| [翻译 v2：单一写者 + 文件信箱](single-writer-translation.md) | 已采纳 |
| [打包与包布局：wheel 必须覆盖公开入口](packaging-and-layout.md) | 已采纳 |
| [平台与配置拆分：`config.py` 只做兼容层](platform-config-split.md) | 已采纳 |
