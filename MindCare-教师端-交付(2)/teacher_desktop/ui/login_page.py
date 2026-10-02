# -*- coding: utf-8 -*-
"""登录页（1:1 迁移 教师端3.html 的登录窗：工号 + 口令）。

- 登录请求走 worker 线程（主线程零网络）；
- 业务错误（工号/口令不对）留在本页说明；网络错误也如实说明。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from desktop_common.api import ApiError
from desktop_common.widgets import (
    Card, hspacer, make_button, make_error, make_label, make_primary_button,
    vspacer,
)

from ..app.worker import run_async
from ..core.triage_client import TriageClient


class LoginPage(QWidget):
    """登录窗。成功后发 login_ok(profile_dict)，由主入口切换主窗。"""

    login_ok = Signal(dict)

    def __init__(self, triage: TriageClient, parent=None) -> None:
        super().__init__(parent)
        self.triage = triage
        self.setObjectName("PageRoot")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(12)
        outer.addWidget(vspacer())

        holder = QHBoxLayout()
        holder.addStretch(1)
        self.card = Card(padding=28, spacing=16)
        self.card.setMaximumWidth(430)
        holder.addWidget(self.card, 2)
        holder.addStretch(1)
        outer.addLayout(holder)
        outer.addWidget(vspacer())

        # ---- 标题区
        title = make_label("MindCare 教师端", "Title", word_wrap=False)
        title.setAlignment(Qt.AlignCenter)
        self.card.add(title)
        sub = make_label("学生心理关怀工作台", "Hint", word_wrap=False)
        sub.setAlignment(Qt.AlignCenter)
        self.card.add(sub)

        # ---- 工号
        self.card.add(make_label("工号", "Hint"))
        self.work_edit = QLineEdit()
        self.work_edit.setPlaceholderText("如 T001")
        self.card.add(self.work_edit)

        # ---- 口令
        self.card.add(make_label("口令", "Hint"))
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setPlaceholderText("教师工号口令")
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.card.add(self.pwd_edit)

        # ---- 按钮 + 错误
        self.login_btn = make_primary_button("登录")
        self.login_btn.clicked.connect(self._do_login)
        self.card.add(self.login_btn)
        self.error_label = make_error("")
        self.card.add(self.error_label)

        hint = make_label("请使用学校分配的教师工号登录", "Hint", word_wrap=False)
        hint.setAlignment(Qt.AlignCenter)
        self.card.add(hint)

        self.work_edit.returnPressed.connect(self._do_login)
        self.pwd_edit.returnPressed.connect(self._do_login)

    # ------------------------------------------------------------------ 登录动作
    def _do_login(self) -> None:
        work_id = self.work_edit.text().strip()
        pwd = self.pwd_edit.text()
        if not work_id or not pwd:
            self._set_error("请填写工号和口令")
            return
        self._set_error("")
        self._set_form_enabled(False)
        self.login_btn.setText("登录中…")

        self._login_worker = run_async(
            self.triage.login, work_id, pwd,
            on_done=self._on_login_ok, on_failed=self._on_login_fail)

    def _on_login_ok(self, _data: dict) -> None:
        profile = self.triage.profile or {"name": "老师"}
        self.login_btn.setText("登录")
        self.login_ok.emit(profile)

    def _on_login_fail(self, exc: Exception) -> None:
        self.login_btn.setText("登录")
        self._set_form_enabled(True)
        if isinstance(exc, ApiError) and str(exc.code) in ("network", "timeout"):
            self._set_error("连不上后端服务，请确认服务端已启动")
        else:
            self._set_error(str(getattr(exc, "message", exc)) or "登录没成功，请再试一次")

    def _set_error(self, text: str) -> None:
        """显示/隐藏错误提示。

        `make_error("")` 初始是**隐藏**的（空文案即不可见），所以这里除了改文案，
        还必须显式切可见性 —— 否则登录失败时错误红字永远不出现。
        """
        self.error_label.setText(text)
        self.error_label.setVisible(bool(text))

    def _set_form_enabled(self, enabled: bool) -> None:
        self.work_edit.setEnabled(enabled)
        self.pwd_edit.setEnabled(enabled)
        self.login_btn.setEnabled(enabled)
