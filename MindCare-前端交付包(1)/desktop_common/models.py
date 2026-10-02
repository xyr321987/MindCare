"""与契约一致的轻量数据类（`docs/UI约定.md` §1 的 `models.py`，可选模块）。

刻意保持"薄"：**只做字段承载，不做业务规则**（业务规则在服务端）。
所有 `from_api` 工厂对缺失字段宽容（服务端多给字段不报错，少给字段用默认值），
这样契约追加字段时客户端不会崩。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "StudentProfile", "LoginResult", "TreeholeEntry", "SubmissionBrief",
    "ProfileDay", "Tip", "SubmissionResult",
    "TriageItem", "StudentToday", "RESULT_SCENES",
]

#: 契约 v1.0 `enums.result_scene`（**穷举 4 个值**，UI 必须逐一映射）。
#: v1.1 才登记的第 5 个值随那次降级一并移出（对应接口不在 v1.0 的 11 个端点里）。
RESULT_SCENES = ("happy_end", "plain_tips", "help_sent", "self_care")


def _get(data: Optional[dict], key: str, default: Any = None) -> Any:
    if not isinstance(data, dict):
        return default
    value = data.get(key)
    return default if value is None else value


@dataclass(frozen=True)
class StudentProfile:
    """`login.data.profile`。"""

    id: str = ""
    name: str = ""
    class_name: Optional[str] = None
    role: str = "student"

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "StudentProfile":
        return cls(
            id=str(_get(data, "id", "")),
            name=str(_get(data, "name", "")),
            class_name=_get(data, "class_name"),
            role=str(_get(data, "role", "student")),
        )


@dataclass(frozen=True)
class LoginResult:
    """`POST /auth/login` 的 `data`。"""

    token: str = ""
    expires_in: int = 0
    profile: StudentProfile = field(default_factory=StudentProfile)

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "LoginResult":
        return cls(
            token=str(_get(data, "token", "")),
            expires_in=int(_get(data, "expires_in", 0) or 0),
            profile=StudentProfile.from_api(_get(data, "profile", {})),
        )


@dataclass(frozen=True)
class TreeholeEntry:
    """`GET /treehole/entries` 的条目（**无任何可见性字段** —— L0 绝对私密）。"""

    entry_id: str = ""
    ts: str = ""
    content: str = ""
    mood_tag: Optional[str] = None

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "TreeholeEntry":
        return cls(
            entry_id=str(_get(data, "entry_id", "")),
            ts=str(_get(data, "ts", "")),
            content=str(_get(data, "content", "")),
            mood_tag=_get(data, "mood_tag"),
        )


@dataclass(frozen=True)
class SubmissionBrief:
    """`GET /profile/me` 的 `submissions[]`。

    ⚠️ v1.0 契约响应**不含** `consent_share`（这是 v1.0 的既有约束，不是 bug）。
    因此这里只承载契约给的 6 个字段；"这次有没有请求老师帮助"直接用
    `request_help` 表达（契约强制 `consent_share == request_help`），
    见 `student_desktop.ui.profile` 的说明。
    """

    record_id: str = ""
    ts: str = ""
    mood: str = ""
    cause_category: Optional[str] = None
    detail: Optional[str] = None
    request_help: bool = False

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "SubmissionBrief":
        return cls(
            record_id=str(_get(data, "record_id", "")),
            ts=str(_get(data, "ts", "")),
            mood=str(_get(data, "mood", "")),
            cause_category=_get(data, "cause_category"),
            detail=_get(data, "detail"),
            request_help=bool(_get(data, "request_help", False)),
        )


@dataclass(frozen=True)
class ProfileDay:
    """`GET /profile/me?date=` 的 `data`。"""

    date: str = ""
    submissions: List[SubmissionBrief] = field(default_factory=list)
    treehole: List[TreeholeEntry] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "ProfileDay":
        return cls(
            date=str(_get(data, "date", "")),
            submissions=[SubmissionBrief.from_api(x) for x in (_get(data, "submissions", []) or [])],
            treehole=[TreeholeEntry.from_api(x) for x in (_get(data, "treehole", []) or [])],
        )


@dataclass(frozen=True)
class Tip:
    """`GET /tips` / `submit_questionnaire.data.tips`。"""

    scene: str = ""
    text: str = ""
    treehole_entry: bool = False

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "Tip":
        return cls(
            scene=str(_get(data, "scene", "")),
            text=str(_get(data, "text", "")),
            treehole_entry=bool(_get(data, "treehole_entry", False)),
        )


@dataclass(frozen=True)
class SubmissionResult:
    """`POST /questionnaire/submissions` 的 `data`。"""

    record_id: str = ""
    date: str = ""
    result_scene: str = ""
    tip: Optional[Tip] = None

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "SubmissionResult":
        tips = _get(data, "tips")
        return cls(
            record_id=str(_get(data, "record_id", "")),
            date=str(_get(data, "date", "")),
            result_scene=str(_get(data, "result_scene", "")),
            tip=Tip.from_api(tips) if isinstance(tips, dict) else None,
        )


@dataclass(frozen=True)
class TriageItem:
    """`GET /triage/list` 的 `items[]`（教师端；列表**不含正文**）。"""

    student_id: str = ""
    name: str = ""
    class_name: str = ""
    priority: int = 3
    flags: Dict[str, Any] = field(default_factory=dict)
    last_active_ts: Optional[str] = None
    last_changed_ts: Optional[str] = None
    masked: bool = True

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "TriageItem":
        return cls(
            student_id=str(_get(data, "student_id", "")),
            name=str(_get(data, "name", "")),
            class_name=str(_get(data, "class_name", "")),
            priority=int(_get(data, "priority", 3) or 3),
            flags=dict(_get(data, "flags", {}) or {}),
            last_active_ts=_get(data, "last_active_ts"),
            last_changed_ts=_get(data, "last_changed_ts"),
            masked=bool(_get(data, "masked", True)),
        )


@dataclass(frozen=True)
class StudentToday:
    """`GET /triage/students/{id}/today`（教师端）。

    ⚠️ 详情页用 `has_shared_records`，**不要复用** `/triage/list` 的 `masked`
    （契约 §2.10 命名修正：同名异义）。
    """

    student_id: str = ""
    date: str = ""
    mood_latest: Optional[str] = None
    submission_count_today: int = 0
    pending_help: bool = False
    alert: Optional[dict] = None
    shared_records: List[dict] = field(default_factory=list)
    has_shared_records: bool = False

    @classmethod
    def from_api(cls, data: Optional[dict]) -> "StudentToday":
        return cls(
            student_id=str(_get(data, "student_id", "")),
            date=str(_get(data, "date", "")),
            mood_latest=_get(data, "mood_latest"),
            submission_count_today=int(_get(data, "submission_count_today", 0) or 0),
            pending_help=bool(_get(data, "pending_help", False)),
            alert=_get(data, "alert"),
            shared_records=list(_get(data, "shared_records", []) or []),
            has_shared_records=bool(_get(data, "has_shared_records", False)),
        )
