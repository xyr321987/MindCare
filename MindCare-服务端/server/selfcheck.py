"""契约自检 —— 直接驱动 App.dispatch 跑 spec §10 的闭环（不依赖真 HTTP 端口）。

用法（在 MindCare-服务端 目录）：
    python -m server.selfcheck
成功打印全 ✓ 并 exit 0；任一失败打印 ✗ 并 exit 1。
"""
from __future__ import annotations

import sys
from typing import Optional

from server.db import Database
from server.httpd import App
from server import engine
from server import schedule as sched


def main() -> int:
    fails: list[str] = []
    db = Database(":memory:")
    app = App(db)

    def ok(cond, label):
        print(("  ✓ " if cond else "  ✗ ") + label)
        if not cond:
            fails.append(label)

    def call(method, path, body=None, query=None, token=None):
        return app.dispatch(method, path, query or {}, body or {}, token)

    def expect_err(method, path, body, token, code, label):
        try:
            call(method, path, body=body, token=token)
        except engine.ApiError as e:
            ok(e.code == code, f"{label} → {e.code}（期望 {code}）")
            return
        except Exception as e:  # noqa
            ok(False, f"{label} → 异常 {type(e).__name__}:{e}")
            return
        ok(False, f"{label} → 未抛错（期望 {code}）")

    # 1 健康
    h = call("GET", "/health")
    ok(h.get("engine_ready") is True, "健康检查 engine_ready=true")

    # 2 学生注册
    reg = call("POST", "/auth/register",
               body={"class_name": "高一(2)班", "name": "林小满", "seat_no": "2023001", "password": "1234"})
    ok(reg.get("token") and reg["profile"]["id"] == "stu_2023001", "学生注册 → token+profile")
    stu_token = reg["token"]

    # 3 重复注册
    expect_err("POST", "/auth/register",
               {"class_name": "x", "name": "y", "seat_no": "2023001", "password": "1234"},
               None, 2001, "重复号次注册")

    # 4 密码错误
    expect_err("POST", "/auth/login", {"role": "student", "id": "2023001", "password": "wrong"},
               None, 1001, "学生密码错误")

    # 5 正确登录
    lg = call("POST", "/auth/login", {"role": "student", "id": "2023001", "password": "1234"})
    ok(bool(lg.get("token")), "学生登录成功")
    stu_token = lg["token"]

    # 6 教师登录
    tlogin = call("POST", "/auth/login", {"role": "teacher", "id": "tch_T001", "password": "mindcare123"})
    ok(bool(tlogin.get("token")), "教师登录成功（预置口令）")
    tea_token = tlogin["token"]

    # 7 happy 提交 → 无工单
    r = call("POST", "/questionnaire/submissions", token=stu_token,
             body={"record_id": "rec_happy1", "mood": "happy", "plain_note": None,
                   "cause_category": None, "detail": None, "request_help": False,
                   "consent_share": False, "consent_ts": None})
    ok(r["result_scene"] == "happy_end", "happy → happy_end")
    ok(db.query_one("SELECT 1 FROM tickets WHERE student_id='stu_2023001'") is None, "happy 不建工单")

    # 8 down+求助 → 建 ticket
    r = call("POST", "/questionnaire/submissions", token=stu_token,
             body={"record_id": "rec_down_help", "mood": "down", "plain_note": None,
                   "cause_category": "study", "detail": "最近三次月考排名连续下滑……",
                   "request_help": True, "consent_share": True, "consent_ts": "2026-10-02T22:31:05+08:00"})
    ok(r["result_scene"] == "help_sent", "down+求助 → help_sent")
    tkt = db.query_one("SELECT * FROM tickets WHERE student_id='stu_2023001' AND status='pending'")
    ok(tkt is not None, "down+求助 自动建 ticket(pending)")

    # 9 幂等：同 record_id 重发不重复落库
    call("POST", "/questionnaire/submissions", token=stu_token,
         body={"record_id": "rec_happy1", "mood": "happy", "plain_note": None,
               "cause_category": None, "detail": None, "request_help": False,
               "consent_share": False, "consent_ts": None})
    cnt = db.query_one("SELECT COUNT(*) AS c FROM questionnaire_submissions WHERE record_id='rec_happy1'")["c"]
    ok(cnt == 1, f"幂等：同 record_id 只落 1 行（实际 {cnt}）")

    # 10 学生自助预约（共享问卷）
    apt = call("POST", "/appointments", token=stu_token,
               body={"apt_id": "apt_self1", "year": "2026", "month": "10", "day": "3",
                     "time": "15:00", "share_questionnaire": True, "share_treehole": False})
    ok(apt.get("apt_id") == "apt_self1", "学生自助预约落库")
    row = db.query_one("SELECT * FROM appointments WHERE apt_id='apt_self1'")
    ok(row and row["slot"] and row["period"], "预约派生出 slot/period")

    # 11 同 slot 重复预约被拒
    expect_err("POST", "/appointments",
               {"apt_id": "apt_self2", "year": "2026", "month": "10", "day": "3",
                "time": "15:00", "share_questionnaire": False, "share_treehole": False},
               stu_token, 2001, "同 slot 二次预约被拒")

    # 11.5 学生读自己的预约（教师代订 → 学生端同步可见，问题 4）
    sch_mine = call("POST", "/db/write", token=tea_token, body={"action": "appointments.schedule",
                    "payload": {"student_id": "stu_2023001", "year": "2026", "month": "10",
                                "day": "6", "time": "08:00", "note": "代订"}})
    ok(sch_mine.get("status") == "scheduled", "教师代订成功（供 mine 端点读取）")
    mine = call("GET", "/appointments/mine", token=stu_token)
    mine_ids = {i.get("apt_id") for i in (mine.get("items") or [])}
    ok("apt_self1" in mine_ids and sch_mine.get("appointment_id") in mine_ids,
       "GET /appointments/mine 同时含学生自约 + 教师代订")
    expect_err("GET", "/appointments/mine", None, tea_token, 1002,
               "教师访问 /appointments/mine 被拒（仅学生）")

    # 12 可见性：教师看今天数据（共享问卷可见、树洞不可见）
    today = call("GET", "/triage/students/stu_2023001/today", token=tea_token)
    ok(today["has_shared_records"] is True, "教师端 has_shared_records=true")
    ok(len(today["shared_records"]) >= 1, "shared_records 含当天问卷")
    ok(today["shared_treehole"] == [], "未共享树洞 → shared_treehole 为空")
    ok(len(today["tickets"]) >= 1, "student_today 返回 tickets（消除 G-1）")

    # 13 树洞 + 共享树洞
    call("POST", "/treehole/entries", token=stu_token,
         body={"entry_id": "tre_1", "content": "今天有点低落", "mood_tag": "down"})
    call("POST", "/appointments", token=stu_token,
         body={"apt_id": "apt_self3", "year": "2026", "month": "10", "day": "4",
               "time": "16:05", "share_questionnaire": False, "share_treehole": True})
    today2 = call("GET", "/triage/students/stu_2023001/today", token=tea_token)
    ok(len(today2["shared_treehole"]) >= 1, "共享树洞 → shared_treehole 可见")

    # 14 教师待预约列表（工单级查询，R11）
    pend = call("POST", "/db/read", token=tea_token, body={"resource": "appointments.pending", "params": {}})
    ok(any(i["student_id"] == "stu_2023001" for i in pend["items"]), "待预约列表含该生工单")

    # 15 教师代订 + 完成联动（决策 11）
    sch = call("POST", "/db/write", token=tea_token, body={"action": "appointments.schedule",
               "payload": {"student_id": "stu_2023001", "ticket_id": tkt["ticket_id"],
                           "year": "2026", "month": "10", "day": "5", "time": "09:55", "note": "约谈"}})
    ok(sch.get("status") == "scheduled", "教师代订 → scheduled")
    ok(db.query_one("SELECT status FROM tickets WHERE ticket_id=?", (tkt["ticket_id"],))["status"] == "accepted",
       "代订联动 ticket→accepted")
    comp = call("POST", "/db/write", token=tea_token, body={"action": "appointments.complete",
               "payload": {"appointment_id": sch["appointment_id"]}})
    ok(comp["status"] == "done", "完成预约 → done")
    ok(db.query_one("SELECT status FROM tickets WHERE ticket_id=?", (tkt["ticket_id"],))["status"] == "done",
       "完成联动 ticket→done")

    # 16 预警：学生 B 连续 3 次 down 不求助 → active；dismiss → dismissed
    regb = call("POST", "/auth/register",
                body={"class_name": "高一(1)班", "name": "陈默", "seat_no": "2023002", "password": "1234"})
    b_token = regb["token"]
    for i in range(3):
        call("POST", "/questionnaire/submissions", token=b_token,
             body={"record_id": f"rec_b_{i}", "mood": "down", "plain_note": None,
                   "cause_category": "family", "detail": "家里有点烦",
                   "request_help": False, "consent_share": False, "consent_ts": None})
    wlist = call("POST", "/db/read", token=tea_token, body={"resource": "warnings.list", "params": {}})
    act = [w for w in wlist["items"] if w["status"] == "active" and w["student_id"] == "stu_2023002"]
    ok(len(act) == 1, "连续 3 次 down 不求助 → warning active")
    dis = call("POST", "/db/write", token=tea_token, body={"action": "warnings.dismiss",
               "payload": {"warning_id": act[0]["warning_id"], "note": "已约谈"}})
    ok(dis["status"] == "dismissed", "dismiss → 留痕 dismissed")

    # 17 回复库 + tips 合并（问题 6）：教师按 result_scene 建回复 → 学生提交后看到回复
    call("POST", "/db/write", token=tea_token, body={"action": "replies.create",
         "payload": {"text": "自定义：先深呼吸十次。", "scenes": ["self_care"]}})
    sub_care = call("POST", "/questionnaire/submissions", token=stu_token,
                    body={"record_id": "rec_reply_probe", "mood": "down", "plain_note": None,
                          "cause_category": "study", "detail": "有点低落",
                          "request_help": False, "consent_share": False, "consent_ts": None})
    ok(sub_care.get("result_scene") == "self_care"
       and sub_care.get("tips", {}).get("text") == "自定义：先深呼吸十次。",
       "教师按 self_care 建回复 → 学生 down 不求助提交后看到自定义回复")
    tip = call("GET", "/tips", query={"scene": "down"}, token=stu_token)
    ok(tip["text"] == "自定义：先深呼吸十次。", "GET /tips?scene=down 反向映射到 self_care 回复")

    # 18 导出零正文
    exp = call("POST", "/db/read", token=tea_token, body={"action": None, "resource": "export.rows",
               "params": {"start": "2026-01-01", "end": "2026-12-31"}})
    keys = set()
    for row in exp["items"]:
        keys |= set(row.keys())
    ok(not (keys & {"detail", "plain_note", "content", "text"}), f"导出零正文（列 {sorted(keys)}）")

    # 19 越权：学生打 /db/read → 1002
    expect_err("POST", "/db/read", {"resource": "warnings.list", "params": {}},
               stu_token, 1002, "学生访问 /db/read")
    # 教师打树洞 → 1002（无路由；此处 route 只对学生开放，教师命中 1002 或 2002）
    try:
        call("GET", "/treehole/entries", query={"date": "2026-10-02"}, token=tea_token)
        ok(False, "教师读树洞应被拒")
    except engine.ApiError as e:
        ok(e.code in (1002, 2002), f"教师读树洞被拒（{e.code}）")

    # ============ 调度系统升级（咨询室/冲突/改期/取消/爽约/批量/统计/日志）============
    # 20 咨询室
    rooms = call("POST", "/db/read", token=tea_token,
                 body={"resource": "rooms.list", "params": {}})
    ok(any(r["name"] == "咨询室A" for r in rooms["items"]), "默认咨询室A已预置")
    room_b = call("POST", "/db/write", token=tea_token,
                  body={"action": "rooms.create", "payload": {"name": "咨询室B"}})
    ok(bool(room_b.get("room_id")), "新建咨询室B")
    teachers = call("POST", "/db/read", token=tea_token,
                    body={"resource": "teachers.list", "params": {}})
    ok(any(t["teacher_id"] == "tch_T001" for t in teachers["items"]), "教师列表含预置教师")

    # 21 冲突检测：同咨询室同时段
    sched_a = call("POST", "/db/write", token=tea_token, body={"action": "appointments.schedule",
                   "payload": {"student_id": "stu_2023001", "year": "2026", "month": "11", "day": "2",
                               "time": "10:00", "room_id": "rm_default", "teacher_id": "tch_T001"}})
    ok(sched_a.get("status") == "scheduled", "预约A（咨询室A 10:00）成功")
    ok(sched_a.get("teacher_name") == "心理老师" and sched_a.get("room_name") == "咨询室A",
       "预约行返回教师/咨询室名称")
    expect_err("POST", "/db/write",
               {"action": "appointments.schedule",
                "payload": {"student_id": "stu_2023002", "year": "2026", "month": "11", "day": "2",
                            "time": "10:00", "room_id": "rm_default", "teacher_id": "tch_T001"}},
               tea_token, 2001, "同咨询室同时段冲突被拒")

    # 22 改期（留痕）
    resch = call("POST", "/db/write", token=tea_token, body={"action": "appointments.reschedule",
                 "payload": {"appointment_id": sched_a["appointment_id"], "year": "2026", "month": "11",
                             "day": "3", "time": "14:00", "room_id": "rm_default",
                             "note": "学生请假改期"}})
    ok(resch.get("status") == "scheduled"
       and resch.get("rescheduled_from") == sched_a["appointment_id"], "改期成功并留痕")

    # 23 取消（记录原因）
    can = call("POST", "/db/write", token=tea_token, body={"action": "appointments.cancel",
               "payload": {"appointment_id": resch["appointment_id"], "reason": "学生临时有事"}})
    ok(can.get("status") == "cancelled" and can.get("cancel_reason") == "学生临时有事",
       "取消并记录原因")

    # 24 爽约
    sched_b = call("POST", "/db/write", token=tea_token, body={"action": "appointments.schedule",
                   "payload": {"student_id": "stu_2023002", "year": "2026", "month": "11", "day": "5",
                               "time": "09:00", "room_id": room_b["room_id"]}})
    noshow = call("POST", "/db/write", token=tea_token, body={"action": "appointments.no_show",
                  "payload": {"appointment_id": sched_b["appointment_id"], "note": "未到未请假"}})
    ok(noshow.get("status") == "no_show", "爽约标记")

    # 25 批量关闭时段
    batch = call("POST", "/db/write", token=tea_token, body={"action": "blocks.batch_set",
                 "payload": {"items": [{"year": "2026", "month": "11", "day": "6", "period": "3"},
                                       {"year": "2026", "month": "11", "day": "6", "period": "4"}],
                             "active": True, "reason": "教师会议"}})
    ok(len(batch.get("slots") or []) == 2, "批量关闭 2 个时段")

    # 26 统计
    stats = call("POST", "/db/read", token=tea_token, body={"resource": "stats.appointments",
                 "params": {"start": "2026-11-01", "end": "2026-11-30"}})
    ok(isinstance(stats.get("total"), int) and isinstance(stats.get("completion_rate"), (int, float)),
       "预约统计返回总量与完成率")

    # 27 操作日志
    events = call("POST", "/db/read", token=tea_token, body={"resource": "appointments.events",
                 "params": {"appointment_id": resch["appointment_id"]}})
    acts = [e["action"] for e in events.get("items") or []]
    ok("scheduled" in acts and "rescheduled" in acts and "cancelled" in acts,
       f"操作日志含 scheduled/rescheduled/cancelled（实际 {acts}）")

    # 28 候补 + 取消自动递补
    occ = call("POST", "/db/write", token=tea_token, body={"action": "appointments.schedule",
               "payload": {"student_id": "stu_2023002", "year": "2026", "month": "12", "day": "10",
                           "time": "10:00", "room_id": "rm_default", "teacher_id": "tch_T001"}})
    ok(occ.get("status") == "scheduled", "占满 12-10 10:00 时段")
    wl = call("POST", "/waitlist", token=stu_token,
              body={"wait_id": "wait_1", "year": "2026", "month": "12", "day": "10", "time": "10:00"})
    ok(wl.get("status") == "waiting", "学生加入候补（时段已满）")
    ok(call("POST", "/waitlist", token=stu_token,
            body={"wait_id": "wait_1", "year": "2026", "month": "12", "day": "10", "time": "10:00"}).get("wait_id") == "wait_1",
       "候补加入幂等")
    call("POST", "/db/write", token=tea_token, body={"action": "appointments.cancel",
         "payload": {"appointment_id": occ["appointment_id"], "reason": "临时取消"}})
    wrow = db.query_one("SELECT * FROM waitlist WHERE wait_id='wait_1'")
    ok(wrow["status"] == "filled" and wrow["filled_apt_id"], "取消后自动递补（filled）")
    filled = db.query_one("SELECT * FROM appointments WHERE apt_id=?", (wrow["filled_apt_id"],))
    ok(filled is not None and filled["student_id"] == "stu_2023001" and filled["status"] == "scheduled",
       "递补生成预约（学生=候补者）")

    # 29 候补 FIFO
    occ2 = call("POST", "/db/write", token=tea_token, body={"action": "appointments.schedule",
                "payload": {"student_id": "stu_2023002", "year": "2026", "month": "12", "day": "11",
                            "time": "10:00", "room_id": "rm_default", "teacher_id": "tch_T001"}})
    call("POST", "/waitlist", token=stu_token,
         body={"wait_id": "wait_a", "year": "2026", "month": "12", "day": "11", "time": "10:00"})
    regc = call("POST", "/auth/register",
                body={"class_name": "高一(4)班", "name": "王五", "seat_no": "2023004", "password": "1234"})
    call("POST", "/waitlist", token=regc["token"],
         body={"wait_id": "wait_b", "year": "2026", "month": "12", "day": "11", "time": "10:00"})
    call("POST", "/db/write", token=tea_token, body={"action": "appointments.cancel",
         "payload": {"appointment_id": occ2["appointment_id"], "reason": "取消"}})
    ok(db.query_one("SELECT status FROM waitlist WHERE wait_id='wait_a'")["status"] == "filled"
       and db.query_one("SELECT status FROM waitlist WHERE wait_id='wait_b'")["status"] == "waiting",
       "候补 FIFO：早加入者先递补")

    # 30 教师管理 + 多教师登录
    tc = call("POST", "/db/write", token=tea_token, body={"action": "teachers.create",
              "payload": {"name": "李老师", "password": "abcd1234"}})
    ok(bool(tc.get("teacher_id")), "新建教师（含凭证）")
    tlogin2 = call("POST", "/auth/login",
                   {"role": "teacher", "id": tc["teacher_id"], "password": "abcd1234"})
    ok(bool(tlogin2.get("token")), "新教师可登录")
    ok(call("POST", "/db/write", token=tea_token, body={"action": "teachers.delete",
            "payload": {"teacher_id": tc["teacher_id"]}}).get("teacher_id") == tc["teacher_id"],
       "删除非预置教师")

    # 31 教师周期可用性冲突（RFC 7953 式）
    wd11 = sched.weekday_from_date(2026, 12, 11)
    call("POST", "/db/write", token=tea_token, body={"action": "teachers.availability.set",
         "payload": {"teacher_id": "tch_T001",
                     "items": [{"weekday": wd11, "period": 3, "active": False}]}})
    expect_err("POST", "/db/write",
               {"action": "appointments.schedule",
                "payload": {"student_id": "stu_2023002", "year": "2026", "month": "12", "day": "11",
                            "time": "10:00", "room_id": "rm_default", "teacher_id": "tch_T001"}},
               tea_token, 2001, "教师该时段不可约被拒")

    # 32 教师个人停诊冲突（blocks.teacher_id）
    call("POST", "/db/write", token=tea_token, body={"action": "blocks.batch_set",
         "payload": {"items": [{"year": "2026", "month": "12", "day": "12", "period": "3"}],
                     "active": True, "reason": "个人请假", "teacher_id": "tch_T001"}})
    expect_err("POST", "/db/write",
               {"action": "appointments.schedule",
                "payload": {"student_id": "stu_2023002", "year": "2026", "month": "12", "day": "12",
                            "time": "10:00", "room_id": "rm_default", "teacher_id": "tch_T001"}},
               tea_token, 2001, "教师个人停诊冲突被拒")

    # 33 教师日历 + 候补列表资源
    cal = call("POST", "/db/read", token=tea_token, body={"resource": "teacher_calendar",
               "params": {"teacher_id": "tch_T001", "start": "2026-12-01", "end": "2026-12-31"}})
    ok(isinstance(cal.get("appointments"), list) and isinstance(cal.get("availability"), list),
       "教师日历返回预约 + 可用性")
    wlist = call("POST", "/db/read", token=tea_token, body={"resource": "waitlist.list",
                 "params": {"year": "2026", "month": "12"}})
    ok(any(w["wait_id"] == "wait_b" for w in wlist["items"]), "候补列表含 waiting 条目")

    # 34 情绪可视化端点：区间内每日 mood（取当天最新一条，同日多次以 rowid 断序）
    today = sched.today_str()
    call("POST", "/questionnaire/submissions", token=stu_token,
         body={"record_id": "rec_mood_probe", "mood": "happy", "plain_note": None,
               "cause_category": None, "detail": None,
               "request_help": False, "consent_share": False, "consent_ts": None})
    mr = call("GET", "/profile/mood/range",
              query={"start": today, "end": today}, token=stu_token)
    ok(bool(mr.get("items")) and mr["items"][0]["date"] == today
       and mr["items"][0]["mood"] == "happy",
       "情绪区间端点返回每日最新 mood（happy）")
    empty = call("GET", "/profile/mood/range",
                 query={"start": "2020-01-01", "end": "2020-01-07"}, token=stu_token)
    ok(empty.get("items") == [], "区间无记录 → 空 items")

    print()
    if fails:
        print(f"自检未通过：{len(fails)} 项")
        for f in fails:
            print(" - " + f)
        return 1
    print(f"契约自检全部通过 ✓（闭环覆盖：注册/登录/问卷/树洞/预约/工单/预警/回复/导出/越权/幂等）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
