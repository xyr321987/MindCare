"""教师端入口：`QApplication` + 登录页 + 主窗口（预约时间表）。

启动::

    $env:PYTHONPATH = '<本包根目录>;<本包根目录>\\teacher-desktop'
    & $py -m teacher_desktop.app.main --server http://127.0.0.1:8080

无显示器环境下::

    $env:QT_QPA_PLATFORM='offscreen'
    & $py -m teacher_desktop.app.selfcheck

网络纪律（`docs/UI约定.md` §3）：**主线程永不调用 `ApiClient`**，
登录请求走 `QThreadPool`（`app/worker.py`）。

⚠️ 服务端由后端队友实现、不在本包内。服务端没起时，登录会失败；
此时可以用「离线演示」只连本机的预约库（`%LOCALAPPDATA%\\MindCare\\*.jsonl`）
查看课表与预约 —— 这也是自检跑的那条路径。
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_common import appointments as appt_store
from desktop_common import schedule_store
from desktop_common import theme
from desktop_common.api import ApiClient
from desktop_common.copy import COPY
from desktop_common.widgets import (
    Card,
    divider,
    enforce_focus_policy,
    hotline_label,
    make_error,
    make_ghost_button,
    make_hint,
    make_label,
    make_primary_button,
    make_title,
)

from .worker import STATS, TaskRunner

from ..ui.schedule import ScheduleTab

__all__ = [
    "LoginView", "TeacherMainWindow", "build_client", "main",
]

#: 演示教师工号前缀（与学生端 `stu_` 同款口径；具体名单由服务端决定）
TEACHER_NO_PREFIX = "tch_"


def normalize_teacher_no(raw: str) -> str:
    """把输入规范化成契约的工号形态（纯数字补 `tch_` 前缀）。

    与学生端 `normalize_student_no()` 同一套思路：服务端精确查表、不补全，
    演示时自然输入 `1001` 会当场拿到 2002，所以前端补前缀。
    """
    text = (raw or "").strip()
    if text.isdigit():
        return TEACHER_NO_PREFIX + text
    return text


def build_client(server: str, *, instrument: bool = True) -> ApiClient:
    """构造 `ApiClient`；默认给传输层套一层计数器（自检用来证明主线程没发请求）。"""
    client = ApiClient(server)
    if instrument:
        original = client._do_http

        def counted(method: str, url: str, body: Optional[dict],
                    token: Optional[str], timeout: float) -> Dict[str, Any]:
            STATS.note_transport()
            return original(method, url, body, token, timeout)

        client._transport = counted
    return client


# --------------------------------------------------------------------------- 登录


class LoginView(QWidget):
    """教师登录页（工号 + 密码；服务端不可用时可走「离线演示」）。"""

    #: 请求登录：`(工号, 密码)`
    login_requested = Signal(str, str)
    #: 只看本机预约库（服务端没起时用）
    demo_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("TeacherLoginView")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(16)
        outer.addStretch(1)

        self.card = Card()
        self.card.add(make_title(COPY["t.login.title"]))
        self.card.add(make_hint(COPY["t.login.subtitle"]))
        self.card.add(make_label(COPY["t.login.field.id"], "Heading"))
        self.id_input = QLineEdit()
        self.id_input.setObjectName("TeacherIdInput")
        self.id_input.setFocusPolicy(Qt.StrongFocus)
        self.id_input.setPlaceholderText(COPY["t.login.placeholder.id"])
        self.card.add(self.id_input)
        self.card.add(make_label(COPY["t.login.field.password"], "Heading"))
        self.password_input = QLineEdit()
        self.password_input.setObjectName("TeacherPasswordInput")
        self.password_input.setFocusPolicy(Qt.StrongFocus)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText(COPY["t.login.placeholder.password"])
        self.card.add(self.password_input)
        self.error_label = make_error("")
        self.card.add(self.error_label)
        self.login_button = make_primary_button(COPY["t.login.action.submit"])
        self.login_button.setObjectName("TeacherLoginButton")
        self.login_button.clicked.connect(self._on_login)
        self.card.add(self.login_button)
        self.card.add(divider())
        self.card.add(make_hint(COPY["t.login.demo.note"]))
        self.demo_button = make_ghost_button(COPY["t.login.demo.action"])
        self.demo_button.setObjectName("TeacherDemoButton")
        self.demo_button.clicked.connect(self.demo_requested.emit)
        self.card.add(self.demo_button)
        self.card.add(make_hint(COPY["t.login.footer"]))
        self.card.add(hotline_label(COPY.hotline_line()))

        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self.card, 3)
        holder.addStretch(1)
        outer.addLayout(holder)
        outer.addStretch(2)

    def _on_login(self) -> None:
        self.login_requested.emit(self.id_input.text().strip(),
                                 self.password_input.text())

    def teacher_no(self) -> str:
        return normalize_teacher_no(self.id_input.text())

    def set_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def set_busy(self, busy: bool) -> None:
        self.login_button.setEnabled(not busy)


# --------------------------------------------------------------------------- 主窗口


class TeacherMainWindow(QMainWindow):
    """主窗口：登录页 → 预约时间表。"""

    def __init__(self, server: str = "http://127.0.0.1:8080",
                 *, client: Optional[ApiClient] = None,
                 pool: Optional[QThreadPool] = None) -> None:
        super().__init__()
        self.setObjectName("TeacherMainWindow")
        self.setWindowTitle(COPY["t.window.title"])
        self.resize(1180, 820)

        self.client = client or build_client(server)
        self.runner = TaskRunner(pool or QThreadPool.globalInstance())
        #: 离线演示态（没有 token，只连本机预约库）
        self.offline_demo = False
        self.teacher_no = ""

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("TeacherRootStack")
        self.login_view = LoginView()
        self.tabs = QTabWidget()
        self.tabs.setObjectName("TeacherMainTabs")
        self.schedule_page = ScheduleTab(client=self.client, runner=self.runner)
        self.tabs.addTab(self.schedule_page, COPY["t.tab.schedule"])
        self.stack.addWidget(self.login_view)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        self.status_label = make_hint("")
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().addWidget(hotline_label(COPY.hotline_line()))

        self._wire()
        enforce_focus_policy(self)
        self.show_login()

    # ---------------------------------------------------------------- 装配

    def _wire(self) -> None:
        self.login_view.login_requested.connect(self._on_login_clicked)
        self.login_view.demo_requested.connect(self._enter_demo)
        self.login_view.id_input.textChanged.connect(
            lambda: self.login_view.set_error(""))
        self.schedule_page.block_changed.connect(self._on_block_changed)

    # ---------------------------------------------------------------- 登录

    def show_login(self) -> None:
        self.stack.setCurrentWidget(self.login_view)
        self.login_view.id_input.setFocus(Qt.OtherFocusReason)

    def show_main(self) -> None:
        self.stack.setCurrentWidget(self.tabs)
        self.schedule_page.start_sync()

    def _on_login_clicked(self, teacher_no: str, password: str) -> None:
        if not teacher_no:
            self.login_view.set_error(COPY["t.login.error.empty"])
            return
        self.login_view.set_error("")
        self.login_view.set_busy(True)
        worker = self.runner.submit(self._login_worker, teacher_no, password,
                                    done=self._on_login_ok,
                                    failed=self._on_login_failed)

    def _login_worker(self, teacher_no: str, password: str) -> dict:
        # ⚠️ 本函数在 QThreadPool 线程里执行（不是主线程）
        return self.client.login_teacher(teacher_no, password)

    def _on_login_ok(self, data: Any) -> None:
        self.login_view.set_busy(False)
        profile = (data or {}).get("profile") or {}
        self.teacher_no = str(profile.get("id") or self.login_view.teacher_no())
        self.offline_demo = False
        self.status_label.setText(
            f"{profile.get('name', '')} · {profile.get('class_name') or ''}".strip(" ·"))
        self.show_main()

    def _on_login_failed(self, error: Any) -> None:
        self.login_view.set_busy(False)
        self.login_view.set_error(self.error_text(error))

    def _enter_demo(self) -> None:
        """离线演示：不连服务端，只看本机预约库（自检也走这条路径）。"""
        self.offline_demo = True
        self.login_view.set_error("")
        self.status_label.setText(COPY["t.login.demo.action"])
        self.show_main()

    def _on_block_changed(self, slot: str, blocked: bool) -> None:
        """教师改了不可预约设定：状态栏给出回执（学生端会自动看到红框）。"""
        self.status_label.setText(COPY["t.schedule.action.blocked"] if blocked
                                  else COPY["t.schedule.action.unblocked"])

    # ---------------------------------------------------------------- 文案

    def error_text(self, error: Any) -> str:
        """异常 → 文案表里的用户可读句子（**不暴露技术措辞**）。"""
        from desktop_common.api import ApiError

        if isinstance(error, ApiError):
            if error.is_network:
                return COPY["t.login.error.network"]
            if str(error.code) in ("1001", "401"):
                return COPY["t.login.error.401"]
        return COPY["c.error.unknown"]

    # ---------------------------------------------------------------- 收尾

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        """关闭前收尾：停同步定时器 + 等后台 worker。"""
        self.schedule_page.stop_sync()
        return self.runner.wait(timeout_ms)


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m teacher_desktop.app.main",
        description="MindCare 教师端（PySide6）",
    )
    parser.add_argument("--server", default="http://127.0.0.1:8080",
                        help="服务端地址（默认 http://127.0.0.1:8080）")
    parser.add_argument("--teacher-no", default="",
                        help="可选：预填工号（纯数字会自动补 tch_ 前缀）")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("MindCare")
    theme.install_fonts(app)
    theme.apply_theme(app)
    window = TeacherMainWindow(args.server)
    if args.teacher_no:
        window.login_view.id_input.setText(normalize_teacher_no(args.teacher_no))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
