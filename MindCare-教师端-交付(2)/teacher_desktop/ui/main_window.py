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

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from desktop_common.widgets import make_button, make_label

from .appointments.appointments_page import AppointmentsPage
from .common.async_mixin import PageContext
from .common.svg import svg_pixmap
from .export.export_page import ExportPage
from .overview.overview_page import OverviewPage
from .replies.replies_page import RepliesPage
from .stats.stats_page import StatsPage
from .students.students_page import StudentsPage
from .triage.triage_page import TriagePage
from .warnings.warnings_page import WarningsPage

#: (导航 key, 文案) —— 新增页面只改这里；「工作预览」为默认首页
NAV_ITEMS = [
    ("overview", "工作预览"),
    ("triage", "分诊台"),
    ("appointments", "今日预约"),
    ("stats", "排班统计"),
    ("warnings", "预警记录"),
    ("replies", "回复库"),
    ("export", "数据导出"),
    ("students", "学生管理"),
]

#: 导航图标（key -> SVG 文件名）
NAV_ICONS = {
    "overview": "icon_overview.svg",
    "triage": "icon_triage.svg",
    "appointments": "icon_appointment.svg",
    "stats": "icon_stats.svg",
    "warnings": "icon_warning.svg",
    "replies": "icon_replies.svg",
    "export": "icon_export.svg",
    "students": "icon_students.svg",
}


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

        # ---- 页面（顺序与 NAV_ITEMS 对齐；overview 为默认首页）
        self.pages: Dict[str, QWidget] = {
            "overview": OverviewPage(ctx),
            "triage": TriagePage(ctx),
            "appointments": AppointmentsPage(ctx),
            "stats": StatsPage(ctx),
            "warnings": WarningsPage(ctx),
            "replies": RepliesPage(ctx),
            "export": ExportPage(ctx),
            "students": StudentsPage(ctx),
        }
        for key, _ in NAV_ITEMS:
            self.stack.addWidget(self.pages[key])

        self._select("overview")

    # ------------------------------------------------------------------ 侧边栏
    def _build_sidebar(self, profile: dict) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(200)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(16, 20, 16, 18)
        layout.setSpacing(8)

        # 品牌：山峰 Logo + 见山 + 副标题
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo = QLabel(bar)
        logo.setPixmap(svg_pixmap("brand_mark.svg", 30, 30))
        logo.setFixedSize(30, 30)
        brand_row.addWidget(logo)
        brand_row.addWidget(make_label("见山", "AppName"))
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
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
            icon_name = NAV_ICONS.get(key)
            if icon_name:
                btn.setIcon(QIcon(svg_pixmap(icon_name, 18, 18)))
                btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            self.nav_group.addButton(btn, index)
            layout.addWidget(btn)

        layout.addStretch(1)

        # 底部：支持中心 / 设置 / 教师身份 / 退出
        layout.addWidget(make_label("支持中心", "Hint"))
        layout.addWidget(make_label("设置", "Hint"))
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
