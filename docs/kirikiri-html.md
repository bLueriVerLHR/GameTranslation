# KiriKiri → HTML5 移植可行性调研

调研目标：把 KiriKiri（吉里吉里，KAG3）游戏带到 **HTML5 环境**
（浏览器 / JoiPlay）的可行路线。围绕本项目已验证的 TyranoScript
工具链（`tyrano/` + 翻译流水线）评估三条路线。结论与取舍如下。

## 结论先行

| 路线 | 原理 | Android/JoiPlay | 工作量 | 成熟度 |
| --- | --- | --- | --- | --- |
| A. JoiPlay 官方 KiriKiri 插件 | 原生引擎移植，直接跑 xp3 | ✅ 插件内运行 | 零移植 | pre-alpha，约一半游戏可跑 |
| B. TyranoScript 重打包（转换器） | KAG3 脚本 + 素材 → TyranoScript 项目 | ✅ 纯 HTML5 | 大（转换器 + 逐游戏调试） | 无现成工具，需自建 |
| C. WASM 引擎（Emscripten） | 引擎编译成 wasm 在浏览器跑 xp3 | ❌ Android WebView 不可用 | 中 | 桌面可用，移动端受限 |

对"在 JoiPlay 上游玩"的目标：**路线 A 优先**（零转换，直接吃现有
`kirikiri/` 翻译流程 → patch.xp3）；**路线 B** 作为 A 兼容性不足时的
兜底（产出物正是本项目已验证的 TyranoScript 构建，翻译/打包全复用）；
**路线 C 不适用于移动端**（详见下），仅适合桌面浏览器分发。

## 路线 A — JoiPlay 官方 KiriKiri 插件（推荐优先）

- JoiPlay 已有 **Kirikiri2 Plugin**（1.20.400 起随模拟器更新推出；
  独立 APK 亦可装），基于 YuriSizuku 的 Kirikiroid2 分支。选择游戏的
  `.xp3` 即可启动，无需任何转换。
- 成熟度：**pre-alpha**，官方说法"至少一半的游戏应该能跑"，兼容性
  随版本提高。插件的限制 = Kirikiroid2 的限制（部分插件 DLL 不兼容、
  个别引擎特性缺失）。
- 与本项目的关系：**完全复用现有 `kirikiri/` 翻译工具链**——解包
  （xp3tool）→ 提取（build_ks_translation）→ 统一 chunk 翻译 →
  写回（apply_ks_translation）→ patch.xp3，原档不动。翻译完成度与
  平台无关。
- 行动：选一款想玩的游戏 → 跑现有 KiriKiri 翻译流程 → 交付
  `patch.xp3` 覆盖即可。

## 路线 B — KAG3 脚本 → TyranoScript 转换器（兜底，需自建）

### 为什么可行

1. **TyranoScript 官方声明与 KAG3 兼容**：官方文档明确"KAG3/吉里吉里
   compatibility"是设计目标（引擎本身参考 KiriKiri 2 SDK 实现）。
2. **语法亲缘度高**：标签系统（`[tag attr=val]`）、`*label` 跳转、
   `;` 注释、`#名前` 说话人缩写、`[jump]/[call]/[return]`、
   `[if]/[else]/[elsif]/[endif]/[ignore]`、`[macro]/[endmacro]`、
   `[chara_new]/[chara_show]/[chara_ptext]` 等**同名同义**，转换以
   属性级映射为主，不需要语法重写。
3. **本项目工具链已验证 TyranoScript 构建闭环**：asar 解包 → 构建 →
   mp3→ogg → 翻译 → 写回 → 验证 → JoiPlay 交付（本仓库 `tyrano/` +
   `docs/tyrano.md`）。转换器只要产出标准 TyranoScript 项目，后续全
   部复用。

### 转换器要点（自建 `kirikiri/convert_kag.py` 或等价工具）

- **脚本**：KAG3 `.ks` → TyranoScript `.ks`。
  - 标签属性映射表（大多数同名，差异主要在默认值/单位）；
  - 表达式：`[eval exp="..."]`、`[if exp="..."]` 里的 TJS2 表达式 →
    JS（两者 `f./sf./tf.` 变量命名空间一致，语法接近）；
  - `iscript/endscript` 内嵌 TJS2 → JS（最重的一块，需按游戏评估）；
  - 素材引用路径映射（`data/image`、`data/fgimage` 等目录约定差异）。
- **素材**：图片（jpg/png/tlg→png）、音频（ogg 保留、mp3 按需重编码、
  走 `tyrano/audio.py` 的 ogg 策略）、字体（复用 `kirikiri/merge_font.py`
  思路）、视频（kmv/mpg→mp4）。
- **存档**：krkr savedata → `configSave=webstorage`（浏览器 localStorage）。
- **坑**：KAG3 的 `cond` 属性（几乎所有标签可用）、`[quake]` 时间单位、
  插件 DLL（krkr 插件无 HTML 等价物，需替换或裁剪）——具体差异按游戏
  实测记录，不入库。

### 现状评估

没有成熟的现成 KAG3→TyranoScript 自动转换器（社区的 KS Converter 类
工具只做纯文本→TyranoBuilder 脚本，不解析 KAG3 标签）。"TyranoScript
与 KAG3 兼容"指的是脚本风格亲缘，不是开箱即用的自动移植。**转换器
需要自建**，且每款游戏都要调试插件/特效差异——所以定位为路线 A
兼容性不足时的兜底，不建议一开始就投入。

## 路线 C — WASM 引擎（桌面可行，移动端不可用）

- **Kirikiroid2 Web**（krkr2-web，Emscripten 编译 Kirikiroid2）：
  完整 TJS2 引擎，原版脚本零修改，拖 xp3 即玩；需 COOP/COEP 头 +
  SharedArrayBuffer（跨源隔离）。
- **krkrsdl2 Web 版**：吉里吉里 SDL2 的官方 Emscripten 构建，同样
  直接跑 xp3。
- **移动端硬伤**：Android **WebView 不支持跨源隔离 / SharedArrayBuffer**
  → JoiPlay 的 HTML 插件跑不了 WASM 引擎；且社区实测安卓端有黑屏、
  大游戏（GB 级）需整体载入内存等限制。iOS 也有 JSPI/触控待解问题。
- 结论：适合 PC 浏览器网页分发，**不解决 JoiPlay 移动端目标**，不在
  本项目路线内。

## 建议行动（按优先级）

1. **先用路线 A**：从 `/mnt/e/KiriKiriGames/`（本机 7 款）选一款，
   跑现有 `kirikiri/` 翻译流程交付汉化 patch.xp3，在 JoiPlay +
   Kirikiri2 插件里实测兼容性——验证插件成熟度后，多数游戏可直接落地。
2. **路线 B 缓建**：只有当某款游戏在插件上跑不动（黑屏/插件缺失）且
   值得移植时才建转换器；转换器范围先收窄到该游戏的标签子集（按
   `docs/table/<Game>/notes.md` 记录差异）。
3. 翻译能力（统一 chunk/subagent 流程）三路线通用，不重复投入。
