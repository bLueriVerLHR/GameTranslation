# GameTranslation

面向 **JP→ZH 翻译 + 可玩构建** 的本地工具库；**DeepSeek V4 Flash**
编写，基本没有人工编写的代码。

## 游戏目的（2026-09 更新）

| 目的 | 引擎 | 做法 |
| --- | --- | --- |
| **可玩构建（JoiPlay）** | HTML5 系（RPG Maker MZ/MV 网页版） | 剥离 NW.js、解密（仅 easy）、压缩音频、清理、验证、7z-zstd 打包 —— `pipeline.py` |
| **可玩构建（JoiPlay）+ 翻译** | TyranoScript / TyranoBuilder（Electron 打包的 HTML5 视觉小说） | 解包 app.asar（`asar` 包，无需 Node.js）、剥 Electron 运行时、存档改 webstorage、mp3→ogg + 脚本引用同步重写、MTool 残留清理、验证 —— `tyrano/pipeline.py`；翻译走标准 chunk 流程写回 .ks |
| **移动端转换（当前主线）** | KiriKiri2 / KAG3 → TyranoScript | 保留脚本、图层、音画时序与交互语义，转换为网页工程，验证后在 Android JoiPlay 实机验收；见 `docs/kirikiri-tyrano.md` |
| **翻译 + 注入** | Unity / Wolf RPG / KiriKiri | 解包 → 提取 → 自译（统一 chunk/subagent 流程）→ 运行时 hook / 补丁注入；KiriKiri 桌面补丁路线仍可单独使用 |

当前优先改善 **KiriKiri → TyranoScript 的原作体验与手机可玩性**。
实施顺序与验收标准见 [手机转换改进计划](docs/kirikiri-mobile-plan.md)。
先验证画面层级、消息排版、动画与语音时序、选择分支和存读档；转换成功或
浏览器能打开不能代替 Android 实机验收。无法等价实现的功能必须记录影响，
经试玩评估取舍。翻译是独立工作阶段：**清除 MTool 机翻，自己翻译**。
Unity = MelonLoader/BepInEx 运行时 hook；Wolf RPG = rewolf-trans 补丁
回写；KiriKiri = patch.xp3 覆盖 scenario；TyranoScript = 标准 chunk
流程写回 .ks（构建/翻译双路线，见 `docs/tyrano.md`）。翻译能力按具体
游戏打补丁优化，游戏特定特征（引擎+特征案例、体量、坑）一律记录在**本地
`docs/table/<Game>/notes.md`**（gitignored，不入库），**不写进仓库文档**。

