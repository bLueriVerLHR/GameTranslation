# GameTranslation

面向 **RPG Maker** 和 **Unity** 等方便翻译的游戏而设计的 **JP→ZH 翻译流程**；
RPG Maker 游戏有打包成 **JoiPlay** 可玩的完整流程。本项目仅由
**DeepSeek V4 Flash** 编写，基本没有人工编写代码。

把 **RPG Maker MZ/MV** 游戏转换成 **JoiPlay 可玩**的构建：
剥离桌面运行时（NW.js）、解密加密资源（仅 easy 加密）、压缩音频、
清理无用文件、验证、HTTP 测试、打包成 `7z-zstd` 压缩包。

```
GameTranslation/
├── pipeline.py          # RPG Maker 命令行（build → decrypt → audio → clean → verify → serve/compress）
├── rpgmz/               # RPG Maker 工具包
│   ├── config.py        #   工具发现（ffmpeg/ffprobe/7z）+ 阈值
│   ├── detect.py        #   引擎 / 网页根目录检测（MZ 根部署 vs MV www/）
│   ├── build.py         #   拷贝网页文件，剥离 NW.js 运行时（asyncio + 并行拷贝）
│   ├── decrypt.py       #   仅 easy 解密：带 RPGMV 头的资源解密；
│   │                    #   复杂/自定义加密文件原样保留并保持标志位
│   ├── audio.py         #   探测 + 重编码 Vorbis（asyncio + 线程池）
│   ├── clean.py         #   安全清理：img 垃圾、未用字体、未用图块
│   ├── verify.py        #   PNG/JSON/标志位/音频引用/解码检查（--source 感知）
│   ├── compress.py      #   7z-zstd 打包（替换旧包）+ 完整性测试
│   └── serve.py         #   HTTP 服务器 + 冒烟测试
├── tools/
│   ├── build_translation.py   # 提取模板/上下文/种类/结构/人名/人名宏
│   │                          #   + 插件参数文本（js/plugins.js）
│   ├── gen_translation_shards.py # 切成双文件块：ja.txt + zh.txt + context.md
│   │                             #   （自动选档：90KB 上下文预算，约 11k 字符/块）
│   ├── gen_completion_shards.py  # 补翻流程分块（同布局、同尺寸）
│   ├── merge_plain_chunks.py     # 合并 ja/zh 对 -> chunks_translated.json + QC
│   ├── merge_translation.py      # 最终合并：chunks + prefilled + sweep 规则 -> translated.json
│   ├── patch_contexts.py         # 向 context.md 注入语气段 + 写优先规则
│   ├── bake_translation.py       # 精确匹配静态烘焙（data + 插件参数 + CJK 字体）
│   ├── plugin_json_leaves.py     # 插件参数内嵌 JSON 的叶子级翻译：extract 收集
│   │                             #   显示叶子（含深层 JSON 递归），rebuild 按叶子
│   │                             #   重建整串参数供烘焙（大 JSON 参数专用）
│   ├── plain_io.py               # 双文件块格式的共享转义/IO
│   ├── plugins_io.py             # 容错 js/plugins.js 解析/序列化
│   ├── extract_remaining_text.py # 残留假名提取器（补翻流程，故事顺序）
│   ├── unlock_gallery.py         # 可选：解锁 CG 回想（启动插件）
│   ├── patch_names.py            # 用规则文件统一字典里的角色名写法
│   ├── rmunite/                  # RPG Maker Unite（Unity Mono）翻译：提取、
│   │                             #   BepInEx+Harmony 运行时 hook 插件、系列预填
│   └── ...（旧版：translate_rpgmz、extract_text、plain_to_translated、
│           qc_translation_chunks、CSV 流程工具 — 旧块格式）
└── docs/
    ├── workflow.md      # RPG Maker 转换工作流（本指南）
    ├── translation.md   # 统一翻译工作流（全量 + 补翻，一套参数：10 并行、
    │                    #   auto 分块约 11k 字符/块）
    ├── experience.md    # 会话经验日志（坑、失败模式）
    └── table/           # 本地名词表/翻译资料库（glossary/tone/notes + 词表）—
                         #   LOCAL ONLY, gitignored, 绝不推送（游戏名 + 成人词表留本地）
```

