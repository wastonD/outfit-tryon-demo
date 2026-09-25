"""每用户每日额度（契约 v1.4 "额度"一节）：判定上限、统计当日已用次数、记录计费事件。

上限取值依次为：CurrentUser.daily_outfit_limit（来自 users.json，仅 multi 模式）→ 环境变量
OUTFIT_DAILY_OUTFIT_LIMIT → 不限；open 模式永远不限。计数用"当天发起的计费操作次数"，
按北京时间（UTC+8）0 点重置。clock 可注入，供测试模拟跨天。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable

from .db import Database
from .deps import CurrentUser
from .errors import ApiError

BEIJING_OFFSET = timedelta(hours=8)
# 计入额度的计费操作：新建搭配、新建 360°、重试 tryon/turntable 任务
BILLABLE_KINDS = ("outfit", "turntable", "retry_tryon", "retry_turntable")


def default_clock() -> datetime:
    return datetime.now(timezone.utc)


def beijing_day_start_utc(now: datetime) -> datetime:
    """返回 now 所在北京日期 00:00 对应的 UTC 时间。"""
    beijing_now = now + BEIJING_OFFSET
    midnight = beijing_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - BEIJING_OFFSET


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class QuotaChecker:
    def __init__(self, db: Database, clock: Callable[[], datetime] = default_clock):
        self.db = db
        self.clock = clock  # 测试可以直接替换这个属性来模拟跨天

    def _day_start_iso(self) -> str:
        return _iso(beijing_day_start_utc(self.clock()))

    def used_today(self, user_id: str) -> int:
        return self.db.count_usage_events(user_id, BILLABLE_KINDS, self._day_start_iso())

    def limit_for(self, current_user: CurrentUser) -> int | None:
        if current_user.mode == "open":
            return None
        if current_user.daily_outfit_limit is not None:
            return current_user.daily_outfit_limit
        env = os.environ.get("OUTFIT_DAILY_OUTFIT_LIMIT")
        if env:
            try:
                return int(env)
            except ValueError:
                return None
        return None

    def check_and_record(self, current_user: CurrentUser, kind: str) -> None:
        """kind 为 "outfit" | "turntable" | "retry_tryon" | "retry_turntable"。

        超过上限时记一条 quota_exceeded 事件（供报表统计触顶次数）并抛 429；
        否则记一条计费事件，计入当天已用次数。
        """
        limit = self.limit_for(current_user)
        now = self.clock()
        if limit is not None and self.used_today(current_user.user_id) >= limit:
            self.db.record_usage_event(current_user.user_id, "quota_exceeded", _iso(now))
            reset_at = _iso(beijing_day_start_utc(now) + timedelta(days=1))
            raise ApiError(429, "quota_exceeded",
                           f"今日额度（{limit} 次）已用完，将于北京时间次日 00:00（{reset_at}）重置")
        self.db.record_usage_event(current_user.user_id, kind, _iso(now))