```
GameTranslation/
├── pipeline.py          # RPG Maker CLI 包装（命令定义在 rpgmaker/cli.py，Typer）
├── kirikiri/            # KiriKiri（吉里吉里）工具包
│   ├── xp3tool.py       #   XP3 解包（zlib 索引、0x80 间接块、raw/zlib 段，含受保护变体体检）
│   ├── xp3pack.py       #   XP3 打包（patch.xp3：raw 段 + zlib 索引 + 自校验）
│   ├── pipeline.py      #   通用移植流水线（probe/unpack/convert/verify/port，按 profile 跑）
│   ├── ks_extract.py    #   .ks 解析（编码探测、方括号配对、可译性判定）
│   ├── tjs2js.py        #   TJS2 → JavaScript 转换（KAG3 [iscript] 块）
│   ├── kag/             #   KAG3 → TyranoScript 转换器（原 convert_kag.py 拆分）
│   │   ├── cli.py       #     CLI（Typer）+ convert() 编排
│   │   ├── tags.py      #     pass 0：标签表与语料/引擎盘点（只读）
│   │   ├── scenario.py  #     pass 1-2：.ks 逐行转换
│   │   ├── assets.py    #     pass 3：素材名映射与媒体转换（TLG/BMP/影片）
│   │   ├── shims.py     #     pass 5：JS/CSS 垫片装配（文本在 js/）
│   │   ├── fonts.py     #     字体与排版注入（@font-face / 竖屏 CSS）
│   │   ├── project.py   #     输出工程组装（引擎骨架、宏、意图报告）
│   │   └── js/          #     垫片源码（真实 .js/.css，importlib.resources 读）
│   │       ├── runtime_shim.js
│   │       ├── map_engine.js
│   │       ├── noop_plus_real.js
│   │       ├── video_shim.js
│   │       ├── waitskip_shim.js
│   │       ├── fast_skip.js
│   │       └── portrait.css
│   ├── convert_kag.py   #   兼容层（历史导入路径 + 可运行入口，转调 kirikiri/kag/）
│   ├── tlg.py           #   TLG 图像解码（TLG5/TLG6，解包立绘/背景）
│   └── merge_font.py    #   中文字体 + 日文字体合并（中文方块修复）
├── translation/         # 翻译工作流 v2：一个子智能体全权负责，主智能体只烘焙
│   ├── codes.py         #   控制码解析 + 从游戏自身 JS 推导的码表（不硬编码）
│   ├── mvkeys.py        #   故事序键提取（MV/MZ：地图→公共事件→敌群→DB→UI→插件）
│   ├── prefill.py       #   从随包的运行时字典（MTool/AI）按精确匹配预填译文库
│   ├── rawlib.py        #   无转义译文库（@@@id@@@）+ 回改执行 + 五道硬门禁
│   ├── bake.py          #   译文库按 id 写回游戏数据（数组/对象两种命令形态）+ 统一字体
│   ├── workspace.py     #   工作区骨架 + 子智能体 MISSION（流程与规则写死）
│   └── cli.py           #   命令行：prepare/extract/scaffold/codes/slice/prefill/append/
│                        #     to-json/rewrite/gates/status/pending/decide/bake
├── wolfrpg/             # Wolf RPG（ウディタ）工具包
│   └── dxarchive.py     #   DXArchive v8 解包器（LZ/Huffman/KeyConv，从 UberWolf 移植）
├── tyrano/              # TyranoScript / TyranoBuilder 工具包
│   ├── asar.py          #   Electron app.asar 解包（用 asar 包，不重复造轮子）
│   ├── build.py         #   JoiPlay 构建：解包 asar、剥 Electron 运行时、存档改 webstorage
│   ├── audio.py         #   mp3→ogg 重编码 + scenario .ks 音频引用同步重写
│   ├── autoplay.py      #   [bgmovie] 自动播放策略补丁（.play() 拒绝时用户交互后重播）
│   ├── clean.py         #   MTool 残留 / 桌面运行时垃圾清理
│   ├── verify.py        #   布局/存档后端/音频引用/PNG 4096 检查（--source 感知）
│   ├── tyrano_extract.py #  TyranoBuilder .ks 解析（tb_start_text 块、speaker 行、text= 属性）
│   └── pipeline.py      #   命令行：build → audio → clean → fix-autoplay → verify → serve → compress → deliver
├── unity/               # Unity 工具包（仅翻译 + 运行时注入，绝不用流水线）
│   └── rmunite/         #   RPG Maker Unite（Unity Mono）翻译：提取、
│                        #   BepInEx+Harmony 运行时 hook 插件、系列预填
│       ├── extract_game.py  #   Addressables bundle 文本提取（UnityPy typetree）
│       ├── prefill.py       #   系列预填（借已翻译作品的词条/剧情字典）
│       └── RMUniteTranslation_plugin.cs # BepInEx + Harmony 运行时 hook 插件
│                        #   （IL2CPP/MelonLoader、Mono/AutoTranslator 见 AGENTS.md）
├── rpgmaker/            # RPG Maker MZ/MV 工具包（两者通用，见 detect.py）
│   ├── cli.py           #   两个入口的 Typer 命令（serve/compress/deliver 只定义一次）
│   ├── archive.py       #   7z 唯一入口：py7zr（zstd）create/verify/extract；
│   │                    #   Windows 侧仍走 7z.exe 桥（跨系统规则）
│   ├── media.py         #   媒体唯一入口：PyAV 探测/解码 + VP9/Opus 转码
│   │                    #   （不需要 ffprobe，视频也不需要 ffmpeg CLI）
│   ├── jssyntax.py      #   JS 语法检查唯一入口（tree-sitter，进程内）
│   ├── cliutil.py       #   每个工具的 Typer 约定：-v/-q/--log-file、
│   │                    #   main(argv)->exit code（不再用 argparse）
│   ├── config.py        #   工具发现（ffmpeg/7z/git...）+ 阈值 + 路径/平台转换
│   ├── runtime.py       #   环境感知调优：CPU/内存/磁盘类型探测 + 自动并行度
│   ├── detect.py        #   引擎 / 网页根目录检测（MZ 根部署 vs MV www/）
│   ├── evb.py           #   launcher 打包件：从 <Game>.exe 的 Enigma Virtual Box
│   │                    #   容器里还原 data/（命令 unpack-data）
│   ├── build.py         #   拷贝网页文件，剥离 NW.js 运行时（asyncio + 并行拷贝）
│   ├── plugincompat.py  #   JoiPlay 兼容：已知 NW.js-only 插件检查的定点维修 +
│   │                    #   模块顶层 process/require 预扫（命令 compat）
│   ├── decrypt.py       #   仅 easy 解密：带 RPGMV 头的资源解密；
│   │                    #   复杂/自定义加密文件原样保留并保持标志位
│   ├── audio.py         #   探测 + 重编码 Vorbis（asyncio + 线程池）
│   ├── clean.py         #   安全清理：img 垃圾、未用字体、未用图块（语料并行读取）
│   ├── verify.py        #   PNG/JSON/标志位/音频引用/解码检查（--source 感知，PNG 并行）
│   ├── compress.py      #   7z-zstd 打包（替换旧包，-mmt 自动线程）+ 完整性测试
│   ├── proctools.py     #   外部程序执行的唯一入口：超时 + UTF-8 解码 + 失败信息
│   ├── logsetup.py      #   唯一的日志配置：格式/等级/--verbose（禁止 import 期配置）
│   ├── doctor.py        #   环境自检：工具可用性 + env_config + deliverables
│   ├── deliver.py       #   写回存储侧：本地压缩 → 复制压缩包到压缩包目录
│   │                    #   （覆盖旧包）→ 删成品目录旧文件夹 → 解压到成品目录
│   └── serve.py         #   HTTP 服务器 + 冒烟测试
├── tools/
│   ├── build_translation.py   # 提取模板/上下文/种类/结构/人名/人名宏
│   │                          #   + 插件参数文本（js/plugins.js）
│   ├── build_wolf_translation.py # Wolf RPG：rewolf-trans 补丁 → 标准工作包
│   ├── apply_translation_to_patch.py # Wolf RPG：translated.json → 补丁注入
│   ├── build_ks_translation.py # KiriKiri：.ks 提取 → 标准工作包（故事顺序）
│   ├── apply_ks_translation.py # KiriKiri：translated.json → 补丁 .ks + patch.xp3
│   ├── build_tyrano_translation.py # TyranoScript：.ks 提取 → 标准工作包（整行键）
│   ├── apply_tyrano_translation.py # TyranoScript：translated.json → 写回 .ks
│   ├── qc_ks_kana.py          # KiriKiri：假名残留 QC（补丁树/字典值）
│   ├── check_iscript_js.py    # KiriKiri：扫 [iscript] 块做 JS 语法检查
│   │                          #   （tree-sitter，进程内；不需 node）
│   │                          #   （TJS→JS 转换错误不报错，只让脚本停摆）
│   ├── transcode_video.py     # 影片 .wmv/.mpg → WebM(VP9+Opus)，编码后用 PyAV
│   │                          #   解码自检（convert_kag.py --video-dir 消费其输出）
│   ├── downscale_images.py    # 把超过 4096 的 PNG 就地缩放到 ≤4096
│   │                          #   （单一构建策略，替代旧 LowRes 变体；自动并行）
│   ├── gen_translation_shards.py # 切成双文件块：ja.txt + zh.txt + context.md
│   │                             #   （自动选档：90KB 上下文预算，约 11k 字符/块）
│   ├── gen_completion_shards.py  # 补翻流程分块（同布局、同尺寸；注入 tone.md）
│   ├── merge_plain_chunks.py     # 合并 ja/zh 对 -> chunks_translated.json + QC
│   ├── merge_translation.py      # 最终合并：chunks + prefilled + sweep 规则 -> translated.json
│   ├── bake_translation.py       # 精确匹配静态烘焙（data + 插件参数 + 字体策略）
│   ├── plugin_json_leaves.py     # 插件参数内嵌 JSON 的叶子级翻译：extract 收集
│   │                             #   显示叶子（含深层 JSON 递归），rebuild 按叶子
│   │                             #   重建整串参数供烘焙（大 JSON 参数专用）
│   ├── plain_io.py               # 双文件块格式的共享转义/IO
│   ├── ctrl_codes.py             # 控制码共享单源：签名（结构化比对）与剥离
│   │                             #   （\N[1]/\RB[a,b]/Wolf :name[..]）
│   ├── plugins_io.py             # 容错 js/plugins.js 解析/序列化
│   ├── scenario_common.py        # KS/Tyrano 场景链共享胶水：场景目录发现、
│   │                             #   存储名解析、工作包写入（最小收敛）
│   ├── extract_remaining_text.py # 残留假名提取器（补翻流程，故事顺序）
│   ├── augment_adv_resources.py  # MZ TextResource 插件/ADV/SNS 文本资源：
│   │                             #   增强工作包（故事顺序）+ 原地烘焙（含低覆盖率闸门）
│   ├── unlock_gallery.py         # 可选：解锁 CG 回想（启动插件）
│   ├── patch_names.py           # 用规则文件统一字典里的角色名写法
│   ├── check_docs.py            # README 目录树 vs 实际仓库文件一致性校验
│   └── ...（旧版：translate_rpgmaker、extract_text、plain_to_translated、
│           qc_translation_chunks、CSV 流程工具 — 旧块格式）
├── tests/                # 单元 + 集成测试（pytest，fake 工具，全流程无外部依赖）
│   ├── conftest.py       #   合成游戏/假 ffmpeg/7z 注入 + 真媒体固件生成
│   ├── fixtures/         #   真容器固件（Ogg Vorbis 带 LOOP 标签、asar 包）
│   ├── fake_tools/       #   测试用假工具脚本（FFMPEG/SEVENZ 环境变量注入）
│   ├── test_*.py         #   各模块单元测试 + pipeline 端到端集成测试
│   └── test_integration.py  # build→decrypt→clean→verify→serve→compress→deliver
├── superseded/           # 已移除对象的历史归档（工具 + 其单测一起搬家，不删）
│   └── ...               #   不参与构建/测试，仅供查阅
└── docs/
    ├── workflow.md      # RPG Maker 转换工作流（JoiPlay 构建）
    ├── translation.md   # 翻译工作流 v2（单译者 + 文件信箱 + 五道门禁；
    │                    #   v1 切块流程仅存历史）
    ├── wolfrpg.md       # Wolf RPG 翻译指南（解包/提取/分块/编码/运行，含坑）
    ├── kirikiri.md      # KiriKiri 翻译指南（解包/提取/写回/patch.xp3/QC）
    ├── kirikiri-html.md # KiriKiri→HTML5 移植调研（JoiPlay 插件 / TyranoScript 转换 / WASM 对比）
    ├── kirikiri-tyrano.md # KiriKiri→TyranoScript 转换调研（路线 B 深化：支持程度分档 + 所需软件清单）
    ├── kirikiri-mobile-plan.md # 手机转换改进计划：体验优先级、实施阶段与验收标准
    ├── tyrano.md        # TyranoScript/TyranoBuilder 指南（JoiPlay 构建 + 翻译）
    ├── experience.md    # 经验库索引（各主题经验入口，见下 experience-*）
    ├── experience-decrypt.md  # 经验：解密/解包/Repacker 识别
    ├── experience-audio-clean.md # 经验：音频/清理/打包
    ├── experience-translation.md  # 经验：翻译工作流/烘焙/QC/补翻
    ├── experience-tyrano.md   # 经验：TyranoScript 构建/移植
    ├── experience-misc.md     # 经验：其他/杂项（服务卫生/CG解锁/运行兼容）
    ├── CONTRIBUTING.md  # 贡献指南（分支/提交/自查/测试/语言/合并推送）
    ├── screenshot.md    # WSL 互操作（WSLInterop binfmt 条目）的前提与排障；
    │                    #   画面验证走浏览器自动化截图 + 读图
    └── table/           # 本地名词表/翻译资料库/游戏特定特征记录（glossary/
                         #   tone/notes + 词表）— LOCAL ONLY, gitignored,
                         #   绝不推送（游戏名 + 成人词表留本地）
```

