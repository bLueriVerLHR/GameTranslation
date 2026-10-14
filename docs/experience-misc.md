# 经验库 · 其他 / 杂项

本文收录工具与依赖卫生、门禁与测试卫生、`.ks` 编码缺陷、运行时排查相关的
经验。其他主题经验见 [打包与清理](experience-packaging.md) ·
[翻译](experience-translation.md) · [Tyrano](experience-tyrano.md) ·
[经验库索引](experience.md)。

## 1. 工具与依赖

### 1.1 现成包代替手写的查找与命令行拼接

**判据**：同一个能力只留一个封装层，且优先用维护中的包。唯一的例外是跨系统
规则要求的 Windows 侧 `7z.exe` 与 PowerShell 桥；对照表与完整例外清单见
`docs/reference/tooling.md`。

- **打包用 py7zr**（唯一入口 `rpgmaker/archive.py`）：`create`／`verify`／
  `names`／`extract` 四个函数，同侧工作全部在进程内完成；`extract()` 直接拒绝
  Windows 侧目标，跨系统的解压交给 `deliver` 的 `7z.exe` 桥。实测（265 MB、
  3009 个文件，zstd level 15）：`7z.exe a -t7z -m0=zstd -mmt=on` 用 5.3 s、
  251.7 MB；py7zr（`FILTER_ZSTD`）用 3.1 s、251.7 MB，且 `7z.exe t` 通过
  （`Method = ZSTD`）。坑：py7zr 把方法名报作 `ZStandard`（`7z.exe` 显示
  `ZSTD`），断言必须两种都接受；它没有 `-mmt` 的对应物（`mp=True` 只影响
  解包），单进程已快过 `-mmt=on`，`threads` 参数只做兼容；完整性校验用
  `testzip()`（逐成员 CRC），坏档案必须 ERROR 加非零退出码——曾只是 INFO 且
  返回值被丢弃，坏档案 exit 0。
- **`app.asar` 用 `asar` 包**（`tyrano/asar.py`）：`npx @electron/asar` 需要
  Node.js，冷 cache 时还可能下载包。PyPI 的 `asar`（纯 Python）实测与官方 node
  工具打的包（含 `--unpack` 条目）提取结果字节一致，文件表也一致（node CLI 在
  Windows 上输出反斜杠路径，包返回正斜杠，已归一）。回归固件
  `tests/fixtures/tiny_app.asar` 就用官方 node 工具打（933 B），保证测试读的是
  外部产生的真包。
- **JS 语法检查用 tree-sitter**（`rpgmaker/jssyntax.py`，由
  `tools/check_iscript_js.py` 调用）：进程内，不执行代码。等价性实测：58 个
  真实 JS（TyranoScript 运行库，含混淆压缩的）乘 4 种变体（原样、截断、删括号、
  插入 `setter(x){…}`）共 225 例，判定与 `node --check` 完全一致（含故意弄坏
  的）。判定口径：树中出现任何 ERROR 或缺 token 即不通过——tree-sitter 是容错
  解析器，不能只看顶层错误。报错文案由 `SyntaxError: …` 变为
  `line N:M: unexpected '…'` 或 `missing '…'`（附坏片段），对已知回归文件的
  定位仍然到位。
- **死依赖的判据**：没有任何生产调用者的 finder 或工具条目就是死代码，不要因为
  「以后可能用」留着。外部程序只在 `rpgmaker/tool_registry.py` 的 `TOOLS` 表
  注册，解析顺序是环境变量 → 本地配置覆盖（支持 `*` 通配）→ 探测常见安装位置
  → `PATH`；每条必须带 `ToolStatus` 分级并有至少一个真实调用者。需要知道某个
  程序实际解析到哪里时跑 `python pipeline.py doctor`（`--json` 机器可读，按
  分级把缺失分成 `[MISS]` 与 `[WARN]`），不靠猜也不靠搜盘。

### 1.2 CLI、进程、日志与测试的唯一入口

- `rpgmaker/cli.py` 用 Typer 定义两个应用（RPG Maker 与 Tyrano），
  `pipeline.py` 与 `tyrano/pipeline.py` 退化成包装，入口是 `gt` 与
  `gt-tyrano`。两个入口曾各自抄一遍同名命令与 `smoke_test`，现已共用。
- `rpgmaker/proctools.py` 是外部进程的唯一入口（默认 900 s 超时、UTF-8
  `replace` 解码、失败信息带程序名与退出码与输出尾部）；缺程序仍抛
  `FileNotFoundError`，保留 resolver 的安装提示。
- `rpgmaker/logsetup.py` 是唯一的日志配置（时间戳加等级加 logger 名）。
  **禁止 import 期配置**：那会改写整个进程的 root logger，并让后续配置静默
  失效。
