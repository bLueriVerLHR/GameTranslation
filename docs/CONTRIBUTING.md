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
认可的文件、`docs/table/**` 除外、允许占位符形式，维护显式的测试用户名
白名单）：

```bash
<venv-python> -m pytest tests/test_repo_hygiene.py -q
```

**(2) 游戏名 / 成人词 / 推广词——本地词表对照**（`docs/table/ad_keywords.md`，
gitignored，每行一个关键词）：

```bash
rg -n -f docs/table/ad_keywords.md --glob '!docs/table/**' .
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
  提供假 ffmpeg/ffprobe/7z）。
- 修改 `.py` 后先过 `python -m py_compile`（工具可运行）。
- 批量任务开工前先**采样 3-5 个代表文件测性能**并向 owner 报告预计总时长
  与瓶颈；检查文件质量用**随机采样**，不反复检查同一已知正确的文件。

## 语言规则

- **代码文件**（`.py`/`.cs` 等）：代码与注释一律**英文**；唯一例外是
  游戏内原生语言内容（日文原文、假名/日文正则、日文样例、注入给翻译
  agent 的 prompt/词表）。**禁止中文注释**。
- **文档文件**（README、`docs/*.md`、AGENTS.md）：一律**中文**。
- 提交信息主要用中文（不含游戏名与敏感词）。

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

## 文档贡献

- `docs/*.md` 均为中文；新增文档须同步更新 `README.md` 目录树（树与
  实际文件保持一致）。
- 经验类内容（坑、失败模式）写入经验库 `docs/experience-*.md`（各主题
  见 `docs/experience.md` 索引），只写「引擎 + 特征」，不带具体游戏名 /
  作者 / 渠道 / 密码。
- 游戏专属数据（词表、语气、游戏特定特征、成人词表）一律放本地
  `docs/table/<Game>/`（gitignored，绝不入库、绝不写进仓库文档）。
