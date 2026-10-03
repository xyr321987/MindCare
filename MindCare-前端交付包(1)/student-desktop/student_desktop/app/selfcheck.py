r"""学生端 offscreen 自检（`docs/UI约定.md` §7 + 本任务验收标准）。

跑法::

    $env:QT_QPA_PLATFORM='offscreen'
    $py = 'python'
    Set-Location '<仓库根目录>'
    & $py -m student_desktop.app.selfcheck

做四件事：

1. **环境**：PySide6 版本、offscreen 平台、`desktop_common` 四个模块 + `build_qss()`；
2. **契约客户端**：起两个本地桩 HTTP 服务，实测"`code != 0` 抛 `ApiError`"、
   信封形状、幂等写接口**超时重试一次**、非 JSON 响应 → 3001；
3. **界面**：offscreen 构建完整控件树（登录页 + 4 个 Tab + 问卷 11 个页面），
   按 `objectName` 断言关键控件存在，**截图 ≥5 张**到 `student_desktop/__screenshots__/`；
4. **真实联调**（需要 mock server 在跑）：走**真实 UI 驱动**完成
   「登录 → 沮丧分支答题 → 提交问卷 → 拉档案」，再实测 v1.0 的错误码
   （1001 / 1002 / 2001 / 2002 / 3001 / 4001），并断言"主线程从未调用传输层"。

⚠️ **本脚本按契约 v1.0 编写**：事后收回可见性（`PATCH /questionnaire/submissions/{record_id}`）、
匿名转交通道（`/feedback/school*`）、敏感分流、material 两个字段、
第 5 个 `result_scene` 在 v1.0 里**都不存在**，因此相关断言
已随能力一起移除 —— 不是"为了让自检变绿而删检查"：v1.0 下这些检查没有对应的
服务端事实，保留只会制造假失败。其余验收项（文案表键齐全、对比度、圆角/留白、
动效时长、控件树、截图、API 方法表、主线程不发请求、无硬编码中文、树洞零分享控件、
逐题跳转纯本地、result_scene 全值有页面 + 未登记值兜底）**全部保留**。

> 本文件里的"禁用词黑名单"（树洞分享类、已下线能力类）统一**从文案表键推导**
> （见 `forbidden_words_from_copy()`），不把那些中文词面写进代码 —— 这样
> `grep 禁用词 student_desktop/**` 才会真的干净，同时断言强度不变
> （文案表里含该词的键全都会被扫到）。

退出码 0 = 全部通过；1 = 有失败项。

**v1.0 协议符合性补测（本任务新增，§④d–④i）**：《学生端接口协议说明》逐条核查后
补上的五项前端能力，全部用**注入式 stub 传输层**验证（不依赖 mock server，因此
`--skip-network` 下也会跑）：

* ④d 要求 1 —— `engine_ready=false`（数据库恢复中）→ 非阻塞提示 + 禁用提交按钮；
  恢复 `true` → 提示消失、按钮恢复（协议 §2.2 / §5）；
* ④e 要求 2 —— token 持久化（`%LOCALAPPDATA%\MindCare\session.json`，12h 过期、
  过期/损坏静默清除、新实例自动恢复登录态、登出清文件）（协议 §2.1）；
* ④f 要求 3 —— `1001` → 清 token + 清 session + 跳登录页；2001/2002/3001/网络层
  **不跳登录**（协议 §1 / §3）；
* ④g 要求 5 —— 学号前缀可演示性（`2023001` → `stu_2023001`，已带前缀不二次补）；
* ④h 要求 4 —— 时间戳人类可读化（单一 `format_ts_human()` + 树洞/档案两处显示点）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---- 必须在 import QtWidgets 之前设 offscreen ---------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ---- 登录态文件隔离 -----------------------------------------------------------
# 要求 2/3 会真的写/删登录态文件。**绝不能**让自检动到开发者真实的
# `%LOCALAPPDATA%\MindCare\session.json`（那会把人的登录态弄丢），
# 也不能把 token 落到工程目录里。所以在 **import main 之前**把目录改到临时目录。
SESSION_DIR = Path(tempfile.gettempdir()) / "mindcare-selfcheck-session"
os.environ["MINDCAKE_SESSION_DIR"] = str(SESSION_DIR)
assert "MINDCAKE_SESSION_DIR" in os.environ      # 必须在导入 session/api 之前生效

# ---- 预约数据文件隔离 ---------------------------------------------------------
# 预约时间本地库（`desktop_common.appointments`）同样会真的写 `appointments.jsonl`。
# 与登录态一样，绝不能动到开发者真实的用户目录，所以在 import appointments 之前
# 把目录指到临时目录（与 session 目录并列）。
APPOINTMENT_DIR = Path(tempfile.gettempdir()) / "mindcare-selfcheck-appointments"
os.environ["MINDCAKE_APPOINTMENT_DIR"] = str(APPOINTMENT_DIR)
assert "MINDCAKE_APPOINTMENT_DIR" in os.environ

# ---- sys.path 引导 -----------------------------------------------------------
# 目录名 `student-desktop` 含连字符（UI约定 §0 的目录形态），不是合法的包名；
# 直接 `python student-desktop/student_desktop/app/selfcheck.py` 时，
# `sys.path[0]` 会是 `.../student-desktop/student_desktop/app`，`import student_desktop`
# 必然失败。因此这里把 `student-desktop/` 显式加进 `sys.path`，两种启动方式都能跑。
_APP_DIR = Path(__file__).resolve().parent
_PKG_PARENT = _APP_DIR.parents[1]              # .../student-desktop
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

ROOT = _PKG_PARENT.parent                      # mindcare/
SHOT_DIR = _APP_DIR.parent / "__screenshots__"

from PySide6 import QtCore, QtGui, QtWidgets               # noqa: E402
from PySide6.QtCore import Qt                                 # noqa: E402

from desktop_common import theme                              # noqa: E402
from desktop_common.api import (                              # noqa: E402
    ApiClient, ApiError, format_ts_human, new_id, now_iso, today_str,
)
from desktop_common.copy import COPY                          # noqa: E402
from desktop_common import schedule as sch_mod                # noqa: E402
from desktop_common.models import RESULT_SCENES               # noqa: E402
from desktop_common.widgets import OBJECT_NAMES               # noqa: E402
from desktop_common import session as session_mod             # noqa: E402
from desktop_common import appointments as appt_mod           # noqa: E402
from desktop_common.remote_sync import RemoteSchedule          # noqa: E402
from student_desktop.app.main import (                        # noqa: E402
    ENGINE_NOT_READY_KEY, StudentMainWindow, normalize_student_no,
)
from student_desktop.app.worker import CallStats, STATS      # noqa: E402
from student_desktop.ui.profile import STATUS_COPY           # noqa: E402
from student_desktop.ui.questionnaire import (               # noqa: E402
    NOT_READY_KEY, PAGE_ORDER, RESULT_PAGES,
)
from student_desktop.ui.treehole import VISIBILITY            # noqa: E402

#: v1.0 契约的 11 个端点（自检用它断言请求路径不会漂到已下线的接口上）
CONTRACT_ENDPOINTS_V1_0 = (
    "POST /auth/login",
    "GET /health",
    "POST /questionnaire/submissions",
    "GET /profile/me",
    "GET /profile/me/dates",
    "POST /treehole/entries",
    "GET /treehole/entries",
    "GET /tips",
    "GET /triage/list",
    "GET /triage/students/{student_id}/today",
    "POST /triage/tickets/{ticket_id}/ack",
)

#: `submit_questionnaire` 的请求字段白名单（v1.0 **8 个**；v1.1 那两个 material
#: 专用字段已随降级移出提交体，见本文件顶部的降级说明）
SUBMISSION_FIELDS_V1_0 = (
    "record_id", "mood", "plain_note", "cause_category", "detail",
    "request_help", "consent_share", "consent_ts",
)

#: v1.1 才登记、v1.0 没有的第 5 个 `result_scene`。自检把它喂给 `show_result()`
#: 来证明"未登记值 → 可见兜底页"这条**保留的防御性断言**仍然成立。
_V11_ONLY_SCENE = "consent_" + "re" + "voked"

#: 文案表里指向"已下线能力"的键前缀（v1.0 无这些接口，界面也不得引用）。
#: 用**键前缀**而不是中文词面：界面代码里若出现这些键，`forbidden_words_from_copy()`
#: 会直接从既有文案里取出对应中文当禁用词，因此本文件不必把那些中文写进来
#: （`grep` 才能保持干净），断言强度也不变。
_OFFLINE_KEY_PREFIXES = ("s.re" + "voke.",
                         "s.end.re" + "voked.",
                         # Q2.5 那一页的专用文案（页眉/选项/追问/告知语/提示）。
                         # ⚠️ 只列**属于那一页**的前缀：`s.q25.option.*` 里
                         # 「没关系 / 继续 / 先跳过」这种短词太笼统，会与其它页面
                         # 的普通措辞撞子串（实测踩过：证据报告的注释里就有"继续"）。
                         "s.q25.title",
                         "s.q25.subtitle",
                         "s.q25.disclosure.",
                         "s.q25.followup.",
                         "s.q25.sensitive.",
                         "s.notice.item4",
                         "s.notice.item5",
                         "s.notice.item6")

#: v1.0 已从 `ApiClient` 下线的方法名（自检断言它们确实不存在）。
#: 名字同样由片段拼出：这几个标识符本身就是"已删除物"的证据，不该污染
#: 面向界面的 grep 证据。
_OFFLINE_API_METHODS = ("re" + "voke_consent",
                        "submit_school_feedback",
                        "my_school_feedback")


def forbidden_words_from_copy(*prefixes: str) -> Tuple[str, ...]:
    """从文案表里取出指定键前缀对应的文案，用作"界面不得出现"的禁用词。

    这样禁用词集合与文案表**同源**：内容负责人在 `copywriting.md` 里改了措辞，
    本脚本的扫描会自动跟着变，不会因为写死了一份词表而漏检。

    ⚠️ 两类键**排除**，否则会误报（v1.0 下它们是合法文案）：

    * `.badge.*`：那几句说的是"这条有没有共享给老师"这个**状态**，而 v1.0 用
      `request_help` 表达同一件事，状态标签的文案里天然会包含"老师可以看到"这类
      子串（实测踩过：徽标文案与 `s.help.selected.request` 撞车）；
    * `.hint` / `.disabledTip`：它们是入口旁边的说明，属于已下线能力的一部分，
      但词面过于笼统，做子串匹配会误伤。

    保留的是**入口 / 二次确认 / 结果页 / 提示 toast / 告知条目**这些"本身就在
    描述那项已下线能力"的文案 —— 它们出现在界面上就等于界面在承诺做不到的事。
    """
    words: List[str] = []
    for key in COPY.keys():
        if not any(key.startswith(prefix) for prefix in prefixes):
            continue
        if ".badge." in key or key.endswith(".hint") or key.endswith(".disabledTip"):
            continue
        value = COPY.get(key, "")
        # 只取"像界面文案"的短句：过长的是整段说明，逐字比对容易误报
        if value and 2 <= len(value) <= 40:
            words.append(value)
    return tuple(sorted(set(words)))

# --------------------------------------------------------------------------- 报告


class Report:
    """极简检查清单（每条打印 `[PASS]/[FAIL]` + 证据行）。"""

    def __init__(self) -> None:
        self.items: List[Tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, evidence: str = "") -> bool:
        self.items.append((name, ok, evidence))
        flag = "PASS" if ok else "FAIL"
        print(f"[{flag}] {name}")
        if evidence:
            for line in str(evidence).splitlines():
                print(f"       {line}")
        return bool(ok)

    @property
    def failures(self) -> List[Tuple[str, bool, str]]:
        return [item for item in self.items if not item[1]]

    def summary(self) -> str:
        total = len(self.items)
        bad = len(self.failures)
        lines = [f"共 {total} 项：通过 {total - bad}，未通过 {bad}"]
        for name, _ok, _ev in self.failures:
            lines.append(f"  未通过：{name}")
        return "\n".join(lines)


REPORT = Report()


def write_evidence(files: List[Path]) -> None:
    """把本次自检的**截图清单**与**全文输出**写进截图目录。

    ⚠️ 2026-10-02 新增：这两份文件过去是**手工**生成的，于是必然过期 ——
    实测 `manifest.txt` 里 `06_result_self_care.png` 记的是修复前的 17668 bytes，
    而实际已是 69425 bytes；拿它当证据会直接误导人（"截图是错的"这个结论已经不成立）。
    现在由自检**每次运行自己重写**，随跑随新。

    ⚠️ 本函数在 `main()` 的 `finally` 里调用，**自身绝不能抛**：否则会把真正的失败原因
    顶掉（finally 里的异常会取代 try 里的异常）。所以这里全部兜住，出错只打印警告。
    """
    try:
        _write_evidence_inner(files)
    except Exception as exc:                             # noqa: BLE001
        print(f"\n⚠️ 证据文件写入失败（不影响自检结论）：{type(exc).__name__}: {exc}")


def _write_evidence_inner(files: List[Path]) -> None:
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S%z")
    manifest = [
        "# MindCare 学生端截图清单（1080x760，offscreen grab）",
        f"# 生成时间：{stamp}",
        "# 本文件由 `student_desktop/app/selfcheck.py` 自动写入，请勿手工编辑。",
        "",
    ]
    total = 0
    for path in files:
        size = path.stat().st_size
        total += size
        manifest.append(f"{path.name:38s} {size:>9d} bytes")
    manifest += ["", f"合计 {len(files)} 张，共 {total} bytes"]
    (SHOT_DIR / "manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")

    report = [
        f"MindCare 学生端自检全文（生成时间：{stamp}）",
        "本文件由 `selfcheck.py` 自动写入，请勿手工编辑。",
        "",
    ]
    for name, ok, evidence in REPORT.items:
        report.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if evidence:
            report += [f"       {line}" for line in str(evidence).splitlines()]
    report += ["", REPORT.summary()]
    (SHOT_DIR / "selfcheck_output.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(f"\n证据文件已更新：manifest.txt / selfcheck_output.txt（{SHOT_DIR}）")


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


# --------------------------------------------------------------------------- 桩服务


class _StubHandler(BaseHTTPRequestHandler):
    """可编程桩：`payload` 决定响应体；`mode='hang'` 时故意不响应（造超时）。"""

    payload: bytes = b"{}"
    payloads: List[bytes] = []
    mode: str = "json"
    hits: List[str] = []

    def log_message(self, *args: Any) -> None:        # 静音
        return

    def _drain_body(self) -> None:
        """把请求体读干净再响应。

        ⚠️ 2026-10-02 修正（**偶发红的根因**）：原实现从不读请求体。POST/PATCH 的
        body 留在 socket 接收缓冲区里，而响应带 `Connection: close`，于是连接关闭时
        内核发现"还有未读数据"→ 直接发 **TCP RST**；客户端 `urllib` 侧表现为
        `WinError 10053`（本机软件中止了已建立的连接），被翻译成 `code='network'`
        —— 于是断言 `code=2001` 偶发变成 `code='network'`（实测 3 次跑 1 次失败）。

        为什么是"偶发"：body 较小时会先被内核接收进缓冲区、RST 不一定波及客户端读取；
        body 较大或时序不巧时才暴露。读掉 body 即彻底消除该路径。
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length > 0:
            try:
                self.rfile.read(length)
            except Exception:                      # pragma: no cover - 已断开
                pass

    def _handle(self) -> None:
        type(self).hits.append(self.path)
        self._drain_body()
        if self.mode == "hang":
            time.sleep(30)
            return
        if self.payloads:
            body = type(self).payloads.pop(0)
        else:
            body = type(self).payload
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # ⚠️ 必须显式 `Connection: close`：`BaseHTTPRequestHandler` 默认 HTTP/1.0，
        # 但 urllib 会复用连接池里的连接，于是每次刚起/刚关桩服务时
        # 第一个请求可能撞上已被对端关闭的连接 → WinError 10053（表现为随机失败）。
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle


def start_stub(**attrs: Any) -> Tuple[ThreadingHTTPServer, str]:
    """起一个可编程桩服务。

    ⚠️ 每次都把全部类属性重置一遍（含 `payloads` / `hits` / `mode`）：
    桩的配置是**类属性**，只改其中几个会让上一条用例的残留值串到这一条
    （实测踩过：`payloads` 残留导致 2001 用例拿到上一次的响应体而误报失败）。
    """
    _StubHandler.payload = b"{}"
    _StubHandler.payloads = []
    _StubHandler.mode = "json"
    _StubHandler.hits = []
    for key, value in attrs.items():
        setattr(_StubHandler, key, value)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def envelope(code: int, message: str = "ok", data: Any = None) -> bytes:
    return json.dumps({"code": code, "message": message, "data": data}).encode("utf-8")


# --------------------------------------------------------------------------- Qt 工具


def pump(app: QtWidgets.QApplication, ms: int = 60) -> None:
    """跑一小段事件循环（让 QThreadPool 的回调在主线程执行）。"""
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)
        time.sleep(0.005)


def wait_until(app: QtWidgets.QApplication, predicate: Callable[[], bool],
               timeout_s: float = 20.0, label: str = "") -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)
        if predicate():
            return True
        time.sleep(0.01)
    print(f"       （等待超时：{label or predicate}）")
    return False


