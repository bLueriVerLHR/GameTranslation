# GameTranslation — 工作规则

本文件是**强制规则**的唯一权威位置。它是 agent 启动时自动加载的入口，所以
**只放规则与索引，不放操作细节**；各引擎的具体做法在 `docs/` 里，本文件
只链接。

| 想知道 | 看这里 |
|---|---|
| 仓库目录树（唯一权威） | `docs/reference/repo-layout.md` |
| 各引擎/能力/入口/状态的现状清单 | `docs/reference/support-matrix.md` |
| 本地私有数据放哪（`.private`/`.asset`/workspace） | `docs/reference/local-layout.md` |
| 文档导航（教程/操作指南/参考/原理） | `docs/index.md` |
| 文档写作规范 | `docs/reference/doc-style.md` |
| 打包与交付 | `docs/workflow.md` |
| 翻译（v2 唯一流程） | `docs/translation.md` |
| TyranoScript | `docs/tyrano.md` |
| KiriKiri 翻译 | `docs/kirikiri.md` |
| Wolf RPG | `docs/wolfrpg.md` |
| Unity（含 IL2CPP / RM Unite） | `docs/engines/unity.md` |
| 经验库（踩过的坑） | `docs/experience.md` |
| 贡献流程 | `docs/CONTRIBUTING.md` |

## 公开仓库卫生（mandatory）

本仓库公开托管在 GitHub（GameTranslation）。**任何文件**（代码、注释、
docs、README、commit message、文件名）都不允许出现下列内容；从具体游戏
工作中得到的经验，只能以「引擎 + 特征描述」的形式写入。

- **禁具体游戏名**：不得出现任何游戏名、系列代号、作者名、角色名、
  开发者标识。一律用引擎 + 特征描述，如 "Unity 6 IL2CPP + Addressables
  视觉小说"、"7 款同作者 RM Unite 短篇系列"、"MV `www/` 部署 +
  ExternMessage.csv"、"MZ MTool repack"。经验记录只写教训，不写是哪款
  游戏。
- **禁密码/密钥**：压缩包密码、默认密码、API key、token、私钥一律不写。
  密码类信息只放本地私有记录（workspace 内），绝不入库。