## 快速开始 — RPG Maker

```powershell
$tk  = "<本工具库路径>"
$src = "C:\path\to\game"
$out = Join-Path $env:TEMP 'game'              # 工作目录（Temp，可删）
$g   = "<交付目录>"   # 成品放这里，和以往每个游戏一致

python $tk\pipeline.py unpack-data $src      # 仅 launcher 打包件：把 data/ 从 <Game>.exe 还原出来
python $tk\pipeline.py build   $src -o $out
python $tk\pipeline.py compat  $out          # 插件加载期崩溃：定点维修 + 预扫（见 docs/workflow.md §4）
python $tk\pipeline.py decrypt $out          # 仅 RPGM + easy 加密；否则跳过
python $tk\pipeline.py audio   $out
python $tk\pipeline.py clean   $out
python $tk\pipeline.py verify  $out --source $src   # 源感知的音频引用检查
python $tk\pipeline.py serve   $out --test     # HTTP 冒烟测试
python $tk\pipeline.py compress $out -o "$g\game.7z"
python $tk\pipeline.py deliver $out            # 写回存储侧（压缩→压缩包目录→解压到成品目录）
```

`decrypt` 默认只在 RPG Maker MZ/MV 且为 **easy** 加密（每个加密资源都带
标准 RPGMV 头）时运行。复杂/自定义加密游戏里它保持原样并跳过。总原则：
如果解密不会改变游戏在 JoiPlay 下的运行方式，就不运行。

