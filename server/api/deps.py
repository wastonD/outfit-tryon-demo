"""从 app.state 取出共享对象的依赖函数，以及鉴权依赖（契约 v1.3：三种模式 + 当前用户）。"""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fastapi import Header, Query, Request

from outfit_core.bootstrap import SERVER_ROOT

from .errors import ApiError


def get_runtime(request: Request):
    return request.app.state.runtime


def get_db(request: Request):
    return request.app.state.db


def get_jobs(request: Request):
    return request.app.state.jobs


def get_presets(request: Request):
    return request.app.state.presets


def get_quota(request: Request):
    return request.app.state.quota


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    name: str
    mode: str  # "multi" | "single" | "open"
    daily_outfit_limit: int | None = None  # v1.4：仅 multi 模式下可能来自 users.json，其余模式为 None


LOCAL_USER = CurrentUser(user_id="local", name="local", mode="open")


def _users_file_path() -> Path:
    override = os.environ.get("OUTFIT_USERS_FILE")
    return Path(override) if override else SERVER_ROOT / "config" / "users.json"


class _UsersFileCache:
    """按路径缓存 users.json 的 tokens；每次访问都比较修改时间，变了才重新读取磁盘。"""

    def __init__(self):
        self._lock = Lock()
        self._entries: dict[str, tuple[float, dict]] = {}

    def tokens_for(self, path: Path) -> dict:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}
        with self._lock:
            cached = self._entries.get(str(path))
            if cached is not None and cached[0] == mtime:
                return cached[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tokens = data.get("tokens", {})
            if not isinstance(tokens, dict):
                tokens = {}
        except (OSError, ValueError):
            tokens = {}
        with self._lock:
            self._entries[str(path)] = (mtime, tokens)
        return tokens


_users_cache = _UsersFileCache()


def _match_token(token: str, tokens: dict) -> dict | None:
    """常数时间比较，避免通过响应耗时差异枚举有效令牌。"""
    for candidate, info in tokens.items():
        if isinstance(candidate, str) and hmac.compare_digest(candidate, token):
            return info
    return None


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return None


def resolve_current_user(token: str | None) -> CurrentUser:
    """按契约的三种模式解析当前用户；令牌无效时抛 401。"""
    users_path = _users_file_path()
    if users_path.exists():
        tokens = _users_cache.tokens_for(users_path)
        info = _match_token(token, tokens) if token else None
        if info is None:
            raise ApiError(401, "unauthorized", "缺少或无效的授权信息")
        user_id = info.get("user_id")
        limit = info.get("daily_outfit_limit")
        if not isinstance(limit, int):
            limit = None
        return CurrentUser(user_id=user_id, name=info.get("name") or user_id, mode="multi",
                           daily_outfit_limit=limit)

    expected = os.environ.get("OUTFIT_API_TOKEN")
    if expected:
        if not token or not hmac.compare_digest(token, expected):
            raise ApiError(401, "unauthorized", "缺少或无效的授权信息")
        return CurrentUser(user_id="default", name="default", mode="single")

    return LOCAL_USER


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    return resolve_current_user(_bearer_token(authorization))


def get_current_user_file(authorization: str | None = Header(default=None),
                          token: str | None = Query(default=None)) -> CurrentUser:
    return resolve_current_user(_bearer_token(authorization) or token)
