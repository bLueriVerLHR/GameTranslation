# Unity IL2CPP + Addressables 翻译（运行时 hooking）

已在 **Unity 6**（本次验证组合：Unity 6000.3.x / metadata v39 /
MelonLoader 0.7.3）验证跑通。

> 下文的版本号是**当时跑通的组合**，不是永久保证。换新版本前先确认本机
> 实际版本（`gt doctor`），失败按 [experience-misc.md](../experience-misc.md)
> 的失败模式入口留档。

IL2CPP 游戏（`GameAssembly.dll`，无 Mono `Managed/`）+ Addressables
（`StreamingAssets/aa/**/*.bundle`）的文本全部在 bundle 的 MonoBehaviour
序列化字段里。

**不要再尝试 bundle 改写**——正确路线是 **MelonLoader 运行时 hook**。
bundle 改写的完整失败史见文末，勿重走。

## 1. 文本提取（确定翻译范围）

文本在多处，缺一不可：

- **MonoBehaviour 序列化字段**：`commandSequence` 里的 `message`
  （成人场景/回想台词）、TMP 组件的 `m_text`（烘焙 UI 文本）、
  `displayName`（cut 名）、`message`（证据文本）——UnityPy `obj.read()`
  遍历 `__dict__`。
- **GameScript `bytecode` 字段（最容易漏！）**：图式脚本插件（如
  NemukeGraph/LogicToolkit）的图被编译成自定义字节码存在 `bytecode`
  字段（`list[int]`），**主剧情台词全在这里**。字符串格式：
  `opcode 6 (0x06) + int32(utf8-len) + utf8`。只做 `read()` 遍历的提取会
  **完全漏掉主剧情**。
- **Unity Localization 字符串表**：
  `localization-string-tables-japanese(ja)_assets_all.bundle` 里的小表
  （通用文本，名字/地名等）。

分片：分批追加契约下 **~250 键 / ~9k 字符** 的大块完全可行，QC 保证不
丢行。

## 2. 运行时注入（MelonLoader + Harmony）

1. 把 `MelonLoader.x64.zip` 解压到游戏根目录，首次启动自动生成
   `MelonLoader\Il2CppAssemblies`（内含 Cpp2IL 处理 metadata v39 的能力）。
2. 插件为 net6.0 class library，引用 `MelonLoader\net6\*` +
   `Il2CppAssemblies\*.dll`（互操作类在 `Il2Cpp` 前缀命名空间，如
   `Il2CppNovelCommand`、`Il2CppNovel.Nameplate`、`Il2CppTMPro.TMP_Text`）。
3. **Hook 点**（Harmony prefix，`ref` 参数直接改字符串）：
   - 对话类静态方法：`NovelCommand.Say/SayNoBacklog/SayNoClear` 的 2/3 参
     重载、`AddChoice` —— 源端翻译，backlog/打字机全部覆盖。
   - `Nameplate.SetName` —— 说话者名字。
   - `TMP_Text.text` setter —— UI 兜底。**必须 patch 基类 `TMP_Text`**
     （MelonLoader 警告：TextMeshProUGUI 未实现该方法，patch 基类才生效）。
4. 翻译字典 `translated.json`（`{ja→zh}`，放游戏根目录），exact-match
   查找；**两侧统一 `Replace("\r","")`**（Unity 序列化字符串带 CRLF，
   不剥会失配）。

## 3. 卡死教训（两次真实事故，表现都是「第一个对话后点击无法推进」）

- **TMP setter 热路径上严禁文件 I/O**：打字机动画每帧 set_text 一次，且
  字符串是递增子串——逐帧写 miss 日志 = 文件 I/O 风暴，主线程堵死。
  TMP hook 必须纯内存、含假名才查表、只翻译完整串。
- **严禁动 `TMP_FontAsset.m_SourceFontFile` / `atlasPopulationMode`**：
  源字体交换会破坏图集/死锁动态字形提取（第一个对话「お……」变方框 +
  全游戏冻结）。动态字形只能走 **fallbackFontAssetTable**。

## 4. 字体（中文方块 → 正常显示）

- 游戏字体是 TMP_FontAsset 且**本来就是 Dynamic**
  （`m_AtlasPopulationMode=1`），但源字体（NotoSansJP/BIZUDGothic 等）
  没有 GB 简体汉字 → 方块。
- **Unity 6 里 `TMP_FontAsset.CreateFontAsset(Font)` 运行时返回 null——必须
  用字符串路径重载**（FontEngine 直接从文件加载）：

  ```csharp
  var cjk = TMP_FontAsset.CreateFontAsset(
      "<path-to-cjk-font>.ttc", 0, 36, 6,
      UnityEngine.TextCore.LowLevel.GlyphRenderMode.SDFAA, 1024, 1024,
      Il2CppTMPro.AtlasPopulationMode.Dynamic, true);
  ```

  （`GlyphRenderMode` 在 `UnityEngine.TextCore.LowLevel`，FontEngine 模块；
  `AtlasPopulationMode` 用 `Il2CppTMPro` 自带的枚举。）
- 把结果 `Add` 进每个游戏字体的 `fallbackFontAssetTable`（**纯加法**：
  日文字形保留原样，缺失汉字回退到宋体）。参考实现：
  eviltwo/SystemFontLocalization（Unity 6 验证）。

## 5. bundle 改写的失败史（2026-08，勿再盲目重复）

**引擎拒绝一切修改过的 bundle**（静默黑屏、无日志、约 2s CPU、窗口
存在）。按顺序全部失败：

1. UnityPy typetree 补丁 + 保存；
2. UnityPy raw `set_raw_data` 字节替换（短键损坏对象——用 4 字节对齐
   填充修复）；
3. 等长替换；
4. 手工 store-block UnityFS 重打包；
5. 保真 LZ4 重打包（头部/标志/块布局一致、LZ4HC 位、UnityPy 可读验证）；
6. catalog crc 与 content-hash 清零。

原始 bundle 在同一机器上运行正常。结论：该构建的 Addressables bundle
加载器存在未检测的完整性/兼容性检查；**以现有工具对 Unity 6
Addressables 游戏做 bundle 改写不可行**（UnityPy 自己的 GitHub 也承认
LZ4 保存的 bundle 可能无法加载）。

另外当时「full residual scan 0」是**假阳性**：`read()` 遍历漏掉了
GameScript bytecode 里的主剧情文本（见 §1）。**bundle 改写历史作废，
勿再尝试。**
