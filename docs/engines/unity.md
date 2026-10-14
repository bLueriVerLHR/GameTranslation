# Unity 游戏（总览）

Unity 游戏只做**翻译与注入**：不在它们上面跑 RPG Maker 流水线（`clean`、
`compress`、`deliver` 等命令都不适用），也不解密、不重编码任何东西。识别特征
是 `<Game>.exe` 加 `<Game>_Data/` 与 `globalgamemanagers`，没有 `index.html`
与 `js/`。

## 1. 范围：仅翻译

- **Unity Mono** —— 用 XUnity.AutoTranslator 的 `Translation\{Lang}\Text\`
  表或 JSON 语言包。
- **Unity IL2CPP** —— 用 MelonLoader 运行时 hook，见
  [unity-il2cpp.md](unity-il2cpp.md)。
- **RPG Maker Unite（Unity Mono）** —— 用 BepInEx 5 加 Harmony 自定义插件，
  见 [unity-rmunite.md](unity-rmunite.md)；工具在 `unity/rmunite/`。

## 2. 放置与清理

- Unity 游戏放到专门的 Unity 游戏目录（`<Game>\`）：先解压到系统临时目录、删除
  广告文件、再移动；剥掉重复嵌套的目录层级。
- **广告清理**：删除根目录的推广文件（推广与注册链接类文案，具体清单见本地
  广告关键词表，逻辑位置见
  [local-layout.md](../reference/local-layout.md)）。保留版本与更新说明
  readme。
- **病毒检查**：核对 BepInEx DLL 清单（只允许 BepInEx／XUnity 标准组件加已知
  mod DLL）、检查 exe 签名（无签名属正常）、可选运行
  `Start-MpScan -ScanType CustomScan`。

## 3. 翻译状态约定

决定「是否需要翻译」前先检查状态，两类文本位置不同：

- **游戏正文** = AutoTranslator 缓存，位于 `Language={lang}`
  （`FromLanguage=ja`）。
- **mod 新增文本** = `BepInEx\plugins\*Json\` 下的 JSON 语言包（按语言分
  目录）。

先看 `AutoTranslatorConfig.ini` 的当前语言再决定。
