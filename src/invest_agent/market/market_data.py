"""시장 데이터 도메인 모델.

KRX/US 시장별 거래 규칙, 상품 유형, 가격 정규화 등을 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timezone
from decimal import Decimal
from enum import StrEnum


class Market(StrEnum):
    """지원 시장."""
    KRX = "KRX"
    US = "US"


class AssetType(StrEnum):
    """자산 유형."""
    STOCK = "STOCK"
    ETF = "ETF"
    DOMESTIC_BOND = "DOMESTIC_BOND"
    FOREIGN_BOND = "FOREIGN_BOND"
    LEVERAGED_ETF = "LEVERAGED_ETF"
    INVERSE_ETF = "INVERSE_ETF"
    DERIVATIVE = "DERIVATIVE"


class Currency(StrEnum):
    """지원 통화."""
    KRW = "KRW"
    USD = "USD"


@dataclass(frozen=True)
class TradingHours:
    """거래 시간 (해당 시장 현지 시간)."""
    market_open: time
    market_close: time
    lunch_start: time | None = None
    lunch_end: time | None = None

    def is_trading_time(self, local_time: time) -> bool:
        """현지 시간 기준 거래 시간 여부."""
        if self.market_open <= local_time < self.market_close:
            if self.lunch_start and self.lunch_end:
                if self.lunch_start <= local_time < self.lunch_end:
                    return False
            return True
        return False


# 시장별 거래 시간 (현지 시간)
MARKET_TRADING_HOURS = {
    Market.KRX: TradingHours(
        market_open=time(9, 0),
        market_close=time(15, 30),
        lunch_start=None,
        lunch_end=None,
    ),
    Market.US: TradingHours(
        market_open=time(9, 30),
        market_close=time(16, 0),
        lunch_start=None,
        lunch_end=None,
    ),
}


@dataclass(frozen=True)
class LotSize:
    """시장별 최소 거래 단위 (주문 수량 단위)."""
    market: Market
    asset_type: AssetType
    min_quantity: int
    lot_size: int  # 매매 단위 (예: KRX 주식 1주, US 주식 1주)

    def round_quantity(self, quantity: int) -> int:
        """수량을 매매 단위로 올림/내림 (기본: 내림)."""
        if self.lot_size <= 1:
            return quantity
        return (quantity // self.lot_size) * self.lot_size

    def validate_quantity(self, quantity: int) -> bool:
        """주문 수량 유효성 검사."""
        return quantity >= self.min_quantity and quantity % self.lot_size == 0


# 시장별/자산유형별 매매 단위
MARKET_LOT_SIZES = {
    # KRX
    (Market.KRX, AssetType.STOCK): LotSize(Market.KRX, AssetType.STOCK, 1, 1),
    (Market.KRX, AssetType.ETF): LotSize(Market.KRX, AssetType.ETF, 1, 1),
    (Market.KRX, AssetType.LEVERAGED_ETF): LotSize(Market.KRX, AssetType.LEVERAGED_ETF, 1, 1),
    (Market.KRX, AssetType.INVERSE_ETF): LotSize(Market.KRX, AssetType.INVERSE_ETF, 1, 1),
    (Market.KRX, AssetType.DOMESTIC_BOND): LotSize(Market.KRX, AssetType.DOMESTIC_BOND, 10, 10),
    # US
    (Market.US, AssetType.STOCK): LotSize(Market.US, AssetType.STOCK, 1, 1),
    (Market.US, AssetType.ETF): LotSize(Market.US, AssetType.ETF, 1, 1),
    (Market.US, AssetType.LEVERAGED_ETF): LotSize(Market.US, AssetType.LEVERAGED_ETF, 1, 1),
    (Market.US, AssetType.INVERSE_ETF): LotSize(Market.US, AssetType.INVERSE_ETF, 1, 1),
    (Market.US, AssetType.FOREIGN_BOND): LotSize(Market.US, AssetType.FOREIGN_BOND, 1, 1),
}


def get_lot_size(market: Market, asset_type: AssetType) -> LotSize:
    """시장/자산유형별 매매 단위 조회."""
    return MARKET_LOT_SIZES.get((market, asset_type), LotSize(market, asset_type, 1, 1))


def validate_quantity(market: Market, asset_type: AssetType, quantity: int) -> bool:
    """주문 수량 유효성 검사."""
    lot = get_lot_size(market, asset_type)
    return lot.validate_quantity(quantity)


@dataclass(frozen=True)
class PriceTick:
    """시장별/가격대별 호가 단위 (Tick Size)."""
    market: Market
    price_from: Decimal  # 이상
    price_to: Decimal    # 미만
    tick_size: Decimal

    def round_price(self, price: Decimal, direction: str = "nearest") -> Decimal:
        """가격을 호가 단위로 반올림.

        direction: "nearest" (기본), "up" (올림), "down" (내림)
        """
        if self.tick_size <= 0:
            return price
        if direction == "up":
            return ((price + self.tick_size - Decimal("0.0000001")) // self.tick_size) * self.tick_size
        elif direction == "down":
            return (price // self.tick_size) * self.tick_size
        else:  # nearest
            return ((price + self.tick_size / 2) // self.tick_size) * self.tick_size


# KRX 호가 단위 (가격대별)
KRX_PRICE_TICKS = [
    PriceTick(Market.KRX, Decimal("0"), Decimal("1000"), Decimal("1")),
    PriceTick(Market.KRX, Decimal("1000"), Decimal("5000"), Decimal("5")),
    PriceTick(Market.KRX, Decimal("5000"), Decimal("10000"), Decimal("10")),
    PriceTick(Market.KRX, Decimal("10000"), Decimal("50000"), Decimal("50")),
    PriceTick(Market.KRX, Decimal("50000"), Decimal("100000"), Decimal("100")),
    PriceTick(Market.KRX, Decimal("100000"), Decimal("500000"), Decimal("500")),
    PriceTick(Market.KRX, Decimal("500000"), Decimal("1000000"), Decimal("1000")),
    PriceTick(Market.KRX, Decimal("1000000"), Decimal("999999999"), Decimal("1000")),
]

# US 호가 단위 (미국 주식은 $0.01 단위, $1 미만은 $0.0001)
US_PRICE_TICKS = [
    PriceTick(Market.US, Decimal("0"), Decimal("1"), Decimal("0.0001")),
    PriceTick(Market.US, Decimal("1"), Decimal("999999999"), Decimal("0.01")),
]

MARKET_PRICE_TICKS = {
    Market.KRX: KRX_PRICE_TICKS,
    Market.US: US_PRICE_TICKS,
}


def get_price_ticks(market: Market) -> list[PriceTick]:
    """시장별 호가 단위 리스트 조회."""
    return MARKET_PRICE_TICKS.get(market, [])


def round_price(market: Market, price: Decimal, direction: str = "nearest") -> Decimal:
    """시장별 호가 단위로 가격 반올림."""
    ticks = get_price_ticks(market)
    for tick in ticks:
        if tick.price_from <= price < tick.price_to:
            return tick.round_price(price, direction)
    # 기본값: 마지막 tick 사용
    if ticks:
        return ticks[-1].round_price(price, direction)
    return price


@dataclass(frozen=True)
class OHLCV:
    """OHLCV 데이터."""
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    asset_id: str
    market: Market

    def is_valid(self) -> bool:
        """데이터 유효성 검사."""
        return (
            self.open >= 0 and self.high >= 0 and self.low >= 0 and self.close >= 0 and
            self.high >= self.low and
            self.high >= self.open and self.high >= self.close and
            self.low <= self.open and self.low <= self.close and
            self.volume >= 0
        )

    def typical_price(self) -> Decimal:
        """대표 가격 (HLC/3)."""
        return (self.high + self.low + self.close) / Decimal("3")

    def vwap_price(self) -> Decimal:
        """가중 평균 가격 근사 (OHLC/4)."""
        return (self.open + self.high + self.low + self.close) / Decimal("4")


@dataclass(frozen=True)
class Quote:
    """실시간 호가."""
    asset_id: str
    market: Market
    price: Decimal
    bid: Decimal | None
    ask: Decimal | None
    bid_size: int | None
    ask_size: int | None
    volume: int | None
    timestamp: datetime

    def spread(self) -> Decimal | None:
        """스프레드 (ask - bid)."""
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    def mid_price(self) -> Decimal | None:
        """중간 가격."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / Decimal("2")
        return self.price


