# 经验库 · 打包与清理

本文收录「垃圾文件与残留识别、`clean` 的删除风险、广告壳插件、压缩包
卫生、文件名与大小写」相关的实战经验。其他主题见
[翻译](experience-translation.md) ·
[Tyrano](experience-tyrano.md) ·
[杂项](experience-misc.md) ·
[经验库索引](experience.md)。

## 1. repack 垃圾与广告文件

- 常见的 repacker 遗留：ASCII 广告文件（根目录或 `data/` 下的假
  `setting.json` 等非合法 JSON）、`.url` 快捷方式、`Tool/` 目录、根级
  翻译字典（`<title>.json`）、`赠品/` 目录。前几类删除；根级翻译字典
  留作预填来源（从源目录读，不拷进交付物）。
- 广告与推广文案只按本地广告关键词表匹配（文件名与关键词均不入库），
  具体文件名以该表为准。
- 目录命名用官方名，剥掉 repacker 附加的译者名；`System.json` 的
  `gameTitle` 为空时设为官方标题。

## 2. `clean` 的删除风险

两例已验证的失败，都是 `clean` 删掉了运行时加载、但静态语料里没有引用
的资源：

- **字体**：MV 的字体引用写在 `fonts/gamefont.css`，语料扫描漏掉该文件
  就会删掉全部字体；带 CJK 名的字体（如 `ラノベPOP.ttf`）还需要能匹配
  CJK 的文件名正则。删错的结果是回退字体渲染，手机端缺字形或出方块。
- **图块**：部分插件在运行时**拼出**图块名并动态加载
  （`World_A1/A2/B/C` 等），`Tilesets.json` 里没有它们，语料检查抓不到。
  这类游戏跳过 `clean` 的图块部分，收益本就只有几十 MB。

安全做法：`clean --dry-run` 后，若字体或图块被标出就不应用，并从源树
恢复（构建应是源的超集）。删除 `img/` 下的 `.txt/.clip/.tmx/.bak` 垃圾
永远安全。

## 3. 广告壳插件（长得像正常插件）

repack 会把纯广告代码塞进 `js/plugins/`，并在 `js/plugins.js` 里注册为
`"status": true`。

- **结构**：几行无害的 `var`，随后内联 **axios**（游戏从不需要）、内联
  **pako**、obfuscator.io 式混淆代码（`_0x` 十六进制变量、
  `["constructor"](...)['apply'](...)`、`\u007a\u0069\u007a\u0023` 式转义）。
- **检测**：`rg -l "axios|pako|_0x[0-9a-f]{4,}" js/plugins/*.js`，再确认
  `data/` 里没有任何插件命令调用它。静态 `rg "debugger"` 找不到它的
  反调试逻辑，运行时才发。
- **删除**：删插件文件，并用 JSON 重写 `$plugins` 数组以移除条目。

## 4. 压缩包卫生

- 压缩包密码可能与包内推广文件绑定：遇到不在本地密码表里的密码，先看
  根目录的推广文件，再决定（密码值只存本地表）。
- 包内嵌套压缩包（名字像汉化包的 `cn.rar` 等）先 `7z l` 看内容再决定，
  不要凭文件名判断。
- MTool 注入残留（`与工具一同启动.bat`、`从游戏中移除工具文件.bat`、
  `winmm.dll`、`injectPath`、根级运行时字典）在打包前删除，删前用
  `rg -l` 确认无引用。

## 5. 文件名与大小写

- **大小写**：引擎按固定大小写加载（`ImageManager.loadSystem("Window")`
  加载 `Window.png`），repacker 在 Windows 上打包时常写成小写。Windows
  下正常，Linux/Android 的文件系统大小写敏感则加载失败。修法是补上
  引擎引用的大小写并**删除错误大小写的文件**：只留一种，否则归档解到
  大小写不敏感的卷上会互相覆盖。归档内用 `7zz l | grep -i` 复查同名
  文件。
- **乱码名**：Shift-JIS 文件名被按 CP936 解出的乱码会让引擎找不到资源，
  用 `tools/fix_mojibake_names.py` 修复（默认 dry-run）。
- **过长文件名**：个别音效把整句对话写进文件名，超过组件名 255 字节的
  上限会让手机端解压失败；这类文件通常是无引用的孤儿，改名或删除。
