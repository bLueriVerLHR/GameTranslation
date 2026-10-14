# 翻译 v2：单一写者 + 文件信箱

状态：已采纳。取代 v1「切块 → 每块一个执行者 → ja/zh 双文件 → 合并」。

## 背景

v1 按块并行分发翻译：每个 chunk 一个执行者，各自写 `ja.txt`/`zh.txt`，最后
按行合并回填。实测失败模式：

- **静默错位**：块与块之间行数不一致时，按行对齐会把译文整体挪位，且不一定
  报错（漏行、多行、`\C[14]` 这类控制码被丢）。
- **状态不在磁盘**：进度只存在于各执行者的上下文里，中断即不可恢复。
- **无法门禁**：没有统一入口校验「控制码逐字一致」「换行数相等」，问题要到
  试玩才暴露。

## 决策

一个翻译执行者（单写者），磁盘状态为权威，文件信箱做接口：

```
python -m translation.cli prepare <game_dir> <work_dir>   # keys.jsonl + 控制码表 + 骨架 + MISSION.md
python -m translation.cli slice <work_dir> --start N --count M --lean --out <file>
python -m translation.cli append <work_dir> --batch <file> --fix-leading --note "..."
python -m translation.cli pending|decide|status|rewrite|to-json|gates <work_dir>
python -m translation.cli bake  <game_dir> <work_dir>
```

- 编排者只做机械活（提取、跑门禁、转 JSON、烘焙）；语言判断全在执行者，其
  任务书是 `prepare` 生成的 `MISSION.md`。
- **唯一落盘入口是 `append`**：逐条校验 id、非空、控制码逐字一致、假名残留，
  任何一条不过则整批不写盘（原子性），因此不存在半批次状态。
- **五道硬门禁**（`gates`：覆盖、控制码、假名残留、换行数一致、待决清零）
  全绿才能 `bake`；烘焙前自动备份到 `<work>/backup/`。
- 派发执行者时一律 fresh 上下文，不 fork；提示词由编排者写全（工作区、起点
  seq、每批流程、硬规则、回报格式），不把编排者的会话投影给执行者。

## 被否方案的教训

- 「按块并行 + 按行合并」在行数不一致时会静默错位，因此行数一致被升级为
  硬门禁，而不是尽力而为。
- 「用 hit/miss 当覆盖率口径」把整块拼接键与非显示串算进分母，导致完整翻译
  的 MZ 游戏只报 7.3%。键表（v2 键集合）是唯一口径。
- 烘焙的五道门禁与覆盖率只证明译库完整，不能证明烘焙本身没跳过整类键；因此
  烘焙后必须把译库每个键的 JSON 路径在构建里解析回来逐条比对。

## 后果

- `translation/` 模块与 `docs/translation.md`、`docs/translation-data.md`、
  `docs/translation-qc.md` 是 v2 的唯一入口；v1 流程归档在
  `docs/archive/translation-v1.md`，不得再用于 MZ 翻译。
- 非 MZ 引擎（Tyrano、Wolf RPG、KiriKiri）的提取与写回链沿用 v1 工具，见
  各自的引擎文档。
- 体量先量后授权：`prepare` 报键数与字符数，得到明确授权后才开工。