- 测试：`pytest-xdist` 默认并行（1163 个用例 27.8 s → 11.2 s）；
  `-p no:xdist` 与 `addopts = "-n auto"` 冲突，串行用 `-n 0`。
- Typer 的退出约定：**成功也走 `SystemExit(0)`**，所以包装函数（`cli._run`）
  把 0 吞掉、非零上抛，测试才能断言「成功返回」与「失败抛 SystemExit」两种
  情况。
- `pip install -e ".[unity]"` 会顺带装 `attrs`（UnityPy 的依赖）；本仓库自己
  的代码不用 `attrs` 与 `pydantic`（面向不可信数据的降级设计）。

### 1.3 解释器基线与依赖处理

- 项目基线统一为 Python 3.14 后，依赖声明、CI、ruff 与 mypy 都要同步；原
  解释器被移除会让旧虚拟环境失效，应备份后重新创建，不直接改配置冒充迁移。
- 测试应验证项目契约，而不是要求新版第三方库重现旧缺陷：不再断言某个库必须
  抛旧异常；仍严格要求有效输入处理成功、损坏输入失败。
- Python 3.14 编译文档字符串时，孤立代理字符转义（如 `\ud800`）可能触发
  `UnicodeEncodeError`，连带导致 pytest 收集失败。说明文字需要展示转义写法时
  用 raw 文档字符串；保留原测试逻辑，重跑编译与属性测试后再跑全量门禁。

### 1.4 交付目录配置的两个阻塞缺陷

- `deliverables.temp` 改为嵌套的 `{persist, tmpfs, win32}` 后，
  `temp_dir()`／`win_temp_dir()` 把 dict 传给了 `re.sub` 而崩溃。修法：
  `_deliverable` 跳过非标量，新增 `_temp_dir_cfg()` 按平台取子键（WSL 取
  `persist`，Windows 取 `win32`），并兼容旧的平铺格式。
- `tools.win32.*` 配置含 `%ProgramFiles%` 等当前侧无法展开的 token 时，旧实现
  把它当成已解析路径（非空即用），默认路径与探测从不尝试，于是工具明明装了也
  报缺失。修法：展开不了的 token 原样保留并让该条目解析失败，回落到探测与
  `PATH`——`settings.expand_env` 保留未知 token，`_config_override` 只接受真实
  存在的文件。
- 两个缺陷都让 `deliver` 直接崩，集成测试在修复前是红的（Python 3.14 下同样
  复现）。

## 2. 门禁与测试卫生

### 2.1 门禁自身的失败模式

**共同判据**：一次性验证过的检查会腐化，必须变成门禁；而门禁必须能真的失败
——写完要故意造一个违规，确认它变红。

- **`git ls-files` 不含未跟踪文件**：多个门禁用 `git ls-files <pattern>` 枚举
  文件，新写的模块在提交之前对门禁不可见。犯过两次：
  `tests/test_tool_registry.py` 的死 resolver 门禁（当时 7 个新模块全未跟踪，
  漏掉了 `find_powershell` 的真实调用者）与 `tests/test_text_io_portability.py`
  的文本 I/O 门禁（新模块含依赖 locale 的 `open()` 时提交前扫不到）。修法：
  一律加 `--cached --others --exclude-standard`（gitignored 仍被排除，所以
  `.venv/`、`.tmp/`、私有数据目录不受影响），已同步到 inventory、package
  boundaries、config facade、text I/O 四处门禁。
- **pathspec 写错会让门禁几乎空转**，这比盲点更危险：`tests/test_inventory.py`
  用 `git ls-files ":(glob)*.py"` 枚举生产文件，而这个规格只匹配仓库根目录的
  文件——实测返回 1 个（`pipeline.py`），正确应为 238 个。后果是「每个生产文件
  都必须登记在 inventory」这道门禁在将近整仓范围内空转，包目录看起来是空的，
  还掩盖了 `rpgmaker/inventory.py` 自己从未被登记。实测对比如下。

  | pathspec | 命中数 |
  |---|---|
  | `*.py` | 238 |
  | `:(glob)*.py` | 1（只有 `pipeline.py`） |
  | `:(glob)**/*.py` | 238 |
  | `:(glob)**/**/*.py` | 238 |

  修法：补 `**/` 前缀，并加「扫描结果过少即断言失败」的下限（inventory 大于
  100、package boundaries 大于 50）。这种缺陷的特征不是崩溃，而是安静地通过。
