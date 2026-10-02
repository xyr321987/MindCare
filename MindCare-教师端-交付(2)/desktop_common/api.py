"""HTTP 契约客户端（`docs/UI约定.md` §3；契约 `contracts/api-contract.json`）。

设计约束（逐条来自 UI约定 §3）：

* **信封解包**：所有响应是 `{code, message, data}`；`code != 0` 一律抛
  `ApiError(code, message, path)`。
* **网络失败不得静默吞掉**：`urllib.error.URLError` / `socket.timeout` 也抛
  `ApiError`（`code='network'` / `'timeout'`），由 UI 统一显示 `COPY['errors']['network']`。
* **幂等键由客户端生成**：`rec_` / `tre_` + 随机串；**超时重试一次**。
* **日期参数一律 Asia/Shanghai 的 `YYYY-MM-DD`**。
* **本模块是同步阻塞的**：调用方必须在 `QThread` / `QThreadPool` 里用它，
  主线程只更新界面（UI约定 §3「不要阻塞 UI 线程」）。

依赖：只用标准库 `urllib`（本机 pip 环境没有 `httpx`/`requests`，见交付报告的实测证据），
因此双端都不需要额外依赖即可联调。
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - 极老解释器兜底
    ZoneInfo = None  # type: ignore[assignment]

try:  # 包内导入
    from . import session as session_mod
except ImportError:  # pragma: no cover - 直接以脚本路径导入时的兜底（同 copy.py）
    import session as session_mod  # type: ignore

__all__ = [
    "ApiError", "ApiClient", "TZ_NAME", "today_str", "now_iso", "new_id",
    "format_ts_human", "DEFAULT_TIMEOUT", "ERROR_CODES",
]

TZ_NAME = "Asia/Shanghai"
DEFAULT_TIMEOUT = 8.0

#: 契约 `error_codes`（另加两个网络层伪码，供 UI 取文案）
ERROR_CODES: Dict[str, str] = {
    "0": "success",
    "1001": "unauthorized_or_token_expired",
    "1002": "forbidden",
    "2001": "validation_failed",
    "2002": "not_found",
    "3001": "internal_error",
    "4001": "rate_limited",
    "network": "transport_failure (客户端伪码)",
    "timeout": "transport_timeout (客户端伪码)",
}

#: 响应信封里允许的键（便于自检断言信封形状）
ENVELOPE_KEYS: Tuple[str, ...] = ("code", "message", "data")


# --------------------------------------------------------------------------- 时间 / ID


def _tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(TZ_NAME)
        except Exception:  # pragma: no cover - 缺 tzdata 的 Windows 兜底
            pass
    from datetime import timedelta, timezone

    return timezone(timedelta(hours=8))


def today_str() -> str:
    """Asia/Shanghai 的 `YYYY-MM-DD`（契约 §1 时间约定）。"""
    return datetime.now(_tz()).strftime("%Y-%m-%d")


def now_iso() -> str:
    """ISO 8601 带时区（如 `2026-10-01T22:31:05+08:00`）。"""
    return datetime.now(_tz()).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    """生成幂等键：`rec_` / `tre_` + 随机串（契约 v1.0 `id_prefixes`）。"""
    return f"{prefix}{os.urandom(6).hex()}"


def format_ts_human(value: Any) -> str:
    """ISO 8601 时间戳 → **给人看的**字符串（界面只显示这个，不显示原始 ISO）。

    契约里 `ts` 是 `2026-10-02T21:40:00+08:00` 这种 25 字符的机器格式；把它
    直接塞进面向学生的界面（树洞列表、档案记录行），是"能跑但不像产品"。
    **全应用只有这一处格式化逻辑** —— 在两个显示点各写一份判断，就一定会漏一处
    （同 `desktop_common` 既有的"判定逻辑单点化"结论）。

    格式：`10月2日 21:40`（算上空格 11 个字符）。

    * **统一**：不分"今天/往日"两套写法 —— 同一列表里混着 `21:40` 与 `10月2日 21:40`
      反而更难扫读，而且"今天"会随零点翻页导致同一屏在不同时刻长得不一样；
    * 秒不显示（问卷/树洞都是当日随手记，分钟粒度足够，也避免噪声）；
    * 时间一律**换算到 `Asia/Shanghai`**（契约 §1 时间约定）后再取时分，
      因此显示结果不受本机时区影响；带 `Z` / 带别处偏移量的 `ts` 都会被正确换算；
    * **不抛异常**：`None` / `''` / 非法格式 / 非字符串 → 原样返回字符串形态
      （拿不到结构化时间就绝不猜，宁可显示服务端原文）。

    :param value: 契约的 `ts` 字段（或任何字符串）
    :return: 可读时间；无法解析时返回传入值的字符串形态
    """
    text = "" if value is None else str(value)
    if not text.strip():
        return ""
    normalized = text.strip()
    if normalized.endswith(("Z", "z")):          # RFC 3339 的 UTC 写法
        normalized = normalized[:-1] + "+00:00"
    else:
        # `+0800` → `+08:00`（`fromisoformat` 需要冒号，Python 3.11+ 才宽松）
        head, _, offset = normalized.rpartition("+")
        if len(offset) == 4 and offset.isdigit() and head:
            normalized = f"{head}+{offset[:2]}:{offset[2:]}"
    try:
        stamp = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return text
    try:
        local = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=_tz())
        local = local.astimezone(_tz())
        return f"{local.month}月{local.day}日 {local.strftime('%H:%M')}"
    except Exception:                            # pragma: no cover - 极端兜底
        return text


# --------------------------------------------------------------------------- 异常


class ApiError(Exception):
    """契约信封的失败响应，或网络层失败。

    :param code: 契约错误码（int）或网络层伪码（`'network'` / `'timeout'`）
    :param message: 服务端的人类可读说明（**不得**直接当界面文案用，界面文案查文案表）
    :param path: 出错的接口路径，便于界面/日志定位
    :param field: 服务端 2001 的 message 里提取到的字段名（尽力而为，可能为 None）
    :param payload: 原始信封（诊断用）
    """

    def __init__(
        self,
        code: Any,
        message: str = "",
        path: str = "",
        *,
        field: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.path = path
        self.field = field
        self.payload = payload
        super().__init__(f"[{code}] {message} ({path})")

    @property
    def is_network(self) -> bool:
        return self.code in ("network", "timeout")

    @property
    def copy_key(self) -> str:
        """该错误在文案表 `errors` 下的键（网络层统一 `network`）。"""
        return "network" if self.is_network else str(self.code)


# 服务端 2001 的 message 形如「字段 detail 校验失败：必须是非空字符串」，
# 这里尽力提取字段名，仅用于把「哪一项没填」说得更具体（文案仍来自文案表）。
_FIELD_HINTS = (
    "record_id", "mood", "plain_note", "cause_category", "detail", "request_help",
    "consent_share", "consent_ts",
    "entry_id", "content", "mood_tag",
    "date", "scene", "role", "id", "password", "action", "note", "since",
)


def _extract_field(message: str) -> Optional[str]:
    for name in _FIELD_HINTS:
        if name in message:
            return name
    return None


def _loads_envelope(text: str) -> Optional[Dict[str, Any]]:
    """把响应体解析成信封 dict；不是 JSON object 时返回 `None`。

    * 空响应 → `{"code": 3001, ...}`（服务端没给信封，按内部错误口径暴露）；
    * 非 JSON → `{"code": 3001, ...}`（同上，**不抛** `JSONDecodeError`）；
    * JSON object → 原样返回（**含** `{code: 2001, ...}` 这类业务失败信封）。
    """
    if not text or not text.strip():
        return {"code": 3001, "message": "服务端返回空响应", "data": None}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"code": 3001, "message": f"响应不是合法 JSON：{text[:120]}", "data": None}
    return parsed if isinstance(parsed, dict) else None


# --------------------------------------------------------------------------- 客户端


class ApiClient:
    """契约客户端。**同步**；请在 worker 线程里调用。

    用法::

        client = ApiClient("http://127.0.0.1:8080")
        client.login_student("2023001")           # 之后自动带 Bearer token
        client.submit_questionnaire(body)
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8080",
                 *, timeout: float = DEFAULT_TIMEOUT,
                 transport: Optional[Callable[[str, str, Optional[dict], Optional[str], float], Dict[str, Any]]] = None,
                 retry_on_timeout: bool = True,
                 session_path: Optional[Any] = None) -> None:
        raw = (base_url or "").strip().rstrip("/")
        if not raw:
            raw = "http://127.0.0.1:8080"
        if not raw.startswith(("http://", "https://")):
            raw = "http://" + raw
        self.base_url = raw
        self.api_root = raw + "/api/v1"
        self.timeout = float(timeout)
        #: 当前 token（`POST /auth/login` 成功后由本类写入）
        self.token: Optional[str] = None
        #: 当前登录档（`{id, name, class_name, role}`）
        self.profile: Optional[dict] = None
        self.expires_in: Optional[int] = None
        #: 幂等写接口超时后重试一次（UI约定 §3）
        self.retry_on_timeout = bool(retry_on_timeout)
        #: 允许注入传输层（自检用它做"不在主线程发请求"的计数断言）
        self._transport = transport
        #: 最近一次请求是否发生过超时重试（UI 可据此显示"替你重试了一次"）
        self.last_retried = False
        #: 登录态持久化文件（协议 §2.1「token 持久化存储」）。
        #: 默认 `%LOCALAPPDATA%\MindCare\session.json`（**不在工程目录里**）；
        #: 传显式路径可覆盖；传 `session_path=False`（或设 `MINDCAKE_SESSION_DISABLE=1`）
        #: 则整个关闭持久化 —— ⚠️ `False` 必须归一成 `None`，否则 `Path(False)` 会在
        #: 登录成功那一刻抛 `TypeError`（实测踩过：`① 登录` 失败但 token 已写入，
        #: 症状是"登录成功却停在登录页"）。
        self.session_path: Optional[Any] = session_path
        if session_path is None and not session_mod.persistence_disabled():
            self.session_path = session_mod.session_file()
        elif session_path is False:
            self.session_path = None
        #: 最近一次 `load_session()` 的结果（`None` = 没恢复出登录态）
        self.restored: Optional[dict] = None

    # ---------------------------------------------------------------- 登录态持久化
    # 依据：`mindcare新版/docs/学生端接口协议说明.md` §2.1「token 持久化存储」+
    # `expires_in=43200`（12h）。存储位置/过期判定在 `desktop_common/session.py`
    # 单点实现，本类只做"什么时候存、什么时候读、什么时候清"。

    def save_session(self, profile: Optional[dict] = None) -> bool:
        """把当前 token 写到本地登录态文件。无 token 时**只清不写**。

        `session_path=None`（持久化被关闭）时返回 `False`，**不抛异常**。
        """
        if not self.token:
            self.clear_session()
            return False
        if not self.session_path:
            return False
        written = session_mod.save_session(
            self.token,
            profile if profile is not None else self.profile,
            expires_in=self.expires_in,
            path=self.session_path,
        )
        return written is not None

    def load_session(self, *, now: Optional[float] = None) -> Optional[dict]:
        """从本地登录态文件恢复 `token` / `profile`。

        * 文件不存在 → `None`；
        * 已过期（12h）→ 文件被清掉，返回 `None`；
        * 文件损坏 → 文件被清掉，返回 `None`；
        * **任何情况都不抛异常**（磁盘/权限问题也只是没有登录态而已）。

        :return: 恢复出来的登录态 dict，或 `None`
        """
        data = session_mod.load_session(path=self.session_path, now=now)
        self.restored = data
        if not data:
            return None
        self.token = data.get("token")
        self.profile = data.get("profile") or {}
        try:
            self.expires_in = int(data.get("expires_in"))
        except (TypeError, ValueError):
            self.expires_in = None
        return data

    def clear_session(self) -> bool:
        """清除内存登录态**并**删除本地登录态文件（登出 / `1001` 跳登录都走这里）。"""
        self.token = None
        self.profile = None
        self.expires_in = None
        self.restored = None
        return session_mod.clear_session(self.session_path)

    # ---------------------------------------------------------------- 传输层

    def _do_http(self, method: str, url: str, body: Optional[dict],
                 token: Optional[str], timeout: float) -> Dict[str, Any]:
        """真正发一次请求，返回解析后的 JSON（**不含信封校验**）。

        ⚠️ 非 2xx 的 HTTP 状态**不一定**是传输层失败：v1.0 服务端用
        `{1001:401, 1002:403, 2001:400, 2002:404, 3001:500, 4001:429}`
        表达业务错误（RFC 9110），响应体仍是标准的 `{code, message, data}` 信封。
        因此这里先把这类响应的**信封解出来照常返回**，让 `request()` 统一按
        `code != 0` 处理；只有响应体确实不是信封时，才退化成网络层伪码
        （否则 UI 会把「2001 未填完整」显示成「网络失败」，且拿不到字段名）。
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
            except Exception:  # pragma: no cover - 读流失败
                text = ""
            parsed = _loads_envelope(text)
            if parsed is not None:
                return parsed
            return {"code": "network", "message": f"HTTP {exc.code}", "data": None}
        return _loads_envelope(text)

    def request(self, method: str, path: str, *, body: Optional[dict] = None,
                query: Optional[dict] = None, auth: bool = True,
                idempotent: bool = False) -> Any:
        """发一次请求并**解包信封**，返回 `data`。

        :raises ApiError: `code != 0`，或网络层失败
        """
        method = method.upper()
        url = self.api_root + path
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        token = self.token if auth else None
        self.last_retried = False

        attempts = 2 if (idempotent and self.retry_on_timeout) else 1
        last_error: Optional[ApiError] = None
        envelope: Any = None
        for attempt in range(attempts):
            try:
                envelope = (self._transport or self._do_http)(
                    method, url, body, token, self.timeout
                )
            except socket.timeout as exc:
                last_error = ApiError("timeout", f"请求超时：{exc}", path)
                if attempt + 1 < attempts:
                    self.last_retried = True
                    continue
                raise last_error from exc
            except urllib.error.HTTPError as exc:
                # 传输层若直接把 HTTPError 抛出来（未走信封解包），也按上面的口径
                # 尝试读信封；读不到才算网络失败。
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except Exception:  # pragma: no cover - 读流失败
                    pass
                parsed = _loads_envelope(detail)
                if parsed is None:
                    raise ApiError("network", f"HTTP {exc.code}：{detail[:200]}",
                                   path) from exc
                envelope = parsed
            except urllib.error.URLError as exc:
                last_error = ApiError("network", f"网络不可用：{exc.reason}", path)
                raise last_error from exc
            except OSError as exc:
                last_error = ApiError("network", f"网络错误：{exc}", path)
                raise last_error from exc
            break

        if last_error is not None and not isinstance(envelope, dict):  # pragma: no cover
            raise last_error

        if not isinstance(envelope, dict):
            raise ApiError(3001, "响应信封不是 JSON object", path, payload=None)
        code = envelope.get("code")
        message = str(envelope.get("message") or "")
        if code != 0:
            raise ApiError(code, message, path,
                           field=_extract_field(message), payload=envelope)
        return envelope.get("data")

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: Optional[dict] = None, **kwargs) -> Any:
        return self.request("POST", path, body=body, **kwargs)

    def patch(self, path: str, body: Optional[dict] = None, **kwargs) -> Any:
        return self.request("PATCH", path, body=body, **kwargs)

    # ---------------------------------------------------------------- 公共

    def health(self) -> dict:
        """`GET /health`（公共，免鉴权）。"""
        return self.request("GET", "/health", auth=False) or {}

    def login_student(self, student_no: str, password: str = "") -> dict:
        """`POST /auth/login {role:"student", id:<号次>, password:<真密码>}`（v1.1 追加件）。

        注册制：学生第一次登录先走 `register_student()`，之后用「号次 + 密码」登录。
        号次由前端**原样发送**（不做前缀补全）。登录成功后**立即**把 token 落盘
        （协议 §2.1「token 持久化存储」），应用重启时 `load_session()` 可直接恢复。
        """
        data = self.request(
            "POST", "/auth/login",
            body={"role": "student", "id": str(student_no), "password": password},
            auth=False,
        ) or {}
        self.token = data.get("token")
        self.profile = data.get("profile")
        self.expires_in = data.get("expires_in")
        self.save_session()
        return data

    def register_student(self, class_name: str, name: str, seat_no: str,
                         password: str) -> dict:
        """`POST /auth/register`（v1.1 追加件）：注册即建个人数据库 + 自动登录。"""
        data = self.request(
            "POST", "/auth/register",
            body={"class_name": class_name, "name": name,
                  "seat_no": seat_no, "password": password},
            auth=False,
        ) or {}
        self.token = data.get("token")
        self.profile = data.get("profile")
        self.expires_in = data.get("expires_in")
        self.save_session()
        return data

    def login_teacher(self, teacher_no: str, password: str) -> dict:
        """`POST /auth/login {role:"teacher", ...}`（教师端用；学生端不调用）。"""
        data = self.request(
            "POST", "/auth/login",
            body={"role": "teacher", "id": str(teacher_no), "password": password},
            auth=False,
        ) or {}
        self.token = data.get("token")
        self.profile = data.get("profile")
        self.expires_in = data.get("expires_in")
        self.save_session()
        return data

    # ---------------------------------------------------------------- 学生端 8 个

    def submit_questionnaire(self, body: dict) -> dict:
        """`POST /questionnaire/submissions`（幂等，超时重试一次）。

        v1.0 契约：请求体只有 8 个字段 ——
        `record_id, mood, plain_note, cause_category, detail, request_help,
        consent_share, consent_ts`（v1.1 那两个 material 专用字段已随降级移出）。
        """
        return self.request("POST", "/questionnaire/submissions", body=body,
                            idempotent=True) or {}

    def my_profile(self, date: str) -> dict:
        """`GET /profile/me?date=YYYY-MM-DD`。"""
        return self.request("GET", "/profile/me", query={"date": date}) or {}

    def my_dates(self) -> dict:
        """`GET /profile/me/dates`。"""
        return self.request("GET", "/profile/me/dates") or {}

    def create_treehole(self, body: dict) -> dict:
        """`POST /treehole/entries`（L0 绝对私密，无分享字段）。"""
        return self.request("POST", "/treehole/entries", body=body, idempotent=True) or {}

    def my_treehole(self, date: str) -> dict:
        """`GET /treehole/entries?date=YYYY-MM-DD`。"""
        return self.request("GET", "/treehole/entries", query={"date": date}) or {}

    def tips(self, scene: str) -> dict:
        """`GET /tips?scene=plain|down`。"""
        return self.request("GET", "/tips", query={"scene": scene}) or {}

    # ---------------------------------------------------------------- 教师端 3 个
    # 学生端不调用；由共享包 owner（学生端 agent）顺手写好，教师端 agent 直接引用。

    def triage_list(self, since: Optional[str] = None) -> dict:
        """`GET /triage/list?since=`（首次不传 since，之后回传上次 `generated_at`）。"""
        return self.request("GET", "/triage/list", query={"since": since}) or {}

    def student_today(self, student_id: str) -> dict:
        """`GET /triage/students/{student_id}/today`。"""
        return self.request(
            "GET", f"/triage/students/{urllib.parse.quote(str(student_id))}/today"
        ) or {}

    def ack_ticket(self, ticket_id: str, action: str, note: Optional[str] = None) -> dict:
        """`POST /triage/tickets/{ticket_id}/ack` body `{action, note}`。

        :param action: `accept` | `done`（`done` 为终态）
        """
        return self.request(
            "POST", f"/triage/tickets/{urllib.parse.quote(str(ticket_id))}/ack",
            body={"action": action, "note": note},
        ) or {}
