# Wolf RPG（ウディタ）翻译指南

Wolf RPG Editor 游戏（.wolf 加密容器 + `Game.exe`）的 JP→ZH 翻译流程。
本会话（2026-08）首次跑通：解包 → 提取 → 分块 → subagent 翻译 → 合并 →
回写补丁 → 重打包验证。**以下所有结论都来自真实操作，含失败教训。**

## 1. 引擎识别

- 目录结构：`Game.exe`（或 `GAMEK.exe`/`GamePro.exe`）+ `Data/*.wolf`。
- `.wolf` 是 **DXArchive v8 容器**（文件头 `44 58 08 00` = "DX"+ver8），
  非简单 XOR。UberWolf 的 C++ 源码是格式权威参考。
- 引擎是**非 Unicode 程序**：路径/文件名/字符串解码取决于**数据内的
  编码设置**（Ver2 日文=SJIS；Ver3=UTF-8），与 Windows 系统区域**无关**
  （英文系统能跑日文原版）。

## 2. 解包（工具：`wolfrpg/dxarchive.py`）

从 UberWolf（MIT）移植的纯 Python DXArchive v8 解包器：

```
python3 wolfrpg/dxarchive.py <game>/Data/MapData.wolf <out_dir> \
    --key 'WLFRPrO!p(;s5((8P@((UFWlu$#5(='
```

- key 是**引擎内置 v2.225 加密密钥**（UberWolf 源码里的
  `DEFAULT_CRYPT_MODES`），游戏作者一般不换。
- 解包产物：`MapData/`（.mps 地图）、`BasicData/`（.dat/.project 数据库）。
- **坑**：文件头 `Flags=0`（cryptVersion=0）→ 走旧版 KeyConv 路径，
  别被 `wolfVersionFixTo`（MTool 残留）误导。
- LZ 解码的 destsize 字段**不可信**（参考实现不校验，只解出实际长度）。
- Huffman 解码第一个字节：参考实现先预载 `PressData[0]`，Python 版必须
  同样初始化 `bit_data = src[payload_start]`，否则首字节错一位。
- 解包器输出可自检：PNG 魔数、Ogg 头、`.mps` 的 `WOLFM` 头。

## 3. 文本提取（rewolf-trans，npx 临时跑，无需安装）

```
npx -y rewolf-trans -r <game> -p <patch_dir> \
    --renc SHIFT_JIS --wenc <编码> generate
```

- 需要**已解包的目录结构**：`Data/MapData/*.mps`、`Data/BasicData/*.dat`。
- 产出 `rewt-patch/` 下的补丁 txt（`> BEGIN STRING` / 原文 / `> CONTEXT`
  位置 / `> END STRING` 块）。
- `_Danger.txt` / `_Extra.txt` 是高风险字符串（文件名、命令名、AI 处理名）
  ——**翻译会破坏游戏，跳过**。

## 4. 工作包与分块（工具：`tools/build_wolf_translation.py`）

```
python3 tools/build_wolf_translation.py <patch_dir> <work_dir> --no-danger --no-extra
python3 tools/gen_translation_shards.py <work_dir> --max-chars 11000 --context-budget-kb 200
```

- `build_wolf_translation.py`：补丁 txt → 标准工作包（template/kinds/
  structure/context），复用 MZ 的 chunk 管线。
- **structure.json 的 map id 是字符串**（文件名），`gen_translation_shards.py`
  已兼容（`isinstance(m["id"], int)` 分支）。
- wolfrpg 的 kind：`story`/`commonevent`（进故事树）、`db`/`system`/`cdb`
  （全局）；commonevent 也按场景排（`[CE]` 前缀 id），不进全局。
- context 窗口：按 CONTEXT 位置（map/page/event）分组取相邻键；全局键
  （db/system/cdb）不生成窗口（否则 context.md 爆炸）。
- **全局块按键数切**（`--global-per-chunk 600` 默认）：短键多，按字符数
  切会让 context.md 超 90KB（3991 键的块 context 高达 274KB）。

## 5. Subagent 翻译

- 沿用 chunk 工具链（`gen_translation_shards` → 分批追加契约 →
  `merge_plain_chunks.py` QC）；MZ 已改走 `docs/translation.md` 的 v2。
- **wolfrpg 特有转义**：控制码在数据里是**双反斜杠**（`\\s[9]`），
  `merge_plain_chunks.py` 的 double-backslash 检测已改为
  `v.count("\\") > k.count("\\")`（相对比较，非绝对判断）。
- **尾部 `\n` 常被 agent 丢**：wolfrpg 键几乎都以 `\n` 结尾，统一修复脚本
  （按 ja 的 `\n` 数补/删尾部）。
- **假名豁免类**（`merge_plain_chunks.kana_left_in` 已内置）：
  - `<>` 标签（状态名引用：`<デレ↑>`）
  - BGM/资源路径、Woditor 内部命令
  - 五十音教学 UI（`あ汉字`、单假名行）
  - 名字谜题注音（`はなさない（永不放手）` 括号内假名）
  - 角色口癖（`俺ちゃん`、`ちゃん/さん/くん` 后缀）
  - 音乐 credits（`feat.`）、作者名
