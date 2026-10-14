# 打包与交付工作流

本文件描述「游戏数据 → 译文 → 成品压缩包 → 成品目录」这条链上，除翻译
本身以外的步骤。翻译流程见 `docs/translation.md`，各引擎的提取与写回见
对应引擎文档（`docs/tyrano.md`、`docs/kirikiri.md`、`docs/wolfrpg.md`、
`docs/engines/`）。

## 1. 路径与环境

- 工作副本一律放系统临时目录；成品放交付目录，命名 `<Game>` 与
  `<Game>.7z`；**绝不修改原版游戏目录**。目录解析见
  `docs/reference/local-layout.md`，实现见 `rpgmaker/deliverables.py` 与
  `rpgmaker/workspace.py`。
- 跨系统处理遵守 AGENTS.md 的 CRITICAL 规则：文件在哪一侧，就用哪一侧的
  原生工具处理；`rpgmaker/platform.py` 的同侧门岗在读写前拒绝跨侧路径，
  Windows 侧操作经 PowerShell 桥接（`rpgmaker/tool_registry.py`）。
- 环境排查先跑 `python pipeline.py doctor`（`--json` 为机器可读），它按
  `ToolStatus` 分级把缺失的程序分成 `[MISS]` 与 `[WARN]`，并给出解析到的
  路径与来源。

## 2. 顺序

| 步骤 | RPG Maker | TyranoScript |
|---|---|---|
| 还原被 launcher 打包的数据库 | `gt unpack-data <game>` | —（`app.asar` 由提取步骤解包） |
| 提取与翻译 | `python -m translation.cli` + `bake` | `tools/build_tyrano_translation.py` + `bake` |
| 清理 | `gt clean <game>` | `gt-tyrano clean <out>` |
| 引擎 UI 本地化 | — | `gt-tyrano localize-ui <out>` |
| 打包 | `gt compress <game>` | `gt-tyrano compress <out>` |
| 交付 | `gt deliver <game>` | `gt-tyrano deliver <out>` |

Unity 与 Wolf RPG 只做翻译与注入，不走本表的打包步骤，见
`docs/reference/support-matrix.md`。

## 3. 命令要点

**`unpack-data`** 处理 launcher（Enigma Virtual Box）打包过的发布版：这类
目录能直接玩，但磁盘上没有 `data/`，数据在 `<Game>.exe` 的 PE 段
（`.enigma1` / `.enigma2`）里。命令把 `data/` 还原出来，非 JSON 载荷会被
跳过并 WARN。

**`clean`** 只做安全删除：广告/推广文件、桌面运行时残留、`img/` 垃圾
（`img/` 下引擎不加载的名字）、未被引用的字体与图块。判定依据是游戏自身
语料的引用扫描，不做猜测；`--dry-run` 只报告不删除。

**`localize-ui`** 处理引擎自带文案（`tyrano/lang.js`）：标题返回确认、
「没有存档」、脚本报错这些对话框不在 `data/scenario` 里，只翻剧情时仍是
日文。按键匹配，`--dump` 输出可译串，`--map` 提交映射；未知键与未过机械
门禁的条目会被拒绝并以非零退出。

**`compress`** 用 py7zr（zstd）在进程内打包，不打外部 7-Zip，写完自校验
（`--level` 调压缩级别）。

**`deliver`** 是收尾一步，按顺序做四件事：本地压缩 → 复制压缩包到压缩包
目录（覆盖旧包）→ 删除成品目录里的旧文件夹 → 解压到成品目录。含完整性
测试；Windows 侧的目标经 PowerShell 桥接，不需要外部 7-Zip 参与同侧打包。

## 4. 打包前清理与归档

- 广告/推广文件、MTool 注入残留（`与工具一同启动.bat`、`winmm.dll`、
  `injectPath` 等）在打包前删除；先 `rg -l` 确认无引用，具体文件名以本地
  广告关键词表为准（见 `docs/reference/local-layout.md`）。
- 已翻译的游戏，其键值对译库（烘焙用的 `translated.json` 或等价
  `{ja→zh}` 字典）随包归档：`translation.cli bake` 会自动在输出目录写出
  `translation_kv.json`，用 `--no-kv` 关闭。未翻译的游戏不打这个文件。
- 统一字体是烘焙的强制步骤，策略与改动点见
  `docs/reference/local-layout.md`。
