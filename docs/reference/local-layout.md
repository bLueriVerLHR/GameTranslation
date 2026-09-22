# 本地数据布局（参考）

本项目同时处理**仓库内的通用工具**与**不入库的本地私有数据**。这份文档
是后者的唯一权威说明；`AGENTS.md` 的规则以本文为准。

核心原则：**仓库只放通用能力 + schema + 示例；真实数据全部在仓库外或其
gitignored 子目录。**

## 1. 四类位置

| 位置 | 存放什么 | 生命周期 | 入库 |
|---|---|---|---|
| `.private/` | 跨游戏共享、长期保留的私密数据：词表、密码、本机配置、私有策略 | 长期 | 否 |
| `.asset/` | 可复用的资源本体，目前是字体（带 `manifest.json`） | 长期 | 否 |
| 系统临时目录 workspace | 单个游戏的解包树、构建、缓存、日志、报告、该游戏词表/语气/经验 | 任务期 | 否 |
| `.tmp/` | 无法用系统 Temp 时的**显式 fallback** | 任务期 | 否 |
| `.tools/` | 本机可执行工具、引擎测试运行时 | 可重建 | 否 |

`.private/` **不再按游戏建子目录**。游戏相关的东西跟随 workspace。

## 2. 目录结构

```text
.private/
├── config/
│   ├── environment.json      # 本机环境覆盖（交付目录、工具路径覆盖）
│   └── font-policy.json      # 字体策略：logical id 与各类任务的默认策略
├── dictionaries/             # 通用名词表（成人词表等通用资料的唯一权威来源）
└── secrets/
    └── passwords.*           # 压缩包密码表（按来源特征匹配）

.asset/
└── fonts/
    ├── manifest.json         # 字体清单（见 §4）
    └── <font files>

.private/README.md            # 目录说明与维护约定
.private/schema/              # 各 JSON 的 schema（本地副本）
```

workspace（默认 `<系统临时目录>/GameTranslation/workspaces/<workspace-id>/`）：

```text
<workspace-id>/
├── workspace.json     # schema 版本、engine、source fingerprint、时间、状态
├── profile.json       # 本次任务参数（禁止写密码明文）
├── glossary.json      # 该游戏术语/人名
├── tone.md            # 该游戏语气/风格要求
├── notes.md           # 该游戏的经验与坑
├── decisions.md       # 术语决策记录
├── source/            # 工作副本或解包树
├── build/             # 构建产物
├── cache/             # 可重建中间产物
├── logs/
└── reports/
```

## 3. workspace 解析顺序

1. CLI `--work-dir`
2. 环境变量 `GT_WORK_ROOT`
3. 系统临时目录下的 `GameTranslation/workspaces/`
4. 仓库 `.tmp/workspaces/` —— **仅在显式配置时**使用

## 4. `.asset/fonts/manifest.json`

每个字体一条记录，至少包含：

| 字段 | 说明 |
|---|---|
| `id` | logical id，代码与策略表引用它（如 `common-zh`），**不引用文件名** |
| `file` | 文件名（相对 `.asset/fonts/`） |
| `postscript_name` | PostScript 名 |
| `family` | 家族名 |
| `purpose` | 用途描述 |
| `license` | 许可（必须可再分发才允许打包进构建） |
| `sha256` | 校验和 |
| `coverage` | 字形覆盖说明（至少注明是否覆盖 GB 简体常用字） |

缺 manifest、校验和不符，或在 `required` 模式下找不到字体时，
`doctor` / bake **必须失败**。

## 5. 字体策略

`--font-policy required|auto|preserve`：

| 策略 | 用于 | 行为 |
|---|---|---|
| `required` | **自行翻译并构建的游戏（默认）** | 必须应用项目标准中文字体；找不到字体则失败 |
| `auto` | **游戏已自带翻译（默认）** | 只检查现有字体的中文字形覆盖，给出报告/WARN，**不写文件** |
| `preserve` | 明确保留原字体 | 不检查、不改动 |

要点：

- 「游戏已自带翻译」时，默认**保留原字体**；把项目标准字体应用到这类游戏
  需要 owner 显式选择（用 `required` 或等价显式选项），**不得静默替换**。
- 中文字形覆盖不足时，按 fallback 只做**加法**：日文字形保留原样，缺失的
  汉字回退到标准中文字体。
- 字体名与「哪个引擎改哪个点」写在 `.private/config/font-policy.json`
  （本地策略），**不写进仓库代码或公开文档**。

## 6. 密码处理

- 密码只存 `.private/secrets/`，**执行时按引用读取**；
- 绝不复制进 `workspace.json`、`profile.json`、日志或提交信息；
- 日志中出现的密码一律按 `***` 处理。

## 7. 从旧布局迁移

旧的 `docs/table/` 只作为**迁移源**，完成迁移后必须删除其运行时读取逻辑
与文档引用。

```text
docs/table/env_config.json       -> .private/config/environment.json
docs/table/passwords.md          -> .private/secrets/passwords.*
docs/table/<通用名词表>          -> .private/dictionaries/
docs/table/font_rollback.md      -> .private/config/font-policy.json
docs/table/fonts/*               -> .asset/fonts/
docs/table/<Game>/*              -> <workspace>/glossary|tone|notes|decisions
```

迁移工具要求：

- 先生成 **manifest 和冲突报告**；
- 默认 **copy + verify**（迁移后逐文件比对）；
- **不删除**旧目录；owner 确认后才清理源数据；
- 迁移本身不改变任何运行时行为（改的是读取位置，不是内容）。

迁移期间**两代布局都能工作**：`rpgmaker/settings.py` 的 `PRIVATE_PATHS` 是
代码里唯一知道物理位置的地方，每个逻辑位置都带一个旧路径作为**只读回退**
（当前路径不存在、旧路径存在时用旧路径）。所以仓库代码和文档里**没有**
任何旧目录拼接；迁移完成后删掉回退表项即可（这是唯一需要改的地方）。

迁移完成后的仓库侧收尾（属于计划内的一次性清理，不改变行为）：

## 8. 管理命令

```text
gt workspace list            # 列出 workspace（id、引擎、状态、大小）
gt workspace info <id>       # 显示单个 workspace 的元数据
gt workspace clean           # 清理（默认 dry-run）
```

`clean` 默认 **dry-run** 并**保留未交付/未导出的 workspace**；真正删除需要
显式 `--yes`。

## 9. 边界规则

- `.private/`、`.asset/`、`.tmp/`、`.tools/` 全部 gitignored；仓库只提交
  schema、示例与本文档。
- 系统 Temp 不保证永久可靠：需要长期保留的每游戏词表/经验，由 owner
  显式导出到仓库外备份位置。
- 代码与公开文档**不写死**本机路径、用户名、字体偏好或私有文件名——一律
  走 `.private/config/` 与 `.asset/fonts/manifest.json`。
- 依赖私有数据却找不到时，**必须 WARN 并说明缺失了什么**，不得静默降级。
