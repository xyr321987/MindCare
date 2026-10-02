"""SQLite 数据层 —— 契约 §3 的 14 张表 + 运行纪律（§8）。

运行纪律（二轮筛查风险控制）：
* **WAL + busy_timeout + 单连接串行写**：所有访问过一把 `RLock`，同一时刻只一个写事务，
  避免 `database is locked`（R1）。
* 注册用**单事务**包裹 `students`+`credentials`（R2）。
* 密码用 `hashlib.pbkdf2_hmac` 加盐存储（`credentials` 独立表）。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional

from . import schedule as sched
from .teacher_store import TEACHER_SCHEMA, TeacherStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id        TEXT PRIMARY KEY,
    seat_no           TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    class_name        TEXT NOT NULL,
    has_mental_history INTEGER NOT NULL DEFAULT 0,
    created_ts        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credentials (
    student_id   TEXT PRIMARY KEY REFERENCES students(student_id),
    password_hash TEXT NOT NULL,
    salt         TEXT NOT NULL,
    updated_ts   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    role       TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS questionnaire_submissions (
    record_id      TEXT PRIMARY KEY,
    student_id     TEXT NOT NULL REFERENCES students(student_id),
    ts             TEXT NOT NULL,
    date           TEXT NOT NULL,
    mood           TEXT NOT NULL,
    plain_note     TEXT,
    cause_category TEXT,
    detail         TEXT,
    request_help   INTEGER NOT NULL DEFAULT 0,
    consent_share  INTEGER NOT NULL DEFAULT 0,
    consent_ts     TEXT
);
CREATE TABLE IF NOT EXISTS treehole_entries (
    entry_id   TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(student_id),
    ts         TEXT NOT NULL,
    date       TEXT NOT NULL,
    content    TEXT NOT NULL,
    mood_tag   TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id        TEXT PRIMARY KEY,
    student_id       TEXT NOT NULL REFERENCES students(student_id),
    source_record_id TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_ts       TEXT NOT NULL,
    updated_ts       TEXT NOT NULL,
    note             TEXT
);
CREATE TABLE IF NOT EXISTS appointments (
    apt_id             TEXT PRIMARY KEY,
    student_id         TEXT NOT NULL REFERENCES students(student_id),
    ticket_id          TEXT REFERENCES tickets(ticket_id),
    teacher_id         TEXT REFERENCES teachers(teacher_id),
    room_id            TEXT REFERENCES rooms(room_id),
    name               TEXT,
    class_name         TEXT,
    year               TEXT,
    month              TEXT,
    day                TEXT,
    period             TEXT,
    weekday            TEXT,
    time_start         TEXT,
    time_end           TEXT,
    slot               TEXT NOT NULL,
    date               TEXT NOT NULL,
    share_questionnaire INTEGER NOT NULL DEFAULT 0,
    share_treehole     INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'scheduled',
    note               TEXT,
    cancel_reason      TEXT,
    rescheduled_from   TEXT,
    no_show_note       TEXT,
    created_ts         TEXT NOT NULL,
    updated_ts         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rooms (
    room_id    TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointment_events (
    event_id        TEXT PRIMARY KEY,
    appointment_id  TEXT NOT NULL REFERENCES appointments(apt_id),
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    note            TEXT,
    created_ts      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocks (
    blk_id     TEXT PRIMARY KEY,
    slot       TEXT NOT NULL UNIQUE,
    year       TEXT,
    month      TEXT,
    day        TEXT,
    period     TEXT,
    active     INTEGER NOT NULL DEFAULT 1,
    reason     TEXT,
    operator   TEXT,
    teacher_id TEXT,
    created_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS waitlist (
    wait_id       TEXT PRIMARY KEY,
    student_id    TEXT NOT NULL REFERENCES students(student_id),
    ticket_id     TEXT REFERENCES tickets(ticket_id),
    year          TEXT,
    month         TEXT,
    day           TEXT,
    period        TEXT,
    teacher_id    TEXT REFERENCES teachers(teacher_id),
    room_id       TEXT REFERENCES rooms(room_id),
    status        TEXT NOT NULL DEFAULT 'waiting',
    filled_apt_id TEXT,
    reason        TEXT,
    created_ts    TEXT NOT NULL,
    updated_ts    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS warnings (
    warning_id   TEXT PRIMARY KEY,
    student_id   TEXT NOT NULL REFERENCES students(student_id),
    rule         TEXT NOT NULL DEFAULT 'silent_down_streak',
    streak_count INTEGER NOT NULL DEFAULT 3,
    latest_ts    TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    dismissed_at TEXT,
    dismiss_note TEXT,
    created_ts   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replies (
    reply_id   TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    scenes     TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_ts TEXT NOT NULL,
    updated_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tips (
    scene          TEXT PRIMARY KEY,
    text           TEXT NOT NULL,
    treehole_entry INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sub_stu_date ON questionnaire_submissions(student_id, date);
CREATE INDEX IF NOT EXISTS idx_tree_stu_date ON treehole_entries(student_id, date);
CREATE INDEX IF NOT EXISTS idx_tickets_stu ON tickets(student_id);
CREATE INDEX IF NOT EXISTS idx_appt_stu ON appointments(student_id);
CREATE INDEX IF NOT EXISTS idx_appt_slot ON appointments(slot);
CREATE INDEX IF NOT EXISTS idx_wait_slot ON waitlist(year, month, day, period, status);
CREATE INDEX IF NOT EXISTS idx_warn_stu ON warnings(student_id);
"""

