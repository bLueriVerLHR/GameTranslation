# 仓库布局（参考）

本文件是仓库目录树的**唯一权威位置**。`README.md` 只保留入口链接，
不再内嵌整棵树。

`README.md`、`AGENTS.md`、`LICENSE`、`.gitignore`、`.gitattributes` 与
`pyproject.toml` 是仓库根目录的元数据文件，不在上面的工具布局树里
（`tools/check_docs.py` 的 `EXCLUDED_ROOT_FILES` 白名单同样排除它们）。
它的作用是防止「树里写了但文件已删」或
「仓库里有文件但树完全没提」——**它是辅助一致性检查，不是语义检查**：
某个文件属于哪个引擎、是不是现役，看
`docs/reference/support-matrix.md` 与 `rpgmaker/inventory.py`（模块清单，
`tests/test_inventory.py` 守卫）。

本地私有数据（词表/密码/字体/每游戏资料）不在树里，也从不入库：
布局见 `docs/reference/local-layout.md`。

```
GameTranslation/
├── pipeline.py          # RPG Maker CLI 包装（命令定义在 rpgmaker/cli.py，Typer）
├── pyproject.toml       # 打包/依赖/lint/coverage 的唯一配置（版本取 rpgmaker.__version__）
├── uv.lock              # 全量依赖锁定（uv lock 生成，含 extra，仅审计/复现用）
├── CHANGELOG.md         # 面向使用者的变更记录（Keep a Changelog；弃用/删除在此留痕）
├── .github/workflows/ci.yml # CI 矩阵：Windows + Ubuntu × py3.10/3.12 + wheel 可用性
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
│   ├── ui_lang.py       #   引擎 UI 本地化（tyrano/lang.js 的 word 块，按键匹配 + 机械门禁）
│   ├── ui_lang_zh.json  #   引擎级可复用映射：TyranoScript 6.00 引擎文案 → 中文
│   ├── clean.py         #   MTool 残留 / 桌面运行时垃圾清理
│   ├── verify.py        #   布局/存档后端/音频引用/PNG 4096 检查（--source 感知）
│   ├── tyrano_extract.py #  TyranoBuilder .ks 解析（tb_start_text 块、speaker 行、text= 属性）
│   └── pipeline.py      #   命令行：build → audio → clean → fix-autoplay → localize-ui → verify → serve → compress → deliver
├── unity/               # Unity 工具包（仅翻译 + 运行时注入，绝不用流水线）
│   └── rmunite/         #   RPG Maker Unite（Unity Mono）翻译：提取、
│                        #   BepInEx+Harmony 运行时 hook 插件、系列预填
│       ├── extract_game.py  #   Addressables bundle 文本提取（UnityPy typetree）
│       ├── prefill.py       #   系列预填（借已翻译作品的词条/剧情字典）
│       └── RMUniteTranslation_plugin.cs # BepInEx + Harmony 运行时 hook 插件
│                        #   （IL2CPP/MelonLoader、Mono/AutoTranslator 见 docs/engines/unity.md）
├── rpgmaker/            # RPG Maker MZ/MV 工具包（两者通用，见 detect.py）
│   ├── cli.py           #   两个入口的 Typer 命令（serve/compress/deliver 只定义一次）
│   ├── archive.py       #   7z 唯一入口：py7zr（zstd）create/verify/extract；
│   │                    #   Windows 侧仍走 7z.exe 桥（跨系统规则）
│   ├── media.py         #   媒体唯一入口：PyAV 探测/解码 + VP9/Opus 转码
│   │                    #   （不需要 ffprobe，视频也不需要 ffmpeg CLI）
│   ├── jssyntax.py      #   JS 语法检查唯一入口（tree-sitter，进程内）
│   ├── io_boundary.py   #   文本/JSON/JSONL 读写唯一入口（原子写、BOM 容错、
│   │                    #   两种字节精确 JSON 风格、备份）
│   ├── japanese.py      #   日文假名检测正则（core：各引擎直接 import，
│   │                    #   不再需要把 tools/ 放进 sys.path）
│   ├── plugins_io.py    #   容错 js/plugins.js 解析/序列化（core，同上）
│   ├── cliutil.py       #   每个工具的 Typer 约定：-v/-q/--log-file、
│   │                    #   main(argv)->exit code（不再用 argparse）
│   ├── platform.py      #   平台/存储侧判定 + 路径转换（唯一权威）：
│   │                    #   PathDomain/StorageSide/PathRef + 同侧写入门岗
│   ├── settings.py      #   本地私有布局唯一映射（PRIVATE_PATHS）+ 机器配置
│   │                    #   校验/版本（旧 docs/table 只读回退）
│   ├── textencoding.py  #   .ks 字节编码探测 + 容错解码（core；KiriKiri 与
│   │                    #   Tyrano 共用的唯一实现，含无 BOM 字节序判定）
│   ├── constants.py     #   RPG Maker 构建常量（头/阈值/4096/网页目录等）
│   ├── tool_registry.py #   外部程序注册表 + 解析（env→配置→探测→PATH），
│   │                    #   ToolStatus 分级；doctor 的报告来源
│   ├── deliverables.py  #   交付/临时目录探测与默认值（可写性检查）
│   ├── workspace.py     #   每游戏工作区根解析（--work-dir→环境→系统临时→.tmp）
│   ├── assets.py        #   字体等本地资产：解析 “用哪个文件”
│   ├── fontpolicy.py    #   字体策略与 manifest 校验：“是否应用” +
│   │                    #   sha256 校验（required 失败 / auto 只报告 / preserve 不动）
│   ├── config.py        #   已退休的兼容层：只 re-export 上面各模块（无逻辑），
│   │                    #   保留一个兼容周期；仓库内已无人 import
│   ├── runtime.py       #   环境感知调优：CPU/内存/磁盘类型探测 + 自动并行度
│   ├── detect.py        #   引擎 / 网页根目录检测（MZ 根部署 vs MV www/）
│   ├── inventory.py     #   模块清单（唯一权威）：每个生产模块的状态/种类/
│   │                    #   所属引擎/是否进 wheel；tests/test_inventory.py 守卫
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
│   ├── qc_build_kana.py       # MZ/MV：**烘焙后**构建的假名残留 + %N 一致性
│   │                          #   （验收硬指标；插件参数只做「按决策排除」计数）
│   ├── resolve_text_keys.py   # MZ/MV：运行期文本键 `\T[键]` 在构建期落成真
│   │                          #   文本（游戏自带 csv 文本表 + 随包字典）
│   ├── check_iscript_js.py    # KiriKiri：扫 [iscript] 块做 JS 语法检查
│   │                          #   （tree-sitter，进程内；不需 node）
│   │                          #   （TJS→JS 转换错误不报错，只让脚本停摆）
│   ├── transcode_video.py     # 影片 .wmv/.mpg → WebM(VP9+Opus)，编码后用 PyAV
│   │                          #   解码自检（convert_kag.py --video-dir 消费其输出）
│   ├── downscale_images.py    # 把超过 4096 的 PNG 就地缩放到 ≤4096
│   │                          #   （单一构建策略，替代旧 LowRes 变体；自动并行）
│   ├── fix_mojibake_names.py  # 修复「Shift-JIS 名被按 CP936 解出」的乱码文件名
│   │                          #   （引擎按原名加载，改名后才找得到；默认 dry-run）
│   ├── fit_texture_4096.py    # 超限贴图的保正确处理：Aseprite 图集重排
│   │                          #   （PNG+JSON 帧矩形同步改写，像素级无损）
│   │                          #   与 IconSet 行边界裁剪（32px 网格不变）；
│   │                          #   这两类机械缩放会破坏帧/图标寻址
│   ├── gen_translation_shards.py # 切成双文件块：ja.txt + zh.txt + context.md
│   │                             #   （自动选档：90KB 上下文预算，约 11k 字符/块）
│   ├── gen_completion_shards.py  # 补翻流程分块（同布局、同尺寸；注入 tone.md）
│   ├── merge_plain_chunks.py     # 合并 ja/zh 对 -> chunks_translated.json + QC
│   ├── merge_translation.py      # 最终合并：chunks + prefilled + sweep 规则 -> translated.json
│   ├── bake_translation.py       # 精确匹配静态烘焙（data + 插件参数 + 字体策略）
│   ├── plugin_json_leaves.py     # 插件参数内嵌 JSON 的叶子级翻译：extract 收集
│   │                             #   显示叶子（含深层 JSON 递归），rebuild 按叶子
│   │                             #   重建整串参数，apply 写回 js/plugins.js
│   │                             #   （大 JSON 参数专用；功能键/标识符原样保留）
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
│   ├── check_all.py             # 本地门禁总入口：一次跑完 hygiene/lint/docs/tests（CI 仍是最终权威）
│   ├── check_docs.py            # 目录树一致性 + 文档门禁（本文件即其默认输入）
│   ├── skip_report.py           # skip 清单：每个 skip 归到哪个能力，未归类的失败
│   ├── check_coverage.py        # 覆盖率下限门禁（区域/高风险模块/总量，只平只升）
│   ├── mypy_check.py            # 类型门禁：全仓错误数只降不升 + strict 模块层零错误
│   ├── mutation_check.py        # 变异表：翻译门禁/归档校验/同侧拒绝/解密标志必须被检出
│   └── ...（旧版：translate_rpgmaker、extract_text、plain_to_translated、
│           qc_translation_chunks、CSV 流程工具 — 旧块格式）
├── tests/                # 单元 + 集成测试（pytest，fake 工具，全流程无外部依赖）
│   ├── README.md         #   分层契约：marker 语义、各层运行命令与环境要求
│   ├── conftest.py       #   合成游戏/假 ffmpeg 注入 + 真媒体固件生成
│   ├── fixtures/         #   真容器固件（Ogg Vorbis 带 LOOP 标签、asar 包、TLG 样本）
│   │   └── MANIFEST.json #   固件清单：来源/用途/许可/sha256（test_fixture_manifest.py 守卫）
│   ├── coverage_floor.json # 覆盖率下限基线（tools/check_coverage.py 的输入）
│   ├── fake_tools/       #   测试用假工具脚本（FFMPEG 环境变量注入）
│   ├── test_*.py         #   各模块单元测试 + pipeline 端到端集成测试
│   ├── test_integration.py  # build→decrypt→clean→verify→serve→compress→deliver
│   ├── test_inventory.py    # 模块清单守卫（无未分类文件、无幽灵条目、wheel 边界）
│   ├── test_cli_smoke_entries.py # 每个入口的 --help 子进程冒烟（cp1252 条件下）
│   ├── test_text_io_portability.py # 文本 I/O 不得依赖本机 locale 编码（含 BOM 检查）
│   ├── test_lockfile.py     # 锁文件门禁：uv.lock 必须与 pyproject.toml 同步
│   ├── test_package_boundaries.py # core 不得 import 引擎、引擎间不得互相 import
│   ├── test_config_facade.py # 已退休的 config 兼容层：谁也不能 import 它
│   ├── test_fixture_manifest.py # 固件必须有清单且字节未变（防“重生成固件让测试变绿”）
│   ├── test_test_layers.py  # 测试分层门禁：marker 注册、每层都有地方跑、skip 预算
│   ├── test_textencoding.py # .ks 编码探测门禁：四种 BOM/字节序组合、两引擎同一实现
│   └── test_wheel_contents.py # 打包门禁：wheel 必须含所有公开入口 + 装到外部目录可导入
└── docs/
    ├── index.md         # 文档入口（按教程/操作指南/参考/原理导航）
    ├── workflow.md      # RPG Maker 转换工作流（JoiPlay 构建）
    ├── translation.md   # 翻译工作流 v2 指南（单译者 + 文件信箱 + 五道门禁）
    ├── translation-data.md  # 翻译数据契约（键表/译文库/控制码/写回）
    ├── translation-qc.md    # 翻译 QC 与故障排除
    ├── wolfrpg.md       # Wolf RPG 翻译指南（解包/提取/分块/编码/运行，含坑）
    ├── kirikiri.md      # KiriKiri 翻译指南（解包/提取/写回/patch.xp3/QC）
    ├── kirikiri-html.md # KiriKiri→HTML5 移植调研（JoiPlay 插件 / TyranoScript 转换 / WASM 对比）
    ├── kirikiri-tyrano.md # KiriKiri→TyranoScript 转换指南（支持程度分档 + 所需软件清单）
    ├── tyrano.md        # TyranoScript/TyranoBuilder 指南（JoiPlay 构建 + 翻译）
    ├── engines/         # 各引擎专项（AGENTS.md 的引擎索引指向这里）
    │   ├── unity-il2cpp.md # Unity IL2CPP + Addressables：MelonLoader 运行时 hook
    │   ├── unity-rmunite.md # RPG Maker Unite（Unity Mono）：BepInEx + Harmony
    │   └── unity.md     # Unity 总览：范围、目录、广告清理、病毒检查、翻译状态
    ├── experience.md    # 经验库索引（各主题经验入口，见下 experience-*）
    ├── experience-decrypt.md  # 经验：解密/解包/Repacker 识别
    ├── experience-audio-clean.md # 经验：音频/清理/打包
    ├── experience-translation.md  # 经验：翻译工作流/烘焙/QC/补翻
    ├── experience-tyrano.md   # 经验：TyranoScript 构建/移植
    ├── experience-misc.md     # 经验：其他/杂项（服务卫生/CG解锁/运行兼容）
    ├── CONTRIBUTING.md  # 贡献指南（分支/提交/自查/测试/语言/合并推送）
    ├── screenshot.md    # WSL 互操作（WSLInterop binfmt 条目）的前提与排障；
    │                    #   画面验证走浏览器自动化截图 + 读图
    ├── archive/         # 退役流程与完成日志（历史归档，勿照它执行）
    │   └── ...          #   v1 翻译流程、手机转换完成日志
    └── reference/       # 参考（现状事实，非路线图）
        ├── support-matrix.md    # 支持矩阵：各引擎/能力/入口/状态/已验证层次
        ├── local-layout.md      # 本地数据布局：.private/.asset/workspace 边界
        ├── tooling.md           # 「能力 → 唯一入口 → 依赖包」对照表（外部程序解析唯一入口）
        ├── deprecation-policy.md # 弃用政策：记录位置、宽限期、可删除条件
        ├── repo-layout.md       # 本文件：仓库目录树（目录树唯一权威）
        ├── schema/              # 本地 JSON 的 schema（仓库只放 schema 与示例）
        │   ├── workspace.schema.json
        │   ├── font-manifest.schema.json
        │   └── font-manifest.example.json  # 示例（占位值，非真实字体）
        └── adr/                 # 架构决策记录
            └── ...
```
