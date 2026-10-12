# f:\memvine_v3\core\time_resolver.py
"""中文时间表达式 → ISO 日期"""

import re
from datetime import datetime, timedelta, timezone


_WEEKDAY_CN = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
               "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6}


class TimeResolver:
    @staticmethod
    def parse(temporal: dict | None, message_ts: float) -> str | None:
        if not temporal or not isinstance(temporal, dict):
            return None
        expr = temporal.get("expression", "")
        ttype = temporal.get("type", "point")
        if not expr:
            return None
        dt = datetime.fromtimestamp(message_ts, tz=timezone.utc)
        result = TimeResolver._resolve(expr, dt)
        return result

    @staticmethod
    def _resolve(expr: str, dt: datetime) -> str | None:

        m = re.match(r"(\d+)天前", expr)
        if m:
            return (dt - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

        m = re.match(r"(\d+)天后", expr)
        if m:
            return (dt + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

        m = re.match(r"(\d+)小时前", expr)
        if m:
            return (dt - timedelta(hours=int(m.group(1)))).isoformat()

        if expr == "昨天":
            return (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        if expr == "今天":
            return dt.strftime("%Y-%m-%d")
        if expr == "明天":
            return (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        if expr == "后天":
            return (dt + timedelta(days=2)).strftime("%Y-%m-%d")
        if expr == "前天":
            return (dt - timedelta(days=2)).strftime("%Y-%m-%d")
        if expr == "上周":
            return (dt - timedelta(days=7)).strftime("%Y-%m-%d")
        if expr == "下周":
            return (dt + timedelta(days=7)).strftime("%Y-%m-%d")
        if expr == "下周一":
            return TimeResolver._next_weekday(dt, 0)
        if expr == "下周二":
            return TimeResolver._next_weekday(dt, 1)
        if expr == "下周三":
            return TimeResolver._next_weekday(dt, 2)
        if expr == "下周四":
            return TimeResolver._next_weekday(dt, 3)
        if expr == "下周五":
            return TimeResolver._next_weekday(dt, 4)
        if expr == "下周六":
            return TimeResolver._next_weekday(dt, 5)
        if expr == "下周日":
            return TimeResolver._next_weekday(dt, 6)

        for cn, wd in _WEEKDAY_CN.items():
            if cn in expr:
                return TimeResolver._last_weekday(dt, wd)

        m = re.match(r"(\d+)个月", expr)
        if m:
            return f"duration:{int(m.group(1))*30}天"

        m = re.match(r"(\d+)天", expr)
        if m:
            return f"duration:{int(m.group(1))}天"

        m = re.match(r"(\d+)周", expr)
        if m:
            return f"duration:{int(m.group(1))*7}天"

        return None

    @staticmethod
    def _last_weekday(dt: datetime, target: int) -> str:
        current = dt.weekday()
        diff = (current - target) % 7
        if diff == 0:
            diff = 7
        return (dt - timedelta(days=diff)).strftime("%Y-%m-%d")

    @staticmethod
    def _next_weekday(dt: datetime, target: int) -> str:
        current = dt.weekday()
        diff = (target - current) % 7
        if diff == 0:
            diff = 7
        return (dt + timedelta(days=diff)).strftime("%Y-%m-%d")