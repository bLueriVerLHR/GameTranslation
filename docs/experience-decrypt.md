# 经验库 · 解密 / 解包 / Repacker 识别

> **先读这篇**：本文收录「解密、解包、Repacker 资源识别」相关的实战经验
> （由原单文件经验库拆分而来，原 §0/§1/§2-decrypt/§4）。
> 其他主题经验见：
> [音频 / 清理 / 打包](experience-audio-clean.md) ·
> [翻译](experience-translation.md) ·
> [Tyrano](experience-tyrano.md) ·
> [其他 / 杂项](experience-misc.md) ·
> [经验库索引](experience.md)。

处理各种引擎 / repack 风格的 RPG Maker MV/MZ 游戏时硬学到的教训。在下一款
游戏上跑流水线**之前**先读这篇。游戏身份刻意省略 — 教训按引擎与特征
写法记录。

## 1. Repacker 惯例

- repack 的 `.rar` 压缩包常**带密码**；解压用 `7z x -p<pass>`
  （见 `docs/workflow.md` §8 坑）。常见密码放在本地
  `docs/table/passwords.md`（gitignored）— 绝不入库。
- 布局：根目录 NW.js 运行时 + `www/`（MV）或根网页部署（MZ）。
  `detect.py` 自动找网页根。
- 某开发者的 MV 游戏**加密**资源（`.rpgmvp`/`.rpgmvo`，密钥在
  `data/System.json`）。它们跨游戏共享**公共资源库**（
  `img/faces/main_cha.png`、`img/tilesets/001_Particle.png`、`fsm_*`
  First Seed Material 套件）— 但每个游戏只带自己用到的子集，**所有被引用
  资源都在原文件里**。不要从另一款游戏拷贝资源来"修"缺失文件；下面的
  缺失文件报告是误报（见 §4）。

## 2. 流水线顺序 & 唯一要记住的

```
build → decrypt → audio → clean → verify → serve → compress
```

- 除非完全理解 `clean` 会删什么，**不要重跑已跑过的 `clean`**（见
  [音频/清理/打包](experience-audio-clean.md) §3）。先 `--dry-run`；它标出
  这些游戏的字体/图块时，别应用，并把已删的恢复。
- **serve 最后、compress 最后。** 先在浏览器里 HTTP 测，再打包。
- 源保持不动；工具库只写构建副本。

## 3. 解密工具补丁（已应用）

- **`decrypt.py`**：支持 MV `.rpgmvp→.png`、`.rpgmvo→.ogg`、
  `.rpgmvm→.webm`（16 字节 RPGMV 头 + 前 16 字节 XOR），不只 MZ `_`
  文件。解密只 XOR **前 16 字节** — 绝不整文件。

## 4. "缺失资源"报告是 FALSE — HTTP 测试 bug，不是 repack 丢弃

早期笔记声称游戏请求从未随包的资源（运行时生成，`rg` 找不到），修复是
从同开发者另一款游戏拷贝：

- `img/faces/main_cha.png` → "从同开发者其他游戏拷贝"
- `img/tilesets/001_Particle.png` → "另一款游戏里有"
- `fsm_*` 图块 → "整套拷贝（199 文件 / ~105 MB）"

**全错。** "Failed to load" 错误是 HTTP serve bug 造成的（过期缓存的
404 / 复用端口上的残留服务器在服务旧目录 — 见
[其他/杂项](experience-misc.md) 服务卫生一节），不是真缺失。对照最终构建
验证：

- 两款游戏里都有 `img/faces/main_cha.png`。
- `Tilesets.json` + 地图 `tilesetId` 引用的每个图块在磁盘上都在（一款
  游戏 175 个引用全在；另一款 261 个全在）。
- `001_Particle.png` 只有其中一款引用，存在于它；另一款从不引用、不随
  包、也不需要。
- `fsm_*` 数量每款不同（86 vs 199），因为每款只带自己引用的文件。

**规则：相信原文件。** `verify`/浏览器报缺失资源时，先杀残留服务器、
禁用缓存重载、查磁盘路径。只有文件真从构建消失**且**被
`Tilesets.json`/地图/`js` 引用，才算 repack 丢弃。从来不需要跨游戏拷贝。
