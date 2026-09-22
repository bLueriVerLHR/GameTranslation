# 贡献指南（CONTRIBUTING）

本仓库是**公开托管**的本地工具库，规则一律以 `AGENTS.md` 为准；本文是
开发/文档贡献的速查版。改动任何内容（代码、文档、README、commit）都
必须遵守下面的分支 / 提交 / 卫生规则。

## 分支命名

- 每个任务开新分支，命名 `<罗马音代号>/<功能>`：
  - 代号取项目/功能的罗马音短名，约 5 个字母（如 `sachi`、`kirikiri`、
    `tyrano`、`wolf`）。
  - 功能如 `translation` / `development` / `audio` / `clean` / `docs` /
    `tests`。
- 不同功能开不同分支，**绝不在主分支上直接改**。
- 本地分支**不推送**到 GitHub（只在本地工作）。

## 提交信息规范

- 主要用**中文**描述，但不得含游戏名与敏感词（见下方自查）。
- 一个功能 / 修复一个提交，按逻辑拆分，不堆大杂烩提交。
- 允许一个分支多个 commit；合并回主分支无需 squash。
- 示例：
  - `新增：TyranoScript 构建的 mp3→ogg 音频重编码`
  - `修复：verify 对缺失引用的误报降级`
  - `文档：经验库按主题拆分`

## 敏感词自查（提交前 mandatory）

