# Wolf RPG（ウディタ）翻译指南

Wolf RPG Editor 游戏（`.wolf` 容器 + `Game.exe`）的 JP→ZH 翻译链：解包 → 提取 →
分块翻译 → 合并 → 回写 rewolf-trans 补丁 → 保真度自检。运行时字典路线（把 MTool
字典的键映射到静态字段后重建）见 §7。

## 1. 引擎识别

- 目录结构：`Game.exe`（或 `GAMEK.exe`、`GamePro.exe`）加 `Data/*.wolf`。
- `.wolf` 是 DXArchive v8 容器（文件头 `44 58 08 00`，即 "DX" 加版本 8），不是
  简单 XOR。UberWolf 的 C++ 源码是格式权威参考。
- 引擎是非 Unicode 程序：路径、文件名与字符串的解码取决于**数据内的编码设置**
  （Ver2 日文用 SJIS，Ver3 用 UTF-8），与 Windows 系统区域无关，所以英文系统也
  能跑日文原版。

## 2. 解包

`wolfrpg/dxarchive.py` 是从 UberWolf（MIT）移植的纯 Python DXArchive v8 解包器：

```bash
python3 wolfrpg/dxarchive.py <game>/Data/MapData.wolf <out_dir> --key <引擎默认密钥字符串>
```

- 密钥是引擎内置的 v2.225 加密密钥，来自 UberWolf 源码的 `DEFAULT_CRYPT_MODES`，
  游戏作者一般不换。密钥是游戏数据，所以由命令行传入，工具里不硬编码。
- 用错密钥的症状是 Huffman 解码越界（`Huffman block: truncated payload`），不是
  密钥校验失败：模块默认的 `DXLIBARC` 是 DXLib 的默认串，Wolf 游戏必须用引擎
  密钥才能解出头部块。排错时先怀疑密钥，再怀疑格式。
- 大档案走 mmap（`_mapped_archive`）：实测一份 2.9 GB 的 `Data.wolf`，在 16 GB
  内存、仅约 2.5 GB 空闲的机器上按整份 `f.read()` 的写法必然失败；改为只读内存
  映射后峰值内存等于最大单个条目。压缩头部块位于文件尾部
  （`raw[name_table_start:]`），所以解包前先读这一段（本例 339,580 字节）。
- 头部块可自检：解出的长度应等于 64 字节头里的 `head_size` 字段（实测
  1,013,748 字节）；不一致说明密钥判断或版本判断有误。
- 解包产物：`MapData/`（`.mps` 地图）与 `BasicData/`（`.dat`、`.project`
  数据库）。
- 文件头 `Flags=0`（cryptVersion=0）时走旧版 KeyConv 路径，别被
  `wolfVersionFixTo`（MTool 残留）误导。
- LZ 解码的 destsize 字段不可信：参考实现不校验它，只按实际长度解。
- Huffman 解码的第一个字节：参考实现先预载 `PressData[0]`，Python 版必须同样
  初始化 `bit_data = src[payload_start]`，否则首字节错一位。
- 受保护数据库文件里的 antidebug 垃圾字节默认剥掉（与 UberWolf 相同的 62 字节
  哨兵），`--no-protection-cleanup` 保留它们。
- 只支持标准 v8 布局（cryptVersion 0 与旧 DXA keying）；Wolf Pro、ChaCha20、AES
  变体会被检测并明确拒绝。
- 输出可自检：PNG 魔数、Ogg 头、`.mps` 的 `WOLFM` 头。

## 3. 文本提取

rewolf-trans 用 npx 临时运行，无需安装：

```bash
npx -y rewolf-trans -r <game> -p <patch_dir> \
    --renc SHIFT_JIS --wenc <编码> generate
```

- 输入需要已解包的目录结构：`Data/MapData/*.mps` 与 `Data/BasicData/*.dat`。
- 产出在 `rewt-patch/` 下，每个原文件一个补丁 txt，块结构是
  `> BEGIN STRING` → 原文行 → `> CONTEXT` 位置行 → `> END STRING`。
- `_Danger.txt` 与 `_Extra.txt` 收的是高风险字符串（文件名、命令名、AI 处理
  名）。按文件整桶跳过是错的做法，处理规则见 §12。

## 4. 工作包与分块

```bash
python3 tools/build_wolf_translation.py <patch_dir> <work_dir>
python3 tools/gen_translation_shards.py <work_dir> --max-chars 11000 --context-budget-kb 200
```

`build_wolf_translation.py` 把补丁 txt 转成标准工作包
（`template.json`、`kinds.json`、`structure.json`、`context.json`），复用 MZ 的
chunk 链。输入布局：