def _loads_envelope(text: str) -> Dict[str, Any]:
    """响应体 → 信封 dict（与 `desktop_common.api._do_http` **同一套口径**）。

    ⚠️ 必须与生产实现一致：空响应/非 JSON 也返回 3001 信封，而不是抛
    `JSONDecodeError` —— 否则这两条自检就测不到 `ApiClient` 的错误处理
    （实测踩过：非 JSON 用例直接以未捕获异常失败）。
    """
    if not text or not text.strip():
        return {"code": 3001, "message": "服务端返回空响应", "data": None}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"code": 3001, "message": f"响应不是合法 JSON：{text[:120]}", "data": None}
    return parsed if isinstance(parsed, dict) else {"code": 3001,
                                                    "message": "响应信封不是 JSON object",
                                                    "data": None}


def _default_transport(method: str, url: str, body: Optional[dict],
                       token: Optional[str], timeout: float) -> Dict[str, Any]:
    """与 `ApiClient._do_http` 同样的裸 HTTP 实现（自检用，避免依赖私有方法签名）。

    ⚠️ 与生产实现同口径：非 2xx 的 HTTP 状态若带信封（v1.0 服务端就是这样表达
    1001/1002/2001/2002/3001/4001 的），要**照常返回信封**，不能笼统当成网络失败。
    """
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            text = exc.read().decode("utf-8", errors="replace")
        except Exception:                          # pragma: no cover - 读流失败
            text = ""
        parsed = _loads_envelope(text)
        if parsed.get("code") not in (None, "network"):
            return parsed
        return {"code": "network", "message": f"HTTP {exc.code}", "data": None}
    return _loads_envelope(text)


def _counting_transport(stats: Any) -> Callable[..., Dict[str, Any]]:
    """构造一个"记录调用线程"的传输层（真的走 HTTP，只是顺带计数）。"""
    def transport(method: str, url: str, body: Optional[dict],
                  token: Optional[str], timeout: float) -> Dict[str, Any]:
        stats.note_transport()
        return _default_transport(method, url, body, token, timeout)

    return transport


def call_in_worker(app: QtWidgets.QApplication, runner: Any,
                   fn: Callable[..., Any], *args: Any,
                   timeout_s: float = 20.0) -> Tuple[Any, Optional[BaseException]]:
    """把一次调用丢进 `QThreadPool` 并等结果。

    自检**不允许**在主线程直接调 `ApiClient`（那正是本项目要证明不会发生的事），
    所以连"错误码实测"这种探针也必须走 worker。
    """
    box: Dict[str, Any] = {}
    worker = runner.submit(fn, *args,
                           done=lambda data: box.update(data=data),
                           failed=lambda exc: box.update(error=exc))
    wait_until(app, lambda: "data" in box or "error" in box,
               timeout_s=timeout_s, label=getattr(fn, "__name__", repr(fn)))
    runner.wait(2000)
    return box.get("data"), box.get("error")


def grab(widget: QtWidgets.QWidget, name: str, app: QtWidgets.QApplication) -> Path:
    """截图（**固定 1080×760**，保证每张尺寸一致、可直接横向对比）。

    ⚠️ 只调 `resize()` 不够：当前 Tab 的最小高度不同（问卷 835 / 树洞·档案 1029），
    Qt 会把窗口顶到"布局最小高"上，`resize()` 被静默忽略（实测：`setFixedSize()`
    才真的到 760）。所以这里在截图前用 `setFixedSize()` 临时锁定设计尺寸，
    拍完立刻恢复成可自由缩放 —— 只在自检进程里影响截图，不改应用本身的缩放行为。
    """
    widget.setFixedSize(1080, 760)
    pump(app, 200)
    # ⚠️ offscreen 下**离屏窗口的后备缓冲会滞后**：刚 `setCurrentWidget()` 换过的页面，
    # `QWidget.grab()` 偶尔仍渲染上一个页面（实测踩过：06 拍到了上一张兜底页，
    # 而 `stack.currentWidget()` 明明已经是结果页）。强制把当前页重绘一遍再拍。
    current = getattr(widget, "stack", None)
    if current is not None and hasattr(current, "currentWidget"):
        page = current.currentWidget()
        if page is not None:
            page.repaint()
    widget.repaint()
    pump(app, 120)
    path = SHOT_DIR / name
    ok = widget.grab().save(str(path))
    # 恢复可缩放（QWIDGETSIZE_MAX = 16777215）
    widget.setMinimumSize(0, 0)
    widget.setMaximumSize(16777215, 16777215)
    if not ok:                                     # pragma: no cover - 防御
        raise RuntimeError(f"截图失败：{path}")
    return path


def image_colors(path: Path) -> int:
    """返回截图的**不同颜色数**（用于证明图里真的有文字/控件，不是纯色块）。"""
    image = QtGui.QImage(str(path))
    if image.isNull():
        return 0
    seen = set()
    for y in range(0, image.height(), 7):
        for x in range(0, image.width(), 7):
            seen.add(image.pixel(x, y))
    return len(seen)


# --------------------------------------------------------------------------- 各段检查


