# -*- coding: utf-8 -*-
"""页面基类与共享上下文。

PageContext：所有页面共用的入口对象（既有接口客户端 + 新功能适配器 + 配置）。
PageBase：
- 统一 `on_show()`（切换到本页时由主窗调用，懒加载）；
- 统一 `call()` 把磁盘/网络调用丢到 QThreadPool，回调在主线程；
- 顶部 Toast 轻提示 + 可挂 Banner。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from desktop_common.widgets import Toast
from ...app.settings import Adapters, Settings
from ...app.worker import run_async
from ...core.triage_client import TriageClient


class PageContext:
    """页面运行上下文（主入口组装一次，所有页面共用）。"""

    def __init__(self, triage: TriageClient, adapters: Adapters,
                 settings: Settings, on_auth_fail=None) -> None:
        self.triage = triage
        self.adapters = adapters
        self.settings = settings
        #: 会话失效（1001）时主窗给的回调，参数为提示语
        self.on_auth_fail = on_auth_fail


class PageBase(QWidget):
    """五个功能页的共同基类。子类实现 refresh() 即可。"""

    PAGE_TITLE = ""

    def __init__(self, ctx: PageContext, parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("PageRoot")
        self._loaded_once = False
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(22, 18, 22, 18)
        self._root.setSpacing(12)
        self.toast = Toast(self)
        self.toast.setVisible(False)
        self._root.addWidget(self.toast)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.clear_message)
        #: 在途 worker 必须保活，否则 PySide 可能在 finished 信号投递前回收 QRunnable
        self._pending_workers = set()

    # ------------------------------------------------------ 异步快捷方式
    def call(self, fn: Callable[..., Any], *args,
             on_ok: Optional[Callable[[Any], None]] = None,
             on_fail: Optional[Callable[[Exception], None]] = None):
        """后台线程执行 fn；回调均在主线程。默认失败弹 Toast。"""
        worker = run_async(fn, *args, on_done=on_ok,
                           on_failed=on_fail or self._default_fail)
        self._pending_workers.add(worker)
        worker.signals.finished.connect(lambda: self._pending_workers.discard(worker))
        return worker

    @staticmethod
    def _default_fail(exc: Exception) -> None:
        # 子类若传了 on_fail 就不会走这里；兜底避免静默
        print(f"[教师端] 后台任务失败：{exc!r}")

    def show_toast(self, text: str, *, hold_ms: int = 2600) -> None:
        self.toast.show_message(text)
        self._toast_timer.start(hold_ms)

    # ------------------------------------------------------ 生命周期
    def on_show(self) -> None:
        """主窗切到本页时调用；默认首次进入自动刷新，之后不重复拉。"""
        if not self._loaded_once:
            self._loaded_once = True
            self.refresh()

    def refresh(self) -> None:  # 子类覆盖
        pass
