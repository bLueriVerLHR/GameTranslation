# 经验库索引（实战笔记与坑）

处理各种引擎 / repack 风格的 RPG Maker MV/MZ 游戏时硬学到的教训。在下一款
游戏上跑流水线**之前**先读这篇。游戏身份刻意省略 — 教训按引擎与特征
写法记录。

> 本文是**经验库索引**，按主题拆分到下列文件。每条经验都以
> 「引擎 + 特征描述」形式记录，不写具体游戏名。

## 主题文件

| 主题 | 一句话说明 | 链接 |
| --- | --- | --- |
| 解密 / 解包 / Repacker 识别 | repack 布局识别、解压密码、加密资源（RPGMV 头）、"缺失资源"误报 | [experience-decrypt.md](experience-decrypt.md) |
| 音频 / 清理 / 打包 | 音频重编码、`clean` 危险、repack 垃圾/广告壳清理、长文件名、文件大小写坑 | [experience-audio-clean.md](experience-audio-clean.md) |
| 翻译 | 静态 subagent 翻译工作流、烘焙/QC、残留补翻、分块估算 bug | [experience-translation.md](experience-translation.md) |
| Tyrano | TyranoScript `[bgmovie]` 自动播放、KAG3→Tyrano 移植 | [experience-tyrano.md](experience-tyrano.md) |
| 其他 / 杂项 | 服务/测试卫生、CG 解锁、浏览器/JoiPlay 运行兼容、工具补丁 | [experience-misc.md](experience-misc.md) |

## 主题速查

- **解密 / 解包**：解压密码（本地 `docs/table/passwords.md`）、MV 加密资源
  `.rpgmvp/.rpgmvo/.rpgmvm`（16 字节 RPGMV 头 + 前 16 字节 XOR）、
  "Failed to load" 多为 HTTP serve 误报 → **相信原文件**。
- **音频 / 清理 / 打包**：`clean` 对运行时动态加载的字体/图块很危险（先
  `--dry-run`）；repack 垃圾/广告壳插件（`axios|pako|_0x` 扫描）；Android
  长文件名解压失败；MZ 文件名大小写敏感坑。
- **翻译**：统一 chunk 流程（`build_translation.py` → shards → subagent →
  `bake_translation.py`）；残留用假名正则检测；`<TE:name>` 按名引用必须
  成对翻译；分块估算按 UTF-8 字节计。v2 五门禁只能护结构：**identity
  纯汉字、跳句专名漂移、JSON 结构叶子、机翻丢内容**四类必须另做普查
  （见 [翻译](experience-translation.md) §7）。
- **Tyrano**：`[bgmovie]` 自动播放策略卡死 → `fix-autoplay`；KAG3 `[s]`/
  可点击地图/`[ch]` 移植语义。
- **其他 / 杂项**：serve 卫生（固定端口、杀残留服务器）；`process`/
  `require('fs')` 插件破坏浏览器构建；Steam 版启动门卡在标题前；
  FOSSIL 入口跳过 setup 块。

## 如何新增经验

新增经验按主题写入对应文件；无法归类的内容放 [其他 / 杂项](experience-misc.md)。
提交前遵守 AGENTS.md 公开仓库卫生：只写「引擎 + 特征」，不带游戏名/作者/
渠道/密码。
