"""交易所日历：不把调休上班日当交易日；未知年份失败关闭。"""
from datetime import date, datetime, time, timedelta, timezone
import json
from .config import ROOT

SH = timezone(timedelta(hours=8), name="Asia/Shanghai")

class CalendarUnknown(ValueError):
    pass

class TradingCalendar:
    def __init__(self, path=ROOT / "data/calendar.json", payload=None):
        self.payload = payload if payload is not None else json.loads(path.read_text(encoding="utf-8"))
        self.years = self.payload["years"]

    def is_session(self, day):
        if isinstance(day, str):
            day = date.fromisoformat(day)
        spec = self.years.get(str(day.year))
        if spec is None:
            raise CalendarUnknown(f"{day.year} 年交易所日历尚未核验，请维护 data/calendar.json")
        if "sessions" in spec:
            return day.isoformat() in spec["sessions"]
        return day.weekday() < 5 and not any(date.fromisoformat(a) <= day <= date.fromisoformat(b) for a, b in spec["closures"])

    def sessions(self, start, end):
        start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        result = []
        while start <= end:
            if self.is_session(start):
                result.append(start.isoformat())
            start += timedelta(days=1)
        return result

    def next_session(self, day):
        day = date.fromisoformat(str(day)) + timedelta(days=1)
        for _ in range(370):
            if self.is_session(day):
                return day
            day += timedelta(days=1)
        raise CalendarUnknown("无法确定下一交易日")

    def expected_date(self, now):
        now = now.astimezone(SH)
        day = now.date()
        # 收盘前仍以最近已收盘交易日为期望日期，15:00 后即提示等待当日数据。
        if now.time() < time(15):
            day -= timedelta(days=1)
        for _ in range(370):
            if self.is_session(day):
                return day.isoformat()
            day -= timedelta(days=1)
        raise CalendarUnknown("无法确定最近收盘交易日")

    def next_open(self, day):
        return datetime.combine(self.next_session(day), time(9, 30), SH)

    def usable_open(self, day, available_at):
        # 留出 30 分钟决策缓冲；迟到的数据不能回填到已过去的开盘。
        opening = self.next_open(day)
        available = datetime.fromisoformat(available_at)
        while available > opening - timedelta(minutes=30):
            opening = self.next_open(opening.date())
        return opening.isoformat()
