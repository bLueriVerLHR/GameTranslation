# tests/ — 测试体系说明

本目录的测试契约（PLAN Phase 5）。**不要用测试总数判断质量**：质量看风险矩阵、
branch coverage、mutation score 与真实验收记录。

## 1. 两个层，一句话区分

一个 marker 表示「PR runner 可能没有这个能力」**——所以「文件放在哪个目录」不是分层，
「这个测试需要什么」才是。** 113 个测试文件里只有 9 个带层 marker（其余 104 个完全不
依赖本机能力），这正是分层的意义：把少数需要外部能力的标出来，而不是把 104 个文件
搬进新目录。

PLAN Phase 5 task 1 写的是「按 unit / contract / integration / e2e 重组」，**本仓没有按
目录重组**，理由有两层：

1. PLAN §7 明禁「全仓一次性目录重排」，而且目录重组会让 153 处测试路径引用
   （源码注释、`tools/mutation_check.py` 的 selector、CI、文档）全部失效，换来的是零行为改变。
2. 实测**task 1 命名的问题在本仓不存在**：113 个文件里 83 个的命名直接对应一个生产模块
   （`test_archive_wrapper.py` ↔ `rpgmaker/archive.py`），另外 30 个是刻意的跨模块门禁
   （`test_package_boundaries.py`、`test_test_layers.py`、`test_fixture_manifest.py` …）。
   没有「一个事故一个文件」无限增长的尾巴。

分层的**实质要求**由 marker + `tests/test_test_layers.py` + CI 的 `nightly` 任务满足。
将来真要做物理拆分，先满足两个条件：路径引用的自动改写（包括变异表 selector）
与一次可回滚的提交。

| 层 | 命令 | 外部依赖 | 本机耗时（参考） |
|---|---|---|---|
| 快速（默认门禁） | `pytest tests -m "not slow and not media and not node and not engine_runtime and not wsl and not browser and not device"` | 无（venv 内即可） | ~45 s（`-n auto`；实测全量 47.6 s） |
| 夜间 / 手动 | `pytest tests -m "slow"`、`-m media`、`-m node`、`-m engine_runtime` | 见下表 | 分钟级 |
| 实机 | `-m wsl` / `-m browser` / `-m device` | WSL / 浏览器自动化 / Android JoiPlay | CI 永不跑 |

| marker | 含义 | 缺能力时 |
|---|---|---|
| `slow` | 单测 >~5 s，或要构建/安装产物 | 不跑，或按 CI 分层跑 |
| `media` | 需要真实编解码器（PyAV libvpx-vp9/libvorbis、ffmpeg 二进制） | skip，并说明缺什么 |
| `node` | 需要外部 Node.js（`rpgmaker.tool_registry.find_node`） | skip |
| `engine_runtime` | 需要本机真实引擎安装/游戏树 | skip |
| `wsl` | 只在 WSL 内有意义 | 非 WSL 跳过 |
| `browser` | 需要浏览器/页面自动化 | 不跑 |
| `device` | 需要 Android/JoiPlay 实机 | 永不跑 |

`slow`/`media`/`node`/`engine_runtime` 由 CI 的 `nightly` 任务分别执行
（`.github/workflows/ci.yml`）。**不要把浏览器冒烟当成 Android 实机验收**——
两者是不同层（ADR-0004、`docs/kirikiri-tyrano.md` §7）。

## 2. skip 预算

`pytest.skip` 分四类，**不允许 silent 降级**：缺 dev 工具（ruff/uv/setuptools）、
缺可选 extra（PIL/av/asar/numba）、平台/环境（git、大小写不敏感文件系统）、
本地私有或缺失的 fixture（TLG 样本、引擎源码）。

`tests/test_test_layers.py` 强制：

- 每个 skip 的**原因必须能对应到一个层**（或属于已知的「marker 也修不了」清单）；
- `SKIP_BUDGET = 27`，**skip 数增长即失败**（要么修，要么显式提高预算并说明）；
- 新增 `importorskip` 的包名必须在 `OPTIONAL_IMPORTS` 里，否则失败。

预算数字只说明“少了几块能力”，**说不了少的是哪块**——所以 CI 还跑
`python tools/skip_report.py --verbose`，把每个 skip 归到具体能力（`node` /
`media` / `guard` / `optional-import` / …），**归不了类的直接失败**
（`tests/test_test_layers.py::test_ci_prints_the_skip_inventory` 钉住 CI 真的在跑它）。

## 3. 覆盖率门槛

```bash
python -m pytest tests -q -n 0 --cov --cov-branch --cov-report=json:coverage.json
python tools/check_coverage.py coverage.json          # 门禁
python tools/check_coverage.py coverage.json --update # 抬高/记录基线
```

基线 `tests/coverage_floor.json` 分三层粒度，避免一个全局高数字掩盖薄弱模块：

