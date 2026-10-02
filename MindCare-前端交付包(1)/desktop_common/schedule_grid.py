"""预约时间**课表网格控件**（学生端与教师端**共用同一份**）。

界面形态（需求原文）
--------------------
* 以**一年**为基本空间：月份 `1 ~ 12` 排成导航栏；
* 星期几为**横轴**（周一 ~ 周日，按 2026 年真实日历编排）；
* 第 1 ~ 第 8 节为**纵轴**（`08:00` 起、`17:00` 前结束）；
* 每一节课一个**小方块**，可点击。

双端共用 = 学生看到的表和老师看到的表必须是**同一张**（否则"学生选的时间同步到
教师端"没有意义）。因此本模块只做**渲染与交互**，格子状态由调用方（学生页 / 教师页）
按各自权限算好后喂进来 —— 判定逻辑留在各自端，渲染逻辑只有这一份。

样式纪律
--------
* 样式**只**来自 `theme.build_qss()` 里 `#SlotCell[slotState="…"]` 那几条规则，
  本模块只 `setObjectName` + `setProperty`（动态属性），**不写内联样式表**；
* 可点控件一律 `Qt.StrongFocus`（`enforce_focus_policy()` 会兜底）；
* 无动画（UI约定 §2 硬要求 3）。

文案纪律
--------
本模块不产生中文：星期名 / 节次名 / 状态说明一律 `COPY[键]`（键来自 `schedule.py`
的 `WEEKDAY_KEYS` / `PERIOD_LABEL_KEYS`）。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import schedule as schedule_mod
from . import theme
from .copy import COPY

__all__ = [
    "SLOT_STATES", "SlotCell", "ScheduleGrid", "MonthBar", "WeekBar",
    "LegendBar", "ScheduleBoard",
]

#: 格子的五种状态（**穷举**：`SlotCell.set_state()` 只接受这五个值）
SLOT_STATES: Tuple[str, ...] = ("free", "blocked", "taken", "mine", "past")

#: 可选年份范围（相对基准年：`CALENDAR_ANCHOR_YEAR-1` ~ `+2`）
YEAR_BACK = 1
YEAR_FORWARD = 2


class SlotCell(QPushButton):
    """课表里的**一个小方块**（一节课）。

    状态只通过 `set_state()` 改：它同时设动态属性 `slotState`（QSS 靠它命中样式）
    并重画样式（`unpolish/polish` —— Qt 不会自动感知动态属性变化）。
    """

    SLOT_OBJECT = "SlotCell"

    def __init__(self, period: int, column: int,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(self.SLOT_OBJECT)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(theme.MIN_TAP)
        #: 第几节（1~8，纵轴）
        self.period = int(period)
        #: 第几列（0~6，对应周一~周日，横轴）
        self.column = int(column)
        self._state = "free"
        self.setProperty("slotState", "free")

    # -- 状态 ---------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str, text: Optional[str] = None, *,
                  clickable: Optional[bool] = None) -> None:
        """设置格子状态。

        :param state: `SLOT_STATES` 之一；不在其中时按 `free` 处理（不抛异常）
        :param text: 格子里显示的短文字（**由调用方从文案表取**）；`None` 时按状态给默认
        :param clickable: 是否可点；`None` 时按状态推导
                          （`free` / `mine` 可点，`blocked` / `taken` / `past` 不可点）
        """
        value = state if state in SLOT_STATES else "free"
        self._state = value
        self.setProperty("slotState", value)
        if text is None:
            text = {
                "free": COPY["c.schedule.cell.free"],
                "blocked": COPY["c.schedule.cell.blocked"],
                "taken": COPY["c.schedule.cell.taken"],
                "mine": COPY["c.schedule.cell.mine"],
                "past": "",
            }.get(value, "")
        self.setText(text)
        if clickable is None:
            clickable = value in ("free", "mine")
        self.setEnabled(bool(clickable))
        # 动态属性变了必须手动重画样式，否则红框不会出现
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class ScheduleGrid(QWidget):
    """8 行（节次）× 7 列（星期）的课表网格。

    列头 = 星期名 + 日期（`周一 10/05`），行头 = 节次名 + 时间段（`第1节 08:00-08:45`），
    其余 56 个位置是 `SlotCell`。
    """

    #: 某个格子被点击：`(第几节, 第几列)`。列 → 具体日期由 `date_at()` 换算。
    cell_activated = Signal(int, int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ScheduleGrid")
        self._dates: List[Tuple[int, int, int]] = []
        self._cells: Dict[Tuple[int, int], SlotCell] = {}
        self._selected: Optional[Tuple[int, int]] = None

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self._build()

    # -- 构建 ---------------------------------------------------------------

    def _build(self) -> None:
        corner = QLabel(COPY["c.schedule.col.period"], self)
        corner.setObjectName("SlotHead")
        corner.setAlignment(Qt.AlignCenter)
        self.grid.addWidget(corner, 0, 0)

        for column in range(schedule_mod.WEEKDAY_COUNT):
            head = QLabel("", self)
            head.setObjectName("SlotHead")
            head.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(head, 0, column + 1)
            self.grid.setColumnStretch(column + 1, 1)

        for period in range(schedule_mod.PERIOD_INDEX_MIN,
                            schedule_mod.PERIOD_INDEX_MAX + 1):
            row_head = QLabel("", self)
            row_head.setObjectName("SlotPeriod")
            row_head.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            row_head.setWordWrap(False)
            self.grid.addWidget(row_head, period, 0)
            for column in range(schedule_mod.WEEKDAY_COUNT):
                cell = SlotCell(period, column, self)
                cell.clicked.connect(
                    lambda _checked=False, p=period, c=column: self._on_click(p, c))
                self.grid.addWidget(cell, period, column + 1)
                self._cells[(period, column)] = cell
        self.set_week(schedule_mod.week_dates(
            schedule_mod.CALENDAR_ANCHOR_YEAR, 1, 1))

    def _on_click(self, period: int, column: int) -> None:
        self.set_selected(period, column)
        self.cell_activated.emit(period, column)

    # -- 数据 ---------------------------------------------------------------

    def set_week(self, dates: Sequence[Tuple[int, int, int]]) -> None:
        """设置横轴的 7 天（`[(y, m, d), ...]`，必须是 7 项、按周一起）。"""
        if len(dates) != schedule_mod.WEEKDAY_COUNT:
            return
        self._dates = [(int(y), int(m), int(d)) for y, m, d in dates]
        for column, (year, month, day) in enumerate(self._dates):
            head = self.grid.itemAtPosition(0, column + 1)
            if head is None:
                continue
            label = head.widget()
            if isinstance(label, QLabel):
                weekday = schedule_mod.weekday_from_date(year, month, day)
                week_key = schedule_mod.WEEKDAY_KEYS[weekday - 1] if 1 <= weekday <= 7 else ""
                name = COPY[week_key] if week_key else ""
                label.setText(f"{name} {schedule_mod.date_text(year, month, day)}")
        for period in range(schedule_mod.PERIOD_INDEX_MIN,
                            schedule_mod.PERIOD_INDEX_MAX + 1):
            head = self.grid.itemAtPosition(period, 0)
            if head is None:
                continue
            label = head.widget()
            if isinstance(label, QLabel):
                key = schedule_mod.period_label_key(period)
                name = COPY[key] if key else ""
                label.setText(f"{name}  {schedule_mod.period_time_text(period)}")

    def dates(self) -> List[Tuple[int, int, int]]:
        return list(self._dates)

    def date_at(self, column: int) -> Optional[Tuple[int, int, int]]:
        """第几列 → 具体日期 `(y, m, d)`（越界返回 `None`）。"""
        if 0 <= column < len(self._dates):
            return self._dates[column]
        return None

    def column_head_text(self, column: int) -> str:
        """第几列的列头文字（星期名 + 日期；自检与排障用）。"""
        item = self.grid.itemAtPosition(0, column + 1)
        widget = item.widget() if item is not None else None
        return widget.text() if isinstance(widget, QLabel) else ""

    def period_head_text(self, period: int) -> str:
        """第几节的行头文字（节次名 + 时间段；自检与排障用）。"""
        item = self.grid.itemAtPosition(period, 0)
        widget = item.widget() if item is not None else None
        return widget.text() if isinstance(widget, QLabel) else ""

    def cell(self, period: int, column: int) -> Optional[SlotCell]:
        return self._cells.get((int(period), int(column)))

    def cells(self) -> List[SlotCell]:
        return [self._cells[(p, c)]
                for p in range(schedule_mod.PERIOD_INDEX_MIN,
                               schedule_mod.PERIOD_INDEX_MAX + 1)
                for c in range(schedule_mod.WEEKDAY_COUNT)
                if (p, c) in self._cells]

    def set_cell(self, period: int, column: int, state: str,
                 text: Optional[str] = None, *,
                 clickable: Optional[bool] = None) -> None:
        cell = self.cell(period, column)
        if cell is not None:
            cell.set_state(state, text, clickable=clickable)

    def apply_states(self, mapper: Callable[[int, int, Tuple[int, int, int]],
                                            Tuple[str, Optional[str], Optional[bool]]]) -> None:
        """批量刷状态：`mapper(period, column, date) -> (state, text, clickable)`。

        ⚠️ 只调一次遍历完成全部格子 —— 56 个格子逐个 `set_state` 会触发 56 次样式重画，
        在轮询同步（1.5s 一次）下能感觉到卡顿。
        """
        for period in range(schedule_mod.PERIOD_INDEX_MIN,
                            schedule_mod.PERIOD_INDEX_MAX + 1):
            for column, date in enumerate(self._dates):
                cell = self._cells.get((period, column))
                if cell is None:
                    continue
                try:
                    state, text, clickable = mapper(period, column, date)
                except TypeError:                       # pragma: no cover - 防御
                    state, text, clickable = "free", None, None
                cell.set_state(state, text, clickable=clickable)
        self._repaint_selection()

    # -- 选中 ---------------------------------------------------------------

    def set_selected(self, period: int, column: int) -> None:
        """把某格标成"当前选中"（**原选中格恢复成它自己的状态**由 `apply_states` 负责）。"""
        self._selected = (int(period), int(column))
        self._repaint_selection()

    def clear_selection(self) -> None:
        self._selected = None
        self._repaint_selection()

    @property
    def selected(self) -> Optional[Tuple[int, int]]:
        return self._selected

    def _repaint_selection(self) -> None:
        for (period, column), cell in self._cells.items():
            is_selected = self._selected == (period, column)
            cell.setProperty("slotSelected", "yes" if is_selected else "no")
            cell.style().unpolish(cell)
            cell.style().polish(cell)


class MonthBar(QWidget):
    """`1 ~ 12` 月导航栏（**一年为基本空间**；当前月高亮）。"""

    month_changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MonthBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: List[QPushButton] = []
        for month in range(1, 13):
            button = QPushButton(str(month), self)
            button.setObjectName("MonthButton")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(theme.MIN_TAP)
            self._group.addButton(button, month)
            button.clicked.connect(
                lambda _checked=False, m=month: self.month_changed.emit(m))
            layout.addWidget(button)
            self._buttons.append(button)

    def set_month(self, month: int) -> None:
        try:
            value = int(month)
        except (TypeError, ValueError):
            return
        if 1 <= value <= 12:
            self._buttons[value - 1].setChecked(True)

    def buttons(self) -> List[QPushButton]:
        return list(self._buttons)


class WeekBar(QWidget):
    """上一周 / 本周区间 / 下一周 / 回到本周。"""

    #: `-1` = 上一周，`+1` = 下一周
    week_shifted = Signal(int)
    #: 回到**今天**所在周
    current_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("WeekBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.prev_button = QPushButton(COPY["c.schedule.week.prev"], self)
        self.prev_button.setObjectName("GhostButton")
        self.prev_button.setFocusPolicy(Qt.StrongFocus)
        self.prev_button.clicked.connect(lambda: self.week_shifted.emit(-1))
        self.range_label = QLabel("", self)
        self.range_label.setObjectName("SlotHead")
        self.range_label.setAlignment(Qt.AlignCenter)
        self.next_button = QPushButton(COPY["c.schedule.week.next"], self)
        self.next_button.setObjectName("GhostButton")
        self.next_button.setFocusPolicy(Qt.StrongFocus)
        self.next_button.clicked.connect(lambda: self.week_shifted.emit(1))
        self.current_button = QPushButton(COPY["c.schedule.week.current"], self)
        self.current_button.setObjectName("GhostButton")
        self.current_button.setFocusPolicy(Qt.StrongFocus)
        self.current_button.clicked.connect(self.current_requested.emit)
        layout.addWidget(self.prev_button)
        layout.addWidget(self.range_label, 1)
        layout.addWidget(self.next_button)
        layout.addWidget(self.current_button)

    def set_range(self, dates: Sequence[Tuple[int, int, int]]) -> None:
        if len(dates) != schedule_mod.WEEKDAY_COUNT:
            return
        start = schedule_mod.date_text(*dates[0])
        end = schedule_mod.date_text(*dates[-1])
        self.range_label.setText(
            COPY["c.schedule.week.range"].replace("{start}", start)
                                         .replace("{end}", end))


class LegendBar(QWidget):
    """方块状态说明（学生端与教师端显示同一套口径）。"""

    #: 状态 → (文案键, QSS 里的 swatch objectName)
    ITEMS: Tuple[Tuple[str, str, str], ...] = (
        ("free", "c.schedule.legend.free", "SwatchFree"),
        ("blocked", "c.schedule.legend.blocked", "SwatchBlocked"),
        ("taken", "c.schedule.legend.taken", "SwatchTaken"),
        ("mine", "c.schedule.legend.mine", "SwatchMine"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LegendBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        title = QLabel(COPY["c.schedule.legend.title"], self)
        title.setObjectName("Hint")
        layout.addWidget(title)
        for _state, key, object_name in self.ITEMS:
            swatch = QFrame(self)
            swatch.setObjectName(object_name)
            swatch.setFixedSize(16, 16)
            layout.addWidget(swatch)
            label = QLabel(COPY[key], self)
            label.setObjectName("Hint")
            layout.addWidget(label)
        layout.addStretch(1)


class ScheduleBoard(QWidget):
    """完整课表面板：**年份 + 1~12 月导航栏 + 周导航 + 8×7 网格 + 图例**。

    学生端与教师端都用它 —— 这就是"映射界面同学生界面"的落点。

    用法::

        board = ScheduleBoard()
        board.view_changed.connect(self._refresh)          # 年/月/周变了
        board.cell_activated.connect(self._on_cell)        # 点了某个方块
        board.set_week(2026, 10, 5)
        board.apply_states(self._state_of)                 # 按权限算每格状态
    """

    #: 点了某个方块：`(第几节, 第几列)`
    cell_activated = Signal(int, int)
    #: 年 / 月 / 周发生变化（调用方据此重新算状态）
    view_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, *,
                 show_legend: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("ScheduleBoard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(10)
        year_label = QLabel(COPY["c.schedule.year"], self)
        year_label.setObjectName("Hint")
        self.year_box = QComboBox(self)
        self.year_box.setObjectName("AppointmentCombo")
        self.year_box.setFocusPolicy(Qt.StrongFocus)
        anchor = schedule_mod.CALENDAR_ANCHOR_YEAR
        for year in range(anchor - YEAR_BACK, anchor + YEAR_FORWARD + 1):
            self.year_box.addItem(str(year), int(year))
        month_label = QLabel(COPY["c.schedule.monthNav"], self)
        month_label.setObjectName("Hint")
        top.addWidget(year_label)
        top.addWidget(self.year_box)
        top.addWidget(month_label)
        outer.addLayout(top)

        self.month_bar = MonthBar(self)
        outer.addWidget(self.month_bar)
        self.month_bar.month_changed.connect(self._on_month)

        self.week_bar = WeekBar(self)
        outer.addWidget(self.week_bar)
        self.week_bar.week_shifted.connect(self._on_shift)
        self.week_bar.current_requested.connect(self.goto_today)

        self.grid = ScheduleGrid(self)
        outer.addWidget(self.grid, 1)
        self.grid.cell_activated.connect(self.cell_activated.emit)

        if show_legend:
            self.legend = LegendBar(self)
            outer.addWidget(self.legend)

        self.year_box.currentTextChanged.connect(self._on_year)
        #: 当前视图锚点 `(y, m, d)`（决定显示哪一周）
        self._anchor: Tuple[int, int, int] = (anchor, 1, 1)
        self.set_week(anchor, 1, 1)

    # -- 视图 ---------------------------------------------------------------

    def anchor(self) -> Tuple[int, int, int]:
        return self._anchor

    def set_week(self, year: int, month: int, day: int) -> None:
        """把视图切到「某一天所在周」，并同步年下拉与月份导航栏。"""
        try:
            y, m = int(year), int(month)
        except (TypeError, ValueError):
            return
        d = schedule_mod.clamp_day(y, m, day)
        self._anchor = (y, m, d)
        week = schedule_mod.week_dates(y, m, d)
        self.grid.set_week(week)
        self.week_bar.set_range(week)
        # 月份导航栏按**锚点日期所在月**高亮（跨周边界时更贴近直觉）
        self.month_bar.set_month(m)
        box_year = str(y)
        if self.year_box.findText(box_year) >= 0:
            self.year_box.setCurrentText(box_year)
        self.grid.clear_selection()
        self.view_changed.emit()

    def goto_today(self) -> None:
        from datetime import date

        today = date.today()
        self.set_week(today.year, today.month, today.day)

    def week(self) -> List[Tuple[int, int, int]]:
        return self.grid.dates()

    def date_at(self, column: int) -> Optional[Tuple[int, int, int]]:
        return self.grid.date_at(column)

    def _on_month(self, month: int) -> None:
        year = int(self.year_box.currentText() or schedule_mod.CALENDAR_ANCHOR_YEAR)
        self.set_week(year, month, 1)

    def _on_year(self, _text: str) -> None:
        year = int(self.year_box.currentText() or schedule_mod.CALENDAR_ANCHOR_YEAR)
        self.set_week(year, self._anchor[1], self._anchor[2])

    def _on_shift(self, delta: int) -> None:
        from datetime import date, timedelta

        y, m, d = self._anchor
        try:
            current = date(y, m, d)
        except ValueError:                                # pragma: no cover - 防御
            return
        moved = current + timedelta(days=7 * int(delta))
        self.set_week(moved.year, moved.month, moved.day)

    # -- 格子 ---------------------------------------------------------------

    def set_cell(self, period: int, column: int, state: str,
                 text: Optional[str] = None, *,
                 clickable: Optional[bool] = None) -> None:
        self.grid.set_cell(period, column, state, text, clickable=clickable)

    def apply_states(self, mapper) -> None:
        self.grid.apply_states(mapper)

    def set_selected(self, period: int, column: int) -> None:
        self.grid.set_selected(period, column)

    def clear_selection(self) -> None:
        self.grid.clear_selection()
