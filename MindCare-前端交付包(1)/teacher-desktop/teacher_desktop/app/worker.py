"""后台请求执行器（与学生端 `student_desktop.app.worker` 同一套纪律）。

`docs/UI约定.md` §3：所有请求走 `QThreadPool`，**主线程只更新界面**。
本模块是教师端的独立副本（不 import 学生端包，避免双端互相依赖）。
"""
from __future__ import annotations

import threading
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from desktop_common.api import ApiError

__all__ = ["WorkerSignals", "ApiWorker", "TaskRunner", "STATS"]


class WorkerSignals(QObject):
    """worker 信号（在主线程 connect，Qt 队列连接会把槽切回主线程执行）。"""

    done = Signal(object)
    failed = Signal(object)
    finished = Signal()


class _Stats:
    """计数器：自检用它证明"主线程没有发过请求"。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.transport_calls_main_thread = 0
        self.transport_calls_worker_thread = 0
        self.worker_runs = 0

    def note_transport(self) -> None:
        main = threading.current_thread() is threading.main_thread()
        with self.lock:
            if main:
                self.transport_calls_main_thread += 1
            else:
                self.transport_calls_worker_thread += 1

    def note_worker(self) -> None:
        with self.lock:
            self.worker_runs += 1

    def reset(self) -> None:
        with self.lock:
            self.transport_calls_main_thread = 0
            self.transport_calls_worker_thread = 0
            self.worker_runs = 0


#: 教师端全局统计（自检断言用）
STATS = _Stats()


class ApiWorker(QRunnable):
    """在 `QThreadPool` 里跑一次可调用对象（通常是 `ApiClient` 的方法）。"""

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
    def run(self) -> None:  # pragma: no cover - 需要事件循环，由自检驱动
        STATS.note_worker()
        try:
            self.result = self._fn(*self._args, **self._kwargs)
            self.ok = True
        except ApiError as exc:
            self.error = exc
            self.signals.failed.emit(exc)
        except Exception as exc:            # noqa: BLE001 - 兜底：不得静默吞掉
            self.error = exc
            exc.__dict__.setdefault("traceback_text", traceback.format_exc())
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(self.result)
        finally:
            self.signals.finished.emit()


class TaskRunner:
    """把 worker 提交到线程池的小门面。"""

    def __init__(self, pool: Optional[QThreadPool] = None) -> None:
        self.pool = pool or QThreadPool.globalInstance()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> ApiWorker:
        done = kwargs.pop("done", None)
        failed = kwargs.pop("failed", None)
        worker = ApiWorker(fn, *args, **kwargs)
        # ⚠️ 必须在 `pool.start` **之前**连好 done/failed 信号（见学生端 worker.py 同款注释）。
        if done is not None:
            worker.signals.done.connect(done)
        if failed is not None:
            worker.signals.failed.connect(failed)
        self.pool.start(worker)
        return worker

    def wait(self, timeout_ms: int = 15000) -> bool:
        """仅自检使用：等所有已提交 worker 结束。"""
        return self.pool.waitForDone(timeout_ms)
