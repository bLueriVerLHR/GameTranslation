# 文档总览

本仓库的文档按**用途**分四类（Diátaxis 口径）。想知道「该看哪一篇」先看
这张表；想找某个**事实**的权威定义，看
`docs/reference/support-matrix.md`（引擎能力与状态）与
`docs/reference/repo-layout.md`（目录树）。

## 按需求找文档

| 需求 | 去看 | 类型 |
|---|---|---|
| 搞清这个仓库整体在做什么、能处理哪些引擎 | `README.md` → `docs/reference/support-matrix.md` | 总览 / 参考 |
| 从零跑一遍某引擎的完整流程（第一次上手） | `docs/workflow.md`（打包与交付）、`docs/translation.md`、`docs/tyrano.md`、`docs/wolfrpg.md`、`docs/kirikiri.md`、`docs/engines/unity.md` | 教程 |
| 查某条命令怎么用、某个文件放哪、某个概念的定义 | `docs/reference/*.md` | 参考 |
| 翻译一款 RPG Maker MZ/MV（v2 流程） | `docs/translation.md` → `docs/translation-data.md` → `docs/translation-qc.md` | 教程 + 参考 |
| 翻译 Unity / Wolf / KiriKiri / Tyrano | `docs/engines/unity*.md`、`docs/wolfrpg.md`、`docs/kirikiri.md`、`docs/tyrano.md` | 教程 |
| 搞懂某个设计**为什么**是这样、被推翻过什么 | `docs/reference/adr/`、`docs/experience.md` | 解释 / 经验 |
| 查某个具体故障怎么修 | `docs/experience.md`（按主题分册）、`docs/translation-qc.md` §6 | 解释 / 排障 |
| 写文档、改文档 | `docs/reference/doc-style.md` | 规则 |
| 改代码前先看约定（规则、门禁、禁区） | `AGENTS.md` | 规则 |
| 贡献代码 / 跑测试 / 提交 | `docs/CONTRIBUTING.md` | 教程 |
| 看某个工具/入口被弃用后怎么办、何时可以删 | `docs/reference/deprecation-policy.md` | 规则 |
| 看本工具库面向使用者的变更 / 弃用与删除记录 | `CHANGELOG.md` | 记录 |
| 验证画面（浏览器自动化 + 截图） | `docs/screenshot.md` | 参考 |
| 看已经退役、但教训仍有效的旧流程 | `docs/archive/translation-v1.md` | 归档（**不要照它执行**） |

## 参考（reference）

权威定义只写在这些文件里，别处只链接：

| 文件 | 管什么 |
|---|---|
| `docs/reference/support-matrix.md` | 每个引擎**支持哪些能力**、入口命令、哪些步骤需要人工验收 |
| `docs/reference/repo-layout.md` | 仓库目录树（`tools/check_docs.py` 的默认输入） |
| `docs/reference/local-layout.md` | 本地私有数据（词表/密码/字体/工作区）的布局、解析顺序、字体策略 |
| `docs/reference/tooling.md` | 「能力 → 唯一入口 → 用的包」对照表；外部程序解析的唯一入口 |
| `docs/reference/deprecation-policy.md` | 弃用流程：记录位置、宽限期、可删除条件与删除清单 |
| `docs/reference/doc-style.md` | 文档写作规范：四条硬性用语规则、结构与标点 |
| `docs/reference/schema/` | 本地 JSON 的 schema（仓库只放 schema 与示例） |
| `docs/reference/adr/` | 架构决策记录（ADR）：一条决策一个文件，文件名即标题 |
| `docs/translation-data.md` | 翻译**读写什么**：提取范围、键表/译文库格式、五道门禁判据 |
| `docs/translation-qc.md` | 翻译 QC 清单、术语一致性、故障排查表 |

## 解释与经验

- `docs/experience.md` — 经验索引，按主题指向下列分册。
- `docs/experience-translation.md` — 翻译侧踩坑（含烘焙后回读比对等门禁教训）。
- `docs/experience-tyrano.md` — TyranoScript `.ks` 结构、`lang.js`、写回坑。
- `docs/experience-packaging.md` — 打包与清理：repack 垃圾、广告壳、压缩包卫生。
- `docs/experience-misc.md` — 工具卫生、运行兼容与杂项排查。

这些文件是**排障入口**：出问题时先按关键词搜它们，再动手。

## 归档（archive）

`docs/archive/` 只放**已退役**的流程与文档。里面的事实可能已经过时，
流程**不得再执行**；保留是为了追溯「为什么现在这么做」。

## 文档维护规则

- 文档一律**中文**；代码与注释一律**英文**（游戏内原生日文内容除外）。
- 每条强制规则**只有一个权威定义**，其他位置只链接，不复制。
- 相对链接、目录树一致性、文档里点名的入口是否存在，由
  `python -m tools.check_docs` 守卫；改动文档后必须跑它。
- 不得写入游戏名、本机路径、密码、成人词汇等（见 `AGENTS.md` 的公开仓库
  卫生规则）；本地私有资料的位置写在 `docs/reference/local-layout.md`。
