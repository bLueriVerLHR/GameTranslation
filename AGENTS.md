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
- **提交前自查 (mandatory)**: 改动后必须跑
  `rg -n -i "<游戏名|密码|C:\\Users\\|露骨词>" --glob "!*.pyc" --glob "!docs/table/**" .`
  确认零命中再 commit（具体广告文件名/推广关键词见本地
  `docs/table/ad_keywords.md`，同样排除）；commit message 同样不含游戏名/
  敏感词。

## 本地名词表 docs/table/ — 加载规则 (mandatory)

`docs/table/` 是**本地名词表/翻译资料库**（gitignored，不入库不推送），
会话中需要它的信息时**主动去读**，不是可选项：

```
docs/table/
├── README.md           # 目录说明与维护约定
├── ad_keywords.md      # 广告/推广关键词与文件名清单（打包前清理对照）
├── passwords.md        # 常用压缩包密码表（解压 `7z x -p<pass>` 用）
├── ero_noun_table.md   # 通用名词词表（成人词表，仅本地）
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
- **翻译风格定案时**: `ero_noun_table.md` 是通用名词词表的唯一权威来源
  （见 `docs/translation.md` §6）。

维护与边界:

- 只允许 owner 通过 edit 工具修改（agent 只读）。
- **该目录内容绝不写进仓库代码/文档/commit**；提交前自查扫描时排除
  `docs/table/**`（见上节）。

## 开发流程（分支/提交/推送, mandatory）

- **每次任务开新分支**，命名 `<罗马音代号>/<功能>`：代号取游戏/项目名的
  罗马音短名（约 5 个字母，如 SachiNTR → `sachi`），功能如
  `translation` / `development` / `audio` / `clean`。不同功能开不同分支，
  绝不在主分支上直接改。
- **本地分支不推送**：feature 分支只在本地工作，不 push 到 GitHub。
- **完成后 squash 成单一 commit 合并回主分支（main）**：
  `git checkout main` → `git merge --squash <分支>` → `git commit` —
  每次任务只产生一个 commit。
- **合并/推送前必须通过检查（mandatory）**：
  1. 敏感词扫描：
     `rg -n -i "<游戏名|密码|C:\\Users\\|露骨词>" --glob "!*.pyc" --glob "!docs/table/**" .`
     零命中；
  2. `python -m py_compile` 所有改动的 `.py`（工具可运行）；
  3. 文档一致性：README 目录树与新增文件同步、文档语言为中文；
  4. 只推送主分支（main）到 GitHub，提交者身份用 opencode
     （不用 owner 的 git 身份）。
- 提交信息用中文/英文均可，但不得含游戏名与敏感词。

## 语言规则（mandatory）

- **代码文件**（`.py`/`.cs` 等）：代码与注释一律**英文**。唯一例外是
  **游戏内原生语言内容**——日文原文、假名/日文正则、日文样例（如
  `\N[1]`、`名前`、`<SG説明`），以及注入给翻译 agent 的 prompt/词表
  内容。**禁止中文注释**。
- **文档文件**（README、`docs/*.md`、AGENTS.md）：一律**中文**。
- 提交信息中文/英文均可（不含游戏名与敏感词）。

## 转换目标

最终目标是**可玩的 JoiPlay 构建**，而不是完美克隆。做让游戏能在
Android 的 JoiPlay 里跑起来所需的最小工作。

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

- RPG Maker MZ/MV → `pipeline.py`（见 `docs/workflow.md`）
- Unity（任何类型）→ 仅翻译，绝不用流水线（见下）

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
  工具在 `tools\rmunite\`）。绝不在 Unity 游戏上跑流水线，绝不解密/
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
  int32(utf8-len) + utf8`。只做 `read()` 遍历的提取会**完全漏掉主剧情**——
  第一次提取报 1960 texts 是错的，真实范围 **2742 条唯一文本 /
  ~15.9 万字符**。
- **Unity Localization 字符串表**：`localization-string-tables-japanese(ja)_assets_all.bundle`
  里的小表（~14 条通用文本，名字/地名等）。

分片：写优先契约下 **~250 键 / ~9k 字符** 的大块完全可行（24 块一轮 10
并行 ~3 轮跑完），QC 保证不丢行。

### 2. 运行时注入（MelonLoader 0.7.3 + Harmony）

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
      "C:\\Windows\\Fonts\\simsun.ttc", 0, 36, 6,
      UnityEngine.TextCore.LowLevel.GlyphRenderMode.SDFAA, 1024, 1024,
      Il2CppTMPro.AtlasPopulationMode.Dynamic, true);
  ```
  （`GlyphRenderMode` 在 `UnityEngine.TextCore.LowLevel`，FontEngine 模块；
  `AtlasPopulationMode` 用 `Il2CppTMPro` 自带的枚举。）
- 把结果 `Add` 进每个游戏字体的 `fallbackFontAssetTable`（纯加法：日文
  字形保留原样，缺失汉字回退到宋体）。**用户偏好：宋体 (SimSun) 比雅黑
  更适合本作**。参考实现：eviltwo/SystemFontLocalization（Unity 6 验证）。

记录：一个 Unity 6000.3.5f2 IL2CPP + Addressables 视觉小说（2026-08）——
**2742 条唯一文本 / ~15.9 万字符**；MelonLoader 运行时 hook（Say 系列 +
AddChoice + Nameplate.SetName + TMP_Text.text）+ translated.json 字典；
24 个 subagent 分片（~250 键/块）翻译 + QC 零假名残留、`<sprite=0>`
逐行 1:1；字体 fallback = 运行时 SimSun。终态：全文本汉化、无卡顿、
游戏完整可玩。**bundle 改写历史作废，勿再尝试。**

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
GameScript bytecode 里的主剧情文本（真实范围 2742 条而非 1960 条）。
游戏已恢复原装日文且可玩；不要再对它做 bundle 改写。

记录：一个 Unity 5.6.7f1 x64 带翻译 mod 的 repack——正文 = AutoTranslator
EN（机器翻译，3651 条 / ~13.1 万字符）；mod 自带完整手工汉化包
（19 个场景 JSON + EventCore 65 个文件，游戏内可选语言）。保持原样
（EN 正文 + CN mod）。**2026-08 删除**（owner 决定——正文翻译量过大；
日后可能再做；本条记录保留作参考）。

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

记录：一个 7 款系列（2026-08, first 123 entries；后续 155–582 entries，
含一次 68 条半翻译修复、系列复用收债线、会津弁口语化译法）。
压缩包密码见本地 `docs/table/passwords.md`（gitignored）；Unity
2021.3.15f1 统一。

## 目录约定

- 工作/解压副本一律放 Temp 目录
  （`%LOCALAPPDATA%\Temp\opencode\<Game>_JoiPlay\`），绝不放源目录旁边。
- 成品放专门交付目录，命名 `<Game>_JoiPlay` / `<Game>_JoiPlay.7z`
  （与其他转换过的游戏一致）。
- 绝不修改原版游戏目录。

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
- 收尾顺序: `verify --source` → `serve --test` → 清理打包 → `compress`
  (自动替换旧包 + 完整性测试)。

## 高清 vs 低清（手机贴图限制）

Android WebView/PixiJS 把 WebGL 贴图限制在**每边 4096 像素**；PNG 超过
4096（通常是竖版立绘，如 2160x4237）在手机上会渲染成**黑块**，而 PC
浏览器正常。

- `<Game>_JoiPlay` = 高清构建，图片不动（原版游戏即高清母版）。
- `<Game>_JoiPlay_LowRes` = 独立兄弟构建，把所有超过 4096 的 PNG 缩放到
  ≤4096（保持宽高比 + alpha，PNG）；绝不覆盖高清目录。
- 只有确实存在超过 4096 的 PNG 时才做 LowRes（扫 IHDR 头字节 16-23，
  无需完整解码）。记录：一款游戏 30 张 2160x4237 竖版立绘，2026-08 修复。

## 翻译体量协商 (mandatory)

启动任何 subagent 翻译任务前，**先量体量并与用户协商**：

- 先跑 `tools/extract_remaining_text.py`（或全量用
  `build_translation.py`）；报告剩余键数、总字符数、估算块数
  （`chars / 11000`，auto 分片会最终确认）。
- 估算约 10+ 块属于大任务：**先问用户是否翻译**（范围：全部 / 子集 /
  跳过）再启动任何 subagent。绝不自动开始超大翻译任务。
- **>30 块 → 不要开始。** 块数超过 30 时，任何情况下都不要启动
  subagent：**等用户明确指示再翻译**。该任务留作批处理项目。
- 小任务（少量块）一行确认即可。

## 翻译并行度 (mandatory — 统一，2026-08 验证)

**每轮 10 个并行 subagent 是基线。** 已验证稳定（9-11 都稳定；首轮成功
率 ~90%+ 是 prompt 的属性，与并行度无关）。策略：

- **默认：每轮 10 个 agent。** 轮次不超过 ~11。
- **一次失败** → 先在**同一个 subagent 会话**里重试（"立即写文件"）；
  ~90% 可恢复。同一会话失败两次后，新开会话试一次，再不行就搁置。
- **反复失败** → 简化 prompt（去掉读上下文步骤，直接下令写文件）；
  仍失败的块累积到最后由编排者统一处理（分析原因，亲自翻译/修复）。
- **轮次间不向 owner 汇报** — 全部完成后一次汇报。
- 只有需要 owner 决策（范围 / 术语 / 是否继续）时才中途交流。

## Subagent 分块 & prompt 契约 (mandatory — 2026-08 验证)

**统一翻译流程见 `docs/translation.md`**（全量/补翻合并为一套参数：10
并行、auto 分块 ~11,000 字符/块、90KB context 预算、写优先契约）——
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
context.md ≤ 预算(90KB+ 的 context 是 no-file 失败温床;估算与实际误差
<3%)。默认(不传 --max-chars/--per-chunk)即走 auto:**90KB 预算下的最大
chunk (~11,000 字符)**。`gen_completion_shards.py` 同款默认
(--max-chars 11000)。用法示例: `gen_translation_shards.py <work>
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
6. 术语/人名一致性: 靠 `glossary.json` 单文件(edit 工具维护)+ 每 chunk
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

### Write-first prompt 契约 (mandatory)

**执行顺序必须明写为"先写,后思考,再改"** — 读完材料后第一动作就是
Write 译文进文件,严禁在思考/计划里结束(一轮 10-11 个 agent 常有 3-5 个
死于无文件;同会话重试基本全恢复)。Write-first prompt contract
(每个 agent prompt 原样包含):

1. Read rules once, read chunk_NN.ja.txt keys once.
2. **Immediately** Write `chunk_NN.zh.txt` first pass for ALL keys
   (unsure: best guess + `【?】`).
3. Read back, improve with a second Write.
4. Final reply = file path + entry count only.
Plus: "Never end before the file exists. Write first, polish later."
prompt 里再加三条明令:
值必须是译文(不得把日文原文写进值)、zh.txt 每行一个译文且行数与 ja.txt
一致(键内嵌真实换行在文件里以字面 `\n` 表示,勿写真实换行)、
控制码写完要数。

- **每个返回的 zh.txt 立即用 `merge_plain_chunks.py` 验证**;可恢复滑落:
  缺行(行数不匹配)、把字面 `\n` 写成真实换行。
- **agent 结束后跑值卫生修复**:折叠双反斜杠、剥离 `【?...】`、diff
  控制码 token 键值两侧。
- **若之后修复了值,构建里已经是旧值** — 按键匹配的补丁不会重新生效;
  用 旧→新 值映射反向打补丁。
- **残留检测**:在**最终构建**上测假名;walker 必须让顶层列表 JSON
  (CommonEvents.json) 走事件 walker,否则静默漏掉它全部对话。

## 顺序

`build` → (`decrypt` 仅 RPG Maker MZ/MV easy 加密时) → `audio` → `clean`
→ `verify --source` → `serve --test` → 新端口 HTTP 试玩 → `compress` 最后。
