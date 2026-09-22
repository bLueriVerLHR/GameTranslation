# GameTranslation

面向 **JP→ZH 翻译 + 手机可玩构建** 的本地工具库；**DeepSeek V4 Flash**
编写，基本没有人工编写的代码。

先看 **[docs/index.md](docs/index.md)** —— 那里按「我想做什么」分流到对应
文档。本文件只回答「这工具能做什么、怎么跑起来、去哪看细节」。

## 能做什么

| 目的 | 引擎 | 入口 |
| --- | --- | --- |
| **JoiPlay 可玩构建**（剥 NW.js、easy 解密、音频压缩、清理、验证、7z-zstd 打包） | RPG Maker MZ/MV 网页版 | `pipeline.py`（= `gt`） |
| **JoiPlay 构建 + 翻译**（解包 `app.asar`、剥 Electron、存档改 webstorage、mp3→ogg 并同步重写引用、MTool 残留清理） | TyranoScript / TyranoBuilder | `tyrano/pipeline.py`（= `gt-tyrano`） |
| **手机转换（当前主线）**：KAG3 → TyranoScript，保留图层、排版与音画时序 | KiriKiri2 / KAG3 | `kirikiri/pipeline.py` |
| **仅翻译 + 注入**（不做移动端转换） | Unity（Mono / IL2CPP）、Wolf RPG、KiriKiri 桌面版 | 见下方「按引擎看」 |

**权威定义不在这里**：每个引擎支持什么、处于什么状态、哪些步骤需要人工
验收，看 **[docs/reference/support-matrix.md](docs/reference/support-matrix.md)**。
**硬边界**：Unity 与 Wolf RPG **绝不走** RPG Maker 流水线，也绝不解密/
重编码；KiriKiri 不使用 RPG Maker 专用流水线。

### 按引擎看

- RPG Maker MZ/MV：`pipeline.py` —— [docs/workflow.md](docs/workflow.md)
- TyranoScript / TyranoBuilder：`tyrano/pipeline.py` —— [docs/tyrano.md](docs/tyrano.md)
- KiriKiri：手机转换 [docs/kirikiri-tyrano.md](docs/kirikiri-tyrano.md)；
  桌面翻译 [docs/kirikiri.md](docs/kirikiri.md)
- Wolf RPG：`wolfrpg/dxarchive.py` —— [docs/wolfrpg.md](docs/wolfrpg.md)
- Unity：运行时 hook（Unity Mono / IL2CPP / RM Unite 三套）——
  [docs/engines/unity.md](docs/engines/unity.md)、
  [unity-il2cpp.md](docs/engines/unity-il2cpp.md)、
  [unity-rmunite.md](docs/engines/unity-rmunite.md)

## 快速开始 — RPG Maker

```powershell
$tk  = "<本工具库路径>"
$src = "C:\path\to\game"
$out = Join-Path $env:TEMP 'game'              # 工作目录（Temp，可删）
$g   = "<交付目录>"                            # 成品放这里

python $tk\pipeline.py unpack-data $src      # 仅 launcher 打包件：还原 <Game>.exe 里的 data/
python $tk\pipeline.py build   $src -o $out
python $tk\pipeline.py compat  $out          # 插件加载期崩溃：定点维修 + 预扫
python $tk\pipeline.py decrypt $out          # 仅 RPGM + easy 加密；否则跳过
python $tk\pipeline.py audio   $out
python $tk\pipeline.py clean   $out
python $tk\pipeline.py verify  $out --source $src
python $tk\pipeline.py serve   $out --test     # 先试玩确认，再打包
python $tk\pipeline.py deliver $out            # 压缩 → 复制压缩包 → 解压到成品目录
```

- `decrypt` 默认只在 RPG Maker MZ/MV **easy** 加密（每个加密资源都带标准
  RPGMV 头）时运行；复杂/自定义加密游戏原样跳过。总原则：如果解密不会
  改变游戏在 JoiPlay 下的运行方式，就不运行。
- 有些 repack 把数据库整个塞进 `<Game>.exe`（Enigma Virtual Box 打包件）：
  先跑 `unpack-data` 把 `data/` 还原回源目录，再按上面顺序构建。
- **打包前必须架服务器试玩**：`serve <dir> --host 0.0.0.0 -p <端口>`
  （不带 `--host` 只有本机能访问，手机连不上）。
- 并行度默认按机器自动调优（`rpgmaker/runtime.py`），可用 `GT_WORKERS` 覆盖。
- WSL 侧命令与路径解析见 [docs/workflow.md](docs/workflow.md)。