- **禁隐私**：本机路径（`C:\Users\<用户名>\`、`E:\`、个人盘符）、用户名、
  邮箱、telegram/社交链接等一律不写；路径用 `%LOCALAPPDATA%`、
  `<path-to-...>` 等通用形式，用户名用 `<user>` 占位。
- **禁版权风险内容**：不写盗版/破解渠道名（论坛名）、破解/绕版权相关
  表述、广告/推广渠道（推广文案、注册链接）。技术事实（插件名、引擎
  行为）可以写，但不带来源渠道与具体推广文件名。
- **禁色情内容**：不写露骨性词汇（身体部位/性行为名词的中日文写法）与
  成人题材专用缩写词；涉及成人内容一律用中性说法（adult scenes /
  成人内容）。
- **游戏专属数据一律本地化**：每游戏词表（glossary/tone/notes）、成人
  词表、作者名豁免表、系列预填字典等只放本地私有位置（逻辑位置见
  `docs/reference/local-layout.md`）或 work 目录，**绝不写入或提交**。
- **工具禁止硬编码游戏专属数据**：新写/改工具时，游戏专属参数（角色名
  表、作者名豁免、语气段、预填字典）一律走命令行参数/外部 JSON/
  `--exempt` 注入；不得把某款游戏的数据写死在脚本里（污染类 bug，见
  `docs/translation.md`）。
- **提交前自查（mandatory）**：分两部分。

  **（1）机器路径/用户名——自动化门禁**（可真正跑到零命中）：

  ```bash
  <venv-python> -m pytest tests/test_repo_hygiene.py -q
  ```

  该测试只扫 git 认可的文件（本地私有表目录已排除），允许本文件规定的
  占位符形式（`C:\Users\<用户名>\`、`/mnt/c/Users/<user>/`），并维护一份
  **显式的**测试合成用户名白名单；真实用户名/机器路径一律失败。需要人工
  确认时可跑
  `rg -nP 'C:\\Users\\(?![<「])|/mnt/[a-z]/Users/(?![<「])' --glob '!<本地私有表目录>/**' .`，
  但**规则文本与测试固件自身就会命中**，所以真正的门禁是上面那个测试。

  **（2）游戏名 / 成人词 / 推广词——词表对照**：用本地广告关键词表
  （每行一个关键词，逻辑位置见 `docs/reference/local-layout.md`）：
  `rg -n -f <广告关键词表> --glob '!<本地私有表目录>/**' .`。
  词表不存在时按「引擎 + 特征描述」原则人工复核。commit message 同样自查。

## 跨系统文件处理 — CRITICAL

**处理文件必须使用「文件所在系统」的原生应用。**

- 文件在 **Windows 侧**（`C:\`/`D:\`，WSL 里显示为 `/mnt/c`、`/mnt/d` 等）
  → 一律用 **Windows 侧的应用**处理：Windows `7z.exe`、Windows 版
  `python.exe`、PowerShell 脚本。从 WSL 调用统一走 `powershell.exe`，
  路径用 Windows 格式（`C:\...`，不要用 `/mnt/...`）。
- 文件在 **WSL 侧**（`/tmp`、`/home` 等 ext4 路径）→ 才允许用 WSL 内的
  工具（`7zz`、WSL 的 python）。

**明确禁止（MUST NOT）**：

1. WSL 内的 `7zz` 解压/压缩 Windows 侧的文件（包括 `/mnt/*` 路径）。
2. WSL 内的 python 脚本直接操作 Windows 侧的文件（包括 `/mnt/*` 路径；
   `shutil.rmtree` / 读写 `/mnt/*` 同样禁止）。

**事故记录**：曾有 agent 用 WSL 内的 7zz / python 直接处理 Windows 侧
文件（解压、脚本读写），造成电脑**花屏**的严重显示故障。本规则为 MUST
级，任何违背立即停止并上报 owner。

**正确姿势**：核心判据是**工具与其输入文件必须在同一平台**。跨系统只
允许「搬运」**单个压缩包**；一切「处理」（解压/压缩/脚本读写）都在文件
所在侧完成。Windows 侧文件需要处理时，从 WSL 经 `powershell.exe` 调
Windows 原生工具（路径用 Windows 格式），例如：

```bash
# <win7z> = 用 `python pipeline.py doctor` 查到的 Windows 7z.exe 路径
powershell.exe -NoProfile -Command \
  "& '<win7z>' x -y '-o<games_dir>' '<archives_dir>\game.7z'"
```

`rpgmaker/deliver.py` 已内置**自动桥接**：WSL 下对 Windows 侧（`/mnt/*`）
文件的删除/解压自动改用 Windows `7z.exe` / PowerShell `Remove-Item`（经
`powershell.exe` 调用，路径自动转 Windows 格式），无需手工介入。仅在两种
情况下拒绝：Windows 7z 缺失（`win_7z()` 的解析顺序是 `SEVENZ_WIN` 环境
变量 → 本地配置 `tools.win32.7z` → 探测 `Program Files`/`Programs` 下的
`7-Zip*`），或同一条 7z 命令的输入跨两侧混用（archive 与 dest 不同侧）。

## 本地私有数据 — 加载规则（mandatory）

仓库**不存放**任何真实本地数据（词表、密码、字体、每游戏资料）。布局、
路径解析顺序、字体策略、迁移映射的**唯一权威说明**是
`docs/reference/local-layout.md`；本节只说**什么时候必须去读**。

- **翻译开始前**：检查当前游戏的 workspace 是否有 `glossary.json`（注入
  词表）、`tone.md`（语气；`tools/gen_translation_shards.py` 把它注入块
  上下文，缺失时用中性默认）、`notes.md`（控制码/豁免清单等坑）；没有
  workspace 则以 work 目录的 `glossary.json` 为准，收尾时再同步。旧布局
  （每游戏子目录）见 `docs/reference/local-layout.md` §7 的迁移映射。
- **解压密码保护的压缩包时**：从本地密码表按来源特征匹配（执行时按引用
  读取，绝不写进构建产物或日志）。
- **打包/压缩前清理广告文件时**：对照本地广告关键词表（关键词与文件名
  清单）扫描并删除（仓库文档里不写具体文件名，以本地表为准）。
- **确定翻译风格时**：本地通用名词表（成人词表）是通用名词词表的唯一
  权威来源（**不在仓库里写死名称**——写死过的文件名曾与实际本地文件名
  不一致，见 `docs/translation.md`）。
- **依赖本地数据却找不到时**：任何 mandatory 步骤若只有 gitignored 数据
  才能完成（词表/字体/env 配置），**必须 WARN 并说明缺失了什么**，
  不得静默降级成空操作。

边界：该数据只允许 owner 修改（agent 只读），且**绝不写进仓库代码/文档/
commit**；提交前自查扫描时排除本地私有目录（见公开仓库卫生一节）。

## 开发流程 — 分支与提交（mandatory）

- **每次任务开新分支**，命名 `<罗马音代号>/<功能>`：代号取游戏/项目名的
  罗马音短名（约 5 个字母，如 SachiGame → `sachi`），功能如 `translation` /
  `development` / `clean` / `packaging`。不同功能开不同分支，绝不在主分支
  上直接改。
- **本地分支不推送**：feature 分支只在本地工作，不 push 到 GitHub。
- **main 保护（mandatory）**：**未获得代码审计/评阅之前，main 不得接受
  任何 commit**。改动一律在 `<代号>/<功能>` 分支上提交，审计/评阅通过后
  再合并回 main。
  - **机制**：仓库内 `.githooks/pre-commit` 在 main 上拒绝直接 commit；
    `MERGE_HEAD` 存在时放行，所以「用 `git commit` 收尾一次有冲突的合并」
    这个正途不被拦。
  - **启用方式**（每个克隆一次，配置本身不入库）：
    `git config core.hooksPath .githooks`。注意：一旦设了 `core.hooksPath`，
    git 就**完全忽略** `.git/hooks`，而版本化的 `.githooks/` 只存在于含它
    的分支上。所以开关前先确认当前分支确实有 `.githooks/pre-commit`
    （看 `git ls-files .githooks/`）；没有就**不要**设 `core.hooksPath`，
    改用与分支无关的兑底办法：把 `.githooks/pre-commit` 拷到
    `.git/hooks/pre-commit`。两种方式都不需要改仓库内容。
  - **紧急绕过**用 `git commit --no-verify`，并写明原因。
  - **审计/评阅由 owner 或 owner 指定的独立审阅者进行**：agent **不得**
    自己审自己然后把改动落到 main；自测与门禁全绿只是审阅的前置条件，
    不是审阅本身。
  - 待审改动的位置写在任务报告里（分支名 + 内容摘要），main 保持与
    `origin/main` 一致；未经审计不得在 main 上留下任何本地 commit。
- **完成后合并回主分支（main）**：`git checkout main` → `git merge <分支>`。
  允许多个 commit，无需 squash 成单一提交；每个功能/修复一个 commit，
  按逻辑拆分即可。
- **推送必须显式获准（mandatory）**：**绝不主动 push 到 GitHub**，只有
  owner 明确说「推送/push」时才推送，且只推主分支（main）；推送前必须先
  通过下方检查。提交者身份固定为 `agent <agent@localhost>`（仓库本地 git
  配置），不用 owner 的个人 git 身份。
- **合并前必须通过检查（mandatory）**：
  1. 卫生门禁（见公开仓库卫生一节）：`tests/test_repo_hygiene.py` 全绿；
  2. `python -m py_compile` 所有改动的 `.py`（工具可运行）；
  3. **lint**：`<venv-python> -m ruff check .` 全绿（规则钉在
     `pyproject.toml`：定位缺陷的 F/E9/B/C4/PIE/RET/UP/SIM/PERF，不选风格类；
     `UP031`/`UP030`/`SIM115` 选中但 ignore、由计数预算
     `[tool.gametranslation.lint-burndown]` 封顶，只能降不能升；
     `tests/test_lint.py` 会把同一命令当门禁跑，未装 ruff 则跳过）；
  4. 文档一致性：`python -m tools.check_docs`（目录树与仓库文件同步，
     解析 `docs/reference/repo-layout.md`）、文档语言为中文；
  5. **单元测试（mandatory）**：新功能/新工具必须写单元测试（`tests/`，
     pytest），**正例、反例、边缘情况都要覆盖**，提交前全绿——venv 解释器
     按平台取 `.venv/bin/python`（POSIX）或 `.venv\Scripts\python.exe`
     （Windows），命令形如 `<venv-python> -m pytest tests/`（默认 `-n auto`
     并行，`-n 0` 串行）。
- **既有约定单点维护（改代码前先看这两处）**：命令行与日志有唯一入口——
  新工具直接照 `rpgmaker/cliutil.py` 文档串的模板写（Typer +
  `main(argv=None)`，不再用 argparse），日志只用 `rpgmaker/logsetup.py`；
  外部程序/包也各有唯一入口（见 `docs/reference/tooling.md` 的「唯一入口」
  表），不得另起一套。
- 提交信息主要用中文描述，但不得含游戏名与敏感词。含 CJK 的提交信息用
  `git commit -F <file>` 传入（PowerShell heredoc 会把 CJK 变成 `?`，且
  `<` 是保留字）。

## Python 导入规则（mandatory）

- 生产模块、测试与测试子进程一律使用正规包导入，不允许通过修改 `sys.path`
  或注入仓库/`tools/` 的 `PYTHONPATH` 来补救导入；工具通过 `python -m`
  或已安装 CLI 启动，开发/测试先安装项目及所需 extra。
- pytest 使用 `--import-mode=importlib`；共享测试构造器放 `tests/helpers.py`，
  fixture 由 `tests/conftest.py` 注册，不把 conftest 当普通工具模块导入。
- 隔离 wheel 安装目标的路径配置与证明隔离有效的负例不属于导入补丁，必须
  保留其验证强度；仓库资源/固件定位使用根路径常量是允许的。
- `tests/test_import_contracts.py` 守卫测试导入；生产边界由
  `tests/test_package_boundaries.py` 守卫。

## 语言规则（mandatory）

- **代码文件**（`.py`/`.cs` 等）：代码与注释一律**英文**。唯一例外是
  **游戏内原生语言内容**——日文原文、假名/日文正则、日文样例（如
  `\N[1]`、`名前`、`<SG説明`），以及注入给翻译 agent 的 prompt/词表
  内容。**禁止中文注释**。
- **文档文件**（README、`docs/*.md`、AGENTS.md）：一律**中文**。
- 提交信息主要用中文描述（不含游戏名与敏感词）。

## 调试与日志（mandatory）

写/改任何工具（解包器、提取器、烘焙器等）时必须遵守：

- **日志等级区分用途**：`DEBUG` 只写诊断细节（中间变量、逐文件进度），
  `INFO` 写阶段与结果（文件数、键数、命中数），`WARN` 写可恢复异常
  （重试后成功、推测性跳过），`ERROR` 写失败。默认只显示 INFO 及以上，
  `--verbose`/`-v` 开 DEBUG。
- **配置只在一个地方**：`rpgmaker/logsetup.py` 的 `setup(verbose=...,
  quiet=..., log_file=...)`（时间戳+等级+logger 名，并顺带把控制台流改成
  UTF-8 `replace`，否则 Windows 上重定向输出遇到 CJK 会 UnicodeEncodeError
  而中断）。常用选项：`-v/--verbose` 开 DEBUG、`-q/--quiet` 只留 WARN/ERROR、
  `--log-file PATH` 同写一份文件、环境变量 `GT_LOG_LEVEL=debug` 临时改级别。
  **只能从 `main()` 调用，绝不能在 import 期配置**——import 期调用会改写
  整个进程（含 pytest 会话）的 root logger，并使 `setup()` 的再次调用静默失效。
  计时一个阶段用 `with logsetup.phase("名称", log):`（自动打 start/done +
  耗时）。任何模块都能通过正规包导入使用；工具统一以 `python -m <包.模块>`
  或已安装的 CLI 启动，不通过修改 `sys.path` 支持直接运行包内文件，也不再
  各自写 basicConfig。
- **CLI 的 `--help` 也要能打中文**：`--help` 由 CLI 框架在命令体执行前
  应答，早于 `logsetup.setup()`；`cliutil.run()` 会先调
  `logsetup.ensure_utf8_streams()` 修流。自定义入口（不走 `cliutil.run` 的
  `main()`）必须自己先修流，否则含 CJK 的 docstring / JSON 报告在 cp1252
  控制台上会直接崩溃；`tests/test_cli_smoke_entries.py` 强制覆盖这一点。
- **日志必须带定位信息**：文件路径（相对路径即可）、行号/偏移（用
  `文件名:行号` 或 `文件名:0x偏移` 格式）、可重试的具体原因，不写
  "Failed to read" 这种无法定位的裸报错。
- **调试期用局部脚本快速验证**：新算法先写一次性验证脚本（`python3 -c`
  或临时文件）打印关键中间字节（hex + repr 可读形式），确认格式假设后再
  固化进工具；验证通过即删。
- **二进制格式工具的输出必须可自检**：解包/解码类工具结束后打印汇总
  （文件数、字节数），解出可疑数据（全零、随机高熵）时 WARN 提示
  key/偏移可能错误。
- **失败模式记录进 `docs/experience-*.md`**（索引见 `docs/experience.md`）：
  格式坑、错误 key 的特征（解出的头部不是可读字节流等）要留档。

## 任务执行规则（mandatory）

1. **批处理前先采样测性能（mandatory）**：任何批量任务（解包、解码、
   重编码、翻译注入等）开工前，先采样处理 3-5 个代表性文件并测量耗时
   （per-file 时间、总量预估），向 owner 报告预计总时长与瓶颈；判断是否
   需要优化（JIT、C++ binding、并行、缓存等均可），确认后再全量跑。
2. **新功能必须带单元测试（mandatory）**：新工具/新功能写 `tests/`
   （pytest），**正例、反例、边缘情况都要覆盖**，提交前
   `<venv-python> -m pytest tests/` 全绿（venv 解释器按平台取，见开发
   流程一节）。
3. **排查问题用只读子代理并行（mandatory）**：多个独立疑点时，开多个
   **只读子代理**（各 harness 的叫法不同：只读/审阅型 agent）并行排查，
   缩短排查时间；各自结论汇总后交叉验证，不要串行逐个试。
4. **随机采样代替定点抽查（mandatory）**：检查文件质量（解码正确性、
   残留、格式异常等）时用**随机采样**（`random.sample`/`shuf`），绝不
   反复检查同一个已知正确的文件，也不在特例中挑文件——否则会系统性漏掉
   坏文件。
5. **速度优先，近源处理（mandatory）**：数据在 WSL 侧就用 WSL 内软件
   处理，在 Windows 侧就用 Windows 处理，只搬运必要的最小数据（优先单个
   压缩包）。
6. **截图 = 当前环境的浏览器自动化（mandatory）**：需要验证画面时用当前
   环境提供的浏览器/页面自动化能力（打开、点击、推进、填表）操作页面后
   截图；**无法完成的截图/操作任务必须停下请求 owner 参与**，不得假装
   完成。

## 画面验证（mandatory）

需要验证画面时用当前环境提供的**浏览器自动化能力**（打开、点击、填表、
推进、截图一体），**不自建窗口截图工具**；无法自动化的步骤停下请 owner
手动完成并告知。截图后**用当前环境可用的视觉路径读图**（能读图就把 PNG
交给读文件工具；若运行所用的模型确实没有视觉能力，就把路径交给 owner 并
明确说明「未能完成视觉验证」，绝不得假装完成）。互操作失效（`WSLInterop`
binfmt 条目缺失）时的修复命令写在 `docs/screenshot.md`。

## 引擎与能力（mandatory）

每个引擎只做「解包 → 文本提取 → 翻译 → 写回 → 打包交付」，**不做任何
运行时转换或移植**。能力与引擎的对应关系以
`docs/reference/support-matrix.md` 为准，代码侧唯一权威是
`rpgmaker/inventory.py` 的 `ENGINE_CAPABILITIES`（未知引擎**失效关闭**：
不静默继续）。

| 引擎 | 做什么 | 入口 | 做法见 |
|---|---|---|---|
| RPG Maker MZ/MV（HTML5） | 还原 launcher 打包的数据库、翻译与烘焙、清理、打包交付 | `pipeline.py`（`gt`） | `docs/workflow.md`、`docs/translation.md` |
| TyranoScript / TyranoBuilder | 解包 `app.asar`、`.ks` 翻译与写回、引擎 UI 本地化、清理、打包交付 | `tyrano/pipeline.py`（`gt-tyrano`） | `docs/tyrano.md` |
| KiriKiri2 / krkrz / KAG3 | 解包 `data.xp3`、`.ks` 翻译、写回 `patch.xp3`、字体合并 | `kirikiri/` | `docs/kirikiri.md` |
| Wolf RPG（ウディタ） | 解包、文本提取、翻译与补丁写回 | `wolfrpg/dxarchive.py` | `docs/wolfrpg.md` |
| Unity（Mono / IL2CPP / RM Unite） | 文本提取、翻译、运行时 hook 注入 | `unity/rmunite/` | `docs/engines/unity.md` |

**引擎边界（mandatory）**：Unity 与 Wolf RPG **绝不**跑 RPG Maker 专用
命令（`unpack-data`/`clean`/`compress`/`deliver` 对它们无意义且会破坏
目录），也绝不解密/重编码任何东西；KiriKiri 同样不用 RPG Maker 流水线。

**翻译口径（mandatory）**：repack 自带的 MTool 机翻一律**清除并自己翻译**；
注入给游戏的补丁内容由 owner 逐款给出。

**游戏特定特征**（引擎 + 特征案例、体量、坑）一律记录在**本地
workspace**（`notes.md`，见 `docs/reference/local-layout.md`），**不写进
仓库文档**；仓库只留引擎级通用知识，以「引擎 + 特征描述」形式。

## 路径与工具规则（mandatory）

- **路径配置只存一份（原生形式）**：Windows 侧资源写 `D:/..`/`C:/..`，
  WSL 侧写 `/tmp/..`；WSL 要用 Windows 侧路径时由代码转换
  （`rpgmaker/platform.py` 的 `localize()` → `to_wsl_path()`），**绝不把
  同一路径写两份**。工具按 `[platform][tool]` 索引（两侧二进制不同）。
  跨系统的同侧门岗在同一模块（`check_same_side()` / `PathRef`）。
- **工作副本一律放系统临时目录**（本机具体路径见本地环境配置的
  `deliverables.temp`），绝不放源目录旁边；成品放专门交付目录，命名
  `<Game>` / `<Game>.7z`；**绝不修改原版游戏目录**。
- **Windows 端下载/暂存**（Windows-only 工具、待处理内容）一律放
  `win_temp`（Windows 的 `%TEMP%`，代码里
  `rpgmaker/deliverables.py::win_temp_dir()`），**绝不放进成品目录或压缩包
  目录**。
- **工具/路径解析只在一处（mandatory）**：外部程序的解析统一走
  `rpgmaker/tool_registry.py` 的 `TOOLS` 表 + `resolve_tool()`，顺序为
  **环境变量 → 本地配置覆盖（可选，支持 `*` 通配）→ 探测常见安装位置
  → PATH**。新增/修改一个程序只改 `TOOLS` 一条，**不得**在别的模块里新写
  `shutil.which` / 自己的查找函数，也**不得**把机器路径写进代码或文档
  （探测代替硬编码）。每条条目必须带 `ToolStatus` 分级，并有至少一个真实
  调用者（无调用者的解析器 = 死代码，教训见 `docs/experience-misc.md`）。
  `pipeline.py doctor`（`--json` 机器可读）打印每个程序实际解析到的路径与
  来源，并按分级把缺失分成 `[MISS]`（`required`）与 `[WARN]`（其余）；
  排查「工具找不到」先跑它，不要搜盘。
- **功能优先用现成包，不自己造轮子（mandatory）**：同一个能力只能有一个
  封装层，且优先用维护中的包而非手写。**「能力 → 唯一入口 → 使用的包」
  对照表见 `docs/reference/tooling.md`**。新代码**不得**再自己拼外部程序
  的 argv、解它们的 stdout、或写第二份 `shutil.which`。例外（代码注释里
  写明原因）：**Windows 侧桥接**仍调 Windows `7z.exe` 与 PowerShell（见
  跨系统 CRITICAL 规则）。其余能力都在进程内实现：7z 归档走 `py7zr`，
  `app.asar` 走 `asar`，JS 语法检查走 `tree-sitter`，不再需要 Node.js /
  npx / ffprobe。
- **命令行约定（mandatory）**：每个工具都是 `rpgmaker/cliutil.py` 的
  Typer 命令，**不再用 argparse**：单命令工具用
  `app = cliutil.command_app(cmd, help=__doc__)`；子命令用
  `cliutil.app(help=__doc__)` + `@app.command()`（模板见该模块文档串）。
  每个工具保留 `def main(argv=None) -> int`，**命令里绝不调 `sys.exit()`**：
  失败用 `return cliutil.fail("…")` 或 `raise typer.Exit(code=N)`。日志选项
  统一用 `cliutil.Verbose` / `Quiet` / `LogFile`（即每个工具都有
  `-v` / `-q` / `--log-file`）。已知与 argparse 的差异（有意保留）：不再
  接受长选项缩写（`--outp`），用法错误提示换成框架文案（退出码仍是 2）。
- **本机环境配置是可选覆盖层**，不是必需条件：文件缺失时由探测 + 内置
  默认值接管。交付目录解析顺序为 环境变量 → 本地配置 → 探测已有惯例目录
  （工作区根即本库的**同级目录**下的 `Games`/`GamesCompress` 优先，再看各
  盘符根与家目录）→ 内置默认（同样是工作区根下这两个目录，按需创建）。
  代码按平台解析（`is_wsl()`），不硬编码本机路径。系统工具安装（如
  `pacman -S ...`）由 owner 执行，agent 不自行下载/提权。

## 打包规则（mandatory，压缩前必做）

打包/压缩前必须清理并核对（每款游戏都做）：

- **删除广告/推广文件**：根目录的推广文本（推广/注册链接类，具体文件名
  见本地广告关键词表）一律删除。
- **删除不必要的外部工具脚本**：MTool 注入残留——`与工具一同启动.bat`、
  `从游戏中移除工具文件.bat`、`winmm.dll`/`version.dll`/`injectPath`、
  游戏不引用的 MTool 运行时字典（根目录 `<title>.json` 且 js/index.html
  均无引用）等一律删除（先 `rg -l` 确认无引用再删）。
- **翻译 KV 随包归档**：若游戏已翻译（数据已烘焙中文），把翻译用的 KV
  （烘焙用的 `translated.json` 或等价 {ja→zh} 字典）放进游戏根目录一起
  打包，这样改译文或重译时不必重新提取整个游戏。`translation.cli bake` 会把
  `<work>/translated.json` 复制为游戏根目录的 `translation_kv.json`；
  `tools/bake_translation.py` 写同一个文件名到 `out_dir`，用 `--no-kv`
  关闭。未翻译的游戏不打此文件。
- **统一字体（mandatory）**：汉化构建必须应用统一字体策略——中文/拉丁/
  日文假名统一走项目标准中文字体，避免中文回退系统字体导致字形不统一。
  字体名、各引擎改动点、`required`/`auto`/`preserve` 三种策略与「已有
  翻译默认保留原字体、不得静默替换」的规则见
  `docs/reference/local-layout.md` §4–5 与本地字体策略表（不入库，缺失时
  **按 WARN 报出并跳过**，不得静默当成已应用）；MZ/MV 走
  `translation/bake.py` 标准字体策略，Tyrano 按本地策略表的 Tyrano 改动点
  （font.css @font-face + Config.tjs `;userFace=`）。
- **烘焙低覆盖率闸门（mandatory）**：静态烘焙（`tools/bake_translation.py`、
  `tools/augment_adv_resources.py`、`tools/bake_tyrano_dict.py`）在写入前
  做一次只读扫描（不复制、不写盘），统计字典对**游戏可译键表**的覆盖率
  （日志 `coverage: N/M keys translated = X%`）。**X < 50%**
  （`--min-coverage`，默认 0.5）**直接拒绝烘焙**——低覆盖烘焙 = 半日半中
  + 污染按块补翻（部分块值、半翻场景），正确路线是**放弃旧翻译
  文件，全量翻译**；故意的阶段一 harvest 烘焙用 `--force` 覆盖。
  **口径只能是键表**：不要用 bake 遍历时的 hit/miss 当口径，它把「整块
  拼接键」与 mvkeys 有意跳过的非显示串都算进分母。MZ/MV 的键表是
  `translation.mvkeys` 的可译串集合。
- **identity 条目（`v == k` 且含假名）自动剔除**：静态烘焙加载字典时删掉
  这类条目——它们会 shadow 逐行 fallback（块查找「成功」但文本还是日文）。
- **烘焙后必须回读比对（mandatory）**：五道门禁与覆盖率只证明**译库**
  完整，bake 本身可能静默跳过整类键——实测 System.json 字段表漂移
  （`element` vs `elements`、缺 `gameTitle`）导致标题/属性名在「100%
  覆盖」下仍是日文。烘焙后必须把译库每个键的 JSON 路径在构建里解析回来
  逐条比对（见 `docs/experience-translation.md`），不一致当失败处理。
  烘焙后验收继续跑
  `python -m tools.qc_build_kana <构建> --source <日文原版> --work <工作区>`。
- **名称引用自动检查（TE/namePop）**：`tools/bake_translation.py` 在烘焙
  尾部自动对照 `<TE:name>`/`<namePop:name>` 与全游戏事件名，失配的 dangling
  ref 逐一 WARN。

## 翻译流程（v2 — 唯一流程）

**翻译只走 `docs/translation.md` 的 v2：一个翻译执行者（单写者，磁盘状态
为权威）+ 文件信箱 + 五道硬门禁。不按 chunk 并行分发、不派发多个翻译
agent。**

```bash
python -m translation.cli prepare <game_dir> <work_dir>   # 提取 keys.jsonl + 控制码表 + 骨架 + MISSION.md
                                                          # 可选 --note-tags A,B：插件把 note 标签载荷当文本显示时打开
python -m translation.cli slice <work_dir> --start N --count M --lean --out <file>
python -m translation.cli append <work_dir> --batch <file> --fix-leading --note "..."
python -m translation.cli pending|decide|status|rewrite|to-json|gates <work_dir>
python -m translation.cli bake  <game_dir> <work_dir>     # 按 id 写回 + 统一字体 + KV 归档
```

- **编排者只做机械活**：提取、跑门禁、转 JSON、烘焙；语言判断全在执行者，
  其任务书是 `prepare` 生成的 `MISSION.md`。
- 唯一落盘入口是 `append`（逐条校验 id/非空/控制码逐字一致/假名残留，
  任何一条不过则整批不写盘）；五道硬门禁（`gates`：覆盖 / 控制码 / 假名
  残留 / 换行数一致 / 待决清零）全绿才能 `bake`；烘焙前自动备份到
  `<work>/backup/`。
- 统一字体是烘焙的强制步骤（本地字体策略表，见
  `docs/reference/local-layout.md` §5）。
- 数据契约（键表/译文库/控制码/写回）见 `docs/translation-data.md`；
  QC 与故障排除见 `docs/translation-qc.md`。

**体量协商（mandatory）**：启动翻译前先 `prepare` 量体量（键数 / 总字符
数），把规模报给 owner 取得**明确授权**（授权逐次，不是常设豁免）；大任务
在 work 目录留 `TRANSLATION_PROJECT.md` 记录进度。绝不自动开始大型翻译
任务。

**派发翻译执行者（mandatory）**：

- **一律 fresh 上下文，不 fork**——不把编排者的上下文投影给执行者
  （`worker` 这类内置代理的默认 context 是 `fork`，派发时**必须显式覆盖
  为 `context: "fresh"`**）。
- **提示词由编排者自己写全**：工作区、cwd、命令、契约文件（`MISSION.md` /
  `decisions.md` / `control_codes.md` / 本地词表）、**起点 seq**、每批流程
  （`slice` → 写批次文件 → `append --fix-leading`）、硬规则、回报格式。
  不要用「读某个任务书文件再照做」代替提示词，也不要把任务拆给多个执行者。
- 提示词里明确写「**开始翻译、按批落盘**」；下一次续跑时先算出**第一个
  未译 seq** 写进提示词，不要让新执行者自己猜起点。

**v1（切块 → 每块一个 subagent → ja/zh 双文件 → merge）已退役**，其工具
仅剩非 MZ 引擎（Tyrano / Wolf / KiriKiri）的提取/写回链在用，**不得再用
于 MZ 翻译**；完整归档见 `docs/archive/translation-v1.md`，失败模式教训
见 `docs/experience-translation.md`。

## 顺序

每款游戏沿一条链推进，`deliver` 放最后：

1. **解包**：launcher 把数据库打进 `<Game>.exe` 时先跑
   `gt unpack-data <game>`；Tyrano 的 `app.asar` 由提取步骤解包。
2. **提取与翻译**：`python -m translation.cli` 的 v2 流程 + `bake`。
3. **清理**：RPG Maker 用 `gt clean <game>`；Tyrano 用
   `gt-tyrano clean <out>`，引擎自带文案用 `gt-tyrano localize-ui <out>`。
4. **打包与交付**：`gt compress`（7z-zstd，进程内，写完自校验）→
   `gt deliver`（Tyrano 用 `gt-tyrano` 的同名命令）。`deliver` 做四件事：
   本地压缩 → 复制压缩包到压缩包目录（覆盖旧包）→ 删除成品目录里的旧
   文件夹 → 解压到成品目录，含压缩包完整性测试。
