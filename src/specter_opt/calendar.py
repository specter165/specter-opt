"""US trading calendar utilities."""

from datetime import date, datetime, time, timedelta
from typing import Optional

import pandas_market_calendars as mcal
import pytz


class TradingCalendar:
    """NYSE trading calendar wrapper."""

    def __init__(self, tz: str = "America/New_York"):
        self.tz = pytz.timezone(tz)
        self.nyse = mcal.get_calendar("NYSE")

    def is_trading_day(self, dt: datetime) -> bool:
        d = dt.date() if isinstance(dt, datetime) else dt
        days = self.nyse.valid_days(start_date=d, end_date=d)
        return len(days) > 0

    def previous_session(self, dt: Optional[datetime] = None) -> date:
        d = (dt or datetime.now(self.tz)).date()
        # Walk backward up to 10 days
        for offset in range(1, 11):
            candidate = d - timedelta(days=offset)
            if self.is_trading_day(candidate):
                return candidate
        raise ValueError("No previous trading session found in last 10 days")

    def next_session(self, dt: Optional[datetime] = None) -> date:
        d = (dt or datetime.now(self.tz)).date()
        for offset in range(1, 11):
            candidate = d + timedelta(days=offset)
            if self.is_trading_day(candidate):
                return candidate
        raise ValueError("No next trading session found in next 10 days")

    def session_open_close(self, d: date) -> tuple[datetime, datetime]:
        schedule = self.nyse.schedule(start_date=d, end_date=d)
        if schedule.empty:
            raise ValueError(f"{d} is not a trading session")
        row = schedule.iloc[0]
        return (
            row["market_open"].to_pydatetime(),
            row["market_close"].to_pydatetime(),
        )

    def regular_session_start(self, d: Optional[date] = None) -> datetime:
        d = d or datetime.now(self.tz).date()
        open_dt, _ = self.session_open_close(d)
        return open_dt

    def days_to_expiry(self, as_of: datetime, expiry_date: date) -> int:
        """Calendar days between as_of and expiry (inclusive convention: DTE)."""
        return max(0, (expiry_date - as_of.date()).days)

    def trading_days_between(self, start: date, end: date) -> int:
        """Number of trading sessions in [start, end]."""
        if end < start:
            return 0
        schedule = self.nyse.schedule(start_date=start, end_date=end)
        return len(schedule)


def now_utc() -> datetime:
    return datetime.now(pytz.UTC)


def localize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)


def ny_now() -> datetime:
    return datetime.now(pytz.timezone("America/New_York"))
