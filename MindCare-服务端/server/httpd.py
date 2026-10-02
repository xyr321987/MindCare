"""HTTP 服务层 —— 契约 §4 的全部端点 + 信封/鉴权（纯 stdlib `http.server`）。

启动：
    python -m server.httpd --port 8080 --data-dir ./data

运行纪律（§8）：ThreadingHTTPServer 多线程接收，但所有 DB 访问已收敛到
`Database` 的单连接 + 全局锁（串行写），规避 SQLite 并发写锁（R1）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from . import engine, schedule as sched
from .db import Database

VERSION = "1.1.0"
API_ROOT = "/api/v1"

#: 端点 → (方法, 所需角色 或 None=公共, handler 名)
# 角色："student" / "teacher" / "any"（学生或教师）
ROUTES = [
    ("GET",    "/health",                        None,       "health"),
    ("POST",   "/auth/register",                 None,       "register"),
    ("POST",   "/auth/login",                    None,       "login"),
    ("POST",   "/questionnaire/submissions",     "student",  "submit_questionnaire"),
    ("GET",    "/profile/me",                    "student",  "my_profile"),
    ("GET",    "/profile/me/dates",              "student",  "my_dates"),
    ("POST",   "/treehole/entries",              "student",  "create_treehole"),
    ("GET",    "/treehole/entries",              "student",  "my_treehole"),
    ("GET",    "/tips",                          "student",  "tips"),
    ("GET",    "/triage/list",                   "teacher",  "triage_list"),
    ("GET",    "/triage/students/{id}/today",    "teacher",  "student_today"),
    ("POST",   "/triage/tickets/{id}/ack",       "teacher",  "ack_ticket"),
    ("POST",   "/appointments",                  "student",  "create_appointment"),
    ("GET",    "/appointments",                  "teacher",  "list_appointments"),
    ("GET",    "/appointments/blocks",           "any",      "list_blocks"),
    ("POST",   "/appointments/blocks",           "teacher",  "set_block"),
    ("GET",    "/appointments/mine",             "student",  "my_appointments"),
    ("POST",   "/waitlist",                      "student",  "join_waitlist"),
    ("GET",    "/waitlist/mine",                 "student",  "my_waitlist"),
    ("POST",   "/db/read",                       "teacher",  "db_read"),
    ("POST",   "/db/write",                      "teacher",  "db_write"),
]


class App:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ 分发
    def dispatch(self, method: str, path: str, query: dict, body: dict,
                 token: Optional[str]):
        session = engine.resolve_session(self.db, token)
        role = session["role"] if session else None
        subject = session["subject_id"] if session else None

        for m, pattern, required, handler in ROUTES:
            if m != method:
                continue
            params = _match(pattern, path)
            if params is None:
                continue
            if required == "student" and role != "student":
                if role is None:
                    raise engine.ApiError(1001, "未登录或 token 过期")
                raise engine.ApiError(1002, "无权限")
            if required == "teacher" and role != "teacher":
                if role is None:
                    raise engine.ApiError(1001, "未登录或 token 过期")
                raise engine.ApiError(1002, "无权限")
            if required == "any" and role is None:
                raise engine.ApiError(1001, "未登录或 token 过期")
            return self._run(handler, subject, params, query, body)
        raise engine.ApiError(2002, "接口不存在")

    def _run(self, handler: str, subject: Optional[str], params: dict,
             query: dict, body: dict):
        db = self.db
        if handler == "health":
            return {"status": "ok", "version": VERSION,
                    "server_time": sched.now_iso(), "engine_ready": True}
        if handler == "register":
            return engine.register(db, body)
        if handler == "login":
            return engine.login(db, body)
        if handler == "submit_questionnaire":
            return engine.submit_questionnaire(db, subject, body)
        if handler == "my_profile":
            return engine.my_profile(db, subject, query.get("date") or sched.today_str())
        if handler == "my_dates":
            return engine.my_dates(db, subject)
        if handler == "create_treehole":
            return engine.create_treehole(db, subject, body)
        if handler == "my_treehole":
            return engine.my_treehole(db, subject, query.get("date") or sched.today_str())
        if handler == "tips":
            return engine.tips(db, query.get("scene") or "")
        if handler == "triage_list":
            return engine.triage_list(db, query.get("since"))
        if handler == "student_today":
            return engine.student_today(db, params["id"])
        if handler == "ack_ticket":
            return engine.ack_ticket(db, params["id"], body.get("action"), body.get("note"))
        if handler == "create_appointment":
            return engine.create_appointment(db, subject, body)
        if handler == "list_appointments":
            date = query.get("date")
            today = sched.today_str()
            rows = self.db.query(
                "SELECT * FROM appointments WHERE date=? ORDER BY period, time_start",
                (date or today,),
            )
            items = []
            for a in rows:
                item = dict(a)
                item["questionnaire"] = None
                item["treehole"] = None
                if a["share_questionnaire"] and engine._is_today_created(a, today):
                    item["questionnaire"] = self.db.query(
                        "SELECT record_id, mood, cause_category, detail FROM questionnaire_submissions"
                        " WHERE student_id=? AND date=? ORDER BY ts DESC",
                        (a["student_id"], today),
                    )
                if a["share_treehole"] and engine._is_today_created(a, today):
                    item["treehole"] = self.db.query(
                        "SELECT entry_id, content, mood_tag FROM treehole_entries"
                        " WHERE student_id=? AND date=? ORDER BY ts DESC",
                        (a["student_id"], today),
                    )
                items.append(item)
            return {"date": date or today, "items": items}
        if handler == "list_blocks":
            return engine.list_blocks(db)
        if handler == "my_appointments":
            return engine.my_appointments(db, subject)
        if handler == "join_waitlist":
            return engine.join_waitlist(db, subject, body)
        if handler == "my_waitlist":
            return engine.my_waitlist(db, subject)
        if handler == "set_block":
            return engine.set_block(db, subject, body)
        if handler == "db_read":
            return engine.db_read(db, body.get("resource") or "", body.get("params") or {})
        if handler == "db_write":
            return engine.db_write(db, body.get("action") or "", body.get("payload") or {})
        raise engine.ApiError(3001, "未实现的 handler")


def _match(pattern: str, path: str) -> Optional[dict]:
    pparts = pattern.split("/")
    parts = path.split("/")
    if len(pparts) != len(parts):
        return None
    params: dict = {}
    for p, q in zip(pparts, parts):
        if p.startswith("{") and p.endswith("}"):
            params[p[1:-1]] = urllib.parse.unquote(q)
        elif p != q:
            return None
    return params


# --------------------------------------------------------------------------- HTTP handler
class Handler(BaseHTTPRequestHandler):
    server_version = "MindCare/1.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # 安静一点，避免刷屏
        pass

    def _reply(self, code: int, payload: dict, http_status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(http_status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    def _token(self) -> Optional[str]:
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return None

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def _handle(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if not path.startswith(API_ROOT):
            self._reply(2002, {"code": 2002, "message": "接口不存在", "data": None}, 404)
            return
        rel = path[len(API_ROOT):] or "/"
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        body = self._read_body()
        token = self._token()
        try:
            data = self.app.dispatch(self.command, rel, query, body, token)
            self._reply(0, {"code": 0, "message": "ok", "data": data})
        except engine.ApiError as exc:
            status = engine.HTTP_STATUS.get(exc.code, 500)
            self._reply(exc.code, {"code": exc.code, "message": exc.message, "data": None}, status)
        except Exception as exc:  # noqa: BLE001 - 兜底：不得让线程崩掉
            self._reply(3001, {"code": 3001, "message": f"服务端内部错误：{exc}", "data": None}, 500)


class ThreadedServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, app: App):
        super().__init__(addr, Handler)
        self.app = app


# --------------------------------------------------------------------------- CLI
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MindCare 服务端 (SQLite)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--data-dir", default="./data")
    p.add_argument("--engine", choices=("real", "mock"), default="real",
                   help="real=落盘 SQLite；mock=内存 SQLite（重启即空）")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.engine == "mock":
        db_path = ":memory:"
    else:
        os.makedirs(args.data_dir, exist_ok=True)
        db_path = os.path.join(args.data_dir, "MindCare.db")
    db = Database(db_path)
    app = App(db)
    srv = ThreadedServer(("127.0.0.1", args.port), app)
    print(f"MindCare 服务端 v{VERSION}  engine={args.engine}  "
          f"http://127.0.0.1:{args.port}{API_ROOT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
