# 本地数据布局（参考）

本项目同时处理**仓库内的通用工具**与**不入库的本地私有数据**。本文件是后者
的唯一权威说明；`AGENTS.md` 的规则以本文为准。

核心原则：**仓库只放通用能力、schema 与示例；真实数据全部在仓库外或其
gitignored 子目录。**

## 1. 位置分类

| 位置 | 存放什么 | 生命周期 | 入库 |
|---|---|---|---|
| `.private/` | 跨游戏共享、长期保留的私密数据：词表、密码、本机配置 | 长期 | 否 |
| `.asset/` | 可复用的资源本体，即字体（带 `manifest.json`） | 长期 | 否 |
| workspace | 单个游戏的解包树、构建、缓存、日志、报告、该游戏的词表与语气 | 任务期 | 否 |
| `.tmp/` | 系统临时目录不可用时的**显式 fallback** | 任务期 | 否 |
| `.tools/` | 本机可执行工具、引擎测试运行时 | 可重建 | 否 |

`.private/` 不按游戏建子目录。游戏相关的东西跟随 workspace。

物理位置只有一处：`rpgmaker/settings.py` 的 `PRIVATE_PATHS` 把逻辑名映射到
路径，其他模块按名字取用，没有第二处拼接本地路径。

## 2. 目录结构

```text
.private/
├── config/
│   ├── environment.json      # 本机环境覆盖（交付目录、工具路径覆盖）
│   └── local_font_path.txt   # 字体路径覆盖：第一行中文字体，第二行日文回退
├── dictionaries/             # 通用名词表（通用资料的唯一权威来源）
└── secrets/
    └── passwords.*           # 压缩包密码表（按来源特征匹配）

.asset/
└── fonts/
    ├── manifest.json         # 字体清单（见 §4）
    └── <font files>

.private/README.md            # 目录说明与维护约定（本地文件）
.private/schema/              # 各 JSON 的 schema（仓库副本见 docs/reference/schema/）
```

## 3. workspace

workspace 是每个游戏一份的可抛弃状态，解析顺序如下：

1. CLI 上的 `--work-dir`
2. 环境变量 `GT_WORK_ROOT`（一个目录装多个 workspace）
3. 系统临时目录下的 `GameTranslation/`，即 `<系统临时目录>/GameTranslation/<workspace-id>/`
4. 仓库的 `.tmp/workspaces/` —— 只在调用方显式选择时使用

顺序与实现都在 `rpgmaker/workspace.py`（`resolve_workspace_dir`）。第 3 步是
工作副本的默认位置，第 4 步是兜底：临时目录不可写时，不该把多 GB 的副本
静默放进仓库所在卷。

workspace 内的文件分三类：

- **翻译 v2 状态文件**（`python -m translation.cli prepare` 创建，翻译执行者
  维护）：`keys.jsonl`、`control_codes.md`、`names_candidates.json`、
  `stats.json`、`allow_kana.json`、`MISSION.md`、`translations.raw.txt`、
  `progress.jsonl`、`pending.jsonl`、`rewrites.jsonl`、`memory.md`、
  `decisions.md`。
- **该游戏资料**（人工维护，工具按需读取）：`glossary.json`（注入词表）、
  `tone.md`（语气要求）、`notes.md`（该游戏的经验与坑）。
- **约定目录**：`source/`（工作副本或解包树）、`build/`（构建产物）、
  `cache/`（可重建中间产物）、`logs/`、`reports/`。

`workspace.json` 记录工作区元数据，schema 见
`docs/reference/schema/workspace.schema.json`，版本常量是
`rpgmaker/workspace.py` 的 `WORKSPACE_SCHEMA_VERSION`。

## 4. `.asset/fonts/manifest.json`

每个字体一条记录，至少包含：

| 字段 | 说明 |
|---|---|
| `id` | logical id，代码与策略引用它（如 `common-zh`），**不引用文件名** |
| `file` | 文件名（相对 `.asset/fonts/`） |
| `postscript_name` | PostScript 名 |
| `family` | 家族名 |
| `purpose` | 用途描述 |
| `license` | 许可（必须可再分发才允许打包进构建） |
| `sha256` | 校验和 |
| `coverage` | 字形覆盖说明（至少注明是否覆盖 GB 简体常用字） |

`coverage.covers_gb_simplified` 是三态：`true`、`false` 与「未声明」。未声明时
按未知处理并 WARN，不假设字体可用。