有些 repack 把数据库整个塞进 `<Game>.exe`（Enigma Virtual Box 打包件）：
磁盘上没有 `data/`，游戏照样能玩，但 `build` 会拒绝这种目录。先跑
`pipeline.py unpack-data $src` 把 `data/` 还原回源目录，再按上面顺序构建——
该命令只做「按容器表切片 + 逐文件 JSON 校验」，非 JSON 的打包残留
（repacker 推广标记）会报出并跳过。

`build`/`decrypt`/`audio` 并行运行（asyncio + 线程池）；每步可用
`--workers N` 调整。**默认自动调优**（`rpgmaker/runtime.py`）：按当前机器的
CPU 数、可用内存和磁盘类型（SSD/HDD）为每步选取最优并行度——IO 型步骤
（build/decrypt/verify PNG）偏多线程，CPU 型步骤（音频编码、解码检查）
按核数 + 内存上限收紧；可用 `GT_WORKERS=<n>`（全局）或
`GT_WORKERS_<KIND>=<n>`（分步，如 `GT_WORKERS_ENCODE=2`）环境变量覆盖。
`verify --source <原版>` 把原版里本来就缺失的引用从失败降级为警告——只有
转换造成的丢失才判失败。

目录约定：工作/解压副本一律放 **Temp** 目录（绝不放在源目录旁边），
成品 JoiPlay 目录和 `.7z` 放专门的交付目录，命名 `<Game>` /
`<Game>.7z`，与其他转换过的游戏一致。**写回存储侧用 `deliver`**：先在
平台内压缩成 7z，把压缩包复制到压缩包目录（覆盖旧包——通常就是源
压缩包），删除成品目录里的同名旧文件夹，再从压缩包解压到成品目录——
跨系统只搬运单个压缩包，避免大量小文件走 9P。**CRITICAL：处理文件必须
用「文件所在系统」的原生应用**——Windows 侧文件（`/mnt/*`）一律用
Windows 侧应用（`7z.exe`、PowerShell，经 `powershell.exe` 调用）处理；
WSL 内 7zz 解压/压缩 Windows 侧文件、WSL 内 python 直接操作 Windows 侧
文件均被禁止（曾致电脑花屏）。`deliver` 在 WSL 下自动桥接 Windows
7z.exe / `Remove-Item` 完成删除与解压。**单一构建策略**：所有
超过 4096 像素的 PNG 在构建期直接缩放到 ≤4096（`tools/downscale_images.py`），
保证 Android 上正常显示，不再分高清/低清两套。

