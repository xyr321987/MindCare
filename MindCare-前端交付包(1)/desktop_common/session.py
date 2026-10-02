"""登录态**持久化存储**（`mindcare新版/docs/学生端接口协议说明.md` §2.1「UI 要点：token 持久化存储」）。

为什么单独一个模块
------------------

协议只要求"token 持久化存储"，但**存哪里、怎么判过期、坏了怎么办**这三件事
必须只有一份实现：协议里 `expires_in=43200`（12h）是服务端口径，恢复登录态时
若在两个地方各判一次"是不是过期了"，就一定会漏一处（同 `desktop_common`
既有结论：判定逻辑单点化）。

存储位置
--------

`%LOCALAPPDATA%\\MindCare\\session.json`（Windows 的用户级本地目录）。

* **绝不写进工程目录**：不落 `mindcare/data/`、不落仓库任何路径
  （本应用是本地演示件，把凭证写进仓库会被整包拷走）；
* 路径**不写死**：用 `os.environ.get("LOCALAPPDATA")` 取；取不到时按
  `XDG_DATA_HOME` / `~/.local/share` / `tempfile.gettempdir()` 依次兜底，
  保证任何平台都能跑而不抛异常；
* 测试覆盖钩子：`MINDCAKE_SESSION_DIR` 环境变量可整体改掉目录
  （自检用它把 session 写到临时目录，**不污染开发者真实的登录态**）。
  `MINDCAKE_SESSION_DISABLE=1` 时完全关闭持久化（`ApiClient(session_path=None)`）。

文件格式
--------

    {"token": "<32 位>", "profile": {...}, "saved_at": 1759...,
     "expires_in": 43200, "expires_at": 1759...}

`expires_at`（绝对过期时刻，Unix 秒）在**写入时**算好：只存 `saved_at` 而
读取时再算的话，"过期判定"就又分散到读取端了。旧文件缺 `expires_at` 时
退回 `saved_at + expires_in`。

失败一律静默
------------

无权限、磁盘满、文件被别的进程写坏（半截 JSON）——**都不得让应用崩**：
所有读写函数都不抛异常，坏文件顺手删掉，应用正常显示登录页。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = [
    "DEFAULT_EXPIRES_IN",
    "SESSION_FILE_NAME",
    "DIR_ENV_VAR",
    "DISABLE_ENV_VAR",
    "session_file",
    "session_dir",
    "save_session",
    "load_session",
    "clear_session",
    "session_is_expired",
]

#: 契约 `POST /auth/login` 返回的 `expires_in`（秒）：43200 = 12h。
#: 服务端 `server/api/auth.py: EXPIRES_SECONDS` 是同一口径；此处是客户端**兜底**值
#: （服务端若返回别的 `expires_in`，以响应为准）。
DEFAULT_EXPIRES_IN = 43200

SESSION_FILE_NAME = "session.json"

#: 覆盖存储目录（自检 / 多实例隔离用）
DIR_ENV_VAR = "MINDCAKE_SESSION_DIR"
#: 设为 `1` 时彻底关闭持久化
DISABLE_ENV_VAR = "MINDCAKE_SESSION_DISABLE"


# --------------------------------------------------------------------------- 路径


def session_dir() -> Path:
    """登录态目录（`%LOCALAPPDATA%\\MindCare`，本机用户级，**不在工程目录里**）。"""
    override = (os.environ.get(DIR_ENV_VAR) or "").strip()
    if override:
        return Path(override)
    base = (os.environ.get("LOCALAPPDATA") or "").strip()
    if not base:
        base = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if not base:
        try:
            base = str(Path.home() / ".local" / "share")
        except Exception:                       # pragma: no cover - 取不到家目录
            import tempfile

            base = tempfile.gettempdir()
    return Path(base) / "MindCare"


def session_file() -> Path:
    """登录态文件全路径：`<session_dir()>/session.json`。"""
    return session_dir() / SESSION_FILE_NAME


def persistence_disabled() -> bool:
    return (os.environ.get(DISABLE_ENV_VAR) or "").strip() in ("1", "true", "yes")


# --------------------------------------------------------------------------- 读写


def clear_session(path: Optional[Path] = None) -> bool:
    """删除登录态文件。**不抛异常**。

    :return: 是否真的删掉了文件（文件本来就不存在时返回 `False`）
    """
    target = Path(path) if path is not None else session_file()
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def save_session(token: str, profile: Optional[dict] = None,
                 *, expires_in: Any = DEFAULT_EXPIRES_IN,
                 path: Optional[Path] = None,
                 now: Optional[float] = None) -> Optional[Path]:
    """把 `{token, profile, saved_at, expires_in, expires_at}` 写盘（原子替换）。

    **只存 token 与登录档**：不存任何问卷/树洞内容（那些是服务端的事实，
    本地副本只会制造不一致）。`token` 是随机串本身，没有额外的账号隐私字段。

    :param expires_in: 服务端返回的有效期（秒）；非正数/非数字 → 用契约默认值
    :param path: 覆盖文件路径（自检用）
    :param now: 覆盖"现在"（自检用；不传取 `time.time()`）
    :return: 写入的路径；失败（无权限/磁盘满）时返回 `None`，**不抛异常**
    """
    if path is None:
        if persistence_disabled():
            return None
        path = session_file()
    target = Path(path)
    stamp = float(now if now is not None else time.time())
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        seconds = DEFAULT_EXPIRES_IN
    if seconds <= 0:
        seconds = DEFAULT_EXPIRES_IN
    payload: Dict[str, Any] = {
        "token": str(token),
        "profile": dict(profile) if isinstance(profile, dict) else {},
        "saved_at": stamp,
        "expires_in": seconds,
        "expires_at": stamp + seconds,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)             # 原子替换：不会留下半截文件
    except OSError:
        return None
    return target


def session_is_expired(data: dict, *, now: Optional[float] = None) -> bool:
    """登录态是否已过期（按 `expires_at`，缺则 `saved_at + expires_in` 兜底）。

    判定用的"现在"是**本机单调无关的墙钟**（`time.time()`），与服务端的
    `server_time` 同量级；时钟偏差最多让边界上多一次 1001 跳登录，正是
    要求 3 覆盖的路径。
    """
    if not isinstance(data, dict):
        return True
    try:
        now_s = float(now if now is not None else time.time())
    except (TypeError, ValueError):         # pragma: no cover - 防御
        now_s = time.time()
    expires_at = data.get("expires_at")
    try:
        if expires_at is not None:
            return now_s >= float(expires_at)
        saved_at = float(data.get("saved_at"))
    except (TypeError, ValueError):
        return True                          # 缺时间戳 = 无法判定 → 按过期处理
    try:
        seconds = int(data.get("expires_in"))
    except (TypeError, ValueError):
        seconds = DEFAULT_EXPIRES_IN
    if seconds <= 0:
        seconds = DEFAULT_EXPIRES_IN
    return now_s >= saved_at + seconds


def load_session(*, path: Optional[Path] = None,
                 now: Optional[float] = None,
                 purge_expired: bool = True) -> Optional[dict]:
    """读登录态。**任何异常都不外抛**，只在返回 `None` 时表示"没有可用登录态"。

    以下情况一律返回 `None`（并顺手清掉坏文件）：

    * 文件不存在；
    * 不是合法 JSON / 不是 JSON object（半截写入、被手工改坏）；
    * `token` 缺失或为空；
    * 已过期（`purge_expired=True` 时删除文件；自检要观察"过期文件确实被清掉"，
      故默认删除）。

    :return: `{"token", "profile", "saved_at", "expires_in", "expires_at"}`
    """
    if path is None:
        if persistence_disabled():
            return None
        path = session_file()
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        clear_session(target)
        return None
    if not isinstance(data, dict):
        clear_session(target)
        return None
    token = data.get("token")
    if not isinstance(token, str) or not token.strip():
        clear_session(target)
        return None
    if session_is_expired(data, now=now):
        if purge_expired:
            clear_session(target)
        return None
    if not isinstance(data.get("profile"), dict):
        data["profile"] = {}
    return data
