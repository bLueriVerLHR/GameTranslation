# Unity 游戏（总览）

Unity 游戏（`<Game>.exe` + `<Game>_Data/` + `globalgamemanagers`，无
`index.html`/`js/`）不属于流水线范围——`build`/`decrypt`/`audio`/`clean`/
`verify` 全部不适用，JoiPlay 也无法运行它们。

## 范围：仅翻译

- **Unity Mono** — 用 XUnity.AutoTranslator 的
  `Translation\{Lang}\Text\` 表 / JSON 语言包。
- **Unity IL2CPP** — 用 MelonLoader 运行时 hook，见
  [unity-il2cpp.md](unity-il2cpp.md)（已在 Unity 6 IL2CPP + Addressables
  游戏上跑通）。
- **RPG Maker Unite（Unity Mono）** — 用 BepInEx 5 + Harmony 自定义插件，
  见 [unity-rmunite.md](unity-rmunite.md)（多款同作者短篇系列跑通，
  工具在 `unity/rmunite/`）。

**绝不在 Unity 游戏上跑流水线，绝不解密/重编码任何东西。**

## 放置与清理

- Unity 游戏放到专门的 Unity 游戏目录（`<Game>\`）：先解压到系统临时
  目录、删除广告文件、再移动；剥掉重复嵌套的目录层级。
- **广告清理**：删除根目录推广文件（推广/注册链接类文案——具体清单见
  本地广告关键词表，逻辑位置见
  [local-layout.md](../reference/local-layout.md)）。保留版本/更新说明
  readme。
- **病毒检查**：核对 BepInEx DLL 清单（只允许 BepInEx/XUnity 标准组件 +
  已知 mod DLL）、检查 exe 签名（无签名属正常）、可选运行
  `Start-MpScan -ScanType CustomScan`。

## 翻译状态约定

决定「是否需要翻译」前先检查状态，两类文本位置不同：

- **游戏正文** = AutoTranslator 缓存于 `Language={lang}`（`FromLanguage=ja`）。
- **mod 新增文本** = `BepInEx\plugins\*Json\` 下的 JSON 语言包（按语言分
  目录）。

先看 `AutoTranslatorConfig.ini` 的当前语言再决定。