- `python pipeline.py --help` 查看全部选项。
- `audio`、`clean`、`verify` 支持 `--sample N` / `--dry-run` / `--decode`
  用于试跑和快速检查。
- **压缩前务必先测**：`serve --test` 检查构建能否正常服务，也可以在
  浏览器里通过 HTTP 打开游戏试玩。最后才压缩。

完整指南见 **[docs/workflow.md](docs/workflow.md)**。

## 翻译（JP → ZH）

统一翻译工作流（[docs/translation.md](docs/translation.md)）涵盖
RPG Maker 静态翻译（提取 → 词表 → subagent 分块 → 精确匹配烘焙）、
残留假名补翻、插件参数文本——以及 **Unity / Wolf RPG / KiriKiri** 的
翻译 + 注入（运行时 hook 或补丁回写；引擎指南见 `docs/wolfrpg.md`、
`docs/kirikiri.md`、`AGENTS.md`）。共同路线：解包/提取 → 标准工作包 →
subagent 翻译 → `translated.json` → 注入。

- **Subagent**：**一个**翻译执行者（单写者）+ 文件信箱（`translation.cli`
  的 slice/append），五道硬门禁全绿才烘焙。
- **本地名词表 + 游戏特定特征**（`docs/table/`，gitignored，仅本地使用）：
  每游戏子目录的 `glossary.json`（术语/人名表）+ `tone.md`（语气/风格）+
  `notes.md`（该游戏经验、坑与特征）；分块时注入每个 chunk 的
  context.md 供 agent 遵循。该目录不入库、不推送（含成人词表，保持私有）。

