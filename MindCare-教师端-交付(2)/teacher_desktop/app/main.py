# -*- coding: utf-8 -*-
"""教师端入口。

启动方式（在 teacher-desktop/ 目录下）：

    python -m teacher_desktop.app.main --server http://127.0.0.1:8080

也可直接双击同目录 start-teacher.cmd。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QStackedWidget

from desktop_common import theme

from ..core.triage_client import TriageClient
from ..ui.common.async_mixin import PageContext
from ..ui.login_page import LoginPage
from ..ui.main_window import MainWindow
from ..ui.teacher_qss import build_teacher_qss
from .settings import make_adapters, parse_args


class AppRoot(QStackedWidget):
    """登录页 / 主工作台两个屏幕的切换容器。"""

    def __init__(self, settings) -> None:
        super().__init__()
        self.settings = settings
        self.triage = TriageClient(server=settings.server)
        self.ctx = PageContext(
            self.triage, make_adapters(settings), settings,
            on_auth_fail=self._back_to_login)
        self._show_login()

    # ------------------------------------------------------------------ 屏幕切换
    def _show_login(self) -> None:
        login = LoginPage(self.triage)
        login.login_ok.connect(self._show_main)
        self._add_screen(login, small=True)

    def _show_main(self, profile: dict) -> None:
        main = MainWindow(self.ctx, profile)
        main.logout_requested.connect(lambda: self._logout())
        self._add_screen(main, small=False)

    def _logout(self) -> None:
        self.triage.logout()
        self._show_login()

    def _back_to_login(self, message: str = "") -> None:
        # 会话失效：清登录态并回登录页（消息由登录页展示）
        self.triage.logout()
        login = LoginPage(self.triage)
        if message:
            login.error_label.setText(message)
        login.login_ok.connect(self._show_main)
        self._add_screen(login, small=True)

    def _add_screen(self, widget, *, small: bool) -> None:
        index = self.addWidget(widget)
        self.setCurrentIndex(index)
        if small:
            self.setWindowTitle("MindCare · 教师端 · 登录")
            self.setFixedSize(480, 560)
        else:
            self.setWindowTitle("MindCare · 教师端")
            self.setMinimumSize(1120, 660)
            self.setMaximumSize(16777215, 16777215)
            self.resize(1280, 760)


def main() -> int:
    settings = parse_args()
    app = QApplication(sys.argv)
    theme.install_fonts(app)
    # 基础 QSS（两个桌面端共用，不改）+ 教师端扩展 QSS（单点维护）
    app.setStyleSheet(theme.build_qss() + build_teacher_qss())

    root = AppRoot(settings)
    root.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
