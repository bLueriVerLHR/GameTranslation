# 弃用政策（DEPRECATION POLICY）

本文件是「某个工具或入口被取代之后怎么办」的**唯一权威说明**：给出可执行
流程与唯一的记录位置。相关规则写在 `AGENTS.md`（公开仓库卫生、既有约定单点
维护）与 `docs/CONTRIBUTING.md`。

## 1. 适用范围

`rpgmaker/inventory.py` 用 `superseded` 与 `dead` 标记被取代或无人使用的模块。
本政策定义这两种状态的两个字段：**弃用自哪个版本**与**何时可以删除**。

一个对象被弃用时，必须同时更新 §2 的三处记录；任一处漏掉都会被门禁挡下
（`tests/test_inventory.py` 与 `tests/test_changelog.py`）。

## 2. 三个记录位置

| 位置 | 写什么 | 由哪个门禁强制 |
|---|---|---|
| `rpgmaker/inventory.py` | 该模块的 `status` 改为 `superseded` 或 `dead`，`replacement` 写成**能解析到的真实目标**（模块路径或文件路径） | `replacement` 必填，且目标文件必须存在（`test_the_superseded_replacement_names_a_real_target`） |
| `CHANGELOG.md` | 「弃用」一节的条目，写明「旧入口 → 新入口」 | 与 inventory 的 `superseded`、`dead` 记录**双向一致**：有记录必须有条目，有条目必须仍是弃用状态 |
| 本文件 §6 | 该对象的**可删除条件**（个案） | 通用规则默认适用，个案必须在此登记 |

`replacement` 必须指向真实目标是因为曾有一条记录指向**从未存在**的文件，
门禁因此加了目标存在性断言。

## 3. 宽限期（默认规则）

默认：弃用后至少保留一个发布周期，且必须满足 §4 的可删除条件才可删除。

本仓库没有 git tag，也不使用发布日期，因此「一个发布周期」的可执行含义是：
弃用条目先提交，并至少经过一次完整的 CI 全矩阵（即 `main` 上跑过一次全绿），
之后才允许删除。这段窗口的作用是让一次真实构建暴露「还有谁在引用它」，而
CI 矩阵是唯一会真的去用它的地方。

不引入日期或版本号的硬性倒计时：`rpgmaker/__init__.py` 的 `__version__` 只随
打包需要变动，把它当倒计时会让「已过期所以可以删」变成一句没人验证的话。

## 4. 可删除条件

必须全部满足：

1. **零导入者**：`git grep` 找不到任何 `import <模块>` 或
   `from <模块> import`（对象自己的测试除外，它应当与被删对象一起删）。
2. **不在任何文档的命令行里**：`docs/`、`README.md`、`AGENTS.md` 中没有位置
   告诉操作员去运行它。若仍有文档指向它，删除的第一步是改文档，不是删代码。
3. **不被别的 `active` 记录当作替代目标引用**（在 `inventory.py` 里检查）。
4. **状态与记录齐全**：`superseded` 或 `dead` + 非空 `replacement` +
   CHANGELOG 条目。
5. **替代入口已被测试覆盖**：否则删掉旧入口可能连唯一能被调用的路径一起
   消失。

## 5. 删除清单

1. `git rm` 该模块及其独占的测试文件。
2. 删除只被它使用的 fixture 与测试辅助。
3. 从 `rpgmaker/inventory.py` 删除该 `Module` 记录。
4. 更新文档：`docs/reference/repo-layout.md` 的目录树、
   `docs/reference/support-matrix.md` 的退役对照表、相关教程里的命令示例。
5. 把 CHANGELOG 的「弃用」条目移入「删除」一节，不删条目：历史要留下。
6. 跑 `python -m tools.check_all`，修掉所有因「有人还在引用它」而变红的门禁。
7. 不得只为让门禁变绿而放宽门禁：仓库的 skip 预算、覆盖率下限、lint 计数
   预算都只能降不能升，为一次删除抬高它们等于把信号关掉。

## 6. 已弃用对象（登记）

| 对象 | 替代入口 | 状态 | 可删除条件 |
|---|---|---|---|
| `tools/plain_to_translated.py` | `translation.cli bake` | `superseded` | 确认非 MZ 引擎链不再引用旧 `===KEY===` 纯文本格式 |
| `tools/translate_rpgmaker.py` | `translation.cli prepare` | `superseded` | 仍被 `tools/bake_translation.py` 导入，删除前必须先迁移该调用 |
| `tools/gen_csv_shards.py` | `translation.cli slice` | `superseded` | 确认 CSV 分片链（非 MZ 引擎）已全部走 v2 |

`superseded/` 归档目录与 `tools/extract_text.py` 已删除，理由与过程记在
`CHANGELOG.md` 的「删除」一节；同一节还记录了随之删除的孤儿 fixture
`fake_powershell` 与被修正的一处假替代声明。

## 7. 不算弃用的情况

- **`maintenance` 状态**：事后数据修复类工具是**永久合法**状态，不是弃用的
  前一步。删掉它意味着下一次同类事故无法处理（规则见 `rpgmaker/inventory.py`）。
- **已退役的外部程序依赖**：`argparse`、`node --check`、`npx asar`、同侧
  `7z.exe` 这些是「不再需要安装什么」，对照表在
  `docs/reference/support-matrix.md` §8，不受本政策管辖。
- **归档文档**（`docs/archive/*.md`）：保留是为了留下教训，标注「不要照它
  执行」即可，不参与删除流程。
