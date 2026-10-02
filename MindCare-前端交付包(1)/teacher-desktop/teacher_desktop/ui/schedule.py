"""教师端「预约时间表」（与学生端**同一张课表**）。

需求要点
--------
* 教师端提取**预约时间数据库**，界面映射同学生界面 —— 因此本页直接复用
  `desktop_common.schedule_grid.ScheduleBoard`，不另画一张表；
* 学生选的预约时间**同步**到这里；
* 教师可以修改数据库、设定**不可预约时间**，并**实时同步到学生界面**上
  （学生端看到红框，见 `student_desktop/ui/pages.py` 的 `AppointmentPage`）。

教师端与学生端的差别只有两点
----------------------------
1. **格子都可点**（`past` 除外）：教师要点它看"谁约了"、也要点它切换不可预约；
2. 右侧多一块**详情**：该时段的预约人（姓名 / 班级 / 学号）+ 是否愿意分享。

⚠️ **分享纪律**：本地库只存"愿不愿意"的布尔标记，**不落正文**。
未勾选分享的同学，教师端只显示班级 / 学号 / 时间，正文一律读不到
（与契约 §2「选择性发送语义」同一口径）。

文案纪律：本模块不出现中文界面文案字面量，一律 `COPY["<ID>"]`。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_common import appointments as appt_store
from desktop_common import schedule as schedule_mod
from desktop_common import schedule_store
from desktop_common import sync as sync_mod
from desktop_common.copy import COPY
from desktop_common.remote_sync import RemoteSchedule
from desktop_common.schedule_grid import ScheduleBoard
from desktop_common.widgets import (
    Card,
    divider,
    make_body,
    make_error,
    make_ghost_button,
    make_hint,
    make_primary_button,
    make_title,
)

__all__ = ["ScheduleTab"]


class ScheduleTab(QWidget):
    """预约时间表：课表 + 该时段预约详情 + 不可预约开关。"""

    #: 教师改了不可预约设定（供主窗口提示 / 自检断言）
    block_changed = Signal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None, *,
                 client: Any = None, runner: Any = None) -> None:
        super().__init__(parent)
        self.setObjectName("ScheduleTab")
        self._selected: Optional[Tuple[int, int]] = None
        #: HTTP 轮询同步器（`client`+`runner` 都给时启用；否则回退本地文件 StoreWatcher，
        #: 供「离线演示」这条不连服务端的路径使用）。
        self._remote: Optional[RemoteSchedule] = None
        self._client = client
        self._runner = runner

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        header = Card()
        header.add(make_title(COPY["t.schedule.title"]))
        header.add(make_hint(COPY["t.schedule.subtitle"]))
        outer.addWidget(header)

        self.board = ScheduleBoard()
        self.board.setObjectName("TeacherScheduleBoard")
        outer.addWidget(self.board, 1)
        self.board.cell_activated.connect(self._on_cell)
        self.board.view_changed.connect(self._refresh)

        self.hint_label = make_hint(COPY["t.schedule.hint.toggle"])
        outer.addWidget(self.hint_label)

        # --- 详情 + 操作 -----------------------------------------------------
        self.detail = Card()
        self.detail_title = make_title(COPY["t.schedule.detail.title"])
        self.detail.add(self.detail_title)
        self.detail_body = make_body(COPY["t.schedule.selected.none"])
        self.detail_body.setObjectName("TeacherScheduleDetail")
        self.detail.add(self.detail_body)
        self.detail_rows = QWidget()
        self.detail_rows_layout = QVBoxLayout(self.detail_rows)
        self.detail_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_rows_layout.setSpacing(6)
        self.detail.add(self.detail_rows)
        outer.addWidget(self.detail)

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)
        self.toggle_button = make_primary_button(COPY["t.schedule.action.block"])
        self.toggle_button.setObjectName("TeacherBlockToggle")
        self.toggle_button.setEnabled(False)
        self.toggle_button.clicked.connect(self._on_toggle)
        self.toggle_error = make_error("")
        actions_layout.addWidget(self.toggle_button)
        actions_layout.addWidget(self.toggle_error, 1)
        self.refresh_button = make_ghost_button(COPY["t.schedule.action.refresh"])
        self.refresh_button.setObjectName("TeacherRefreshButton")
        self.refresh_button.clicked.connect(self.force_refresh)
        actions_layout.addWidget(self.refresh_button)
        outer.addWidget(actions)

        # --- 实时同步（学生端改预约 → 这里也立刻更新）-------------------------
        # HTTP 模式（联调后端共享库）：由 `RemoteSchedule` 轮询 blocks + 全部预约；
        # 本地模式（离线演示）：沿用文件签名 `StoreWatcher`。
        if client is not None and runner is not None:
            self._remote = RemoteSchedule(client, runner, fetch_appointments=True)
            self._sync = self._remote
        else:
            self._sync = sync_mod.StoreWatcher(
                [appt_store.appointment_file(), schedule_store.block_file()])
        self._sync.changed.connect(self._refresh)

        today = date.today()
        self.board.set_week(today.year, today.month, today.day)
        self._refresh()

    # -- 同步 ---------------------------------------------------------------

    def start_sync(self) -> None:
        self._sync.start()

    def stop_sync(self) -> None:
        self._sync.stop()

    @property
    def sync_count(self) -> int:
        return self._sync.change_count

    def force_refresh(self) -> None:
        """手工刷新（按钮 / 自检都走这里）。"""
        self._sync.force_refresh()

    # -- 渲染 ---------------------------------------------------------------

    def _refresh(self) -> None:
        """重读事实源并重刷格子 + 详情（**唯一的刷新入口**）。"""
        blocked = self._blocked_slots()
        today = date.today()

        def state_of(period: int, _column: int,
                     day: Tuple[int, int, int]) -> Tuple[str, Optional[str], Optional[bool]]:
            year, month, day_no = day
            slot = schedule_mod.slot_id(year, month, day_no, period)
            if schedule_mod.is_past_slot(year, month, day_no, period, now=today):
                return "past", "", False
            if slot in blocked:
                return "blocked", None, True
            records = self._records_at(year, month, day_no, period)
            if records:
                # 教师端要能看到"几个人约了"：格子里直接显示人数
                return "taken", str(len(records)), True
            return "free", None, True

        self.board.apply_states(state_of)
        self._render_detail()

    # -- 数据源（HTTP / 本地二选一）-----------------------------------------

    def _blocked_slots(self) -> set:
        if self._remote is not None:
            return self._remote.blocked_slots()
        return schedule_store.blocked_slots()

    def _records_at(self, year, month, day, period) -> List[dict]:
        if self._remote is not None:
            return self._remote.appointments_at(year, month, day, period)
        return appt_store.appointments_at(year, month, day, period)

    def _slot_blocked(self, year, month, day, period) -> bool:
        slot = schedule_mod.slot_id(year, month, day, period)
        if self._remote is not None:
            return slot in self._remote.blocked_slots()
        return schedule_store.is_blocked(year, month, day, period)

    # -- 选中 ---------------------------------------------------------------

    def _on_cell(self, period: int, column: int) -> None:
        self._selected = (int(period), int(column))
        self.toggle_error.setText("")
        self.toggle_error.setVisible(False)
        self.board.set_selected(period, column)
        self._render_detail()

    def selected_slot(self) -> Optional[Tuple[int, int, int, int]]:
        """当前选中的 `(year, month, day, period)`；没选返回 `None`。"""
        if self._selected is None:
            return None
        period, column = self._selected
        day = self.board.date_at(column)
        if day is None:
            return None
        return day[0], day[1], day[2], period

    def _render_detail(self) -> None:
        slot = self.selected_slot()
        if slot is None:
            self.detail_body.setText(COPY["t.schedule.selected.none"])
            self.detail_body.setVisible(True)
            self._clear_rows()
            self.toggle_button.setEnabled(False)
            self.toggle_button.setText(COPY["t.schedule.action.block"])
            return

        year, month, day, period = slot
        weekday = schedule_mod.weekday_from_date(year, month, day)
        week_key = schedule_mod.WEEKDAY_KEYS[weekday - 1] if 1 <= weekday <= 7 else ""
        head = (f"{schedule_mod.date_text(year, month, day)} "
                f"{COPY[week_key] if week_key else ''} "
                f"{schedule_mod.period_start(period)}-{schedule_mod.period_end(period)}")
        self.detail_body.setText(head)
        self.detail_body.setVisible(True)

        records = self._records_at(year, month, day, period)
        self._clear_rows()
        if not records:
            self._add_row(COPY["t.schedule.detail.empty"])
        else:
            count_text = COPY["t.schedule.detail.count"].replace(
                "{count}", str(len(records)))
            self._add_row(count_text)
            for record in records:
                self._render_record(record)

        # 开关按钮：按**当前**是否被设为不可预约显示两种文案
        blocked = self._slot_blocked(year, month, day, period)
        self.toggle_button.setText(COPY["t.schedule.action.unblock"] if blocked
                                   else COPY["t.schedule.action.block"])
        # 过去的时间不改了（改了也没有意义，学生本来就约不到）
        self.toggle_button.setEnabled(
            not schedule_mod.is_past_slot(year, month, day, period))

    def _render_record(self, record: dict) -> None:
        """一位预约人：基本信息 + **是否愿意分享**（正文不在这里）。"""
        name = str(record.get("name") or "")
        class_name = str(record.get("class_name") or "")
        student_id = str(record.get("student_id") or "")
        parts = [f"{COPY['t.schedule.detail.student']}：{name}"]
        if class_name:
            parts.append(f"{COPY['t.schedule.detail.class']}：{class_name}")
        if student_id:
            parts.append(f"{COPY['t.schedule.detail.sid']}：{student_id}")
        self._add_row("　".join(parts))
        share_q = bool(record.get("share_questionnaire"))
        share_t = bool(record.get("share_treehole"))
        self._add_row(COPY["t.schedule.detail.share.q.yes" if share_q
                           else "t.schedule.detail.share.q.no"])
        self._add_row(COPY["t.schedule.detail.share.t.yes" if share_t
                           else "t.schedule.detail.share.t.no"])
        if not share_q and not share_t:
            self._add_row(COPY["t.schedule.detail.noShare"])

    def _add_row(self, text: str) -> None:
        label = make_body("· " + text)
        self.detail_rows_layout.addWidget(label)

    def _clear_rows(self) -> None:
        """清空详情行。

        ⚠️ `takeAt()` 只把条目从**布局**里摘下来，控件本身仍是
        `detail_rows` 的子控件、**仍然可见**（实测：旧行残留、越积越多）。
        必须 `setParent(None)` 先摘出控件树，再 `deleteLater()` 回收。
        """
        while self.detail_rows_layout.count():
            item = self.detail_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # -- 设为不可预约 --------------------------------------------------------

    def _on_toggle(self) -> None:
        """切换当前格子的不可预约状态。

        HTTP 模式：`POST /appointments/blocks`（异步，成功后再刷新 + 回执）；
        本地模式：`schedule_store.toggle_block`（只追加一条记录，不改写历史行）。
        """
        slot = self.selected_slot()
        if slot is None:
            return
        year, month, day, period = slot
        slot_id = schedule_mod.slot_id(year, month, day, period)
        if self._remote is not None:
            active = not self._slot_blocked(year, month, day, period)
            self.toggle_error.setText("")
            self.toggle_error.setVisible(False)
            worker = self._runner.submit(
                self._client.set_block, year, month, day, period, active, None,
                done=lambda _data: self._after_block_set(slot_id, active),
                failed=self._on_block_failed)
            return
        after = schedule_store.toggle_block(year, month, day, period,
                                            operator="teacher")
        if after is None:
            self.toggle_error.setText(COPY["t.schedule.action.failed"])
            self.toggle_error.setVisible(True)
            return
        self.block_changed.emit(slot_id, bool(after))
        self._refresh()

    def _after_block_set(self, slot: str, active: bool) -> None:
        self.block_changed.emit(slot, bool(active))
        self._refresh()

    def _on_block_failed(self, error: Any) -> None:
        self.toggle_error.setText(COPY["t.schedule.action.failed"])
        self.toggle_error.setVisible(True)

    # -- 生命周期 -----------------------------------------------------------

    def shutdown(self) -> None:
        self.stop_sync()
