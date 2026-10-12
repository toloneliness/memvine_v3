import time
import pendulum


class SystemClock:
    """
    MemVine 的唯一时间源。

    设计原则：
      1. 内部永远使用 UTC timestamp (float) 进行计算和存储
      2. 只在"人类边界"（LLM prompt、日志）才转换为上海时区
      3. 提供 freeze/advance 接口，让单元测试可以控制时间
    """
    def __init__(self, timezone: str = None):
        if timezone is None:
            from config import SYSTEM_TIMEZONE
            timezone = SYSTEM_TIMEZONE
        self.timezone = timezone
        self._frozen_ts: float | None = None

    def now_ts(self) -> float:
        """获取当前 UTC 时间戳 (机器计算/存储用)"""
        return self._frozen_ts if self._frozen_ts is not None else time.time()

    def now_local(self) -> pendulum.DateTime:
        """获取当前本地时间 (仅用于给 LLM 看或日志打印)"""
        return pendulum.from_timestamp(self.now_ts(), tz=self.timezone)

    def format_local(self, ts: float = None) -> str:
        """格式化时间戳为本地时区可读字符串"""
        if ts is None:
            ts = self.now_ts()
        return pendulum.from_timestamp(ts, tz=self.timezone).format("YYYY-MM-DD HH:mm:ss dddd")
    def freeze(self, ts: float):
        """冻结时间到指定时间戳"""
        self._frozen_ts = ts

    def unfreeze(self):
        """恢复真实时间"""
        self._frozen_ts = None

    def advance(self, seconds: float):
        """在冻结状态下快进时间"""
        if self._frozen_ts is not None:
            self._frozen_ts += seconds