# 打包与包布局：wheel 必须覆盖全部公开入口

状态：已采纳

## 背景

项目长期只以「仓库 + 可编辑安装」（`pip install -e .`）形式使用，这掩盖了
打包缺陷：editable 安装从检出目录导入，`pyproject.toml` 里漏掉的包照样能
`import`，本地测试与 CI 全绿，而产出的 wheel 是坏的。

**实测**：`pip wheel . --no-deps` 产出的 wheel 只有 68 个成员，
`translation/`、`tools/` 与 `tyrano/ui_lang_zh.json` 全部缺失。

- `[tool.setuptools] packages` 漏列 `translation` 与 `tools`。
- `[tool.setuptools.package-data]` 只声明了垫片资源，漏了公开可复用资源。
- 版本号重复两处（`pyproject.toml` 与 `rpgmaker/__init__.py`）。

其中 `translation` 是文档化的公开入口（`python -m translation.cli`）。

## 决策

1. **官方支持 wheel 安装**，并把「wheel 内容」当作门禁而不是附带产物：
   `tests/test_wheel_contents.py` 断言 wheel 含全部文档化入口与资源，并在
   **装到外部目录**后真正 import、跑 `--help`（不依赖检出目录）。
2. **版本号单一来源**：`pyproject.toml` 用 dynamic version 读
   `rpgmaker.__version__`。
3. **依赖锁定**：提交 `uv.lock`（含 extra），用于审计与可复现安装；
   `tests/test_lockfile.py` 断言锁文件与 `pyproject.toml` 同步。
4. **`tools/` 整体进入 `packages`**：`python -m tools.*` 是文档化的入口，
   且 `tools/` 内部使用同级裸导入，需要它自身在 `sys.path` 上。代价是 wheel
   携带全部维护脚本。
5. 与布局相关的**目录树唯一权威**是 `docs/reference/repo-layout.md`，
   `tools/check_docs.py` 用它做一致性检查。

## 后果

- 任何阶段若打不出干净的 wheel，或 Windows 与 Linux 基线不通过，必须停下并
  恢复基线。
- 新增公开入口或包内资源时，必须同步 `pyproject.toml` 与
  `tests/test_wheel_contents.py`，否则门禁失败。
- 顶层包名与 `src/` 布局的重排是独立决策：改动需要单独的 ADR 说明迁移步骤
  与兼容期，不在本决策范围内。
