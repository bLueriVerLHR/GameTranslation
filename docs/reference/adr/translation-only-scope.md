# 项目范围：只做解包、翻译、插件翻译与烘焙

状态：已采纳

## 背景

项目早期面向「让游戏在手机上可玩」，因此包含多条运行时转换链：RPG Maker
的 JoiPlay 构建（剥 NW.js 运行时、解密、音频重编码、贴图缩放）、Tyrano 的
Electron 剥离与音频转换、KiriKiri 的 KAG3→TyranoScript 转换。这些链的共同
特征是**改变游戏的运行方式**，而不是改变它的文本。

维护代价集中在三处：

- 每条转换链都需要真机验收，验证层次（构建产物、浏览器冒烟、实机）无法由
  单元测试替代，链一停就不再可信。
- 转换链带来的代码量远大于翻译链，门禁表、测试分层与变异表的大部分条目
  服务于它。
- 转换结论随引擎版本漂移，而翻译结论只依赖数据格式，稳定得多。

## 决策

项目范围限定为**解包、翻译、插件翻译、烘焙**四类工作：把游戏的数据拿出
来、翻成中文、写回去、随包归档译库。**不做任何运行时转换或移植**。

随之移除的能力：

| 移除项 | 原用途 |
|---|---|
| RPG Maker 构建链（`build`/`decrypt`/`audio`/`serve`/`verify`/`compat`） | 生成 JoiPlay 可玩目录 |
| Tyrano Electron 剥离、音频转换、自动播放补丁、静态验证 | 同上 |
| KAG3→TyranoScript 转换器与其 JavaScript 垫片 | KiriKiri 手机化 |
| 媒体层（PyAV）与移动端工具（贴图缩放、图集重排、视频转码） | 体积与贴图上限 |
| `ffmpeg` 与 `node` 的注册表条目 | 音频编码、JS 运行时 |

保留的能力：各引擎的解包与文本提取、翻译 v2 流程与写回、插件参数文本、
烘焙与 QC 门禁、打包与交付（`clean`/`compress`/`deliver`）。

## 被否方案

- **保留但标注为不维护**：转换链的验收依赖实机，缺少实机验收的链只能靠
  文档声称可用，与「只写已验证事实」的规则冲突。
- **把转换链拆到独立仓库**：本仓库不再需要它，拆分的收益要等到真的再做
  移植时才会出现。
- **仅删除文档、保留代码**：代码仍会被门禁与测试维护，成本一分不减。

## 后果

- `docs/reference/support-matrix.md` 不再出现转换类能力；`rpgmaker/inventory.py`
  的能力词表只含 `detect`/`unpack`/`adpack`/`extract_text`/`apply_translation`/
  `package`/`inject`。未知引擎仍然失效关闭。
- 外部程序注册表只剩 `git`（开发）、`powershell` 与 Windows 侧 `7z`（跨系统
  桥接，见 [cross-system-file-ownership.md](cross-system-file-ownership.md)）。
- Unity 与 Wolf RPG 与本决策一致：它们本来就只做翻译与注入。
- 引擎索引指向翻译文档（`docs/tyrano.md`、`docs/kirikiri.md`、
  `docs/wolfrpg.md`、`docs/engines/`）。