- **area**（7 个包目录）；
- **高风险 module**（core 原语、二进制格式解析器、翻译门禁）；
- **total**，仅作粗略兜底。

规则是**只允许持平或上升**：降任何一条都要在 `waivers` 里写明理由，`--update`
会拒绝无声下调。基线里记录了产生它的命令。

### 新增防御性代码时：先判定可达性，再决定测、删还是标注

加边界守卫会让**分母变大**，覆盖率可能下降。此时**不允许**用「下调下限」或
`--update` 掩盖，逐条判定清楚：

- **可达** → 补测试（例：`xp3tool._need()` 用 25 字节缓冲可触发；
  `codes.bracket_pair()` 返回 `None` 可用 `\{` / `\.` 触发）；
- **不可达且无价值** → **删掉分支**（例：`xp3tool.parse_index` 的
  `segm_size < 0`——`find_chunk` 已拒绝非正长度）；
- **不可达但守卫有价值** → 保留并标 `# pragma: no cover` + **写明实测依据**
  （例：`wolfrpg/dxarchive.py` huffman 的 `node_idx < 0`——9 位查找表在
  `[1]*256`、随机 1..500、随机 1..5000、Fibonacci 权重下都无空洞；留下的理由
  是参考实现在此读 `nodes[-1]` 会**静默解错**）。

**绝不造假测试去凑覆盖率**——一条跑不到的断言配一个为它写的事例，只是把
「未覆盖」换成「假装已覆盖」。

**看新增未覆盖行要用 diff 相交，不能比 `missing_lines` 集合差**：插入代码后
后续行号全部平移，集合差会满屏假差异。做法是取 `git diff -U0` 的**新增行**与
`missing_lines` 求交（本阶段实测：13 行）。

### 工具自己也要被量：子进程里跑的代码覆盖不到

`coverage.py` **不测量子进程**，除非子进程是用 `coverage run -m` /
`COVERAGE_PROCESS_START` 起的。本阶段的三个维护工具一开始正是用
`subprocess.run([sys.executable, TOOL, ...])` 测的（那是对的 argv/退出码契约
测试），结果 `tools/check_coverage.py` 的 `cmd()` 与 `tools/mutation_check.py`
的 `check()/cmd()` 对覆盖率门禁**完全不可见**——抓覆盖率的那个工具，恰恰是
覆盖率抓不到的那个文件。`tools/skip_report.py` 更极端：只有 CI 调它，本仓
0% 覆盖。

修法是**双层**，两层各自证明不同的事：

- **进程内**（`cc.main([...])` / `sr.main([...])`）：证明分支与失败路径
  （目标文件缺失、`--update` 拒绝下调、waiver 生效、unknown 归不了类）。
- **子进程**（`_run(*argv)`）：证明真实 CLI 契约（argv 解析、退出码、stderr）。

进程内调用有两个坑（都踩过）：直接调 `cmd()` 而不传参数时，Typer 给的是
`OptionInfo` 对象而非默认值（truthy），会静默走错分支——要么走 `main(["--json"])`，
要么显式写出 `as_json=False`；另外**细节在 `log.error` 里而不是 stderr**，
所以断言要用 `caplog`，`capsys` 只能看到 `error: ...` 那一行。

### `@njit(cache=True)` 的函数体永远量不到（2026-09 实测）

本机 `kirikiri/tlg.py` 的 numba 块（`if _USE_NUMBA:` 起，第 800 行起）实测只有
装饰器/`def` 行算作“已执行”，**函数体整块缺失**——冷缓存（`NUMBA_CACHE_DIR`
指向空目录）与热缓存结果完全一样。最小复现：一个 `@njit(cache=False)` 模块
里 `fast()` 执行到 `def` 行，其函数体 3 行全在 `missing_lines`；
**换成 `@njit(cache=True)` 连 `def` 行都不执行**。经验规则：

- 看到 `module kirikiri/tlg.py` 这类模块的覆盖率下降，先看变化的是**行号**还是
  **是否执行**（把旧行号按 diff 映射到新行号再比，别直接比 `missing_lines` 集合）。
- 不要为了把 numba 块纳入分母而改 `cache=True`/加 `# pragma: no cover`：会改变
  运行时行为或把遗漏藏起来。正确做法是判断该历史上下限（这里是 47.9）只能靠
  waiver 说明维持，并把“待慢层被测量后重记”写进 waiver 理由。

## 4. mutation testing（定向）

```bash
python tools/mutation_check.py --list     # 看表
python tools/mutation_check.py            # 跑门禁（slow）
python tools/mutation_check.py --only coverage-gate
```

