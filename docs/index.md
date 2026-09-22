# 文档总览

本仓库的文档按**用途**分四类（Diátaxis 口径）。想知道「该看哪一篇」先看
这张表；想找某个**事实**的权威定义，看
`docs/reference/support-matrix.md`（引擎能力）与
`docs/reference/repo-layout.md`（目录）。

## 我想……

| 我想…… | 去看 | 类型 |
|---|---|---|
| 搞清这个仓库整体在做什么、能处理哪些引擎 | `README.md` → `docs/reference/support-matrix.md` | 总览 / 参考 |
| 从零跑一遍某引擎的完整流程（第一次上手） | `docs/workflow.md`（RPG Maker）、`docs/tyrano.md`、`docs/wolfrpg.md`、`docs/kirikiri.md`、`docs/kirikiri-tyrano.md`、`docs/engines/unity.md` | 教程 |
| 查某条命令怎么用、某个文件放哪、某个概念的定义 | `docs/reference/*.md` | 参考 |
| 翻译一款 RPG Maker MZ/MV（现行 v2） | `docs/translation.md` → `docs/translation-data.md` → `docs/translation-qc.md` | 教程 + 参考 |
| 翻译 Unity / Wolf / KiriKiri / Tyrano | `docs/engines/unity*.md`、`docs/wolfrpg.md`、`docs/kirikiri.md`、`docs/tyrano.md` | 教程 |
| 搞懂某个设计**为什么**是这样、被推翻过什么 | `docs/reference/adr/*.md`、`docs/experience*.md` | 解释 / 经验 |
| 查某个具体故障怎么修 | `docs/experience*.md`（按引擎分册）、`docs/translation-qc.md` §6 | 解释 / 排障 |
| 改代码前先看约定（规则、门禁、禁区） | `AGENTS.md` | 规则 |
| 贡献代码 / 跑测试 / 提交 | `docs/CONTRIBUTING.md` | 教程 |
| 看某个工具/入口被弃用后怎么办、何时可以删 | `docs/reference/deprecation-policy.md` | 规则 |
| 看本工具库面向使用者的变更 / 弃用与删除记录 | `CHANGELOG.md` | 记录 |
| 验证画面（浏览器自动化 + 截图） | `docs/screenshot.md` | 参考 |
| 看已经退役、但教训仍有效的旧流程 | `docs/archive/*.md` | 归档（**不要照它执行**） |

## 参考（reference）

权威定义只写在这些文件里，别处只链接：

| 文件 | 管什么 |
|---|---|
| `docs/reference/support-matrix.md` | 每个引擎**支持哪些能力**、入口命令、哪些步骤需要人工验收 |
| `docs/reference/repo-layout.md` | 仓库目录树（`tools/check_docs.py` 的默认输入） |
| `docs/reference/local-layout.md` | 本地私有数据（词表/密码/字体/工作区）的布局、解析顺序、字体策略 |
| `docs/reference/tooling.md` | 「能力 → 唯一入口 → 用的包」对照表；外部程序解析的唯一入口 |
| `docs/reference/deprecation-policy.md` | 弃用流程：三个记录位置、宽限期、可删除条件与删除清单 |
| `docs/reference/adr/` | 重大技术选择的决策记录（架构决策记录） |
| `docs/translation-data.md` | 翻译**读写什么**：提取范围、键表/译文库格式、五道门禁判据 |

## 解释（explanation）与经验

- `docs/experience.md` — 经验索引，按主题指向下列分册。
- `docs/experience-translation.md` — 翻译侧踩坑（含烘焙后回读比对等门禁教训）。
- `docs/experience-decrypt.md` — 解密/编码类故障。
- `docs/experience-audio-clean.md` — 音频转换与清理。
- `docs/experience-misc.md` — 工具链、打包、杂项（含「无调用者的工具入口=死代码」等规则）。
- `docs/experience-tyrano.md` — TyranoScript/Electron 打包侧。

这些文件是**排障入口**：出问题时先按关键词搜它们，再动手。

## 归档（archive）

`docs/archive/` 只放**已退役**的流程与文档。里面的事实可能已经过时，
流程**不得再执行**；保留是为了追溯「为什么现在这么做」。

## 文档维护规则

- 文档一律**中文**；代码与注释一律**英文**（游戏内原生日文内容除外）。
- 每条强制规则**只有一个权威定义**，其他位置只链接，不复制。
- 相对链接、重复标题、失效入口点由 `python tools/check_docs.py` 守卫
  （与目录树一致性检查同一个门禁）；改动文档后必须跑它。
- 不得写入游戏名、本机路径、密码、成人词汇等（见 `AGENTS.md` 的公开仓库
  卫生规则）；本地私有资料的位置写在 `docs/reference/local-layout.md`。