```
patch_dir/rewt-patch/
  MapData/<map>.txt              故事序对白
  BasicData/CommonEvent/*.txt    公共事件（按场景排，`[CE]` 前缀的 id，不进全局）
  BasicData/DataBase/*.txt       数据库文本（全局）
  BasicData/SysDatabase/*.txt    系统数据库文本（全局）
  BasicData/CDataBase/*.txt      角色数据库文本（全局）
  ..._Danger.txt / ..._Extra.txt 高风险串
```

补丁块格式与键的定义：

```
> REWOLF TRANS PATCH FILE VERSION 1.0
> BEGIN STRING
<键行，含 \\s[9] 控制码与消息内的真实换行>
> CONTEXT [NEW] MPS:<map>/<page>/<event>/[<cmd>]Message/<n>
> END STRING
```

- 键是字符串内容原样，真实换行保留；补丁里 `\\s[9]` 是字面反斜杠加 `s`。chunk
  链的 `plain_io` 转义把真实换行变成字面 `\n`、把字面反斜杠变成 `\\`。
- 故事序：MapData 各图按 rewolf-trans 遍历地图档案的顺序出现（即编辑器的地图
  列表顺序），公共事件排在地图之后，数据库文件是全局文本，没有场景序。
- 每条 CONTEXT 记为该键的位置；一个键出现在多个 CONTEXT 时（公共事件与地图
  共享的对白）记全部位置。
- `structure.json` 的 map id 是字符串（文件名），`gen_translation_shards.py` 已
  兼容这一支。
- kind：`story` 与 `commonevent` 进故事树，`db`/`system`/`cdb` 是全局。
- context 窗口按 CONTEXT 位置（map/page/event）分组取相邻键；全局键
  （db/system/cdb）不生成窗口，否则 `context.md` 会膨胀。
- 全局块按键数切（`--global-per-chunk`，默认 600）：短键多，按字符数切会让
  `context.md` 超过 90 KB（3991 键的块 context 曾达 274 KB）。
- `--no-danger`、`--no-extra` 只跳过对应文件，处理危险文件的正解见 §12。

## 5. chunk 链翻译与 Wolf 特有规则

翻译走统一 chunk 链（`gen_translation_shards` → 分批追加契约 →
`merge_plain_chunks` 的 QC）。

- Wolf 的控制码在数据里是双反斜杠（`\\s[9]`），`merge_plain_chunks.py` 的
  double-backslash 检测是相对比较（`v.count("\\") > k.count("\\")`），不是绝对
  判断。
- 尾部 `\n` 常被丢：wolfrpg 的键几乎都以 `\n` 结尾，修复脚本按原文的 `\n` 数
  补或删尾部。
- 假名豁免类（`merge_plain_chunks.kana_left_in` 已内置）：`<>` 标签（状态名引用
  `<デレ↑>`）、BGM 与资源路径、Woditor 内部命令、五十音教学 UI（`あ汉字`、单
  假名行）、名字谜题注音（`はなさない（永不放手）` 括号内的假名）、角色口癖
  （`俺ちゃん`、`ちゃん`/`さん`/`くん` 后缀）、音乐 credits（`feat.`）、作者名。
- 分块尺寸：600 键一块的成功率低（约 30%），拆到约 300 键一块可高于 80%。
  `gen_translation_shards` 的 11000 字符预算对 wolfrpg 的键长偏紧，用
  `--max-chars 11000 --context-budget-kb 200`。

## 6. 回写补丁与 apply

```bash
python3 tools/apply_translation_to_patch.py <patch_dir> <translated.json>
npx -y rewolf-trans -r <game> -p <patch_dir> --renc SHIFT_JIS --wenc <编码> \
    apply -o <out>
```

补丁块里译文的位置是固定的：`> BEGIN STRING` → 原文行 → `> CONTEXT` 行 →
译文行 → `> END STRING`。两个静默失败陷阱都表现为「什么都没报，什么都没写」：

1. **行尾不能改。** 生成的补丁是 LF；在 Windows 上用文本模式重写会得到 CRLF，
   工具就把 `\r` 当成 CONTEXT 名的一部分，每个节点都解析失败并静默丢弃条目
   （实测整文件条目全被跳过，零 ERROR，只有 `Node not found: …/cmd/221/0\r`
   这类行）。写回用二进制写或 `newline=""`，原样保留行尾。
2. **只能插在 CONTEXT 之后，不能改写原文行。** 直接替换原文行会让同一套节点
   查找失败（日志里是 `Node not found: <CONTEXT 名>`），该条译文被丢掉。

受控实验（在隔离工作副本上做，原版目录只读，只改一笔译文）复现了这两点：LF 改
CRLF 与改写原文行都导致 `Node not found`；改正后 apply 无告警，译文以 UTF-8
字节落在数据文件里（实测字节 `e3 80 8c …`，字符串长度字段同步更新），文件仍可
再解析。结论：回写链可以携带非 SJIS 文本，但两个错误都只表现为静默不写，所以
回写后必须重新提取并与译前补丁做多重集比对（§13）。

