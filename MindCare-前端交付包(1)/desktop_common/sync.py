"""多端**实时同步**：本地数据文件变更 → 界面自动刷新。

为什么需要
----------
教师把某一格设成「不可预约」后，学生端必须**立刻**看到红框 —— 不能等学生重启应用、
也不能靠他点一下刷新。服务端版本走接口轮询（见契约文档 §6.3），联调前两端都读
本机同一份 JSON Lines，因此这里用**文件签名轮询**实现"实时"。

为什么是轮询而不是 `QFileSystemWatcher`
---------------------------------------
`QFileSystemWatcher` 在部分网络盘 / 同步盘 / 容器挂载目录上不投递事件，
而且**文件被 truncate 重写**时会丢信号；轮询 `(mtime_ns, size)` 的行为在所有
平台上一致，且成本可以忽略（每 1.5s 两次 `stat`）。
⚠️ 本模块**只发"变了"这个信号**，不搬运数据 —— 读库仍是各端自己的存储模块，
避免出现第二份事实源。

不在主线程阻塞
--------------
`stat` 是微秒级系统调用，直接在 `QTimer.timeout` 里做即可，不需要额外线程
（UI约定 §3 的"主线程不发请求"指的是 **HTTP**，不是本地 `stat`）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

__all__ = [
    "DEFAULT_INTERVAL_MS", "signature", "StoreWatcher",
]

#: 默认轮询间隔（1.5s：教师点完 → 学生端看到，体感上是"立刻"）
DEFAULT_INTERVAL_MS = 1500


def signature(paths: Sequence[Path]) -> Tuple[Tuple[str, int, int], ...]:
    """一组文件的当前签名：`[(path, mtime_ns, size), ...]`。

    文件不存在记为 `(-1, -1)` —— **文件从有到无**也是一种变更（例如清库），
    同样要触发刷新。任何 `OSError` 都按"不存在"处理，**不抛异常**。
    """
    out: List[Tuple[str, int, int]] = []
    for raw in paths:
        path = Path(raw)
        try:
            info = os.stat(path)
            out.append((str(path), int(info.st_mtime_ns), int(info.st_size)))
        except OSError:
            out.append((str(path), -1, -1))
    return tuple(out)


class StoreWatcher(QObject):
    """监视若干本地数据文件，内容一变就发 `changed`（**去重**：签名不变不发）。

    用法::

        watcher = StoreWatcher([appointments.appointment_file(),
                                schedule_store.block_file()])
        watcher.changed.connect(self._refresh_grid)
        watcher.start()

    :param paths: 被监视的文件（**每次都重算**：换目录/换用户后也能跟上）
    :param interval_ms: 轮询间隔
    """

    #: 任意被监视文件的内容发生变化（去重后）
    changed = Signal()

    def __init__(self, paths: Optional[Iterable[Path]] = None,
                 *, interval_ms: int = DEFAULT_INTERVAL_MS,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._paths: List[Path] = [Path(p) for p in (paths or [])]
        self._timer = QTimer(self)
        self._timer.setInterval(max(200, int(interval_ms)))
        self._timer.timeout.connect(self.poll)
        #: 上一次见到的签名（`None` = 还没取过基线）
        self._last: Optional[Tuple[Tuple[str, int, int], ...]] = None
        #: 已经发出过的 `changed` 次数（自检用它断言"真的同步过"）
        self.change_count = 0
        #: 最近一次签名（诊断用；自检可断言两端看到的是同一份数据）
        self.last_signature: Tuple[Tuple[str, int, int], ...] = ()

    # -- 配置 ---------------------------------------------------------------

    @property
    def paths(self) -> List[Path]:
        return list(self._paths)

    def set_paths(self, paths: Iterable[Path]) -> None:
        """替换被监视的文件列表（下一轮轮询生效）。"""
        self._paths = [Path(p) for p in paths]
        self._last = None               # 换目标后重新取基线，避免误报一次

    @property
    def interval_ms(self) -> int:
        return int(self._timer.interval())

    def is_active(self) -> bool:
        return bool(self._timer.isActive())

    def set_interval(self, interval_ms: int) -> None:
        """调整轮询间隔（自检把它调小，好让"实时同步"在几秒内被测到）。"""
        self._timer.setInterval(max(50, int(interval_ms)))

    # -- 运行 ---------------------------------------------------------------

    def start(self) -> None:
        """开始轮询。**先取一次基线**（不触发 `changed`），避免启动即误报。"""
        self._last = signature(self._paths)
        self.last_signature = self._last
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> bool:
        """取一次签名，与上次不同就发 `changed`。

        :return: 是否发生了变化（**不需要**调用方再判断）
        """
        current = signature(self._paths)
        self.last_signature = current
        if self._last is not None and current == self._last:
            return False
        self._last = current
        self.change_count += 1
        self.changed.emit()
        return True

    def force_refresh(self) -> None:
        """无条件发一次 `changed`（手动刷新按钮用）。"""
        self.change_count += 1
        self.changed.emit()