`tools/mutation_check.py` 手工维护一张**小而准**的表：每条记录「去掉哪个守卫」
「为什么那条守卫重要」「哪个测试负责发现」。做法是**在临时副本里**改源码再跑真
测试（同 `tests/test_wheel_contents.py`），从不改工作树。

- **不用 `mutmut`**：它拒绝在 Windows 运行（提示要用 WSL），而 ADR-0002 禁止
  WSL 原生工具处理 `/mnt/*` 树。
- 任意变异农场会产生大量等价变异（比如舍入方向），存活也没有意义；PLAN 点名的
  风险点比一个分数值钱（当前 **10 个，10/10 KILLED**：翻译的覆盖/控制码/假名残留/
  换行四道门禁 + 批量全有或全无、档案完整性、跨系统同侧拒绝、解密标志、verify 的
  残留标志与 `--source` 基线）。
- 「存活的变异」= 守卫是装饰。`tests/test_mutation_detection.py` 既证明表里的
  变异都被杀掉，也证明**探测器本身能报出存活变异**（否则 harness 永远返回
  「已杀」也能过）。
- 锚点必须**恰好出现一次**，否则 `LookupError`（不存在「改第一个命中」的降级）——
  锚点过期 = 变异没做却报「已杀」。

## 5. 性质测试

`tests/test_translation_properties.py`（Hypothesis）覆盖控制码 parse/render 往返、
译文库原子读写、`safe_replace` 幂等、机器配置与字体 manifest 的「任何形状都不
抛异常」；`tests/test_path_properties.py` 覆盖路径转换与同侧判定；
`tests/test_format_fuzz.py` 覆盖 XP3/DXArchive/TLG 的边界与随机输入。

写这类测试时的两条硬规则：

- **不要用 `tmp_path`**：Hypothesis 拒绝在生成的输入之间重置 function-scoped
  fixture；用 `tempfile.TemporaryDirectory`（见 `_TempDir`）。
- **不变量必须对任意输入成立**，不要靠固定种子制造偶然通过。
- **生成器必须真的生成「反例」**。真实翻车：
  `test_text_before_the_first_header_is_a_value_error` 的过滤条件写成
  `t.strip()`，而 `read_library` **刻意容忍 `#` 注释行**，Hypothesis 于是把失败
  收缩到 `'#'` 报 `DID NOT RAISE ValueError`——**是测试错、代码对**。判断方向
  的办法是先读被测函数的分支：生成器排除掉「读者会容忍的输入」，再补一条
  钉住那半容忍（`test_a_hash_note_before_the_first_header_is_tolerated`），
  否则下次修守卫就会把不对称删掉。

## 6. 性能测试

`tests/test_perf_smoke.py` 的原则：**不设会因机器慢而闪红的硬时限**。主要断言是
行为性的（walk 必须触达每个文件），放宽的 60 s 上限只用来抓 O(n²) 回归。

## 7. 删除一个测试的条件（PLAN Phase 5 task 10）

不是「看起来重复」，而是**同时**满足：

1. 该行为已由更高层契约测试覆盖；
2. mutation / 故障注入证明它不增加检测能力；
3. 删除后关键路径覆盖率与回归清单不下降。

不满足就保留。覆盖率门槛会拦住第三条，mutation 表会拦住第二条。

## 8. 顺序无关性（PLAN Phase 5 验收「随机顺序下稳定」）

测试必须与执行顺序无关。`-p randomly` 用本机已装的 `pytest-randomly` 做乱序验证：

```powershell
# 先装（可选工具，不进 [dev] extra——否则它会改变每次默认运行的顺序）
& .\.venv\Scripts\python.exe -m pip install pytest-randomly

# 单个种子可复现（种子会打印在输出里，用 -p randomly --randomly-seed=N 重放）
& .\.venv\Scripts\python.exe -m pytest tests -q -p randomly
& .\.venv\Scripts\python.exe -m pytest tests -q -p no:randomly   # 关掉它
```

**故意不把 `pytest-randomly` 放进 `[dev]` extra**：它通过 entry point 自动加载，
一旦进入默认环境就会改变**每一次**运行的执行顺序（并重置 `random`/`numpy` 的种子），
而本仓的门禁需要可重现的顺序。它改在 **CI 的 `nightly` 任务**里装一次并跑
快速层（step 名 `Random order`），所以乱序不是「手动才做的事」，而是**每天会跑一次
的门禁**——这正是本仓已经记录过两次的教训：一次性验证过的检查会腐化，必须变成门禁。
`tests/test_test_layers.py` 钉住该 step 存在、带 `-p randomly`，且跑的是与 PR 层
**完全相同的层表达式**（否则验证的是另一批测试）。

### 非 hermetic 是缺陷，不是 flake