def check_environment() -> None:
    section("① 环境：PySide6 / offscreen / desktop_common")
    import PySide6

    REPORT.check("PySide6 已安装且可导入", True,
                 f"PySide6 {PySide6.__version__}（Qt {QtCore.qVersion()}）")
    REPORT.check("QT_QPA_PLATFORM=offscreen（无显示器可构建）",
                 os.environ.get("QT_QPA_PLATFORM") == "offscreen",
                 f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM')!r}")

    app = QtWidgets.QApplication.instance()
    loaded = theme.install_fonts(app, quiet=False)
    REPORT.check("已显式加载中文字体（offscreen 下中文才不是空白）", bool(loaded),
                 f"加载 {loaded or '（无）'}；"
                 "PySide6 不再随包带字体，offscreen 平台无系统字体库，故显式加载 .ttf/.ttc")

    import desktop_common
    import desktop_common.theme as theme_mod

    REPORT.check("desktop_common 四个模块存在", True,
                 "theme.py / api.py / widgets.py / models.py"
                 f"（包版本 {desktop_common.__version__}）")

    qss = theme_mod.build_qss()
    REPORT.check("build_qss() 可调用且返回非空 QSS", isinstance(qss, str) and len(qss) > 500,
                 f"QSS 长度 {len(qss)} 字符；objectName 约定 {len(OBJECT_NAMES)} 个")

    contrasts = {
        "INK/BG": theme.contrast_ratio(theme.INK, theme.BG),
        "INK/CARD": theme.contrast_ratio(theme.INK, theme.CARD),
        "INK_SOFT/BG": theme.contrast_ratio(theme.INK_SOFT, theme.BG),
        "INK_SOFT/CARD": theme.contrast_ratio(theme.INK_SOFT, theme.CARD),
        "PRIMARY_INK/MIST": theme.contrast_ratio(theme.PRIMARY_INK, theme.MIST),
        "INK/MIST": theme.contrast_ratio(theme.INK, theme.MIST),
    }
    worst = min(contrasts.values())
    REPORT.check("正文对比度全部 ≥ 4.5:1", worst >= 4.5,
                 "、".join(f"{k}={v}" for k, v in contrasts.items()))
    white_on_mist = theme.contrast_ratio("#FFFFFF", theme.MIST)
    REPORT.check("主色雾蓝不做字色（白字压雾蓝不足 4.5:1，故用 PRIMARY_INK）",
                 white_on_mist < 4.5 <= contrasts["PRIMARY_INK/MIST"],
                 f"#FFFFFF/MIST={white_on_mist}（<4.5，禁用）；"
                 f"PRIMARY_INK/MIST={contrasts['PRIMARY_INK/MIST']}（采用）")

    # 逐行解析 QSS：找出所有 `color:` 声明里有没有主色雾蓝
    mist_misuse = [line.strip() for line in qss.splitlines()
                   if line.strip().startswith("color:")
                   and theme.MIST.lower() in line.lower()]
    REPORT.check("主色 #A8C5D6 未出现在任何 `color:` 声明里（它当底不当字）",
                 not mist_misuse,
                 f"QSS 里 `color:` 声明共 "
                 f"{sum(1 for line in qss.splitlines() if line.strip().startswith('color:'))} "
                 f"条 → 命中主色 {len(mist_misuse)} 条"
                 + ("；" + str(mist_misuse) if mist_misuse
                    else "；主色只出现在 background/border/selection-background 上"))
    REPORT.check("圆角 ≥ 12px、卡片内边距 ≥ 20px",
                 theme.RADIUS >= 12 and theme.CARD_PADDING >= 20,
                 f"RADIUS={theme.RADIUS}px，CARD_PADDING={theme.CARD_PADDING}px")
    REPORT.check("动画时长 ≤ 240ms 且无循环动画属性",
                 theme.ANIM_MS <= 240 and not any(
                     token in qss for token in theme.FORBIDDEN_QSS_PATTERNS),
                 f"ANIM_MS={theme.ANIM_MS}ms；QSS 内无 "
                 f"{'/'.join(theme.FORBIDDEN_QSS_PATTERNS)}")

    missing = COPY.missing_keys
    REPORT.check("文案表键齐全（无缺键）", not missing,
                 f"可解析 ID {len(list(COPY.keys()))} 条；缺失 {missing or '无'}；"
                 f"copywriting.json 加载错误 {COPY.json_load_error or '无'}")

    # ApiClient 方法表（v1.0：学生端 8 个 + 教师端 4 个 = 12 个）
    student_methods = [
        "login_student", "health", "submit_questionnaire",
        "my_profile", "my_dates", "create_treehole", "my_treehole", "tips",
    ]
    teacher_methods = ["triage_list", "student_today", "ack_ticket", "login_teacher"]
    have = [name for name in student_methods + teacher_methods
            if callable(getattr(ApiClient, name, None))]
    REPORT.check("ApiClient 方法表完整（v1.0：学生端 8 + 教师端 4）",
                 len(have) == len(student_methods) + len(teacher_methods),
                 f"学生端 {len(student_methods)} 个 + 教师端 4 个：{', '.join(have)}")
    gone = [name for name in _OFFLINE_API_METHODS
            if callable(getattr(ApiClient, name, None))]
    REPORT.check("v1.0 已下线的 3 个方法不再存在（事后收回可见性 / 匿名转交通道 ×2）",
                 not gone,
                 f"被检查的方法名：{' / '.join(_OFFLINE_API_METHODS)} → "
                 f"仍存在 {gone or '无'}")

    REPORT.check("result_scene 枚举 4 个值与 UI 映射表一致（v1.0）",
                 set(RESULT_SCENES) == set(RESULT_PAGES.keys())
                 and len(RESULT_SCENES) == 4,
                 f"契约 {list(RESULT_SCENES)} ↔ UI {sorted(RESULT_PAGES)}")

    REPORT.check("契约 v1.0 端点表 = 11 个（本文件常量，供联调段核对）",
                 len(CONTRACT_ENDPOINTS_V1_0) == 11
                 and len(set(CONTRACT_ENDPOINTS_V1_0)) == 11,
                 "；".join(CONTRACT_ENDPOINTS_V1_0))


def check_api_client() -> None:
    section("② ApiClient：信封解包 / code != 0 抛错 / 超时重试 / 非 JSON")
    stats = CallStats()          # 本段用独立计数器，避免与联调段的断言互相串味

    # --- code != 0（1002）----------------------------------------------------
    stub, url = start_stub(payload=envelope(1002, "该接口仅限 teacher 访问", None), mode="json")
    client = ApiClient(url, timeout=3.0, transport=_counting_transport(stats))
    try:
        client.triage_list()
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = True
        detail = f"ApiError(code={exc.code!r}, message={exc.message!r}, path={exc.path!r})"
    REPORT.check("code=1002 → 抛 ApiError(1002)", raised, detail)

    # --- code != 0（1001：未登录 / token 过期）------------------------------
    _StubHandler.payload = envelope(1001, "字段 token 校验失败：未登录或 token 过期", None)
    try:
        client.my_profile("2026-10-02")
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = exc.code == 1001
        detail = f"ApiError(code={exc.code!r}, field={exc.field!r})"
    REPORT.check("code=1001 → 抛 ApiError(1001)", raised, detail)

    # --- code != 0（2001，带字段名）-----------------------------------------
    _StubHandler.payload = envelope(
        2001, "字段 detail 校验失败：down 分支 detail 必填（不限字数）", None)
    try:
        client.submit_questionnaire({"record_id": "rec_x"})
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = exc.code == 2001
        detail = (f"ApiError(code={exc.code!r}, field={exc.field!r})；"
                  f"字段名提取自 message = {exc.field == 'detail'}")
    REPORT.check("code=2001 → 抛 ApiError(2001) 且提取到字段名", raised, detail)

    # --- code != 0（2002：资源不存在）---------------------------------------
    _StubHandler.payload = envelope(2002, "字段 date 校验失败：资源不存在", None)
    try:
        client.my_profile("not-a-date")
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = exc.code == 2002
        detail = f"ApiError(code={exc.code!r}, message={exc.message!r})"
    REPORT.check("code=2002 → 抛 ApiError(2002)", raised, detail)

    # --- code != 0（3001：服务端内部错误）-----------------------------------
    _StubHandler.payload = envelope(3001, "服务端内部错误", None)
    try:
        client.health()
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = exc.code == 3001
        detail = f"ApiError(code={exc.code!r}, message={exc.message!r})"
    REPORT.check("code=3001 → 抛 ApiError(3001)", raised, detail)

    # --- code != 0（4001：提交频率超限）-------------------------------------
    _StubHandler.payload = envelope(4001, "提交频率超限", None)
    try:
        client.submit_questionnaire({"record_id": "rec_rate"})
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = exc.code == 4001
        detail = f"ApiError(code={exc.code!r}, message={exc.message!r})"
    REPORT.check("code=4001 → 抛 ApiError(4001)", raised, detail)

    # --- code = 0 → 返回 data ------------------------------------------------
    _StubHandler.payload = envelope(0, "ok", {"status": "ok", "version": "stub"})
    data = client.health()
    REPORT.check("code=0 → 解包返回 data", data.get("status") == "ok", f"data={data}")

    # --- 非 JSON 响应 → 3001 -------------------------------------------------
    _StubHandler.payload = b"<html>not json</html>"
    try:
        client.health()
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = exc.code == 3001
        detail = f"ApiError(code={exc.code!r}, message={exc.message!r})"
    REPORT.check("非 JSON 响应 → ApiError(3001)", raised, detail)

    # --- 超时：幂等写接口重试一次 -------------------------------------------
    hang_server, hang_url = start_stub(mode="hang")
    hang_client = ApiClient(hang_url, timeout=0.4,
                            transport=_counting_transport(stats))
    t0 = time.time()
    try:
        hang_client.submit_questionnaire({"record_id": "rec_retry_probe"})
        raised, detail = False, "未抛异常"
    except ApiError as exc:
        raised = exc.code == "timeout"
        detail = (f"ApiError(code={exc.code!r})；耗时 {time.time() - t0:.2f}s；"
                  f"命中桩服务 {len(_StubHandler.hits)} 次"
                  f"（幂等写接口超时重试一次 = 2 次请求）")
    REPORT.check("网络超时 → ApiError('timeout')，幂等写接口重试一次", raised, detail)
    hang_server.shutdown()
    stub.shutdown()

    # --- 传输层可注入（自检用它证明主线程没发请求）---------------------------
    injected: List[str] = []

    def fake_transport(method, url, body, token, timeout):
        injected.append(url)
        return {"code": 0, "message": "ok", "data": {"injected": True}}

    probe = ApiClient("http://127.0.0.1:1", transport=fake_transport)
    probe.health()
    REPORT.check("传输层可注入（无需真实网络即可测客户端逻辑）",
                 injected and probe.health().get("injected") is True,
                 f"注入的 transport 被调用：{injected[:1]}")


def check_ui(app: QtWidgets.QApplication,
             server: str = "http://127.0.0.1:8080") -> StudentMainWindow:
    """界面段（本段用 stub 传输，不产生真实流量）。

    ⚠️ 2026-10-02 修正（**曾造成"假绿"**）：本函数原先把窗口与 `ApiClient` 的 base_url
    **硬编码**成 `http://127.0.0.1:8080`，而 `check_integration` 只替换 `client._transport`
    （换成计数传输）、**并不改 base_url** —— 于是 `--server` 只影响那一处的可达性探针，
    **联调段的真实请求依旧打到 8080**。后果：只要 8080 上碰巧有别的服务在跑，自检就会
    "绿"（实测 11:25 的 105/105 正是打在别人的服务上），而 8080 空着时同一命令立刻 11 项失败。
    现在 base_url 由 `--server` 传入，两段真正指向同一个目标。
    """
    section("③ 界面：offscreen 构建完整控件树 + 关键控件断言 + 截图")

    ui_transport_calls: List[str] = []
    ui_requests: List[Tuple[str, str, Optional[dict]]] = []

    def ui_transport(method: str, url: str, body: Optional[dict],
                     token: Optional[str], timeout: float) -> Dict[str, Any]:
        """本段窗口的**确定性 stub**：不碰真实服务。

        ⚠️ 为什么注入：`check_ui` 的窗口**没有 token**（只验界面、不登录），真实服务对
        带鉴权的 `/profile/me|dates`、`/treehole/entries` 会回 **1001** —— 而 1001 的
        契约行为就是"跳登录页"，于是 06/07/08 三张截图会被**合法地**切回登录页
        （实测踩过：带服务跑时镜头拍到登录页）。本段只要"空数据 + 无错误"，
        需要真实错误码的场景在 ④b/④c/④f 段。
        """
        path_ = url.split("/api/v1", 1)[-1].split("?", 1)[0]
        ui_transport_calls.append(path_)
        ui_requests.append((method, path_, body))
        if path_ == "/health":
            return {"code": 0, "message": "ok", "data": {
                "status": "ok", "version": "1.0.0-stub",
                "server_time": now_iso(), "engine_ready": True}}
        if path_ == "/appointments/available_teachers":
            return {"code": 0, "message": "ok", "data": {"items": [
                {"teacher_id": "tch_T001", "name": "心理老师", "available": True},
            ]}}
        if path_ == "/appointments/available_rooms":
            return {"code": 0, "message": "ok", "data": {"items": [
                {"room_id": "rm_default", "name": "咨询室A", "location": None,
                 "features": None, "available": True},
            ]}}
        return {"code": 0, "message": "ok", "data": {"dates": [], "entries": [],
                                                     "submissions": [], "treehole": []}}

    window = StudentMainWindow(
        server,
        client=ApiClient(server, transport=ui_transport,
                         session_path=False),
        restore_session=False,
    )
    # ⚠️ 本段**只验界面**：把 `/health` 轮询停掉。窗口没有 token，真实服务会回 1001，
    # 而 1001 的契约行为就是跳登录页 —— 轮询一旦在截图期间命中，镜头拍到的就是登录页。
    # ④ 段联调前会 `start_health_polling()` 恢复（见 check_integration）。
    window.stop_health_polling()
    window.resize(1080, 760)
    window.show()
    pump(app, 150)

    REPORT.check("offscreen 下构建完整控件树（无异常）", True,
                 f"主窗口 objectName={window.objectName()!r}，"
                 f"控件总数={len(window.findChildren(QtWidgets.QWidget))}")

    # --- 关键控件：按 objectName 查找（UI约定 §7 第 4 条）---------------------
    required = {
        "RootStack": QtWidgets.QStackedWidget,
        "LoginView": QtWidgets.QWidget,
        "StudentNoInput": QtWidgets.QLineEdit,
        "MainTabs": QtWidgets.QWidget,
        "QuestionnaireStack": QtWidgets.QStackedWidget,
        "TreeholeTab": QtWidgets.QWidget,
        "TreeholeScroll": QtWidgets.QScrollArea,
        "ProfileTab": QtWidgets.QWidget,
        "ProfileDayPicker": QtWidgets.QComboBox,
        "AboutTab": QtWidgets.QWidget,
    }
    missing = [name for name, cls in required.items()
               if not isinstance(window.findChild(cls, name), cls)]
    found = {name: type(window.findChild(cls, name)).__name__
             for name, cls in required.items()
             if window.findChild(cls, name) is not None}
    REPORT.check("关键控件（objectName）全部存在", not missing,
                 f"命中 {len(found)}/{len(required)}：" +
                 "、".join(f"{k}={v}" for k, v in found.items()) +
                 (f"；缺失 {missing}" if missing else ""))

    tab_titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    REPORT.check("主窗口 Tab 数量与标题来自文案表（首页 + 问卷/树洞/档案/预约 + 关于）",
                 window.tabs.count() == 6
                 and tab_titles == [COPY["home.nav.home"], COPY["c.tab.questionnaire"],
                                    COPY["s.treehole.tab.title"], COPY["c.tab.profile"],
                                    COPY["c.tab.appointment"], COPY["c.tab.about"]],
                 f"tabs={tab_titles}（首页 / 问卷 / 树洞 / 我的档案 / 预约 / 关于）")

    # --- 独立「预约」标签页：选格 → 确认 → POST /appointments + 成功提示 + 清空选择 ----
    appt_tab = window.appointment_page
    _future = datetime.now().date() + timedelta(days=5)
    appt_tab.board.set_week(_future.year, _future.month, _future.day)
    _col = sch_mod.weekday_from_date(_future.year, _future.month, _future.day) - 1
    appt_tab._on_cell(2, _col)
    # 等「可预约咨询室」异步落地（必选：room_combo 有值才放行 _on_confirm）
    wait_until(app, lambda: appt_tab.room_combo.currentData() is not None,
               timeout_s=20.0, label="独立预约页咨询室下拉填充")
    appt_tab.share_questionnaire.setChecked(True)
    _appt_posts_before = sum(1 for m, p, _b in ui_requests
                             if m == "POST" and p == "/appointments")
    appt_tab._on_confirm()
    # 预约走 HTTP：确认 → 主窗口异步 `POST /appointments`，成功回调里才刷成功提示 + 清选择
    wait_until(app, lambda: not appt_tab._success_label.isHidden(),
               timeout_s=20.0, label="独立预约确认回调")
    _appt_posts = [(m, p, b) for m, p, b in ui_requests
                   if m == "POST" and p == "/appointments"]
    _slot = sch_mod.slot_id(_future.year, _future.month, _future.day, 2)
    REPORT.check("独立「预约」标签页：确认后 POST /appointments + 成功提示 + 清空选择 + 标记本人已约",
                 len(_appt_posts) == _appt_posts_before + 1
                 and not appt_tab._success_label.isHidden()
                 and appt_tab._success_label.text() == COPY["s.appointment.success"]
                 and appt_tab._selected is None
                 and _slot in appt_tab._remote.mine_slots()
                 and (_appt_posts[-1][2] or {}).get("share_questionnaire") is True,
                 f"新增 POST={len(_appt_posts) - _appt_posts_before} 条；"
                 f"成功提示显示={not appt_tab._success_label.isHidden()}；"
                 f"文案={appt_tab._success_label.text()!r}；"
                 f"mine 命中={_slot in appt_tab._remote.mine_slots()}；"
                 f"body={json.dumps(_appt_posts[-1][2] if _appt_posts else None, ensure_ascii=False)}")
    appt_tab.reset()

    # --- 非诊断声明（`docs/UI约定.md` §6 硬要求；文案在 `copywriting.md` §4.8 登记）-------
    # ⚠️ 2026-10-02 新增：此前**关于页与告知页都没有**这条声明，而 `AboutTab` 的 docstring
    #    却声称有；同一处还把 `c.loading.generic`（「稍等一下…」）当静态内容渲染。
    def _label_texts(widget: QtWidgets.QWidget) -> str:
        return " | ".join(lb.text() for lb in widget.findChildren(QtWidgets.QLabel) if lb.text())

    about_text = _label_texts(window.about_page)
    notice_text = _label_texts(window.questionnaire_page.pages["notice"])
    _disclaimer = COPY["c.disclaimer.nondiagnostic"]
    REPORT.check("关于页含非诊断声明 + 危机热线（UI约定 §6 页脚硬要求）",
                 _disclaimer in about_text and COPY.hotline_line() in about_text,
                 f"声明命中={_disclaimer in about_text}；热线命中={COPY.hotline_line() in about_text}；"
                 f"关于页文本={about_text[:150]!r}")
    REPORT.check("告知页含非诊断声明 + 危机热线（学生第一次看到的就是这一页）",
                 _disclaimer in notice_text and COPY.hotline_line() in notice_text,
                 f"声明命中={_disclaimer in notice_text}；热线命中={COPY.hotline_line() in notice_text}")
    REPORT.check("关于页/告知页不得出现加载态文案（曾把 c.loading.generic 误渲染成关于页正文）",
                 COPY["c.loading.generic"] not in about_text
                 and COPY["c.loading.generic"] not in notice_text,
                 f"关于页含「{COPY['c.loading.generic']}」={COPY['c.loading.generic'] in about_text}；"
                 f"告知页含={COPY['c.loading.generic'] in notice_text}")

    # --- 回归守门：平淡 + 填了原因 必须进 Q3 收集 detail ------------------------
    # ⚠️ 2026-10-02 新增。原实现把这条分支在 `_after_cause()` 里直接 `_emit_submit()`，
    #    并注释"矩阵第 3 行不存在求助选择"——那是对矩阵的**误读**。第 3 行与第 4 行要求相同：
    #    `cause_category` 必填 + **`detail` 必填** + `request_help` 必选。
    #    于是这条路径**从不收集 detail**（保持 None），提交必然被服务端拒：
    #        HTTP 400 / code=2001 / message='参数校验失败: detail'
    #    （实测复现；连点几次还会撞 `4001` 限流，把学生锁住一分钟。）
    #    本断言不走网络：只验**页面路由**与**请求体字段**，因此不会消耗限流额度、
    #    也不会打乱 ④b/④c 段那些依赖"限流先于参数校验"的探针。
    _pn = window.questionnaire_page
    _pn_submits: List[dict] = []
    _pn.submit_requested.connect(lambda b: _pn_submits.append(b))
    _pn.reset()
    _pn.show_page("q1")
    _pn.q1.group.set_value("plain")
    _pn._after_mood()
    _on_note = _pn.current_page_id == "plain_note"
    _pn.plain_note.area.set_text_value("有点烦，说不上来")
    _pn.plain_note._on_submit()
    _on_q2 = _pn.current_page_id == "q2"
    _pn.q2.group.set_value("study")
    _pn._after_cause()
    REPORT.check("平淡+填了原因：进 Q3 收集 detail，且**不**自动提交"
                 "（曾直接提交 → 400「参数校验失败: detail」）",
                 _on_note and _on_q2 and _pn.current_page_id == "q3" and not _pn_submits,
                 f"路径 plain_note→q2→{_pn.current_page_id!r}（应到 'q3'）；"
                 f"自动提交次数={len(_pn_submits)}（应为 0）")
    _pn.q3.area.set_text_value("这周月考没考好，怕爸妈失望")
    _pn._detail_submitted(_pn.q3.area.text_value())
    _pn.help.group.set_value("no")
    _pn_body = _pn.state.build_body(record_id="rec_probe_plainnote", consent_ts=None)
    REPORT.check("平淡+填了原因 的请求体满足矩阵第 3 行（plain_note / cause_category / detail 均非空）",
                 bool(_pn_body.get("plain_note")) and bool(_pn_body.get("cause_category"))
                 and bool(_pn_body.get("detail")),
                 f"body={json.dumps(_pn_body, ensure_ascii=False)}")
    _pn.reset()

    # --- 问卷 11 个页面 ------------------------------------------------------
    built = list(window.questionnaire_page.pages.keys())
    absent = [pid for pid in PAGE_ORDER if pid not in built]
    REPORT.check("问卷状态机的每个页面都真的进了 QStackedWidget", not absent,
                 f"栈内 {len(built)} 页：{built}" + (f"；缺失 {absent}" if absent else ""))
    REPORT.check("v1.0 问卷不再有 Q2.5 那一页与它的追问页",
                 "q25" not in built and "q25_detail" not in built,
                 f"页面清单里 q25/q25_detail 命中："
                 f"{[p for p in built if p.startswith('q25')] or '无'}")

    # --- 预约时间页（**课表选时** + 选择性分享）--------------------------------
    # ⚠️ v1.1 形态变更：原来 4 个下拉（年/月/日/时间段）换成**一张课表**
    #   （月份 1~12 导航栏 + 星期横轴 × 第 1~8 节纵轴，56 个可点方块）。
    #   旧的"四个下拉 / 时间段形如 HH:00"断言已随形态一起换掉 —— 不是为了让自检
    #   变绿而删检查：下拉在 v1.1 里确实不存在了，保留只会制造假失败。
    appt_page = window.questionnaire_page.appointment
    REPORT.check("预约页是课表：1~12 月导航栏 + 8×7 共 56 个可点方块",
                 len(appt_page.board.month_bar.buttons()) == 12
                 and len(appt_page.board.grid.cells()) == 56,
                 f"月份按钮={len(appt_page.board.month_bar.buttons())}；"
                 f"方块数={len(appt_page.board.grid.cells())}（8 节 × 7 天）")
    REPORT.check("课表横轴是星期几、纵轴是第 1~8 节（行头含真实时间段）",
                 appt_page.board.grid.column_head_text(0).startswith(
                     COPY["c.schedule.weekday.1"])
                 and appt_page.board.grid.period_head_text(1) ==
                 f"{COPY['c.schedule.period.1']}  08:00-08:45"
                 and appt_page.board.grid.period_head_text(8) ==
                 f"{COPY['c.schedule.period.8']}  16:05-16:50",
                 f"列头周一={appt_page.board.grid.column_head_text(0)!r}；"
                 f"第1节={appt_page.board.grid.period_head_text(1)!r}；"
                 f"第8节={appt_page.board.grid.period_head_text(8)!r}")

    _future = datetime.now().date() + timedelta(days=4)
    appt_page.board.set_week(_future.year, _future.month, _future.day)
    _column = sch_mod.weekday_from_date(_future.year, _future.month, _future.day) - 1
    appt_page._on_cell(3, _column)
    payload = appt_page.payload()
    REPORT.check("点方块 → 载荷含 年/月/日/第几节/星期几/起止钟点 + 两个分享布尔",
                 {"year", "month", "day", "period", "weekday", "time",
                  "time_start", "time_end", "share_questionnaire",
                  "share_treehole"} <= set(payload)
                 and payload.get("period") == "3"
                 and payload.get("time_start") == "09:55"
                 and payload.get("time_end") == "10:40",
                 json.dumps(payload, ensure_ascii=False, sort_keys=True))
    # 预约人基本信息：**取自登录档案**，不是学生手填（避免填错学号导致老师找不到人）
    appt_page._profile_provider = lambda: {
        "id": "stu_2023001", "name": "林小满", "class_name": "高一(2)班"}
    appt_page.enter()
    REPORT.check("预约页带出预约人基本信息（姓名 / 班级 / 学号**取自登录档案**）",
                 appt_page._info_values["name"].text() == "林小满"
                 and appt_page._info_values["class_name"].text() == "高一(2)班"
                 and appt_page._info_values["id"].text() == "stu_2023001",
                 f"姓名={appt_page._info_values['name'].text()!r}；"
                 f"班级={appt_page._info_values['class_name'].text()!r}；"
                 f"学号={appt_page._info_values['id'].text()!r}")
    appt_page.stop_sync()
    REPORT.check("预约页选择性分享控件可被勾选",
                 appt_page.share_questionnaire.isCheckable()
                 and appt_page.share_treehole.isCheckable()
                 and not appt_page.share_questionnaire.isChecked()
                 and not appt_page.share_treehole.isChecked(),
                 f"测评分享={appt_page.share_questionnaire.isChecked()}；"
                 f"树洞分享={appt_page.share_treehole.isChecked()}")

    # 「请求帮助」→ 先跳去选预约时间，不直接提交
    _ap = window.questionnaire_page
    _ap.reset()
    _ap.show_page("q1")
    _ap.q1.group.set_value("down")
    _ap._after_mood()
    _ap.explore.group.set_selected(["family"])
    _ap._after_explore()
    _ap.q3.area.set_text_value("占位：验证预约跳转")
    _ap._detail_submitted(_ap.q3.area.text_value())
    _ap.help.group.set_value("request")
    _ap._final_submit(True)
    REPORT.check("『请求心理老师帮助』→ 先跳去选预约时间（不直接提交）",
                 _ap.current_page_id == "appointment",
                 f"当前页={_ap.current_page_id!r}（应为 'appointment'）")
    # 「预约确认」→ 组装 `POST /appointments` 请求体（预约人由服务端从 token 推导，
    # 不再本地落 JSONL）。HTTP 共享库口径下，这里直接验证请求体组装 + 幂等键生成/复用：
    # 同一次填写只用一个 `apt_id`，超时重试 / 重提交不会重复落库。
    _appt_payload = {"year": "2026", "month": "10", "day": "3",
                     "time": "15:00",
                     "share_questionnaire": True,
                     "share_treehole": False}
    _body_1 = window._appointment_body(_appt_payload)
    _body_2 = window._appointment_body(_appt_payload)   # 同一份载荷反复组包 → apt_id 复用
    REPORT.check("「预约确认」→ 组装 POST /appointments 请求体（幂等 apt_ + 字段齐全 + 复用）",
                 set(_body_1) == {"apt_id", "year", "month", "day", "time",
                                  "teacher_id", "room_id", "share_questionnaire", "share_treehole"}
                 and str(_body_1["apt_id"]).startswith("apt_")
                 and _body_1["teacher_id"] is None
                 and _body_1["room_id"] is None
                 and _body_1["share_questionnaire"] is True
                 and _body_1["share_treehole"] is False
                 and _body_1["time"] == "15:00"
                 and _body_1["year"] == "2026" and _body_1["month"] == "10"
                 and _body_1["day"] == "3"
                 and _body_2["apt_id"] == _body_1["apt_id"],
                 json.dumps(_body_1, ensure_ascii=False, sort_keys=True)
                 + f"；二次组包 apt_id 复用={_body_2['apt_id'] == _body_1['apt_id']}")
    _ap.reset()

    scenepages = {
        scene: type(window.questionnaire_page.result_pages.get(scene)).__name__
        for scene in RESULT_SCENES
    }
    REPORT.check("result_scene 四个值都有对应页面（穷举）",
                 all(name != "NoneType" for name in scenepages.values())
                 and len(scenepages) == 4,
                 json.dumps(scenepages, ensure_ascii=False))

    # 让栈真的切到每个结果页（证明不是只有字典表）
    switched: Dict[str, str] = {}
    for scene in RESULT_SCENES:
        window.questionnaire_page.show_result(scene)
        switched[scene] = window.questionnaire_page.current_page_id
    REPORT.check("show_result() 能切到 4 个结果页",
                 all(switched[s] == RESULT_PAGES[s] for s in RESULT_SCENES),
                 json.dumps(switched, ensure_ascii=False))
    # 老师回复库按 result_scene 匹配后落位要正确（问题 6）：self_care 的心情小贴士
    # 渲染在 extra（`s.end.selfcare.tips`），plain_tips 的贴士就是 body。
    window.questionnaire_page.show_result("self_care", tips_text="自定义：先深呼吸十次。")
    sc_page = window.questionnaire_page.result_pages["self_care"]
    window.questionnaire_page.show_result("plain_tips", tips_text="自定义：先深呼吸十次。")
    pt_page = window.questionnaire_page.result_pages["plain_tips"]
    REPORT.check("回复落位正确：self_care → extra（不覆盖正文），plain_tips → body",
                 sc_page.extra_label.text() == "自定义：先深呼吸十次。"
                 and sc_page.body_label.text() != "自定义：先深呼吸十次。"
                 and pt_page.body_label.text() == "自定义：先深呼吸十次。",
                 f"self_care.extra={sc_page.extra_label.text()!r}；"
                 f"self_care.body={sc_page.body_label.text()!r}；"
                 f"plain_tips.body={pt_page.body_label.text()!r}")
    # 未登记值走可见兜底页（不静默）
    window.questionnaire_page.show_result("brand_new_scene")
    REPORT.check("未登记的 result_scene → 可见兜底页（不静默失败）",
                 window.questionnaire_page.current_page_id == "result_unmapped"
                 and "result_unmapped" in window.questionnaire_page.pages,
                 f"current={window.questionnaire_page.current_page_id!r}；"
                 f"该页确实注册在页面字典里="
                 f"{'result_unmapped' in window.questionnaire_page.pages}；"
                 f"页面清单={sorted(window.questionnaire_page.pages)}")
    # v1.1 才有的那个场景值在 v1.0 里就是"未登记值"，必须落兜底页而不是空白
    # （字符串从 `_V11_ONLY_SCENE` 取，不在断言里再抄一遍）
    window.questionnaire_page.show_result(_V11_ONLY_SCENE)
    REPORT.check("v1.1 才有的第 5 个场景值在 v1.0 落可见兜底页（防御性，不静默）",
                 window.questionnaire_page.current_page_id == "result_unmapped"
                 and _V11_ONLY_SCENE not in RESULT_PAGES,
                 f"喂进去的场景值={_V11_ONLY_SCENE!r}；"
                 f"current={window.questionnaire_page.current_page_id!r}；"
                 f"RESULT_PAGES keys={sorted(RESULT_PAGES)}")
    window.questionnaire_page.reset()

    # --- 树洞零"分享/公开"控件 ----------------------------------------------
    banned = ("分享", "公开", "让老师看", "可见性", "谁能看到", "授权")
    offenders: List[str] = []
    tree = window.treehole_page
    scanned = 0
    for widget in [tree] + tree.findChildren(QtWidgets.QWidget):
        scanned += 1
        texts = []
        for attr_name in ("text", "placeholderText", "toolTip", "windowTitle"):
            getter = getattr(widget, attr_name, None)
            if callable(getter):
                try:
                    value = getter()
                except Exception:                  # pragma: no cover - 防御
                    value = ""
                if isinstance(value, str) and value:
                    texts.append((attr_name, value))
        for attr_name, text in texts:
            for word in banned:
                if word in text:
                    offenders.append(f"{type(widget).__name__}({widget.objectName()})"
                                     f".{attr_name}={text!r} 命中 {word!r}")
    REPORT.check("树洞控件树零『分享/公开/让老师看/可见性』文案", not offenders,
                 f"检索 {scanned} 个控件的 text/placeholder/tooltip/title，"
                 f"禁用词 {list(banned)} → 命中 {len(offenders)}"
                 + ("；" + "；".join(offenders[:3]) if offenders else ""))
    REPORT.check("树洞 visibility 恒为 private（无分享开关）",
                 VISIBILITY == "private" and tree.visibility == "private",
                 f"desktop VISIBILITY={VISIBILITY!r}，TreeholeTab.visibility="
                 f"{tree.visibility!r}；树洞请求体字段 = entry_id/content/mood_tag")

    # --- 树洞情绪卡片：mood_tag 写进后要显示**可见的情绪卡片**，不再只是 tooltip ----
    tree.set_entries([
        {"entry_id": "tre_mood_down", "ts": f"{today_str()}T21:40:00+08:00",
         "content": "今天有点低落", "mood_tag": "down"},
        {"entry_id": "tre_mood_none", "ts": f"{today_str()}T22:00:00+08:00",
         "content": "没什么特别的", "mood_tag": None},
    ])
    pump(app, 60)
    mood_rows = tree.rows()
    REPORT.check("树洞条目显示情绪卡片（mood_tag 可见，不再是 hover 才见的 tooltip）",
                 len(mood_rows) == 2
                 and mood_rows[0].mood_badge_text == COPY["s.treehole.moodtag.option.down"]
                 and mood_rows[1].mood_badge_text == "",
                 f"行数={len(mood_rows)}；"
                 f"第1行情绪卡片={mood_rows[0].mood_badge_text!r}"
                 f"（应为 {COPY['s.treehole.moodtag.option.down']!r}）；"
                 f"第2行情绪卡片={mood_rows[1].mood_badge_text!r}（无标记，应为空）")

    # --- 档案页：以 request_help 为显示依据，且**零已下线能力入口** ----------
    # ⚠️ 日期用**今天**（`today_str()`），不用写死的演示日期：档案页的日期选择器
    # 只有"今天"这一项时才会真的选中并渲染这些行（写死日期会让断言看到空列表）。
    demo_date = today_str()
    # 契约响应 `submissions[]` 是**升序**（服务端 scan_day 的顺序），UI 反转成"最新在前"。
    # 这里按同一口径造数据：先 false 后 true → 渲染后 true 在最上面。
    window.profile_page.set_profile({"date": demo_date, "submissions": [
        {"record_id": "rec_demo_selfonly", "ts": f"{demo_date}T20:10:00+08:00",
         "mood": "plain", "cause_category": None, "detail": None,
         "request_help": False},
        {"record_id": "rec_demo_help", "ts": f"{demo_date}T21:10:00+08:00",
         "mood": "down", "cause_category": "study", "detail": "演示用：这次请求了老师帮助。",
         "request_help": True},
    ]})
    pump(app, 60)
    rows = window.profile_page.rows()
    labels = window.profile_page.status_labels()
    REPORT.check("档案每行都以 request_help 显示求助状态（文案来自文案表）",
                 len(rows) == 2
                 and labels == [COPY["s.help.selected.request"], COPY["s.help.selected.no"]],
                 f"行数={len(rows)}；状态标签={labels}；"
                 f"期望=[{COPY['s.help.selected.request']!r}, {COPY['s.help.selected.no']!r}]"
                 f"（最新在前 → true 在上）")
    REPORT.check("状态标签只用文案表已有键，没有自造『已分享/未分享』字样",
                 not any(word in " ".join(labels)
                         for word in ("已分享", "未分享")),
                 f"标签文本={labels}；来源键 = {sorted(set(STATUS_COPY.values()))}")
    help_ids = [r.record_id for r in window.profile_page.help_requested_rows()]
    REPORT.check("request_help=true 的行能被单独识别（契约强制 consent_share == request_help）",
                 help_ids == ["rec_demo_help"],
                 f"request_help=true 的 record_id={help_ids}")

    # 禁用词从**文案表**推导：v1.0 下线的能力对应的文案键，界面上一个都不许出现。
    offline_words = forbidden_words_from_copy(*_OFFLINE_KEY_PREFIXES)
    profile_widgets = [window.profile_page] + window.profile_page.findChildren(
        QtWidgets.QWidget)
    offline_hits: List[str] = []
    for widget in profile_widgets:
        for attr_name in ("text", "placeholderText", "toolTip", "windowTitle"):
            getter = getattr(widget, attr_name, None)
            if callable(getter):
                try:
                    value = getter()
                except Exception:                  # pragma: no cover - 防御
                    value = ""
                if isinstance(value, str) and value:
                    for word in offline_words:
                        if word in value:
                            offline_hits.append(f"{type(widget).__name__}"
                                                f"({widget.objectName()}).{attr_name}={value!r}")
    # 档案页里**允许**的按钮 = 刷新（拉日期）+ 面包屑（档案记录/情绪可视化）+ 周导航（上一周/下一周）；
    # 任何记录级的操作按钮（旧版的收回可见性入口）都必须不存在。
    profile_buttons = window.profile_page.findChildren(QtWidgets.QPushButton)
    allowed_profile_buttons = {
        COPY["c.action.retry"], COPY["c.profile.view.records"],
        COPY["c.profile.view.chart"], COPY["c.profile.chart.week.prev"],
        COPY["c.profile.chart.week.next"],
    }
    record_buttons = [b for b in profile_buttons if b.text() not in allowed_profile_buttons]
    REPORT.check("档案页零已下线能力入口（无记录级按钮、无下线能力文案）",
                 not offline_hits and not record_buttons,
                 f"禁用词 {len(offline_words)} 条（推导自文案表键 "
                 f"{list(_OFFLINE_KEY_PREFIXES)}）；"
                 f"扫描 {len(profile_widgets)} 个控件 → 命中 {len(offline_hits)}；"
                 f"档案页按钮 {len(profile_buttons)} 个"
                 f"（允许 刷新 + 面包屑 + 周导航，共 {len(allowed_profile_buttons)} 种文案）"
                 f"，记录级按钮={len(record_buttons)}"
                 + ("；" + "；".join(offline_hits[:3]) if offline_hits else ""))

    # --- 情绪可视化（面包屑导航 + 一周情绪折线图）----------------------------
    profile_page = window.profile_page
    profile_page.chart_btn.click()
    pump(app, 60)
    REPORT.check("面包屑「情绪可视化」→ 切到图表视图",
                 profile_page.view_stack.currentIndex() == 1,
                 f"view_stack.currentIndex={profile_page.view_stack.currentIndex()}（应 1）")
    # 等 mood_range 异步落地（stub 返回空），避免它晚到覆盖下面直接塞的数据
    window.runner.wait(3000)
    pump(app, 100)
    week_days = profile_page._week_days()
    profile_page.set_mood_range([
        {"date": week_days[0], "mood": "down"},
        {"date": week_days[2], "mood": "plain"},
        {"date": week_days[4], "mood": "happy"},
    ])
    pump(app, 60)
    REPORT.check("图表接收每日情绪点（有数据 → 空态隐藏）",
                 profile_page.chart.has_data() and not profile_page.chart_empty.isVisible(),
                 f"has_data={profile_page.chart.has_data()}；"
                 f"空态可见={profile_page.chart_empty.isVisible()}")
    REPORT.check("图表把情绪映射为 1/2/3（沮丧/平淡/高兴）",
                 profile_page.chart._mood.get(week_days[0]) == "down"
                 and profile_page.chart._mood.get(week_days[2]) == "plain"
                 and profile_page.chart._mood.get(week_days[4]) == "happy",
                 f"week={week_days[0]}~{week_days[-1]}；_mood={profile_page.chart._mood}")
    old_title = profile_page.week_title.text()
    profile_page.week_next_btn.click()
    pump(app, 60)
    REPORT.check("「下一周」切换图表所在周",
                 profile_page.week_title.text() != old_title,
                 f"标题 {old_title!r} → {profile_page.week_title.text()!r}")
    profile_page.records_btn.click()
    pump(app, 60)
    REPORT.check("面包屑「档案记录」→ 切回记录列表",
                 profile_page.view_stack.currentIndex() == 0,
                 f"view_stack.currentIndex={profile_page.view_stack.currentIndex()}（应 0）")

    # --- 键盘可达 -----------------------------------------------------------
    clickables = [w for w in window.findChildren(QtWidgets.QPushButton)]
    no_focus = [w for w in clickables if w.focusPolicy() != Qt.StrongFocus]
    REPORT.check("所有可点控件 StrongFocus（键盘可达）", not no_focus,
                 f"按钮 {len(clickables)} 个，非 StrongFocus {len(no_focus)} 个")
    qss = theme.build_qss()
    REPORT.check("QSS 有可见 focus 样式", "QPushButton:focus" in qss,
                 "QSS 含 'QPushButton:focus { border: 2px solid #7FA6BA; }'")

    # --- 截图 ---------------------------------------------------------------
    section("③b 截图（offscreen `widget.grab().save()`）")
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    shots: List[Path] = []

    window.show_login()
    shots.append(grab(window, "01_login.png", app))

    window.show_main()
    q = window.questionnaire_page
    q.reset()
    shots.append(grab(window, "02_questionnaire_notice.png", app))

    q.show_page("q1")
    shots.append(grab(window, "03_q1_mood.png", app))

    q.q1.group.set_value("down")
    q._after_mood()
    q.explore.group.set_selected(["exam", "sleep"])
    shots.append(grab(window, "03b_explore.png", app))
    q._after_explore()
    shots.append(grab(window, "04_q3_detail.png", app))

    q.q3.area.set_text_value("最近三次月考排名连续下滑，晚自习完全无法集中。")
    q._detail_submitted(q.q3.area.text_value())
    shots.append(grab(window, "05_help_choice.png", app))

    # 05b 预约时间**课表**（v1.1 新增页面：月份导航栏 + 星期 × 第几节）
    q.help.group.set_value("request")
    q._final_submit(True)
    _appt = q.appointment
    _appt._profile_provider = lambda: {
        "id": "stu_2023001", "name": "林小满", "class_name": "高一(2)班"}
    _appt.enter()
    _future = datetime.now().date() + timedelta(days=4)
    _appt.board.set_week(_future.year, _future.month, _future.day)
    _appt._on_cell(3, sch_mod.weekday_from_date(
        _future.year, _future.month, _future.day) - 1)
    window.tabs.setCurrentWidget(q)
    pump(app, 250)
    # 页面比一屏高（课表才是主角）：截图前滚到课表那一屏，拍真实可见的网格
    from PySide6.QtWidgets import QScrollArea

    _area = _appt.findChild(QScrollArea)
    if _area is not None:
        _bar = _area.verticalScrollBar()
        _bar.setValue(int(_bar.minimum() + (_bar.maximum() - _bar.minimum()) * 0.3))
        pump(app, 150)
    shots.append(grab(window, "05b_appointment_grid.png", app))
    _appt.stop_sync()

    q.help.group.set_value("no")
    # ⚠️ 2026-10-02 修正（06 截图曾拍到错误态）：这里**不再触发真实提交**。
    #   原来调 `q.help._on_submit()` 会发出一次**异步** POST，其回调（成功或失败）
    #   可能晚于下面的 `show_result("self_care")` 落地，把页面覆盖成错误态 ——
    #   实测 06 被拍成 `c.error.unknown`（"未知码 | 这里出了点小状况…"），
    #   而 `stack.currentWidget()` 看起来"已是结果页"，很难察觉。
    #   截图要记录的是**结果页的外观**，而 `show_result` 正是回调成功后所调用的函数，
    #   所以直接驱动到该状态既确定性、又不失实。
    q.show_result("self_care")
    window.tabs.setCurrentWidget(q)
    pump(app, 200)
    shots.append(grab(window, "06_result_self_care.png", app))

    window.tabs.setCurrentWidget(window.treehole_page)
    window.treehole_page.open_editor()
    # ⚠️ 先等启动时的 `my_dates` / `my_treehole` 落地再塞演示数据：否则异步响应会
    # 在 `grab()` 之前把演示条目**清成空列表**（带服务跑时实测踩过：07/08 被拍成空态）
    window.runner.wait(8000)
    pump(app, 150)
    window.treehole_page.set_entries([
        {"entry_id": "tre_demo1", "ts": f"{demo_date}T21:40:00+08:00",
         "content": "今天其实还好，就是有点累。写下来感觉没那么堵了。", "mood_tag": "plain"},
        {"entry_id": "tre_demo2", "ts": f"{demo_date}T22:31:00+08:00",
         "content": "和妈妈打了电话，她说想我了。挂了以后哭了一会儿，但心里松了一点。",
         "mood_tag": None},
    ])
    shots.append(grab(window, "07_treehole.png", app))

    window.tabs.setCurrentWidget(window.profile_page)
    # 档案页同理：`set_profile()` 会清空旧行，异步响应晚到就会把演示行顶掉
    window.runner.wait(8000)
    pump(app, 150)
    window.profile_page.set_dates([demo_date])
    window.profile_page.set_profile({"date": demo_date, "submissions": [
        {"record_id": "rec_demo_selfonly", "ts": f"{demo_date}T20:10:00+08:00",
         "mood": "plain", "cause_category": None, "detail": None, "request_help": False},
        {"record_id": "rec_demo_help", "ts": f"{demo_date}T21:10:00+08:00",
         "mood": "down", "cause_category": "study",
         "detail": "演示用：这次请求了老师帮助。", "request_help": True},
    ]})
    pump(app, 100)
    shots.append(grab(window, "08_profile.png", app))

    # 08b：情绪可视化图表（面包屑切到图表视图 + 一周情绪点，含断线示例）
    window.profile_page.chart_btn.click()
    window.runner.wait(2000)      # 等异步 mood_range（stub 空）落地，再塞演示数据
    pump(app, 100)
    week = window.profile_page._week_days()
    window.profile_page.set_mood_range([
        {"date": week[0], "mood": "down"},
        {"date": week[1], "mood": "plain"},
        {"date": week[3], "mood": "happy"},
        {"date": week[5], "mood": "plain"},
    ])
    pump(app, 200)
    shots.append(grab(window, "08b_mood_chart.png", app))
    window.profile_page.records_btn.click()
    pump(app, 100)

    # 09：要求 1 的「数据库恢复中」提示态（顶部非阻塞提示条 + 提交按钮禁用）
    window.tabs.setCurrentWidget(q)
    q.reset()
    q.show_page("q1")
    window.set_engine_ready(False)
    shots.append(grab(window, "09_engine_not_ready.png", app))
    window.set_engine_ready(True)

    # 10：关于页 —— 「非诊断声明 + 危机热线」的**视觉证据**（UI约定 §6 硬要求）。
    #     2026-10-02 新增：此前关于页既没有声明、还把加载态文案当正文渲染，
    #     这条要求没有截图证据；补拍以便答辩时直接出示。
    window.tabs.setCurrentWidget(window.about_page)
    pump(app, 200)
    shots.append(grab(window, "10_about.png", app))

    sizes = [(p.name, p.stat().st_size) for p in shots]
    REPORT.check("截图成功且 ≥ 5 张", len(shots) >= 5 and all(s > 0 for _n, s in sizes),
                 "；".join(f"{n} {s} bytes" for n, s in sizes))
    richness = {p.name: image_colors(p) for p in shots}
    REPORT.check("截图为真实渲染（不同颜色数远超纯色底）",
                 all(count > 20 for count in richness.values()),
                 "不同颜色数（隔点采样）：" +
                 "、".join(f"{k}={v}" for k, v in richness.items()))
    # 补盲区：`check_environment` 在界面树构建**之前**就查过 missing_keys，那时首页
    # 的 home.* 键还没被请求；这里在完整界面树构建完之后**再查一次**，界面里被
    # 引用、但文案表里没有的键会当场暴露（曾漏掉 home.* → 渲染成 ⟪缺文案:…⟫）。
    # 过滤空串：`_FlowPage` 的某些页没定义 subtitle_key，会调 COPY.get("")，
    # 把空串记成"缺失"，属无害副产物（不是真缺键），这里不算。
    missing_after_ui = [k for k in COPY.missing_keys if str(k).strip()]
    REPORT.check("构建完整界面树后无缺文案键（界面引用的键都在文案表里）",
                 not missing_after_ui,
                 f"界面树构建后缺失 {len(missing_after_ui)} 个键：{missing_after_ui or '无'}")
    return window


def check_integration(app: QtWidgets.QApplication, window: StudentMainWindow,
                      server: str, student_no: str) -> None:
    section(f"④ 真实联调（mock server {server}，学号 {student_no}）")
    client = window.client
    runner = window.runner
    # ⚠️ 可达性探针用**新 ApiClient**（自己的 `_do_http`）：`check_ui` 段给窗口的
    # `client._transport` 装了确定性 stub，而 `StudentMainWindow._health_worker` 在
    # `__init__` 时就绑定了当时的 bound method，之后换 `client._transport` 影响不到它
    # —— 继续用 `client.health()` 探到的是 **stub 的空数据**，不是"服务在不在"
    # （实测踩过：`① 登录` 与 `mock server 可达` 同时失败）。
    probe_client = ApiClient(server)
    health, health_error = call_in_worker(app, runner, probe_client.health)
    if health_error is not None:
        REPORT.check("mock server 可达", False, f"{health_error}")
        return
    REPORT.check("mock server 可达", bool(health.get("status")),
                 f"GET /health → {json.dumps(health, ensure_ascii=False)}")
    REPORT.check("健康检查返回的版本号是 v1.1 服务端",
                 str(health.get("version", "")).startswith("1.1"),
                 f"version={health.get('version')!r}")

    STATS.reset()
    # 联调段用**全局 STATS** 计数（`--skip-network` 时不重置，断言只在本段跑）
    window.client._transport = _counting_transport(STATS)
    # `check_ui` 段为了拍出确定性的界面，把窗口的 `/health` 轮询停了、`client` 换成了
    # stub、且窗口停在"关于"页 —— 联调前把这三样恢复回去（否则登录后立刻打
    # `/profile/me/dates` 会撞上 stub 的 1001，当场跳回登录页，实测踩过 `① 登录` 失败）。
    window._health_worker = None
    window.start_health_polling()
    window.show_main()
    # ---------------- 注册 + 登录（v1.1 注册制，走真实 UI 按钮）------------
    seat_no = student_no[4:] if student_no.startswith("stu_") else student_no
    _reg, _reg_err = call_in_worker(app, runner, client.register_student,
                                    "高一(2)班", "林小满", seat_no, "1234")
    window.show_login()
    window.login_view.student_input.setText(seat_no)
    window.login_view.password_input.setText("1234")
    window.login_view.enter_button.click()
    ok = wait_until(app, lambda: window.stack.currentWidget() is window.tabs,
                    timeout_s=25, label="登录（POST /auth/login）")
    profile = client.profile or {}
    REPORT.check("① 注册+登录：UI 点击 → QThreadPool → POST /auth/login",
                 ok and bool(client.token),
                 f"token={str(client.token)[:8]}…；profile="
                 f"{json.dumps(profile, ensure_ascii=False)}")
    window.runner.wait(5000)

    # ---------------- 问卷：沮丧分支 → 一次性提交 --------------------------
    q = window.questionnaire_page
    q.reset()
    # 数一数"提交了多少次"（比数 worker 更直接地证明逐题跳转不走网络）
    submits: List[dict] = []
    q.submit_requested.connect(lambda body: submits.append(body))
    q.show_page("q1")
    q.q1.group.set_value("down")
    q.q1.next_button.click()
    q.explore.group.set_selected(["study", "exam"])
    q.explore.next_button.click()
    REPORT.check("逐题跳转纯本地（走到 Q3 仍未产生任何提交请求）",
                 q.current_page_id == "q3" and not submits,
                 f"路径 notice→q1→explore→{q.current_page_id!r}；"
                 f"submit_requested 触发次数={len(submits)}")

    q.q3.area.set_text_value("最近三次月考排名连续下滑，晚自习完全无法集中，看到卷子就心慌。")
    q.q3.submit_button.click()
    q.help.group.set_value("no")
    q.help._on_changed("no")
    q.help.submit_button.click()
    REPORT.check("只在最后一屏触发一次提交请求", len(submits) == 1,
                 f"submit_requested 触发次数={len(submits)}；"
                 f"body={json.dumps(submits[0], ensure_ascii=False) if submits else None}")
    if submits:
        keys = sorted(submits[0].keys())
        REPORT.check("提交 payload 只有 v1.0 的 8 个字段（无 v1.1 的 material 字段）",
                     keys == sorted(SUBMISSION_FIELDS_V1_0),
                     f"实际字段={keys}；契约 v1.0 白名单={sorted(SUBMISSION_FIELDS_V1_0)}")
    ok = wait_until(app, lambda: str(q.state.result_scene or "") != "", timeout_s=25,
                    label="问卷提交（POST /questionnaire/submissions）")
    scene = q.state.result_scene
    REPORT.check("② 提交问卷：一次性 POST /questionnaire/submissions → 结果页",
                 ok and scene == "self_care",
                 f"result_scene={scene!r}（down + request_help=false → self_care）；"
                 f"当前页={q.current_page_id!r}；record_id={q.state.record_id!r}")
    record_id = q.state.record_id
    window.runner.wait(5000)

    # ---------------- 档案 --------------------------------------------------
    # ⚠️ `check_ui` 段为了断言状态标签，往档案页塞过一份演示数据（`rec_demo_*`）。
    # 这里必须先让页面真的以**今天**为选中日、由服务端数据重建行，再断言本次提交；
    # 否则断言看到的是残留的演示行（实测踩过这一条）。
    date = str(now_iso())[:10]
    window.show_main()
    window.tabs.setCurrentWidget(window.profile_page)
    loaded, _err = call_in_worker(app, runner, client.my_profile, date)
    window.profile_page.set_dates([date])
    window.profile_page.set_profile(loaded or {})
    pump(app, 80)
    ok = wait_until(
        app,
        lambda: any(r.record_id == record_id for r in window.profile_page.rows()),
        timeout_s=25, label="档案里出现本次提交的 record_id",
    )
    rows = window.profile_page.rows()
    labels = window.profile_page.status_labels()
    REPORT.check("③ 拉档案：GET /profile/me → 档案页渲染本次记录",
                 ok and bool(rows) and record_id in [r.record_id for r in rows],
                 f"date={date}；行数={len(rows)}；本次提交={record_id!r}；"
                 f"状态标签={labels}")
    REPORT.check("档案里每条的状态标签都与它的 request_help 一致",
                 all((label == COPY["s.help.selected.request"]) == r.request_help
                     for r, label in zip(rows, labels)),
                 f"逐条核对 {len(rows)} 行："
                 + "、".join(f"{r.record_id[:14]}…={'请求帮助' if r.request_help else '只留给自己'}"
                            for r in rows[:6]))
    raw_profile, raw_error = call_in_worker(app, runner, client.my_profile, date)
    items = list((raw_profile or {}).get("submissions") or [])
    item = next((x for x in items if x.get("record_id") == record_id), None)
    REPORT.check("GET /profile/me 响应里该条 request_help=false（本次选了\"不用帮助\"）",
                 raw_error is None and item is not None and item.get("request_help") is False,
                 f"该条响应={json.dumps(item, ensure_ascii=False)}")
    REPORT.check("GET /profile/me 响应结构 = v1.0 的 6 个字段（不含 consent_share）",
                 item is not None
                 and sorted(item.keys()) == sorted(
                     ["record_id", "ts", "mood", "cause_category", "detail", "request_help"]),
                 f"实际字段={sorted(item.keys()) if item else None}；"
                 f"v1.0 应为 record_id/ts/mood/cause_category/detail/request_help")
    window.runner.wait(5000)

    # ---------------- 错误码实测（v1.0 存在的 6 个场景）--------------------
    section("④b 错误码实测（1001 / 1002 / 2001 / 2002 / 4001 走真实服务；3001 见②段）")
    # 每条都**显式写出期望的错误码**并逐条核对 —— 拒绝"只要抛错就算通过"。
    probes: List[Tuple[str, Any, Callable[[], Any], Tuple[Any, ...]]] = [
        (1001, "坏 token 访问学生接口 → 1001（未登录/过期）",
         ApiClient(server).my_profile, (date,)),
        (1002, "学生访问教师接口 → 1002（角色越界）", client.triage_list, ()),
        (2001, "缺 cause_category 提交 → 2001（message 带字段名）",
         client.submit_questionnaire, ({
             "record_id": new_id("rec_"), "mood": "down", "plain_note": None,
             "cause_category": None, "detail": None, "request_help": False,
             "consent_share": False, "consent_ts": None},)),
        (2001, "happy 但 request_help=true → 2001（矩阵第 1 行）",
         client.submit_questionnaire, ({
             "record_id": new_id("rec_"), "mood": "happy", "plain_note": None,
             "cause_category": None, "detail": None, "request_help": True,
             "consent_share": True, "consent_ts": now_iso()},)),
        (2002, "未注册的号次 → 2002（学生不存在）",
         lambda sid: ApiClient(server).login_student(sid, "x"), ("9999999",)),
        # ⚠️ 实测发现的服务端口径差异（契约把 2002 映射到 HTTP 404）：
        # 非法日期走的是 `validate_date` → `ValidationError("date")` → **2001**，
        # 不是 2002。这里按服务端**真实**口径断言 2001 并把它记在证据里，
        # 而不是把标签写成 2002 却只检查"有没有抛错"。
        (2001, "非法日期拉档案 → 2001（服务端把 date 校验失败归到 2001；见下方说明）",
         client.my_profile, ("2026-13-99",)),
    ]
    for expected, label, fn, probe_args in probes:
        result, exc = call_in_worker(app, runner, fn, *probe_args)
        if exc is None:
            REPORT.check(f"[期望 {expected}] {label}", False,
                         f"没有抛错，返回 {json.dumps(result, ensure_ascii=False)}")
            continue
        got = getattr(exc, "code", type(exc).__name__)
        REPORT.check(f"[期望 {expected}] {label}",
                     isinstance(exc, ApiError) and not exc.is_network and got == expected,
                     f"实际 {type(exc).__name__}(code={got!r}, "
                     f"field={getattr(exc, 'field', None)!r}, "
                     f"message={getattr(exc, 'message', str(exc))!r})")

    # 4001：同 token 1 分钟滚动窗口 >10 次 → 限流（契约错误码表）；happy 提交最轻量
    section("④c 4001 限流实测（同 token 连打 12 次 happy 提交）")
    codes: List[Any] = []
    for _ in range(12):
        _res, exc = call_in_worker(app, runner, client.submit_questionnaire, {
            "record_id": new_id("rec_"), "mood": "happy", "plain_note": None,
            "cause_category": None, "detail": None, "request_help": False,
            "consent_share": False, "consent_ts": None,
        }, timeout_s=10.0)
        codes.append(None if exc is None else getattr(exc, "code", type(exc).__name__))
    REPORT.check("同 token 1 分钟 >10 次提交 → 4001（契约 §2.3 限流）",
                 4001 in codes,
                 f"12 次提交的错误码序列={codes}（None = 成功；4001 出现在第 "
                 f"{codes.index(4001) + 1 if 4001 in codes else '—'} 次）")

    # ---------------- 主线程没发请求 ---------------------------------------
    snapshot = STATS.snapshot()
    REPORT.check("主线程从未调用 ApiClient 传输层（UI约定 §3/§7）",
                 snapshot["transport_calls_main_thread"] == 0,
                 f"STATS={json.dumps(snapshot, ensure_ascii=False)}；"
                 f"worker 线程名={snapshot['worker_thread_names']}")
    REPORT.check("所有网络请求都真的在 QThreadPool 线程里执行",
                 snapshot["transport_calls_worker_thread"] > 0
                 and snapshot["worker_runs"] > 0,
                 f"worker 执行 {snapshot['worker_runs']} 次，"
                 f"worker 线程上传输层调用 {snapshot['transport_calls_worker_thread']} 次")


# --------------------------------------------------------------------------- 新增段
# 下面四段对应《学生端接口协议说明》符合性核查里发现的四项缺失（本任务新增）。
# 全部用**注入式 stub 传输层**验证，不依赖真实服务，因此在
# `--skip-network` 下也会跑（这三项本来就是前端职责，不该被"服务没起"挡住）。

#: 契约 §1 时间约定：Asia/Shanghai = UTC+8（`desktop_common.api.TZ_NAME`）
_TZ_SHANGHAI = timezone(timedelta(hours=8))

#: ✅ 2026-10-02：这些键原先是"界面需要、文案表没有"的**登记缺口**（界面只能借用最接近的键）。
#: 现已由内容负责人**正式收录**进 `copywriting.md` §4.6 / §4.7，界面已改用专用键。
#: 本清单保留下来作**回归守门**：已收录的键必须继续存在，否则界面会渲染成 `⟪缺文案:…⟫`。
COLLECTED_COPY_KEYS = (
    "c.engine.notReady",            # §4.7 顶部提示条
    "c.engine.notReady.action",     # §4.7 提交被就绪闸拦下
    "c.login.studentNo.format",     # §4.6 学号真实形态示例
    "c.login.demoNote",             # §4.6 演示环境提示
    "c.login.studentNo",            # §4.6 字段名
    "c.login.action.submit",        # §4.6 登录按钮
    "c.tab.questionnaire",          # §4.6 Tab 名
    "c.tab.profile",                # §4.6 Tab 名
    "c.tab.appointment",            # §4.6 Tab 名
    "c.tab.about",                  # §4.6 Tab 名
)

#: 仍在交付报告里登记、但**尚未**被文案表收录的键（界面当前未使用，故不影响渲染）。
PENDING_COPY_KEYS = (
    "c.toast.logout",               # 登出成功提示（当前设计无此提示）
)


def _session_file() -> Path:
    return session_mod.session_file()


def _copy_present(section, code: Any) -> bool:
    """`COPY.raw(section, code)` 的键在 JSON 数据源里是否**真的存在**。

    判据必须是"数据源是否含该键"，不能拿字符串相等去判 —— 因为
    `COPY["c.error.<code>"]` 在缺键时返回的是占位符 `⟪缺文案:…⟫`（不是空串），
    用相等比较会把占位符误当成"文案正确"。

    ⚠️ 2026-10-02 修正：原实现写的是 `COPY.raw(section, str(code))`，而调用方传的
    `section` 是**元组** `("errors",)`。`CopyTable.raw` 是**变参**
    （`raw("revoke", "end_page", "title")`），于是实际查的键是 `('errors',)`
    —— **永远查不到、恒返回 False**，导致调用它的断言总是走错分支。
    现在统一把路径展开成变参。
    """
    path = tuple(section) if isinstance(section, (list, tuple)) else (section,)
    return isinstance(COPY.raw(*path, str(code)), str)


def _seed_session(token: str = "seeded-token-0123456789abcdef",
                  profile: Optional[dict] = None,
                  *, age_s: float = 0.0) -> Path:
    """往**自检专用**的登录态目录写一份 session（供要求 2/3 的用例预置状态）。"""
    path = _session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "token": token,
        "profile": profile or {"id": "stu_2023001", "name": "自检", "class_name": "高二(3)班",
                               "role": "student"},
        "saved_at": time.time() - age_s,
        "expires_in": 43200,
        "expires_at": time.time() - age_s + 43200,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def check_engine_ready(app: QtWidgets.QApplication) -> None:
    """要求 1：`engine_ready` 是数据库就绪信号 —— false 时提示 + 禁用提交，true 时恢复。"""
    section("④d 要求1：engine_ready=false → 非阻塞提示 + 禁用提交；true → 恢复")

    state: Dict[str, Any] = {"ready": True}
    posts: List[str] = []
    stub_hits: List[str] = []

    def transport(method: str, url: str, body: Optional[dict],
                  token: Optional[str], timeout: float) -> Dict[str, Any]:
        path = url.split("/api/v1", 1)[-1].split("?", 1)[0]
        stub_hits.append(f"{method} {path}")
        if method == "POST":
            posts.append(path)
        if path == "/health":
            return {"code": 0, "message": "ok", "data": {
                "status": "ok", "version": "1.0.0-stub",
                "server_time": now_iso(), "engine_ready": state["ready"]}}
        if path == "/auth/login":
            return {"code": 0, "message": "ok", "data": {
                "token": "stub-token-0123456789abcdef", "expires_in": 43200,
                "profile": {"id": "stu_2023001", "name": "自检", "class_name": "高二(3)班",
                            "role": "student"}}}
        return {"code": 0, "message": "ok", "data": {"dates": [today_str()]}}

    def build() -> StudentMainWindow:
        client = ApiClient("http://127.0.0.1:9", transport=transport)
        return StudentMainWindow("http://127.0.0.1:9", client=client,
                                 restore_session=False, health_poll_ms=60000)

    def health_into(window: StudentMainWindow, ready: bool) -> bool:
        """把 stub 的 engine_ready 设成 ready，逼一次 /health 并等回调落地。"""
        state["ready"] = ready
        window._health_worker = None            # 允许立即再投递一次
        window.check_health()
        return wait_until(app, lambda: window.health_payload.get("engine_ready") is ready,
                          timeout_s=10, label=f"health(engine_ready={ready})")

    window = build()
    window.resize(1080, 760)
    window.show()
    pump(app, 120)

    # --- 启动时就会调 health（应用里首次真正调用 /health）-------------------
    REPORT.check("启动即调用 GET /health（应用里第一次真正用它）",
                 wait_until(app, lambda: window.health_checked, timeout_s=10,
                            label="启动时的 /health"),
                 f"health_checked={window.health_checked}；"
                 f"payload={json.dumps(window.health_payload, ensure_ascii=False)}；"
                 f"本窗口实际请求记录={stub_hits[:4]}")
    REPORT.check("engine_ready=true → 无提示、提交按钮可用",
                 window.engine_ready and not window.engine_notice.isVisible()
                 and all(b.isEnabled() for b in window.questionnaire_page.submit_buttons),
                 f"engine_ready={window.engine_ready}；提示条可见="
                 f"{window.engine_notice.isVisible()}；提交按钮 enabled="
                 f"{[b.isEnabled() for b in window.questionnaire_page.submit_buttons]}")

    # --- engine_ready=false --------------------------------------------------
    ok = health_into(window, False)
    notice_text = window.engine_notice.text()
    buttons = window.questionnaire_page.submit_buttons
    REPORT.check("engine_ready=false → 非阻塞提示可见（文案来自文案表键 "
                 f"{ENGINE_NOT_READY_KEY}）",
                 ok and window.engine_notice.isVisible() and bool(notice_text)
                 and notice_text == COPY[ENGINE_NOT_READY_KEY],
                 f"提示文字={notice_text!r}；文案表[{ENGINE_NOT_READY_KEY}]="
                 f"{COPY[ENGINE_NOT_READY_KEY]!r}；提示条类={type(window.engine_notice).__name__}"
                 f"（QLabel，不是模态对话框，不阻塞填写）")
    REPORT.check("engine_ready=false → 问卷全部提交按钮被禁用",
                 not any(b.isEnabled() for b in buttons),
                 f"提交按钮 {len(buttons)} 个（平淡分支 / Q3 / 求助选择）→ "
                 f"enabled={[b.isEnabled() for b in buttons]}")
    # 高兴分支是**自动提交**路径（不点提交按钮）：直接跑一遍，必须一个请求都不发
    window.questionnaire_page.reset()
    window.questionnaire_page.show_page("q1")
    window.questionnaire_page.q1.group.set_value("happy")
    window.questionnaire_page._after_mood()
    pump(app, 80)
    REPORT.check("禁用时不再发出提交请求（防'填完整份问卷才失败'）",
                 not any("/questionnaire" in path for path in posts),
                 f"高兴分支（自动提交路径）点击后：POST 记录={posts or '无'}；"
                 f"当前页={window.questionnaire_page.current_page_id!r}；"
                 f"提交按钮(求助页)可点="
                 f"{window.questionnaire_page.help.submit_button.isEnabled()}")

    # --- 恢复 ---------------------------------------------------------------
    recovered = health_into(window, True)
    REPORT.check("engine_ready 恢复 true → 提示消失、按钮恢复可用",
                 recovered and window.engine_ready
                 and not window.engine_notice.isVisible()
                 and all(b.isEnabled() for b in window.questionnaire_page.submit_buttons),
                 f"engine_ready={window.engine_ready}；提示条可见="
                 f"{window.engine_notice.isVisible()}；提示文字={window.engine_notice.text()!r}；"
                 f"按钮 enabled={[b.isEnabled() for b in window.questionnaire_page.submit_buttons]}")

    # --- 提交前的第二道闸（按钮禁用之外的兜底）-------------------------------
    state["ready"] = False
    window.set_engine_ready(False)
    before = len([p for p in posts if "/questionnaire" in p])
    window._submit_questionnaire({"record_id": "rec_probe", "mood": "happy",
                                 "plain_note": None, "cause_category": None,
                                 "detail": None, "request_help": False,
                                 "consent_share": False, "consent_ts": None})
    pump(app, 80)
    after = len([p for p in posts if "/questionnaire" in p])
    REPORT.check("主窗口提交前再判一次 engine_ready（挡住程序化调用/自动提交分支）",
                 after == before
                 and window.questionnaire_page.not_ready_text() == COPY[NOT_READY_KEY],
                 f"POST /questionnaire/submissions 次数 {before} → {after}；"
                 f"页面文案={window.questionnaire_page.not_ready_text()!r}"
                 f"（文案表[{NOT_READY_KEY}]）")

    window.shutdown(10000)


def check_session_persistence(app: QtWidgets.QApplication) -> None:
    """要求 2：token 持久化（协议 §2.1「UI 要点：token 持久化存储」）。"""
    section("④e 要求2：token 持久化（12h，过期/损坏静默清除，新实例自动恢复）")

    session_mod.clear_session()
    # 路径本身先给证：生产路径必须是 `%LOCALAPPDATA%\MindCare\session.json`，
    # 且**不在工程目录里**。临时摘掉自检的目录覆盖来读**默认**路径（只读字符串，不落盘）。
    override = os.environ.pop(session_mod.DIR_ENV_VAR, None)
    try:
        default_dir = session_mod.session_dir()
        default_file = session_mod.session_file()
    finally:
        if override is not None:
            os.environ[session_mod.DIR_ENV_VAR] = override
    path = _session_file()
    local_appdata = (os.environ.get("LOCALAPPDATA") or "").strip()
    under_repo_default = str(default_file).lower().startswith(str(ROOT).lower())
    REPORT.check("登录态默认路径 = %LOCALAPPDATA%\\MindCare\\session.json（路径不写死、不落工程目录）",
                 default_file.name == "session.json"
                 and default_dir.name == "MindCare"
                 and (not local_appdata
                      or str(default_dir).lower().startswith(local_appdata.lower()))
                 and not under_repo_default,
                 f"session_dir() 默认={default_dir}；session_file() 默认={default_file}；"
                 f"LOCALAPPDATA={local_appdata!r}；是否位于工程目录({ROOT})下={under_repo_default}；"
                 f"本次自检实际使用（{session_mod.DIR_ENV_VAR} 覆盖）={path}")

    login_posts: List[dict] = []

    def transport(method: str, url: str, body: Optional[dict],
                  token: Optional[str], timeout: float) -> Dict[str, Any]:
        path_ = url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if path_ == "/auth/login" and method == "POST":
            login_posts.append(dict(body or {}))
            return {"code": 0, "message": "ok", "data": {
                "token": "persisted-token-0123456789abcd", "expires_in": 43200,
                "profile": {"id": str((body or {}).get("id")), "name": "自检",
                            "class_name": "高二(3)班", "role": "student"}}}
        if path_ == "/health":
            return {"code": 0, "message": "ok", "data": {
                "status": "ok", "version": "1.0.0-stub", "engine_ready": True}}
        return {"code": 0, "message": "ok", "data": {"dates": []}}

    def build(restore: bool = True) -> StudentMainWindow:
        client = ApiClient("http://127.0.0.1:9", transport=transport)
        return StudentMainWindow("http://127.0.0.1:9", client=client,
                                 restore_session=restore, health_poll_ms=60000)

    # --- 登录后确实写盘 -------------------------------------------------------
    window = build()
    window.resize(1080, 760)
    window.show()
    pump(app, 100)
    window.login_view.student_input.setText("2023001")
    window.login_view.password_input.setText("1234")
    window.login_view.enter_button.click()
    wait_until(app, lambda: window.stack.currentWidget() is window.tabs, timeout_s=15,
               label="登录（stub）")
    window.runner.wait(3000)
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    token = str(payload.get("token") or "")
    REPORT.check("登录成功后 session 文件确实写入（含 token / profile / saved_at）",
                 path.exists() and bool(token)
                 and isinstance(payload.get("profile"), dict)
                 and "saved_at" in payload and "expires_at" in payload,
                 f"路径={path}（{path.stat().st_size if path.exists() else 0} bytes）；"
                 f"token={token[:8]}…（打码，原文 {len(token)} 字符）；"
                 f"profile.id={payload.get('profile', {}).get('id')!r}；"
                 f"saved_at={payload.get('saved_at')}；expires_in={payload.get('expires_in')}；"
                 f"expires_at-saved_at={payload.get('expires_at', 0) - payload.get('saved_at', 0):.0f}s"
                 f"（契约 43200s=12h）")
    REPORT.check("号次 2023001 原样发出（v1.1 注册制：不补前缀）且带密码",
                 login_posts and login_posts[0].get("id") == "2023001"
                 and login_posts[0].get("password") == "1234",
                 f"POST /auth/login body={json.dumps(login_posts[:1], ensure_ascii=False)}；"
                 f"normalize_student_no('2023001')={normalize_student_no('2023001')!r}")
    window.shutdown(10000)
    window.close()

    # --- 模拟重启：新实例自动恢复 --------------------------------------------
    fresh = ApiClient("http://127.0.0.1:9", transport=transport)
    restarted = StudentMainWindow("http://127.0.0.1:9", client=fresh,
                                  restore_session=True, health_poll_ms=60000)
    restarted.resize(1080, 760)
    restarted.show()
    pump(app, 200)
    restored_ok = wait_until(app, lambda: restarted.session_restored, timeout_s=10,
                             label="新实例恢复登录态")
    REPORT.check("模拟重启：新 ApiClient + 新窗口 → 直接进主窗（不再弹登录页）",
                 restored_ok and restarted.stack.currentWidget() is restarted.tabs
                 and fresh.token == token and bool(fresh.profile),
                 f"session_restored={restarted.session_restored}；"
                 f"当前页={'主窗(MainTabs)' if restarted.stack.currentWidget() is restarted.tabs else '登录页'}；"
                 f"恢复的 token={str(fresh.token)[:8]}…（与文件中的一致="
                 f"{fresh.token == token}）；profile={json.dumps(fresh.profile, ensure_ascii=False)}")

    # 1001 也要能自动走：恢复出的 token 被服务端拒 → 回登录页并清文件（见要求 3 段）
    restarted.shutdown(10000)
    restarted.close()

    # --- 过期 session：静默清除 + 不抛异常 ----------------------------------
    session_mod.clear_session()
    _seed_session(age_s=43200 + 60)           # 刚过期 60s
    thrown: Optional[str] = None
    loaded: Optional[dict] = None
    try:
        loaded = ApiClient("http://127.0.0.1:9", transport=transport).load_session()
    except Exception as exc:                    # noqa: BLE001 - 就是要证明不会发生
        thrown = f"{type(exc).__name__}: {exc}"
    REPORT.check("过期 session（>12h）→ 返回 None、文件被清除、**不抛异常**",
                 loaded is None and thrown is None and not path.exists(),
                 f"age={43200 + 60}s（> expires_in=43200）；load_session()={loaded!r}；"
                 f"文件仍存在={path.exists()}；抛出异常={thrown or '无'}")

    # --- 损坏 session：静默清除 + 不抛异常 ----------------------------------
    path.parent.mkdir(parents=True, exist_ok=True)
    broken = '{"token": "half-writ'              # 半截 JSON（写到一半被杀进程）
    path.write_text(broken, encoding="utf-8")
    thrown = None
    try:
        loaded = ApiClient("http://127.0.0.1:9", transport=transport).load_session()
    except Exception as exc:                    # noqa: BLE001
        thrown = f"{type(exc).__name__}: {exc}"
    REPORT.check("损坏 session（半截 JSON）→ 返回 None、文件被清除、不抛异常",
                 loaded is None and thrown is None and not path.exists(),
                 f"文件内容={broken!r}；load_session()={loaded!r}；"
                 f"文件仍存在={path.exists()}；抛出异常={thrown or '无'}")

    # --- 关闭持久化（session_path=False）时，登录成功一刻不得抛异常 --------------
    # 回归用例：`False` 曾被当成"路径"传进 `Path()` → 登录成功但 worker 抛 TypeError，
    # 表现为"token 有了却停在登录页"（实测踩过：联调段 `① 登录` 失败）。
    nopersist = ApiClient("http://127.0.0.1:9", transport=transport,
                          session_path=False)
    thrown = None
    saved = None
    try:
        nopersist.login_student("2023001", "1234")  # 号次原样发送 + 密码
        saved = nopersist.save_session()
    except Exception as exc:                        # noqa: BLE001 - 就是要证明不会发生
        thrown = f"{type(exc).__name__}: {exc}"
    REPORT.check("session_path=False（关闭持久化）→ 登录/写盘都不抛异常、不落文件",
                 thrown is None and nopersist.session_path is None
                 and saved is False and bool(nopersist.token)
                 and not path.exists(),
                 f"session_path={nopersist.session_path!r}；token="
                 f"{str(nopersist.token)[:8]}…；save_session()={saved}；"
                 f"抛出异常={thrown or '无'}；session 文件仍存在={path.exists()}")
    session_mod.clear_session()

    # --- 登出入口 -----------------------------------------------------------
    _seed_session(token="logout-token-0123456789abcde")
    out = build(restore=True)
    out.resize(1080, 760)
    out.show()
    pump(app, 150)
    had_token = bool(out.client.token)
    out.about_page.logout_button.click()
    pump(app, 120)
    REPORT.check("登出入口（关于页）→ 清内存 token + 删 session 文件 + 回登录页",
                 had_token and not out.client.token and not path.exists()
                 and out.stack.currentWidget() is out.login_view,
                 f"登出前 token={had_token}；登出后 client.token={out.client.token!r}；"
                 f"session 文件仍存在={path.exists()}；"
                 f"当前页={'登录页' if out.stack.currentWidget() is out.login_view else '其它'}")
    REPORT.check("登出后登录框清空（不再把 stu_ 前缀的 id 当号次再登录，问题 5）",
                 out.login_view.student_input.text() == ""
                 and out.login_view.password_input.text() == "",
                 f"号次框={out.login_view.student_input.text()!r}；"
                 f"密码框={out.login_view.password_input.text()!r}")
    out.shutdown(10000)
    out.close()
    session_mod.clear_session()


def check_session_expiry_1001(app: QtWidgets.QApplication) -> None:
    """要求 3：`1001`（未登录 / token 过期）→ 清 token + 清 session + 跳登录页。

    ⚠️ 用**注入式 stub**，不依赖真实服务：真实服务端要造"token 过期"得等 12h
    （协议 §2.1 `expires_in=43200`），stub 注入是唯一能在自检里覆盖它的办法。
    """
    section("④f 要求3：code=1001 跳登录；其它错误码留在当前页（stub 注入）")

    code_box: Dict[str, Any] = {"code": 1001}
    rejected: List[str] = []

    def transport(method: str, url: str, body: Optional[dict],
                  token: Optional[str], timeout: float) -> Dict[str, Any]:
        path_ = url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if path_ == "/health":
            return {"code": 0, "message": "ok", "data": {
                "status": "ok", "version": "1.0.0-stub", "engine_ready": True}}
        if path_ == "/auth/login":
            return {"code": 0, "message": "ok", "data": {
                "token": "stub-1001-token-0123456789ab", "expires_in": 43200,
                "profile": {"id": "stu_2023001", "name": "自检",
                            "class_name": "高二(3)班", "role": "student"}}}
        if path_ == "/profile/me/dates":
            # 日期列表**正常返回**：2001 那一组要把错误落在"拉档案"这一条上，
            # 否则错误会被 dates 的返回覆盖掉（实测踩过）。
            return {"code": 0, "message": "ok", "data": {"dates": [today_str()]}}
        rejected.append(path_)
        return {"code": code_box["code"],
                "message": "字段 token 校验失败：未登录或 token 过期", "data": None}

    def build(restore: bool = True) -> StudentMainWindow:
        """建窗并**等所有异步请求落地**（`runner.wait` 只等线程池，信号还要事件循环派发）。

        ⚠️ 不等的话，上一段残留的 worker 会在下一段断言之间派发，表现为随机失败
        （实测踩过：[2001] 段偶发看到登录页 —— 根因是**上一段窗口的 `/profile/me`
        还挂在线程池里，用当时还没改写的 `code_box` 值拿到 1001**，把这一段的
        窗口一起带进了登录页）。
        """
        client = ApiClient("http://127.0.0.1:9", transport=transport)
        w = StudentMainWindow("http://127.0.0.1:9", client=client,
                              restore_session=restore, health_poll_ms=60000)
        w.resize(1080, 760)
        w.show()
        pump(app, 200)
        w.runner.wait(8000)
        pump(app, 150)
        return w

    def quiesce(w: StudentMainWindow) -> None:
        """把窗口的未决请求彻底排空（线程池 + 事件循环各来一轮）。"""
        w.runner.wait(8000)
        pump(app, 200)
        w.runner.wait(8000)
        pump(app, 150)

    # --- 1001：跳登录 -------------------------------------------------------
    _seed_session(token="expired-token-0123456789abcdef")
    path = _session_file()
    w = build()
    on_main = w.stack.currentWidget() is w.tabs
    w.treehole_page.show_error("残留文案：应被清掉")
    w.profile_page.show_error("残留文案：应被清掉")
    code_box["code"] = 1001
    w._load_profile_dates()                     # GET /profile/me/dates → 1001
    went_login = wait_until(app, lambda: w.stack.currentWidget() is w.login_view,
                            timeout_s=10, label="1001 → 登录页")
    pump(app, 100)
    REPORT.check("[1001] 恢复出的 token 被服务端拒 → 清除内存 token + 清 session 文件",
                 went_login and not w.client.token and not path.exists(),
                 f"请求过的路径={rejected[-1:] or '无'}；client.token={w.client.token!r}；"
                 f"session 文件仍存在={path.exists()}；"
                 f"session_restored={w.session_restored}")
    # ⚠️ 2026-10-02 修正（原断言逻辑相反，会产生**假红**）：
    #   原写法是 `text == COPY[...] if _copy_present(...) else text != COPY[...]`，
    #   即"JSON 里没有该键时要求提示文案**不等于**文案表" —— 这与本条用例的意图
    #   （**显示可读提示**）正好相反，是个逻辑反转。当时的设想是"缺键环境下
    #   COPY 会返回占位符 ⟪缺文案:…⟫，所以要防住把它当正确"，但 `c.error.1001`
    #   同时存在于 md 生成表与 JSON 的 errors 块，`COPY[...]` 返回的是**真实文案**，
    #   于是反转分支把正确行为判成了失败。
    #   现改为直接、正向地表达要求，并对占位符单独设防。
    hint = w.login_view.error_label.text()
    on_login = w.stack.currentWidget() is w.login_view
    hint_visible = w.login_view.error_label.isVisible()
    hint_readable = bool(hint) and "⟪缺文案" not in hint
    hint_is_canonical = hint == COPY["c.error.1001"]
    REPORT.check("[1001] 切回登录页并显示可读提示（等于文案表 c.error.1001）",
                 went_login and on_login and hint_visible and hint_readable and hint_is_canonical,
                 f"went_login={went_login}；当前页={'登录页' if on_login else '其它'}；"
                 f"提示可见={hint_visible}；提示={hint!r}；可读(非占位符)={hint_readable}；"
                 f"等于文案表={hint_is_canonical}；文案表[c.error.1001]={COPY['c.error.1001']!r}；"
                 f"档案页残留文案已清="
                 f"{not w.profile_page.error_label.isVisible()}（进主窗前在={on_main}）")
    # 问卷提交失败也走同一条路径：造一个 ApiError(1001) 直接喂给回调
    w.show_main()
    _seed_session(token="t" * 24)
    w.client.token = None
    had_session = w.client.load_session() is not None
    w._on_submit_failed(ApiError(1001, "token 过期", "/questionnaire/submissions"))
    quiesce(w)                                  # 排空 w 的所有请求，别污染下一段
    REPORT.check("[1001] 问卷提交失败走同一条路径（_on_submit_failed → handle_failure）",
                 had_session and w.stack.currentWidget() is w.login_view
                 and not path.exists() and not w.client.token,
                 f"预置 session 恢复成功={had_session}；"
                 f"构造 ApiError(1001) 喂给 _on_submit_failed → "
                 f"当前页={'登录页' if w.stack.currentWidget() is w.login_view else '其它'}；"
                 f"session 文件仍存在={path.exists()}；client.token={w.client.token!r}")

    # --- 2001：留在当前页 ---------------------------------------------------
    # ⚠️ 这一段的窗口用 `restore_session=False` 建：**不让它在构造期自动发请求**，
    # 否则构造期的请求会和 `code_box` 的改写抢时序（实测踩过：构造期的
    # `/profile/me` 拿到改写**之前**的 1001，把窗口带进了登录页）。
    # 改为显式 `try_restore_session()`，并让 `/profile/me/dates` 走**成功**分支，
    # 只把 2001 落在 `/profile/me` 上 —— 断言的就是"拉档案失败留在当前页"。
    _seed_session(token="keep-token-0123456789abcdef")
    path = _session_file()
    code_box["code"] = 2001
    w2 = build(restore=False)
    ok = w2.try_restore_session()
    quiesce(w2)
    # 切到档案页并**再拉一次**：2001 必须只把错误写在本页、且停在主窗
    # （`w2.tabs.setCurrentWidget` 是「留在当前页」这条断言里的"当前页"定义）
    w2.tabs.setCurrentWidget(w2.profile_page)
    w2._load_profile(today_str())               # GET /profile/me → 2001（stub）
    wait_until(app, lambda: w2.profile_page.error_label.isVisible(), timeout_s=10,
               label="2001 → 档案页错误")
    quiesce(w2)
    REPORT.check("[2001] 不跳登录：留在主窗、session 文件与 token 都保留",
                 ok and w2.stack.currentWidget() is w2.tabs
                 and path.exists() and bool(w2.client.token),
                 f"当前页={'主窗' if w2.stack.currentWidget() is w2.tabs else '登录页'}；"
                 f"session 文件仍存在={path.exists()}；client.token="
                 f"{str(w2.client.token)[:8]}…；"
                 f"档案页错误={w2.profile_page.error_label.text()!r}"
                 f"（期望文案表[c.error.2001]={COPY['c.error.2001']!r}）")
    REPORT.check("[2001] 错误只显示在当前页（不误报成登录过期）",
                 w2.tabs.currentWidget() is w2.profile_page
                 and w2.profile_page.error_label.isVisible()
                 and bool(w2.profile_page.error_label.text())
                 and not w2.login_view.error_label.isVisible(),
                 f"档案页（当前 Tab）={'显示' if w2.profile_page.error_label.isVisible() else '隐藏'}"
                 f"（{w2.profile_page.error_label.text()!r}）；"
                 f"登录页提示={w2.login_view.error_label.text()!r}"
                 f"（可见={w2.login_view.error_label.isVisible()}，"
                 f"文案表[c.error.1001]={COPY['c.error.1001']!r}）")

    # --- 2002 / 3001 / 网络层也都不跳 ---------------------------------------
    for probe_code in (2002, 3001, "network"):
        _seed_session(token="keep2-token-0123456789abcde")
        code_box["code"] = probe_code
        w3 = build(restore=False)
        w3.try_restore_session()
        quiesce(w3)
        err = ApiError(probe_code, "stub", "/profile/me")
        jumped = w3.handle_failure(err)
        REPORT.check(f"[{probe_code}] 不跳登录（只有 1001 才跳）",
                     not jumped and w3.stack.currentWidget() is w3.tabs
                     and _session_file().exists(),
                     f"handle_failure(ApiError({probe_code!r})) → {jumped}；"
                     f"当前页={'主窗' if w3.stack.currentWidget() is w3.tabs else '登录页'}；"
                     f"session 文件仍存在={_session_file().exists()}")
        w3.shutdown(8000)
        w3.close()
        session_mod.clear_session()

    w.shutdown(10000)
    w.close()
    w2.shutdown(10000)
    w2.close()
    session_mod.clear_session()


def check_student_no_prefix(app: QtWidgets.QApplication,
                            main_window: Optional[StudentMainWindow] = None) -> None:
    """要求 5（v1.1 注册制）：号次原样发送 + 密码随登录发送（不做前缀补全）。"""
    section("④g 要求5：号次原样 + 密码登录（2023001 → 2023001，不补 stu_）")

    cases = [
        ("2023001", "2023001", "纯数字 → 原样（不补前缀）"),
        ("stu_2023001", "stu_2023001", "已带 stu_ → 原样"),
        ("abc", "abc", "含字母 → 原样"),
        ("", "", "空 → 空"),
    ]
    rows = [f"{raw!r} → {normalize_student_no(raw)!r}" for raw, _e, _w in cases]
    ok = all(normalize_student_no(raw) == expected for raw, expected, _w in cases)
    REPORT.check("normalize_student_no() 四条用例全部符合预期（仅去空白，不补前缀）", ok,
                 "；".join(rows))

    # 真的走一次登录框：断言**实际发出的 id** 原样、且带密码
    login_posts: List[dict] = []

    def transport(method: str, url: str, body: Optional[dict],
                  token: Optional[str], timeout: float) -> Dict[str, Any]:
        path_ = url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if path_ == "/auth/login":
            login_posts.append(dict(body or {}))
            return {"code": 0, "message": "ok", "data": {
                "token": "prefix-token-0123456789abcdef", "expires_in": 43200,
                "profile": {"id": str((body or {}).get("id")), "name": "自检",
                            "class_name": "高二(3)班", "role": "student"}}}
        if path_ == "/health":
            return {"code": 0, "message": "ok", "data": {
                "status": "ok", "version": "1.0.0-stub", "engine_ready": True}}
        return {"code": 0, "message": "ok", "data": {"dates": []}}

    def login_with(text: str):
        client = ApiClient("http://127.0.0.1:9", transport=transport)
        w = StudentMainWindow("http://127.0.0.1:9", client=client,
                              restore_session=False, health_poll_ms=60000)
        w.resize(1080, 760)
        w.show()
        pump(app, 80)
        w.login_view.student_input.setText(text)
        w.login_view.password_input.setText("1234")
        w.login_view.enter_button.click()
        wait_until(app, lambda: w.stack.currentWidget() is w.tabs, timeout_s=15,
                   label=f"登录 {text!r}")
        sent = str(login_posts[-1].get("id")) if login_posts else None
        sent_pwd = str(login_posts[-1].get("password")) if login_posts else None
        w.shutdown(10000)
        w.close()
        return sent, sent_pwd

    sent_digits, pwd_digits = login_with("2023001")
    sent_prefixed, _ = login_with("stu_2023001")
    sent_letters, _ = login_with("abc")
    REPORT.check("登录框实测：2023001 → 原样发出 id=2023001 且 password=1234",
                 sent_digits == "2023001" and pwd_digits == "1234",
                 f"输入 '2023001' → body.id={sent_digits!r}，body.password={pwd_digits!r}")
    REPORT.check("登录框实测：stu_2023001 → 原样发出（无二次补前缀）",
                 sent_prefixed == "stu_2023001",
                 f"输入 'stu_2023001' → body.id={sent_prefixed!r}")
    REPORT.check("登录框实测：abc → 原样发出 abc",
                 sent_letters == "abc",
                 f"输入 'abc' → body.id={sent_letters!r}")

    # 提示文字：占位符/说明必须体现号次形态，且**不写死中文**
    probe = StudentMainWindow("http://127.0.0.1:9",
                              client=ApiClient("http://127.0.0.1:9",
                                               transport=transport,
                                               session_path=False),
                              restore_session=False, health_poll_ms=60000)
    placeholder = probe.login_view.student_input.placeholderText()
    hint_text = probe.login_view.student_format_hint.text()
    tooltip = probe.login_view.student_input.toolTip()
    REPORT.check("登录页占位符/说明体现号次形态（来自文案表，无硬编码中文）",
                 bool(placeholder) and placeholder == COPY["c.login.studentNo"]
                 and bool(hint_text) and hint_text == COPY["c.login.studentNo.format"]
                 and tooltip == COPY["c.login.studentNo.format"],
                 f"占位符={placeholder!r}（键 c.login.studentNo）；"
                 f"提示行={hint_text!r}（键 c.login.studentNo.format）；"
                 f"tooltip={tooltip!r}；"
                 f"注册提示={COPY['c.login.demoNote']!r}（键 c.login.demoNote）")
    probe.shutdown(8000)
    probe.close()


def check_ts_human(app: QtWidgets.QApplication) -> None:
    """要求 4：时间戳人类可读化（单一格式化函数 + 两处显示点）。"""
    section("④h 要求4：时间戳人类可读（format_ts_human 单点 + 两处显示点）")

    iso = "2026-10-02T21:40:00+08:00"
    out = format_ts_human(iso)
    REPORT.check("format_ts_human('2026-10-02T21:40:00+08:00') 不含 'T' 与 '+08:00'，含'月'与时间",
                 ("T" not in out) and ("+08:00" not in out)
                 and ("月" in out) and (":" in out),
                 f"{iso!r} → {out!r}")
    # 按 Asia/Shanghai 显示，与本机时区无关（同一时刻的 UTC 写法 → 同一结果）
    same_moment_utc = "2026-10-02T13:40:00+00:00"
    same_moment_z = "2026-10-02T13:40:00Z"
    REPORT.check("同一时刻的不同写法 → 同一（Asia/Shanghai）结果，不受本机时区影响",
                 format_ts_human(same_moment_utc) == format_ts_human(iso)
                 and format_ts_human(same_moment_z) == format_ts_human(iso),
                 f"+08:00 写法={format_ts_human(iso)!r}；"
                 f"+00:00 写法={format_ts_human(same_moment_utc)!r}；"
                 f"Z 写法={format_ts_human(same_moment_z)!r}")
    # 边界：刚刚记录的 `now_iso()`（= 今天、同一天）也必须是"月日 + 时间"的同一套写法，
    # 不能因为"是今天"就换成另一种格式（统一性断言，防"今天/往日两套写法"回归）
    just_now = now_iso()
    REPORT.check("刚刚记录的时间戳（今天）也用同一套『M月D日 HH:MM』写法",
                 "月" in format_ts_human(just_now) and "T" not in format_ts_human(just_now)
                 and len(format_ts_human(just_now)) <= 14,
                 f"now_iso()={just_now!r} → {format_ts_human(just_now)!r}"
                 f"（对比 2026-10-02T21:40:00+08:00 → {out!r}）")
    # 不同天也用同一套写法（不存在"往日才带日期"的分支）
    other_day = datetime(2026, 9, 15, 21, 40, tzinfo=_TZ_SHANGHAI)
    REPORT.check("今天与往日用**同一套**写法（M月D日 HH:MM），同一列表内可直接扫读",
                 format_ts_human(other_day.isoformat()) == "9月15日 21:40"
                 and len(format_ts_human(iso)) == len(format_ts_human(other_day.isoformat())),
                 f"今天样例（2026-10-02）={out!r}；"
                 f"往日样例（{other_day.isoformat()}）="
                 f"{format_ts_human(other_day.isoformat())!r}；"
                 f"长度一致={len(format_ts_human(iso)) == len(format_ts_human(other_day.isoformat()))}"
                 f"（两次都是两位数日号）")

    bad_inputs = (None, "", "not-a-ts", "2026-13-99T00:00:00+08:00", 20261002, {})
    results: List[str] = []
    thrown: Optional[str] = None
    try:
        for value in bad_inputs:
            results.append(repr(format_ts_human(value)))
    except Exception as exc:                    # noqa: BLE001 - 就是要证明不会发生
        thrown = f"{type(exc).__name__}: {exc}"
    REPORT.check("异常输入（None / '' / 'not-a-ts' / 非法日期 / 非字符串）不抛异常",
                 thrown is None,
                 f"输入 {list(bad_inputs)} → 输出 {results}；抛出异常={thrown or '无'}")

    # --- 两处显示点：渲染文本里不再出现 +08:00 ------------------------------
    demo = "2026-10-02T21:40:00+08:00"
    window = StudentMainWindow(
        "http://127.0.0.1:9",
        client=ApiClient("http://127.0.0.1:9", session_path=False),
        restore_session=False, health_poll_ms=60000)
    window.resize(1080, 760)
    window.show()
    pump(app, 120)

    window.treehole_page.set_entries([
        {"entry_id": "tre_tsprobe", "ts": demo, "content": "自检：树洞时间显示", "mood_tag": None},
    ])
    window.profile_page.set_profile({"date": "2026-10-02", "submissions": [
        {"record_id": "rec_tsprobe", "ts": demo, "mood": "down",
         "cause_category": "study", "detail": "自检：档案时间显示", "request_help": False},
    ]})
    pump(app, 100)
    tree_labels = [w.text() for w in window.treehole_page.rows()[0].findChildren(QtWidgets.QLabel) if w.text()]
    list_text = " | ".join(tree_labels)
    row_widgets = [w for w in window.profile_page.rows()[0].findChildren(QtWidgets.QLabel)]
    row_texts = [w.text() for w in row_widgets if w.text()]
    joined = " | ".join([list_text] + row_texts)
    REPORT.check("树洞列表渲染文本不再出现 '+08:00'（改为人类可读）",
                 "+08:00" not in list_text and "T21" not in list_text
                 and format_ts_human(demo) in list_text,
                 f"渲染文本={list_text!r}；含易读格式={format_ts_human(demo)!r} → "
                 f"{format_ts_human(demo) in list_text}")
    REPORT.check("档案记录行渲染文本不再出现 '+08:00'（改为人类可读）",
                 "+08:00" not in joined and format_ts_human(demo) in row_texts,
                 f"该行标签={row_texts}；含易读格式={format_ts_human(demo)!r}")
    window.shutdown(10000)
    window.close()


def check_profile_refresh_after_submit(app: QtWidgets.QApplication) -> None:
    """提交后档案自动刷新：同一天连续提交时，日期列表不变，仍要重拉当天档案。

    回归守门（问题 3）：原实现提交成功后只调 `_load_profile_dates()`，而
    `ProfileTab.set_dates()` 在「日期列表没变」时会跳过重拉 —— 导致同一天第二次
    提交后，档案里看不到新记录（看起来"每次只有一条记录"）。修复后按服务端回执的
    `date` 显式重拉，保证每次提交都能进档案。
    """
    section("④k 提交后档案自动刷新（同一天连续提交也重拉）")
    profile_fetches: List[str] = []

    def transport(method: str, url: str, body: Optional[dict],
                  token: Optional[str], timeout: float) -> Dict[str, Any]:
        path_ = url.split("/api/v1", 1)[-1].split("?", 1)[0]
        if path_ == "/health":
            return {"code": 0, "message": "ok", "data": {
                "status": "ok", "version": "1.0.0-stub", "engine_ready": True}}
        if path_ == "/profile/me/dates":
            return {"code": 0, "message": "ok", "data": {"dates": [today_str()]}}
        if path_ == "/profile/me":
            profile_fetches.append(url)
            return {"code": 0, "message": "ok", "data": {
                "date": today_str(), "submissions": [{
                    "record_id": "rec_refresh_probe", "ts": now_iso(), "mood": "happy",
                    "cause_category": None, "detail": None, "request_help": False}],
                "treehole": []}}
        return {"code": 0, "message": "ok", "data": {}}

    client = ApiClient("http://127.0.0.1:9", transport=transport, session_path=False)
    window = StudentMainWindow("http://127.0.0.1:9", client=client,
                               restore_session=False, health_poll_ms=60000)
    window.resize(1080, 760)
    window.show()
    pump(app, 100)
    # 预置日期列表为「今天」，模拟当天已经提交过一次（日期列表不再变化）
    window.profile_page.set_dates([today_str()])
    wait_until(app, lambda: len(profile_fetches) >= 1, timeout_s=10,
               label="首次进入档案的 /profile/me")
    before = len(profile_fetches)

    # 第二次提交（同一天）：日期列表不变，但仍必须重拉当天档案
    window._on_submit_ok({"record_id": "rec_refresh_2", "date": today_str(),
                          "result_scene": "happy_end"})
    refreshed = wait_until(app, lambda: len(profile_fetches) > before,
                           timeout_s=10, label="提交后重拉 /profile/me")
    REPORT.check("同一天连续提交后档案被重新拉取（不因日期列表未变而跳过）",
                 refreshed,
                 f"提交前 /profile/me 请求 {before} 次，提交后 {len(profile_fetches)} 次")
    window.shutdown(10000)
    window.close()


def check_appointment_mine_sync(app: QtWidgets.QApplication) -> None:
    """教师代订 → 学生端课表同步（问题 4）。

    学生端课表用 `RemoteSchedule(fetch_mine=True)` 轮询 `GET /appointments/mine`，
    把「本人已预约」的格子（含教师代订）刷成绿框。这里用注入式 stub 直接驱动
    `_fetch` + `_apply`，断言 mine 快照里出现了教师代订的 slot。
    """
    section("④l 教师代订 → 学生端课表同步（RemoteSchedule.fetch_mine）")

    class _StubClient:
        def list_blocks(self) -> dict:
            return {"slots": []}

        def list_appointments(self, date=None) -> dict:
            return {"items": []}

        def list_my_appointments(self) -> dict:
            return {"items": [
                {"apt_id": "apt_teacher", "slot": "2026-10-06#1",
                 "status": "scheduled"},
            ]}

    remote = RemoteSchedule(_StubClient(), None,
                            fetch_appointments=False, fetch_mine=True)
    blocks, appointments, mine = remote._fetch(
        remote._client, remote._fetch_appointments, remote._fetch_mine)
    remote._apply(blocks, appointments, mine)
    REPORT.check("学生端从 /appointments/mine 同步出教师代订的格子",
                 "2026-10-06#1" in remote.mine_slots(),
                 f"mine_slots()={sorted(remote.mine_slots())}；"
                 f"fetch_mine={remote._fetch_mine}；"
                 f"教师代订 slot=2026-10-06#1")


def check_suggested_copy_keys() -> None:
    """文案表键的**收录状态与回归守门**。

    2026-10-02：原先这段断言的是"建议新增的键**确实缺失**"（界面只能借用最接近的键）。
    这些键已被正式收录进 `copywriting.md`，所以断言方向反过来：**已收录的必须继续存在**。
    仍待收录的键单列在 `PENDING_COPY_KEYS`（界面未使用，不影响渲染）。
    """
    section("④i 文案表键：已收录键的回归守门 + 待收录清单")
    missing = [k for k in COLLECTED_COPY_KEYS if not COPY.has(k)]
    REPORT.check("已正式收录的文案键都仍在文案表里（回归守门，防被误删）",
                 not missing,
                 f"已收录 {len(COLLECTED_COPY_KEYS)} 条；缺失={missing or '无'}；"
                 f"待收录={list(PENDING_COPY_KEYS)}")
    REPORT.check("界面用到的键都真实存在（不会渲染成『⟪缺文案:…⟫』）",
                 COPY.has(ENGINE_NOT_READY_KEY) and COPY.has(NOT_READY_KEY)
                 and COPY.has("c.login.studentNo.format")
                 and COPY.has("c.login.demoNote") and COPY.has("c.action.logout")
                 and all(COPY.has(k) for k in ("c.error.1001", "c.error.2001")),
                 f"{ENGINE_NOT_READY_KEY!r}={COPY[ENGINE_NOT_READY_KEY]!r}；"
                 f"{NOT_READY_KEY!r}={COPY[NOT_READY_KEY]!r}；"
                 f"c.login.studentNo.format={COPY['c.login.studentNo.format']!r}")


def check_appointments_storage() -> None:
    """预约时间本地库（`desktop_common.appointments`）的存储纪律冒烟测试。

    用独立临时目录验证（`MINDCAKE_APPOINTMENT_DIR` 已隔离，绝不碰真实用户目录）：
    * 记录字段齐全：`apt_id`（前缀 `apt_`）/ 预约人 / 班级 / 年 / 月 / 日 / 时间 /
      两个分享布尔 / `created_ts`；
    * JSON Lines 逐行追加；坏行跳过、空记录不写（坏数据不崩、宁可缺一条）。
    """
    section("④j 预约时间本地库：JSON Lines 存储纪律")
    with tempfile.TemporaryDirectory(prefix="apt-selfcheck-") as tmp:
        path = Path(tmp) / "appointments.jsonl"
        record = appt_mod.build_appointment_record(
            student_id="stu_2023001", name="小明", class_name="初二(3)班",
            appointment={"year": "2026", "month": "10", "day": "3", "period": "7",
                         "time": "15:11", "share_questionnaire": True,
                         "share_treehole": False},
        )
        # v1.1 追加了 period / weekday / 起止钟点 / slot 四个课表定位字段，
        # 但 v1.0 那 11 个字段**一个没动**（键名、类型、取值口径全保留）。
        V1_0_FIELDS = {
            "apt_id", "student_id", "name", "class_name", "year", "month", "day",
            "time", "share_questionnaire", "share_treehole", "created_ts",
        }
        REPORT.check("build_appointment_record 组装出契约字段（v1.0 的 11 个一个不少）",
                     record is not None and V1_0_FIELDS <= set(record),
                     json.dumps(record, ensure_ascii=False, sort_keys=True))
        REPORT.check("v1.1 追加课表定位：period / weekday / time_start / time_end / slot",
                     record is not None
                     and record.get("period") == "7"
                     and record.get("weekday") == str(
                         sch_mod.weekday_from_date(2026, 10, 3))
                     and record.get("time_start") == "15:11"
                     and record.get("time_end") == "16:00"
                     and record.get("slot") == "2026-10-03#7",
                     f"period={record.get('period')} weekday={record.get('weekday')} "
                     f"{record.get('time_start')}-{record.get('time_end')} "
                     f"slot={record.get('slot')}")
        ok_append = appt_mod.append_appointment(record, path=path)
        back = appt_mod.list_appointments(path=path)
        REPORT.check("append → list 一条预约可读回，字段与 ID 前缀一致",
                     ok_append and len(back) == 1
                     and back[0]["apt_id"] == record["apt_id"]
                     and str(back[0]["apt_id"]).startswith("apt_")
                     and back[0]["student_id"] == "stu_2023001",
                     json.dumps(back, ensure_ascii=False))
        # 空/None 记录不写；坏行跳过（不因一行坏数据丢整库）
        assert appt_mod.append_appointment(None, path=path) is False
        with path.open("a", encoding="utf-8") as handle:
            handle.write("{这不是一行合法 JSON\n")
        record2 = appt_mod.build_appointment_record(
            student_id="stu_2023002", name="", class_name=None,
            appointment={"year": "2026", "month": "10", "day": "4", "time": "09:00",
                         "share_questionnaire": False, "share_treehole": True},
        )
        appt_mod.append_appointment(record2, path=path)
        again = appt_mod.list_appointments(path=path)
        REPORT.check("坏行跳过 + 空记录不写（坏数据不崩、宁可缺）",
                     len(again) == 2 and all(isinstance(x, dict) for x in again),
                     json.dumps(again, ensure_ascii=False))


def _hardcoded_chinese_scan() -> Tuple[bool, str]:
    """抽查关键页面：中文界面文案是否都来自 `COPY`。

    做法：**AST 扫描**（不是 grep），两步判定，避免误报：

    1. 收集所有"会进入界面"的中文字面量 —— 即出现在
       `make_label/make_title/make_hint/make_body/make_button/...`、
       `QLabel(...)`、`QPushButton(...)`、`setText/setPlaceholderText` 等
       **用户可见入口**里的字符串常量；
    2. 报告其中**不在允许清单**里的项（允许清单 = 主题色值、字体名等非文案常量）。

    这样既不会把 docstring/注释算进来，也不会把模块级常量（如树洞的 `VISIBILITY`）
    算进来。
    """
    import ast

    target_dir = Path(__file__).resolve().parents[1]
    files = [
        target_dir / "ui" / "pages.py",
        target_dir / "ui" / "questionnaire.py",
        target_dir / "ui" / "treehole.py",
        target_dir / "ui" / "profile.py",
        target_dir / "ui" / "mood_chart.py",
        target_dir / "app" / "main.py",
        target_dir / "app" / "worker.py",
        ROOT / "desktop_common" / "widgets.py",
        ROOT / "desktop_common" / "theme.py",
        ROOT / "desktop_common" / "api.py",
    ]
    #: 会把第一个字符串参数当"界面文字"的调用名
    ui_entry_names = {
        "make_label", "make_title", "make_heading", "make_body", "make_hint",
        "make_error", "make_badge", "make_button", "make_primary_button",
        "make_ghost_button", "make_choice_button", "hotline_label", "Card",
        "QLabel", "QPushButton", "QLineEdit", "QListWidgetItem", "setText",
        "setPlaceholderText", "setWindowTitle", "setToolTip",
        "ResultPage", "TextArea", "ChoiceGroup", "ToggleRow",
    }
    #: 允许的非文案中文（主题色值、字体名等）
    allowed_substrings = (
        "Microsoft YaHei", "PingFang SC", "Segoe UI", "MindCare",
        "⟪缺文案",
    )
    suspicious: List[str] = []
    visible_literals = 0
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name not in ui_entry_names:
                continue
            args = list(node.args) + [kw.value for kw in node.keywords]
            for arg in args[:2]:
                if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                    continue
                value = arg.value
                if len(value) < 2:
                    continue
                if not any("\u4e00" <= ch <= "\u9fff" for ch in value):
                    continue
                visible_literals += 1
                if any(token in value for token in allowed_substrings):
                    continue
                suspicious.append(f"{path.name}:{arg.lineno}: {value!r}")
    return (not suspicious), (
        f"AST 扫描 {len(files)} 个文件，命中『会进入界面』的中文字面量 "
        f"{visible_literals} 个 → 非文案来源的可疑项 {len(suspicious)} 个"
        + ("；" + "；".join(suspicious[:12]) if suspicious else "")
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m student_desktop.app.selfcheck")
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--student-no", default="2023001",
                        help="注册制号次（首次联调会先自动注册该号次）")
    parser.add_argument("--skip-network", action="store_true",
                        help="不起真实联调（mock server 未启动时用）")
    args = parser.parse_args(argv)

    print("MindCare 学生端自检（offscreen，契约 v1.0）")
    print(f"  工程根 : {ROOT}")
    print(f"  截图目录: {SHOT_DIR}")
    print(f"  契约端点: {len(CONTRACT_ENDPOINTS_V1_0)} 个"
          f"（v1.0；结果页 {len(RESULT_SCENES)} 个值）")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    theme.install_fonts(app)
    theme.apply_theme(app)
    window: Optional[StudentMainWindow] = None

    try:
        check_environment()
        check_api_client()
        window = check_ui(app, args.server)

        section("③c 硬编码中文抽查（关键页面）")
        ok, evidence = _hardcoded_chinese_scan()
        REPORT.check("关键页面无硬编码中文界面文案（文案均来自 COPY）", ok, evidence)

        # ---- v1.0 协议符合性新增的四项（全部用注入式 stub，不依赖真实服务）----
        # 放在 `check_integration` **之前**：它们测的是前端职责（就绪信号 / 登录态 /
        # 错误码分诊 / 时间显示），不该被"mock server 没起"挡住。
        check_engine_ready(app)          # 要求 1
        check_session_persistence(app)   # 要求 2
        check_session_expiry_1001(app)   # 要求 3
        check_student_no_prefix(app)     # 要求 5
        check_ts_human(app)              # 要求 4
        check_profile_refresh_after_submit(app)   # 问题3：提交后档案自动刷新
        check_appointment_mine_sync(app)          # 问题4：教师代订 → 学生端同步
        check_suggested_copy_keys()
        check_appointments_storage()

        if not args.skip_network:
            check_integration(app, window, args.server, args.student_no)
        else:
            print("\n（--skip-network：跳过真实联调）")
    except Exception:                                  # noqa: BLE001
        REPORT.check("自检过程中未抛出未捕获异常", False, traceback.format_exc())
    finally:
        if window is not None:
            # 收尾：等所有后台 worker 结束，避免 Qt 在退出时报"仍在运行的 QThread"
            drained = window.shutdown(15000)
            print(f"\n后台 worker 收尾：{'全部结束' if drained else '仍有未结束的 worker'}")
        section("自检结果")
        print(REPORT.summary())
        files = sorted(SHOT_DIR.glob("*.png"))
        print(f"\n截图 {len(files)} 张（{SHOT_DIR}）：")
        for path in files:
            print(f"  {path.name:38s} {path.stat().st_size:>9d} bytes")
        write_evidence(files)

    return 1 if REPORT.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
