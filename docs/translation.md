# 翻译流程（RPG Maker MZ/MV）

v2 翻译流程 = 一个翻译执行者（单写者，磁盘状态为权威）+ 文件信箱 + 五道硬门禁。
本文件写流程与命令。相邻文档各管一件事：

| 想知道 | 看 |
|---|---|
| 键表、译文库、控制码、写回、提取范围、门禁判据 | `docs/translation-data.md` |
| 失败模式、QC 清单、故障排查 | `docs/translation-qc.md` |
| 已退役的切块流程与旧工具链 | `docs/archive/translation-v1.md` |
| 本地词表、语气、字体策略的存放位置 | `docs/reference/local-layout.md` |

## 1. 两个角色

| 角色 | 负责 | 不负责 |
|---|---|---|
| 编排者（主智能体） | 提取键表、推导控制码表、跑五道硬门禁、转 JSON、烘焙、统一字体、交付 | 语言判断 |
| 翻译执行者（一个） | 人名与语气草案、分块翻译、二义记录、回改决定 | 写 JSON、转义、改构建 |
| 工具（`translation/`） | 上述两者之外的重复劳动 | — |

译文库只有一个写入口（`append`）。状态文件与译文库都在磁盘上，所以执行者断线
或换新上下文后按磁盘状态接着做；任务书由 `prepare` 生成，位于
`<work_dir>/MISSION.md`。

## 2. 命令

`python -m translation.cli --help` 列出全部子命令：

| 命令 | 作用 |
|---|---|
| `prepare <game_dir> <work_dir>` | 提取键表并搭好工作区（`extract` + `scaffold`） |
| `extract <game_dir> <work_dir>` | 只提取：故事序 `keys.jsonl`、控制码表、统计 |
| `scaffold <work_dir>` | 只搭工作区：状态文件与 `MISSION.md`，不覆盖已有内容 |
| `codes <work_dir>` | 从游戏自身 JS 与观测计数重建 `control_codes.md` |
| `slice <work_dir>` | 取一批键交给执行者 |
| `prefill <work_dir> <dict.json>` | 从随包运行时字典精确匹配预填 |
| `append <work_dir> --batch <file>` | 校验批次后原子追加（唯一写入口） |
| `to-json <work_dir>` | raw 译文库 → `translated.json` 与 `translated_ids.json` |
| `rewrite <work_dir>` | 执行 `rewrites.jsonl` 的全量回改 |
| `gates <work_dir>` | 五道硬门禁；退出码非零即不得烘焙 |
| `pending <work_dir> --why "..."` | 记录待决问题（转义由工具做） |
| `decide <work_dir> --all-open --reason "..."` | 追加式裁定，关闭待决 |
| `status <work_dir>` | 进度：键数、已译、待决、上次门禁结果 |
| `bake <game_dir> <work_dir>` | 按 id 写回 + 统一字体 + KV 归档 |

常用调用：

```bash
python -m translation.cli prepare <game_dir> <work_dir> [--window N] [--note-tags A,B]
python -m translation.cli slice  <work_dir> --start N --count M --lean --out <file>
python -m translation.cli slice  <work_dir> --count M --lean --todo --out <file>
python -m translation.cli prefill <work_dir> <runtime.json> [--out <batch>]
python -m translation.cli append <work_dir> --batch <file> --fix-leading --note "..."
python -m translation.cli pending <work_dir> --id X --why "..."
python -m translation.cli decide  <work_dir> --all-open --reason "..."
python -m translation.cli to-json <work_dir> [--out translated.json]
python -m translation.cli gates   <work_dir> [--markdown <file>]
python -m translation.cli rewrite <work_dir>
python -m translation.cli bake    <game_dir> <work_dir> [--font-only] [--dry-run]
```

关键选项：

| 选项 | 作用 |
|---|---|
| `prepare --window N` | 每个键保留的上下文行数（默认 2） |
| `prepare --note-tags A,B` | 把这两个插件标签的载荷当文本提取，默认关闭 |
| `slice --lean` | 去掉上下文行，只留 `id`/`ja`/`speaker`/`where` |
| `slice --compact` | 去掉 `where`/`kind`/`seq` |
| `slice --todo` | 跳过译文库已有译文的键 |
| `slice --kind` | 只取一类：`map`/`common`/`troop`/`db`/`ui`/`plugin` |
| `append --fix-leading` | 从原文补回漏掉的前导控制码 |
| `decide --id X` | 只裁定一条 |
| `decide --dry-run` | 只列出会被关闭的条目 |
| `bake --font-policy` | `required` 默认（字体不可用即失败）/ `auto` 只报告 / `preserve` 不动字体 |
| `bake --no-font` | 跳过统一字体步骤 |
| `bake --font-only` | 只做统一字体步骤（文本已烘焙时用） |