乱序/并发下才红的测试，根因通常是**拿实时资源当期望值**。Phase 5 修过一个实例：
`tests/test_kag_assets.py::TestParallelEqualsSerial::test_default_worker_count_comes_from_runtime`
断言 `seen["tlg"] == assets.runtime.physical_cpu_count()`，但 worker 数实际经
`rpgmaker/runtime.py` 的 `_ram_bounded()` 用**实时空闲内存**夹紧，于是单跑绿、
并发跑红（`assert 7 == 8`）。修法是钉住输入（`physical_cpu_count` /
`memory_available_bytes` / `disk_is_rotational`，模式见
`tests/test_runtime.py::TestAutoWorkersPhysicalBase::_pin`），不是把阈值放宽。
真正的稳定性保障是：每个测试自己造数据（`tests/conftest.py` 的 `hermetic_resolution`
autouse fixture 强制 `GT_NO_PROBE=1` 并重置 `deliverables._noted_defaults`），不靠
执行顺序传递状态（Phase 5 已修过一个实例：`test_kag_assets.py` 的 worker 数测试
原本依赖真实空闲内存，见 `docs/experience-misc.md`）。

#### 「只在满载下红」也可能是真缺陷——先拿到完整诊断再判 flake（2026-09 实测）

`tests/test_mutation_detection.py::test_the_harness_reports_a_surviving_mutation`
在 `-n auto` 全量跑时红、单独跑和五个文件一起跑都绿。当时判为「拥挤下的 flaky」，
**那个结论是错的**：

- 复现方法：起满 CPU 的忙循环，8 轮内必现（所以「重跑几次绿了」不能当证据）。
- **真正的障碍是诊断被截断**：`tools/mutation_check.py::tail(text, lines=4)` 只保留
  最后 4 行，假设检验给的反例（`path='//'`）正好在被丢掉的行里。临时把 `tail`
  改成不截断，一眼就看到根因。
- 根因是**真 bug**：`rpgmaker/platform.py::domain_of` 把裸分隔符串（`//`、`\\\\`）
  判为 `WINDOWS_UNC`，于是 `side_of("//")` 返回 `WINDOWS`，WSL 下
  `require_native_paths()` 会误拒一个其实只是相对形式的输入。两个字符即可触发。
- 同时**属性测试也写错了**：`test_relative_and_empty_paths_have_no_derivable_side`
  的 `assume` 没排除 `WINDOWS_UNC`，而 UNC 确实有 side（`WINDOWS`）。所以是
  「分类器太窄 + 断言太宽」叠在一起，两边都要看。

可操作的规则：

1. 并发/满载下才红的测试，先**钉住复现**并**拿到完整诊断**，再谈 flake；
   打印/捕获路径上的截断（`tail(..., lines=N)`、`[-N:]`）会藏根因。
2. 抛错概率低的缺陷要靠**随机输入**才能撞到，那更要把反例信息完整报出，
   否则每次复现都得到不同的无用信息。
3. **枚举值定义了却没有分支返回它**＝「文档比代码宽」的信号：`EXOTIC` 从阶段 4
   写在那里到本轮才第一次真正被返回。
4. 假设检验的示例库（`.hypothesis`）是**每台机器的状态**，已从两组源码拷贝
   （`tools/mutation_check.py::COPY_IGNORE`、`tests/test_wheel_contents.py::_copy_tree_to`）
   中排除，否则拷贝树的输入空间会被本机缓存的反例左右。

## 9. 本机常用命令

```powershell
# 一次跑完所有本地门禁（提交前跑这个；CI 仍是最终权威）
& .\.venv\Scripts\python.exe tools\check_all.py

# 只跑便宜的几项（跳过套件）
& .\.venv\Scripts\python.exe tools\check_all.py --fast

# 需要套件的只跑其中几项
& .\.venv\Scripts\python.exe tools\check_all.py --only tests --only lint

# 带覆盖率测量与下限门禁
& .\.venv\Scripts\python.exe tools\check_all.py --coverage

# 快速层（只跑套件）
& .\.venv\Scripts\python.exe -m pytest tests -q

# 串行（排查顺序相关的失败）
& .\.venv\Scripts\python.exe -m pytest tests -q -n 0

# 单个文件 / 单个测试
& .\.venv\Scripts\python.exe -m pytest tests/test_translation_v2.py -q -n 0
```

`tools/check_all.py` 是 `AGENTS.md` 那份手工清单的可执行形式：它照原样跑同一批
命令，不重新实现检查，并且**缺依赖时把缺失的名字报出来**（缺 `ruff`/`uv` 时
「没检查」与「检查通过」看起来一样，那两个真实事故就是它存在的理由）。

`pyproject.toml` 的 `[tool.pytest.ini_options]` 是 marker 注册表的唯一来源
（`strict_markers = true`，拼错即 collection error）。新增 marker 必须同时改
`tests/test_test_layers.py` 的 `EXPECTED_MARKERS` 与 CI 的层命令。
