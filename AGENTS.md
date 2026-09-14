# GameTranslation — 工作规则

针对本工具库的每次转换会话规则。

## 公开仓库卫生 (mandatory — 本仓库公开托管在 GitHub，新增/修改任何内容都必须遵守)

本仓库会公开推送到 GitHub（GameTranslation）。**任何文件**（代码、注释、
docs、README、commit message、文件名）都不允许出现以下内容；游戏会话中
产出的经验教训只能以「引擎 + 特征描述」的形式写入：

- **禁具体游戏名**: 不得出现任何游戏名、系列代号、作者名、角色名、
  开发者标识。一律用引擎+特征描述,如 "Unity 6 IL2CPP + Addressables
  视觉小说"、"7 款同作者 RM Unite 短篇系列"、"MV `www/` 部署 +
  ExternMessage.csv"、"MZ MTool repack"。经验记录只写教训，不写是哪款游戏。
- **禁密码/密钥**: 压缩包密码、默认密码、API key、token、私钥一律不写。
  密码类信息只放本地私有记录（workspace 内），绝不入库。
- **禁隐私**: 本机路径（`C:\Users\<用户名>\`、`E:\`、个人盘符）、用户名、
  邮箱、telegram/社交链接等一律不写；路径用 `%LOCALAPPDATA%`、
  `<path-to-...>` 等通用形式，用户名用 `<user>` 占位。
- **禁版权风险内容**: 不写盗版/破解渠道名（论坛名）、破解/绕版权
  相关表述、广告/推广渠道（推广文案、注册链接）。技术事实（插件名、引擎
  行为）可以写，但不要带来源渠道与具体推广文件名。
- **禁色情内容**: 不写露骨性词汇（身体部位/性行为名词的中日文写法）与
  成人题材专用缩写词；涉及成人内容一律用中性说法（adult scenes /
  成人内容）。
- **游戏专属数据一律本地化**: 每游戏词表（glossary/tone/notes）、成人
  词表、作者名豁免表、系列预填字典等只放本地 `docs/table/`（gitignored）
  或 work 目录，**绝不写入或提交**。
- **工具禁止硬编码游戏专属数据**: 新写/改工具时，游戏专属参数（角色名表、
  作者名豁免、语气段、预填字典）一律走命令行参数/外部 JSON/`--exempt`
  注入；不得把某款游戏的数据写死在脚本里（污染类 bug，见
  `docs/translation.md` §3）。
- **提交前自查 (mandatory)**: 分两部分。

  **(1) 机器路径/用户名——自动化门禁**（可真正跑到零命中）:

  ```bash
  <venv-python> -m pytest tests/test_repo_hygiene.py -q
  ```

  该测试只扫 git 认可的文件（`docs/table/**` 已排除），允许 AGENTS.md
  规定的占位符形式（`C:\Users\<用户名>\`、`/mnt/c/Users/<user>/`），
  并维护一份**显式的**测试合成用户名白名单；真实用户名/机器路径一律
  失败。若需人工确认，可直接跑
  `rg -nP 'C:\\Users\\(?![<「])|/mnt/[a-z]/Users/(?![<「])' --glob '!docs/table/**' .`，
  但请注意**规则文本与测试固件自身就会命中**，所以真正的门禁是上面那个
  测试。

  **(2) 游戏名 / 成人词 / 推广词——词表对照**：用本地词表
  `docs/table/ad_keywords.md`（gitignored，每行一个关键词）：
  `rg -n -f docs/table/ad_keywords.md --glob '!docs/table/**' .`；
  词表不存在时按「引擎 + 特征描述」原则人工复核。commit message 同样自查。

## 跨系统文件处理 — CRITICAL（MUST，2026-08 定案）

**处理文件必须使用「文件所在系统」的原生应用**：

- 文件在 **Windows 侧**（`C:\`/`D:\`，WSL 里显示为 `/mnt/c`、`/mnt/d`
  等）→ 一律用 **Windows 侧的应用**处理：Windows `7z.exe`、Windows 版
  `python.exe`、PowerShell 脚本。从 WSL 调用统一走 `powershell.exe`，
  路径用 Windows 格式（`C:\...`，不要用 `/mnt/...`）。
- 文件在 **WSL 侧**（`/tmp`、`/home` 等 ext4 路径）→ 才允许用 WSL 内的
  工具（`7zz`、WSL 的 python）。

**明确禁止（MUST NOT）**：

1. **WSL 内的 `7zz` 解压/压缩 Windows 侧的文件**（包括 `/mnt/*` 路径）。
2. **WSL 内的 python 脚本直接操作 Windows 侧的文件**（包括 `/mnt/*`
   路径；`shutil.rmtree` / 读写 `/mnt/*` 同样禁止）。

**事故记录（2026-08）**：曾有 agent 用 WSL 内 7zz / python 直接处理
Windows 侧文件（解压、脚本读写），造成电脑**花屏**的严重显示故障。
本规则为 MUST 级，任何违背立即停止并上报 owner。

**正确姿势**：核心判据——**工具与其输入文件必须在同一平台**。跨系统只
允许「搬运」**单个压缩包**；一切「处理」（解压/压缩/脚本读写）都在文件
所在侧完成。Windows 侧文件需要处理时，从 WSL 经 `powershell.exe` 调
Windows 原生工具（路径用 Windows 格式），例如：

```bash
# <win7z> = 用 `python pipeline.py doctor` 查到的 Windows 7z.exe 路径
powershell.exe -NoProfile -Command \
  "& '<win7z>' x -y '-o<games_dir>' '<archives_dir>\game.7z'"
```

`rpgmaker/deliver.py` 已内置**自动桥接**：WSL 下对 Windows 侧（`/mnt/*`）
文件的删除/解压自动改用 Windows 7z.exe / PowerShell `Remove-Item`（经
`powershell.exe` 调用，路径自动转 Windows 格式），无需手工介入；仅当
Windows 7z（`win_7z()` 解析：`SEVENZ_WIN` 环境变量 → 本地配置
`tools.win32.7z` → 探测 `Program Files`/`Programs` 下的 `7-Zip*`）缺失、
或同一 7z 命令的输入跨两侧混用（archive 与 dest 不同侧）时才拒绝。

## 本地名词表 docs/table/ — 加载规则 (mandatory)

`docs/table/` 是**本地名词表/翻译资料库**（gitignored，不入库不推送），
会话中需要它的信息时**主动去读**，不是可选项：

```
docs/table/
├── README.md           # 目录说明与维护约定
├── ad_keywords.md      # 广告/推广关键词与文件名清单（打包前清理对照）
├── passwords.md        # 常用压缩包密码表（解压 `7z x -p<pass>` 用）
├── <通用名词词表>.md   # 通用名词词表（成人词表，仅本地；实际文件名以本
│                       #   目录 README.md 为准，不要在仓库里写死名称）
├── env_config.json     # 本机环境覆盖（可选，缺失时靠探测 + 默认值）
├── font_rollback.md    # 统一字体策略的字体名与各引擎改动点（可选）
├── fonts/              # 打包字体（自动发现，不写绝对路径）
└── <Game>/             # 每款游戏一个子目录（<Game> 用本地代号，如工作目录名）
    ├── glossary.json   # 术语/人名 KV
    ├── tone.md         # 语气/风格要求
    ├── terms.json      # 术语决策记录
    └── notes.md        # 该游戏的经验与坑
```

必须加载的场景：

- **翻译会话开始前**: 检查 `docs/table/<Game>/` 是否存在该游戏的子目录，
  存在则读取 `glossary.json`（注入词表）、`tone.md`（语气，分片时写入
  chunk context）、`notes.md`（控制码/豁免清单等坑）；不存在则本次翻译的
  词表以 work 目录的 `glossary.json` 为准，收尾时再同步过来。
- **解压密码保护的压缩包时**: 查 `docs/table/passwords.md`（按来源特征
  匹配密码）。
- **打包/压缩前清理广告文件时**: 对照 `docs/table/ad_keywords.md` 的关键词
  与文件名清单扫描并删除（仓库文档里不写具体文件名，以本表为准）。
- **翻译风格定案时**: `docs/table/` 下的**通用名词词表**（成人词表）是通用
  名词词表的唯一权威来源（具体文件名以 `docs/table/README.md` 为准，
  **不在仓库里写死**——写死过的文件名曾与实际本地文件名不一致，
  见 `docs/translation.md` §6）。
- **依赖本地数据却找不到时**: 任何 mandatory 步骤若只有 gitignored 数据
  才能完成（词表/字体/env_config），**必须 WARN 并说明缺失了什么**，
  不得静默降级成空操作。

维护与边界:

- 只允许 owner 通过 edit 工具修改（agent 只读）。
- **该目录内容绝不写进仓库代码/文档/commit**；提交前自查扫描时排除
  `docs/table/**`（见上节）。

## 开发流程（分支/提交, mandatory）

- **每次任务开新分支**，命名 `<罗马音代号>/<功能>`：代号取游戏/项目名的
  罗马音短名（约 5 个字母，如 SachiGame → `sachi`），功能如
  `translation` / `development` / `audio` / `clean`。不同功能开不同分支，
  绝不在主分支上直接改。
- **本地分支不推送**：feature 分支只在本地工作，不 push 到 GitHub。
- **完成后合并回主分支（main）**：
  `git checkout main` → `git merge <分支>` — 允许多个 commit，无需 squash
  成单一提交；每个功能/修复一个提交，按逻辑拆分即可。
- **推送必须显式获准（mandatory）**：**绝不主动 push 到 GitHub** —
  只有 owner 明确说"推送/push"时才推送，且只推主分支（main）；推送前
  必须先通过下方检查。提交者身份用本工具库的固定身份（与历史提交一致，
  见 `git log` 的 author），不用 owner 的个人 git 身份。
- **合并前必须通过检查（mandatory）**：
  1. 卫生门禁（见上节第一条）：`tests/test_repo_hygiene.py` 全绿；
  2. `python -m py_compile` 所有改动的 `.py`（工具可运行）；
  3. 文档一致性：`python tools/check_docs.py`（README 目录树与仓库文件
     同步）、文档语言为中文；
  4. **单元测试（mandatory，2026-08 定案）**：新功能/新工具必须写单元
     测试（`tests/`，pytest），**正例、反例、边缘情况都要覆盖**，提交前
     全绿——venv 解释器按平台取 `.venv/bin/python`（POSIX）或
     `.venv\Scripts\python.exe`（Windows），命令形如
     `<venv-python> -m pytest tests/`。
- 提交信息主要用中文描述，但不得含游戏名与敏感词。

## 语言规则（mandatory）

- **代码文件**（`.py`/`.cs` 等）：代码与注释一律**英文**。唯一例外是
  **游戏内原生语言内容**——日文原文、假名/日文正则、日文样例（如
  `\N[1]`、`名前`、`<SG説明`），以及注入给翻译 agent 的 prompt/词表
  内容。**禁止中文注释**。
- **文档文件**（README、`docs/*.md`、AGENTS.md）：一律**中文**。
- 提交信息主要用中文描述（不含游戏名与敏感词）。

## 调试与日志（mandatory — 2026-08 定案）

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
  整个进程（含 pytest 会话）的 root logger，并让后续配置静默失效。
  计时一个阶段用 `with logsetup.phase("名称", log):`（自动打 start/done +
  耗时）。任何模块都能用（可直接从自身目录运行的 7 个模块也统一了：它们
  用 `sys.path.append(repo_root)` 后 import 本模块，不再各自写 basicConfig）。
- **调试与日志**
- **日志必须带定位信息**：文件路径（相对路径即可）、行号/偏移（用
  `文件名:行号` 或 `文件名:0x偏移` 格式）、可重试的具体原因，不写
  "Failed to read" 这种无法定位的裸报错。
- **调试期用局部脚本快速验证**：新算法先写一次性验证脚本（
  `python3 -c` 或临时文件）打印关键中间字节（hex + repr 可读形式），
  确认格式假设后再固化进工具；验证通过即删。
- **二进制格式工具的输出必须可自检**：解包/解码类工具结束后打印
  汇总（文件数、字节数），解出可疑数据（全零、随机高熵）时 WARN 提示
  key/偏移可能错误。
- **失败模式记录进 docs/experience-*.md（索引见 docs/experience.md）**：踩过的格式坑、错误 key 的特征
  （解出的头部不是可读字节流等）要留档，避免后人重走弯路。

## 任务执行规则（mandatory — 2026-08 定案）

1. **批处理前先采样测性能（mandatory）**：任何批量任务（解包、解码、
   重编码、翻译注入等）开工前，先采样处理 3-5 个代表性文件并测量
   耗时（per-file 时间、总量预估），向 owner 报告预计总时长与瓶颈；
   判断是否需要优化（JIT、C++ binding、并行、缓存等均可），确认后再
   全量跑。
2. **新功能必须带单元测试（mandatory）**：新工具/新功能写
   `tests/`（pytest），**正例、反例、边缘情况都要覆盖**，提交前
   `<venv-python> -m pytest tests/` 全绿（venv 解释器按平台取，见上）。
3. **排查问题用只读子代理并行（mandatory）**：多个独立疑点时，开多个
   **只读子代理**（各 harness 的叫法不同：只读/审阅型 agent）并行排查，
   缩短排查时间；各自结论汇总后交叉验证，不要串行逐个试。
4. **随机采样代替定点抽查（mandatory）**：检查文件质量（解码正确性、
   残留、格式异常等）时用**随机采样**（`random.sample`/`shuf`），
   绝不反复检查同一个已知正确的文件，也不在特例中挑文件——否则会
   系统性漏掉坏文件。
5. **速度优先，近源处理（mandatory）**：数据在 WSL 侧就用 WSL 内软件
   处理，在 Windows 侧就用 Windows 处理，只搬运必要的最小数据（优先
   单个压缩包）。**当前研究重点：打造一套 WSL 内的工具链**（解包/
   解码/转换），减少对 Windows 侧工具的依赖。
6. **截图 = WSL 内控制外部应用（mandatory）**：需要验证画面时，由 WSL
   内脚本（如 `tools/wsl_capture.py`）控制外部浏览器/应用执行对应操作
   （启动、点击、推进）后对窗口截图；**无法完成的截图/操作任务必须
   停下请求 owner 参与**，不得假装完成。

## 运行验证截图（窗口级，2026-08 定案）

需要截取**指定 app 窗口**（游戏运行画面、对话框、报错弹窗）时用
`tools/wsl_capture.py`（自动部署 `tools/capture_window.ps1` 到 Windows
临时目录；窗口自动移入可视区 + PrintWindow 捕获，被遮挡也能截）。
**操作步骤（点击/推进/输入）由 WSL 内脚本控制外部应用执行**（如
PowerShell `AppActivate` + SendKeys、浏览器 CDP/命令行参数），操作后
再截图；无法自动化的步骤停下请 owner 手动完成并告知。
完整流程/前提/排查见 `docs/screenshot.md`；截图后**用当前 harness 可用的
视觉路径读图**（本工具库的主模型支持图片输入，可直接把 PNG 交给 `read`
工具；若某次运行的模型确实没有视觉能力，就把路径交给 owner 并明确说明
「未能完成视觉验证」，绝不得假装完成）。互操作失效（`WSLInterop` binfmt
条目缺失）时的修复命令也写在 docs/screenshot.md。


## 转换目标

转换目的（2026-09 更新），按游戏类别与当前任务选择：

1. **HTML5 系游戏（RPG Maker MZ/MV 网页版）→ 可玩的 JoiPlay 构建**：
   剥离桌面运行时（NW.js）、解密（仅 easy）、压缩音频、清理、验证、
   7z-zstd 打包。做让游戏能在 Android 的 JoiPlay 里跑起来所需的最小工作。
2. **TyranoScript / TyranoBuilder 游戏（Electron 打包的 HTML5 视觉小说）
   → 可玩的 JoiPlay 构建 + 翻译**：解包 app.asar（用 `asar` 包，不重复
   造轮子，也不再需要 Node.js）、剥 Electron 运行时、存档改 webstorage、
   mp3→ogg + scenario 引用同步重写、MTool 残留清理、验证（`tyrano/pipeline.py`，
   完整指南 `docs/tyrano.md`）；翻译走统一 chunk 流程写回 .ks。
3. **Unity / Wolf RPG 游戏 → 翻译 + 注入**（**不做 JoiPlay 转换**）：
   解包 → 提取 → 翻译（**清除 MTool 机翻，自己翻译**）→ 运行时 hook /
   补丁注入。翻译能力按具体游戏持续优化，打补丁内容由 owner 逐款给出。
4. **KiriKiri2 / KAG3 → TyranoScript → Android JoiPlay（当前主线）**：
   使用 `kirikiri/convert_kag.py`，保留原作图层、排版、音画时序与交互体验。
   先定位可复现差异，用合成数据回归测试，再在工作副本验证；未经运行验证
   不得声称恢复原作体验。浏览器验证与 Android JoiPlay 实机验收分别记录。
   无法等价实现的行为必须记录影响和取舍，不能把空操作当成功。详见
   `docs/kirikiri-tyrano.md`。桌面翻译仍可选择 `patch.xp3` 路线。

**游戏特定特征（引擎+特征案例、体量、坑）一律记录在本地
`docs/table/<Game>/notes.md`，不写进仓库文档**（仓库只留引擎级通用知识，
以「引擎 + 特征描述」形式，见公开仓库卫生）。

## 解密规则

默认只在游戏是 RPG Maker MZ/MV 且为 **easy** 加密时运行 `decrypt`——
即每个加密资源都带标准 16 字节 RPGMV 头（原装 MZ/MV 加密）。此时
`decrypt` 是正常流水线步骤。

以下情况跳过 `decrypt`：

- 引擎不是 RPG Maker MZ/MV，或
- 游戏使用复杂/自定义/插件加密（任何资源缺少 RPGMV 头）：`decrypt`
  对这类文件原样保留并保持 System.json 标志位，因此运行它不会改变
  构建。

总原则：如果解密不会改变游戏在 JoiPlay 下的运行方式，就不运行。

## 引擎

- RPG Maker MZ/MV（HTML5）→ `pipeline.py`（JoiPlay 构建，见
  `docs/workflow.md`）
- TyranoScript / TyranoBuilder（Electron 打包的 HTML5 视觉小说）→
  `tyrano/pipeline.py`（JoiPlay 构建 + 翻译，见 `docs/tyrano.md`）
- Unity（任何类型）→ 仅翻译 + 运行时注入，绝不用流水线（见下）
- Wolf RPG（ウディタ）→ 仅翻译 + 解包/回写，绝不用流水线（见
  `docs/wolfrpg.md`）
- KiriKiri（吉里吉里）→ 手机目标走 KAG3 → TyranoScript 转换（见
  `docs/kirikiri-tyrano.md`）；桌面翻译走 patch.xp3（见 `docs/kirikiri.md`）。
  不使用 RPG Maker 专用流水线。

## Unity 游戏（非 RPG Maker）

Unity 游戏（`<Game>.exe` + `<Game>_Data/` + `globalgamemanagers`，无
`index.html`/`js/`）不属于流水线范围——`build`/`decrypt`/`audio`/`clean`/
`verify` 全部不适用，JoiPlay 也无法运行它们。

- **范围：仅翻译** — Unity Mono 游戏用 XUnity.AutoTranslator
  `Translation\{Lang}\Text\` 表/JSON 语言包；**IL2CPP 游戏用 MelonLoader
  运行时 hook**（见下节 "Unity IL2CPP + Addressables 翻译（运行时
  hooking）"，已在 Unity 6 IL2CPP + Addressables 游戏上跑通）；
  **RPG Maker Unite（Unity Mono）用 BepInEx 5 + Harmony 自定义插件**
  （见下节 "RPG Maker Unite (Unity Mono) 翻译"，多款同作者短篇系列跑通，
  工具在 `unity\rmunite\`）。绝不在 Unity 游戏上跑流水线，绝不解密/
  重编码任何东西。
- Unity 游戏放到专门的 Unity 游戏目录（`<Game>\`；先解压到 Temp、
  删除广告文件、再移动；剥掉重复嵌套的目录层级）。
- 广告清理：删除根目录推广文件（推广/注册链接类文案——具体清单见本地
  `docs/table/ad_keywords.md`）。保留版本/更新说明 readme。
- 病毒检查：核对 BepInEx DLL 清单（只允许 BepInEx/XUnity 标准组件 +
  已知 mod DLL）、检查 exe 签名（无签名属正常）、可选运行
  `Start-MpScan -ScanType CustomScan`。
- 翻译状态约定：游戏正文 = AutoTranslator 缓存于 `Language={lang}`
  （`FromLanguage=ja`）；mod 新增文本 = `BepInEx\plugins\*Json\` 下的
  JSON 语言包（按语言分目录）。决定是否需要翻译前先检查
  `AutoTranslatorConfig.ini` 的当前语言。

## Unity IL2CPP + Addressables 翻译（运行时 hooking — 已在 Unity 6 验证）

IL2CPP 游戏（`GameAssembly.dll`，无 Mono `Managed/`）+ Addressables
（`StreamingAssets/aa/**/*.bundle`）的文本全部在 bundle 的 MonoBehaviour
序列化字段里。**不要再尝试 bundle 改写**（Unity 6 拒绝一切修改过的
bundle，见下方 FAILURE 记录）——正确路线是 **MelonLoader 运行时 hook**
（Unity 6000.3.x / metadata v39 验证通过）。

### 1. 文本提取（确定翻译范围）

文本在多处，缺一不可：

- **MonoBehaviour 序列化字段**：`commandSequence` 里的 `message`（成人场景/
  回想台词）、TMP 组件的 `m_text`（烘焙 UI 文本）、`displayName`（cut 名）、
  `message`（证据文本）—— UnityPy `obj.read()` 遍历 `__dict__`。
- **GameScript `bytecode` 字段（最容易漏！）**：图式脚本插件（如
  NemukeGraph/LogicToolkit）的图被编译成自定义字节码存在 `bytecode` 字段
  （`list[int]`），**主剧情台词全在这里**。字符串格式：`opcode 6 (0x06) +
  int32(utf8-len) + utf8`。只做 `read()` 遍历的提取会**完全漏掉主剧情**。
- **Unity Localization 字符串表**：`localization-string-tables-japanese(ja)_assets_all.bundle`
  里的小表（通用文本，名字/地名等）。

分片：分批追加契约下 **~250 键 / ~9k 字符** 的大块完全可行，QC 保证不丢行。

### 2. 运行时注入（MelonLoader 0.7.3 + Harmony — 先 `doctor`/自检版本）

> 下文的版本号（MelonLoader / Unity / BepInEx / metadata）是**当时跑通的
> 组合**，不是永久保证；换新版本前先确认本机实际版本，失败按本文末尾
> “失败模式”入口记入 `docs/experience-*.md`。

1. 把 `MelonLoader.x64.zip` 解压到游戏根目录，首次启动自动生成
   `MelonLoader\Il2CppAssemblies`（内含 Cpp2IL 处理 metadata v39 的能力）。
2. 插件为 net6.0 class library，引用 `MelonLoader\net6\*` +
   `Il2CppAssemblies\*.dll`（互操作类在 `Il2Cpp` 前缀命名空间，如
   `Il2CppNovelCommand`、`Il2CppNovel.Nameplate`、`Il2CppTMPro.TMP_Text`）。
3. Hook 点（Harmony prefix，`ref` 参数直接改字符串）：
   - 对话类静态方法：`NovelCommand.Say/SayNoBacklog/SayNoClear` 的 2/3 参
     重载、`AddChoice` —— 源端翻译，backlog/打字机全部覆盖。
   - `Nameplate.SetName` —— 说话者名字。
   - `TMP_Text.text` setter —— UI 兜底。**必须 patch 基类 `TMP_Text`**
     （MelonLoader 警告：TextMeshProUGUI 未实现该方法，patch 基类才生效）。
4. 翻译字典 `translated.json`（{ja→zh}，放游戏根目录），exact-match 查找；
   **两侧统一 `Replace("\r","")`**（Unity 序列化字符串带 CRLF，不剥会失配）。

### 3. 卡死教训（两次真实事故，都表现为"第一个对话后点击无法推进"）

- **TMP setter 热路径上严禁文件 I/O**：打字机动画每帧 set_text 一次且
  字符串是递增子串——逐帧写 miss 日志 = 文件 I/O 风暴，主线程堵死。
  TMP hook 必须纯内存、含假名才查表、只翻译完整串。
- **严禁动 `TMP_FontAsset.m_SourceFontFile` / `atlasPopulationMode`**：
  源字体交换会破坏图集/死锁动态字形提取（第一个对话"お……"变方框 +
  全游戏冻结）。动态字形只能走 **fallbackFontAssetTable**。

### 4. 字体（中文方块 → 正常显示）

- 游戏字体是 TMP_FontAsset 且**本来就是 Dynamic**
  （`m_AtlasPopulationMode=1`），但源字体（NotoSansJP/BIZUDGothic 等）
  没有 GB 简体汉字 → 方块。
- **Unity 6 里 `TMP_FontAsset.CreateFontAsset(Font)` 运行时返回 null——
  必须用字符串路径重载**（FontEngine 直接从文件加载）：
  ```csharp
  var cjk = TMP_FontAsset.CreateFontAsset(
      "<path-to-cjk-font>.ttc", 0, 36, 6,
      UnityEngine.TextCore.LowLevel.GlyphRenderMode.SDFAA, 1024, 1024,
      Il2CppTMPro.AtlasPopulationMode.Dynamic, true);
  ```
  （`GlyphRenderMode` 在 `UnityEngine.TextCore.LowLevel`，FontEngine 模块；
  `AtlasPopulationMode` 用 `Il2CppTMPro` 自带的枚举。）
- 把结果 `Add` 进每个游戏字体的 `fallbackFontAssetTable`（纯加法：日文
  字形保留原样，缺失汉字回退到宋体）。**用户偏好：宋体 (SimSun) 比雅黑
  更适合本作**。参考实现：eviltwo/SystemFontLocalization（Unity 6 验证）。

**Unity 6 bundle-改写 FAILURE（2026-08，勿再盲目重复）：** 引擎拒绝一切
修改过的 bundle（静默黑屏、无日志、约 2s CPU、窗口存在）。按顺序全部
失败：UnityPy typetree 补丁+保存；UnityPy raw set_raw_data 字节替换
（短键损坏对象——用 4 字节对齐填充修复）；等长替换；手工 store-block
UnityFS 重打包；保真 LZ4 重打包（头部/标志/块布局一致、LZ4HC 位、
UnityPy 可读验证）；catalog crc 与 content-hash 清零。原始 bundle 在同一
机器上运行正常。结论：该构建的 Addressables bundle 加载器存在未检测的
完整性/兼容性检查；**以现有工具对 Unity 6 Addressables 游戏做 bundle
改写不可行**（UnityPy 自己的 GitHub 也承认 LZ4 保存的 bundle 可能无法
加载）。**旧记录的"翻译需要 runtime hooking（BepInEx+AutoTranslator，
Unity 6 存疑）"已过时**——MelonLoader 运行时 hook 方案于同日跑通并交付
 （见上节）。另外当时"full residual scan 0"是**假阳性**：read() 遍历漏掉了
GameScript bytecode 里的主剧情文本。**bundle 改写历史作废，勿再尝试。**

## RPG Maker Unite (Unity Mono) 翻译 — 已在短篇系列验证（2026-08）

7 款同作者 RM Unite 短篇成人游戏全部跑通（系列复用词条/剧情字典），
Unity **2021.3.15f1 Mono**（非 IL2CPP），Addressables bundles。

### 1. 文本提取（UnityPy typetree）

- 文本全在 `StreamingAssets\aa\StandaloneWindows64\**\*.bundle` 的
  **MonoBehaviour 序列化字段**；typetree **未剥离**，`read_typetree()`
  直接可用。
- 三类文本位置，缺一不可：
  - **对话**：`EventSO.dataModel.eventCommands[].parameters[0]`（code
    401/101，说话人前缀如 `【角色名】` 内嵌在文本里）+ 选择肢 code 402 的
    `parameters[2]`。
  - **UI/菜单**：`UnityEngine.UI.Text.m_Text`（prefab 组件）。
  - **词条**：`WordSO`/`SystemSO`/`ItemSO` 等共享数据库文本（攻撃/アイテム
    等 UI 词条；**游戏本体与 UI 共用，必须译**）。
  - `TileDataModel` 磁贴名 = 编辑器内部名，**不译**。
- 每个事件的完整命令序列在 `others_assets_event\*.asset`（EventSO 一个
  事件一个 asset）；主 scene assets（globalgamemanagers/sharedassets）
  无文本。
- MonoScript 类名映射：先遍历 bundle 内 MonoScript 的 `read_typetree()`
  （`m_ClassName`+`m_Namespace`），再按 MB 的 `m_Script.m_PathID` 解析。

### 2. 运行时注入（BepInEx 5.4.23.5 + Harmony）

- **Hook 点（对话源头，严禁只 hook 显示端）**：
  - `RPGMaker.Codebase.Runtime.Common.Component.HudHandler.SetShowMessage(string)`
    —— **唯一整句文本入口**，IL 极简（`_messageWindow.ShowMessage(msg)`）。
    MessageTextProcessor 只处理窗口设置（名字/头像/颜色），不含正文。
  - `UnityEngine.UI.Text.set_text` + `TMPro.TMP_Text.set_text` —— UI 兜底。
    **必须 patch 基类 `TMP_Text`**（TextMeshProUGUI 未实现 set_text，
    patch 子类直接抛 "Undefined target method"，且 PatchAll 中断后续所有
    patch）。
- **打字机陷阱**：消息窗口逐**字符**调 set_text（捕获日志可见逐字文本），
  整句匹配必然失败 → 翻译必须做在 SetShowMessage 源头。
- **BepInEx preloader 崩溃修复**：游戏自带 MonoMod 19.x（RM Unite 插件
  机制）与 BepInEx 冲突，`MethodAccessException:
  MonoMod.Utils.PlatformHelper.set_Current`。解法：`doorstop_config.ini`
  设 `dll_search_path_override = BepInEx\core`。干净原版（无
  0Harmony/MonoMod 的 repack）不需要此设置。
- **行尾符**：运行时文本带 `\r`，提取时归一化为 `\n` → 查表前两侧统一
  `Replace("\r\n","\n").Replace("\r","\n")`，命中后译文按原文行尾风格
  补回（原文 CR 结尾则译文补 CR），否则消息窗口换行判断异常。
- **验证**：插件加 stats Timer（每 15s 报 hits/misses）+ miss 日志
  （限 30 条，热路径严禁无限制文件 I/O）。`hits>0 misses=0` + 无 miss
  日志 = 翻译全命中。自动测试：启动后 `AppActivate` + SendKeys ENTER
  推进剧情触发对话。

### 3. 批量流水线（系列多款复用）

1. `extract_game.py <game_dir> <out>`（参数化提取，先全量再过滤两个类）。
2. **prefill**：第一款翻译作为系列词条库预填充，`【名字】` 前缀替换
   + 正文查 base。**坑**：正文不在 base 时 `base.get(rest, rest)` 原样
   保留 → **半翻译**（前缀中文、正文日文）静默入库。
3. QC 必须用**假名正则** `[\u3040-\u30ff]` 检查值残留（中文/日文共享
   CJK 汉字区 `\u4e00-\u9fff`，按汉字查会全部误报）。
4. 系列共享剧情（如收债人线）直接从已翻译作品借字典，逐键 exact 匹配。
5. 翻译 `translated.json`（{ja→zh}）放游戏根目录，插件 exact-match 查表。
6. 交付：汉化版完整目录放 Workspace（含 BepInEx/插件/translated.json），
   原版不动。

## KiriKiri（吉里吉里）翻译 — 补丁注入（2026-08 定案）

KiriKiri 游戏（`Game.exe` + `data.xp3` 等，无 `index.html`/`js/`）不走
RPG Maker 流水线。下述为桌面翻译路线；手机转换另见
`docs/kirikiri-tyrano.md`，不做 Ren'Py 移植。桌面路线：
解包 → 提取 → 统一 chunk 翻译 → 写回 → 打包 `patch.xp3`（引擎档案
优先级 patch > 原档，同名文件先到先得，**原包不动**）。完整指南见
`docs/kirikiri.md`。

- **解包**：`kirikiri/xp3tool.py`（标准 krkrz 头、zlib/raw 索引、
  0x80 间接块、raw/zlib 段）。多档案（data/patch/update）解到**同一
  目录覆盖**（等价引擎叠加顺序）。
- **打包**：`kirikiri/xp3pack.py`（纯 Python：raw 段 + zlib 索引 +
  写完用 xp3tool 解析器回读自校验）。
- **提取/写回**：`tools/build_ks_translation.py` → 统一 chunk 流程 →
  `tools/apply_ks_translation.py`（整行键替换，保留缩进/行尾/原编码）。
- **键 = 整行**（含 `[l]` 等格式标签与 `text="..."` 属性）：标签是
  控制码，逐行 1:1 数清（chunk 契约与 RPG Maker 相同）；这同时覆盖
  对白、名字窗（`[name text=..]`）、消息窗（`[wm2 text=..]`）、选择肢
  （`[select_caption text=..]`）。
- **故事顺序**：从入口脚本（默认 `start.ks`）沿 `[call]/[jump]`
  storage 引用 BFS 追踪，孤立文件按排序追加；`@bg storage=` 等**素材
  引用不追踪**。
- **编码**：每文件自动探测（UTF-16LE/BE、Shift-JIS、UTF-8），写回用
  原编码；**Shift-JIS 编不下中文时整文件转 UTF-16LE**（引擎按 BOM
  嗅探）并 WARN。
- **`*` 标签行、`;` 注释行、未配对方括号行一律不提取**（防改坏跳转）。
- **QC**：`tools/qc_ks_kana.py`（补丁树/字典值假名残留，文件:行定位；
  汉字不算残留；**只查显示文本**——标签行/注释/代码块/变量引用
  `&f.名前` 不算，Tyrano 合法用日文标识符，不排除会淹没真漏译）。
- **MTool 清除**：KiriKiri 游戏同样按打包规则删 MTool 注入残留
  （根目录运行时字典 json、winmm.dll/version.dll、启动/移除 bat）。
- **字体**：中文方块按具体游戏解决（系统字体 / `kirikiri/merge_font.py`
  合并字体），跑通的方案记入本地 `docs/table/<Game>/notes.md`。

## 目录约定

- 工作/解压副本一律放**系统临时文件夹**（如 Windows 的 `Temp`、Linux 的
  `/tmp`；本机具体路径见本地私有配置 `docs/table/env_config.json` 的
  `deliverables.temp`），绝不放源目录旁边。
- **路径配置只存一份（原生形式）**：Windows 侧资源写 `D:/..`/`C:/..`，
  WSL 侧写 `/tmp/..`；WSL 要用 Windows 侧路径时由代码转换
  （`rpgmaker/config.py` 的 `localize()` → `to_wsl_path()`），**绝不把同一
  路径写两份**。工具按 `[platform][tool]` 索引（两侧二进制不同）。
- **Windows 端下载/暂存**（Windows-only 工具、待处理内容）一律放
  `deliverables.win_temp`（Windows 的 `%TEMP%`，代码里
  `rpgmaker/config.py` 的 `win_temp_dir()`），**绝不放进 `deliverables.games`
  或 `deliverables.archives`**。
- 成品放专门交付目录，命名 `<Game>` / `<Game>.7z`，与其他转换过的游戏一致。
- 绝不修改原版游戏目录。
- **工作流（2026-08 定案）**：源压缩包在存储侧（Windows），处理在
  WSL 侧进行；只做必要的跨系统搬运。**严格遵守「跨系统文件处理」
  CRITICAL 规则（见上）**：
  1. 开工前先检查**系统临时文件夹**（`deliverables.temp`，WSL 侧）：
     已有该游戏的工作副本 → 直接基于它继续，不重复解压/复制；
  2. 没有 → 把源压缩包（`deliverables.archives`，Windows 侧）**单个文件
     复制**到系统临时文件夹，再在 WSL 侧解压（处理发生在 WSL 侧）；
  3. 在 WSL 侧处理（流水线/翻译等，工具用 WSL 内的）；
  4. 收尾用 `pipeline.py deliver <成品目录>`：先在 WSL 侧把成品压缩成
     本地 7z（快文件系统），再把压缩包**单个文件复制**到压缩包目录
     （`deliverables.archives`，Windows 侧，覆盖旧包——通常就是源压缩包）；
  5. 删除成品目录（`deliverables.games`，Windows 侧）同名旧文件夹 + 从
     压缩包解压到成品目录：**由 Windows 侧工具完成**。`rpgmaker/deliver.py`
     内置**自动桥接**（`config.is_windows_side` / `win_7z`）：WSL 下对
     `/mnt/*` 的删除与解压自动改用 Windows 7z.exe / PowerShell
     `Remove-Item`（经 `powershell.exe` 调用），无需手工介入；仅当
     Windows 7z 缺失或输入跨两侧混用时报错（提示见上节）。
  跨系统只搬运单个压缩包，避免大量小文件走 9P。
- **工具/路径解析只在一处（mandatory，2026-08 重设）**：外部程序的解析
  统一走 `rpgmaker/config.py` 的 `TOOLS` 表 + `resolve_tool()`，顺序为
  **环境变量 → 本地配置覆盖（可选，支持 `*` 通配）→ 探测常见安装位置
  → PATH**。新增/修改一个程序只改 `TOOLS` 一条，**不得**在别的模块里新
  写 `shutil.which` / 自己的查找函数，也**不得**把机器路径写进代码或
  文档（探测代替硬编码）。`pipeline.py doctor`（`--json` 机器可读）打印
  每个程序实际解析到的路径与来源；排查「工具找不到」先跑它，不要搜盘。
- **功能优先用现成包，不自己造轮子（mandatory，2026-09 定案）**：
  同一个能力只能有一个封装层，且优先用维护中的包而非手写：

  | 能力 | 唯一入口 | 用的包 |
  |---|---|---|
  | 7z 打包/校验/解包（同侧） | `rpgmaker/archive.py` | `py7zr`（zstd；实测比 `7z.exe -mmt` 快 1.7x、体积相同、互读通过） |
  | 媒体探测/解码检查 | `rpgmaker/media.py` | `av`（PyAV）——**不再需要 ffprobe** |
  | 视频转码（VP9+Opus WebM） | `rpgmaker/media.py::transcode_to_webm` | `av`（libvpx-vp9 + libopus，**不再需要 ffmpeg CLI**；实测帧数/时间戳/音频采样数与 CLI 完全一致、PSNR 差 ±0.3 dB，视频码流大约 6%） |
  | Electron app.asar 解包 | `tyrano/asar.py` | `asar`（纯 Python；**不再需要 Node.js/npx**；用官方 node 工具打的包（含 unpacked 条目）双向提取字节一致） |
  | JS 语法检查 | `rpgmaker/jssyntax.py` | `tree-sitter` + `tree-sitter-javascript`（**不再需要 `node --check`**；58 个真实 JS 文件 × 4 种变体共 225 例判定与 node 完全一致） |
  | 命令行 | 每个工具用 `rpgmaker/cliutil.py` 的 Typer 约定（禁止 argparse）；入口包装 `pipeline.py` / `tyrano/pipeline.py` 用 `rpgmaker/cli.py` | `typer` |
  | 外部进程执行 | `rpgmaker/proctools.py` | 标准库 `subprocess`（超时 + UTF-8 + 统一失败信息） |
  | 日志配置 | `rpgmaker/logsetup.py`（唯一入口，只能从 `main()` 调用） | 标准库 `logging` |
  | 测试 | `tests/` | `pytest` + `pytest-xdist`（默认 `-n auto`）+ `pytest-cov` + `ruff` |

  新代码**不得**再自己拼 ffprobe/7z/node 的 argv、解它们的 stdout、或写
  第二份 `shutil.which`。剩下的例外（已在代码注释里写明原因）：
  **Vorbis 音频编码**仍调 ffmpeg CLI（PyAV 的 wheel 不含 libvorbis，而 q2/q3
  是实测验证过的移动端配方，重构不得静默改质量）；**Windows 侧桥接**仍调
  Windows `7z.exe` 与 PowerShell（跨系统 CRITICAL 规则）；**窗口截图**用
  PowerShell PrintWindow（Win32 API，跨系统必须由 Windows 侧执行）。探测/
  解码/视频转码/asar/JS 语法检查已全部改为进程内。

- **命令行约定（mandatory，2026-09 定案）**：每个工具都是
  `rpgmaker/cliutil.py` 的 Typer 命令，**不再用 argparse**（曾 53 个文件、
  223 个 `add_argument`）：
  - 单命令工具：`app = cliutil.command_app(cmd, help=__doc__)`；子命令用
    `cliutil.app(help=__doc__)` + `@app.command()`（模板见该模块文档串）。
  - 每个工具保留 `def main(argv=None) -> int`（`cliutil.run` 在 argv 为
    None 时读 `sys.argv`），**命令里绝不调 `sys.exit()`**：失败用
    `return cliutil.fail("…")` 或 `raise typer.Exit(code=N)`。
  - 日志选项统一用 `cliutil.Verbose` / `Quiet` / `LogFile` 三个注解类型
    （即每个工具都有 `-v` / `-q` / `--log-file`）。
  - 已知与 argparse 的差异（有意保留）：不再接受长选项缩写
    （`--outp`），用法错误的提示语换成框架自己的文案（退出码仍是 2）。
- **本机环境信息**（交付目录、工具路径覆盖、venv 等）写进本地私有配置
  `docs/table/env_config.json`（gitignored，不入库）——**这是可选覆盖层，
  不是必需条件**：文件缺失时由探测 + 内置默认值接管。交付目录解析顺序
  为 环境变量 → 本地配置 → 探测已有惯例目录（工作区根即本库的**同级
  目录**下的 `Games`/`GamesCompress` 优先，再看各盘符根与家目录）→
  内置默认（同样是工作区根下这两个目录，按需创建）。代码按
  平台解析（`is_wsl()`），不硬编码本机路径。系统工具安装（如
  `pacman -S ...`）由 owner 执行，agent 不自行下载/提权。

## 打包规则 (mandatory, 压缩前必做)

打包/压缩前必须清理并核对(每款游戏都做):

- **删除广告/推广文件**: 根目录的推广文本（推广/注册链接类，具体
  文件名见本地 `docs/table/ad_keywords.md`）一律删除。
- **删除不必要的外部工具脚本**: MTool 注入残留 —— `与工具一同启动.bat`、
  `从游戏中移除工具文件.bat`、`winmm.dll`/`version.dll`/`injectPath`、
  游戏不引用的 MTool 运行时字典(根目录 `<title>.json` 且 js/index.html
  均无引用)等一律删除(先 `rg -l` 确认无引用再删)。
- **翻译 KV 随包归档**: 若游戏已翻译(数据已烘焙中文),把翻译用的 KV
  (烘焙用的 `translated.json` 或等价 {ja→zh} 字典)放进游戏根目录一起打包,
  方便后续修改/重译。**bake_translation.py 现在自动写入
  `translation_kv.json`** (out_dir 根目录,`--no-kv` 关闭) — 无需手工改名;
  未翻译的游戏不打此文件。
- **打包前必架服务器供 owner 试玩 (mandatory, 2026-08 定案)**: 收尾
  `deliver` 之前,必须用 `serve` 起 HTTP 服务器,让 owner 实际试玩确认
  (翻译、字体、运行无报错)。owner 确认后才能 `compress`/`deliver`。
  命令必须**显式带 `--host 0.0.0.0`**（默认是回环 `127.0.0.1`，不带就
  只有本机能访问、手机连不上）：
  `python pipeline.py serve <dir> --host 0.0.0.0 -p <port>`
  （Tyrano 构建用 `tyrano/pipeline.py serve`；端口避开近期用过的）。
- **统一字体 (mandatory, 2026-08 定案)**: 汉化构建必须应用统一字体
  策略——中文/拉丁/日文假名统一走项目标准中文字体,避免中文回退系统
  字体导致字形不统一。具体字体名与各引擎改动点见本地
  `docs/table/font_rollback.md`(不入库,缺失时**按 WARN 报出并跳过**,
  不得静默当成已应用);MZ/MV 走 `bake_translation.py`
  标准字体策略,Tyrano 按 `font_rollback.md` 的 Tyrano 改动点
  (font.css @font-face + Config.tjs `;userFace=`)。
- **bake 低覆盖率闸门 (mandatory, 2026-08 定案)**: bake 前先做一次只读
  扫描(不复制、不写盘),统计游戏内 kana 显示字符串被 dict 命中的比例
  (`coverage: N hit / M missed = X%`)。**X < 50% (`--min-coverage`,默认
  0.5) 直接拒绝烘焙** — 低覆盖烘焙 = 半日半中 + 污染后续 completion
  (部分块值、半翻场景),正确路线是**放弃旧翻译文件,全量翻译**:
  `extract_remaining_text.py` 出模板 → subagent chunks → merge → 再 bake。
  故意的阶段一 harvest 烘焙用 `--force` 覆盖。
- **identity 条目 (v == k 且含假名) 自动剔除**: bake 加载 dict 时删掉
  这类条目 — 它们会 SHADOW 逐行 fallback(块查找"成功"但文本还是日文)。
- **名称引用自动检查 (TE/namePop)**: bake 尾部自动对照 `<TE:name>`/
  `<namePop:name>` 与全游戏事件名,失配的 dangling ref 逐一 WARN
  (含带控制码而被跳过翻译的 ref — 若事件名被翻了而 ref 没翻必被抓)。
  无需再手工 `rg -o "<TE:[^>]+>" data/` 抽查(可作二次确认)。
- 收尾顺序: `verify --source` → `serve --test` → 清理打包 → `deliver`
  (本地压缩 → 复制压缩包到压缩包目录覆盖旧包 → 删除成品目录旧文件夹 →
  解压到成品目录;含压缩包完整性测试)。

## 手机贴图限制（强制单一构建，2026-08 定案）

Android WebView/PixiJS 把 WebGL 贴图限制在**每边 4096 像素**；PNG 超过
4096（通常是竖版立绘）在手机上会渲染成**黑块**，而 PC 浏览器正常。

- **不再分高清/低清两套构建。** 每个游戏只交付一个构建
  `<Game>` / `<Game>.7z`：把超过 4096 的 PNG 直接缩放到 ≤4096（保持
  宽高比 + alpha，PNG），保证在 Android 上正常显示即可。PC 端损失可忽略。
- 用 `tools/downscale_images.py <web_root>` 扫描 `img/**/*.png`（读 IHDR
  头字节 16-23 预检）并就地缩放超限图片；`--dry-run` 只报告不写。
- 只在确实存在超过 4096 的 PNG 时才需要这一步（大多数游戏没有）。
- 曾试行运行时检测贴图上限并即时缩放（插件方案）以省去缩放步骤 —
  维护成本高于收益，已放弃，一律构建期缩放。

## 翻译体量协商 (mandatory)

启动任何 subagent 翻译任务前，**先量体量并与用户协商**：

- 先跑 `tools/extract_remaining_text.py`（或全量用
  `build_translation.py`）；报告剩余键数、总字符数、估算块数
  （`chars / 11000`，auto 分片会最终确认）。
- 估算约 10+ 块属于大任务：**先问用户是否翻译**（范围：全部 / 子集 /
  跳过）再启动任何 subagent。绝不自动开始超大翻译任务。
- **>30 块 → 不要自行开始。** 块数超过 30 时，任何情况下都不要自行启动
  subagent：**等用户明确指示再翻译**（历史上 50～130 块的全量任务都是
  owner 明确授权后才跑的——授权是逐次的，不是一次性的常设豁免）。
  该任务留作批处理项目，并准备 work 目录的 `TRANSLATION_PROJECT.md`
  状态文件（已完成步骤、剩余任务、下一步、并行策略）。
- 小任务（少量块）一行确认即可。

## 翻译并行度 (mandatory — 统一，2026-08 验证)

**默认每轮 10 个并行 subagent**（历史标定值：9-11 都稳定；首轮成功率
主要取决于 prompt 质量而非并行度）。并行度上限受当前 harness 限制，
当 harness 装不下 10 个时就按实际上限降低并保持其余策略不变。策略：

- **默认：每轮 10 个 agent**（受 harness 并发上限限制，取小者）；
  轮次数量由实际块数 ÷ 并行度决定，不固定。
- **一次失败** → 先在**同一个 subagent 会话**里重试（"立即写文件"）；
  ~90% 可恢复。同一会话失败两次后，新开会话试一次。
- **三次重试仍失败 → 编排者亲自翻译（mandatory）**：同一块累计三次
  重试（同会话两次 + 新会话一次）仍无文件，编排者**必须自己翻译该块**
  （或至少翻译其开头/结尾一段），从中分析失败原因（context 过大、
  键含特殊内容、输出超限、prompt 误导等），把原因和修复记入
  `docs/experience-*.md`（索引见 `docs/experience.md`）。不要无限重试——失败模式往往在亲自翻译时
  一眼看出。
- **反复失败（多块同因）** → 先修因再继续：简化 prompt（去掉读上下文
  步骤，直接下令写文件）、拆小块（~300 键）、词表内联等；仍失败的块
  累积到最后由编排者统一处理。
- **轮次间不向 owner 汇报** — 全部完成后一次汇报。
- 只有需要 owner 决策（范围 / 术语 / 是否继续）时才中途交流。

## Subagent 分块 & prompt 契约 (mandatory — 2026-08 验证)

**统一翻译流程见 `docs/translation.md`**（全量/补翻合并为一套参数：10
并行、auto 分块 ~11,000 字符/块、90KB context 预算、分批追加契约）——
完整失败模式目录、术语一致性审计清单、QC 关卡清单、修复脚本用法都在
里面。

### Chunk 双文件布局(2026-08 定案,取代旧 JSON chunk)

`gen_translation_shards.py` / `gen_completion_shards.py` 每个 chunk 产出:
- `chunks/chunk_NN.ja.txt` — **键专用,agent 绝不改动**:每行一个日文 key,
  无引号、非 JSON。转义:文件里 `\n` = 消息内真实换行,`\\` = 单个反斜杠
  (控制码前缀),两者无歧义。
- `chunks/chunk_NN.zh.txt` — **agent 唯一输出**:每行一个译文,与 ja.txt
  逐行 1:1(行数、顺序必须一致)。
- `chunks/chunk_NN.context.md` — 规则 + 语气 + 词表 + 人名宏表 + 场景上下文。
- `chunks/chunk_NN.meta.json` — 该 chunk 覆盖的地图(并行度参考)。

合并: `merge_plain_chunks.py` 把 ja/zh 两文件合并成 `chunks_translated.json`
(含行数/假名残留/控制码 QC),`merge_translation.py --chunks ...` 再叠加
prefilled 命中与 sweep 规则出最终 `translated.json`。

### chunk 尺寸自动选档 (2026-08 定案,默认行为)

`gen_translation_shards.py <work> [--target-chunks N] [--context-budget-kb 90]`:
脚本按每键的 context 行实际长度(含控制码行/窗口行)估算各 chunk 的
context.md 体积,**二分搜索最大的 --max-chars**,使 chunk 数 ≤ N 且最大
context.md ≤ 预算(90KB+ 的 context 是 no-file 失败温床;该估算只在短键
游戏上接近实际,长日文/大量控制码的游戏实测可达估算的 2 倍以上——见
`docs/experience-translation.md`,所以以生成器**打印的实际 context 大小**
为准,不要相信估算百分比)。默认(不传 --max-chars/--per-chunk)即走 auto:
**90KB 预算下的最大 chunk (~11,000 字符,历史标定值)**。
`gen_completion_shards.py` 同款默认(--max-chars 11000,且同样注入
`<work>/tone.md`)。用法示例: `gen_translation_shards.py <work>
--target-chunks 55 --context-budget-kb 90 --window 1`。

### 术语/人名词表 = 单文件,只读

- 词表文件 `glossary.json`(work 目录;收尾同步到本地
  `docs/table/<Game>/`,**该目录不入库**,见 `docs/translation.md` §6):
  首次与 owner 商定后,**此后只能用 edit 工具修改**(避免并发写坏);
  agent 只读 chunk 的 context.md 里的词表快照,绝不写 glossary。
- 人名宏是控制码,不是文本:`\N[1]`/`\P[1]` 等是 C++/LaTeX 式替换引用 —
  agent 要"理解成角色名",但绝不翻译/改动宏本身;名字在 Actors.json DB 里译。
  context.md 提供 Name macros 对照表(`\N[1] = 角色名 (词表: 中文名)`)。

### 上下文 = 独立产物,不翻译

`build_translation.py`/`extract_remaining_text.py`/`extract_rvdata2.py`
产出 `context.json`(key → 位置 + 前后文窗口),分片时注入各 chunk 的
context.md 场景时间线;上下文本身不参与翻译,只为 agent 提供语境。

### 对话连续性(强制,每次分片后必须检查)

**跨 chunk 的场景翻译必须保持对话连续**,这是验收硬标准,分片时始终注意:

1. **故事顺序分片**: chunk 内键严格按 故事序(MapInfos `@order`/MZ
   MapInfos 顺序 → 地图 → 事件 → 页 → 命令位置 → CommonEvents → UI/DB)
   排列,绝不按字母/类别乱序。
2. **每键 ±2 句窗口**: context.md 的场景时间线给每个 [K] 键附带上下文行
   (| 行),相邻键窗口去重,45 字符截断。
3. **跨 chunk carry-over**: 每个故事 chunk 的 context.md 开头注入**上一个
   故事 chunk 的尾部对话(最多 8 条)**,场景被切成相邻 chunk 时 agent 能
   看到前文。全局/UI/DB chunk 不产生 carry。
4. **顺序执行**: 线性场景的相邻故事 chunk **必须串行处理**,只能并行无
   叙事依赖的 chunk(不同地图/DB);乱序并行会把场景译得前后不连贯。
5. 分片生成后抽查: 相邻 chunk 的 context.md 应能对上(前一个的尾部 ≈
   后一个的 Carry-over 段),对不上就是分片 bug。
6. 术语/人名一致性: 靠 `glossary.json` 单文件(只用编辑工具改)+ 每 chunk
   词表快照;新名词在翻译中首次出现时,编排者必须把它补进词表并通知后续
   chunk。

### 菜单插件文本

`build_translation.py`/`extract_remaining_text.py` 默认提取
`js/plugins.js` 插件参数里含日文的字符串(kind=`plugin`,`--no-plugins`
关闭),`bake_translation.py` 精确匹配写回(解析失败时降级为字面量文本
替换)。插件参数可能是功能性值 — 只有整串精确命中才替换,绝不片段替换。

### 名称查找型引用(note/备注里的功能性引用,2026-08 定案)

**bake 后必须检查按名称查找的引用是否成对翻译**:
事件 note 里的 `<TE:模板名>`(TemplateEvent 模板引用)、插件按名称
`callEventByName`/`searchDataItem(...,'name',...)` 的查找键、BalloonPlus
气泡名、MPP_ChoiceEX 标签文本等 — 若只翻译了被查方(模板地图事件名)而
引用方(note)没翻,查找失败,模板不生效,无条件 autorun 事件每帧重触发、
永不擦除 → `isEventRunning()` 恒 true → 玩家无法移动。
`bake_translation.py` 已内置 `_translate_note_refs()` 同步翻译
`<TE:name>`/`<namePop:name>`(跳过含 `\v[n]` 等控制码的引用),并在烘焙
尾部**自动做 dangling 对照**(每个 ref 必须命中某个事件名;含"ref 因带
控制码没翻而事件名被翻"的失配类)——失配逐一 WARN,无需再手工
`rg -o "<TE:[^>]+>" data/` 抽查(可作二次确认)。

### 分批追加 prompt 契约 (mandatory — 2026-08 定案, 取代旧 Write-first)

旧 Write-first 契约("先写,后思考,再改"、一次性 Write 全文件)在
700+ 行的大 chunk 上失败率高(一轮 10 个 agent 常 3-5 个死于无文件;
同会话重试基本全恢复)。**2026-08 定案: 分批追加 + 分步自检**,
一轮 10 个 agent 首轮成功率实测 ~100%(连续 3 轮 0 失败;该数字是"prompt +
工具链 + 分批追加契约均正常"时的上限,不是任何情况的保证——同一流程也
出现过 ~90% 的首轮成功率,差异在 prompt, 不在并行度)。

**执行顺序必须明写为"先写,后思考,再改",且整块拆成小批** —
每个 agent prompt 原样包含(用**意图**描述而不是某个 harness 的工具名:
"创建文件" / "在文件末尾追加";换 harness 时工具名不同,但契约不变):

1. Read rules once, read chunk_NN.ja.txt keys once.
2. **分批翻译**: 每批约 100-130 行(键数更少的 chunk 可一批全译)。
   第一批创建 `chunk_NN.zh.txt`(写文件工具); 后续每批把新译文追加到
   文件末尾(编辑工具: 以当前最后一行作为匹配串,替换为"最后一行 +
   新批译文")。每批译文行数必须与该批 ja 行数一致。
3. **分步自检 (per-batch)**: 每追加一批后读回 zh.txt 对应段, 核对:
   ① 行数与 ja 对应段一致 ② 字面 `\n` 数量一致 ③ 控制码原样保留且
   数量一致 ④ 无假名残留。发现错误立即在批内修正再继续下一批。
4. 全部批次完成后最终读回全文核对行数 = ja.txt 行数。
5. Final reply = file path + entry count only.
Plus: "Never end before the file exists. 先写文件, 再推敲内容。"
prompt 里再加三条明令:
值必须是译文(不得把日文原文写进值)、zh.txt 每行一个译文且行数与 ja.txt
一致(键内嵌真实换行在文件里以字面 `\n` 表示,勿写真实换行)、
控制码写完要数。

- **每个返回的 zh.txt 立即用 `merge_plain_chunks.py` 验证**;可恢复滑落:
  缺行(行数不匹配)、把字面 `\n` 写成真实换行、agent 漏掉个别键
  (行数少 1 时从 `chunks_translated.json` 重建该文件再对齐)。
- **agent 结束后跑值卫生修复**:折叠双反斜杠、剥离 `【?...】`、diff
  控制码 token 键值两侧、按词表替换残留的【日文人名】前缀。
- **若之后修复了值,构建里已经是旧值** — 按键匹配的补丁不会重新生效;
  用 旧→新 值映射反向打补丁。
- **残留检测**:在**最终构建**上测假名;walker 必须让顶层列表 JSON
  (CommonEvents.json) 走事件 walker,否则静默漏掉它全部对话。

## 顺序

`build` → (`decrypt` 仅 RPG Maker MZ/MV easy 加密时) → `audio` → `clean`
→ `verify --source` → `serve --test` → 新端口 HTTP 试玩 → `deliver` 最后
(压缩 → 复制压缩包到压缩包目录 → 删除成品目录旧文件夹 → 解压到成品目录)。
