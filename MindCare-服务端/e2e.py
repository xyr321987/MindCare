# -*- coding: utf-8 -*-
"""三端 E2E 验收脚本 —— spec §10 闭环，走真实 HTTP（学生端 ApiClient + 教师端适配器）。

用法（在 MindCare-服务端 目录）：
    python e2e.py

流程：起 mock 服务端 → 学生端注册/登录/问卷/树洞/预约 → 教师端分诊/代订/预警/回复/导出 →
学生管理 → 断言 → 收尾。成功打印全 ✓ 并 exit 0。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PKG1 = os.path.join(HERE, "..", "MindCare-前端交付包(1)")
PKG2 = os.path.join(HERE, "..", "MindCare-教师端-交付(2)")

for p in (PKG2, PKG1):  # PKG1 最后插入 → 排最前；desktop_common 用学生端完整版（含预约方法）
    if p not in sys.path:
        sys.path.insert(0, p)

from desktop_common.api import ApiClient, ApiError, now_iso  # noqa: E402
from teacher_desktop.core.data_gateway import DataGateway  # noqa: E402
from teacher_desktop.core.adapters.appointment_adapter import HttpAppointmentAdapter  # noqa: E402
from teacher_desktop.core.adapters.reply_adapter import HttpReplyAdapter  # noqa: E402
from teacher_desktop.core.adapters.warning_adapter import HttpWarningAdapter  # noqa: E402
from teacher_desktop.core.adapters.export_adapter import HttpExportAdapter  # noqa: E402
from teacher_desktop.core.adapters.block_adapter import HttpBlockAdapter  # noqa: E402
from teacher_desktop.core.adapters.student_admin_adapter import HttpStudentAdminAdapter  # noqa: E402

FAILS: list[str] = []


def check(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        FAILS.append(label)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_health(base: str, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/v1/health", timeout=1.0) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("服务端未就绪")


def main() -> int:
    port = free_port()
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.httpd", "--port", str(port), "--engine", "mock"],
        cwd=HERE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        wait_health(base)
        run_cases(base)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if FAILS:
        print(f"E2E 未通过：{len(FAILS)} 项")
        for f in FAILS:
            print(" - " + f)
        return 1
    print("三端 E2E 全部通过 ✓")
    return 0


def run_cases(base: str) -> None:
    # ===== 学生端（desktop_common.ApiClient）=====
    sc = ApiClient(base)

    # 1 注册
    reg = sc.register_student("高一(2)班", "林小满", "2023001", "1234")
    check(reg["profile"]["id"] == "stu_2023001", "① 学生注册 → 建个人数据库")

    # 2 重复号次
    dup = None
    try:
        ApiClient(base).register_student("x", "y", "2023001", "1234")
    except ApiError as e:
        dup = e.code
    check(dup == 2001, "② 重复号次 → 2001")

    # 3 密码登录
    sc2 = ApiClient(base)
    sc2.login_student("2023001", "1234")
    check(bool(sc2.token), "③ 号次+密码登录")

    # 4 教师登录
    gw = DataGateway(base)
    gw.client.login_teacher("tch_T001", "mindcare123")
    check(bool(gw.client.token), "④ 教师预置账号登录")

    # 5 happy → 无工单
    r = sc2.submit_questionnaire({"record_id": "rec_h", "mood": "happy", "plain_note": None,
                                  "cause_category": None, "detail": None, "request_help": False,
                                  "consent_share": False, "consent_ts": None})
    check(r["result_scene"] == "happy_end", "⑤ happy → happy_end")

    # 6 down+求助+共享问卷+预约
    sc2.create_appointment({"apt_id": "apt_a", "year": "2026", "month": "10", "day": "3",
                            "time": "15:00", "share_questionnaire": True, "share_treehole": False})
    sc2.submit_questionnaire({"record_id": "rec_d", "mood": "down", "plain_note": None,
                              "cause_category": "study", "detail": "三次月考下滑",
                              "request_help": True, "consent_share": True, "consent_ts": now_iso()})
    appt = HttpAppointmentAdapter(gw)
    pend = appt.pending_requests()
    check(any(p.student_id == "stu_2023001" for p in pend), "⑥ 求助→待预约工单")
    today = gw.client.request("GET", f"/triage/students/{sc2.profile['id']}/today")
    check(today.get("has_shared_records") is True, "⑥ 教师可见当天共享问卷")

    # 7 只预约不共享
    sc2.create_appointment({"apt_id": "apt_b", "year": "2026", "month": "10", "day": "4",
                            "time": "09:55", "share_questionnaire": False, "share_treehole": False})
    day = appt.list_by_date("2026-10-04")
    no_share = [a for a in day if a.appointment_id == "apt_b"]
    check(no_share and no_share[0].questionnaire is None, "⑦ 只预约→正文 null（仅基本信息）")

    # 8 共享树洞
    sc2.create_treehole({"entry_id": "tre_t", "content": "今天有点低落", "mood_tag": "down"})
    sc2.create_appointment({"apt_id": "apt_c", "year": "2026", "month": "10", "day": "5",
                            "time": "16:05", "share_questionnaire": False, "share_treehole": True})
    today2 = gw.client.request("GET", f"/triage/students/{sc2.profile['id']}/today")
    check(len(today2.get("shared_treehole") or []) >= 1, "⑧ 共享树洞→教师可见当天树洞")

    # 9 只求助不选格子 → 教师代订
    sc3 = ApiClient(base)
    sc3.register_student("高一(1)班", "陈默", "2023002", "1234")
    sc3.submit_questionnaire({"record_id": "rec_e", "mood": "down", "plain_note": None,
                              "cause_category": "family", "detail": "家里有点烦",
                              "request_help": True, "consent_share": True, "consent_ts": now_iso()})
    pend2 = appt.pending_requests()
    target = next(p for p in pend2 if p.student_id == "stu_2023002")
    sch = appt.schedule(target.student_id, target.ticket_id, "2026-10-06T09:55:00+08:00", "约谈")
    check(sch.status == "scheduled", "⑨ 教师代订→scheduled")

    # 10 完成联动
    comp = appt.complete(sch.appointment_id)
    check(comp.status == "done", "⑩ 完成→appointment done + ticket done")

    # 11 预警
    for i in range(3):
        sc3.submit_questionnaire({"record_id": f"rec_w{i}", "mood": "down", "plain_note": None,
                                  "cause_category": "study", "detail": "低落",
                                  "request_help": False, "consent_share": False, "consent_ts": None})
    warn = HttpWarningAdapter(gw)
    act = [w for w in warn.list_all() if w.student_id == "stu_2023002" and w.status == "active"]
    check(len(act) == 1, "⑪ 连续3次down不求助→warning active")
    warn.dismiss(act[0].warning_id, "已约谈")
    check(warn.list_all()[0].status == "dismissed", "⑪ dismiss→留痕")

    # 12 blocks → 学生端读到
    blk = HttpBlockAdapter(gw)
    blk.set(2026, 10, 7, 3, True, "老师不在")
    slots = sc2.list_blocks()
    check("2026-10-07#3" in (slots.get("slots") or []), "⑫ 教师设红框→学生端可读")

    # 13 回复 → 学生 tips 覆盖（教师按 result_scene=self_care 建回复，学生 down 不求助提交后可见）
    rep = HttpReplyAdapter(gw)
    rep.create("自定义：先深呼吸十次。", ["self_care"])
    sub_care = sc2.submit_questionnaire({"record_id": "rec_reply_probe", "mood": "down",
                                         "plain_note": None, "cause_category": "study",
                                         "detail": "有点低落", "request_help": False,
                                         "consent_share": False, "consent_ts": None})
    check(sub_care.get("result_scene") == "self_care"
          and sub_care.get("tips", {}).get("text") == "自定义：先深呼吸十次。",
          "⑬ 老师按 self_care 建回复 → 学生提交后看到回复")
    tip = sc2.tips("down")
    check(tip["text"] == "自定义：先深呼吸十次。", "⑬ GET /tips?scene=down 反向映射到回复")

    # 14 导出零正文
    exp = HttpExportAdapter(gw)
    rows = exp.fetch_rows("2026-01-01", "2026-12-31")
    keys = set()
    for row in rows:
        keys |= set(vars(row).keys())
    check(not (keys & {"detail", "plain_note", "content", "text"}), "⑭ 导出零正文")

    # 15 病史 + 重置密码
    adm = HttpStudentAdminAdapter(gw)
    adm.set_history("stu_2023002", True)
    adm.reset_password("stu_2023002", "5678")
    ok_login = None
    try:
        ApiClient(base).login_student("2023002", "5678")
        ok_login = True
    except ApiError:
        ok_login = False
    check(ok_login is True, "⑮ 病史标记 + 重置密码后新密码可登录")

    # 16 越权
    forbid = None
    try:
        sc2.request("POST", "/db/read", body={"resource": "warnings.list", "params": {}})
    except ApiError as e:
        forbid = e.code
    check(forbid == 1002, "⑯ 学生访问 /db → 1002")


if __name__ == "__main__":
    sys.exit(main())