schema 与示例是 `docs/reference/schema/font-manifest.schema.json` 与
`docs/reference/schema/font-manifest.example.json`；校验实现在
`rpgmaker/fontpolicy.py`。缺 manifest、校验和不符，或在 `required` 模式下
找不到字体时，`doctor` 与 bake **失败**。

## 5. 字体策略

`--font-policy required|auto|preserve`：

| 策略 | 用于 | 行为 |
|---|---|---|
| `required` | 自行翻译并烘焙的游戏 | `translation.cli bake` 的默认策略；必须应用项目标准中文字体，找不到字体则失败 |
| `auto` | 游戏已自带翻译的游戏 | `translation.bake` 库函数的默认策略；只检查现有字体的中文字形覆盖，给出报告或 WARN，**不写文件** |
| `preserve` | 明确保留原字体 | 不检查、不改动 |

字体文件的解析顺序（`rpgmaker/fontpolicy.py` 的 `decide_font`）：

1. 命令行显式给出的字体路径（`python -m translation.cli bake --font`）
2. 环境变量 `CJK_FONT_PATH`
3. 本地字体路径文件 `.private/config/local_font_path.txt`（第一行中文字体，
   第二行日文回退；相对路径相对该文件自身解析）
4. `.asset/fonts/manifest.json` 里注册的字体
5. 无（调用方保留游戏自带字体）

要点：

- 「游戏已自带翻译」时默认**保留原字体**。把项目标准字体应用到这类游戏需要
  显式选择（`required` 或等价的显式选项），**不得静默替换**。
- 中文字形覆盖不足时，按 fallback 只做**加法**：日文字形保留原样，缺失的
  汉字回退到标准中文字体。
- 用哪个字体由 manifest 的 logical id 决定；各引擎的字体改动点写在各引擎的
  烘焙实现里。仓库代码与公开文档**不写死**本机路径、字体偏好或私有文件名。
- 字体名与各引擎改动点属本地资料：字体名以 manifest 的 logical id 为准，
  「哪个引擎改哪个点」写在本地字体策略表里（存放在 `.private/`，不入库）。
  该表缺失或策略未应用时，按 WARN 报出并跳过，不得当成已应用。

`doctor` 报告每个逻辑位置的解析结果与布局代次（新布局或旧回退）。

## 6. 密码处理

- 密码只存 `.private/secrets/`，**执行时按引用读取**；
- 绝不复制进 workspace 元数据、日志或提交信息；
- 日志中出现的密码一律按 `***` 处理。

## 7. 旧布局迁移（只读回退）

旧布局是单棵 `docs/table/` 树。代码读取的四个位置各有一个旧拼写，作为
**只读回退**：新位置不存在而旧位置存在时用旧位置。回退表在
`rpgmaker/settings.py` 的 `PRIVATE_PATHS`：

| 旧位置 | 新位置 |
|---|---|
| `docs/table/fonts/` | `.asset/fonts/` |
| `docs/table/3rd/` | `.tools/bin/` |
| `docs/table/env_config.json` | `.private/config/environment.json` |
| `docs/table/local_font_path.txt` | `.private/config/local_font_path.txt` |

每游戏资料（`docs/table/<Game>/*`）迁移到对应 workspace 的
`glossary.json`、`tone.md`、`notes.md`、`decisions.md`。

迁移工具要求：

- 先生成 **manifest 与冲突报告**；
- 默认 **copy + verify**（迁移后逐文件比对）；
- **不删除**旧目录；owner 确认后才清理源数据；
- 迁移只改读取位置，不改变任何运行时行为。

迁移期间两代布局都能工作。仓库代码与文档里没有任何旧目录拼接；迁移完成后
删掉回退表项即可，这是唯一需要改的地方。

## 8. 每游戏资料与经验

每游戏的词表、语气、经验教训只放 workspace，不入库。仓库文档只记录引擎级
通用知识，形式是「引擎 + 特征描述」。

系统临时目录不保证长期可靠：需要长期保留的每游戏词表与经验，由 owner 显式
导出到仓库外的备份位置。

## 9. 边界规则

- `.private/`、`.asset/`、`.tmp/`、`.tools/` 全部 gitignored；仓库只提交
  schema、示例与本文档。
- 依赖私有数据却找不到时，**必须 WARN 并说明缺失了什么**，不得静默降级。
