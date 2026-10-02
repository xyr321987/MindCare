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
        row = db.query_one("SELECT * FROM teachers WHERE teacher_id=?", (raw_id,))
        if not row:
            raise _err(2002, "教师不存在", "id")
        cred = db.query_one(
            "SELECT * FROM teacher_credentials WHERE teacher_id=?", (row["teacher_id"],)
        )
        if not cred or not verify_password(password, cred["salt"], cred["password_hash"]):
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
    r = db.query_one("SELECT * FROM teachers WHERE teacher_id=?", (subject_id,))
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

    # 拒绝重复预约（决策 30/R6）：同 slot 已有 scheduled 预约
    clash = db.query_one(
        "SELECT 1 FROM appointments WHERE slot=? AND status='scheduled'", (slot,)
    )
    if clash:
        raise _err(2001, "该时段已被预约", "slot")

    stu = db.query_one("SELECT * FROM students WHERE student_id=?", (student_id,))
    now = sched.now_iso()
    slot_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    weekday = sched.weekday_from_date(int(year), int(month), int(day))
    db.execute(
        "INSERT INTO appointments"
        "(apt_id, student_id, name, class_name, year, month, day, period, weekday,"
        " time_start, time_end, slot, date, share_questionnaire, share_treehole, status, created_ts, updated_ts)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (apt_id, student_id, stu["name"], stu["class_name"], str(year), str(month), str(day),
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
            "UPDATE blocks SET active=?, reason=?, operator=?, created_ts=? WHERE slot=?",
            (int(active), reason, operator, now, slot),
        )
    else:
        db.execute(
            "INSERT INTO blocks(blk_id, slot, year, month, day, period, active, reason, operator, created_ts)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (new_id("blk_"), slot, str(year), str(month), str(day), str(period),
             int(active), reason, operator, now),
        )
    db.commit()
    row = db.query_one("SELECT * FROM blocks WHERE slot=?", (slot,))
    return row


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
    item = {
        "appointment_id": a["apt_id"],
        "student_id": a["student_id"],
        "student_name": a["name"],
        "class_name": a["class_name"],
        "ticket_id": a["ticket_id"],
        "scheduled_at": _iso_from_appt(a),
        "status": a["status"],
        "note": a["note"],
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
    raise _err(2001, f"未注册的资源: {resource}", "resource")


def _is_today_created(appt: dict, today: str) -> bool:
    return (appt.get("created_ts") or "")[:10] == today


def db_write(db: Database, action: str, payload: dict) -> Any:
    if action == "appointments.schedule":
        student_id = str(payload.get("student_id") or "")
        st = _require_student(db, student_id)
        ticket_id = payload.get("ticket_id")
        if payload.get("scheduled_at"):
            year, month, day, time_text = _parse_scheduled_at(payload.get("scheduled_at"))
        else:
            year, month, day = payload.get("year"), payload.get("month"), payload.get("day")
            time_text = str(payload.get("time") or "")
        period = _coerce_period(year, month, day, time_text, None)
        slot = sched.slot_id(int(year), int(month), int(day), period)
        clash = db.query_one("SELECT 1 FROM appointments WHERE slot=? AND status='scheduled'", (slot,))
        if clash:
            raise _err(2001, "该时段已被预约", "slot")
        now = sched.now_iso()
        apt_id = new_id("apt_")
        slot_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        weekday = sched.weekday_from_date(int(year), int(month), int(day))
        db.execute(
            "INSERT INTO appointments"
            "(apt_id, student_id, ticket_id, name, class_name, year, month, day, period, weekday,"
            " time_start, time_end, slot, date, share_questionnaire, share_treehole, status, note, created_ts, updated_ts)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (apt_id, student_id, ticket_id, st["name"], st["class_name"],
             str(year), str(month), str(day), str(period), str(weekday),
             sched.period_start(period), sched.period_end(period), slot, slot_date,
             1, 0, "scheduled", payload.get("note"), now, now),
        )
        if ticket_id:
            db.execute("UPDATE tickets SET status='accepted', updated_ts=? WHERE ticket_id=?", (now, ticket_id))
        db.commit()
        a = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        return _teacher_appointment(db, a, sched.today_str())
    if action == "appointments.complete":
        apt_id = str(payload.get("appointment_id") or "")
        a = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (apt_id,))
        if not a:
            raise _err(2002, "预约不存在", "appointment_id")
        now = sched.now_iso()
        db.execute("UPDATE appointments SET status='done', updated_ts=? WHERE apt_id=?", (now, apt_id))
        if a["ticket_id"]:
            db.execute("UPDATE tickets SET status='done', updated_ts=? WHERE ticket_id=?", (now, a["ticket_id"]))
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
    raise _err(2001, f"未注册的动作: {action}", "action")


#: /db 白名单注册表（与教师端 data_gateway.py 的 RESOURCE/ACTION 注册表逐字对齐）
RESOURCE_REGISTRY = (
    "appointments.pending", "appointments.by_date", "blocks.list",
    "warnings.list", "replies.list", "export.classes", "export.rows",
)
ACTION_REGISTRY = (
    "appointments.schedule", "appointments.complete", "blocks.set",
    "warnings.dismiss", "replies.create", "replies.update", "replies.delete",
    "students.set_history", "students.reset_password",
)
