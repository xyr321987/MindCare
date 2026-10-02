# -*- coding: utf-8 -*-
"""轻量数据模型：只做字段承载，不做业务规则（业务规则在服务端/适配器）。

既有分诊接口的模型用 `from_api` 从信封 data 构造，对缺字段宽容（服务端多给不报错，
少给走默认值）；新功能（预约/预警/回复/导出行）的字段即"协议提案"的数据形状，
适配器产出这些模型，见 docs/教师端新增接口协议提案.md。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ============================================================ 既有冻结接口的模型

@dataclass
class TriageFlags:
    has_history: bool = False
    recent_down_count: int = 0
    window_size: int = 0
    pending_help: bool = False

    @classmethod
    def from_api(cls, raw: Optional[dict]) -> "TriageFlags":
        raw = raw or {}
        return cls(
            has_history=bool(raw.get("has_history")),
            recent_down_count=int(raw.get("recent_down_count") or 0),
            window_size=int(raw.get("window_size") or 0),
            pending_help=bool(raw.get("pending_help")),
        )


@dataclass
class TriageItem:
    """GET /triage/list 的一条（契约 §2.9，恰好这些字段，没有正文）。"""
    student_id: str
    name: str
    class_name: str = ""
    priority: int = 3
    flags: TriageFlags = field(default_factory=TriageFlags)
    last_active_ts: Optional[str] = None
    masked: bool = True
    #: 抽屉数据懒加载缓存（非接口字段；UI 内部状态）
    today: Optional["StudentToday"] = None

    @classmethod
    def from_api(cls, raw: dict) -> "TriageItem":
        return cls(
            student_id=str(raw.get("student_id", "")),
            name=str(raw.get("name", "")),
            class_name=str(raw.get("class_name") or ""),
            priority=int(raw.get("priority") or 3),
            flags=TriageFlags.from_api(raw.get("flags")),
            last_active_ts=raw.get("last_active_ts"),
            masked=bool(raw.get("masked", True)),
        )


@dataclass
class Ticket:
    ticket_id: str
    status: str = "pending"      # pending | accepted | done


@dataclass
class SharedRecord:
    record_id: str
    ts: str
    mood: Optional[str] = None
    cause_category: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class Alert:
    level: int = 1
    rule: str = "history_plus_recent_down"
    recent_down_count: int = 0
    window_size: int = 0


@dataclass
class StudentToday:
    """GET /triage/students/{id}/today（契约 §2.10）。"""
    student_id: str
    date: str = ""
    mood_latest: Optional[str] = None
    submission_count_today: int = 0
    pending_help: bool = False
    alert: Optional[Alert] = None
    shared_records: List[SharedRecord] = field(default_factory=list)
    shared_treehole: List[dict] = field(default_factory=list)
    has_shared_records: bool = False
    masked: bool = True
    #: v1.1 追加件：today 返回该生待处理工单（消除契约缺口 G-1）
    tickets: List[Ticket] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict) -> "StudentToday":
        alert_raw = raw.get("alert")
        alert = Alert(
            level=int(alert_raw.get("level", 1)),
            rule=str(alert_raw.get("rule", "history_plus_recent_down")),
            recent_down_count=int(alert_raw.get("recent_down_count") or 0),
            window_size=int(alert_raw.get("window_size") or 0),
        ) if alert_raw else None
        return cls(
            student_id=str(raw.get("student_id", "")),
            date=str(raw.get("date", "")),
            mood_latest=raw.get("mood_latest"),
            submission_count_today=int(raw.get("submission_count_today") or 0),
            pending_help=bool(raw.get("pending_help")),
            alert=alert,
            shared_records=[
                SharedRecord(
                    record_id=str(r.get("record_id", "")),
                    ts=str(r.get("ts", "")),
                    mood=r.get("mood"),
                    cause_category=r.get("cause_category"),
                    detail=r.get("detail"),
                ) for r in (raw.get("shared_records") or [])
            ],
            shared_treehole=list(raw.get("shared_treehole") or []),
            has_shared_records=bool(raw.get("has_shared_records", False)),
            masked=bool(raw.get("masked", True)),
            tickets=[
                Ticket(ticket_id=str(t.get("ticket_id", "")), status=str(t.get("status", "pending")))
                for t in (raw.get("tickets") or [])
            ],
        )


# ============================================================ 新功能模型（协议提案形状）

@dataclass
class Appointment:
    """预约（预约数据库 API 到位后字段以对方为准；本形状写入协议提案）。

    单线流程状态：pending_request（待预约，来自求助工单）→ scheduled（已预约）
    → done（已完成）；调度升级后新增 cancelled（已取消）/ no_show（爽约）。
    """
    appointment_id: str
    student_id: str
    student_name: str
    class_name: str = ""
    ticket_id: str = ""
    scheduled_at: Optional[str] = None    # ISO8601；None=还在待预约
    status: str = "scheduled"             # scheduled | done | cancelled | no_show | pending_request
    note: Optional[str] = None
    created_at: Optional[str] = None
    help_text_preview: str = ""           # 求助关联说明（不含问卷正文，仅"发起了求助"）
    questionnaire: Optional[List[dict]] = None  # 共享问卷正文（share_questionnaire=true 且当天）
    treehole: Optional[List[dict]] = None       # 共享树洞正文（share_treehole=true 且当天）
    # ---- 调度升级（多教师/多咨询室/取消改期爽约留痕）----
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    cancel_reason: Optional[str] = None
    rescheduled_from: Optional[str] = None
    no_show_note: Optional[str] = None


@dataclass
class WaitlistEntry:
    """候补队列条目（学生/工单锚定到某时段，取消/爽约后自动递补）。"""
    wait_id: str
    student_id: str
    student_name: str = ""
    class_name: str = ""
    ticket_id: str = ""
    year: str = ""
    month: str = ""
    day: str = ""
    period: str = ""
    teacher_id: Optional[str] = None
    room_id: Optional[str] = None
    status: str = "waiting"                # waiting | filled | cancelled | expired
    filled_apt_id: Optional[str] = None
    reason: Optional[str] = None
    created_ts: Optional[str] = None


@dataclass
class WarningRecord:
    """连续沮丧不求助预警。

    口径（用户确认）：同一学生连续 mood=down 且 request_help=false 的提交，
    满 3 次触发；中途选其他分支（happy/plain/down+求助）计数清零；
    老师约谈后手动消除也清零。真值由服务端扫描计算，教师端只展示与消除。
    """
    warning_id: str
    student_id: str
    student_name: str
    class_name: str = ""
    rule: str = "silent_down_streak"
    streak_count: int = 3
    latest_ts: Optional[str] = None
    status: str = "active"                # active | dismissed
    dismissed_at: Optional[str] = None
    dismiss_note: Optional[str] = None


@dataclass
class ReplyEntry:
    """自定义回复自由条目（老师任意新建；用场景标签关联学生端结束页）。"""
    reply_id: str
    text: str
    scenes: List[str] = field(default_factory=list)   # happy_end/plain_tips/help_sent/self_care
    enabled: bool = True
    updated_at: Optional[str] = None


@dataclass
class ExportRow:
    """导出汇总表的一行 —— **零正文**（用户确认：不含任何 detail/plain_note/树洞）。"""
    student_id: str
    name: str
    class_name: str
    date: str
    ts: str
    mood: str
    cause_category: Optional[str] = None
    request_help: bool = False
    consent_share: bool = False
    ticket_status: str = ""               # pending/accepted/done/空

    #: 导出列定义（顺序即 Excel 列顺序；改列只改这里）
    COLUMNS = [
        ("student_id", "学号"), ("name", "姓名"), ("class_name", "班级"),
        ("date", "日期"), ("ts", "提交时间"), ("mood", "心情"),
        ("cause_category", "原因分类"), ("request_help", "是否求助"),
        ("consent_share", "是否授权共享"), ("ticket_status", "工单状态"),
    ]
