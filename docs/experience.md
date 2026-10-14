# 经验库索引

本库按主题记录踩坑与教训。每条按「引擎 + 特征」形式记录，不含游戏名、
作者名与渠道信息（见 `AGENTS.md` 的公开仓库卫生规则）。

## 主题文件

| 主题 | 内容 | 链接 |
| --- | --- | --- |
| 翻译 | 提取/分块/写回、烘焙与 QC、残留补翻、门禁盲区 | [experience-translation.md](experience-translation.md) |
| TyranoScript | `.ks` 结构、`lang.js`、MTool 残留、写回坑 | [experience-tyrano.md](experience-tyrano.md) |
| 打包与清理 | repack 垃圾与广告文件、`clean` 的删除风险、广告壳插件、压缩包卫生、文件名与大小写 | [experience-packaging.md](experience-packaging.md) |
| 其他 | 工具卫生、运行兼容、杂项排查 | [experience-misc.md](experience-misc.md) |

## 速查

- **解包**：压缩包密码按来源特征匹配本地密码表；"Failed to load" 多为
  静态引用的误报，先核对原文件是否存在、大小写是否一致。
- **翻译**：统一走 `docs/translation.md` 的 v2 流程；残留用假名正则检测，
  汉字不算残留（中日共用 CJK 块）。v2 五道门禁只保证结构：identity 纯
  汉字、跳句专名漂移、JSON 结构叶子、机翻丢内容四类需要另行普查。
- **打包**：`clean` 对运行时动态加载的字体与图块有风险，先 `--dry-run`；
  归档前删除广告文件与注入残留。
- **新增经验**：按主题写入对应文件；无法归类的写入
  [杂项](experience-misc.md)。