#: 静态 tips 种子（契约 §2.8）
TIPS_SEED = (
    ("plain", "可以出去看看哦，运动或和朋友走走都可以有不一样的体验。", 0),
    ("down", "可以跟我做：深呼吸，走一走，或者去树洞写写心里话。", 1),
)

_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> tuple[str, str]:
    """加盐哈希 → (salt, hash)。stdlib `pbkdf2_hmac(sha256)`，无第三方依赖。"""
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
    )
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hex: str) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ROUNDS
    )
    return hmac.compare_digest(digest.hex(), expected_hex)


class Database:
    """单连接 + 全局锁的 SQLite 门面（写操作天然串行，规避 R1 锁冲突）。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        with self._lock:
            # 教师分支先建：appointments / waitlist 的 teacher_id 外键指向 teachers
            self._conn.executescript(TEACHER_SCHEMA)
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._migrate()
        self._seed()
        # 教师信息分支唯一 DAO（其余模块对教师数据只读、只走这里）
        self.teacher = TeacherStore(self, hash_password, verify_password)
        self.teacher.ensure_seed()

    # ------------------------------------------------------------------ 基础
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return cur

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)
            self._conn.commit()

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def transaction(self, fn):
        """在单事务里执行 fn(cursor)；成功 commit，异常 rollback 后重抛。"""
        with self._lock:
            try:
                cur = self._conn.cursor()
                result = fn(cur)
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise

    # ------------------------------------------------------------------ 迁移
    def _migrate(self) -> None:
        """为旧库补预约调度升级新增的列（幂等）。"""
        cols = {r["name"] for r in self.query("PRAGMA table_info(appointments)")}
        for name in ("teacher_id", "room_id", "cancel_reason",
                     "rescheduled_from", "no_show_note"):
            if name not in cols:
                self.execute(f"ALTER TABLE appointments ADD COLUMN {name} TEXT")
        bcols = {r["name"] for r in self.query("PRAGMA table_info(blocks)")}
        if "teacher_id" not in bcols:
            self.execute("ALTER TABLE blocks ADD COLUMN teacher_id TEXT")
        self.commit()

    # ------------------------------------------------------------------ 种子
    def _seed(self) -> None:
        # 教师预置种子已随 TeacherStore.ensure_seed() 自洽处理，此处只管咨询室与 tips
        if not self.query_one("SELECT 1 FROM rooms"):
            self.execute(
                "INSERT INTO rooms(room_id, name, active, created_ts) VALUES(?,?,?,?)",
                ("rm_default", "咨询室A", 1, sched.now_iso()),
            )
        for scene, text, treehole in TIPS_SEED:
            self.execute(
                "INSERT OR IGNORE INTO tips(scene, text, treehole_entry) VALUES(?,?,?)",
                (scene, text, treehole),
            )
        self.commit()

    # ------------------------------------------------------------------ 会话
    def create_session(self, role: str, subject_id: str, expires_at: float) -> str:
        token = os.urandom(16).hex()  # 32 位随机串
        self.execute(
            "INSERT INTO sessions(token, role, subject_id, expires_at) VALUES(?,?,?,?)",
            (token, role, subject_id, expires_at),
        )
        self.commit()
        return token

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        return self.query_one(
            "SELECT * FROM sessions WHERE token=?", (token,)
        )

    def delete_session(self, token: str) -> None:
        self.execute("DELETE FROM sessions WHERE token=?", (token,))
        self.commit()