其余事实：

- `translated.json` 的键带尾部 `\n`，拼接原文行后补 `\n` 再查表。
- 补丁文件可能是 `\r\n` 行尾，用 `splitlines()` 统一处理。
- `apply` 的 `--wenc` 决定写出编码：GBK（Ver2 中文）或 UTF-8（Ver3）。中文
  字符无法用 SHIFT_JIS 编码，会报错或乱码。

## 7. 键空间映射与运行时字典

随包的运行时字典（MTool 格式）键是运行时片段，每条只有一个消息窗口、没有
语境，而且只覆盖了游戏的一部分。`tools/mtool_keymap.py` 用它做键列表，把每条键
映射到静态字段，再按字段重建字典：

```bash
python3 tools/mtool_keymap.py build <字典>.json <patch_dir>/rewt-patch <work>
python3 tools/mtool_keymap.py slice <work> --buckets DB,COMMONEVENT \
    --kinds whole-field,line-aligned --units 12 --out <batch>
python3 tools/mtool_keymap.py apply <work> <batch>
python3 tools/mtool_keymap.py gates <work> [--font <构建字体>.ttf]
python3 tools/mtool_keymap.py export <work> <原字典>.json <字典-out>.json
```

- `build` 把每条键映射到补丁树里承载它的字段（哪个文件、哪个偏移、哪个地图或
  事件），写出 keymap 与每个宿主字段一条记录；字段按来源分桶（`DB`、
  `COMMONEVENT`、`MPS`、`OTHER`）与种类（`whole-field`、`line-aligned`、
  `sub-line`）。
- `slice` 以宿主字段为单位发批（一批里的字段都带自己的片段），默认只发
  `DB,COMMONEVENT` 的整字段与整行键，一批最多 `--units` 个片段；没有宿主字段的
  运行时键按 25 条一组切。
- `apply` 合并译好的批次，全有或全无：一个片段不过（控制码、换行数、假名残留）
  就整批不写。
- `gates` 跑覆盖、控制码、换行数、假名残留、冲突五项，`--font` 额外要求构建字体
  能画出每个字符。
- `export` 写出可放回游戏旁的运行时字典：键集与键序与原字典一致；刻意不译的键
  （资源路径、引擎按名解析的参数）算决定、不算漏，只有完全没碰过的键才拒绝交付。
- 其余子命令：`release`（释放批次占用的键）、`answer`（译文文件 → 校验 → 入库）、
  `skip`（带理由标记整段不译）、`terms`（对照工作区词表查术语漂移）、
  `normalize`（按显式表替换构建字体画不出的符号）、`import-keys`（收编没有静态
  原文的字典键）、`adopt-fields`（把未译片段的宿主字段收编为翻译单元）、
  `revise`（改已入库的值，同样过门禁）、`resolve`（同一键的多个值收敛为一个）。
- 原字典的值只用来当键列表，不搬运任何机译文。

## 8. 编码与运行

Wolf RPG 是 ANSI 引擎，输出编码由游戏基本设置决定。两条路线的实测结果：

**Ver2 加 GBK 的代价。** 数据用 GBK 中文时，引擎需要在中文区域运行（Locale
Emulator zh-CN）。但地图文件名是 SJIS 存储的，中文区域下引擎按 GBK 读文件名，
得到 `偽幣個儺.mps` 一类乱码并找不到文件；要把所有日文文件名也转成 GBK 编码的
中文名并同步更新引用，工程量大且易错。这条路线未采用。

**Ver3 加 UTF-8 的步骤**（社区流程，LinguaGacha 同款）：

1. 部署纯原版数据（SJIS）。
2. 用 Wolf RPG Editor Pro 的 `EditorPro.exe` 加 `GamePro.exe`（Ver3.595）覆盖到
   游戏目录，打开 EditorPro 触发 Ver2→Ver3 数据转换：所有数据转 UTF-8，自动备份
   到 `Backup_Before_Ver3/`。
3. 用 rewolf-trans 以 UTF-8 重写翻译数据（`--wenc UTF-8`）。
4. 部署翻译文件，并保留转换后的 `Game.dat`。

- 转换后引擎原生 UTF-8：中文正常，文件名引用也正常。
- 顺序不能颠倒：编辑器转换会把混合编码或 GBK 数据当文本转换，二进制 `.dat` 被
  截断损坏（实测 696060 字节变成 237108 字节），所以翻译数据必须在转换之后以
  UTF-8 生成，不能先部署 GBK 再转换。
