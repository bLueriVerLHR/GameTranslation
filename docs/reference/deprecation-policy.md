# 弃用政策（DEPRECATION POLICY）

本文件是「某个工具/入口被取代之后怎么办」的**唯一权威说明**。规则本身写在
`AGENTS.md`（公开仓库卫生、既有约定单点维护）与 `docs/CONTRIBUTING.md`；
这里给出**可执行的流程**与**唯一的记录位置**，并说明哪些部分由门禁强制。

## 为什么需要它

本仓库长期存在一个真实缺口：`rpgmaker/inventory.py` 里早有 `superseded` /
`dead` 两种状态，但**没有任何地方写「什么时候可以删」**。结果是
`tools/extract_text.py` 这种**零导入者**的 v1 工具在主测试树里躺了多个阶段，
既不会被删也不会被用 —— 计划里「兼容周期结束后删除旧包装和 v1 工具」这句
话无法执行，因为「兼容周期」从来没有被定义过。本文件把这句话变成两个可查
的字段：**弃用自哪个版本**、**何时可以删**。

## 三个记录位置（缺一不可）

一个对象被弃用时，必须同时更新三处；任一处漏掉都会被门禁挡下
（`tests/test_inventory.py` 与 `tests/test_changelog.py`）：

| 位置 | 写什么 | 由哪个门禁强制 |
|---|---|---|
| `rpgmaker/inventory.py` | 该模块的 `status` 改为 `superseded` 或 `dead`，并把 `replacement` 写成**能解析到的真实目标**（模块路径或文件路径） | 必须填 `replacement`；且目标文件必须存在（`test_the_superseded_replacement_names_a_real_target`），做到这一点是因为曾经有一条 replacement 指向一个**从未存在**的文件 |
| `CHANGELOG.md` | 「弃用」一节的条目，写明「旧入口 → 新入口」 | 弃用条目与 inventory 的 `superseded`/`dead` 记录必须**双向一致**：有记录必须有条目，有条目必须仍是弃用状态 |
| 本文件 §宽限期 | 该对象的**可删除条件**，若为个案而非通用规则 | 通用规则默认适用，个案必须在此登记 |

## 宽限期（默认规则）

**默认：弃用后至少保留一个发布周期，且必须满足下方「可删除条件」才可删除。**

本仓库目前**没有 git tag，也没有用到发布日期**，所以「一个发布周期」在本仓的
可执行含义是：**弃用条目先提交并至少经过一次完整的 CI 全矩阵**（即
`main` 上跑过一次全绿），之后才允许删除。理由是这段窗口的作用就是让一次真实
构建暴露「还有谁在引用它」，而 CI 矩阵是唯一会真的去用它的地方。

不引入日期或版本号的硬性倒计时，是因为本仓的版本号（`rpgmaker/__init__.py` 的
`__version__`）只随打包需要变动，把它当倒计时会让「已过期所以可以删」变成一句
没人验证的话。**这条默认规则需要 owner 确认**；`AGENTS.md` 的下一次修订应把它
写进去（否则它就只是本文件的一厢情愿）。

### 可删除条件（必须全部满足）

1. **零导入者**：`git grep` 找不到任何 `import <模块>` 或
   `from <模块> import`（自身测试除外 —— 但它自己的测试应当与被删对象一起删）。
2. **不在任何文档的命令行里**：`docs/`、`README.md`、`AGENTS.md` 中没有任何
   位置告诉操作员去运行它。若仍有文档指向它，删除的第一步是改文档，不是删代码。
3. **不在 `inventory.py` 里被别的 `active` 记录当作替代目标引用**。
4. **状态与记录齐全**：`superseded`/`dead` + 非空 `replacement` + CHANGELOG 条目。
5. **替代入口已被测试覆盖**：替代入口有测试（否则删掉旧入口可能连唯一能被调用
   的路径一起消失）。

### 删除清单（照做，逐条打勾）

1. `git rm` 该模块及其独占的测试文件。
2. 删除只被它使用的 fixture / 测试辅助（本仓曾留下孤儿 fixture
   `fake_powershell`，唯一消费者是被删的归档测试）。
3. 从 `rpgmaker/inventory.py` 删除该 Module 记录。
4. 更新文档：`docs/reference/repo-layout.md` 目录树、`docs/reference/support-matrix.md`
   的「退役对照」表、相关教程里的命令示例。
5. 把 CHANGELOG 的「弃用」条目移入「删除」一节（而不是删掉条目 —— 历史要留下）。
6. 跑 `tools/check_all.py`，修掉所有因「有人还在引用它」而变红的门禁。
7. **不要只为让门禁变绿而放宽门禁**：本仓的 skip 预算、覆盖率下限、lint 计数
   预算都**只能降不能升**，为一次删除抬高它们属于把信号关掉。

## 已弃用对象（当前登记）

| 对象 | 替代入口 | 状态 | 可删除条件 |
|---|---|---|---|
| `tools/extract_text.py` | `translation.cli prepare` | `superseded`，**零导入者** | 满足全部条件即可删 |
| `tools/plain_to_translated.py` | `translation.cli bake` | `superseded` | 需确认非 MZ 引擎链不再引用旧 `===KEY===` 纯文本格式 |
| `tools/translate_rpgmaker.py` | `translation.cli prepare` | `superseded` | 注意：仍被 `tools/bake_translation.py` 导入，删除前必须先迁移该调用 |
| `tools/gen_csv_shards.py` | `translation.cli slice` | `superseded` | 需确认 CSV 分片链（非 MZ 引擎）已全部走 v2 |

`superseded/` 归档目录已于本阶段删除（不在此表：它是归档目录本身而非工具），
理由与过程见 `CHANGELOG.md` 的「删除」一节。

## 什么**不算**弃用

- **`maintenance` 状态**：事后数据修复类工具是**永久合法**状态，不是弃用的
  前一步。删掉它意味着下一次同类事故无法处理（规则写在 `inventory.py`）。
- **已退役的外部程序依赖**（`argparse`、`ffprobe`、`node --check`、`npx asar`）：
  这些是「不再需要安装什么」，对照表在 `docs/reference/support-matrix.md` §6，
  不受本政策管辖。
- **归档文档**（`docs/archive/*.md`）：保留是为了留下教训，明确标注「不要照它
  执行」即可，不参与删除流程。
