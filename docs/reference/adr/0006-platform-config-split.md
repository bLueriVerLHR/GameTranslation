# 0006 平台与配置拆分：每个关注点一个模块，`config.py` 只做兼容层

- 状态：已采纳
- 日期：Phase 4（平台与配置安全）

## 背景

`rpgmaker/config.py` 长期是 951 行的「什么都装」模块，同时承担五件事：

1. 平台识别与路径转换（WSL / Windows / 原生）；
2. 本地私有数据布局（`.private` / `.asset`，以及旧布局的只读回退）；
3. 机器配置文件的加载、校验与版本；
4. 外部程序注册表与解析（`TOOLS` / `resolve_tool()`）；
5. 交付目录、工作区根、字体解析，外加 RPG Maker 构建常量。

后果很具体：

- **反向依赖无法拦截**：`rpgmaker/plugincompat.py:55` 曾 `from tools import
  plugins_io`，而 core 按定义必须引擎中立（`docs/experience-misc.md`）。
- **`sys.path` 魔法**：59 个生产模块改写 `sys.path` 只为了能 `import
  config` 的邻居，因为一个大模块让「谁是共享核心」变得不可见。
- **测试无法重定向**：`monkeypatch.setattr(config, "_home_dir", ...)` 这类
  打补丁能生效，只是因为所有东西恰好在同一个模块命名空间里；模块一旦变大，
  「这个 patch 到底改了谁」就没有答案。
- **跨系统规则靠人肉遵守**：判定函数和写盘函数在同一文件，写入门岗无处落
  脚（PLAN Phase 4 task 4 要求「每个写操作在入口检查同侧」）。

## 决策

按关注点拆成七个模块，各自有 docstring 与 `__all__`：

| 模块 | 职责 |
|---|---|
| `rpgmaker/platform.py` | 平台识别、`StorageSide`/`PathDomain`/`PathRef`、路径转换、同侧写入门岗（`check_same_side`） |
| `rpgmaker/settings.py` | 本地私有布局的**唯一映射**（`PRIVATE_PATHS`）、机器配置校验与版本 |
| `rpgmaker/tool_registry.py` | 外部程序注册表、解析顺序、`ToolStatus` 分级、`win_7z`/`run_powershell` |
| `rpgmaker/deliverables.py` | 交付目录与临时目录的探测/默认值 |
| `rpgmaker/workspace.py` | 每游戏工作区的根与解析顺序 |
| `rpgmaker/assets.py` | 字体**文件**解析（回答「哪个文件」） |
| `rpgmaker/constants.py` | RPG Maker 构建常量（阈值、目录名、magic header） |

三条配套规则：

1. **`rpgmaker/config.py` 退化为无逻辑的 re-export 兼容层**，保留一个兼容
   周期。它的 docstring 明说私有 helper **故意不 re-export**——旧 patch 若
   不再有效，应当 `AttributeError` 失败，而不是让测试静默地什么都不测。
   `tests/test_config_facade.py` 钉死这一点：仓库内**没有任何生产模块**
   （`tests/` 除外）可以 import 这个 facade。
2. **跨模块读取一律走模块属性，不 import 值**。`tool_registry` 写
   `settings.LOCAL_ENV_FILE`、`platform.is_wsl()`，而不是
   `from .settings import LOCAL_ENV_FILE`——import 期捕获的值无法被
   monkeypatch 重定向，这是拆分过程中真实出现过的 bug。
3. **`fontpolicy.py` 是第八个模块**，超出 PLAN 原本列的六个：`assets.py`
   只回答「哪个字体文件」，`fontpolicy.py` 回答「是否应用 + 文件是否就是
   manifest 描述的那个」（sha256）。把「策略」塞进 `assets.py` 会让职责二
   义（`required` 失败 / `auto` 只报告 / `preserve` 不动）。

## 被否掉的方案

- **新建顶层 `gametranslation` 包 + `src/` 布局**（PLAN Phase 3 task 1 的
  原始写法）：被 ADR-0005 挡下（`src/` 迁移需要自己的 ADR 与兼容窗口），
  且 `PLAN.md` §7 禁止一次性全仓重排。本次改为**在现有包内做边界工作**，
  重排仍未做。
- **保留 `config.py` 为真实实现、只加薄包装**：那样反向依赖照样成立，门禁
  照样拦不住。
- **用 Pydantic 校验机器配置**：形状小且固定，手写校验 + dataclass 已足够；
  为六个字符串字段引入运行时依赖不划算（同一论点见 PLAN Phase 4 task 5）。

## 后果

- `tests/test_package_boundaries.py` 与 `tests/test_config_facade.py` 把
  方向钉死：core 不 import 引擎、引擎之间不互相 import、facade 无人 import。
- 测试按新边界拆分为 `tests/test_platform_paths.py`、`test_settings.py`、
  `test_tool_registry.py`、`test_deliverables.py`、`test_assets.py`、
  `test_constants.py`、`test_config_facade.py`、`test_fontpolicy.py`、
  `test_path_properties.py`；原 641 行的 `tests/test_config.py` 已删除。
- `doctor --json` 成为稳定接口（`ok` / `checks` / `tools` / `private` /
  `warnings`），并按 `ToolStatus` 把缺失分成 `[MISS]` 与 `[WARN]`。
- 新增外部程序 = 在 `tool_registry.TOOLS` 加一条，且**必须有真实调用者**
  （无调用者的解析器条目是死代码，`docs/experience-misc.md` §10.4）。