工作方式：

- `slice` 交出一批键，执行者译完用 `append` 落盘，再取下一批。
- `--lean` 去掉上下文行：长跑里读切片比翻译本身更贵，实测省 57%；`speaker`
  与故事序已足够保持场景连贯。
- `gates` 的退出码非零表示门禁未全绿；`bake` 的退出码非零表示有键被跳过
  （逐条打印在日志里）。
- `to-json` 是唯一转义点，写 `translated.json`（`{原文: 译文}`）与
  `translated_ids.json`（`{id: 译文}`）；`bake` 按 id 写回，读的是后者。
- `bake` 先把每个被改动的文件备份到 `<work>/backup/<相对路径>`，并把译文库
  复制为 `<game_dir>/translation_kv.json`；`--dry-run` 只报告，不写盘。

## 3. 预填（repack 自带运行时字典时先跑）

repack 常带一个运行时替换字典（`<title>.json`、`AI翻译.json`、
`…翻译文件.json` 等）。字典的键是运行时形态：控制码被剥掉、整条消息用 `\n`
拼接，还含片段键，所以**不能直接烘焙**（贪心片段替换会把助词替换到词中间，
毁掉句子）。字典的值是已经看过的译文，可以安全地用来预填：

```bash
python -m translation.cli prefill <work_dir> "<游戏目录>/<字典>.json"
python -m translation.cli append  <work_dir> --batch <work_dir>/prefill.batch.txt --fix-leading --note "harvest"
python -m translation.cli status  <work_dir>
```

- 只做精确匹配：先整串命中；未命中时剥掉首尾控制码后再查，命中则把值重新
  包回那串控制码。子串匹配与逐步缩短的贪心匹配一律不做。
- 控制码夹在行中间、字典值自带控制码等情形单独计数，这些键留给执行者。
- 预填结果写成批次文件，不直写译文库：`append` 仍是唯一写入口，每个预填值与
  手写值过同一套门禁。会撞门禁的候选在 `prefill` 阶段剔除并逐类报告，否则
  两万条的批次会因一条不合格而整体被拒。
- 预填后执行者用 `slice --todo` 取活，不必自己数 `--start`。
- 报告字段：`harvested`（可用候选）、`rejected`（被门禁剔除）、`missed`
  （字典没命中，含控制码夹在行中间的）、`rejected_by`（剔除原因分类）、
  `lookup`（整串命中、剥码命中、值自带控制码等分项计数）。`missed` 多通常
  是字典覆盖不足或键形不同，不是脚本故障。

## 4. 统一字体（交付硬要求）

中文构建必须统一字体，否则中文落在系统回退字体上、字形不统一。改动点有三处，
缺一处就会出现两套字体：

1. 引擎字体面：MV 改 `fonts/gamefont.css` 的 `@font-face`；MZ 改
   `data/System.json`（带字体切换插件的构建只改这里，插件在运行时注册的
   `FontFace` 会覆盖 CSS 拆分）。
2. 插件参数里的字体名：消息插件带按语言切换的字体参数
   （`Font Name CH = "SimHei, Heiti TC, sans-serif"`），于是对白用系统黑体、
   界面用 `GameFont`。CSS 层救不了它，字体名是插件参数值；`bake` 把 font
   形状的参数指向统一字族。
3. 插件 JS 里硬编码的 `font-family`，例如 HUD 自建 HTML 的 CSS。

字体策略（`required`/`auto`/`preserve`）、字体清单与校验、已有翻译默认保留
原字体，见 `docs/reference/local-layout.md` §4–5。字体策略表或字体资产缺失时
必须 WARN 并说明缺了什么，不得当成已应用。

## 5. 归档与相邻流程

- v1 的流程（切块 → 每块一个执行者 → 逐行对齐 → 合并 → 烘焙）在
  `docs/archive/translation-v1.md`，**不得再用于 MZ 翻译**。非 MZ 引擎
  （TyranoScript、Wolf RPG、KiriKiri）的提取与写回走各自指南的统一 chunk 链。
- v1 的失败模式、QC 清单、术语审计见 `docs/translation-qc.md`，按引擎无关的
  教训阅读。
- v1 的补翻链（`extract_remaining_text.py` → `gen_completion_shards.py` →
  merge → bake）见归档；MZ 补翻用本文的 `prefill` + `slice --todo` +
  `append`。
