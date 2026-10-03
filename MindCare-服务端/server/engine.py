"""业务引擎 —— 契约 §4/§5/§6/§7 的服务端实现（纯 stdlib，无框架）。

本模块只做业务规则 + 数据落库，不碰 HTTP；HTTP 层见 `httpd.py`。
所有 handler 返回已解包的 `data` dict，失败抛 `ApiError`。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from . import schedule as sched
from .db import Database, hash_password, verify_password
from .teacher_store import PRESET_TEACHER_ID

# --------------------------------------------------------------------------- 常量
EXPIRES_SECONDS = 43200  # 12h（契约 §2.1）

#: 错误码（契约 v1.0 + 无新增码；HTTP 状态映射见 httpd.py）
HTTP_STATUS = {
    1001: 401, 1002: 403, 2001: 400, 2002: 404, 3001: 500, 4001: 429,
}

MOODS = ("happy", "plain", "down")
CAUSES = ("study", "relationship", "family")
RESULT_SCENES = ("happy_end", "plain_tips", "help_sent", "self_care")

#: `result_scene`（回复库标签）→ `tips` 表默认 scene 键。
#: `happy_end` / `help_sent` 没有默认小贴士，只有教师回复库能覆盖。
_RESULT_TO_TIPS_SCENE = {
    "plain_tips": "plain",
    "self_care": "down",
}
#: `tips` 表 scene 键 → `result_scene`（`GET /tips?scene=plain|down` 反向映射）。
_TIPS_SCENE_TO_RESULT = {
    "plain": "plain_tips",
    "down": "self_care",
}

#: 分诊参数（契约 §2.9 params）
WINDOW_N = 3
THRESHOLD_K = 2

#: 预警规则参数（决策 7/§8）
WARNING_STREAK = 3


class ApiError(Exception):
    def __init__(self, code: int, message: str, field: Optional[str] = None) -> None:
        self.code = code
        self.message = message
        self.field = field
        super().__init__(f"[{code}] {message}")


def _err(code: int, message: str, field: Optional[str] = None) -> ApiError:
    return ApiError(code, message, field)


def new_id(prefix: str) -> str:
    return f"{prefix}{os.urandom(6).hex()}"


#: 布尔字段：SQLite 存 INTEGER 0/1，响应需转 JSON boolean（契约要求 true/false）
_BOOL_FIELDS = {"request_help", "consent_share", "has_mental_history",
                "share_questionnaire", "share_treehole", "active", "enabled",
                "treehole_entry"}


def _boolify(d: dict) -> dict:
    for k in list(d.keys()):
        if k in _BOOL_FIELDS and isinstance(d[k], int):
            d[k] = bool(d[k])
    return d


def _validate_date(date: str) -> None:
    if not date or len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise _err(2001, "字段 date 校验失败：格式必须是 YYYY-MM-DD", "date")
    try:
        y, m, d = int(date[:4]), int(date[5:7]), int(date[8:10])
    except ValueError:
        raise _err(2001, "字段 date 校验失败：格式必须是 YYYY-MM-DD", "date")
    if sched.weekday_from_date(y, m, d) < 0:
        raise _err(2001, "字段 date 校验失败：日期不存在", "date")


#: 问卷提交限流（契约 §2.3：同一 token 1 分钟 >10 次 → 4001）
_RATE_WINDOW = 60.0
_RATE_LIMIT = 10
_rate_log: Dict[str, list] = {}


# =========================================================================== 认证
def register(db: Database, body: dict) -> dict:
    """POST /auth/register（公共）。注册即建 students+credentials（单事务，R2）。"""
    class_name = str(body.get("class_name") or "").strip()
    name = str(body.get("name") or "").strip()
    seat_no = str(body.get("seat_no") or "").strip()
    password = str(body.get("password") or "")

    if not class_name:
        raise _err(2001, "字段 class_name 校验失败：必须是非空字符串", "class_name")
    if not name:
        raise _err(2001, "字段 name 校验失败：必须是非空字符串", "name")
    if not seat_no:
        raise _err(2001, "字段 seat_no 校验失败：必须是非空字符串", "seat_no")
    if len(seat_no) > 32:
        raise _err(2001, "字段 seat_no 校验失败：长度不得超过 32", "seat_no")
    if len(password) < 4:
        raise _err(2001, "字段 password 校验失败：长度至少 4 位", "password")

    student_id = "stu_" + seat_no
    existing = db.query_one("SELECT 1 FROM students WHERE seat_no=?", (seat_no,))
    if existing:
        raise _err(2001, "号次已注册", "seat_no")

    now = sched.now_iso()
    salt, digest = hash_password(password)

    def _do(cur) -> None:
        cur.execute(
            "INSERT INTO students(student_id, seat_no, name, class_name, has_mental_history, created_ts)"
            " VALUES(?,?,?,?,0,?)",
            (student_id, seat_no, name, class_name, now),
        )
        cur.execute(
            "INSERT INTO credentials(student_id, password_hash, salt, updated_ts) VALUES(?,?,?,?)",
            (student_id, digest, salt, now),
        )

    db.transaction(_do)
    return _issue_session(db, "student", student_id)


def login(db: Database, body: dict) -> dict:
    """POST /auth/login（公共）。学生：号次+密码；教师：工号+口令。"""
    role = str(body.get("role") or "")
    raw_id = str(body.get("id") or "").strip()
    password = str(body.get("password") or "")

    if role == "student":
        seat_no = raw_id
        row = db.query_one("SELECT * FROM students WHERE seat_no=?", (seat_no,))
        if not row:
            raise _err(2002, "学生不存在", "id")
        cred = db.query_one("SELECT * FROM credentials WHERE student_id=?", (row["student_id"],))
        if not cred or not verify_password(password, cred["salt"], cred["password_hash"]):
            raise _err(1001, "密码错误", "password")
        return _issue_session(db, "student", row["student_id"])
    if role == "teacher":
        row = db.teacher.get(raw_id)
        if not row:
            raise _err(2002, "教师不存在", "id")
        if not db.teacher.verify_password(row["teacher_id"], password):
            raise _err(1001, "密码错误", "password")
        return _issue_session(db, "teacher", row["teacher_id"])
    raise _err(2001, "字段 role 校验失败：只能是 student 或 teacher", "role")


def _issue_session(db: Database, role: str, subject_id: str) -> dict:
    expires_at = time.time() + EXPIRES_SECONDS
    token = db.create_session(role, subject_id, expires_at)
    profile = _profile(db, role, subject_id)
    return {"token": token, "expires_in": EXPIRES_SECONDS, "profile": profile}


def _profile(db: Database, role: str, subject_id: str) -> dict:
    if role == "student":
        r = db.query_one("SELECT * FROM students WHERE student_id=?", (subject_id,))
        return {"id": r["student_id"], "name": r["name"],
                "class_name": r["class_name"], "role": "student"}
    r = db.teacher.get(subject_id)
    return {"id": r["teacher_id"], "name": r["name"],
            "class_name": None, "role": "teacher"}


def resolve_session(db: Database, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    row = db.get_session(token)
    if not row:
        return None
    if time.time() >= float(row["expires_at"]):
        db.delete_session(token)
        return None
    return row


# =========================================================================== 问卷
def _validate_submission(body: dict) -> dict:
    mood = body.get("mood")
    if mood not in MOODS:
        raise _err(2001, "字段 mood 校验失败：必须是 happy/plain/down", "mood")
    plain_note = body.get("plain_note")
    cause_category = body.get("cause_category")
    detail = body.get("detail")
    request_help = bool(body.get("request_help"))
    consent_share = bool(body.get("consent_share"))
    consent_ts = body.get("consent_ts")
    record_id = str(body.get("record_id") or "").strip()

    if not record_id:
        raise _err(2001, "字段 record_id 校验失败：必须是非空字符串", "record_id")
    if consent_share != request_help:
        raise _err(2001, "consent_share 必须与 request_help 同值", "consent_share")
    if request_help and not consent_ts:
        raise _err(2001, "request_help=true 时 consent_ts 必填", "consent_ts")

    if mood == "happy":
        if plain_note or cause_category or detail or request_help:
            raise _err(2001, "mood=happy 时不得携带原因/详情/求助", "mood")
    elif mood == "plain":
        filled = bool(plain_note)
        if filled:
            if not cause_category:
                raise _err(2001, "字段 cause_category 校验失败：必填", "cause_category")
            if not detail:
                raise _err(2001, "字段 detail 校验失败：必须是非空字符串", "detail")
        else:
            if cause_category or detail or request_help:
                raise _err(2001, "mood=plain 未填原因时不得携带原因/详情/求助", "mood")
    else:  # down
        if not cause_category:
            raise _err(2001, "字段 cause_category 校验失败：必填", "cause_category")
        if not detail:
            raise _err(2001, "字段 detail 校验失败：必须是非空字符串", "detail")

    if cause_category is not None and cause_category not in CAUSES:
        raise _err(2001, "字段 cause_category 校验失败：study/relationship/family", "cause_category")
    return {
        "record_id": record_id, "mood": mood, "plain_note": plain_note,
        "cause_category": cause_category, "detail": detail,
        "request_help": request_help, "consent_share": consent_share, "consent_ts": consent_ts,
    }


def submit_questionnaire(db: Database, student_id: str, body: dict) -> dict:
    """POST /questionnaire/submissions（学生，幂等）。"""
    data = _validate_submission(body)
    record_id = data["record_id"]

    existing = db.query_one(
        "SELECT * FROM questionnaire_submissions WHERE record_id=?", (record_id,)
    )
    if existing:
        return _submission_result(db, existing)

    now_ts = time.time()
    recent = [t for t in _rate_log.get(student_id, []) if now_ts - t < _RATE_WINDOW]
    if len(recent) >= _RATE_LIMIT:
        raise _err(4001, "提交太频繁，请稍后再试")
    recent.append(now_ts)
    _rate_log[student_id] = recent

    now = sched.now_iso()
    today = sched.today_str()
    db.execute(
        "INSERT INTO questionnaire_submissions"
        "(record_id, student_id, ts, date, mood, plain_note, cause_category, detail,"
        " request_help, consent_share, consent_ts)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (record_id, student_id, now, today, data["mood"], data["plain_note"],
         data["cause_category"], data["detail"], int(data["request_help"]),
         int(data["consent_share"]), data["consent_ts"]),
    )
    db.commit()

    if data["request_help"]:
        _create_ticket(db, student_id, record_id)

    _scan_warning(db, student_id)

    row = db.query_one("SELECT * FROM questionnaire_submissions WHERE record_id=?", (record_id,))
    return _submission_result(db, row)


def _create_ticket(db: Database, student_id: str, source_record_id: str) -> str:
    now = sched.now_iso()
    ticket_id = new_id("tkt_")
    db.execute(
        "INSERT INTO tickets(ticket_id, student_id, source_record_id, status, created_ts, updated_ts)"
        " VALUES(?,?,?,?,?,?)",
        (ticket_id, student_id, source_record_id, "pending", now, now),
    )
    db.commit()
    return ticket_id


def _result_scene(data: dict) -> str:
    if data["mood"] == "happy":
        return "happy_end"
    if data["mood"] == "plain":
        return "plain_tips"
    return "help_sent" if data["request_help"] else "self_care"


def _tip_for_scene(db: Database, result_scene: str) -> dict:
    """tips 合并（决策 6 / R18）：教师启用回复（按 `result_scene` 打标）> tips 表默认。

    回复库（`replies`）的 `scenes` 与教师端 `RESULT_SCENES` 对齐（`happy_end` /
    `plain_tips` / `help_sent` / `self_care`）；默认文案（`tips` 表）用
    `plain` / `down` 两个键。两者是**两套枚举**：这里先按 `result_scene` 查回复，
    命中则覆盖；否则把 `result_scene` 映射回 tips 键取默认。
    """
    rows = db.query(
        "SELECT * FROM replies WHERE enabled=1 AND scenes LIKE ? ORDER BY updated_ts DESC LIMIT 1",
        (f'%"{result_scene}"%',),
    )
    if rows:
        return {"scene": result_scene, "text": rows[0]["text"], "treehole_entry": False}
    tip_key = _RESULT_TO_TIPS_SCENE.get(result_scene)
    if tip_key:
        t = db.query_one("SELECT * FROM tips WHERE scene=?", (tip_key,))
        if t:
            return {"scene": result_scene, "text": t["text"],
                    "treehole_entry": bool(t["treehole_entry"])}
    return {"scene": result_scene, "text": "", "treehole_entry": False}


def _submission_result(db: Database, row: dict) -> dict:
    scene = _result_scene(row)
    result = {"record_id": row["record_id"], "date": row["date"], "result_scene": scene}
    tip = _tip_for_scene(db, scene)
    if tip["text"]:
        result["tips"] = tip
    return result


def _scan_warning(db: Database, student_id: str) -> None:
    """预警扫描（决策 7/§8）：连续 down 且不求助满 3 → active；被其他分支打断 → 清零。"""
    rows = db.query(
        "SELECT mood, request_help FROM questionnaire_submissions WHERE student_id=?"
        " ORDER BY ts DESC, rowid DESC",
        (student_id,),
    )
    streak = 0
    for r in rows:
        if r["mood"] == "down" and not r["request_help"]:
            streak += 1
        else:
            break
    if streak >= WARNING_STREAK:
        active = db.query_one(
            "SELECT * FROM warnings WHERE student_id=? AND status='active'", (student_id,)
        )
        now = sched.now_iso()
        if active:
            db.execute(
                "UPDATE warnings SET streak_count=?, latest_ts=? WHERE warning_id=?",
                (streak, now, active["warning_id"]),
            )
        else:
            db.execute(
                "INSERT INTO warnings(warning_id, student_id, rule, streak_count, latest_ts, status, created_ts)"
                " VALUES(?,?,?,?,?,?,?)",
                (new_id("warn_"), student_id, "silent_down_streak", streak, now, "active", now),
            )
    else:
        db.execute(
            "DELETE FROM warnings WHERE student_id=? AND status='active'", (student_id,)
        )
    db.commit()


# =========================================================================== 档案
def my_profile(db: Database, student_id: str, date: str) -> dict:
    _validate_date(date)
    subs = db.query(
        "SELECT record_id, ts, mood, cause_category, detail, request_help"
        " FROM questionnaire_submissions WHERE student_id=? AND date=? ORDER BY ts",
        (student_id, date),
    )
    for s in subs:
        _boolify(s)
    tree = db.query(
        "SELECT entry_id, ts, content, mood_tag FROM treehole_entries WHERE student_id=? AND date=? ORDER BY ts",
        (student_id, date),
    )
    return {"date": date, "submissions": subs, "treehole": tree}


def my_dates(db: Database, student_id: str) -> dict:
    rows = db.query(
        "SELECT DISTINCT date FROM questionnaire_submissions WHERE student_id=? ORDER BY date DESC",
        (student_id,),
    )
    tree_dates = db.query(
        "SELECT DISTINCT date FROM treehole_entries WHERE student_id=? ORDER BY date DESC",
        (student_id,),
    )
    dates = sorted({r["date"] for r in rows} | {r["date"] for r in tree_dates}, reverse=True)
    return {"dates": dates}


def mood_range(db: Database, student_id: str, start: str, end: str) -> dict:
    """区间内每日情绪点（学生端「情绪可视化」）：每天取最新一次提交的 mood。"""
    _validate_date(start)
    _validate_date(end)
    if start > end:
        start, end = end, start
    rows = db.query(
        "SELECT date, mood FROM questionnaire_submissions"
        " WHERE student_id=? AND date>=? AND date<=?"
        " ORDER BY date, ts DESC, rowid DESC",
        (student_id, start, end),
    )
    by_day: dict = {}
    for r in rows:
        by_day.setdefault(r["date"], r["mood"])
    items = [{"date": d, "mood": m} for d, m in sorted(by_day.items())]
    return {"start": start, "end": end, "items": items}


# =========================================================================== 树洞
def create_treehole(db: Database, student_id: str, body: dict) -> dict:
    entry_id = str(body.get("entry_id") or "").strip()
    content = str(body.get("content") or "").strip()
    mood_tag = body.get("mood_tag")
    if not entry_id:
        raise _err(2001, "字段 entry_id 校验失败：必须是非空字符串", "entry_id")
    if not content:
        raise _err(2001, "字段 content 校验失败：必须是非空字符串", "content")
    existing = db.query_one("SELECT * FROM treehole_entries WHERE entry_id=?", (entry_id,))
    if existing:
        return {"entry_id": existing["entry_id"], "ts": existing["ts"]}
    now = sched.now_iso()
    today = sched.today_str()
    db.execute(
        "INSERT INTO treehole_entries(entry_id, student_id, ts, date, content, mood_tag)"
        " VALUES(?,?,?,?,?,?)",
        (entry_id, student_id, now, today, content, mood_tag),
    )
    db.commit()
    return {"entry_id": entry_id, "ts": now}


def my_treehole(db: Database, student_id: str, date: str) -> dict:
    _validate_date(date)
    rows = db.query(
        "SELECT entry_id, ts, content, mood_tag FROM treehole_entries WHERE student_id=? AND date=? ORDER BY ts",
        (student_id, date),
    )
    return {"date": date, "entries": rows}


def tips(db: Database, scene: str) -> dict:
    if scene not in ("plain", "down"):
        raise _err(2001, "字段 scene 校验失败：只能是 plain/down", "scene")
    result_scene = _TIPS_SCENE_TO_RESULT.get(scene)
    return _tip_for_scene(db, result_scene)


# =========================================================================== 预约（学生）
def create_appointment(db: Database, student_id: str, body: dict) -> dict:
    """POST /appointments（学生，幂等）。服务端派生格子信息，不信任客户端。"""
    apt_id = str(body.get("apt_id") or "").strip()
    if not apt_id:
        raise _err(2001, "字段 apt_id 校验失败：必须是非空字符串", "apt_id")
    existing = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
    if existing:
        return {"apt_id": existing["apt_id"], "created_ts": existing["created_ts"]}

    year, month, day = body.get("year"), body.get("month"), body.get("day")
    time_text = str(body.get("time") or "")
    period = _coerce_period(year, month, day, time_text, body.get("period"))
    slot = sched.slot_id(int(year), int(month), int(day), period)
    slot_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    # 学生可选老师 + 必选咨询室：做「教师 + 咨询室」双资源冲突检测；teacher_id/room_id 可空向后兼容
    teacher_id = body.get("teacher_id") or None
    if teacher_id and not db.teacher.get(str(teacher_id)):
        raise _err(2002, "教师不存在", "teacher_id")
    room_id = body.get("room_id") or None
    if room_id and not db.query_one("SELECT 1 FROM rooms WHERE room_id=?", (str(room_id),)):
        raise _err(2002, "咨询室不存在", "room_id")
    conflict = _conflict(db, slot, slot_date, str(period), teacher_id, room_id)
    if conflict:
        raise _err(2001, conflict, "slot")

    stu = db.query_one("SELECT * FROM students WHERE student_id=?", (student_id,))
    now = sched.now_iso()
    weekday = sched.weekday_from_date(int(year), int(month), int(day))
    db.execute(
        "INSERT INTO appointments"
        "(apt_id, student_id, teacher_id, room_id, name, class_name, year, month, day, period, weekday,"
        " time_start, time_end, slot, date, share_questionnaire, share_treehole, status, created_ts, updated_ts)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (apt_id, student_id, teacher_id, room_id, stu["name"], stu["class_name"], str(year), str(month), str(day),
         str(period), str(weekday), sched.period_start(period), sched.period_end(period),
         slot, slot_date, int(bool(body.get("share_questionnaire"))),
         int(bool(body.get("share_treehole"))), "scheduled", now, now),
    )
    db.commit()
    return {"apt_id": apt_id, "created_ts": now}


def _coerce_period(year, month, day, time_text, period_hint) -> int:
    try:
        y, m, d = int(year), int(month), int(day)
    except (TypeError, ValueError):
        raise _err(2001, "字段 year/month/day 校验失败：必须是数字", "year")
    if sched.weekday_from_date(y, m, d) < 0:
        raise _err(2001, "字段 day 校验失败：日期不存在", "day")
    period = None
    if period_hint is not None:
        try:
            p = int(period_hint)
            if sched.PERIOD_INDEX_MIN <= p <= sched.PERIOD_INDEX_MAX:
                period = p
        except (TypeError, ValueError):
            pass
    if period is None:
        period = sched.period_of_time(time_text)
    if period is None:
        raise _err(2001, "字段 time 校验失败：无法定位到节次", "time")
    return period


def available_teachers(db: Database, year, month, day, period) -> dict:
    """某时段的可预约老师（学生选老师用）。

    空闲判定（唯一事实源，复用 `_conflict` 的教师三路检查）：
    周期可用 + 无该教师同时段预约 + 无全局/个人停诊。
    """
    period = _coerce_period(year, month, day, None, period)
    slot = sched.slot_id(int(year), int(month), int(day), period)
    slot_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    items = []
    for t in db.teacher.list_all():
        conflict = _conflict(db, slot, slot_date, str(period), t["teacher_id"], None)
        items.append({
            "teacher_id": t["teacher_id"], "name": t["name"],
            "available": conflict is None,
        })
    return {"items": items}


def available_rooms(db: Database, year, month, day, period) -> dict:
    """某时段的可预约咨询室（学生必选咨询室用）。

    空闲判定（唯一事实源，复用 `_conflict` 的咨询室路）：
    启用中 + 无该咨询室同时段预约 + 无全局停诊。
    """
    period = _coerce_period(year, month, day, None, period)
    slot = sched.slot_id(int(year), int(month), int(day), period)
    slot_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    items = []
    for r in db.query("SELECT * FROM rooms ORDER BY created_ts"):
        conflict = _conflict(db, slot, slot_date, str(period), None, r["room_id"])
        items.append({
            "room_id": r["room_id"], "name": r["name"],
            "location": r.get("location"), "features": r.get("features"),
            "available": bool(r["active"]) and conflict is None,
        })
    return {"items": items}


def my_appointments(db: Database, student_id: str) -> dict:
    """GET /appointments/mine（学生）：读自己的预约。

    教师代订（`/db/write appointments.schedule`）也是写进同一张 `appointments`，
    这里把该生的 `scheduled` 预约连同 `slot` 一并返回，学生端课表据此把「老师
    帮我约的那一格」刷成已预约（问题 4：教师代订 → 学生端同步可见）。
    """
    rows = db.query(
        "SELECT apt_id, slot, status, year, month, day, period, time_start, time_end, created_ts"
        " FROM appointments WHERE student_id=? AND status='scheduled' ORDER BY created_ts DESC",
        (student_id,),
    )
    return {"items": [dict(r) for r in rows]}


def list_blocks(db: Database) -> dict:
    rows = db.query("SELECT * FROM blocks WHERE active=1")
    return {"slots": [r["slot"] for r in rows]}


def set_block(db: Database, operator: str, body: dict) -> dict:
    year, month, day = body.get("year"), body.get("month"), body.get("day")
    period = body.get("period")
    active = bool(body.get("active", True))
    reason = body.get("reason")
    teacher_id = body.get("teacher_id")  # None=全局停诊；有值=该教师个人停诊
    try:
        slot = sched.slot_id(int(year), int(month), int(day), int(period))
    except (TypeError, ValueError):
        raise _err(2001, "字段 year/month/day/period 校验失败：必须是数字", "period")
    if sched.weekday_from_date(int(year), int(month), int(day)) < 0:
        raise _err(2001, "字段 day 校验失败：日期不存在", "day")
    now = sched.now_iso()
    existing = db.query_one("SELECT * FROM blocks WHERE slot=?", (slot,))
    if existing:
        db.execute(
            "UPDATE blocks SET active=?, reason=?, operator=?, teacher_id=?, created_ts=? WHERE slot=?",
            (int(active), reason, operator, teacher_id, now, slot),
        )
    else:
        db.execute(
            "INSERT INTO blocks(blk_id, slot, year, month, day, period, active, reason, operator, teacher_id, created_ts)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("blk_"), slot, str(year), str(month), str(day), str(period),
             int(active), reason, operator, teacher_id, now),
        )
    db.commit()
    row = db.query_one("SELECT * FROM blocks WHERE slot=?", (slot,))
    return row


# =========================================================================== 候补（waitlist）与教师
def join_waitlist(db: Database, student_id: str, body: dict) -> dict:
    """学生加入候补（幂等）。仅当目标时段已被预约时才允许加入。"""
    wait_id = str(body.get("wait_id") or "").strip()
    if not wait_id:
        raise _err(2001, "字段 wait_id 校验失败：必须是非空字符串", "wait_id")
    existing = db.query_one("SELECT * FROM waitlist WHERE wait_id=?", (wait_id,))
    if existing:
        return {"wait_id": existing["wait_id"], "created_ts": existing["created_ts"]}

    year, month, day = body.get("year"), body.get("month"), body.get("day")
    time_text = str(body.get("time") or "")
    period = _coerce_period(year, month, day, time_text, body.get("period"))
    slot = sched.slot_id(int(year), int(month), int(day), period)
    occupied = db.query_one(
        "SELECT 1 FROM appointments WHERE slot=? AND status='scheduled'", (slot,))
    if not occupied:
        raise _err(2001, "该时段当前可约，请直接预约", "slot")
    _require_student(db, student_id)
    now = sched.now_iso()
    db.execute(
        "INSERT INTO waitlist(wait_id, student_id, ticket_id, year, month, day, period,"
        " teacher_id, room_id, status, reason, created_ts, updated_ts)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (wait_id, student_id, body.get("ticket_id"), str(year), str(month), str(day),
         str(period), body.get("teacher_id"), body.get("room_id"), "waiting",
         body.get("reason"), now, now),
    )
    db.commit()
    return {"wait_id": wait_id, "status": "waiting", "created_ts": now}


def my_waitlist(db: Database, student_id: str) -> dict:
    rows = db.query(
        "SELECT * FROM waitlist WHERE student_id=? ORDER BY created_ts DESC", (student_id,))
    return {"items": [dict(r) for r in rows]}


def _promote_waitlist(db: Database, year, month, day, period,
                      teacher_id, room_id, actor: str) -> Optional[str]:
    """取消/爽约/改期释放 slot 后，把最早匹配的候补递补为预约（FIFO，单槽单补）。

    **不 commit**：由调用方（cancel/no_show/reschedule）在同一事务内 commit，保证
    「槽释放 + 递补」原子性（对齐 SQLite WAL 单写者纪律）。返回新预约 id 或 None。
    """
    rows = db.query(
        "SELECT * FROM waitlist WHERE year=? AND month=? AND day=? AND period=?"
        " AND status='waiting' ORDER BY created_ts",
        (str(year), str(month), str(day), str(period)),
    )
    candidate = None
    for w in rows:
        if w["teacher_id"] and teacher_id and w["teacher_id"] != teacher_id:
            continue
        if w["room_id"] and room_id and w["room_id"] != room_id:
            continue
        candidate = w
        break
    if not candidate:
        return None

    slot = sched.slot_id(int(year), int(month), int(day), int(period))
    dup = db.query_one(
        "SELECT 1 FROM appointments WHERE student_id=? AND slot=? AND status='scheduled'",
        (candidate["student_id"], slot))
    if dup:  # 保守：该生此时段已有预约则不递补（防止重复预约）
        return None

    stu = _require_student(db, candidate["student_id"])
    apt_id = new_id("apt_")
    period_i = int(period)
    weekday = sched.weekday_from_date(int(year), int(month), int(day))
    t_id = candidate["teacher_id"] or teacher_id
    r_id = candidate["room_id"] or room_id
    now = sched.now_iso()
    db.execute(
        "INSERT INTO appointments"
        "(apt_id, student_id, ticket_id, teacher_id, room_id, name, class_name,"
        " year, month, day, period, weekday, time_start, time_end, slot, date,"
        " share_questionnaire, share_treehole, status, note, created_ts, updated_ts)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (apt_id, candidate["student_id"], candidate["ticket_id"], t_id, r_id,
         stu["name"], stu["class_name"], str(year), str(month), str(day), str(period_i),
         str(weekday), sched.period_start(period_i), sched.period_end(period_i), slot,
         f"{int(year):04d}-{int(month):02d}-{int(day):02d}", 1, 0, "scheduled",
         "候补递补", now, now),
    )
    if candidate["ticket_id"]:
        db.execute("UPDATE tickets SET status='accepted', updated_ts=? WHERE ticket_id=?",
                   (now, candidate["ticket_id"]))
    db.execute("UPDATE waitlist SET status='filled', filled_apt_id=?, updated_ts=? WHERE wait_id=?",
               (apt_id, now, candidate["wait_id"]))
    _log_event(db, apt_id, actor, "scheduled", "候补自动递补")
    return apt_id


def teacher_calendar(db: Database, teacher_id: str, start: str, end: str) -> dict:
    """某教师的个人日历：区间内预约 + 停诊（含全局）+ 周期可用性。"""
    rows = db.query(
        "SELECT * FROM appointments WHERE teacher_id=? AND date>=? AND date<=?"
        " ORDER BY date, period", (teacher_id, start, end))
    appts = [_teacher_appointment(db, a, sched.today_str()) for a in rows]
    owned_blocks = []
    for b in db.query("SELECT * FROM blocks ORDER BY created_ts"):
        if b["teacher_id"] and b["teacher_id"] != teacher_id:
            continue
        bdate = (b.get("slot") or "").split("#")[0]
        if not bdate or not (start <= bdate <= end):
            continue
        owned_blocks.append(dict(b))
    availability = db.teacher.list_availability(teacher_id)
    return {
        "teacher_id": teacher_id, "start": start, "end": end,
        "appointments": appts, "blocks": owned_blocks,
        "availability": list(availability),
    }


# =========================================================================== 分诊（教师）
def triage_list(db: Database, since: Optional[str]) -> dict:
    students = db.query("SELECT * FROM students ORDER BY created_ts")
    items = []
    for st in students:
        item = _triage_item(db, st)
        if since and (item["last_active_ts"] or st["created_ts"]) <= since:
            continue
        items.append(item)
    items.sort(key=lambda x: (x["priority"], x["student_id"]))
    return {
        "generated_at": sched.now_iso(),
        "params": {"window_n": WINDOW_N, "threshold_k": THRESHOLD_K, "p3_lookback_days": 7},
        "items": items,
    }


def _triage_item(db: Database, st: dict) -> dict:
    recent = db.query(
        "SELECT mood FROM questionnaire_submissions WHERE student_id=? ORDER BY ts DESC, rowid DESC LIMIT ?",
        (st["student_id"], WINDOW_N),
    )
    recent_down = sum(1 for r in recent if r["mood"] == "down")
    pending = db.query_one(
        "SELECT 1 FROM tickets WHERE student_id=? AND status='pending'", (st["student_id"],)
    )
    has_history = bool(st["has_mental_history"])
    pending_help = bool(pending)
    if has_history and recent_down >= THRESHOLD_K:
        priority = 1
    elif pending_help:
        priority = 2
    else:
        priority = 3
    last_active = db.query_one(
        "SELECT ts FROM questionnaire_submissions WHERE student_id=? ORDER BY ts DESC LIMIT 1",
        (st["student_id"],),
    )
    return {
        "student_id": st["student_id"],
        "name": st["name"],
        "class_name": st["class_name"],
        "priority": priority,
        "flags": {
            "has_history": has_history,
            "recent_down_count": recent_down,
            "window_size": WINDOW_N,
            "pending_help": pending_help,
        },
        "last_active_ts": (last_active or {}).get("ts"),
        "masked": True,
    }


def _authorized_today(db: Database, student_id: str, today: str):
    """§5 可见性过滤：预约创建日 = today 的预约，其 share 标记授权当天数据。"""
    appts = db.query(
        "SELECT * FROM appointments WHERE student_id=? AND substr(created_ts,1,10)=?",
        (student_id, today),
    )
    share_q = any(a["share_questionnaire"] for a in appts)
    share_t = any(a["share_treehole"] for a in appts)
    q_rows = db.query(
        "SELECT record_id, ts, mood, cause_category, detail FROM questionnaire_submissions"
        " WHERE student_id=? AND date=? ORDER BY ts DESC",
        (student_id, today),
    ) if share_q else []
    t_rows = db.query(
        "SELECT entry_id, ts, content, mood_tag FROM treehole_entries"
        " WHERE student_id=? AND date=? ORDER BY ts DESC",
        (student_id, today),
    ) if share_t else []
    return q_rows, t_rows, (share_q or share_t)


def student_today(db: Database, student_id: str) -> dict:
    today = sched.today_str()
    st = db.query_one("SELECT * FROM students WHERE student_id=?", (student_id,))
    if not st:
        raise _err(2002, "学生不存在", "student_id")
    subs = db.query(
        "SELECT * FROM questionnaire_submissions WHERE student_id=? AND date=? ORDER BY ts DESC",
        (student_id, today),
    )
    mood_latest = subs[0]["mood"] if subs else None
    pending_help = bool(db.query_one(
        "SELECT 1 FROM tickets WHERE student_id=? AND status='pending'", (student_id,)
    ))
    recent = db.query(
        "SELECT mood FROM questionnaire_submissions WHERE student_id=? ORDER BY ts DESC, rowid DESC LIMIT ?",
        (student_id, WINDOW_N),
    )
    recent_down = sum(1 for r in recent if r["mood"] == "down")
    alert = None
    if st["has_mental_history"] and recent_down >= THRESHOLD_K:
        alert = {"level": 1, "rule": "history_plus_recent_down",
                 "recent_down_count": recent_down, "window_size": WINDOW_N}
    q_rows, t_rows, authorized = _authorized_today(db, student_id, today)
    tickets = db.query(
        "SELECT ticket_id, status FROM tickets WHERE student_id=? AND status IN ('pending','accepted') ORDER BY created_ts",
        (student_id,),
    )
    return {
        "student_id": student_id,
        "date": today,
        "mood_latest": mood_latest,
        "submission_count_today": len(subs),
        "pending_help": pending_help,
        "alert": alert,
        "shared_records": q_rows,
        "shared_treehole": t_rows,
        "has_shared_records": authorized,
        "tickets": tickets,
        "masked": not authorized,
    }


def ack_ticket(db: Database, ticket_id: str, action: str, note: Optional[str]) -> dict:
    if action not in ("accept", "done"):
        raise _err(2001, "字段 action 校验失败：只能是 accept/done", "action")
    t = db.query_one("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,))
    if not t:
        raise _err(2002, "工单不存在", "ticket_id")
    status = "accepted" if action == "accept" else "done"
    now = sched.now_iso()
    db.execute(
        "UPDATE tickets SET status=?, note=?, updated_ts=? WHERE ticket_id=?",
        (status, note, now, ticket_id),
    )
    db.commit()
    return {"ticket_id": ticket_id, "status": status, "updated_at": now}


# =========================================================================== /db 网关（教师）
def _require_student(db: Database, student_id: str) -> dict:
    st = db.query_one("SELECT * FROM students WHERE student_id=?", (student_id,))
    if not st:
        raise _err(2002, "学生不存在", "student_id")
    return st


def _iso_from_appt(a: dict) -> Optional[str]:
    """预约行 → 约谈时刻 ISO（date + time_start）。缺 time_start 返回 None。"""
    ts = a.get("time_start") or ""
    if a.get("date") and ts:
        return f"{a['date']}T{ts}:00+08:00"
    return None


def _parse_scheduled_at(iso: str):
    """ISO 约谈时刻 → (year, month, day, time_start 'HH:MM')。"""
    text = (iso or "").strip()
    if not text:
        raise _err(2001, "字段 scheduled_at 校验失败：必填", "scheduled_at")
    date_part, time_part = text[:10], text[11:16]
    try:
        y, m, d = date_part.split("-")
        int(y), int(m), int(d)
        hh, mm = time_part.split(":")
        int(hh), int(mm)
    except (ValueError, IndexError):
        raise _err(2001, "字段 scheduled_at 校验失败：格式必须是 ISO8601", "scheduled_at")
    if sched.weekday_from_date(int(y), int(m), int(d)) < 0:
        raise _err(2001, "字段 scheduled_at 校验失败：日期不存在", "scheduled_at")
    return y, m, d, f"{hh}:{mm}"


def _teacher_appointment(db: Database, a: dict, today: str) -> dict:
    """DB 预约行 → 教师端 Appointment 形状（正文按 §5 仅当天 + share 标记）。"""
    teacher_name = room_name = None
    if a.get("teacher_id"):
        teacher_name = db.teacher.get_name(a["teacher_id"])
    if a.get("room_id"):
        r = db.query_one("SELECT name FROM rooms WHERE room_id=?", (a["room_id"],))
        room_name = r["name"] if r else None
    item = {
        "appointment_id": a["apt_id"],
        "student_id": a["student_id"],
        "student_name": a["name"],
        "class_name": a["class_name"],
        "ticket_id": a["ticket_id"],
        "teacher_id": a["teacher_id"],
        "teacher_name": teacher_name,
        "room_id": a["room_id"],
        "room_name": room_name,
        "scheduled_at": _iso_from_appt(a),
        "date": a["date"],
        "period": a["period"],
        "weekday": a["weekday"],
        "status": a["status"],
        "note": a["note"],
        "cancel_reason": a["cancel_reason"],
        "rescheduled_from": a["rescheduled_from"],
        "no_show_note": a["no_show_note"],
        "created_at": a["created_ts"],
        "help_text_preview": "发起了求助" if a["ticket_id"] else "",
        "questionnaire": None,
        "treehole": None,
    }
    if a["share_questionnaire"] and (a["created_ts"] or "")[:10] == today:
        item["questionnaire"] = db.query(
            "SELECT record_id, mood, cause_category, detail FROM questionnaire_submissions"
            " WHERE student_id=? AND date=? ORDER BY ts DESC",
            (a["student_id"], today),
        )
    if a["share_treehole"] and (a["created_ts"] or "")[:10] == today:
        item["treehole"] = db.query(
            "SELECT entry_id, content, mood_tag FROM treehole_entries"
            " WHERE student_id=? AND date=? ORDER BY ts DESC",
            (a["student_id"], today),
        )
    return item


def _reply_item(r: dict) -> dict:
    d = dict(r)
    try:
        d["scenes"] = json.loads(d.get("scenes") or "[]")
    except (ValueError, TypeError):
        d["scenes"] = []
    return d


def _conflict(db: Database, slot: str, date: str, period: str,
              teacher_id: Optional[str], room_id: Optional[str],
              exclude_apt_id: Optional[str] = None) -> Optional[str]:
    """预约冲突检测：同格 / 同教师同时段 / 同咨询室同时段 / 停诊 / 教师可用性。"""
    def _hit(sql: str, args: list) -> bool:
        return db.query_one(sql, args) is not None

    # 1. 同格冲突（slot 唯一）
    q = "SELECT 1 FROM appointments WHERE slot=? AND status='scheduled'"
    args: list = [slot]
    if exclude_apt_id:
        q += " AND apt_id != ?"
        args.append(exclude_apt_id)
    if _hit(q, args):
        return "该时段已被预约"

    # 2. 教师同时段冲突
    if teacher_id:
        q = ("SELECT 1 FROM appointments WHERE teacher_id=? AND date=? AND period=?"
             " AND status='scheduled'")
        args = [teacher_id, date, str(period)]
        if exclude_apt_id:
            q += " AND apt_id != ?"
            args.append(exclude_apt_id)
        if _hit(q, args):
            return "该教师此时段已有预约"

    # 3. 咨询室同时段冲突
    if room_id:
        q = ("SELECT 1 FROM appointments WHERE room_id=? AND date=? AND period=?"
             " AND status='scheduled'")
        args = [room_id, date, str(period)]
        if exclude_apt_id:
            q += " AND apt_id != ?"
            args.append(exclude_apt_id)
        if _hit(q, args):
            return "该咨询室此时段已被占用"

    # 4. 停诊冲突（全局停诊 或 该教师个人停诊）
    q = ("SELECT 1 FROM blocks WHERE slot=? AND active=1"
         " AND (teacher_id IS NULL OR teacher_id=?)")
    args = [slot, teacher_id]
    if _hit(q, args):
        return "该教师此时段停诊" if teacher_id else "该时段已停诊"

    # 5. 教师周期可用性（RFC 7953 VAVAILABILITY 式：缺省全可用，显式关才拦）
    if teacher_id:
        try:
            yy, mm, dd = (int(x) for x in date.split("-"))
            wd = sched.weekday_from_date(yy, mm, dd)
        except (ValueError, AttributeError):
            wd = -1
        if wd > 0 and not db.teacher.is_available(teacher_id, wd, int(period)):
            return "该教师此时段不可约"
    return None


def _log_event(db: Database, appointment_id: str, actor: str, action: str,
               note: Optional[str] = None) -> None:
    """追加预约操作日志（不 commit，由调用方统一提交）。"""
    db.execute(
        "INSERT INTO appointment_events(event_id, appointment_id, actor, action, note, created_ts)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("evt_"), appointment_id, actor, action, note, sched.now_iso()),
    )


def db_read(db: Database, resource: str, params: dict) -> Any:
    today = sched.today_str()
    if resource == "appointments.pending":
        rows = db.query(
            "SELECT t.ticket_id, t.student_id, s.name, s.class_name, t.created_ts"
            " FROM tickets t JOIN students s ON s.student_id=t.student_id"
            " WHERE t.status='pending' AND t.ticket_id NOT IN"
            " (SELECT ticket_id FROM appointments WHERE ticket_id IS NOT NULL)"
            " ORDER BY t.created_ts",
        )
        items = [{
            "appointment_id": "", "student_id": r["student_id"],
            "student_name": r["name"], "class_name": r["class_name"],
            "ticket_id": r["ticket_id"], "scheduled_at": None,
            "status": "pending_request", "note": None,
            "created_at": r["created_ts"], "help_text_preview": "发起了求助",
        } for r in rows]
        return {"items": items}
    if resource == "appointments.by_date":
        date = params.get("date") or today
        rows = db.query(
            "SELECT * FROM appointments WHERE date=? ORDER BY period, time_start", (date,)
        )
        return {"date": date, "items": [_teacher_appointment(db, a, today) for a in rows]}
    if resource == "blocks.list":
        return {"items": [_boolify(dict(r)) for r in db.query("SELECT * FROM blocks ORDER BY created_ts")]}
    if resource == "warnings.list":
        rows = db.query(
            "SELECT w.*, s.name AS student_name, s.class_name FROM warnings w"
            " JOIN students s ON s.student_id=w.student_id"
            " ORDER BY (w.status='active') DESC, w.latest_ts DESC",
        )
        return {"items": [dict(r) for r in rows]}
    if resource == "replies.list":
        return {"items": [_boolify(_reply_item(r)) for r in db.query("SELECT * FROM replies ORDER BY updated_ts DESC")]}
    if resource == "export.classes":
        rows = db.query("SELECT DISTINCT class_name FROM students ORDER BY class_name")
        return {"items": [r["class_name"] for r in rows]}
    if resource == "export.rows":
        start = params.get("start")
        end = params.get("end")
        class_name = params.get("class_name")
        if not start or not end:
            raise _err(2001, "字段 start/end 校验失败：必填", "start")
        sql = (
            "SELECT q.student_id, s.name, s.class_name, q.date, q.ts, q.mood,"
            " q.cause_category, q.request_help, q.consent_share,"
            " (SELECT t.status FROM tickets t WHERE t.source_record_id=q.record_id LIMIT 1) AS ticket_status"
            " FROM questionnaire_submissions q JOIN students s ON s.student_id=q.student_id"
            " WHERE q.date >= ? AND q.date <= ?"
        )
        args: List[Any] = [start, end]
        if class_name:
            sql += " AND q.class_name = ?"  # placeholder not on q; fix below
            sql = sql.replace(" AND q.class_name = ?", " AND s.class_name = ?")
            args.append(class_name)
        sql += " ORDER BY q.date, s.class_name, q.ts"
        rows = db.query(sql, args)
        return {"items": [_boolify(dict(r)) for r in rows]}
    if resource == "teachers.list":
        return {"items": db.teacher.list_all()}
    if resource == "rooms.list":
        return {"items": [dict(r) for r in db.query("SELECT * FROM rooms ORDER BY created_ts")]}
    if resource == "appointments.events":
        apt_id = params.get("appointment_id")
        if apt_id:
            rows = db.query(
                "SELECT * FROM appointment_events WHERE appointment_id=? ORDER BY created_ts",
                (apt_id,))
        else:
            rows = db.query("SELECT * FROM appointment_events ORDER BY created_ts DESC LIMIT 200")
        return {"items": [dict(r) for r in rows]}
    if resource == "stats.appointments":
        start = params.get("start") or today
        end = params.get("end") or today
        rows = db.query(
            "SELECT date, teacher_id, room_id, status, COUNT(*) AS cnt FROM appointments"
            " WHERE date >= ? AND date <= ? GROUP BY date, teacher_id, room_id, status",
            (start, end),
        )
        total = sum(r["cnt"] for r in rows)
        done = sum(r["cnt"] for r in rows if r["status"] == "done")
        teacher_names = db.teacher.name_map()
        room_names = {r["room_id"]: r["name"]
                      for r in db.query("SELECT room_id, name FROM rooms")}
        by_teacher: Dict[str, int] = {}
        by_room: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        for r in rows:
            t = teacher_names.get(r["teacher_id"], "(未分配)") if r["teacher_id"] else "(未分配)"
            m = room_names.get(r["room_id"], "(未分配)") if r["room_id"] else "(未分配)"
            by_teacher[t] = by_teacher.get(t, 0) + r["cnt"]
            by_room[m] = by_room.get(m, 0) + r["cnt"]
            by_status[r["status"]] = by_status.get(r["status"], 0) + r["cnt"]
        return {
            "start": start, "end": end,
            "total": total, "done": done,
            "completion_rate": round(done / total, 4) if total else 0,
            "by_teacher": by_teacher, "by_room": by_room, "by_status": by_status,
            "rows": [dict(r) for r in rows],
        }
    if resource == "waitlist.list":
        year = params.get("year")
        month = params.get("month")
        day = params.get("day")
        status = params.get("status")
        sql = ("SELECT w.*, s.name AS student_name, s.class_name FROM waitlist w"
               " JOIN students s ON s.student_id=w.student_id")
        conds, args = [], []
        if year:
            conds.append("w.year=?"); args.append(str(year))
        if month:
            conds.append("w.month=?"); args.append(str(month))
        if day:
            conds.append("w.day=?"); args.append(str(day))
        if status:
            conds.append("w.status=?"); args.append(str(status))
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY w.created_ts"
        return {"items": [dict(r) for r in db.query(sql, args)]}
    if resource == "teacher_calendar":
        return teacher_calendar(db, params.get("teacher_id") or "",
                                params.get("start") or today,
                                params.get("end") or today)
    raise _err(2001, f"未注册的资源: {resource}", "resource")


def _is_today_created(appt: dict, today: str) -> bool:
    return (appt.get("created_ts") or "")[:10] == today


def db_write(db: Database, action: str, payload: dict) -> Any:
    if action == "appointments.schedule":
        student_id = str(payload.get("student_id") or "")
        st = _require_student(db, student_id)
        ticket_id = payload.get("ticket_id")
        teacher_id = payload.get("teacher_id") or None
        room_id = payload.get("room_id") or None
        if payload.get("scheduled_at"):
            year, month, day, time_text = _parse_scheduled_at(payload.get("scheduled_at"))
        else:
            year, month, day = payload.get("year"), payload.get("month"), payload.get("day")
            time_text = str(payload.get("time") or "")
        period = _coerce_period(year, month, day, time_text, None)
        slot = sched.slot_id(int(year), int(month), int(day), period)
        slot_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        conflict = _conflict(db, slot, slot_date, str(period), teacher_id, room_id)
        if conflict:
            raise _err(2001, conflict, "slot")
        now = sched.now_iso()
        apt_id = new_id("apt_")
        weekday = sched.weekday_from_date(int(year), int(month), int(day))
        db.execute(
            "INSERT INTO appointments"
            "(apt_id, student_id, ticket_id, teacher_id, room_id, name, class_name,"
            " year, month, day, period, weekday, time_start, time_end, slot, date,"
            " share_questionnaire, share_treehole, status, note, created_ts, updated_ts)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (apt_id, student_id, ticket_id, teacher_id, room_id, st["name"], st["class_name"],
             str(year), str(month), str(day), str(period), str(weekday),
             sched.period_start(period), sched.period_end(period), slot, slot_date,
             1, 0, "scheduled", payload.get("note"), now, now),
        )
        if ticket_id:
            db.execute("UPDATE tickets SET status='accepted', updated_ts=? WHERE ticket_id=?", (now, ticket_id))
        _log_event(db, apt_id, "teacher", "scheduled", payload.get("note"))
        db.commit()
        a = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        return _teacher_appointment(db, a, sched.today_str())
    if action == "appointments.reschedule":
        apt_id = str(payload.get("appointment_id") or "")
        a = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        if not a:
            raise _err(2002, "预约不存在", "appointment_id")
        if payload.get("scheduled_at"):
            year, month, day, time_text = _parse_scheduled_at(payload.get("scheduled_at"))
        else:
            year, month, day = payload.get("year"), payload.get("month"), payload.get("day")
            time_text = str(payload.get("time") or "")
        period = _coerce_period(year, month, day, time_text, None)
        slot = sched.slot_id(int(year), int(month), int(day), period)
        slot_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        teacher_id = payload.get("teacher_id", a["teacher_id"]) or None
        room_id = payload.get("room_id", a["room_id"]) or None
        conflict = _conflict(db, slot, slot_date, str(period), teacher_id, room_id,
                             exclude_apt_id=apt_id)
        if conflict:
            raise _err(2001, conflict, "slot")
        now = sched.now_iso()
        weekday = sched.weekday_from_date(int(year), int(month), int(day))
        db.execute(
            "UPDATE appointments SET teacher_id=?, room_id=?, year=?, month=?, day=?,"
            " period=?, weekday=?, time_start=?, time_end=?, slot=?, date=?,"
            " rescheduled_from=?, updated_ts=? WHERE apt_id=?",
            (teacher_id, room_id, str(year), str(month), str(day), str(period), str(weekday),
             sched.period_start(period), sched.period_end(period), slot, slot_date,
             apt_id, now, apt_id),
        )
        _log_event(db, apt_id, "teacher", "rescheduled", payload.get("note"))
        # 改期释放旧时段 → 递补候补（同一事务，保证原子性）
        _promote_waitlist(db, a["year"], a["month"], a["day"], a["period"],
                          a["teacher_id"], a["room_id"], "teacher")
        db.commit()
        return _teacher_appointment(
            db, db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,)),
            sched.today_str())
    if action == "appointments.cancel":
        apt_id = str(payload.get("appointment_id") or "")
        a = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        if not a:
            raise _err(2002, "预约不存在", "appointment_id")
        reason = str(payload.get("reason") or "")
        now = sched.now_iso()
        db.execute("UPDATE appointments SET status='cancelled', cancel_reason=?, updated_ts=? WHERE apt_id=?",
                   (reason, now, apt_id))
        if a["ticket_id"]:
            db.execute("UPDATE tickets SET status='pending', updated_ts=? WHERE ticket_id=?", (now, a["ticket_id"]))
        _log_event(db, apt_id, "teacher", "cancelled", reason)
        # 取消释放时段 → 递补候补（同一事务，保证原子性）
        _promote_waitlist(db, a["year"], a["month"], a["day"], a["period"],
                          a["teacher_id"], a["room_id"], "teacher")
        db.commit()
        return _teacher_appointment(
            db, db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,)),
            sched.today_str())
    if action == "appointments.no_show":
        apt_id = str(payload.get("appointment_id") or "")
        a = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        if not a:
            raise _err(2002, "预约不存在", "appointment_id")
        note = str(payload.get("note") or "")
        now = sched.now_iso()
        db.execute("UPDATE appointments SET status='no_show', no_show_note=?, updated_ts=? WHERE apt_id=?",
                   (note, now, apt_id))
        _log_event(db, apt_id, "teacher", "no_show", note)
        # 爽约释放时段 → 递补候补（同一事务，保证原子性）
        _promote_waitlist(db, a["year"], a["month"], a["day"], a["period"],
                          a["teacher_id"], a["room_id"], "teacher")
        db.commit()
        return _teacher_appointment(
            db, db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,)),
            sched.today_str())
    if action == "rooms.create":
        name = str(payload.get("name") or "").strip()
        if not name:
            raise _err(2001, "字段 name 校验失败：必须是非空字符串", "name")
        location = str(payload.get("location") or "").strip() or None
        features = str(payload.get("features") or "").strip() or None
        room_id = new_id("rm_")
        db.execute("INSERT INTO rooms(room_id, name, location, features, active, created_ts)"
                   " VALUES(?,?,?,?,1,?)",
                   (room_id, name, location, features, sched.now_iso()))
        db.commit()
        return dict(db.query_one("SELECT * FROM rooms WHERE room_id=?", (room_id,)))
    if action == "rooms.update":
        room_id = str(payload.get("room_id") or "")
        r = db.query_one("SELECT * FROM rooms WHERE room_id=?", (room_id,))
        if not r:
            raise _err(2002, "咨询室不存在", "room_id")
        if "name" in payload and payload["name"] is not None:
            db.execute("UPDATE rooms SET name=? WHERE room_id=?",
                       (str(payload["name"]).strip(), room_id))
        if "location" in payload and payload["location"] is not None:
            db.execute("UPDATE rooms SET location=? WHERE room_id=?",
                       (str(payload["location"]).strip() or None, room_id))
        if "features" in payload and payload["features"] is not None:
            db.execute("UPDATE rooms SET features=? WHERE room_id=?",
                       (str(payload["features"]).strip() or None, room_id))
        if "active" in payload and payload["active"] is not None:
            db.execute("UPDATE rooms SET active=? WHERE room_id=?",
                       (int(bool(payload["active"])), room_id))
        db.commit()
        return dict(db.query_one("SELECT * FROM rooms WHERE room_id=?", (room_id,)))
    if action == "rooms.delete":
        room_id = str(payload.get("room_id") or "")
        db.execute("DELETE FROM rooms WHERE room_id=?", (room_id,))
        db.commit()
        return {"room_id": room_id}
    if action == "blocks.batch_set":
        items = list(payload.get("items") or [])
        active = bool(payload.get("active", True))
        reason = payload.get("reason")
        teacher_id = payload.get("teacher_id")  # None=全局；有值=该教师个人停诊
        now = sched.now_iso()
        slots = []
        for it in items:
            try:
                slot = sched.slot_id(int(it["year"]), int(it["month"]),
                                     int(it["day"]), int(it["period"]))
            except (KeyError, TypeError, ValueError):
                continue
            existing = db.query_one("SELECT * FROM blocks WHERE slot=?", (slot,))
            if existing:
                db.execute("UPDATE blocks SET active=?, reason=?, operator=?, teacher_id=?, created_ts=? WHERE slot=?",
                           (int(active), reason, "teacher", teacher_id, now, slot))
            else:
                db.execute(
                    "INSERT INTO blocks(blk_id, slot, year, month, day, period, active, reason, operator, teacher_id, created_ts)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id("blk_"), slot, str(it["year"]), str(it["month"]), str(it["day"]),
                     str(it["period"]), int(active), reason, "teacher", teacher_id, now))
            slots.append(slot)
        db.commit()
        return {"slots": slots}
    if action == "appointments.complete":
        apt_id = str(payload.get("appointment_id") or "")
        a = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        if not a:
            raise _err(2002, "预约不存在", "appointment_id")
        now = sched.now_iso()
        db.execute("UPDATE appointments SET status='done', updated_ts=? WHERE apt_id=?", (now, apt_id))
        if a["ticket_id"]:
            db.execute("UPDATE tickets SET status='done', updated_ts=? WHERE ticket_id=?", (now, a["ticket_id"]))
        _log_event(db, apt_id, "teacher", "completed")
        db.commit()
        a2 = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        return _teacher_appointment(db, a2, sched.today_str())
    if action == "blocks.set":
        return set_block(db, "teacher", payload)
    if action == "warnings.dismiss":
        wid = str(payload.get("warning_id") or "")
        w = db.query_one("SELECT * FROM warnings WHERE warning_id=?", (wid,))
        if not w:
            raise _err(2002, "预警不存在", "warning_id")
        now = sched.now_iso()
        db.execute(
            "UPDATE warnings SET status='dismissed', dismissed_at=?, dismiss_note=? WHERE warning_id=?",
            (now, payload.get("note"), wid),
        )
        db.commit()
        w2 = db.query_one(
            "SELECT w.*, s.name AS student_name, s.class_name FROM warnings w"
            " JOIN students s ON s.student_id=w.student_id WHERE w.warning_id=?", (wid,)
        )
        return dict(w2)
    if action == "replies.create":
        text = str(payload.get("text") or "").strip()
        scenes = list(payload.get("scenes") or [])
        if not text:
            raise _err(2001, "字段 text 校验失败：必须是非空字符串", "text")
        now = sched.now_iso()
        reply_id = new_id("rpl_")
        db.execute(
            "INSERT INTO replies(reply_id, text, scenes, enabled, created_ts, updated_ts) VALUES(?,?,?,1,?,?)",
            (reply_id, text, json.dumps(scenes, ensure_ascii=False), now, now),
        )
        db.commit()
        return _reply_item(db.query_one("SELECT * FROM replies WHERE reply_id=?", (reply_id,)))
    if action == "replies.update":
        rid = str(payload.get("reply_id") or "")
        r = db.query_one("SELECT * FROM replies WHERE reply_id=?", (rid,))
        if not r:
            raise _err(2002, "回复不存在", "reply_id")
        fields, args = [], []
        if "text" in payload and payload["text"] is not None:
            fields.append("text=?"); args.append(str(payload["text"]).strip())
        if "scenes" in payload and payload["scenes"] is not None:
            fields.append("scenes=?"); args.append(json.dumps(payload["scenes"], ensure_ascii=False))
        if "enabled" in payload and payload["enabled"] is not None:
            fields.append("enabled=?"); args.append(int(bool(payload["enabled"])))
        if fields:
            fields.append("updated_ts=?"); args.append(sched.now_iso())
            args.append(rid)
            db.execute(f"UPDATE replies SET {', '.join(fields)} WHERE reply_id=?", args)
            db.commit()
        return _reply_item(db.query_one("SELECT * FROM replies WHERE reply_id=?", (rid,)))
    if action == "replies.delete":
        rid = str(payload.get("reply_id") or "")
        db.execute("DELETE FROM replies WHERE reply_id=?", (rid,))
        db.commit()
        return {"reply_id": rid}
    if action == "students.set_history":
        student_id = str(payload.get("student_id") or "")
        _require_student(db, student_id)
        has_history = bool(payload.get("has_history"))
        db.execute("UPDATE students SET has_mental_history=? WHERE student_id=?", (int(has_history), student_id))
        db.commit()
        return dict(db.query_one("SELECT * FROM students WHERE student_id=?", (student_id,)))
    if action == "students.reset_password":
        student_id = str(payload.get("student_id") or "")
        new_password = str(payload.get("new_password") or "")
        if len(new_password) < 4:
            raise _err(2001, "字段 new_password 校验失败：长度至少 4 位", "new_password")
        _require_student(db, student_id)
        salt, digest = hash_password(new_password)
        now = sched.now_iso()
        db.execute(
            "UPDATE credentials SET password_hash=?, salt=?, updated_ts=? WHERE student_id=?",
            (digest, salt, now, student_id),
        )
        db.commit()
        return {"student_id": student_id, "reset": True}
    if action == "waitlist.join":
        return join_waitlist(db, str(payload.get("student_id") or ""), payload)
    if action == "waitlist.cancel":
        wait_id = str(payload.get("wait_id") or "")
        w = db.query_one("SELECT * FROM waitlist WHERE wait_id=?", (wait_id,))
        if not w:
            raise _err(2002, "候补不存在", "wait_id")
        db.execute("UPDATE waitlist SET status='cancelled', updated_ts=? WHERE wait_id=?",
                   (sched.now_iso(), wait_id))
        db.commit()
        return dict(db.query_one("SELECT * FROM waitlist WHERE wait_id=?", (wait_id,)))
    if action == "teachers.create":
        name = str(payload.get("name") or "").strip()
        password = str(payload.get("password") or "")
        if not name:
            raise _err(2001, "字段 name 校验失败：必须是非空字符串", "name")
        if len(password) < 4:
            raise _err(2001, "字段 password 校验失败：长度至少 4 位", "password")
        return db.teacher.create(name, password)
    if action == "teachers.update":
        teacher_id = str(payload.get("teacher_id") or "")
        if not db.teacher.get(teacher_id):
            raise _err(2002, "教师不存在", "teacher_id")
        if "name" in payload and payload["name"] is not None:
            db.teacher.rename(teacher_id, str(payload["name"]).strip())
        return db.teacher.get(teacher_id)
    if action == "teachers.reset_password":
        teacher_id = str(payload.get("teacher_id") or "")
        new_password = str(payload.get("new_password") or "")
        if len(new_password) < 4:
            raise _err(2001, "字段 new_password 校验失败：长度至少 4 位", "new_password")
        result = db.teacher.reset_password(teacher_id, new_password)
        if result is None:
            raise _err(2002, "教师不存在", "teacher_id")
        return result
    if action == "teachers.delete":
        teacher_id = str(payload.get("teacher_id") or "")
        if teacher_id == PRESET_TEACHER_ID:
            raise _err(2001, "预置教师不可删除", "teacher_id")
        result = db.teacher.delete(teacher_id)
        if result is None:
            raise _err(2002, "教师不存在", "teacher_id")
        return result
    if action == "teachers.availability.set":
        teacher_id = str(payload.get("teacher_id") or "")
        result = db.teacher.set_availability(teacher_id, list(payload.get("items") or []))
        if result is None:
            raise _err(2002, "教师不存在", "teacher_id")
        return result
    raise _err(2001, f"未注册的动作: {action}", "action")


#: /db 白名单注册表（与教师端 data_gateway.py 的 RESOURCE/ACTION 注册表逐字对齐）
RESOURCE_REGISTRY = (
    "appointments.pending", "appointments.by_date", "blocks.list",
    "warnings.list", "replies.list", "export.classes", "export.rows",
    "rooms.list", "teachers.list", "appointments.events", "stats.appointments",
    "waitlist.list", "teacher_calendar",
)
ACTION_REGISTRY = (
    "appointments.schedule", "appointments.complete", "blocks.set",
    "warnings.dismiss", "replies.create", "replies.update", "replies.delete",
    "students.set_history", "students.reset_password",
    "appointments.reschedule", "appointments.cancel", "appointments.no_show",
    "rooms.create", "rooms.update", "rooms.delete", "blocks.batch_set",
    "waitlist.join", "waitlist.cancel",
    "teachers.create", "teachers.update", "teachers.reset_password",
    "teachers.delete", "teachers.availability.set",
)
