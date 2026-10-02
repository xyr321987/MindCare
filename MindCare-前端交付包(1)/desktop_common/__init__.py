"""MindCare 双端共享包（`docs/UI约定.md` §1）。

| 模块 | 内容 |
|---|---|
| `theme` | 调色板 + 尺寸 + `build_qss()`（**两个应用都调它**） |
| `api` | `ApiClient` + `ApiError`（信封解包，`code != 0` 一律抛） |
| `widgets` | 基础控件（按钮/卡片/标签/输入区/进度/结果页容器/提示条） |
| `models` | 与契约一致的轻量数据类 |
| `copy` | 文案解析（**面向用户的文字一律来自文案表**） |

owner：学生端 agent（UI约定 §1 改动规则）。教师端只读引用。
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.1.0"
