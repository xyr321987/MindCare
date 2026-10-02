"""文案解析（`docs/UI约定.md` §4）：**面向用户的文字一律来自文案表**。

两份事实源，键名口径不同（详见 `tools/gen_copy_text.py` 的头部说明）：

1. `mindcare/copywriting.md` —— 内容负责人维护的完整文案表，用**点分 ID**
   （`s.q1.title` / `s.revoke.entry.action` …）。构建期由
   `tools/gen_copy_text.py` 解析成 `desktop_common/copy_text.py`。
2. `mindcare/copywriting.json` —— **运行时文案表（B 线资产，与 `copywriting.md` 同级）**。
   **本模块在运行时读它**（UI约定 §4 指定的用法），用于
   `errors` / `hotlines` / `/tips` 场景键，并覆盖 md 与 JSON 用词不一致的条目。

   ⚠️ **为什么不在 `server/` 下**（2026-10-02 修正）：文案表由 **B 线（前端）维护**，
   而 `server/` 是**给定的后端 API**，工程纪律要求它保持与上游交付逐字节一致、不被前端改动。
   原先把运行时 JSON 放在 `server/` 下，导致"前端资源依赖后端目录"的耦合——
   一旦 `server/` 按上游原样恢复，前端 58 条文案就会静默缺失。现在两份事实源都归前端所有。

界面代码只允许写 ID：

    from desktop_common.copy import COPY
    COPY["s.q1.title"]
    COPY.error(1002)
    COPY.hotline_line()

**缺键不得就地写死**：`COPY.missing_keys` 会记录所有未解析的 ID，
自检脚本会把它打印出来（并要求为空）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # 包内导入
    from .copy_text import TEXT as _GENERATED_TEXT
except ImportError:  # pragma: no cover - 直接以脚本路径导入时的兜底
    from copy_text import TEXT as _GENERATED_TEXT  # type: ignore

__all__ = ["COPY", "CopyTable", "ROOT", "COPY_JSON_PATH"]

#: 工程根 = `mindcare/`（本文件在 `mindcare/desktop_common/` 下）
#: PyInstaller 打包（frozen）时数据文件在 `sys._MEIPASS`，不依赖 `__file__` 相对路径。
if getattr(sys, "frozen", False):
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).resolve().parent.parent
COPY_JSON_PATH = ROOT / "copywriting.json"


class CopyTable:
    """文案表门面：`[]` 取点分 ID，另提供 JSON 专有键的便捷方法。"""

    def __init__(self, json_path: Path = COPY_JSON_PATH) -> None:
        self.json_path = Path(json_path)
        self._raw_json: Dict[str, Any] = {}
        self._load_error: Optional[str] = None
        self._missing: List[str] = []
        self._data: Dict[str, str] = dict(_GENERATED_TEXT)

        # ① 运行时读 JSON（UI约定 §4）；用于 errors / hotlines / tips 场景键，
        #    并覆盖 md 与 JSON 用词不一致的条目（与 tools/gen_copy_text.py 的
        #    OVERRIDES / JSON_ONLY 同一份口径）。
        try:
            self._raw_json = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # 不静默：记录原因，`missing_keys` 里会出现 `__json__`
            self._raw_json = {}
            self._load_error = f"{type(exc).__name__}: {exc}"
            self._missing.append("__json__")

        for key in self._json_override_keys():
            path = _OVERRIDE_PATHS[key]
            value = _walk(self._raw_json, path)
            if isinstance(value, str):
                self._data[key] = value
            else:
                if key not in self._missing:
                    self._missing.append(key)

    # -- 基础 ---------------------------------------------------------------

    def __getitem__(self, key: str) -> str:
        try:
            return self._data[key]
        except KeyError:
            if key not in self._missing:
                self._missing.append(key)
            # 明确暴露缺键（界面显示成括号 ID，便于一眼看出是配置问题），
            # **绝不**在这里编一句中文兜底 —— 那正是"就地写死"。
            return f"⟪缺文案:{key}⟫"

    def get(self, key: str, default: str = "") -> str:
        value = self._data.get(key)
        if value is None:
            if key not in self._missing:
                self._missing.append(key)
            return default
        return value

    def has(self, key: str) -> bool:
        return key in self._data

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def keys(self) -> Iterable[str]:
        return self._data.keys()

    # -- JSON 专有键 --------------------------------------------------------

    def raw(self, *path: Any) -> Any:
        """按路径读 `copywriting.json`（如 `raw('revoke', 'end_page', 'title')`）。"""
        return _walk(self._raw_json, path)

    def error(self, code: Any) -> str:
        """契约错误码 → 文案（`errors`；网络层用 `'network'`）。"""
        key = "network" if str(code) in ("network", "timeout") else str(code)
        value = _walk(self._raw_json, ("errors", key))
        if isinstance(value, str):
            return value
        return self["c.error.unknown"]

    def hotlines(self) -> List[Dict[str, str]]:
        value = self._raw_json.get("hotlines")
        return list(value) if isinstance(value, list) else []

    def hotline_line(self) -> str:
        value = _walk(self._raw_json, ("self_care_page", "hotline_line"))
        if isinstance(value, str):
            return value
        return self["c.hotline.line"]

    # -- 缺键 ---------------------------------------------------------------

    @property
    def missing_keys(self) -> List[str]:
        """未解析的 ID（自检要求为空；非空 = 文案表缺键，需回给内容负责人）。"""
        return sorted(set(self._missing))

    @property
    def json_load_error(self) -> Optional[str]:
        return self._load_error

    def _json_override_keys(self) -> Iterable[str]:
        return _OVERRIDE_PATHS.keys()


#: `ID -> JSON 路径`（与 `tools/gen_copy_text.py` 的 OVERRIDES / JSON_ONLY 同口径）
_OVERRIDE_PATHS: Dict[str, Tuple[Any, ...]] = {
    "s.end.plain.tips": ("plain_tips", "text"),
    "s.end.selfcare.tips": ("down_tips", "text"),
    "s.end.selfcare.title": ("self_care_page", "title"),
    "s.end.selfcare.body": ("self_care_page", "body"),
    "s.end.selfcare.action.treehole": ("self_care_page", "treehole_action"),
    "s.end.selfcare.action.close": ("self_care_page", "close_action"),
    "s.end.selfcare.hotline.title": ("self_care_page", "hotline_title"),
    "s.end.selfcare.hotline.body": ("self_care_page", "hotline_line"),
    "s.end.happy.title": ("happy_end", "title"),
    "s.end.happy.body": ("happy_end", "body"),
    "s.end.help.title": ("help_sent", "title"),
    "s.end.help.body": ("help_sent", "body"),
    "s.revoke.badge.shared": ("revoke", "badge_shared"),
    "s.revoke.badge.revoked": ("revoke", "badge_revoked"),
    "s.revoke.entry.action": ("revoke", "entry_action"),
    "s.revoke.entry.action.revoked": ("revoke", "entry_action_revoked"),
    "s.revoke.entry.hint": ("revoke", "entry_hint"),
    "s.revoke.confirm.title": ("revoke", "confirm_title"),
    "s.revoke.confirm.body": ("revoke", "confirm_body"),
    "s.revoke.confirm.irreversible": ("revoke", "confirm_irreversible"),
    "s.revoke.confirm.keepNote": ("revoke", "confirm_keep_note"),
    "s.revoke.confirm.action.ok": ("revoke", "confirm_ok"),
    "s.revoke.confirm.action.cancel": ("revoke", "confirm_cancel"),
    "s.revoke.toast.done": ("revoke", "toast_done"),
    "s.revoke.toast.doneNote": ("revoke", "toast_done_note"),
    "s.revoke.toast.failed": ("revoke", "toast_failed"),
    "s.revoke.toast.alreadyRevoked": ("revoke", "toast_already_revoked"),
    "s.revoke.toast.notShared": ("revoke", "toast_not_shared"),
    "s.revoke.after.note": ("revoke", "after_note"),
    "s.revoke.after.relink": ("revoke", "after_relink"),
    "s.revoke.error.1002": ("revoke", "errors", "1002"),
    "s.revoke.error.2002": ("revoke", "errors", "2002"),
    "s.revoke.error.2001.notShared": ("revoke", "errors", "2001_not_shared"),
    "s.revoke.error.2001.restore": ("revoke", "errors", "2001_restore"),
    "s.revoke.error.network": ("revoke", "errors", "network"),
    "s.end.revoked.title": ("revoke", "end_page", "title"),
    "s.end.revoked.body": ("revoke", "end_page", "body"),
    "s.end.revoked.reassure": ("revoke", "end_page", "reassure"),
    "s.end.revoked.action.back": ("revoke", "end_page", "back_action"),
    "s.end.revoked.action.close": ("revoke", "end_page", "close_action"),
    "s.end.revoked.footer": ("revoke", "end_page", "footer"),
    "s.end.revoked.hotline": ("revoke", "end_page", "hotline"),
    "s.q25.disclosure.anonymous": ("disclosure", "q25_anonymous"),
    "s.q25.disclosure.materialOnly": ("disclosure", "q25_material_only"),
    "s.q25.sensitive.notice": ("disclosure", "q25_sensitive"),
    "c.error.1001": ("errors", "1001"),
    "c.error.1002": ("errors", "1002"),
    "c.error.2001": ("errors", "2001"),
    "c.error.2002": ("errors", "2002"),
    "c.error.3001": ("errors", "3001"),
    "c.error.4001": ("errors", "4001"),
    "c.error.network": ("errors", "network"),
    "c.hotline.national.name": ("hotlines", 0, "label"),
    "c.hotline.national.number": ("hotlines", 0, "number"),
    "c.hotline.beijing.name": ("hotlines", 1, "label"),
    "c.hotline.beijing.number": ("hotlines", 1, "number"),
    "c.hotline.emergency.name": ("hotlines", 2, "label"),
    "c.hotline.emergency.number": ("hotlines", 2, "number"),
    "c.hotline.line": ("self_care_page", "hotline_line"),
}


def _walk(node: Any, path: Tuple[Any, ...]) -> Any:
    current = node
    for step in path:
        try:
            current = current[step]
        except (KeyError, IndexError, TypeError):
            return None
    return current


#: 全局文案表（双端都可 import；**只读**）
COPY = CopyTable()
