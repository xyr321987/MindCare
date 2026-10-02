# -*- coding: utf-8 -*-
"""后台请求执行器：**所有网络请求都走 QThreadPool，主线程只更新界面**。

沿用学生端交付包（app/worker.py）同一条纪律：主线程发起的传输调用次数必须为 0，
selfcheck 会断言。用法::

    from app.worker import run_async
    run_async(client.triage_list, on_done=self._render, on_failed=self._on_error)
    run_async(lambda: adapters.warning.list_all(), on_done=self._render)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

__all__ = ["WorkerSignals", "ApiWorker", "run_async", "TaskRunner"]


class WorkerSignals(QObject):
    done = Signal(object)       # 成功：业务数据
    failed = Signal(object)     # 失败：异常对象
    finished = Signal()         # 无论成败


class ApiWorker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)
        self.ok = False
        self.error: Optional[BaseException] = None
        self.result: Any = None

    @Slot()
    def run(self) -> None:
        try:
            self.result = self._fn(*self._args, **self._kwargs)
            self.ok = True
        except Exception as exc:  # noqa: BLE001 - 兜底：异常必须送到 failed，不得静默
            self.error = exc
            exc.__dict__.setdefault("traceback_text", traceback.format_exc())
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(self.result)
        finally:
            self.signals.finished.emit()


class TaskRunner:
    """线程池门面：页面只用它，不直接碰 QThreadPool。"""

    def __init__(self) -> None:
        self.pool = QThreadPool.globalInstance()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> ApiWorker:
        worker = ApiWorker(fn, *args, **kwargs)
        self.pool.start(worker)
        return worker


def run_async(fn: Callable[..., Any], *args: Any,
              on_done: Optional[Callable[[Any], None]] = None,
              on_failed: Optional[Callable[[Exception], None]] = None,
              **kwargs: Any) -> ApiWorker:
    """便捷提交：成功/失败回调都在主线程执行（Qt 队列连接自动切线程）。"""
    worker = ApiWorker(fn, *args, **kwargs)
    if on_done is not None:
        worker.signals.done.connect(on_done)
    if on_failed is not None:
        worker.signals.failed.connect(on_failed)
    QThreadPool.globalInstance().start(worker)
    return worker
