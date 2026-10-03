# -*- coding: utf-8 -*-
"""教师信息「数据库分支」：身份 / 凭证 / 每周可用时间 的唯一数据访问层（DAO）。

与主库同协议、但边界清晰：
* 本模块是 `teachers` / `teacher_credentials` / `teacher_availability` 三张表的
  **唯一写入口**；其它任何模块（含 engine 的预约/停诊/统计）对教师数据一律只读，
  且只走本类方法，不直接拼这三张表的 SQL。
* 表 DDL 独立在 `TEACHER_SCHEMA`，与主库 `db.SCHEMA` 分开维护；迁移/种子随本类自洽。
* 密码只存加盐 PBKDF2 verifier（hash/verify 由 db 注入，见 OWASP / NIST 800-63B）。
* 每周可用时间按 RFC 7953 VAVAILABILITY 语义：缺行 = 默认可约，显式 active=0 才拦。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from . import schedule as sched

#: 教师分支三张表（与主库 SCHEMA 分开，避免与 students/appointments 等混杂）
TEACHER_SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    teacher_id TEXT PRIMARY KEY,
    teacher_no TEXT UNIQUE,
    name       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teacher_credentials (
    teacher_id    TEXT PRIMARY KEY REFERENCES teachers(teacher_id),
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teacher_availability (
    teacher_id TEXT NOT NULL REFERENCES teachers(teacher_id),
    weekday    INTEGER NOT NULL,
    period     INTEGER NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (teacher_id, weekday, period)
);
"""

#: 预置教师（决策 13/18）
PRESET_TEACHER_ID = "tch_T001"
PRESET_TEACHER_NAME = "心理老师"
PRESET_TEACHER_PASSWORD = "mindcare123"


def _new_id(prefix: str) -> str:
    return f"{prefix}{os.urandom(6).hex()}"