- **从不读锁的检查**：`uv.lock` 被手工验证过 `uv lock --check`，但没有变成
  门禁；往 dev 依赖加 `hypothesis>=6` 后锁文件静默过期，而所有 CI 任务都用
  pip 从 `pyproject.toml` 安装、从不读锁，于是没有一道现有门禁能发现。修法：
  新增 `tests/test_lockfile.py`（`uv lock --check` 加断言 `uv.lock` 被 git
  跟踪）与 CI 的 `lock` 任务。只有 `uv lock --check` 也不等于 CI 使用了锁
  文件：测试任务仍用无约束 pip 安装时，同一个提交可随上游发版变红，所以回归
  任务要用 `uv sync --locked`，运行命令用 `uv run --no-sync`，避免再次解析或
  清除仅夜间安装的随机顺序插件。
- **静默的假通过**：模块拆分后，一个测试仍在 `monkeypatch.setattr` 已经被搬走的
  旧名字，而被测模块读的是 `rpgmaker.tool_registry`；该测试一直是绿的，只因为
  本机真的没有那个外部程序（被 patch 的 finder 本来就返回 None），于是根本没
  走到被测分支。修法：patch 真正归属的模块。**模块拆分后要 grep 被测工具自己的
  命名空间**：`monkeypatch.setattr(<tool>.<module>, ...)` 这种形式用
  `grep config.<name>` 看不到。

### 2.2 路径安全门禁的两种漏检

- 只比较输入与输出同侧，不等于处理器也在同侧：所有路径都属于 Windows 时，
  WSL 原生 Python 仍不得读写。档案入口需分别验证源、目标和处理器。
- 相对输出补后缀、解析链接与路径绝对化会改变实际访问对象。应先确定真正的输出
  路径，再执行安全检查；不能绝对化之后丢掉原有「相对文件名补后缀」的语义。
  此类重构必须保留原文件名契约测试，不能为了类型改造修改期望值。
- 测试构建与变异副本必须显式排除私有数据目录。临时副本不是保密边界，即使内容
  最终不进入 wheel，也不应读取或复制本地私有资料。

## 3. 运行时与排查

### 3.1 长驻服务与端口的卫生

- 一次只服务一款游戏，并用**新端口**：端口上的残留服务会在服务改名或旧目录时
  返回像游戏 bug 的 404。测试后按端口杀干净：
  `Get-NetTCPConnection -State Listen | Where LocalPort -in 8101,8102`
  再 `Stop-Process`。
- 同一台机器上多个游戏共享一个 origin，`localStorage` 与 IndexedDB（存档、插件
  偏好）在强制刷新后仍然存活并在游戏之间泄漏。
- 绑 `0.0.0.0` 时 WSL 的局域网地址（`ip -4 addr` 的 `eth1`）可直连；本机
  `curl` 被代理截获（502）是代理行为，加 `--noproxy '*'` 验证。

### 3.2 PowerShell 的坑

- **`> NUL` 会在仓库里留下一个叫 `NUL` 的文件**。现象：全量测试突然报
  `shutil.Error: [WinError 87] The parameter is incorrect`，指向
  `<repo>\NUL -> <temp>\GameTranslation\NUL`；原因是仓库根目录多了一个 0 字节、
  名为 `NUL` 的文件（Windows 保留设备名），而这类测试会把整个仓库复制到临时
  目录，复制到 `NUL` 必然失败。来源是某条 PowerShell 命令里写了 `... > NUL`：
  在 `cmd` 里 `NUL` 是空设备，在 PowerShell 里是普通文件名。判据：测试失败信息
  里出现「复制仓库」加 `WinError 87` 或 `NUL`／`CON`／`AUX`／`PRN`／`COM1`
  之类的名字，就是这类污染，不是代码坏了。保留名不能直接 `Remove-Item`，用
  `cmd /c 'del "\\?\<repo>\NUL"'` 删除。规矩：PowerShell 里丢弃输出一律用
  `> $null` 或 `| Out-Null`，新建脚本前先 `git status --porcelain` 扫一眼有没有
  冒出来的未跟踪文件。
- **`Start-Process -ArgumentList` 对含 `～`（全角波浪号）的路径失效**：进程启动
  即退且无日志。同一命令换成
  `cmd /c start /b python -m <module> "<path>" -p <port>` 正常；路径无此字符时
  `Start-Process` 正常，所以症状不固定。启动失败后先在前台跑一次看是否端口
  冲突，再换 `cmd /c start /b`。
- **`Start-Process -ArgumentList` 会弄坏带空格的参数**：把整条命令写成一个预
  引号字符串（`'"<带空格的路径>" -p 8100'` 形式）再传，并带上脚本路径。

## 4. `.ks` 编码探测的字节序反转