- **分块尺寸**：600 键/块 agent 成功率低（~30%），**拆 ~300 键/块**
  成功率 >80%。`gen_translation_shards` 的 11000 字符预算对 wolfrpg
  键长偏紧，用 `--max-chars 11000 --context-budget-kb 200`。

## 6. 回写补丁与 apply（工具：`tools/apply_translation_to_patch.py`）

```
python3 tools/apply_translation_to_patch.py <patch_dir> <translated.json>
npx -y rewolf-trans -r <game> -p <patch_dir> --renc SHIFT_JIS --wenc <编码> \
    apply -o <out>
```

- 补丁文件结构：`> BEGIN STRING` → 原文行 → `> CONTEXT` 行 →
  **译文行** → `> END STRING`。译文插在 CONTEXT 之后、END 之前。
  **两个静默失败陷阱（2026-10 实测，都会“什么都没报却什么都没写”）**：
  1. **行尾不能改**。生成的补丁是 **LF**；在 Windows 上用文本模式重写会把整个
     文件变成 CRLF，工具就把 `\r` 当成 CONTEXT 名的一部分、**每个节点都解析
     失败并静默丢弃条目**（实测：整文件条目全被跳过，零 ERROR）。写回时
     用二进制写 / `newline=""`，原样保留行尾。
  2. **只能插在 CONTEXT 之后，不能改写原文行**。直接替换原文行会让同一套
     节点查找失败（日志里是 `Node not found: <CONTEXT 名>`），该条译文被
     丢掉。
  因此：**写入后必须重新提取并与译前补丁做多重集比对**，否则这两种失败
  根本看不出来（§11）。
- translated.json 的键带尾部 `\n`，拼接原文行后**补 `\n`** 再查表。
- patch 文件可能是 `\r\n` 行尾，用 `splitlines()` 统一处理。
- `apply` 的 `--wenc` 决定写出编码：**GBK**（Ver2 中文）或 **UTF-8**
  （Ver3）。中文字符无法用 SHIFT_JIS 编码（会报错或乱码）。

### 6.1 静默失败陷阱的受控实验 + UTF-8 写入验证（2026-10 实测）

在一个隔离工作副本上做（原版目录只读，只改一笔译文）：

1. **把补丁文件从 LF 改写成 CRLF**（Windows 文本模式默认）→ 工具把 `\r`
   当成 CONTEXT 名的一部分，**每个节点都解析失败、整批条目被静默丢弃**
   （无 ERROR，只有 `Node not found: …/cmd/221/0\r` 这类行）。
2. **直接改写原文行**（而不是在 CONTEXT 行后插入译文行）→ 同样变成
   `Node not found`，该条译文被丢掉。

改正后（二进制写保住 LF + 译文插在 CONTEXT 之后）：apply 无告警，
译文以 **UTF-8 字节**落在数据文件里（实测字节 `e3 80 8c …`，字符串长度
字段同步更新），文件仍可被再解析。

结论：**回写链可以携带非 SJIS 文本，但两个错误都只表现为“静默不写”，
所以回写后必须重新提取并与译前补丁做多重集比对**（§11）；这条自检
不能省。

## 7. 编码与运行（本会话最大教训）

Wolf RPG 是 ANSI 引擎，编码由**游戏基本设置**决定，有两条路线：

### 路线 A：Ver2 引擎 + GBK（老旧，不推荐）
- 数据 GBK 中文，引擎需在**中文区域**（Locale Emulator zh-CN）运行。
- **但地图文件名是 SJIS 存储**，中文区域下引擎按 GBK 读文件名 →
  `偽幣個儺.mps` 之类乱码找不到文件。需要把所有日文文件名也转成 GBK
  编码的中文名并同步更新引用——工程量大且易错。
- 结论：**放弃**。

### 路线 B：Ver3 引擎 + UTF-8（社区标准，LinguaGacha 同款）
- **用 Wolf RPG Editor Pro（EditorPro.exe）+ GamePro.exe（Ver3.595）
  覆盖到游戏目录**，打开 EditorPro 触发 **Ver2→Ver3 数据转换**
  （所有数据转 UTF-8，自动备份到 `Backup_Before_Ver3/`）。
- 转换后引擎原生 UTF-8：中文正常、文件名引用正常（不再乱码）。
- 关键顺序（**必须先原版后翻译**）：
  1. 先部署**纯原版数据**（SJIS）
  2. 用 EditorPro 转换 → 数据变 UTF-8，`Game.dat` 变 Ver3 格式
  3. 再用 rewolf-trans 以 **UTF-8** 重写翻译数据（`--wenc UTF-8`）
  4. 部署翻译文件 + 保留转换后的 `Game.dat`
- **坑（本会话踩的）**：编辑器转换会把**混合编码/GBK 数据**当文本转换，
  二进制 .dat 被**截断损坏**（696060 → 237108 字节）——所以翻译数据
  必须在转换后、以 UTF-8 生成，不能先部署 GBK 再转换。
