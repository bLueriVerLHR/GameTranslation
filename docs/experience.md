# 经验库索引

本库按主题记录踩过的坑与判据，每条按「引擎 + 特征」形式记录，不含游戏名、
作者名与渠道信息（见 `AGENTS.md` 的公开仓库卫生规则）。

## 主题文件

| 主题 | 内容 | 链接 |
| --- | --- | --- |
| 翻译 | 提取范围、写回与烘焙、验收普查、插件参数文本、分块批次 | [experience-translation.md](experience-translation.md) |
| TyranoScript | `.ks` 写回、省略号改写、`lang.js`、`[iscript]` 可见字符串 | [experience-tyrano.md](experience-tyrano.md) |
| 打包与清理 | repack 垃圾与广告文件、`clean` 的删除风险、广告壳插件、压缩包卫生、文件名与大小写 | [experience-packaging.md](experience-packaging.md) |
| 其他 | 工具与依赖卫生、门禁与测试卫生、`.ks` 编码缺陷、运行时排查 | [experience-misc.md](experience-misc.md) |

## 速查

- **解包**：压缩包密码按来源特征匹配本地密码表；`Failed to load` 多为静态引用
  的误报，先核对原文件是否存在、大小写是否一致。
- **翻译**：MZ 与 MV 走 `docs/translation.md` 的 v2 流程；残留用假名正则检测，
  汉字不算残留（中日共用 CJK 块）。五道门禁只保证结构：identity 纯汉字、跳句
  专名漂移、JSON 结构叶子、机翻丢内容四类需要另行普查。
- **打包**：`clean` 对运行时动态加载的字体与图块有风险，先 `--dry-run`；归档
  前删除广告文件与注入残留。
- **归位**：无法归入上表主题的经验写入 [杂项](experience-misc.md)。