KiriKiri 与 TyranoScript 的 `.ks` 用同一套「探测编码」逻辑，但历史上是两份
拷贝（`kirikiri/ks_extract.py` 与 `tyrano/tyrano_extract.py` 各一份）。合并到
core（`rpgmaker/textencoding.py`）时才发现：两份拷贝里那一行都是错的，所以谁
也纠正不了谁。

### 4.1 缺陷：无 BOM 的 UTF-16 字节序取反

无 BOM 时靠「空字节落在哪个奇偶位」判断字节序，原实现是：

```python
return "utf-16-be" if odd > even else "utf-16"
```

实测（真实 `.ks` 场景文本，112 字节、38 个空字节）：

| 实际编码 | even_null | odd_null | 原判定 | 正确 |
|---|---|---|---|---|
| UTF-16 **LE**（无 BOM） | 0 | 38 | `utf-16-be` 错 | LE |
| UTF-16 **BE**（无 BOM） | 38 | 0 | `utf-16`（本机 LE）错 | BE |

**两个方向都刚好取反**。机理：UTF-16 里近乎 ASCII 的文本每个字符带一个空
字节，那是**高字节**——LE 时落在奇数偏移，BE 时落在偶数偏移。原式把「奇数位
空字节多」判成了 BE。

### 4.2 后果不止是读错：回写会把文件也写坏

`tools/apply_ks_translation.py::patch_file` 用探测到的名字回写：

```python
text, enc = ks_extract.load_ks(src_path)   # enc 可能是错的
...
encoded = data.encode(enc)                 # 于是用错误字节序写出
```

`data.encode("utf-16-be")` **不写 BOM**，所以「无 BOM 的 UTF-16LE 原文」会被
换成「无 BOM 的 UTF-16BE 打补丁文件」——读一次错、写一次错，引擎再按 LE
解释，等于整篇报废。流水线里这不是崩溃而是**静默**：`errors="replace"` 保证
谁都不抛异常，提取出的键表是乱码或空的，QC 只会报「覆盖率为 0」。

### 4.3 原有单测为什么没抓住

编码探测原有的单测只断言带 BOM 的形式，但
`"...".encode("utf-16-be")` **根本不写 BOM**——那条「BE」用例喂进去的其实是
无 BOM 的 BE 字节，却按 `utf-16-be` 断言，**期望值恰好等于错误答案，于是蒙
对**。LE 那条用 `encode("utf-16")` 会带 BOM，走的是 BOM 分支，所以也没覆盖
无 BOM 路径。

三条教训：

1. 断言要写**实测出来**的值（用探针打印 hex 与奇偶空字节数），不要写「我想它
   应该是」；期望值与实现同错时测试是零信息。
2. BOM／无 BOM 乘 LE／BE 是**四种组合**，每种都要一条；`encode("utf-16-be")`
   不是「带 BOM 的 BE」。
3. 短样本靠不住：12 字节、1 个空字节低于 `nulls > len//8` 阈值，会走 Shift-JIS
   分支，所以测试要用**真实长度**的场景文本，否则测的不是那条分支。

### 4.4 现在的防线

- `rpgmaker/textencoding.py` 是唯一实现（core 级），两个引擎都从中 re-export；
  `ks_extract.detect_encoding is textencoding.detect_encoding` 按 **identity**
  断言（同一对象，不是又抄一份）。
- `tests/test_textencoding.py::TestByteOrder` 覆盖四种组合、端到端 round-trip、
  以及「两种字节序必须给出不同答案」。
- `tests/test_textencoding.py::TestBothEnginesShareOneImplementation` 额外断言
  `tyrano/tyrano_extract.py` 源码里不再出现 `kirikiri`（跨引擎 import 由
  `tests/test_package_boundaries.py` 统一拦，这里钉住这个具体缺陷）。
- 变异验证（写完门禁必须确认它能变红）：把那一行改回取反，**6 个用例变红**；
  把探测改成「无 BOM 时永远返回 `utf-8`」，**2 个用例变红**。

### 4.5 去重本身就是一种测试

同一个 bug 在 N 份拷贝里就是 N 份 bug，而且**互相掩盖**——看起来「两个引擎
行为一致」，其实是一致地错。合并重复实现时如果只做机械搬运，缺陷会被原样搬进
新家，而且更难发现（只剩一处可看，反而像是对的）。

1. 合并重复实现前，先给被合并的行为写**基于实测的性质测试**，再搬。
2. 搬完必须做**变异验证**：「搬过来还是绿的」只说明老测试弱，不说明新代码对。
3. 跨引擎共享的逻辑一律放 core，`tests/test_package_boundaries.py` 会拦下再
   抄一份的尝试——这道门禁在合并时抓到了 `tyrano → kirikiri` 的边。