## 测试

单元测试 + 综合测试位于 `tests/`（pytest，运行在项目 venv 里；
venv 解释器按平台取：POSIX `.venv/bin/python`，Windows
`.venv\Scripts\python.exe`）：

```bash
<venv-python> -m pytest tests/          # 全部测试
<venv-python> -m pytest tests/ -q       # 静默模式
```

- **单元测试**：config/runtime（自动并行度）、detect、evb（打包件 `data/`
  还原 + 切片自检）、decrypt（RPGMV 头
  XOR）、verify、build、clean、audio（位率策略）、plain_io（双文件块转义）、
  plugins_io、rvdata2（Ruby Marshal 解码）、merge_plain_chunks（QC 规则）、
  downscale_images、dxarchive（LZ/Huffman 往返 + 合成 .wolf 全包解包）。
- **集成测试**（`test_integration.py`）：在合成游戏上跑完整流水线
  build → decrypt → clean → verify → serve 冒烟 → compress → deliver，
  以及真实 CLI 子进程调用与退出码。
- **打包/媒体/日志已改用现成包**（不再手写 argv 与 stdout 解析）：
  `py7zr`（7z+zstd）、`av`/PyAV（探测与解码检查）、`typer`（CLI）、
  `pytest` + `pytest-xdist` + `pytest-cov`。详见 `pyproject.toml`。
- **并行跑测试是默认**（`addopts = "-n auto"`，本套 1400+ 用例 27.8s →
  11.2s）；`-n 0` 可改为串行。
- **lint 门禁**：`python -m ruff check .`，规则钉在 `pyproject.toml`（只选
  定位缺陷的 F/E9，不选风格类）；`tests/test_lint.py` 在装了 ruff 时会把
  同一命令当门禁跑，未装则跳过。
- **无外部工具也能跑**：`tests/fake_tools/` 提供假 ffmpeg/7z
  （经 `FFMPEG`/`SEVENZ` 环境变量注入，与真工具同协议），真实媒体用
  `tests/fixtures/sine_loop.ogg`（5.8 KB 真 Ogg Vorbis，带 LOOP 标签），
  测试不依赖系统安装的工具；服务冒烟测试用真实 HTTP 端口。

## 环境要求

- **Python 3.10+** 与六个运行时包：`typer`、`py7zr`、`av`、`asar`、
  `tree-sitter`、`tree-sitter-javascript`（外加可选的 `Pillow`/`numpy`，
  图像步骤；`fonttools`，字体合并）。项目自带本地虚拟环境 `.venv/`
  （gitignored）：`pip install -e ".[images,dev]"` 一次装齐（dev 额外装
  `pytest`/`pytest-xdist`/`pytest-cov`/`ruff`；字体合并再加 `.[fonts]`）。
- **ffmpeg**（含 libvorbis）— 仅 **audio** 步骤的音频编码用。探测/解码检查已
  改为 PyAV 在进程内完成（**不再需要 ffprobe**），视频转码也已改为 PyAV
  （libvpx-vp9 + libopus，**不再需要 ffmpeg 跑转码**）；PyAV 的 wheel 不含
  libvorbis，所以 Vorbis 编码仍用 ffmpeg CLI，质量策略与实测一致。
