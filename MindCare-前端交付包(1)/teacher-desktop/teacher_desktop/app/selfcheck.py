r"""教师端 offscreen 自检 + **双端预约时间一致性**验收。

跑法::

    $env:QT_QPA_PLATFORM='offscreen'
    Set-Location '<本包根目录>'
    $env:PYTHONPATH = "$PWD;$PWD\teacher-desktop;$PWD\student-desktop"
    & $py -m teacher_desktop.app.selfcheck

覆盖
----
1. **环境**：PySide6 / offscreen / `desktop_common` 各模块 / `build_qss()`；
2. **课表事实源**：8 节课（含第 8 节笔误修正）、星期换算与**真实日历**逐日交叉验证、
   周 / 月周换算；
3. **不可预约库**：append-only + `active` 开关、toggle、坏行跳过；
4. **预约库 v1.1 字段**：`period` / `weekday` / `slot` 落地，v1.0 老记录可回推；
5. **实时同步**：教师改设定 → **不手动刷新**、学生端自己变成红框且不可点；
6. **双端同一张表**：同一格子两端状态一致；
7. **对比度**：新增格子配色 ≥ 4.5:1（UI约定 §2 硬要求 1）；
8. **界面**：offscreen 构建完整控件树 + 关键控件断言 + 截图 ≥ 3 张；
9. **纪律**：无硬编码中文界面文案、主线程未发请求。

⚠️ 所有落库都指到临时目录（`MINDCAKE_*_DIR`），**绝不动**开发者真实的
`%LOCALAPPDATA%\MindCare`。

退出码 0 = 全部通过；1 = 有失败项。
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
import tempfile
import threading
import time
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---- 必须在 import QtWidgets 之前设 offscreen ---------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ---- 数据目录隔离（**必须在 import 存储模块之前**）----------------------------
_TMP_ROOT = Path(tempfile.gettempdir()) / "mindcare-teacher-selfcheck"
SESSION_DIR = _TMP_ROOT / "session"
APPOINTMENT_DIR = _TMP_ROOT / "appointments"
BLOCK_DIR = _TMP_ROOT / "blocks"
os.environ["MINDCAKE_SESSION_DIR"] = str(SESSION_DIR)
os.environ["MINDCAKE_APPOINTMENT_DIR"] = str(APPOINTMENT_DIR)
os.environ["MINDCAKE_BLOCK_DIR"] = str(BLOCK_DIR)
for _key in ("MINDCAKE_SESSION_DIR", "MINDCAKE_APPOINTMENT_DIR", "MINDCAKE_BLOCK_DIR"):
    assert _key in os.environ

# ---- sys.path 引导（目录名含连字符，不是合法包名）------------------------------
_APP_DIR = Path(__file__).resolve().parent
_PKG_PARENT = _APP_DIR.parents[1]              # .../teacher-desktop
ROOT = _PKG_PARENT.parent                      # MindCare-前端交付包/
for _path in (str(_PKG_PARENT), str(ROOT),
              str(ROOT / "student-desktop")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

SHOT_DIR = _APP_DIR.parent / "__screenshots__"

from PySide6 import QtWidgets                                    # noqa: E402
from PySide6.QtCore import Qt, QThreadPool                       # noqa: E402

from desktop_common import (                                     # noqa: E402
    appointments as appt_store,
    schedule as schedule_mod,
    schedule_store,
    sync as sync_mod,
    theme,
)
from desktop_common.api import ApiClient                         # noqa: E402
from desktop_common.copy import COPY                             # noqa: E402
from desktop_common.schedule_grid import (                       # noqa: E402
    SLOT_STATES, ScheduleBoard, SlotCell,
)
from server import seed_data                                     # noqa: E402
from server.app import create_server                             # noqa: E402
from teacher_desktop.app.main import TeacherMainWindow           # noqa: E402
from teacher_desktop.app.worker import STATS, TaskRunner         # noqa: E402
from teacher_desktop.ui.schedule import ScheduleTab              # noqa: E402

from student_desktop.ui.pages import AppointmentPage             # noqa: E402


# --------------------------------------------------------------------------- 报告


class Report:
    """极简检查清单（每条打印 `[PASS]/[FAIL]` + 证据行）。"""

    def __init__(self) -> None:
        self.items: List[Tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, evidence: str = "") -> bool:
        self.items.append((name, bool(ok), evidence))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        for line in str(evidence).splitlines():
            print(f"       {line}")
        return bool(ok)

    @property
    def failures(self) -> List[Tuple[str, str]]:
        return [(name, ev) for name, ok, ev in self.items if not ok]

    def summary(self) -> str:
        total = len(self.items)
        failed = len(self.failures)
        return (f"共 {total} 项：通过 {total - failed}，未通过 {failed}\n"
                + "\n".join(f"  FAIL {name}" for name, _ in self.failures))


REPORT = Report()


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def pump(app: QtWidgets.QApplication, ms: int) -> None:
    """让事件循环跑 `ms` 毫秒（offscreen 下用来等定时器 / 截图布局）。"""
    end = time.time() + max(0, ms) / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


# --------------------------------------------------------------------------- ① 环境


def check_environment() -> None:
    import PySide6

    section("① 环境")
    REPORT.check("PySide6 可用 + offscreen 平台",
                 os.environ.get("QT_QPA_PLATFORM") == "offscreen",
                 f"PySide6 {PySide6.__version__}；"
                 f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM')}")

    missing = [name for name in ("api", "copy", "models", "session", "theme",
                                 "widgets", "appointments", "schedule",
                                 "schedule_store", "schedule_grid", "sync")
               if not (ROOT / "desktop_common" / f"{name}.py").exists()]
    REPORT.check("共享包模块齐全（含本轮新增的 4 个）", not missing,
                 f"desktop_common 共 11 个模块；缺失 {missing}")

    qss = theme.build_qss()
    REPORT.check("build_qss() 无禁用的动画属性（UI约定 §2 硬要求 3）",
                 not any(pattern in qss for pattern in theme.FORBIDDEN_QSS_PATTERNS),
                 f"QSS {len(qss)} 字符；禁用模式命中 0")

    REPORT.check("课表样式已登记（红框 / 选中 / 图例）",
                 all(token in qss for token in
                     ('#SlotCell[slotState="blocked"]', '#SlotCell[slotSelected="yes"]',
                      "#SwatchBlocked", "#MonthButton")),
                 "blocked / slotSelected / SwatchBlocked / MonthButton 四条规则齐备")


# --------------------------------------------------------------------------- ② 课表事实源


def check_schedule_facts() -> None:
    section("② 课表事实源（节次 / 星期 / 2026 真实日历）")

    REPORT.check("8 节课，起止钟点覆盖 08:00–17:00",
                 len(schedule_mod.PERIODS) == 8
                 and schedule_mod.PERIODS[0]["start"] == "08:00"
                 and schedule_mod.PERIODS[-1]["end"] == "16:50",
                 " / ".join(f"{p['index']}:{p['start']}~{p['end']}"
                            for p in schedule_mod.PERIODS))

    REPORT.check("第 8 节笔误已修正（原文 16:05~16:00 结束早于开始）",
                 schedule_mod.PERIODS[7]["start"] == "16:05"
                 and schedule_mod.PERIODS[7]["end"] == "16:50"
                 and schedule_mod.PERIODS[7]["end"] > schedule_mod.PERIODS[7]["start"],
                 f"第8节 = {schedule_mod.period_time_text(8)}（需求原文为 16:05~16:00）")

    # 星期换算与**真实日历**逐日交叉验证（2026 全年）
    mismatched: List[str] = []
    cursor = date(2026, 1, 1)
    while cursor.year == 2026:
        expect = cursor.weekday() + 1          # datetime: 0=周一
        got = schedule_mod.weekday_from_date(cursor.year, cursor.month, cursor.day)
        if expect != got:
            mismatched.append(f"{cursor.isoformat()}: expect {expect} got {got}")
        cursor += timedelta(days=1)
    REPORT.check("2026 全年 365 天的星期几与真实日历一致", not mismatched,
                 f"逐日比对 365 天，不一致 {len(mismatched)} 天"
                 + (f"；例：{mismatched[:3]}" if mismatched else ""))

    week = schedule_mod.week_dates(2026, 10, 5)
    REPORT.check("周换算：7 天、周一起、含指定日",
                 len(week) == 7 and week[0] == (2026, 10, 5)
                 and week[0][2] == 5,
                 f"2026-10-05 所在周 = {week}")

    weeks = schedule_mod.month_weeks(2026, 10)
    REPORT.check("月周换算：2026 年 10 月覆盖 5 周（首周含 9 月的几天）",
                 len(weeks) == 5 and weeks[0][0] == (2026, 9, 28),
                 f"首周 = {weeks[0]}；共 {len(weeks)} 周")

    REPORT.check("格子 ID 可逆（`YYYY-MM-DD#P` ↔ 年月日节）",
                 schedule_mod.parse_slot_id(schedule_mod.slot_id(2026, 10, 5, 3))
                 == (2026, 10, 5, 3)
                 and schedule_mod.parse_slot_id("bad") is None,
                 f"{schedule_mod.slot_id(2026, 10, 5, 3)} -> "
                 f"{schedule_mod.parse_slot_id(schedule_mod.slot_id(2026, 10, 5, 3))}")


# --------------------------------------------------------------------------- ③ 不可预约库


def check_block_store() -> None:
    section("③ 不可预约时段库（append-only + active 开关）")
    path = BLOCK_DIR / "schedule_blocks.jsonl"
    if path.exists():
        path.unlink()

    REPORT.check("初始为空", schedule_store.blocked_slots() == set(),
                 f"blocked = {sorted(schedule_store.blocked_slots())}")

    ok1 = schedule_store.set_blocked(2026, 10, 5, 3, True, operator="tch_1001")
    REPORT.check("设成不可预约 → 该格在 blocked 集合里",
                 ok1 and schedule_store.is_blocked(2026, 10, 5, 3)
                 and not schedule_store.is_blocked(2026, 10, 5, 4),
                 f"is_blocked(2026-10-05#3)="
                 f"{schedule_store.is_blocked(2026, 10, 5, 3)}；#4="
                 f"{schedule_store.is_blocked(2026, 10, 5, 4)}")

    schedule_store.set_blocked(2026, 10, 5, 3, False, operator="tch_1001")
    REPORT.check("恢复可预约（**只追加一行**，不改写历史）",
                 not schedule_store.is_blocked(2026, 10, 5, 3)
                 and len(schedule_store.list_blocks()) == 2,
                 f"记录行数={len(schedule_store.list_blocks())}（设 1 行 + 取消 1 行）；"
                 f"当前 blocked={sorted(schedule_store.blocked_slots())}")

    schedule_store.set_blocked(2026, 10, 5, 3, True, operator="tch_1001")
    REPORT.check("同一格「设→取消→再设」取**最后一条**为准",
                 schedule_store.is_blocked(2026, 10, 5, 3)
                 and len(schedule_store.list_blocks()) == 3,
                 f"行数={len(schedule_store.list_blocks())}；"
                 f"blocked={sorted(schedule_store.blocked_slots())}")

    toggled = schedule_store.toggle_block(2026, 10, 5, 3)
    REPORT.check("toggle 切换返回**切换后**的状态", toggled is False,
                 f"toggle(2026-10-05#3) -> {toggled}")

    REPORT.check("非法格子不落库（月份/节次/日期越界）",
                 schedule_store.set_blocked(2026, 13, 5, 3, True) is False
                 and schedule_store.set_blocked(2026, 10, 5, 99, True) is False
                 and schedule_store.set_blocked(2026, 2, 30, 3, True) is False,
                 "13 月 / 第99节 / 2月30日 三条全部被拒")

    path.write_text(path.read_text(encoding="utf-8") + "{坏行\n",
                    encoding="utf-8")
    REPORT.check("坏行跳过（其余行照常读出）",
                 len(schedule_store.list_blocks()) == 4,
                 f"追加坏行后仍读出 {len(schedule_store.list_blocks())} 行有效记录")

    for file_path in (path, APPOINTMENT_DIR / "appointments.jsonl"):
        if file_path.exists():
            file_path.unlink()


# --------------------------------------------------------------------------- ④ 预约库 v1.1


def check_appointment_fields() -> None:
    section("④ 预约记录：v1.0 字段不变 + v1.1 追加课表定位")
    path = APPOINTMENT_DIR / "appointments.jsonl"
    if path.exists():
        path.unlink()

    record = appt_store.build_appointment_record(
        student_id="stu_2023001", name="林小满", class_name="高一(2)班",
        appointment={"year": "2026", "month": "10", "day": "5", "period": "3",
                     "share_questionnaire": True, "share_treehole": False},
    )
    v1_fields = ("apt_id", "student_id", "name", "class_name", "year", "month",
                 "day", "time", "share_questionnaire", "share_treehole", "created_ts")
    REPORT.check("v1.0 的 11 个字段一个不少（键名/类型不变）",
                 all(key in record for key in v1_fields),
                 f"{sorted(record)}")

    REPORT.check("v1.1 追加 period / weekday / 起止钟点 / slot",
                 record.get("period") == "3" and record.get("weekday") == "1"
                 and record.get("time") == "09:55"
                 and record.get("time_start") == "09:55"
                 and record.get("time_end") == "10:40"
                 and record.get("slot") == "2026-10-05#3",
                 f"period={record.get('period')} weekday={record.get('weekday')} "
                 f"time={record.get('time')} "
                 f"{record.get('time_start')}-{record.get('time_end')} "
                 f"slot={record.get('slot')}")

    appt_store.append_appointment(record, path=path)
    REPORT.check("按格子查得到这条预约（教师端「谁约了」用）",
                 len(appt_store.appointments_at(2026, 10, 5, 3, path=path)) == 1
                 and appt_store.appointment_slots(path=path).get("2026-10-05#3")
                 is not None,
                 f"appointments_at -> "
                 f"{[r.get('name') for r in appt_store.appointments_at(2026, 10, 5, 3, path=path)]}")

    # v1.0 老记录（只有 time，没有 period）也要能定位
    legacy = {"apt_id": "apt_legacy", "student_id": "stu_2023002", "name": "旧记录",
              "class_name": None, "year": "2026", "month": "10", "day": "5",
              "time": "15:30", "share_questionnaire": False, "share_treehole": False,
              "created_ts": "2026-10-02T22:31:05+08:00"}
    REPORT.check("v1.0 老记录（无 period）按起始钟点回推节次",
                 appt_store.record_slot(legacy) == "2026-10-05#7",
                 f"time=15:30 -> {appt_store.record_slot(legacy)}（第7节 15:11~16:00）")

    if path.exists():
        path.unlink()


# --------------------------------------------------------------------------- ⑤⑥ 界面 + 同步闭环


def _future_day(offset: int = 5) -> Tuple[int, int, int]:
    day = date.today() + timedelta(days=offset)
    return day.year, day.month, day.day


def _start_server() -> Any:
    """启动一台 in-process 后端（随机端口 + 独立临时库），返回 server 对象。

    教师端自检「实时同步闭环」与「双端同一张表」必须打**真实后端**（HTTP 共享
    SQLite），不能再靠本地 JSONL 文件签名轮询 —— 否则测的是两条互不相干的本地链。
    """
    tmp = Path(tempfile.mkdtemp(prefix="mindcare-teacher-selfcheck-"))
    server = create_server("127.0.0.1", 0, db_path=tmp / "mindcare.db")
    server._selfcheck_url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    probe = ApiClient(server._selfcheck_url, session_path=False)
    for _ in range(200):
        try:
            probe.health()
            break
        except Exception:                         # noqa: BLE001 - 等服务就绪
            time.sleep(0.02)
    return server


def _stop_server(server: Any) -> None:
    server.shutdown()
    server.server_close()
    server.db.close()


def _login_client(url: str, role: str) -> ApiClient:
    """登录并返回**已带 token** 的契约客户端（自检装置，非 UI 代码路径）。"""
    client = ApiClient(url, session_path=False)
    if role == "teacher":
        client.login_teacher(seed_data.TEACHER_NO, seed_data.TEACHER_PASSWORD)
    else:
        client.login_student("stu_2023001")
    return client


def check_ui_and_sync(app: QtWidgets.QApplication, teacher_client: Any,
                      student_client: Any) -> Tuple[Any, Any]:
    section("⑤ 界面 + 实时同步闭环（教师改 → 学生端自己变红框，走 HTTP 共享库）")

    window = TeacherMainWindow(client=teacher_client)
    window.resize(1180, 820)
    window.show()
    # 直接进主窗口（HTTP 模式下「离线演示」不再适用：ScheduleTab 始终走远端）
    window.show_main()
    pump(app, 120)
    REPORT.check("教师端 offscreen 构建完整控件树（无异常）", True,
                 f"objectName={window.objectName()!r}；"
                 f"控件总数={len(window.findChildren(QtWidgets.QWidget))}")

    required = {
        "TeacherRootStack": QtWidgets.QStackedWidget,
        "TeacherLoginView": QtWidgets.QWidget,
        "TeacherIdInput": QtWidgets.QLineEdit,
        "TeacherPasswordInput": QtWidgets.QLineEdit,
        "TeacherMainTabs": QtWidgets.QTabWidget,
        "ScheduleTab": QtWidgets.QWidget,
        "TeacherScheduleBoard": QtWidgets.QWidget,
        "TeacherBlockToggle": QtWidgets.QPushButton,
        "TeacherRefreshButton": QtWidgets.QPushButton,
    }
    missing = [name for name, cls in required.items()
               if not isinstance(window.findChild(cls, name), cls)]
    REPORT.check("教师端关键控件（objectName）全部存在", not missing,
                 f"命中 {len(required) - len(missing)}/{len(required)}"
                 + (f"；缺失 {missing}" if missing else ""))

    # --- 学生端预约页（同一后端共享库，**也跑 HTTP**）--------------------------
    student_runner = TaskRunner(QThreadPool.globalInstance())
    student = AppointmentPage(
        profile_provider=lambda: {"id": "stu_2023001", "name": "林小满",
                                  "class_name": "高一(1)班"},
        standalone=True, client=student_client, runner=student_runner)

    def _on_student_confirmed(payload: dict) -> None:
        """学生端「确认预约」：真实 `POST /appointments`，成功后原地标「我的」。

        等价于学生主窗口 `_on_standalone_appointment_saved` 的落库 + 刷绿部分；
        网络调用放在自检装置里完成（UI 代码路径仍由主窗口在 worker 里投递）。
        """
        if not payload:
            return
        body = {
            "apt_id": appt_store.new_appointment_id(),
            "year": payload["year"], "month": payload["month"], "day": payload["day"],
            "time": payload["time"],
            "share_questionnaire": bool(payload.get("share_questionnaire")),
            "share_treehole": bool(payload.get("share_treehole")),
        }
        try:
            student_client.create_appointment(body)
        except Exception:                         # noqa: BLE001 - 自检里失败要显式
            REPORT.check("学生预约 POST /appointments 未抛异常", False,
                         traceback.format_exc())
            return
        slot = schedule_mod.slot_id(int(payload["year"]), int(payload["month"]),
                                    int(payload["day"]), int(payload["period"]))
        student.mark_mine(slot)
        student._refresh()

    student.confirmed.connect(_on_student_confirmed)
    student.resize(1080, 900)
    student.show()
    pump(app, 120)

    year, month, day = _future_day(5)
    column = schedule_mod.weekday_from_date(year, month, day) - 1
    period = 3

    teacher_tab = window.schedule_page
    teacher_tab.board.set_week(year, month, day)
    student.board.set_week(year, month, day)
    pump(app, 60)

    REPORT.check("双端网格结构一致（8 行 × 7 列 = 56 个方块）",
                 len(teacher_tab.board.grid.cells()) == 56
                 and len(student.board.grid.cells()) == 56
                 and all(isinstance(cell, SlotCell) for cell in
                         student.board.grid.cells()),
                 f"教师端 {len(teacher_tab.board.grid.cells())} 格 / "
                 f"学生端 {len(student.board.grid.cells())} 格")

    REPORT.check("双端同一周、同一列头（星期几按真实日历）",
                 teacher_tab.board.week() == student.board.week(),
                 f"周 = {student.board.week()}；"
                 f"列头 = {student.board.grid.column_head_text(column)}；"
                 f"行头 = {student.board.grid.period_head_text(period)}")

    free_before = student.board.grid.cell(period, column)
    REPORT.check("同一格在两端初始状态一致（free）",
                 free_before.state == teacher_tab.board.grid.cell(period, column).state
                 == "free",
                 f"学生端={free_before.state}；教师端="
                 f"{teacher_tab.board.grid.cell(period, column).state}")

    # ⚠️ 两端**先把同步跑起来**再改数据：轮询会取一次基线，基线之后的变化才算
    # 「同步」。先改再启动 = 永远测不到同步（StoreWatcher 时代踩过，HTTP 同样要守）。
    teacher_tab.start_sync()
    student.start_sync()
    teacher_tab._sync.set_interval(200)
    student._sync.set_interval(200)
    pump(app, 400)
    before = student.sync_count

    # --- 教师点格子 → 设为不可预约（HTTP：异步 `POST /appointments/blocks`）----
    teacher_tab._on_cell(period, column)
    teacher_tab._on_toggle()
    pump(app, 900)                     # 等 set_block 落库 + 教师端下一轮轮询刷到
    teacher_cell = teacher_tab.board.grid.cell(period, column)
    REPORT.check("教师设为不可预约：教师端该格变 blocked",
                 teacher_cell.state == "blocked"
                 and teacher_cell.property("slotState") == "blocked",
                 f"state={teacher_cell.state}；"
                 f"slotState={teacher_cell.property('slotState')}；"
                 f"按钮文案={teacher_tab.toggle_button.text()}")

    # --- **不手动刷新**，只让学生端轮询自己发现远端变了 -----------------------
    pump(app, 1500)

    student_cell = student.board.grid.cell(period, column)
    REPORT.check("**实时同步**：教师改完，学生端**自动**变成红框（未手动刷新）",
                 student_cell.state == "blocked"
                 and student_cell.property("slotState") == "blocked"
                 and student.sync_count > before,
                 f"学生端 state={student_cell.state}；"
                 f"slotState={student_cell.property('slotState')}；"
                 f"同步触发次数 {student.sync_count}（改前 {before}）")

    REPORT.check("学生端该格**不可点**（禁选，而不是点了才报错）",
                 not student_cell.isEnabled(),
                 f"isEnabled={student_cell.isEnabled()}")

    # --- 学生选了它 → 确认时按**当前**库状态拦下 ------------------------------
    student._on_cell(period, column)
    student._on_confirm()
    REPORT.check("学生点它确认 → 给出「老师设成不可预约」的文案",
                 student.error_label.text() == COPY["s.appointment.error.blocked"],
                 f"错误文案={student.error_label.text()!r}")

    # --- 教师恢复 → 学生端自动恢复可约 --------------------------------------
    teacher_tab._on_toggle()           # 该格现在 blocked，再 toggle = 取消
    pump(app, 1500)                    # 教师端刷到 free，学生端跟着刷到 free
    REPORT.check("教师恢复可预约 → 学生端**自动**恢复（同步是双向的）",
                 student.board.grid.cell(period, column).state == "free"
                 and student.board.grid.cell(period, column).isEnabled(),
                 f"学生端 state={student.board.grid.cell(period, column).state}；"
                 f"isEnabled={student.board.grid.cell(period, column).isEnabled()}")

    # --- 学生预约 → 教师端看到 -----------------------------------------------
    student.share_questionnaire.setChecked(True)
    student._on_confirm()              # 确认 → POST /appointments + 标「我的」
    pump(app, 1500)                    # 教师端轮询拉到这条新预约
    REPORT.check("学生确认预约 → 载荷含 year/month/day/period/weekday/起止钟点",
                 all(key in student.payload() for key in
                     ("year", "month", "day", "period", "weekday", "time",
                      "time_start", "time_end"))
                 and student.payload().get("share_questionnaire") is True,
                 f"payload = {student.payload()}")

    teacher_cell = teacher_tab.board.grid.cell(period, column)
    REPORT.check("教师端自动看到这条预约（格子变 taken + 显示人数）",
                 teacher_cell.state == "taken" and teacher_cell.text() == "1",
                 f"state={teacher_cell.state}；格子文字={teacher_cell.text()!r}")

    teacher_tab._on_cell(period, column)
    pump(app, 80)                     # 让 Qt 走完 layout 激活 + 新行的 show 事件
    detail_text = " | ".join(
        label.text() for label in teacher_tab.findChildren(QtWidgets.QLabel)
        if label.text() and label.isVisible())
    REPORT.check("教师端详情显示预约人（班级 / 学号）+ 是否愿意分享",
                 "林小满" in detail_text and "高一(1)班" in detail_text
                 and "stu_2023001" in detail_text
                 and COPY["t.schedule.detail.share.q.yes"] in detail_text
                 and COPY["t.schedule.detail.share.t.no"] in detail_text,
                 f"详情命中：姓名={'林小满' in detail_text} "
                 f"班级={'高一(1)班' in detail_text} "
                 f"学号={'stu_2023001' in detail_text} "
                 f"愿分享测评={COPY['t.schedule.detail.share.q.yes'] in detail_text} "
                 f"不愿分享树洞={COPY['t.schedule.detail.share.t.no'] in detail_text}")

    # --- 学生端看到自己的预约 -------------------------------------------------
    student._refresh()
    pump(app, 60)
    REPORT.check("学生端把已约的格子标成「我的」（可点、可改选）",
                 student.board.grid.cell(period, column).state == "mine"
                 and student.board.grid.cell(period, column).isEnabled(),
                 f"state={student.board.grid.cell(period, column).state}")

    return window, student


def check_states_exhaustive() -> None:
    section("⑤b 格子状态穷举")
    REPORT.check("五种状态全部登记且 `set_state` 只接受它们",
                 SLOT_STATES == ("free", "blocked", "taken", "mine", "past"),
                 f"SLOT_STATES = {SLOT_STATES}")
    unknown = SlotCell(1, 0)
    unknown.set_state("不存在的状态")
    REPORT.check("未知状态降级为 free（不崩、不静默显示怪值）",
                 unknown.state == "free", f"state={unknown.state}")


# --------------------------------------------------------------------------- ⑦ 对比度


def check_contrast() -> None:
    section("⑥ 新增格子配色的正文对比度（UI约定 §2 硬要求 1：≥ 4.5:1）")
    pairs = (
        ("不可预约（红框内的深色字）", theme.SLOT_BLOCKED_INK, theme.SLOT_BLOCKED_BG),
        ("已约（暖砂底）", theme.INK, theme.SLOT_TAKEN_BG),
        ("我的预约（嫩芽绿底）", theme.INK, theme.SLOT_MINE_BG),
        ("可预约（卡片底）", theme.INK, theme.CARD),
        ("选中（雾蓝底）", theme.PRIMARY_INK, theme.MIST),
    )
    rows = []
    worst = 99.0
    for name, fg, bg in pairs:
        ratio = theme.contrast_ratio(fg, bg)
        worst = min(worst, ratio)
        rows.append(f"{name}: {fg} on {bg} = {ratio}:1")
    REPORT.check("五种格子状态的正文对比度全部 ≥ 4.5:1", worst >= 4.5,
                 "\n".join(rows) + f"\n最低 {worst}:1")

    REPORT.check("红框本身足够醒目（框色 vs 卡片底 ≥ 3:1，图形对比度）",
                 theme.contrast_ratio(theme.SLOT_BLOCKED_LINE, theme.CARD) >= 3.0,
                 f"框 {theme.SLOT_BLOCKED_LINE} on 卡片 {theme.CARD} = "
                 f"{theme.contrast_ratio(theme.SLOT_BLOCKED_LINE, theme.CARD)}:1")


# --------------------------------------------------------------------------- ⑧ 纪律


def _hardcoded_chinese_scan() -> Tuple[bool, str]:
    """AST 扫描新写的界面模块：会进入界面的中文字面量必须来自文案表。"""
    files = [
        ROOT / "desktop_common" / "schedule_grid.py",
        ROOT / "desktop_common" / "schedule.py",
        ROOT / "desktop_common" / "schedule_store.py",
        ROOT / "desktop_common" / "sync.py",
        _APP_DIR.parent / "ui" / "schedule.py",
        _APP_DIR / "main.py",
        ROOT / "student-desktop" / "student_desktop" / "ui" / "pages.py",
    ]
    ui_entry_names = {
        "make_label", "make_title", "make_heading", "make_body", "make_hint",
        "make_error", "make_badge", "make_button", "make_primary_button",
        "make_ghost_button", "make_choice_button", "hotline_label", "Card",
        "QLabel", "QPushButton", "QLineEdit", "setText", "setPlaceholderText",
        "setWindowTitle", "setToolTip", "ResultPage", "TextArea", "ChoiceGroup",
    }
    allowed = ("Microsoft YaHei", "PingFang SC", "Segoe UI", "MindCare", "⟪缺文案")
    suspicious: List[str] = []
    total = 0
    for path in files:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in ui_entry_names:
                continue
            for arg in list(node.args)[:2]:
                if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                    continue
                value = arg.value
                if len(value) < 2 or not any("\u4e00" <= ch <= "\u9fff" for ch in value):
                    continue
                total += 1
                if any(token in value for token in allowed):
                    continue
                suspicious.append(f"{path.name}:{arg.lineno}: {value!r}")
    return (not suspicious), (
        f"AST 扫描 {len([p for p in files if p.exists()])} 个文件，"
        f"命中『会进入界面』的中文字面量 {total} 个 → 非文案来源的可疑项 "
        f"{len(suspicious)} 个" + ("；" + "；".join(suspicious[:8]) if suspicious else ""))


def check_discipline() -> None:
    section("⑦ 纪律：无硬编码中文 / 主线程未发请求 / 文案表无缺键")
    ok, evidence = _hardcoded_chinese_scan()
    REPORT.check("新写的界面模块无硬编码中文文案（一律来自 COPY）", ok, evidence)

    REPORT.check("文案表缺键为空（`COPY.missing_keys`）",
                 not COPY._missing, f"missing = {COPY._missing}")

    REPORT.check("预约 / 课表相关的文案键齐全",
                 all(key in COPY for key in
                     ("s.appointment.title", "s.appointment.profile.sid",
                      "s.appointment.error.blocked", "t.schedule.title",
                      "t.schedule.action.unblock", "c.schedule.period.8",
                      "c.schedule.weekday.7", "c.schedule.cell.blocked")),
                 "抽查 8 条键全部命中")


# --------------------------------------------------------------------------- 截图


def take_shots(app: QtWidgets.QApplication, window: Any, student: Any) -> List[Path]:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    shots: List[Path] = []

    def grab(widget: Any, name: str) -> None:
        widget.show()
        pump(app, 200)
        path = SHOT_DIR / name
        widget.grab().save(str(path))
        if path.exists() and path.stat().st_size > 0:
            shots.append(path)

    window.show_login()
    grab(window, "01_teacher_login.png")

    year, month, day = _future_day(5)
    column = schedule_mod.weekday_from_date(year, month, day) - 1
    window.show_main()
    window.schedule_page.board.set_week(year, month, day)
    window.schedule_page._on_cell(3, column)
    grab(window, "02_teacher_schedule.png")

    window.schedule_page._on_toggle()      # 设为不可预约 → 红框
    pump(app, 200)
    grab(window, "03_teacher_blocked.png")

    student.board.set_week(year, month, day)
    student.force_sync()
    grab(student, "04_student_appointment_grid.png")
    return shots


def write_evidence(files: List[Path]) -> None:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SHOT_DIR / "selfcheck_output.txt").write_text(
        REPORT.summary(), encoding="utf-8")
    lines = [f"{path.name}\t{path.stat().st_size} bytes" for path in files]
    (SHOT_DIR / "manifest.txt").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- main


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m teacher_desktop.app.selfcheck")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    args = parser.parse_args(argv)

    print("MindCare 教师端自检（offscreen，双端预约时间一致性）")
    print(f"  工程根   : {ROOT}")
    print(f"  截图目录 : {SHOT_DIR}")
    print(f"  临时数据 : {_TMP_ROOT}")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    theme.install_fonts(app)
    theme.apply_theme(app)
    STATS.reset()
    window = student = server = None

    try:
        server = _start_server()
        print(f"  共享后端 : {server._selfcheck_url}（in-process 临时库）")
        teacher_client = _login_client(server._selfcheck_url, "teacher")
        student_client = _login_client(server._selfcheck_url, "student")

        check_environment()
        check_schedule_facts()
        check_block_store()
        check_appointment_fields()
        check_states_exhaustive()
        window, student = check_ui_and_sync(app, teacher_client, student_client)
        check_contrast()
        check_discipline()
        shots = take_shots(app, window, student)
        REPORT.check("截图 ≥ 3 张（教师端登录 / 课表 / 红框 / 学生端网格）",
                     len(shots) >= 3,
                     "\n".join(f"{p.name} {p.stat().st_size} bytes" for p in shots))
        write_evidence(shots)
        REPORT.check("主线程从未调用传输层（UI约定 §3）",
                     STATS.transport_calls_main_thread == 0,
                     f"主线程 {STATS.transport_calls_main_thread} 次；"
                     f"worker 线程 {STATS.transport_calls_worker_thread} 次")
    except Exception:                                            # noqa: BLE001
        REPORT.check("自检过程中未抛出未捕获异常", False, traceback.format_exc())
    finally:
        if window is not None:
            window.shutdown(15000)
        if student is not None:
            student.stop_sync()
        if server is not None:
            _stop_server(server)
        section("自检结果")
        print(REPORT.summary())

    return 1 if REPORT.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