公开仓库**任何文件**（代码、注释、docs、README、commit message、文件名）
都不得出现：具体游戏名 / 系列代号 / 作者名 / 角色名 / 密码 / 密钥 /
本机路径（`C:\Users\<用户名>\`、个人盘符）/ 盗版渠道名 / 推广渠道名 /
露骨性词汇。经验教训只能以「引擎 + 特征描述」形式写（如
"Unity 6 IL2CPP + Addressables 视觉小说"、"MV `www/` 部署 +
ExternMessage.csv"）。

卫生门禁分两部分。

**(1) 机器路径 / 用户名——自动化**（`tests/test_repo_hygiene.py`，只扫 git
认可的文件、排除本地私有数据目录、允许占位符形式，维护显式的测试用户名
白名单）：

```bash
<venv-python> -m pytest tests/test_repo_hygiene.py -q
```

**(2) 游戏名 / 成人词 / 推广词——本地词表对照**（本地私有数据目录里的
广告关键词表，gitignored，每行一个关键词；路径见
`docs/reference/local-layout.md`）：

```bash
rg -n -f <关键词表> --glob '!<本地私有目录>/**' .
```

commit message 同样自查。注：不要用「裸 `rg` 扫规则文本自身」当门禁——
规则与测试固件里就写着这些字面量，那种扫永远不通过，真泄漏反而被淹没。

## 测试要求

- **新功能 / 新工具必须写单元测试**（`tests/`，pytest），**正例、反例、
  边缘情况都要覆盖**；提交前全量跑（venv 解释器按平台取，POSIX 为
  `.venv/bin/python`，Windows 为 `.venv\Scripts\python.exe`）：
  ```bash
  <venv-python> -m pytest tests/
  ```
- 集成测试在合成游戏上跑完整流水线（build → decrypt → clean → verify →
  serve → compress → deliver），全流程无外部依赖（`tests/fake_tools/`
  提供假 ffmpeg/7z）。
- 修改 `.py` 后先过 `python -m py_compile`（工具可运行）。
- **命令行统一用 `rpgmaker/cliutil.py`（Typer），不用 argparse**：
  单命令 `app = cliutil.command_app(cmd, help=__doc__)`，子命令
  `cliutil.app()` + `@app.command()`；每个工具保留 `def main(argv=None) -> int`
  （`cliutil.run` 在 argv 为 None 时读 `sys.argv`），**命令里不调 `sys.exit()`**
  （失败用 `return cliutil.fail("…")` 或 `raise typer.Exit(code=N)`）；日志选项
  统一用 `cliutil.Verbose` / `Quiet` / `LogFile`。模板见该模块文档串。
- **lint 用 ruff（规则钉在 `pyproject.toml`）**：
  ```bash
  <venv-python> -m ruff check .
  ```
  选择的是**定位缺陷与等语法**的规则（F 未定义名/未用导入与变量/重定义，
  E9 语法错误，B 循环变量捕获/bare except/无 `strict=` 的 zip/`raise` 丢失
  原因，C4 重复构造的内建，PIE 冗余写法，RET 只为 return 的赋值，UP 旧语法，
  SIM 等价但更短的写法，PERF 循环重复造轮子）；**不选风格类规则**
  （E402/E501/RUF/`I` 排序等）——否则仓库自己的书写习惯会全部报错
  （本机全局 ruff 配置 `select = ALL` 会报出 1112 条，绝大多数是风格）。
  但 `UP031`/`UP030`/`SIM115` 是「选中但被 ignore，用计数预算卡住」的：
  它们是纯现代化、本身不是缺陷，而全仓 ~640 处机械改写有真实行为风险
  （`"%d" % n` 变 `f"{n:d}"` 在 float 上会抛错而 `%d` 会截断），所以预算只能
  降不能升，见 `pyproject.toml` 的 `[tool.gametranslation.lint-burndown]`。
  `tests/test_lint.py` 会在装了 ruff 时把同一命令当作门禁跑（含预算只能降
  的那条断言）；未装 ruff（只装运行时依赖）则跳过。
- 批量任务开工前先**采样 3-5 个代表文件测性能**并向 owner 报告预计总时长
  与瓶颈；检查文件质量用**随机采样**，不反复检查同一已知正确的文件。

## 语言规则

- **代码文件**（`.py`/`.cs` 等）：代码与注释一律**英文**；唯一例外是
  游戏内原生语言内容（日文原文、假名/日文正则、日文样例、注入给翻译
  agent 的 prompt/词表）。**禁止中文注释**。
- **文档文件**（README、`docs/*.md`、AGENTS.md）：一律**中文**。
- 提交信息主要用中文（不含游戏名与敏感词）。

## 标准模板

新增能力的**步骤模板**。每条都点名必须先改哪个文件 —— 「照现有约定做」
这种写法等于没写，因为约定就散在那些文件里。

## 新增引擎

1. `rpgmaker/inventory.py`：先加 Module 记录（`status` 从 `active` 开始，
   填 `kind`/`engines`/`wheel`），并在 `ENGINE_CAPABILITIES` 里登记它与
   各能力的对应关系。**能力清单是失效关闭的**：未登记的引擎不会静默
   继续。
2. `docs/reference/support-matrix.md`：「各引擎/能力/入口/状态」表加行，
   写清哪些能力已验、哪些只写了代码没实测。
3. `docs/reference/repo-layout.md`：新增的包/目录必须进目录树，否则
   `tools/check_docs.py` 会报 `EXTRA`。
4. 若该引擎**不走某个现有流水线**（例如 Unity / Wolf RPG 绝不用 RPG Maker
   的 `build`/`decrypt`/`audio`），在 `AGENTS.md` 的引擎索引里写一句边界，
   并补一条「跨系统路径归属门禁」：入口函数开头调
   `platform.require_native_paths(...)`。
5. 测试：在 `tests/test_engine_ownership.py` 里为每个入口补正例与反例
   （跨侧输入必须在打开后端之前被拒）。

## 新增命令

1. 用 `rpgmaker/cliutil.py` 的约定，**不用 argparse**：单命令
   `app = cliutil.command_app(cmd, help=__doc__)`，多子命令
   `app = cliutil.app(help=__doc__)` + `@app.command()`。
2. 保留 `def main(argv=None) -> int`，命令体内**不调 `sys.exit()`**（失败用
   `return cliutil.fail("…")` 或 `raise typer.Exit(code=N)`）。
3. 日志选项直接用 `cliutil.Verbose` / `Quiet` / `LogFile`；日志本身只用
   `rpgmaker/logsetup.py`（**禁止在 import 期配置**，那只在 `main()` 里做）。
4. 命令若收路径参数，把它交给 `cliutil.own_paths(...)`（跨系统门禁），
   或在命令体第一句调平台检查；有理由不拦的要在测试里写明。
5. 测试：入口会被 `tests/test_cli_smoke_entries.py` 自动发现（`--help` 必须
   能打中文），路径门禁看 `tests/test_tool_ownership.py`。

## 新增测试

1. 新功能/新工具的测试写进 `tests/`，**正例、反例、边缘情况都要覆盖**；
   不要只测 happy path —— 本仓多个真缺陷（跨驱动器路径、裸分隔符串、
   被截断的 JSONL）都是反例才揭露的。
2. 能定位缺陷的断言优于「不报错」：比较具体字节/行号/报文，而不是
   `assert result`。
3. 新写的门禁要**真的反控过一次**：先制造一个会被它抓住的输入，确认它
   变红，再还原。否则你不知道它是检查了还是永远绿的。
4. marker：慢的测试打 `slow`，需要 Node/浏览器/真机/引擎运行时的分别打
   `node` / `browser` / `device` / `engine_runtime`，网络相关打 `wsl`；
   注册与分层规则见 `tests/test_test_layers.py`，skip 预算只降不升。
5. 提交前用 `tools/check_all.py` 跑全部门禁（它按依赖顺序跑，并会报出
   **缺哪个包**，避免「没检查」与「通过」看起来一样）；迭代期只需定向跑
   受影响的文件。

## 新增文档

1. 新文档落位：教程/操作指南/参考/原理四类，并在 `docs/index.md` 的
   「我想……」或「参考」表里加入口（没人链的文档等于不存在）。
2. 新文件必须同步进 `docs/reference/repo-layout.md` 目录树，否则
   `tools/check_docs.py` 报漂移；文档一律**中文**，代码注释一律英文。
3. 经验类内容（坑、失败模式）写 `docs/experience-*.md`（索引
   `docs/experience.md`），只写「引擎 + 特征描述」，不带具体游戏名 /
   作者 / 渠道 / 密码 / 本机路径。

## 新增 ADR

1. 只记录**已定案、影响面较大**的决策（一个决策一个文件）。
2. 落位 `docs/reference/adr/`，命名 `NNNN-短横线标题.md`，**编号不回收、
   不重排**；标题用英文短横线形式，正文用中文。
3. 同时更新 `docs/reference/adr/index.md` 的编号表（编号 / 标题 / 状态）。
4. 决策被推翻**不删旧文件**：把状态改成 `被 NNNN 取代` 再另写一篇说明
   为什么改。

## 合并 / 推送规则

- 完成后合并回主分支（main）：
  ```bash
  git checkout main
  git merge <分支>
  ```
- **绝不主动 push 到 GitHub** — 只有 owner 明确说"推送/push"时才推送，
  且只推主分支（main）；推送前必须通过上方检查。
- 提交者身份用本工具库的固定身份（与历史提交一致，见 `git log` 的 author），
  不用 owner 的个人 git 身份；仓库已配好时直接用仓库配置。

## 弃用与删除

- 取代某个工具/入口时，**先登记再说**：`rpgmaker/inventory.py` 状态改
  `superseded`/`dead` 并填真实存在的 `replacement`，同时在 `CHANGELOG.md`
  的「弃用」一节记下「旧入口 → 新入口」。这两处由
  `tests/test_inventory.py` 与 `tests/test_changelog.py` 双向校验。
- 什么条件下才能删、删除时的逐步清单，见
  `docs/reference/deprecation-policy.md`（**不要**只为让门禁变绿而放宽
  skip 预算 / 覆盖率下限 / lint 计数预算）。

## 文档贡献

- `docs/*.md` 均为中文；新增文档须同步更新 `README.md` 目录树（树与
  实际文件保持一致）。
- 经验类内容（坑、失败模式）写入经验库 `docs/experience-*.md`（各主题
  见 `docs/experience.md` 索引），只写「引擎 + 特征」，不带具体游戏名 /
  作者 / 渠道 / 密码。
- 游戏专属数据（词表、语气、游戏特定特征、成人词表）一律放本地
  **工作区**（每游戏一份）或**跨游戏通用词表目录**（长期共享），gitignored，
  绝不入库、绝不写进仓库文档——具体位置与解析顺序见
  `docs/reference/local-layout.md`。