- **不再需要 Node.js**：app.asar 由 `asar` 包读取（原 `npx @electron/asar`），
  JS 语法检查由 tree-sitter 完成（原 `node --check`）。`node` 只剩一个用途：
  `tests/test_kag_audio_runtime.py` 要在真 JS 运行时里观察音频脚本的行为（没
  装则跳过）。
- Node.js（**仅测试**：`tests/test_kag_audio_runtime.py` 要在真 JS 运行时里
  观察音频脚本行为；未装则跳过。工具链本身不再调 node/npx）
- **7-Zip 只在 Windows 侧桥接时需要**：同侧打包/解包由 py7zr 在进程内
  完成（`rpgmaker/archive.py`，实测比 `7z.exe -mmt` 快且体积相同）；
  `deliver` 在 WSL 下写 Windows 侧目录时仍调 Windows `7z.exe`。
- ripgrep（`rg`）— **可选**，仅人工/agent 手动检索用（工具库代码里不调用
  `rg`：内容搜索是纯 Python 实现）

外部程序的实际路径不需要手工维护：`python pipeline.py doctor` 列出每个
程序的解析结果与来源（`env`/`config`/`probe`/`path`）与交付目录；
`doctor --json` 供脚本消费。

**本机环境配置（`docs/table/env_config.json`，gitignored 仅本地）是可选
覆盖层：** 所有外部程序都由 `rpgmaker/config.py` 的 `TOOLS` 表统一解析
（**环境变量 → 本地配置 → 自动探测常见安装位置 → PATH**），交付目录同样
先探测（工作区根下的 `Games`/`GamesCompress` 优先，再看各盘符与家目录）
再回到内置默认（同样是工作区根下的这两个目录，按需创建）——**没有配置
文件也能跑**。用 `python pipeline.py doctor` 看每个程序实际解析到的路径
与来源（`env`/`config`/`probe`/`path`），`doctor --json` 出机器可读版本；
`GT_NO_PROBE=1` 可关闭探测。配置里的工具路径支持 `*` 通配（WinGet 的
版本/哈希目录）。**工具只处理「同侧」文件**：
Windows 侧文件的处理（解压/压缩/脚本读写）必须由 Windows 侧应用完成
（从 WSL 经 `powershell.exe` 调用，路径用 Windows 格式）——WSL 内 7zz /
python 严禁直接操作 Windows 侧文件（CRITICAL，见上）。**字体（中文/日文打包字体）
放 `docs/table/fonts/`，自动发现，不写绝对路径**（可用
`docs/table/local_font_path.txt` 覆盖，支持相对路径；见
`docs/workflow.md` 标准字体策略）。工作流：源压缩包在存储侧 →
解压到系统临时文件夹 → 平台内处理 → 成品移到成品目录 → 压缩到压缩包
目录（详见 `docs/workflow.md`）。系统工具安装/下载由 owner 执行。

### WSL 快速开始 — RPG Maker

```bash
$tk = "<本工具库路径>"
cfg() { python3 -c "import sys; sys.path.insert(0, '$tk'); from rpgmaker import config; print(config.$1())"; }

$src = "<原版游戏路径>"                       # 绝不修改原版
$out = "$(cfg temp_dir)/game"                 # 系统临时文件夹（工作副本）
$g   = "$(cfg games_dir)"                     # 成品游戏目录
$ga  = "$(cfg archives_dir)"                  # 成品压缩包目录

python3 "$tk/pipeline.py" unpack-data "$src"   # 仅 launcher 打包件：还原 <Game>.exe 里的 data/
python3 "$tk/pipeline.py" build   "$src" -o "$out"
python3 "$tk/pipeline.py" decrypt "$out"          # 仅 RPGM + easy 加密；否则跳过
python3 "$tk/pipeline.py" audio   "$out"
python3 "$tk/pipeline.py" clean   "$out"
python3 "$tk/pipeline.py" verify  "$out" --source "$src"
python3 "$tk/pipeline.py" serve   "$out" --test
python3 "$tk/pipeline.py" compress "$out" -o "$ga/game.7z"
python3 "$tk/pipeline.py" deliver "$out"      # 写回存储侧（压缩→压缩包目录→解压到成品目录；
                                              # WSL 下删除/解压自动桥接 Windows 7z.exe）
```
