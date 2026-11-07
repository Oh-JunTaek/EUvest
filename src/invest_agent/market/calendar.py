"""시장 캘린더 - 휴장일, 조기종료일 관리."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from invest_agent.market.market_data import Market


@dataclass(frozen=True)
class Holiday:
    """휴장일 정보."""
    date: date
    name: str
    market: Market
    is_early_close: bool = False
    early_close_time: str | None = None  # "HH:MM" 형식


# KRX 휴장일 (2024년 기준)
KRX_HOLIDAYS_2024 = [
    Holiday(date(2024, 1, 1), "신정", Market.KRX),
    Holiday(date(2024, 2, 9), "설날 연휴", Market.KRX),
    Holiday(date(2024, 2, 10), "설날", Market.KRX),
    Holiday(date(2024, 2, 11), "설날 연휴", Market.KRX),
    Holiday(date(2024, 2, 12), "설날 대체공휴일", Market.KRX),
    Holiday(date(2024, 3, 1), "삼일절", Market.KRX),
    Holiday(date(2024, 4, 10), "국회의원선거일", Market.KRX),
    Holiday(date(2024, 5, 5), "어린이날", Market.KRX),
    Holiday(date(2024, 5, 6), "어린이날 대체공휴일", Market.KRX),
    Holiday(date(2024, 5, 15), "석가탄신일", Market.KRX),
    Holiday(date(2024, 6, 6), "현충일", Market.KRX),
    Holiday(date(2024, 8, 15), "광복절", Market.KRX),
    Holiday(date(2024, 9, 16), "추석 연휴", Market.KRX),
    Holiday(date(2024, 9, 17), "추석", Market.KRX),
    Holiday(date(2024, 9, 18), "추석 연휴", Market.KRX),
    Holiday(date(2024, 10, 3), "개천절", Market.KRX),
    Holiday(date(2024, 10, 9), "한글날", Market.KRX),
    Holiday(date(2024, 12, 25), "성탄절", Market.KRX),
]

# US 휴장일 (2024년 기준)
US_HOLIDAYS_2024 = [
    Holiday(date(2024, 1, 1), "New Year's Day", Market.US),
    Holiday(date(2024, 1, 15), "Martin Luther King Jr. Day", Market.US),
    Holiday(date(2024, 2, 19), "Presidents' Day", Market.US),
    Holiday(date(2024, 3, 29), "Good Friday", Market.US),
    Holiday(date(2024, 5, 27), "Memorial Day", Market.US),
    Holiday(date(2024, 6, 19), "Juneteenth", Market.US),
    Holiday(date(2024, 7, 4), "Independence Day", Market.US),
    Holiday(date(2024, 9, 2), "Labor Day", Market.US),
    Holiday(date(2024, 11, 28), "Thanksgiving Day", Market.US),
    Holiday(date(2024, 12, 25), "Christmas Day", Market.US),
]

# 조기 종료일
US_EARLY_CLOSE_2024 = [
    Holiday(date(2024, 7, 3), "Independence Day Eve", Market.US, is_early_close=True, early_close_time="13:00"),
    Holiday(date(2024, 11, 29), "Day after Thanksgiving", Market.US, is_early_close=True, early_close_time="13:00"),
    Holiday(date(2024, 12, 24), "Christmas Eve", Market.US, is_early_close=True, early_close_time="13:00"),
]

MARKET_HOLIDAYS = {
    Market.KRX: {2024: KRX_HOLIDAYS_2024},
    Market.US: {2024: US_HOLIDAYS_2024 + US_EARLY_CLOSE_2024},
}


class MarketCalendar:
    """시장 캘린더 - 영업일 판단, 휴장일 조회."""

    def __init__(self, market: Market):
        self.market = market
        self._holidays_cache: dict[int, list[Holiday]] = {}
        self._load_holidays()

    def _load_holidays(self) -> None:
        """휴장일 로드."""
        market_holidays = MARKET_HOLIDAYS.get(self.market, {})
        for year, holidays in market_holidays.items():
            self._holidays_cache[year] = holidays

    def is_holiday(self, dt: date) -> bool:
        """휴장일 여부."""
        holidays = self._holidays_cache.get(dt.year, [])
        return any(h.date == dt and not h.is_early_close for h in holidays)

    def is_early_close(self, dt: date) -> bool:
        """조기 종료일 여부."""
        holidays = self._holidays_cache.get(dt.year, [])
        return any(h.date == dt and h.is_early_close for h in holidays)

    def get_early_close_time(self, dt: date) -> str | None:
        """조기 종료 시간 반환 (HH:MM)."""
        holidays = self._holidays_cache.get(dt.year, [])
        for h in holidays:
            if h.date == dt and h.is_early_close:
                return h.early_close_time
        return None

    def is_business_day(self, dt: date) -> bool:
        """영업일 여부 (주말 + 휴장일 제외)."""
        if dt.weekday() >= 5:  # 토(5), 일(6)
            return False
        return not self.is_holiday(dt)

    def next_business_day(self, dt: date) -> date:
        """다음 영업일 반환."""
        next_day = dt
        while True:
            next_day = date.fromordinal(next_day.toordinal() + 1)
            if self.is_business_day(next_day):
                return next_day

    def prev_business_day(self, dt: date) -> date:
        """이전 영업일 반환."""
        prev_day = dt
        while True:
            prev_day = date.fromordinal(prev_day.toordinal() - 1)
            if self.is_business_day(prev_day):
                return prev_day

    def add_business_days(self, dt: date, days: int) -> date:
        """영업일 기준 N일 후/전 날짜 반환."""
        current = dt
        step = 1 if days > 0 else -1
        remaining = abs(days)

        while remaining > 0:
            current = date.fromordinal(current.toordinal() + step)
            if self.is_business_day(current):
                remaining -= 1
        return current

    def get_holidays(self, year: int) -> list[Holiday]:
        """특정 연도 휴장일 목록 반환."""
        return self._holidays_cache.get(year, [])


# 전역 캘린더 인스턴스
_krx_calendar: MarketCalendar | None = None
_us_calendar: MarketCalendar | None = None


def get_calendar(market: Market) -> MarketCalendar:
    """시장별 캘린더 싱글톤 반환."""
    global _krx_calendar, _us_calendar

    if market == Market.KRX:
        if _krx_calendar is None:
            _krx_calendar = MarketCalendar(Market.KRX)
        return _krx_calendar
    elif market == Market.US:
        if _us_calendar is None:
            _us_calendar = MarketCalendar(Market.US)
        return _us_calendar
    raise ValueError(f"지원하지 않는 시장: {market}")


def is_market_open_now(market: Market) -> bool:
    """현재 시장 개장 여부 (대략적 판단)."""
    from invest_agent.market.market_data import MARKET_TRADING_HOURS, get_market_timezone

    tz = get_market_timezone(market)
    now = datetime.now(tz)

    calendar = get_calendar(market)
    if not calendar.is_business_day(now.date()):
        return False

    # 거래 시간 확인
    hours = MARKET_TRADING_HOURS.get(market)
    if not hours:
        return False

    current_time = now.time()

    # 조기 종료일 확인
    if calendar.is_early_close(now.date()):
        early_close = calendar.get_early_close_time(now.date())
        if early_close:
            early_hour, early_min = map(int, early_close.split(":"))
            from datetime import time
            early_time = time(early_hour, early_min)
            return hours.market_open <= current_time < early_time

    return hours.is_trading_time(current_time)
