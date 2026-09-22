# 0005 打包与包布局：wheel 必须覆盖全部公开入口

状态：已采纳（2026-09 定案）

## 背景

项目长期只以「仓库 + 可编辑安装」形式使用（`pip install -e .`）。这掩盖了
打包缺陷：editable 安装从检出目录导入，`pyproject.toml` 里漏掉的包照样能
`import`，本地测试与 CI 全绿，而产出的 wheel 是坏的。

**实测**：`pip wheel . --no-deps` 产出的 wheel 只有 **68 个成员**，
`translation=False`、`tools=False`、`ui_map=False`：

- `[tool.setuptools] packages` 只列了 `rpgmaker`、`kirikiri`、
  `kirikiri.kag`、`tyrano`、`wolfrpg`、`unity`、`unity.rmunite`，缺
  `translation` 与 `tools`。
- `[tool.setuptools.package-data]` 只声明了
  `"kirikiri.kag" = ["js/*.js", "js/*.css"]`，缺 `tyrano/ui_lang_zh.json`
  这类公开可复用资源。
- 版本号重复两处（`pyproject.toml` 与 `rpgmaker/__init__.py`）。

其中 `translation` 是**文档化的公开入口**（`python -m translation.cli`），
`tools` 被生产代码导入（`rpgmaker/plugincompat.py`、`kirikiri/pipeline.py`）。

## 决策

1. **官方支持 wheel 安装**，并把「wheel 内容」当作**门禁**而不是附带产物：
   `tests/test_wheel_contents.py` 断言 wheel 必须含全部文档化入口与资源，
   并在**装到外部目录**后真正 import / 跑 `--help`（不依赖检出目录）。
2. **版本号单一来源**：`pyproject.toml` 用 dynamic version 读
   `rpgmaker.__version__`，不重复写字面量。
3. **依赖锁定**：提交 `uv.lock`（含 extra），仅用于审计与可复现安装。
4. **暂不迁移 `src/` 布局**：目标架构在 `PLAN.md` §3 规划为
   `src/gametranslation/`，但那是一次**目录级重构**，与本决策解耦。当前
   `tools/` 整体进入 `packages`（因为 `tools/` 内部依赖同级裸导入
   `import japanese_utils`，需要 `tools/` 自身在 `sys.path` 上），代价是
   wheel 携带全部 44 个 `__main__` 脚本；收紧到显式模块列表放在后续阶段。
5. 与布局相关的**目录树唯一权威**是 `docs/reference/repo-layout.md`，
   `tools/check_docs.py` 用它做一致性检查。

## 后果

- 任何阶段若打不出干净的 wheel，或 Windows/Linux 基线不通过，**必须停下并
  恢复基线**（见 `PLAN.md` §7）。
- 新增公开入口或包内资源时，必须同步 `pyproject.toml` 与
  `tests/test_wheel_contents.py`，否则门禁失败。
- `PLAN.md` 提出的 `src/gametranslation/` 重排是**独立后续决策**，改之前需
  另写一篇 ADR 说明迁移步骤与兼容期。
