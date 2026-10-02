"""后台请求执行器：**所有网络请求都走 `QThreadPool`，主线程只更新界面**。

依据 `docs/UI约定.md` §3「关键：不要阻塞 UI 线程。所有请求走 `QThread`/`QThreadPool`
或 `QTimer` + worker；主线程只更新界面」+ §7「禁止把网络请求放在主线程」。

用法::

    worker = ApiWorker(client.my_profile, "2026-10-01")
    worker.signals.done.connect(self._render)      # 主线程槽
    worker.signals.failed.connect(self._on_error)  # 主线程槽
    QThreadPool.globalInstance().start(worker)

自检断言：所有 worker 都运行在非主线程（`NotMainThreadRunner` 会记录实际线程名），
且 `ApiClient` 的传输层在主线程上被调用的次数为 0。
"""
from __future__ import annotations

import threading
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from desktop_common.api import ApiError

__all__ = ["WorkerSignals", "ApiWorker", "TaskRunner", "CallStats", "STATS"]


class WorkerSignals(QObject):
    """worker 信号（必须在主线程被 connect，Qt 默认队列连接会切回主线程执行槽）。"""

    done = Signal(object)          # 成功：业务数据
    failed = Signal(object)        # 失败：ApiError 或其它异常
    finished = Signal()            # 无论成败


class _GlobalStats:
    """全局计数器：自检用它证明"主线程没有发过请求"。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.transport_calls_main_thread = 0
        self.transport_calls_worker_thread = 0
        self.worker_runs = 0
        self.worker_thread_names: set[str] = set()

    def note_transport(self) -> None:
        # 判据就是"当前 Python 线程是不是主线程"：`QThreadPool` 的 worker 跑在
        # 其它 OS 线程上，因此主线程被记录到 main 计数就说明有人违反了 UI约定 §3。
        main = threading.current_thread() is threading.main_thread()
        with self.lock:
            if main:
                self.transport_calls_main_thread += 1
            else:
                self.transport_calls_worker_thread += 1

    def note_worker(self) -> None:
        with self.lock:
            self.worker_runs += 1
            self.worker_thread_names.add(threading.current_thread().name)

    def reset(self) -> None:
        with self.lock:
            self.transport_calls_main_thread = 0
            self.transport_calls_worker_thread = 0
            self.worker_runs = 0
            self.worker_thread_names = set()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "transport_calls_main_thread": self.transport_calls_main_thread,
                "transport_calls_worker_thread": self.transport_calls_worker_thread,
                "worker_runs": self.worker_runs,
                "worker_thread_names": sorted(self.worker_thread_names),
            }


#: 全局统计（自检断言用）
STATS = _GlobalStats()
CallStats = _GlobalStats  # 别名，便于阅读


class ApiWorker(QRunnable):
    """在 `QThreadPool` 里跑一次可调用对象（通常是 `ApiClient` 的方法）。"""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)
        #: 最近一次执行状态（自检可读）
        self.ok = False
        self.error: Optional[BaseException] = None
        self.result: Any = None

    @Slot()
    def run(self) -> None:  # pragma: no cover - 需要事件循环，由自检驱动
        STATS.note_worker()
        try:
            self.result = self._fn(*self._args, **self._kwargs)
            self.ok = True
        except ApiError as exc:            # 契约错误码（含网络层伪码）
            self.error = exc
            self.signals.failed.emit(exc)
        except Exception as exc:           # noqa: BLE001 - 兜底：不得静默吞掉
            self.error = exc
            exc.__dict__.setdefault("traceback_text", traceback.format_exc())
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(self.result)
        finally:
            self.signals.finished.emit()


class TaskRunner:
    """把 worker 提交到线程池的小门面（页面只用它，不直接碰 QThreadPool）。"""

    def __init__(self, pool: Optional[QThreadPool] = None) -> None:
        self.pool = pool or QThreadPool.globalInstance()
        self._live: list[ApiWorker] = []

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> ApiWorker:
        done = kwargs.pop("done", None)
        failed = kwargs.pop("failed", None)
        worker = ApiWorker(fn, *args, **kwargs)
        # ⚠️ 必须在 `pool.start` **之前**连好 done/failed 信号：worker 在另一个线程里
        # 跑，若先 start 再 connect，worker 可能抢在 connect 之前就把结果信号发出来
        # （stub/本地后端极快时必现），信号没人接 = 结果静默丢失（实测踩过 `1001`
        # 跳登录偶发失效）。
        if done is not None:
            worker.signals.done.connect(done)
        if failed is not None:
            worker.signals.failed.connect(failed)
        self._live = [w for w in self._live if not w.ok and w.error is None]
        self._live.append(worker)
        self.pool.start(worker)
        return worker

    def wait(self, timeout_ms: int = 15000) -> bool:
        """仅自检使用：等所有已提交 worker 结束。"""
        return self.pool.waitForDone(timeout_ms)

    @property
    def busy(self) -> bool:
        return self.pool.activeThreadCount() > 0