**跨系统铁律（CRITICAL）**：处理文件必须用**文件所在系统**的原生应用。
Windows 侧文件（`/mnt/*`）一律用 Windows 的 `7z.exe`/PowerShell，从 WSL 经
`powershell.exe` 调用；WSL 内 7zz/python 直接操作 Windows 侧文件被禁止
（曾导致电脑花屏）。跨系统只搬运**单个压缩包**；`deliver` 已内置自动桥接。
原版游戏目录**绝不修改**。背景与后果见
[docs/reference/adr/0002-cross-system-file-ownership.md](docs/reference/adr/0002-cross-system-file-ownership.md)。

## 翻译（JP → ZH）

现行流程只有一条：**单一写者 + 文件信箱 + 五道硬门禁**
（[docs/translation.md](docs/translation.md)）——
`python -m translation.cli prepare/slice/append/gates/bake`；
v1 的「切块 → 每块一个 subagent → 按行合并」已退役
（[docs/archive/translation-v1.md](docs/archive/translation-v1.md)，
不要照它执行）。

- 数据契约（键表、译文库、门禁口径）见
  [docs/translation-data.md](docs/translation-data.md)；真机踩过的坑与
  故障排查见 [docs/translation-qc.md](docs/translation-qc.md)。
- 非 MZ 引擎（Tyrano / Wolf / KiriKiri）沿用各自引擎指南里的提取/写回链。
- **清除 MTool 机翻，自己翻译**；翻译前先量体量并取得 owner 授权。
- 每游戏资料（词表/语气/笔记）**不入库**，只存在本地私有数据目录，
  位置与边界见 [docs/reference/local-layout.md](docs/reference/local-layout.md)。

## 环境要求

- **Python 3.10+**。建本地虚拟环境 `.venv/`（gitignored）：
  `pip install -e ".[images,unity,fonts,dev]"`。
- 外部程序只有**两个**必需：`ffmpeg`（仅 Vorbis 音频编码 —— PyAV 的 wheel
  不含 libvorbis）与 Windows 侧 `7z.exe`（仅跨系统桥接）。其余能力已在进程内
  实现（7z→py7zr、媒体→PyAV、asar→`asar`、JS 语法→tree-sitter），
  **不再需要 Node.js / npx / ffprobe**。完整表格见
  [docs/reference/support-matrix.md](docs/reference/support-matrix.md) §4 与
  [docs/reference/tooling.md](docs/reference/tooling.md)。
- 外部程序路径**不需要手工维护**：`python pipeline.py doctor` 列出每个程序
  解析到的路径与来源（环境变量 → 本地配置 → 探测 → PATH），`--json` 供脚本
  消费。本机环境覆盖是**可选层**——没有它也能跑。

## 开发与门禁

贡献流程、分支命名与提交规则见 [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
与 [AGENTS.md](AGENTS.md)。合并前五道门禁全绿：

```bash
<venv-python> -m pytest tests/                        # 单元 + 集成（默认 -n auto）
<venv-python> -m ruff check .                         # lint（规则钉在 pyproject.toml）
<venv-python> -m pytest tests/test_repo_hygiene.py -q # 公开仓库卫生（禁本机路径等）
<venv-python> tools/check_docs.py                     # 目录树一致性 + 文档门禁
<venv-python> -m compileall -q <改动的包>             # 改动的 Python 必须能编译
```

改了 `.py` 后按需同时跑其余两道门禁：**组件锁** `uv lock --check`（改了
`pyproject.toml` 依赖就必须重跑 `uv lock` 并提交 `uv.lock`，否则干净环境装
出的开发工具链与测试过的不一致）与 **wheel 内容**（新增公开入口或包内资源
必须同步 `pyproject.toml` 与 `tests/test_wheel_contents.py`）。两道门禁都有对应
的 pytest 文件（`tests/test_lockfile.py` / `tests/test_wheel_contents.py`），
因此 `pytest tests/` 已覆盖。
测试不需要外部工具：`tests/fake_tools/` 提供假 ffmpeg（Vorbis 编码仍调 ffmpeg
CLI），真实媒体固件在 `tests/fixtures/`。打包是进程内的（py7zr），所以没有假
7z。

## 目录与本地私有数据

目录树见 **[docs/reference/repo-layout.md](docs/reference/repo-layout.md)**
（唯一权威，`tools/check_docs.py` 用它做一致性检查）。设计决策与已推翻的
做法见 [docs/reference/adr/](docs/reference/adr/)；踩坑经验见
[docs/experience.md](docs/experience.md)。

**词表 / 密码 / 打包字体 / 每游戏资料一律不入库**（`.private/`、`.asset/`、
系统临时文件夹里的工作区），干净检出不存在它们；缺失时相关步骤按规则
**WARN 并跳过，不静默降级**。布局、迁移与字体策略见
[docs/reference/local-layout.md](docs/reference/local-layout.md)。