- EditorPro 打开旧项目会弹转换对话框：确认「コンバートを実行」→
  「動作バージョン 最新 で OK」→ 转换日志在
  `Backup_Before_Ver3/ConvertLog.txt`（`変換OK` 行）。
- **EditorPro 需要日文区域**（Locale Emulator ja-JP），且命令行
  `-f <path>` 在英文/日文区域下都可能报"路径不存在"（路径参数编码
  问题）——**直接双击运行 EditorPro.exe 最可靠**（它会弹转换提示）。

### 字体
- 游戏自带日文字体（如 AkazukinPop.ttf、Onryou.ttf），不含简体中文。
- 需在游戏基本设置里改字体为**中文字体**（宋体/微软雅黑），或用
  LinguaGacha 的 LGBaseFont。转换后 `Game.dat` 的字体字段为 UTF-8，
  可直接改。

## 8. 交付与清理

- 解包目录（`Data/MapData/`、`Data/BasicData/`）**替代对应 .wolf**
  （删除 `MapData.wolf`/`BasicData.wolf` 防冲突），图片/音频 .wolf 保留。
- 清理 MTool 残留：`MTool_*.exe`、`与工具一同启动.bat`、`*.json` 字典、
  `Save_MTool/`、`forceWolf3Start` 等。
- **目录/文件路径必须纯 ASCII**：引擎（尤其 Ver2）无法处理含日文/中文
  的路径（`Read Error: Cannot locate ...`）。
- 交付目录命名用 ASCII（如 `wolfrpg_cn`）。

## 9. 工具清单（本项目新增）

| 工具 | 作用 |
|---|---|
| `wolfrpg/dxarchive.py` | DXArchive v8 解包器（含 LZ/Huffman/KeyConv） |
| `tools/build_wolf_translation.py` | rewolf-trans 补丁 → 标准工作包 |
| `tools/apply_translation_to_patch.py` | translated.json → 补丁 txt 注入 |
| `tools/gen_translation_shards.py` | （改）兼容字符串 map id + wolfrpg 全局 kind |
| `tools/merge_plain_chunks.py` | （改）wolfrpg 双反斜杠/假名豁免规则 |

## 10. 危险文件不要整桶跳过（2026-10 定案，推翻旧做法）

`rewolf-trans` 按**文件**把字符串分为安全 / `_Danger` / `_Extra`；旧流程
（本文档第 3、4 节写的“跳过”）就是整桶不翻。**实测某 Ver2/SJIS 作品后
判定这是错的**：

- `_Danger` + `_Extra` 共 29,156 条唯一串，其中**路径/资源名类只占 13.4%**，
  其余是散文、引号对白与无假名杂项；
- 非路径类里有**约 58.5% 能被运行时注入工具的字典抓到**（= 玩家真能看到的
  文本）；整桶跳过会漏掉大块剧情与旁白。

正确姿势：**按键分类，不按文件跳过**——路径 / 资源文件名 / Woditor 内部
命令名一律原样保留，其余正常翻译，控制码逐字一致。（分类只需正则：
`\.png|\.ogg|\.mp3|\.mps|\.dat|…|^[A-Za-z0-9_]+/[^ ]*$` 等。）

## 11. 回写链保真度自检（2026-10 定案）

`apply` 不是字节级打补丁，而是**按解析模型重新序列化**数据文件，所以任何
写入后都必须自检。可复现的自检方法：

1. 用**相同**读写编码原样 `generate` → `apply`；
2. 产物与原始解包树逐文件 `sha256` 比对；
3. 对产物**再 `generate` 一次**，把补丁内容当**多重集**比较（串 + `> CONTEXT`
   位置都算）。

实测（某 Ver2/SJIS 作品，613 个数据文件）：

- **560 个逐字节相同**；
- **1 个被整文件重写**（`CommonEvent.dat`，体积 −24,770 B）；
- **52 个不输出**（`Game.dat`、图标 png、archive 内带子目录的条目）⇒ 交付
  是“覆盖式”而不是“完整目录”，不能让回写产物单独当完整数据树；
- 但第 3 步结果是**补丁 572,207 行完全一致、可译串 63,168 条一致** ⇒
  重写是**等价**的，本行为不是文本丢失。

其余两条实测事实：

- 工具会以 `info` 级记 `Unknown command: <id>`（实测撞到 id 104），未知命令
  按原字节保留；它**恰好落在重写后第一个字节差异处**，要单独核对该命令。
- archive 内**带子目录**的文件名条目（形如 `子目录\Map012.mps`）回写不输出，
  交付时需要保留原 `.wolf` 或自行补写。

## 12. 参考

- UberWolf（解包格式）：https://github.com/Sinflower/UberWolf
- rewolf-trans（提取/回写）：https://github.com/KCFindstr/rewolf-trans
- LinguaGacha BestPracticeForWOLF（社区汉化流程）：
  https://github.com/neavo/LinguaGacha/wiki/BestPracticeForWOLF
- Wolf RPG Editor 官方（编辑器下载）：
  https://www.silversecond.com/WolfRPGEditor/
