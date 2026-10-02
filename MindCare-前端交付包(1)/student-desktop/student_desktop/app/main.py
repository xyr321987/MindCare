"""学生端入口：`QApplication` + 主窗口 + Tab（`docs/UI约定.md` §0/§5.1）。

启动（UI约定 §0 的启动方式）::

    $py = 'C:\\Users\\cu\\.dsh\\dsh-runtimes\\dsh-primary-runtime\\dependencies\\python\\python.exe'
    Set-Location 'E:\\Users data\\Desktop\\黑客松项目\\mindcare'
    & $py -m student_desktop.app.main --server http://127.0.0.1:8080

无显示器环境下::

    $env:QT_QPA_PLATFORM='offscreen'
    & $py -m student_desktop.app.selfcheck

网络纪律（UI约定 §3/§7）：**主线程永远不调用 `ApiClient`**。
`ApiClient` 实例只被 `_submit` / `_load_*` 这些"只负责投递 worker"的方法引用，
真正执行在 `QThreadPool`；自检会断言"主线程上的传输层调用次数 == 0"。
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QSize, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_common import theme
from desktop_common import appointments
from desktop_common import schedule as schedule_mod
from desktop_common.api import ApiClient, ApiError, new_id, now_iso
from desktop_common.copy import COPY
from desktop_common.widgets import (
    Card,
    divider,
    enforce_focus_policy,
    hotline_label,
    make_body,
    make_error,
    make_ghost_button,
    make_hint,
    make_label,
    make_primary_button,
    make_title,
)

from .worker import TaskRunner

from ..ui.profile import ProfileTab
from ..ui.pages import AppointmentPage, NoticePage
from ..ui.questionnaire import QuestionnaireTab
from ..ui.treehole import TreeholeTab
from ..ui.home import HomePage, svg_pixmap

__all__ = [
    "LoginView", "StudentMainWindow", "AboutTab", "build_client", "main",
    "normalize_student_no", "ENGINE_NOT_READY_KEY",
]

#: 「数据库恢复中，稍后再试」用哪条文案。
#:
#: ✅ 2026-10-02：原实现借用教师端键 `t.login.error.network`（「暂时连不上服务，稍后再试就好。」），
#: 有两处不妥：① 语义不准 —— 服务明明连得上，只是数据库在恢复；
#: ② 学生端复用教师端文案。现已在 `copywriting.md` §4.7 正式收录专用键，改用之。
ENGINE_NOT_READY_KEY = "c.engine.notReady"

#: 提交被就绪闸拦下时的提示（`copywriting.md` §4.7）。
ENGINE_NOT_READY_SUBMIT_KEY = "c.engine.notReady.action"

#: 演示学号前缀（种子名单为 `stu_2023001` ~ `stu_2023012`）。
#: ⚠️ 这是**数据格式**（学号 ID 的词法前缀，契约 §2.1 `profile.id` 为 `stu_` 前缀），
#: 与界面文案无关，因此可以写成常量；面向用户的提示文字仍全部来自文案表。
STUDENT_NO_PREFIX = "stu_"


def normalize_student_no(raw: str) -> str:
    """把登录框里的输入规范成「号次」形态（v1.1 注册制）。

    注册制下号次由学生注册时自定、全校唯一，登录**原样发送**、不做前缀补全
    （服务端按 `seat_no` 精确查表）。这里只做「去首尾空白」这一条确定性改写。
    """
    return (raw or "").strip()


def build_client(server: str, *, instrument: bool = True, stats=None) -> ApiClient:
    """构造 `ApiClient`；默认给传输层套一层**计数器**（自检用来证明主线程没发请求）。

    :param instrument: 是否套计数器
    :param stats: 计数器目标（默认 `worker.STATS`；自检每段用独立实例，互不串味）
    """
    from . import worker as worker_module

    counter = stats if stats is not None else worker_module.STATS
    client = ApiClient(server)
    if instrument:
        original = client._do_http

        def counted(method, url, body, token, timeout):
            counter.note_transport()
            return original(method, url, body, token, timeout)

        client._transport = counted
    return client


# --------------------------------------------------------------------------- 登录页


class LoginView(QWidget):
    """登录页（v1.1 注册制）：号次 + 密码登录；可切换「注册」（班级/姓名/号次/密码）。

    号次由学生注册时自定、全校唯一；登录**原样发送**（`normalize_student_no` 仅去空白）。
    占位符/提示文字仍只来自文案表，不硬编码中文。
    """

    #: 请求登录：(号次, 密码)
    login_requested = Signal(str, str)
    #: 请求注册：(班级, 姓名, 号次, 密码)
    register_requested = Signal(str, str, str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LoginView")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(16)
        outer.addStretch(1)

        self.card = Card()
        self.card.add(make_title(COPY["c.login.title"]))
        self.card.add(make_hint(COPY["c.login.subtitle"]))
        self.card.add(make_hint(COPY["c.login.demoNote"]))

        self.card.add(make_label(COPY["c.login.studentNo"], "Heading"))
        self.student_input = QLineEdit()
        self.student_input.setObjectName("StudentNoInput")
        self.student_input.setFocusPolicy(Qt.StrongFocus)
        self.student_input.setPlaceholderText(COPY["c.login.studentNo"])
        self.student_format_hint = make_hint(COPY["c.login.studentNo.format"])
        self.student_format_hint.setObjectName("LoginFormatHint")
        self.student_input.setToolTip(COPY["c.login.studentNo.format"])
        self.card.add(self.student_input)
        self.card.add(self.student_format_hint)

        # 注册专用字段（默认隐藏）
        self.class_label = make_label(COPY["c.login.className"], "Heading")
        self.class_input = QLineEdit()
        self.class_input.setObjectName("RegisterClassInput")
        self.class_input.setFocusPolicy(Qt.StrongFocus)
        self.class_input.setPlaceholderText(COPY["c.login.className"])
        self.name_label = make_label(COPY["c.login.name"], "Heading")
        self.name_input = QLineEdit()
        self.name_input.setObjectName("RegisterNameInput")
        self.name_input.setFocusPolicy(Qt.StrongFocus)
        self.name_input.setPlaceholderText(COPY["c.login.name"])
        self._register_widgets = [self.class_label, self.class_input,
                                  self.name_label, self.name_input]
        for widget in self._register_widgets:
            self.card.add(widget)
            widget.setVisible(False)

        self.card.add(make_label(COPY["c.login.password"], "Heading"))
        self.password_input = QLineEdit()
        self.password_input.setObjectName("StudentPasswordInput")
        self.password_input.setFocusPolicy(Qt.StrongFocus)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText(COPY["c.login.password"])
        self.card.add(self.password_input)

        self.error_label = make_error("")
        self.card.add(self.error_label)

        self.enter_button = make_primary_button(COPY["c.login.action.submit"])
        self.enter_button.setObjectName("LoginButton")
        self.enter_button.clicked.connect(self._on_enter)
        self.card.add(self.enter_button)

        self.toggle_button = make_ghost_button(COPY["c.login.toggle.register"])
        self.toggle_button.setObjectName("ToggleRegisterButton")
        self.toggle_button.clicked.connect(self._toggle_mode)
        self.card.add(self.toggle_button)

        self.card.add(divider())
        self.card.add(make_hint(COPY["c.hotline.footer"]))
        self.card.add(hotline_label(COPY.hotline_line()))

        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self.card, 3)
        holder.addStretch(1)
        outer.addLayout(holder)
        outer.addStretch(2)

        self._register_mode = False

    # -- 模式切换 -----------------------------------------------------------
    def _toggle_mode(self) -> None:
        self._register_mode = not self._register_mode
        for widget in self._register_widgets:
            widget.setVisible(self._register_mode)
        self.enter_button.setText(
            COPY["c.login.action.register"] if self._register_mode
            else COPY["c.login.action.submit"])
        self.toggle_button.setText(
            COPY["c.login.toggle.login"] if self._register_mode
            else COPY["c.login.toggle.register"])
        self.set_error("")

    def _on_enter(self) -> None:
        if self._register_mode:
            self.register_requested.emit(
                self.class_input.text().strip(), self.name_input.text().strip(),
                self.student_input.text().strip(), self.password_input.text())
        else:
            self.login_requested.emit(
                self.student_input.text().strip(), self.password_input.text())

    # -- 读取 ---------------------------------------------------------------
    def student_no(self) -> str:
        """号次输入框原文（未规范化）。"""
        return self.student_input.text().strip()

    def password(self) -> str:
        return self.password_input.text()

    def normalized_student_no(self) -> str:
        """实际会发给服务端的号次（仅去首尾空白，不做前缀补全）。"""
        return normalize_student_no(self.student_no())

    def set_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))


# --------------------------------------------------------------------------- 关于页


class AboutTab(QWidget):
    """关于页：非诊断声明 + 危机热线（UI约定 §6 页脚硬要求）。

    声明的条目清单与问卷告知页**同源**（`NoticePage.item_indexes`）：v1.0 里
    `s.notice.item4/5/6` 描述的匿名转交通道与"事后收回可见性"两条能力都不存在，
    两处一起不渲染，避免关于页继续承诺已下线的能力。

    另提供**登出入口**（`c.action.logout`）：登出会同时清掉内存 token 与本地
    登录态文件（`%LOCALAPPDATA%\\MindCare\\session.json`）。
    """

    #: 请求登出（由主窗口清 token + 清登录态文件 + 回登录页）
    logout_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("AboutTab")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)
        card = Card()
        for index in NoticePage.item_indexes:
            card.add(make_body("· " + COPY[f"s.notice.item{index}"]))
        card.add(divider())
        # 非诊断声明（`docs/UI约定.md` §6 硬要求：「页脚/关于页必须含：非诊断声明 + 危机热线」；
        # 文案在 `copywriting.md` §4.8 单独登记 —— §6.6 规定否定式免责须单独登记）。
        # ⚠️ 2026-10-02 修正：这里原先渲染的是 `c.loading.generic`＝「稍等一下…」，
        #    把**加载提示**当成了关于页的静态内容（可见缺陷）；同时类 docstring 声称
        #    "非诊断声明 + 危机热线"却并没有声明。两处一并修掉。
        card.add(make_hint(COPY["c.disclaimer.nondiagnostic"]))
        card.add(make_hint(COPY["c.hotline.footer"]))
        card.add(hotline_label(COPY.hotline_line()))
        card.add(divider())
        self.logout_button = make_ghost_button(COPY["c.action.logout"])
        self.logout_button.setObjectName("LogoutButton")
        self.logout_button.clicked.connect(self.logout_requested.emit)
        card.add(self.logout_button)
        outer.addWidget(card)
        outer.addStretch(1)


class SideNav(QWidget):
    """左侧导航栏（浅米白）+ 内容栈（`QTabWidget` 西向的自定义替代）。

    结构（见山规范）::

        顶部品牌（「见山」+ 标语）
        中部功能菜单（首页 / 问卷 / 树洞 / 我的档案 / 预约）
        底部（设置 / 关于 / 用户信息）

    菜单与「关于」都是可勾选按钮（`QButtonGroup` 互斥），点击切换 `QStackedWidget`。
    为免改动自检与主窗口里大量 `tabs` 用法，保留 `QTabWidget` 常用接口：
    `count / tabText / widget / currentWidget / setCurrentWidget / currentIndex /
    setCurrentIndex / indexOf` 与 `currentChanged(int)`。
    """

    currentChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainTabs")

        self._pages: List[QWidget] = []
        self._buttons: List[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        #: 「设置」入口指向的页面（主窗口在创建完「关于」页后注入）
        self._settings_target: Optional[QWidget] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.nav_bar = QWidget(self)
        self.nav_bar.setObjectName("SideNavBar")
        nav = QVBoxLayout(self.nav_bar)
        nav.setContentsMargins(18, 26, 18, 20)
        nav.setSpacing(6)

        # ---- 品牌 ----
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self.brand_mark = QLabel(self.nav_bar)
        self.brand_mark.setPixmap(svg_pixmap("brand_mark.svg", 30, 30))
        self.brand_mark.setFixedSize(30, 30)
        brand_row.addWidget(self.brand_mark)
        self.brand_label = make_label(COPY["home.nav.brand"], "NavBrand", word_wrap=False)
        brand_row.addWidget(self.brand_label)
        brand_row.addStretch(1)
        nav.addLayout(brand_row)
        self.slogan_label = make_label(COPY["home.nav.slogan"], "NavBrandSlogan", word_wrap=False)
        nav.addWidget(self.slogan_label)
        nav.addSpacing(22)

        # ---- 菜单 ----
        self._menu_layout = QVBoxLayout()
        self._menu_layout.setSpacing(6)
        nav.addLayout(self._menu_layout)
        nav.addStretch(1)

        # ---- 底部：设置 / 关于 / 用户信息 ----
        self._bottom_layout = QVBoxLayout()
        self._bottom_layout.setSpacing(6)
        nav.addLayout(self._bottom_layout)

        self.settings_button = QPushButton(COPY["home.nav.settings"], self.nav_bar)
        self.settings_button.setObjectName("NavItem")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setFocusPolicy(Qt.StrongFocus)
        self.settings_button.setIcon(QIcon(svg_pixmap("icon_settings.svg", 18, 18)))
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.clicked.connect(self._open_settings)
        self._bottom_layout.addWidget(self.settings_button)

        user_card = QWidget(self.nav_bar)
        user_card.setObjectName("NavUserCard")
        user_lay = QHBoxLayout(user_card)
        user_lay.setContentsMargins(12, 12, 12, 12)
        user_lay.setSpacing(10)
        self.avatar = QLabel("", user_card)
        self.avatar.setObjectName("NavAvatar")
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setFixedSize(36, 36)
        user_lay.addWidget(self.avatar)
        user_text = QVBoxLayout()
        user_text.setSpacing(1)
        self.user_name = make_label("", "NavUserName", word_wrap=False)
        self.user_class = make_label("", "NavUserClass", word_wrap=False)
        user_text.addWidget(self.user_name)
        user_text.addWidget(self.user_class)
        user_lay.addLayout(user_text)
        user_lay.addStretch(1)
        self._user_card = user_card
        self._bottom_layout.addWidget(self._user_card)

        self.pages = QStackedWidget(self)
        self.pages.setObjectName("MainPages")

        layout.addWidget(self.nav_bar)
        layout.addWidget(self.pages, 1)

        self._group.idClicked.connect(self._on_item_clicked)

    def add_page(self, page: QWidget, title: str, *, bottom: bool = False,
                 icon: str = "") -> None:
        """追加一个内容页 + 对应导航按钮（`bottom=True` 放到底部「关于」区）。"""
        index = len(self._pages)
        button = QPushButton(title, self.nav_bar)
        button.setObjectName("NavItem")
        button.setCheckable(True)
        button.setFocusPolicy(Qt.StrongFocus)
        button.setCursor(Qt.PointingHandCursor)
        if icon:
            button.setIcon(QIcon(svg_pixmap(icon, 18, 18)))
            button.setIconSize(QSize(18, 18))
        self._group.addButton(button, index)
        if bottom:
            target = self._bottom_layout
            at = target.indexOf(self._user_card)
            target.insertWidget(max(0, at), button)
        else:
            self._menu_layout.addWidget(button)
        self._buttons.append(button)
        self._pages.append(page)
        self.pages.addWidget(page)
        if index == 0:
            button.setChecked(True)

    def set_settings_target(self, page: QWidget) -> None:
        """「设置」入口指向的页面（无独立设置页，暂指向「关于」）。"""
        self._settings_target = page

    def set_user(self, profile: Optional[dict]) -> None:
        """更新底部用户信息（头像首字 + 姓名 + 班级）。"""
        profile = profile or {}
        name = str(profile.get("name") or "").strip()
        class_name = str(profile.get("class_name") or "").strip()
        self.user_name.setText(name)
        self.user_class.setText(class_name)
        self.avatar.setText(name[:1] if name else "")

    def _open_settings(self) -> None:
        if self._settings_target is not None:
            self.setCurrentWidget(self._settings_target)

    # -- 兼容 QTabWidget 的常用接口 -----------------------------------------

    def count(self) -> int:
        return len(self._pages)

    def tabText(self, index: int) -> str:
        return self._buttons[index].text()

    def widget(self, index: int) -> QWidget:
        return self._pages[index]

    def indexOf(self, widget: QWidget) -> int:
        return self._pages.index(widget)

    def currentIndex(self) -> int:
        return self.pages.currentIndex()

    def setCurrentIndex(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self._buttons[index].setChecked(True)
        self.currentChanged.emit(index)

    def currentWidget(self) -> Optional[QWidget]:
        return self.pages.currentWidget()

    def setCurrentWidget(self, widget: QWidget) -> None:
        self.setCurrentIndex(self.indexOf(widget))

    # -- 内部 ---------------------------------------------------------------

    def _on_item_clicked(self, index: int) -> None:
        if index != self.pages.currentIndex():
            self.setCurrentIndex(index)


# --------------------------------------------------------------------------- 主窗口


class StudentMainWindow(QMainWindow):
    """主窗口：登录页 → (问卷 | 树洞 | 我的档案 | 关于)。"""

    def __init__(self, server: str = "http://127.0.0.1:8080",
                 *, client: Optional[ApiClient] = None,
                 pool: Optional[QThreadPool] = None,
                 restore_session: bool = True,
                 health_poll_ms: int = 10000) -> None:
        super().__init__()
        self.setObjectName("StudentMainWindow")
        self.setWindowTitle(COPY["home.nav.brand"])
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)

        self.client = client or build_client(server)
        self.runner = TaskRunner(pool or QThreadPool.globalInstance())
        self.student_no = ""
        #: 未完成的异步请求句柄（新请求到达时断开旧回调，避免过期结果覆盖界面）
        self._pending: Dict[str, Any] = {}
        #: 已经回调完成或作废的 worker（退出前统一 join，避免"仍在运行的 QThread"）
        self._finished: list = []
        #: 服务端 `engine_ready`（数据库就绪信号，协议 §2.2/§5）。
        #: 默认 `True`：health 响应里缺这个字段时按"就绪"处理（老服务端兼容），
        #: 只有**明确** `False` 才降级提示 + 禁用提交。
        self.engine_ready = True
        #: 是否已经成功读到过一次 `engine_ready`（用于"启动即请求"的自证）
        self.health_checked = False
        self.health_payload: Dict[str, Any] = {}
        self.health_error: Optional[str] = None
        self._health_worker: Any = None
        self._health_timer: Optional[QTimer] = None
        self.health_poll_ms = max(500, int(health_poll_ms))
        #: 应用启动时**是否直接从本地登录态恢复**（自检要求 2 的断言点）
        self.session_restored = False

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("RootStack")
        self.login_view = LoginView()
        self.tabs = SideNav()

        #: 预约页要显示"班级 / 学号"，取当前登录档案（`client.profile` 由登录写入）
        self.home_page = HomePage()
        self.questionnaire_page = QuestionnaireTab(
            profile_provider=self._current_profile,
            client=self.client, runner=self.runner)
        self.treehole_page = TreeholeTab()
        self.profile_page = ProfileTab()
        self.appointment_page = AppointmentPage(
            profile_provider=self._current_profile, standalone=True,
            client=self.client, runner=self.runner)
        self.about_page = AboutTab()
        self.tabs.add_page(self.home_page, COPY["home.nav.home"], icon="icon_home.svg")
        self.tabs.add_page(self.questionnaire_page, COPY["c.tab.questionnaire"],
                           icon="icon_questionnaire.svg")
        self.tabs.add_page(self.treehole_page, COPY["s.treehole.tab.title"],
                           icon="icon_treehole.svg")
        self.tabs.add_page(self.profile_page, COPY["c.tab.profile"],
                           icon="icon_profile.svg")
        self.tabs.add_page(self.appointment_page, COPY["c.tab.appointment"],
                           icon="icon_appointment.svg")
        self.tabs.add_page(self.about_page, COPY["c.tab.about"], bottom=True,
                           icon="icon_about.svg")
        self.tabs.set_settings_target(self.about_page)

        self.stack.addWidget(self.login_view)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        #: 顶部**非阻塞**状态条：`engine_ready=false` 时可见（不弹模态、不挡填写）。
        #: 固定高度 + 单行省略：它要让开内容区，不能把整个问卷页往下顶。
        self.engine_notice = make_error("")
        self.engine_notice.setObjectName("EngineNotice")
        self.engine_notice.setVisible(False)
        self.engine_notice.setFixedHeight(32)
        self.engine_notice.setContentsMargins(24, 0, 24, 0)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.engine_notice)
        central_layout.addWidget(self.stack)
        self.setCentralWidget(central)

        self.status_label = make_hint("")
        self.statusBar().addPermanentWidget(self.status_label)
        #: 危机热线常驻窗口底部边缘：视觉弱化（见 QLabel#Hotline）后仍保证始终可见
        self.hotline = hotline_label(COPY.hotline_line())
        self.statusBar().addWidget(self.hotline)

        self._wire()
        # 键盘可达：兜底给所有可点控件补 StrongFocus（UI约定 §2 硬要求 4）
        enforce_focus_policy(self)
        self.show_login()

        # 启动即取一次 `/health`（协议 §2.2：engine_ready 是数据库就绪信号）；
        # 之后按 `health_poll_ms` 轮询，**恢复为 True 时提示自动消失、按钮自动恢复**。
        self._apply_engine_ready()
        self.check_health()
        self.start_health_polling()

        # 登录态持久化（协议 §2.1「token 持久化存储」）：本地有**未过期**的
        # session 就直接进主窗，不再弹登录页。过期/损坏时 `load_session()` 已静默
        # 清掉文件并返回 None，这里就正常停在登录页。
        if restore_session and not self.try_restore_session():
            self.show_login()

    # ---------------------------------------------------------------- 装配

    def _current_profile(self) -> dict:
        """当前登录档案（`{id, name, class_name}`），供预约页显示预约人基本信息。

        没登录时把已输入的学号兜底填进 `id` —— 预约记录**必须**能定位到人，
        但界面上"学号"那栏空着会让以为没带上，所以宁可显示已输入的那串。
        """
        profile = self.client.profile or {}
        if not isinstance(profile, dict):
            profile = {}
        if not profile.get("id") and self.student_no:
            profile = dict(profile)
            profile["id"] = self.student_no
        return profile

    def _wire(self) -> None:
        self.login_view.login_requested.connect(self._on_login_clicked)
        self.login_view.register_requested.connect(self._on_register_clicked)
        self.login_view.student_input.textChanged.connect(
            lambda: self.login_view.set_error(""))
        self.login_view.password_input.textChanged.connect(
            lambda: self.login_view.set_error(""))
        self.login_view.student_input.returnPressed.connect(self.login_view._on_enter)
        self.login_view.password_input.returnPressed.connect(self.login_view._on_enter)
        self.about_page.logout_requested.connect(self.logout)

        self.questionnaire_page.submit_requested.connect(self._submit_questionnaire)
        self.questionnaire_page.treehole_deeplink.connect(self.open_treehole_editor)
        self.questionnaire_page.restart_requested.connect(self.questionnaire_page.reset)

        self.treehole_page.dates_requested.connect(self._load_treehole_dates)
        self.treehole_page.entries_requested.connect(self._load_treehole_entries)
        self.treehole_page.save_requested.connect(self._save_treehole_entry)

        self.profile_page.dates_requested.connect(self._load_profile_dates)
        self.profile_page.profile_requested.connect(self._load_profile)
        self.profile_page.mood_range_requested.connect(self._load_mood_range)

        self.appointment_page.confirmed.connect(self._on_standalone_appointment_confirmed)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.home_page.navigate.connect(self._on_home_navigate)

    def _on_home_navigate(self, key: str) -> None:
        """首页四张功能卡片 → 切到对应功能页。"""
        mapping = {
            "questionnaire": self.questionnaire_page,
            "treehole": self.treehole_page,
            "appointment": self.appointment_page,
            "profile": self.profile_page,
        }
        page = mapping.get(key)
        if page is not None:
            self.tabs.setCurrentWidget(page)

    # ---------------------------------------------------------------- 异步工具

    def _start(self, key: str, fn: Any, *args: Any, on_done: Any, on_fail: Any) -> Any:
        """投递一个后台请求：同一个 key 的旧请求会被作废（断开回调）。"""
        previous = self._pending.pop(key, None)
        if previous is not None:
            self._finished.append(previous)
            try:
                previous.signals.done.disconnect()
                previous.signals.failed.disconnect()
            except (RuntimeError, TypeError):    # pragma: no cover - 已断开
                pass
        worker = self.runner.submit(fn, *args, done=on_done, failed=on_fail)
        worker.signals.finished.connect(lambda w=worker: self._finished.append(w))
        self._pending[key] = worker
        return worker

    def _on_async_failed(self, error: Any) -> None:
        # 1001（未登录 / token 过期）→ 清登录态 + 回登录页，并**就地返回**：
        # 已经切走页面了，再往档案页/树洞页写错误文案只会让人以为还停在原页。
        # 其它错误码（1002 / 2001 / 2002 / 3001 / 4001 / 网络）**只在当前页提示**。
        if self.handle_failure(error):
            return
        text = self.error_text(error)
        self.profile_page.show_error(text)
        self.treehole_page.show_error(text)

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        """关闭前收尾：等所有后台 worker 结束（避免 Qt 报"仍在运行的 QThread"）。"""
        self._pending.clear()
        if self._health_timer is not None:
            self._health_timer.stop()
        return self.runner.wait(timeout_ms)

    # ---------------------------------------------------------------- 服务端就绪
    # 协议 §2.2「engine_ready(bool，数据库就绪信号——false 时提示稍后再试）」
    # 协议 §5「engine_ready=false 时（数据库恢复中）所有带鉴权请求应提示稍后重试」

    def check_health(self) -> Any:
        """取一次 `/health`（公共、免鉴权，**在 worker 线程里跑**）。

        失败（网络不可用等）**不弹错**：只按"还不能提交"处理 ——
        学生看到的是"稍后再试"，而不是技术措辞。
        """
        if self._health_worker is not None and self._health_worker.result is None \
                and self._health_worker.error is None:
            return self._health_worker          # 上一次还没回来，不重复投递
        worker = self.runner.submit(self.client.health,
                                    done=self._on_health_ok,
                                    failed=self._on_health_failed)
        self._health_worker = worker
        return worker

    def start_health_polling(self) -> None:
        """开始轮询 `/health`（默认 10s 一次），用于**自动恢复**。"""
        if self._health_timer is None:
            self._health_timer = QTimer(self)
            self._health_timer.timeout.connect(self.check_health)
        self._health_timer.start(self.health_poll_ms)

    def stop_health_polling(self) -> None:
        if self._health_timer is not None:
            self._health_timer.stop()

    def _on_health_ok(self, data: Any) -> None:
        payload = data if isinstance(data, dict) else {}
        self.health_payload = payload
        self.health_error = None
        self.health_checked = True
        # 缺字段时按"就绪"（判据写成 `is not False`）：只有服务端**明确**报了
        # false 才降级，避免老服务端 / 字段改名时把整个应用锁死。
        self.set_engine_ready(payload.get("engine_ready") is not False)

    def _on_health_failed(self, error: Any) -> None:
        self.health_checked = True
        self.health_error = f"{type(error).__name__}: {error}"
        if not self.engine_ready:
            return                              # 已经降级过就不重复刷提示
        self.set_engine_ready(False)

    def set_engine_ready(self, ready: bool) -> None:
        """更新"数据库是否就绪"的界面状态（提示条 + 提交按钮）。"""
        self.engine_ready = bool(ready)
        self._apply_engine_ready()

    def _apply_engine_ready(self) -> None:
        # 提示条：**非阻塞**（一个 QLabel，不弹模态、不挡填写）
        self.engine_notice.setText("" if self.engine_ready else self.engine_notice_text())
        self.engine_notice.setVisible(not self.engine_ready)
        # 提交按钮：`engine_ready=false` 时禁用，避免学生填完整份问卷才失败
        self.questionnaire_page.set_engine_ready(self.engine_ready)

    def engine_notice_text(self) -> str:
        """`engine_ready=false` 的提示文案（来自文案表，见 `ENGINE_NOT_READY_KEY`）。"""
        return COPY[ENGINE_NOT_READY_KEY]

    # ---------------------------------------------------------------- 登录态持久化

    def try_restore_session(self, *, now: Optional[float] = None) -> bool:
        """尝试用本地登录态直接进主窗（协议 §2.1「token 持久化存储」）。

        文件不存在 / 已过期 / 损坏时 `ApiClient.load_session()` 已经静默处理完
        （过期与损坏的文件顺手删掉），这里只是返回 `False` 让调用方停在登录页。

        :return: 是否恢复成功（`True` 时**不显示登录页**）
        """
        data = self.client.load_session(now=now) if now is not None \
            else self.client.load_session()
        if not data:
            return False
        profile = data.get("profile") or {}
        self.student_no = str(profile.get("id") or self.student_no or "")
        self.login_view.student_input.setText(self.student_no)
        self.login_view.set_error("")
        self.session_restored = True
        self.status_label.setText(
            f"{profile.get('name', '')} · {profile.get('class_name') or ''}".strip(" ·")
        )
        self.show_main()
        self.home_page.set_profile(profile)
        self.tabs.set_user(profile)
        self._load_profile_dates()
        self._load_treehole_dates()
        return True

    def logout(self) -> None:
        """登出：清内存 token + 删本地登录态文件 + 回登录页（入口在「关于」页）。"""
        self.client.clear_session()
        self._leave_session("")

    def _leave_session(self, message: str) -> None:
        """`1001` 与登出共用的收尾：回到登录页并把界面状态复位。"""
        self.session_restored = False
        self.student_no = ""
        self.status_label.setText("")
        self._pending.clear()
        self.questionnaire_page.reset()
        self.appointment_page.reset()
        self.profile_page.show_error("")
        self.treehole_page.show_error("")
        self.treehole_page.set_entries([])
        self.treehole_page.set_dates([])
        self.profile_page.set_dates([])
        self.home_page.set_profile({})
        self.tabs.set_user({})
        # 清空登录框：登录成功后 `student_input` 会被填成 `profile.id`（`stu_` 前缀），
        # 若不清空，退出再登录会把 `stu_2023001` 当号次发给服务端 → 学生不存在，
        # 学生就像被锁在账号外、记录"消失"了。这里让下次登录从空白号次开始。
        self.login_view.student_input.setText("")
        self.login_view.password_input.setText("")
        self.show_login()
        self.login_view.set_error(message)
        # 回登录页后顺手刷新一次引擎状态：登录页虽然不能提交问卷，但"服务端在不在"
        # 会影响到恢复到主窗后的第一印象（且这是唯一不需要 token 的端点）。
        self.check_health()

    def handle_failure(self, error: Any) -> bool:
        """契约错误码的统一分诊。

        * `1001`（未登录 / token 过期，协议 §1「**跳登录**」）→
          清内存 token + 清本地登录态文件 + 切回登录页，显示 `c.error.1001`，
          并返回 `True`（调用方应当**就地返回**，不要再往旧页面写文案）；
        * 其它错误码 → 返回 `False`，调用方照常"留在当前页显示错误"
          （2001 / 2002 / 3001 / 4001 / 网络层都**不**跳登录）。

        所有失败路径（`_on_async_failed` / 问卷提交 / 档案 / 树洞 / 登录）都过这一处，
        避免"两处各写一份判断"那样漏掉一条路径。
        """
        if not isinstance(error, ApiError) or error.is_network:
            return False
        if str(error.code) != "1001":
            return False
        self.client.clear_session()
        self._leave_session(self.error_text(error))
        return True

    # ---------------------------------------------------------------- 登录

    def show_login(self) -> None:
        self.stack.setCurrentWidget(self.login_view)
        self.login_view.student_input.setFocus(Qt.OtherFocusReason)

    def show_main(self) -> None:
        self.stack.setCurrentWidget(self.tabs)

    def _on_login_clicked(self, seat_no: str, password: str) -> None:
        if not seat_no or not password:
            self.login_view.set_error(COPY["c.error.2001"])
            return
        self.login_view.set_error(COPY["c.loading.generic"])
        worker = self.runner.submit(self._login_worker, seat_no, password,
                                    done=self._on_login_ok,
                                    failed=self._on_login_failed)

    def _login_worker(self, seat_no: str, password: str) -> dict:
        # ⚠️ 本函数在 QThreadPool 线程里执行（不是主线程）
        return self.client.login_student(seat_no, password)

    def _on_register_clicked(self, class_name: str, name: str,
                             seat_no: str, password: str) -> None:
        if not class_name or not name or not seat_no or not password:
            self.login_view.set_error(COPY["c.error.2001"])
            return
        self.login_view.set_error(COPY["c.loading.generic"])
        worker = self.runner.submit(self._register_worker,
                                    class_name, name, seat_no, password,
                                    done=self._on_login_ok,
                                    failed=self._on_register_failed)

    def _register_worker(self, class_name: str, name: str,
                         seat_no: str, password: str) -> dict:
        # ⚠️ 本函数在 QThreadPool 线程里执行
        return self.client.register_student(class_name, name, seat_no, password)

    def _on_register_failed(self, error: Any) -> None:
        if self.handle_failure(error):
            return
        self.login_view.set_error(self.error_text(error))

    def _on_login_ok(self, data: Any) -> None:
        profile = (data or {}).get("profile") or {}
        # 用**规范化后**的学号（服务端 profile.id 本来就是 `stu_` 形态）
        self.student_no = str(profile.get("id") or self.login_view.normalized_student_no())
        self.login_view.student_input.setText(self.student_no)
        self.login_view.set_error("")
        self.status_label.setText(
            f"{profile.get('name', '')} · {profile.get('class_name') or ''}".strip(" ·")
        )
        # token 已由 `ApiClient.login_student()` 落盘（协议 §2.1）
        self.session_restored = False
        self.show_main()
        self.home_page.set_profile(profile)
        self.tabs.set_user(profile)
        self._load_profile_dates()
        self._load_treehole_dates()
        # 登录后立刻校一次引擎就绪：数据库正在恢复时，提交按钮当场就是禁用的
        self.check_health()

    def _on_login_failed(self, error: Any) -> None:
        if self.handle_failure(error):
            return
        self.login_view.set_error(self.error_text(error))

    # ---------------------------------------------------------------- 错误文案

    def error_text(self, error: Any) -> str:
        """把异常翻成**文案表**里的用户可读句子（不暴露技术措辞）。"""
        if isinstance(error, ApiError):
            if error.code == 2001 and error.field:
                return COPY["c.error.2001.field"].replace("{field}", error.field)
            return COPY.error(error.copy_key)
        return COPY["c.error.unknown"]

    def _busy(self, text: str) -> None:
        self.status_label.setText(text)

    # ---------------------------------------------------------------- 问卷提交

    def _submit_questionnaire(self, body: dict) -> None:
        """一次性 `POST /questionnaire/submissions`（唯一的一次网络请求）。"""
        if not self.submission_allowed():
            return
        body = dict(body)
        # 幂等键由客户端生成，且**同一次填写只用同一个 record_id**（重试不会重复落库）
        record_id = self.questionnaire_page.state.record_id or new_id("rec_")
        self.questionnaire_page.state.record_id = record_id
        body["record_id"] = record_id
        if body.get("consent_share"):
            body["consent_ts"] = now_iso()     # 单独同意的留痕时间戳
        else:
            body["consent_ts"] = None
        # 预约时间（HTTP 共享库）：request_help=true 且选了预约时间时，先落预约
        # `POST /appointments`（幂等），成功后再走一次性问卷提交。
        appt = self.questionnaire_page.state.appointment
        if body.get("request_help") and appt:
            self._busy(COPY["s.branch.a.toast.saving"])
            self._create_appointment_then_submit(appt, body)
            return
        self._busy(COPY["s.branch.a.toast.saving"])
        self._start("submit", self.client.submit_questionnaire, body,
                    on_done=self._on_submit_ok, on_fail=self._on_submit_failed)

    def _appointment_body(self, appointment: dict) -> dict:
        """把预约载荷组装成 `POST /appointments` 的请求体（预约人由服务端从 token 推导）。

        幂等键 `apt_id` 由客户端生成并**回写到载荷**上；同一份载荷反复组包只用一个
        `apt_id`，超时重试 / 重提交不会重复落库。
        """
        apt_id = str(appointment.get("apt_id") or "")
        if not apt_id:
            apt_id = appointments.new_appointment_id()
            appointment["apt_id"] = apt_id
        return {
            "apt_id": apt_id,
            "year": str(appointment.get("year") or ""),
            "month": str(appointment.get("month") or ""),
            "day": str(appointment.get("day") or ""),
            "time": str(appointment.get("time") or ""),
            "teacher_id": appointment.get("teacher_id"),
            "share_questionnaire": bool(appointment.get("share_questionnaire", False)),
            "share_treehole": bool(appointment.get("share_treehole", False)),
        }

    def _create_appointment_then_submit(self, appointment: dict, body: dict) -> None:
        """先 `POST /appointments`（幂等），成功后再提交问卷。"""
        worker = self.runner.submit(
            self.client.create_appointment, self._appointment_body(appointment),
            done=lambda _data: self._after_appointment_created(appointment, body),
            failed=self._on_appointment_failed)

    def _after_appointment_created(self, appointment: dict, body: dict) -> None:
        # 预约已落库，清掉状态再发问卷，避免"重试 / 再次提交"重复写预约。
        self.questionnaire_page.state.appointment = None
        self._start("submit", self.client.submit_questionnaire, body,
                    on_done=self._on_submit_ok, on_fail=self._on_submit_failed)

    def _on_appointment_failed(self, error: Any) -> None:
        self._busy("")
        if self.handle_failure(error):      # 1001 → 已切回登录页
            return
        message = self.error_text(error)
        self.questionnaire_page.set_error(message)
        self.questionnaire_page.help.set_error(message)

    def _appointment_slot(self, appointment: dict) -> str:
        """预约载荷 → 格子 ID（独立标签页预约成功后把这一格刷绿用）。"""
        try:
            return schedule_mod.slot_id(
                int(appointment.get("year")), int(appointment.get("month")),
                int(appointment.get("day")), int(appointment.get("period")))
        except (TypeError, ValueError):
            return ""

    def _on_standalone_appointment_confirmed(self, appointment: dict) -> None:
        """独立「预约」标签页的确认：`POST /appointments` 成功后原地刷成「已预约」。

        与问卷流程（提交后即跳走）不同，独立标签页确认后停留在原地，把这一格刷成
        「已预约」（绿框）并给一条可读的成功回执。
        """
        if not appointment:
            return
        self._busy(COPY["s.branch.a.toast.saving"])
        worker = self.runner.submit(
            self.client.create_appointment, self._appointment_body(appointment),
            done=lambda _data: self._on_standalone_appointment_saved(appointment),
            failed=self._on_standalone_appointment_failed)

    def _on_standalone_appointment_saved(self, appointment: dict) -> None:
        self._busy("")
        self.appointment_page.mark_mine(self._appointment_slot(appointment))
        self.appointment_page.notify_saved(COPY["s.appointment.success"])
        self.appointment_page.set_error("")
        self.appointment_page._selected = None
        self.appointment_page.selected_label.setText(COPY["s.appointment.selected.none"])
        self.appointment_page.board.clear_selection()
        self.appointment_page._refresh()

    def _on_standalone_appointment_failed(self, error: Any) -> None:
        self._busy("")
        if self.handle_failure(error):      # 1001 → 已切回登录页
            return
        self.appointment_page.set_error(self.error_text(error))

    def _on_tab_changed(self, index: int) -> None:
        """切到「预约」页时开启实时同步（重刷红框），离开时停掉轮询。"""
        if self.tabs.widget(index) is self.appointment_page:
            self.appointment_page.enter()
        else:
            self.appointment_page.stop_sync()

    def submission_allowed(self) -> bool:
        """提交前的最后一道闸：`engine_ready=false` 时**不发请求**。

        "禁用按钮"只挡得住点按钮的那两条路径；问卷还有两条**自动提交**路径
        （高兴分支、平淡且填了原因），它们不经过按钮（见 `QuestionnaireTab`），
        所以这里是更靠底的一道闸。协议 §5 要求这时"提示稍后重试"。

        :return: 是否允许提交（`False` 时已在当前页给出文案）
        """
        if self.engine_ready:
            return True
        # 提交闸用「还不能提交」那条；顶部状态条用「稍等一下再试」那条（`copywriting.md` §4.7）
        text = COPY[ENGINE_NOT_READY_SUBMIT_KEY]
        self.questionnaire_page.set_error(text)
        self.questionnaire_page.help.set_error(text)
        return False

    def _on_submit_ok(self, data: Any) -> None:
        self._busy("")
        data = data or {}
        scene = str(data.get("result_scene") or "")
        tips = data.get("tips") or {}
        self.questionnaire_page.show_result(scene, tips_text=str(tips.get("text") or ""))
        # 新提交后档案需要重拉（共享状态与当日记录都可能变化）
        self._load_profile_dates()
        # 同一天连续提交时日期列表不变，`set_dates` 会跳过重拉；这里按服务端回执的
        # `date` 显式重拉当天档案，保证「每次提交都能在档案里看到自己的记录」。
        submitted_date = str(data.get("date") or "")
        if submitted_date:
            self._load_profile(submitted_date)

    def _on_submit_failed(self, error: Any) -> None:
        self._busy("")
        if self.handle_failure(error):      # 1001 → 已切回登录页
            return
        message = self.error_text(error)
        self.questionnaire_page.set_error(message)
        self.questionnaire_page.help.set_error(message)

    # ---------------------------------------------------------------- 树洞

    def _load_treehole_dates(self) -> None:
        self._start("treehole_dates", self.client.my_dates,
                    on_done=self._on_treehole_dates, on_fail=self._on_async_failed)

    def _on_treehole_dates(self, data: Any) -> None:
        dates = list((data or {}).get("dates") or [])
        self.treehole_page.set_dates(dates)

    def _load_treehole_entries(self, date: str) -> None:
        self._start("treehole_entries", self.client.my_treehole, date,
                    on_done=self._on_treehole_entries, on_fail=self._on_async_failed)

    def _on_treehole_entries(self, data: Any) -> None:
        self.treehole_page.set_entries(list((data or {}).get("entries") or []))

    def _save_treehole_entry(self, body: dict) -> None:
        payload = dict(body)
        payload["entry_id"] = new_id("tre_")
        worker = self.runner.submit(self.client.create_treehole, payload,
                                    done=self._on_treehole_saved,
                                    failed=self._on_treehole_save_failed)

    def _on_treehole_saved(self, data: Any) -> None:
        self.treehole_page.show_saved(COPY["s.treehole.save.donePrivate"])
        date = str((data or {}).get("ts") or "")[:10]
        if date:
            self._load_treehole_entries(date)

    def _on_treehole_save_failed(self, error: Any) -> None:
        if self.handle_failure(error):      # 1001 → 已切回登录页
            return
        self.treehole_page.show_error(self.error_text(error))

    def open_treehole_editor(self) -> None:
        """结果页「写树洞」深链：切到树洞 Tab 并打开编辑器（接口约定 §4.1）。"""
        self.tabs.setCurrentWidget(self.treehole_page)
        self.treehole_page.open_editor()

    # ---------------------------------------------------------------- 我的档案

    def _load_profile_dates(self) -> None:
        self._start("profile_dates", self.client.my_dates,
                    on_done=self._on_profile_dates, on_fail=self._on_async_failed)

    def _on_profile_dates(self, data: Any) -> None:
        self.profile_page.set_dates(list((data or {}).get("dates") or []))

    def _load_profile(self, date: str) -> None:
        self._start("profile", self.client.my_profile, date,
                    on_done=self._on_profile, on_fail=self._on_profile_failed)

    def _on_profile(self, data: Any) -> None:
        self.profile_page.set_profile(data or {})

    def _on_profile_failed(self, error: Any) -> None:
        if self.handle_failure(error):      # 1001 → 已切回登录页
            return
        self.profile_page.show_error(self.error_text(error))

    def _load_mood_range(self, start: str, end: str) -> None:
        self._start("mood_range", self.client.my_mood_range, start, end,
                    on_done=self._on_mood_range, on_fail=self._on_mood_range_failed)

    def _on_mood_range(self, data: Any) -> None:
        self.profile_page.set_mood_range(list((data or {}).get("items") or []))

    def _on_mood_range_failed(self, error: Any) -> None:
        if self.handle_failure(error):      # 1001 → 已切回登录页
            return
        self.profile_page.show_error(self.error_text(error))

    # v1.0：**没有**事后收回可见性的入口（`PATCH /questionnaire/submissions/{record_id}`
    # 不在契约的 11 个端点里），因此这里不再有任何对应的异步回调方法。


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m student_desktop.app.main",
        description="MindCare 学生端（PySide6）",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8080",
                        help="服务端地址（默认 http://127.0.0.1:8080）")
    parser.add_argument("--student-no", default="",
                        help="可选：预填学号（纯数字会自动补 stu_ 前缀）")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("MindCare")
    theme.install_fonts(app)
    theme.apply_theme(app)
    window = StudentMainWindow(args.server)
    if args.student_no:
        # 预填也走同一套规范化，避免 `--student-no 2023001` 直接吃 2002
        window.login_view.student_input.setText(normalize_student_no(args.student_no))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