- EditorPro 打开旧项目会弹转换对话框：确认「コンバートを実行」，再按
  「動作バージョン 最新 で OK」。转换日志在
  `Backup_Before_Ver3/ConvertLog.txt`（有 `変換OK` 行）。
- EditorPro 需要在日文区域运行（Locale Emulator ja-JP），且命令行 `-f <path>`
  在英文或日文区域下都可能报路径不存在（路径参数的编码问题）；直接双击运行
  `EditorPro.exe` 最可靠，它会自己弹出转换提示。

## 9. 字体

游戏自带日文字体（如 AkazukinPop.ttf、Onryou.ttf）不含简体中文。要在游戏基本
设置里把字体改成中文字体（宋体、微软雅黑），或使用 LinguaGacha 的 LGBaseFont。
转换后 `Game.dat` 的字体字段是 UTF-8，可以直接改。

## 10. 交付与清理

- 解包目录（`Data/MapData/`、`Data/BasicData/`）替代对应的 `.wolf`：删除
  `MapData.wolf` 与 `BasicData.wolf` 防冲突，图片与音频的 `.wolf` 保留。
- 清理 MTool 残留：`MTool_*.exe`、`与工具一同启动.bat`、`*.json` 字典、
  `Save_MTool/`、`forceWolf3Start` 等。
- 目录与文件路径必须纯 ASCII：引擎（尤其 Ver2）无法处理含日文或中文的路径，会报
  `Read Error: Cannot locate ...`。
- 交付目录命名用 ASCII（如 `wolfrpg_cn`）。

## 11. 工具清单

| 工具 | 作用 |
|---|---|
| `wolfrpg/dxarchive.py` | DXArchive v8 解包器（含 LZ、Huffman、KeyConv） |
| `tools/build_wolf_translation.py` | rewolf-trans 补丁 → 标准工作包 |
| `tools/apply_translation_to_patch.py` | `translated.json` → 补丁 txt 注入 |
| `tools/mtool_keymap.py` | 运行时字典键 → 静态字段映射，并重建字典 |
| `tools/gen_translation_shards.py` | 分块（兼容字符串 map id 与 wolfrpg 全局 kind） |
| `tools/merge_plain_chunks.py` | 按块 QC（含 wolfrpg 双反斜杠与假名豁免规则） |

## 12. 危险文件按键分类，不整桶跳过

rewolf-trans 按文件把字符串分为安全、`_Danger`、`_Extra` 三类。整桶不翻是错的：

- `_Danger` 与 `_Extra` 合计 29,156 条唯一串，其中路径与资源名类只占 13.4%，
  其余是散文、引号对白与无假名杂项。
- 非路径类里约 58.5% 能被运行时注入工具的字典抓到，即玩家真能看到的文本；整桶
  跳过会漏掉大块剧情与旁白。

正确规则是按键分类：路径、资源文件名、Woditor 内部命令名一律原样保留，其余正常
翻译，控制码逐字一致。分类只需正则，例如
`\.png|\.ogg|\.mp3|\.mps|\.dat|…|^[A-Za-z0-9_]+/[^ ]*$` 一类。

## 13. 回写链保真度自检

`apply` 不是字节级打补丁，而是按解析模型重新序列化数据文件，所以每次写入后都要
自检：

1. 用相同的读写编码原样 `generate` 再 `apply`。
2. 产物与原始解包树逐文件 `sha256` 比对。
3. 对产物再 `generate` 一次，把补丁内容当多重集比较（串与 `> CONTEXT` 位置都
   算）。

实测（一款 Ver2/SJIS 作品，613 个数据文件）：

- 560 个逐字节相同。
- 1 个被整文件重写（`CommonEvent.dat`，体积 −24,770 字节）。
- 52 个不输出（`Game.dat`、图标 png、archive 内带子目录的条目），所以交付是
  覆盖式的，回写产物不能单独当完整数据树用。
- 第 3 步的结果是补丁 572,207 行完全一致、可译串 63,168 条一致，说明重写是等价
  的，不是文本丢失。

另外两条实测事实：

- 工具会以 `info` 级记 `Unknown command: <id>`（实测撞到 id 104），未知命令按
  原字节保留；它恰好落在重写后第一个字节差异处，要单独核对该命令。
- archive 内带子目录的文件名条目（形如 `子目录\Map012.mps`）回写时不输出，交付
  时需要保留原 `.wolf` 或自行补写。

## 14. 参考

- UberWolf（解包格式）：https://github.com/Sinflower/UberWolf
- rewolf-trans（提取与回写）：https://github.com/KCFindstr/rewolf-trans
- LinguaGacha BestPracticeForWOLF（社区汉化流程）：
  https://github.com/neavo/LinguaGacha/wiki/BestPracticeForWOLF
- Wolf RPG Editor 官方（编辑器下载）：https://www.silversecond.com/WolfRPGEditor/