class TeacherStore:
    """教师信息分支唯一 DAO。哈希/校验函数由 db 注入（避免反向依赖 db 形成循环导入）。"""

    def __init__(self, db, hash_password, verify_password) -> None:
        self.db = db
        self._hash = hash_password
        self._verify = verify_password

    # ------------------------------------------------------------------ 身份
    def list_all(self) -> List[Dict[str, Any]]:
        return self.db.query("SELECT teacher_id, teacher_no, name FROM teachers ORDER BY teacher_id")

    def get(self, teacher_id: str) -> Optional[Dict[str, Any]]:
        return self.db.query_one("SELECT * FROM teachers WHERE teacher_id=?", (teacher_id,))

    def get_by_no(self, teacher_no: str) -> Optional[Dict[str, Any]]:
        """按工号查教师（登录用）。工号是业务键，可编辑、唯一。"""
        return self.db.query_one("SELECT * FROM teachers WHERE teacher_no=?", (teacher_no,))

    def get_name(self, teacher_id: str) -> Optional[str]:
        row = self.db.query_one("SELECT name FROM teachers WHERE teacher_id=?", (teacher_id,))
        return row["name"] if row else None

    def name_map(self) -> Dict[str, str]:
        return {r["teacher_id"]: r["name"] for r in self.list_all()}

    def create(self, name: str, password: str,
               teacher_no: Optional[str] = None) -> Dict[str, Any]:
        """新建教师 + 凭证（单事务）。工号留空则自动生成（= 内部 id）。"""
        teacher_id = _new_id("tch_")
        no = (teacher_no or "").strip() or teacher_id
        salt, digest = self._hash(password)

        def _do(cur):
            cur.execute("INSERT INTO teachers(teacher_id, teacher_no, name) VALUES(?,?,?)",
                        (teacher_id, no, name))
            cur.execute(
                "INSERT INTO teacher_credentials(teacher_id, password_hash, salt)"
                " VALUES(?,?,?)", (teacher_id, digest, salt))
        self.db.transaction(_do)
        return {"teacher_id": teacher_id, "teacher_no": no, "name": name}

    def rename(self, teacher_id: str, name: Optional[str] = None,
               teacher_no: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """改姓名 / 工号（传哪个改哪个；工号唯一，重复抛 ValueError）。"""
        if not self.get(teacher_id):
            return None
        if name is not None:
            self.db.execute("UPDATE teachers SET name=? WHERE teacher_id=?",
                            (str(name).strip(), teacher_id))
        if teacher_no is not None:
            no = str(teacher_no).strip()
            if not no:
                raise ValueError("工号不能为空")
            dup = self.get_by_no(no)
            if dup and dup["teacher_id"] != teacher_id:
                raise ValueError("工号已存在")
            self.db.execute("UPDATE teachers SET teacher_no=? WHERE teacher_id=?", (no, teacher_id))
        self.db.commit()
        return self.get(teacher_id)

    def delete(self, teacher_id: str) -> Optional[Dict[str, Any]]:
        """先删子表（凭证/可用性）再删身份，遵守外键顺序。"""
        if not self.get(teacher_id):
            return None
        self.db.execute("DELETE FROM teacher_availability WHERE teacher_id=?", (teacher_id,))
        self.db.execute("DELETE FROM teacher_credentials WHERE teacher_id=?", (teacher_id,))
        self.db.execute("DELETE FROM teachers WHERE teacher_id=?", (teacher_id,))
        self.db.commit()
        return {"teacher_id": teacher_id}

    # ------------------------------------------------------------------ 凭证
    def verify_password(self, teacher_id: str, password: str) -> bool:
        cred = self.db.query_one(
            "SELECT * FROM teacher_credentials WHERE teacher_id=?", (teacher_id,))
        if not cred:
            return False
        return self._verify(password, cred["salt"], cred["password_hash"])

    def reset_password(self, teacher_id: str, new_password: str) -> Optional[Dict[str, Any]]:
        if not self.get(teacher_id):
            return None
        salt, digest = self._hash(new_password)
        self.db.execute(
            "UPDATE teacher_credentials SET password_hash=?, salt=? WHERE teacher_id=?",
            (digest, salt, teacher_id))
        self.db.commit()
        return {"teacher_id": teacher_id, "reset": True}

    # ------------------------------------------------------------------ 每周可用时间
    def set_availability(self, teacher_id: str, items: List[dict]) -> Optional[Dict[str, Any]]:
        """替换式设定周期可用性（items=[{weekday, period, active}]）。缺行=默认可约。"""
        if not self.get(teacher_id):
            return None
        self.db.execute("DELETE FROM teacher_availability WHERE teacher_id=?", (teacher_id,))
        for it in items:
            try:
                wd, period = int(it["weekday"]), int(it["period"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (1 <= wd <= 7
                    and sched.PERIOD_INDEX_MIN <= period <= sched.PERIOD_INDEX_MAX):
                continue
            self.db.execute(
                "INSERT INTO teacher_availability(teacher_id, weekday, period, active)"
                " VALUES(?,?,?,?)",
                (teacher_id, wd, period, int(bool(it.get("active", True)))),
            )
        self.db.commit()
        return {"teacher_id": teacher_id, "availability": self.list_availability(teacher_id)}

    def list_availability(self, teacher_id: str) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT weekday, period, active FROM teacher_availability WHERE teacher_id=?",
            (teacher_id,))

    def is_available(self, teacher_id: str, weekday: int, period: int) -> bool:
        """该教师某 (weekday, period) 是否可约。缺行 = 可约；显式 active=0 才不可约。"""
        row = self.db.query_one(
            "SELECT active FROM teacher_availability"
            " WHERE teacher_id=? AND weekday=? AND period=?",
            (teacher_id, weekday, period))
        return not (row is not None and not bool(row["active"]))

    # ------------------------------------------------------------------ 种子
    def ensure_seed(self) -> None:
        if not self.get(PRESET_TEACHER_ID):
            salt, digest = self._hash(PRESET_TEACHER_PASSWORD)
            self.db.execute("INSERT INTO teachers(teacher_id, teacher_no, name) VALUES(?,?,?)",
                            (PRESET_TEACHER_ID, PRESET_TEACHER_ID, PRESET_TEACHER_NAME))
            self.db.execute(
                "INSERT INTO teacher_credentials(teacher_id, password_hash, salt)"
                " VALUES(?,?,?)", (PRESET_TEACHER_ID, digest, salt))
            self.db.commit()
