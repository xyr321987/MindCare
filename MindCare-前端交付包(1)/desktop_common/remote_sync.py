"""预约时间表「远端实时同步」：用 `ApiClient` 轮询共享后端，取代本地 JSONL 文件签名轮询。

背景
----
契约里不可预约段（`GET /appointments/blocks`，学生+教师共读）与预约清单
（`GET /appointments`，教师）都落在共享后端的 SQLite 里。本模块把"从各自本地文件
轮流 `stat` 看变没变"（`sync.StoreWatcher`）换成"定时打接口、把远端事实灌进界面"。

约束（沿用 `docs/UI约定.md` §3）：**网络请求必须跑在 worker 线程**。本模块的 `poll()`
只负责把一次「拉取 blocks（教师再拉 appointments）」投递到 `QThreadPool`，
`done` 回来后**在主线程**合并快照并 `changed.emit()`，界面据此重刷格子。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from PySide6.QtCore import QObject, QTimer, Signal

try:  # 包内导入
    from . import schedule as schedule_mod
except ImportError:  # pragma: no cover - 直接以脚本路径导入时的兜底
    import schedule as schedule_mod  # type: ignore

__all__ = [
    "DEFAULT_INTERVAL_MS", "RemoteSchedule",
]

DEFAULT_INTERVAL_MS = 2000


def _slot_of(record: dict) -> str:
    """一条预约记录 → 格子 ID。服务端已带 `slot`；缺省时用年月日+period 回推。"""
    slot = str(record.get("slot") or "").strip()
    if slot:
        return slot
    try:
        return schedule_mod.slot_id(
            int(record.get("year")), int(record.get("month")),
            int(record.get("day")), int(record.get("period")))
    except (TypeError, ValueError):
        return ""


class RemoteSchedule(QObject):
    """预约表的远端快照 + 定时轮询。

    :param client: `ApiClient`（`list_blocks()` / `list_appointments()`）
    :param runner: `TaskRunner`（`submit(fn, *args)` → 带 `signals.done/failed` 的 worker）
    :param fetch_appointments: 是否同时拉预约清单（教师 True；学生只能读 blocks，False）
    :param interval_ms: 轮询间隔
    """

    #: 远端事实发生变化（或首次拉到）后发出；界面据此重刷格子
    changed = Signal()

    def __init__(self, client, runner, *, fetch_appointments: bool = True,
                 fetch_mine: bool = False,
                 interval_ms: int = DEFAULT_INTERVAL_MS,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._client = client
        self._runner = runner
        self._fetch_appointments = bool(fetch_appointments)
        self._fetch_mine = bool(fetch_mine)

        #: 当前不可预约格子集合（`{"YYYY-MM-DD#P", ...}`）
        self._blocked: Set[str] = set()
        #: `slot -> [预约记录]`（教师端看"谁约了"；同一格可能多条约未防重服务端）
        self._appointments: Dict[str, List[dict]] = {}
        #: 本人已预约的格子（学生端本地暂存，服务端不给学生读预约清单）
        self._mine: Set[str] = set()

        self._timer = QTimer(self)
        self._timer.setInterval(max(500, int(interval_ms)))
        self._timer.timeout.connect(self.poll)
        self._in_flight = False
        #: 已经收到过多少次"数据变了"（自检断言真的同步过）
        self.change_count = 0

    # -- 配置 ---------------------------------------------------------------

    @property
    def interval_ms(self) -> int:
        return int(self._timer.interval())

    def set_interval(self, interval_ms: int) -> None:
        self._timer.setInterval(max(100, int(interval_ms)))

    def is_active(self) -> bool:
        return bool(self._timer.isActive())

    # -- 运行 ---------------------------------------------------------------

    def start(self) -> None:
        """开始轮询，并**立即拉一次**（首屏就有数据，不必等一个周期）。"""
        self._timer.start()
        self.poll()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> None:
        """投递一次后台拉取；上一个还没回来时不重复投递。"""
        if self._in_flight:
            return
        self._in_flight = True
        worker = self._runner.submit(
            self._fetch, self._client, self._fetch_appointments, self._fetch_mine,
            done=self._on_fetched, failed=self._on_failed)

    def force_refresh(self) -> None:
        """手动触发一次拉取（自检/排障用；接口与 `StoreWatcher.force_refresh` 对齐）。"""
        self.poll()

    @staticmethod
    def _fetch(client, fetch_appointments: bool, fetch_mine: bool):
        """在 worker 线程里跑：拉 blocks（教师再拉全部预约；学生拉自己的预约）。"""
        blocks = client.list_blocks()
        appointments = client.list_appointments(None) if fetch_appointments else None
        mine = client.list_my_appointments() if fetch_mine else None
        return blocks, appointments, mine

    def _on_fetched(self, result) -> None:
        self._in_flight = False
        blocks, appointments, mine = result
        self._apply(blocks, appointments, mine)

    def _on_failed(self, error) -> None:
        # 网络失败 / 未登录：幂等地保留旧快照，不弹错 —— 等下一轮重试即可。
        self._in_flight = False

    def _apply(self, blocks: dict, appointments: Optional[dict], mine: Optional[dict]) -> None:
        slots = set(str(s) for s in (blocks or {}).get("slots") or [])
        changed = slots != self._blocked
        self._blocked = slots

        by_slot: Dict[str, List[dict]] = {}
        items = (appointments or {}).get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            slot = _slot_of(item)
            if not slot:
                continue
            by_slot.setdefault(slot, []).append(item)
        if by_slot != self._appointments:
            changed = True
        self._appointments = by_slot

        # 本人预约（学生端）：从 `/appointments/mine` 推导，教师代订也会同步进来
        mine_slots: Set[str] = set()
        for item in (mine or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            slot = _slot_of(item)
            if slot:
                mine_slots.add(slot)
        if mine_slots != self._mine:
            changed = True
        self._mine = mine_slots

        if changed:
            self.change_count += 1
            self.changed.emit()

    # -- 读取（界面用）-----------------------------------------------------

    def blocked_slots(self) -> Set[str]:
        return set(self._blocked)

    def appointment_slots(self) -> Dict[str, dict]:
        """`slot -> 该格最后一条预约`（同一格多条约时取最后，与 blocks 同款口径）。"""
        out: Dict[str, dict] = {}
        for slot, records in self._appointments.items():
            if records:
                out[slot] = records[-1]
        return out

    def appointments_at(self, year, month, day, period) -> List[dict]:
        """某个格子上的全部预约记录（教师端看"谁约了"用）。"""
        try:
            target = schedule_mod.slot_id(int(year), int(month), int(day), int(period))
        except (TypeError, ValueError):
            return []
        return list(self._appointments.get(target, []))

    # -- 本人预约（学生端）-------------------------------------------------

    def add_mine(self, slot: str) -> None:
        self._mine.add(str(slot))

    def clear_mine(self) -> None:
        self._mine.clear()

    def mine_slots(self) -> Set[str]:
        return set(self._mine)