## 快速开始 — RPG Maker

```powershell
$tk  = "<本工具库路径>"
$src = "C:\path\to\game"
$out = "$env:LOCALAPPDATA\Temp\opencode\game_JoiPlay"   # 工作目录（Temp，可删）
$g   = "<交付目录>"   # 成品放这里，和以往每个游戏一致

python $tk\pipeline.py build   $src -o $out
python $tk\pipeline.py decrypt $out          # 仅 RPGM + easy 加密；否则跳过
python $tk\pipeline.py audio   $out
python $tk\pipeline.py clean   $out
python $tk\pipeline.py verify  $out --source $src   # 源感知的音频引用检查
python $tk\pipeline.py serve   $out --test     # HTTP 冒烟测试
python $tk\pipeline.py compress $out -o "$g\game_JoiPlay.7z"
```

`decrypt` 默认只在 RPG Maker MZ/MV 且为 **easy** 加密（每个加密资源都带
标准 RPGMV 头）时运行。复杂/自定义加密游戏里它保持原样并跳过。总原则：
如果解密不会改变游戏在 JoiPlay 下的运行方式，就不运行。

`build`/`decrypt`/`audio` 并行运行（asyncio + 线程池）；每步可用
`--workers N` 调整。`verify --source <原版>` 把原版里本来就缺失的引用从
失败降级为警告——只有转换造成的丢失才判失败。

目录约定：工作/解压副本一律放 **Temp** 目录（绝不放在源目录旁边），
成品 JoiPlay 目录和 `.7z` 放专门的交付目录，命名 `<Game>_JoiPlay` /
`<Game>_JoiPlay.7z`，与其他转换过的游戏一致。

- `python pipeline.py --help` 查看全部选项。
- `audio`、`clean`、`verify` 支持 `--sample N` / `--dry-run` / `--decode`
  用于试跑和快速检查。
- **压缩前务必先测**：`serve --test` 检查构建能否正常服务，也可以在
  浏览器里通过 HTTP 打开游戏试玩。最后才压缩。

完整指南见 **[docs/workflow.md](docs/workflow.md)**。

## 翻译（JP → ZH）

统一翻译工作流（[docs/translation.md](docs/translation.md)）涵盖
RPG Maker 静态翻译（提取 → 词表 → subagent 分块 → 精确匹配烘焙）、
残留假名补翻、插件参数文本——以及 Unity 游戏的运行时 hook 翻译
（`tools/rmunite/`、MelonLoader、BepInEx+Harmony；引擎记录见 `AGENTS.md`）。

- **Subagent**：每轮 10 个并行，写优先 prompt 契约，auto 分块
  （约 11,000 字符）配 90KB 上下文预算。
- **本地名词表**（`docs/table/`，gitignored，仅本地使用）：翻译用语库 —
  每游戏子目录的 `glossary.json`（术语/人名表）+ `tone.md`（语气/风格）+
  `notes.md`（该游戏经验与坑），以及通用词表；分块时注入每个 chunk 的
  context.md 供 agent 遵循。该目录不入库、不推送（含成人词表，保持私有）。

## 环境要求

- Python 3.10+
- ffmpeg/ffprobe（含 libvorbis；默认路径在 `%LOCALAPPDATA%\Temp\opencode\`）
  — 仅 **audio** 步骤使用
- 7-Zip-Zstandard（默认 `C:\Program Files\7-Zip-Zstandard\7z.exe`）
- ripgrep（`rg`）用于构建内的快速内容搜索（如 `rg -n "process\." js/plugins/*.js`）
- Everything（`es` CLI）用于跨盘即时文件名查找（如 `es "game name"`）