def normalize_asset_id(raw: str, market: Market) -> str:
    """자산 ID 정규화.

    KRX: 6자리 종목코드 (예: 005930) -> KRX:005930
    US: 심볼 그대로 (예: AAPL) -> US:AAPL
    """
    raw = raw.strip().upper()
    if market == Market.KRX:
        if not raw.startswith("KRX:"):
            return f"KRX:{raw.zfill(6)}"
        return raw
    elif market == Market.US:
        if not raw.startswith("US:"):
            return f"US:{raw}"
        return raw
    return raw


def parse_asset_id(asset_id: str) -> tuple[Market, str]:
    """자산 ID 파싱 -> (시장, 심볼)."""
    if asset_id.startswith("KRX:"):
        return Market.KRX, asset_id[4:]
    elif asset_id.startswith("US:"):
        return Market.US, asset_id[3:]
    raise ValueError(f"알 수 없는 자산 ID 형식: {asset_id}")


def get_market_timezone(market: Market) -> timezone:
    """시장별 타임존 반환."""
    if market == Market.KRX:
        return timezone(datetime.now().astimezone().utcoffset())  # KST (UTC+9)
    elif market == Market.US:
        # 미국 동부 시간 (EST/EDT) - 간단히 UTC-5로 처리
        return timezone(datetime.now().astimezone().utcoffset())
    return UTC


def to_market_time(utc_dt: datetime, market: Market) -> datetime:
    """UTC 시간을 시장 현지 시간으로 변환."""
    tz = get_market_timezone(market)
    return utc_dt.astimezone(tz)


def to_utc(market_dt: datetime, market: Market) -> datetime:
    """시장 현지 시간을 UTC로 변환."""
    tz = get_market_timezone(market)
    if market_dt.tzinfo is None:
        market_dt = market_dt.replace(tzinfo=tz)
    return market_dt.astimezone(UTC)
