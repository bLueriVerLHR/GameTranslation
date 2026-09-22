# RPG Maker Unite（Unity Mono）翻译

已在 **7 款同作者 RM Unite 短篇成人游戏**上验证跑通（系列复用词条/剧情
字典）。引擎为 Unity **2021.3.15f1 Mono**（非 IL2CPP），Addressables
bundles。工具在 `unity/rmunite/`。

## 1. 文本提取（UnityPy typetree）

- 文本全在 `StreamingAssets/aa/StandaloneWindows64/**/*.bundle` 的
  **MonoBehaviour 序列化字段**；typetree **未剥离**，`read_typetree()`
  直接可用。
- 三类文本位置，缺一不可：
  - **对话**：`EventSO.dataModel.eventCommands[].parameters[0]`（code
    401/101，说话人前缀如 `【角色名】` 内嵌在文本里）+ 选择肢 code 402 的
    `parameters[2]`。
  - **UI/菜单**：`UnityEngine.UI.Text.m_Text`（prefab 组件）。
  - **词条**：`WordSO`/`SystemSO`/`ItemSO` 等共享数据库文本（攻撃/アイテム
    等 UI 词条；**游戏本体与 UI 共用，必须译**）。
  - `TileDataModel` 磁贴名 = 编辑器内部名，**不译**。
- 每个事件的完整命令序列在 `others_assets_event/*.asset`（EventSO 一个
  事件一个 asset）；主 scene assets（`globalgamemanagers`/`sharedassets`）
  无文本。
- MonoScript 类名映射：先遍历 bundle 内 MonoScript 的 `read_typetree()`
  （`m_ClassName` + `m_Namespace`），再按 MB 的 `m_Script.m_PathID` 解析。

## 2. 运行时注入（BepInEx 5.4.23.5 + Harmony）

- **Hook 点（对话源头，严禁只 hook 显示端）**：
  - `RPGMaker.Codebase.Runtime.Common.Component.HudHandler.SetShowMessage(string)`
    —— **唯一整句文本入口**，IL 极简（`_messageWindow.ShowMessage(msg)`）。
    MessageTextProcessor 只处理窗口设置（名字/头像/颜色），不含正文。
  - `UnityEngine.UI.Text.set_text` + `TMPro.TMP_Text.set_text` —— UI 兜底。
    **必须 patch 基类 `TMP_Text`**（TextMeshProUGUI 未实现 set_text，
    patch 子类直接抛 "Undefined target method"，且 PatchAll 中断后续所有
    patch）。
- **打字机陷阱**：消息窗口逐**字符**调 set_text（捕获日志可见逐字文本），
  整句匹配必然失败 → 翻译必须做在 `SetShowMessage` 源头。
- **BepInEx preloader 崩溃修复**：游戏自带 MonoMod 19.x（RM Unite 插件
  机制）与 BepInEx 冲突，报
  `MethodAccessException: MonoMod.Utils.PlatformHelper.set_Current`。
  解法：`doorstop_config.ini` 设 `dll_search_path_override = BepInEx\core`。
  干净原版（无 0Harmony/MonoMod 的 repack）不需要此设置。
- **行尾符**：运行时文本带 `\r`，提取时归一化为 `\n` → 查表前两侧统一
  `Replace("\r\n","\n").Replace("\r","\n")`，命中后译文按原文行尾风格
  补回（原文 CR 结尾则译文补 CR），否则消息窗口换行判断异常。
- **验证**：插件加 stats Timer（每 15s 报 hits/misses）+ miss 日志
  （限 30 条，热路径严禁无限制文件 I/O）。`hits>0 misses=0` + 无 miss
  日志 = 翻译全命中。自动测试：启动后 `AppActivate` + SendKeys ENTER
  推进剧情触发对话。

## 3. 批量流水线（系列多款复用）

1. `extract_game.py <game_dir> <out>`（参数化提取，先全量再过滤两个类）。
2. **prefill**：第一款翻译作为系列词条库预填充，`【名字】` 前缀替换 +
   正文查 base。**坑**：正文不在 base 时 `base.get(rest, rest)` 原样保留
   → **半翻译**（前缀中文、正文日文）静默入库。
3. QC 必须用**假名正则** `[\u3040-\u30ff]` 检查值残留（中文/日文共享
   CJK 汉字区 `\u4e00-\u9fff`，按汉字查会全部误报）。
4. 系列共享剧情（如收债人线）直接从已翻译作品借字典，逐键 exact 匹配。
5. 翻译 `translated.json`（`{ja→zh}`）放游戏根目录，插件 exact-match
   查表。
6. **交付**：汉化版完整目录放交付目录（含 BepInEx / 插件 /
   `translated.json`），**原版不动**。
