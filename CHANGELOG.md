# 变更记录（CHANGELOG）

本文件记录本工具库**面向使用者**的变更：新的引擎支持、命令行为变化、
依赖增减、以及**弃用与删除**。

## 格式与规则

- 采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的分节
  方式（`新增` / `变更` / `修复` / `弃用` / `删除` / `安全`）。
- **版本号来自代码**：唯一来源是 `rpgmaker/__init__.py` 的 `__version__`
  （`pyproject.toml` 用 `version = {attr = "rpgmaker.__version__"}` 读取它）。
  本文件不维护第二份版本字面量。
- **`Unreleased` 一节是默认位置**。一次「发布」= 把该节改名为带版本号的
  标题并另起一个新的空 `Unreleased`。本仓库目前**没有 git tag**，所以
  `1.0.0` 是代码里的当前版本号，而不是一个已打标签的发布。
- **弃用必须写进「弃用」一节**，并同时在 `rpgmaker/inventory.py` 里把该模块
  的状态标为 `superseded` 或 `dead` 并写明 `replacement`。规则与宽限期见
  `docs/reference/deprecation-policy.md`；`tests/test_changelog.py` 会把这条
  规则当门禁跑（漏记会让测试变红，而不是只靠人工复核）。

---

## [Unreleased]

### 新增

- **共享 I/O 边界**：`rpgmaker/io_boundary.py` 成为文本 / JSON / JSONL 读写的
  唯一入口。写入**原子发布**（临时文件建在目标同目录、一次 `os.replace` 落地），
  失败或中断既不留下残骸也不摧毁旧内容；`dump_json` 覆盖仓库既有的两种字节
  精确风格（pretty 与 compact）；`read_jsonl` 对坏行**报出 `path:line` 而不是
  静默跳过**；`backup_file` 保证备份保存的是 patch **前**的内容。
- **mypy 双层类型门禁**：全仓层用错误预算封顶（只降不升），strict 层把已清理
  的模块按住零错误，避免债务在总预算里长回来。工具 `tools/mypy_check.py`，
  已接入本地总入口与 CI。
- **本地门禁总入口** `tools/check_all.py`：按依赖顺序跑全部检查，缺失依赖时
  **报出缺哪个包**（`SKIPPED` 不再与「通过」看起来一样）。
- **跨系统路径归属门禁**：档案、各引擎读写入口、全部命令行工具都已接入
  `require_native_paths`，跨侧操作在打开后端之前就被拒绝并给出一行原因。
- **新增文档**：`docs/reference/deprecation-policy.md`（弃用政策）。
- **贡献模板**：`docs/CONTRIBUTING.md` 新增五条标准步骤（新增引擎 / 命令 /
  测试 / 文档 / ADR），每条点名必须先改哪个文件（inventory 登记、
  `cliutil.py` 约定、`check_all.py` 门禁、目录树、ADR 编号表）。

### 变更

- **CI 门禁真正生效**：覆盖率下限现在由 `tools/check_coverage.py` 在 CI 里
  阻断（此前只上传 XML 而从不比对）；wheel 任务装齐了自己要跑的命令；
  Windows 矩阵的多行命令改为单行（PowerShell 下 `\` 续行无效，曾使整个
  Windows 矩阵失效）。

### 修复

- `os.path.relpath` 在 Windows 上跨驱动器会抛 `ValueError`，把「图片转换
  失败的告警」升级成整个构建崩溃；新增 `platform.display_path` 统一处理。
- 裸分隔符串（`//`、`\\`）曾被误判为 UNC 路径，导致 WSL 下拒绝一个其实只是
  相对形式的输入。
- mypy 错误预算随宿主平台漂移（Windows 189 / Linux 188），使同一个门禁在
  不同 runner 上结果不同；现已钉死一个平台。
- Python 3.10 上 `import tomllib` 直接失败（该模块 3.11+ 才有），会让门禁
  **什么都没检查却返回非零**。

### 弃用

以下工具已被取代，保留一个宽限期的唯一理由是「万一还在引用」；新流程一律
用括号里的替代入口。删除时机见 `docs/reference/deprecation-policy.md`。

- **`tools/extract_text.py`** → `translation.cli prepare`。已**零导入者**。
- **`tools/plain_to_translated.py`** → `translation.cli bake`（旧 `===KEY===`
  纯文本格式，v1 流程遗留）。
- **`tools/translate_rpgmaker.py`** → `translation.cli prepare`（v1 翻译链）。
- **`tools/gen_csv_shards.py`** → `translation.cli slice`（CSV 分片链）。

### 删除

- **`superseded/` 归档目录整体移除**（窗口截图工具 + WSL 包装 + 其单测）。
  删除理由不是「换了工具」而是**政策禁止**：`AGENTS.md` 明写需要验证画面时
  使用浏览器自动化能力、**不自建窗口截图工具**，无法自动化的步骤停下请
  owner 手动完成。既然禁止复用，继续归档只是噪声。
- 随之删除孤儿 fixture `fake_powershell`（唯一消费者是被删的归档测试）。
- 修掉一处**假替代声明**：inventory 曾把归档测试的替代写成
  `tests/test_screenshot_docs.py`，而该文件从未存在；现在有门禁
  `test_the_superseded_replacement_names_a_real_target` 解析每条 replacement
  的目标并断言它真的存在。

### 安全

- 仓库卫生门禁（`tests/test_repo_hygiene.py`）与本地广告关键词表扫描是提交前
  的强制检查，公开仓库**任何文件**都不得含游戏名 / 作者名 / 密码 / 本机路径 /
  推广渠道名 / 露骨词汇；游戏专属数据一律只放本地私有位置。
