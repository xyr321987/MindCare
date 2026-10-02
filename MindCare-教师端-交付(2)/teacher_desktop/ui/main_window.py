# -*- coding: utf-8 -*-
"""主窗：左侧导航壳 + 右侧页面栈（五个功能页）。

导航顺序（与新增需求一一对应）：
1. 分诊台     —— 迁移 教师端3.html（保留 P1/P2/P3 优先级与轮询）
2. 今日预约   —— 待预约求助 + 当日单线时间轴
3. 预警记录   —— 连续低落不求助预警（独立页，不动分诊台既有优先级）
4. 回复库     —— 老师自定义回复条目 CRUD
5. 数据导出   —— 跨班汇总（零正文）导出 Excel
"""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from desktop_common.widgets import make_button, make_label

from .appointments.appointments_page import AppointmentsPage
from .common.async_mixin import PageContext
from .export.export_page import ExportPage
from .replies.replies_page import RepliesPage
from .students.students_page import StudentsPage
from .triage.triage_page import TriagePage
from .warnings.warnings_page import WarningsPage

#: (导航 key, 文案) —— 新增页面只改这里
NAV_ITEMS = [
    ("triage", "分诊台"),
    ("appointments", "今日预约"),
    ("warnings", "预警记录"),
    ("replies", "回复库"),
    ("export", "数据导出"),
    ("students", "学生管理"),
]


class MainWindow(QWidget):
    """登录成功后的主工作台（作为页面栈的一个嵌片，不用 QMainWindow 以便整体切换）。
    退出登录发 logout_requested。"""

    logout_requested = Signal()

    def __init__(self, ctx: PageContext, profile: dict, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_sidebar(profile))
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        # ---- 五个页面（顺序与 NAV_ITEMS 对齐）
        self.pages: Dict[str, QWidget] = {
            "triage": TriagePage(ctx),
            "appointments": AppointmentsPage(ctx),
            "warnings": WarningsPage(ctx),
            "replies": RepliesPage(ctx),
            "export": ExportPage(ctx),
            "students": StudentsPage(ctx),
        }
        for key, _ in NAV_ITEMS:
            self.stack.addWidget(self.pages[key])

        self._select("triage")

    # ------------------------------------------------------------------ 侧边栏
    def _build_sidebar(self, profile: dict) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(200)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(16, 20, 16, 18)
        layout.setSpacing(8)

        name = make_label("MindCare", "AppName")
        layout.addWidget(name)
        layout.addWidget(make_label("教师关怀工作台", "AppSub"))
        layout.addSpacing(14)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (key, text) in enumerate(NAV_ITEMS):
            btn = QPushButton(text)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            self.nav_group.addButton(btn, index)
            layout.addWidget(btn)

        layout.addStretch(1)

        # 底部：数据源标记 / 教师姓名 / 退出
        server = getattr(self.ctx.settings, "server", "")
        layout.addWidget(make_label(f"数据源：{server}", "ModeTag"))
        layout.addWidget(make_label(f"当前老师：{profile.get('name', '老师')}", "Hint"))
        logout = make_button("退出登录", "ghost")
        logout.clicked.connect(self.logout_requested.emit)
        layout.addWidget(logout)
        return bar

    # ------------------------------------------------------------------ 切换
    def _select(self, key: str) -> None:
        index = next(i for i, (k, _) in enumerate(NAV_ITEMS) if k == key)
        self.stack.setCurrentIndex(index)
        btn = self.nav_group.button(index)
        if btn is not None:
            btn.setChecked(True)
        page = self.pages[key]
        if hasattr(page, "on_show"):
            page.on_show()
