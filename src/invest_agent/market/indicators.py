"""기술적 지표 - 기본 OHLCV 기반 지표 계산."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from invest_agent.market.market_data import OHLCV


@dataclass
class MovingAverageResult:
    """이동평균 결과."""
    sma: Decimal | None  # 단순 이동평균
    ema: Decimal | None  # 지수 이동평균
    period: int


@dataclass
class BollingerBandsResult:
    """볼린저 밴드 결과."""
    upper: Decimal | None
    middle: Decimal | None
    lower: Decimal | None
    bandwidth: Decimal | None
    period: int
    std_dev: int


@dataclass
class RSIResult:
    """RSI 결과."""
    rsi: Decimal | None
    period: int


class TechnicalIndicators:
    """기술적 지표 계산기 (스트리밍/배치 지원)."""

    def __init__(self):
        self._price_buffer: deque[Decimal] = deque()
        self._ohlcv_buffer: deque[OHLCV] = deque()

    def add_price(self, price: Decimal) -> None:
        """가격 추가 (SMA/EMA용)."""
        self._price_buffer.append(price)

    def add_ohlcv(self, ohlcv: OHLCV) -> None:
        """OHLCV 추가."""
        self._ohlcv_buffer.append(ohlcv)

    def sma(self, period: int) -> Decimal | None:
        """단순 이동평균 (SMA)."""
        if len(self._price_buffer) < period:
            return None
        prices = list(self._price_buffer)[-period:]
        return sum(prices) / Decimal(str(period))

    def ema(self, period: int, smoothing: Decimal = Decimal("2")) -> Decimal | None:
        """지수 이동평균 (EMA).

        EMA = Price * k + EMA_prev * (1 - k)
        k = 2 / (period + 1)
        """
        if len(self._price_buffer) < period:
            return None

        prices = list(self._price_buffer)[-period:]
        k = smoothing / Decimal(str(period + 1))

        # 첫 EMA는 SMA로 초기화
        ema = sum(prices[:period]) / Decimal(str(period))

        for price in prices[period:]:
            ema = price * k + ema * (Decimal("1") - k)

        return ema

    def moving_average(self, period: int) -> MovingAverageResult:
        """SMA/EMA 동시 계산."""
        return MovingAverageResult(
            sma=self.sma(period),
            ema=self.ema(period),
            period=period,
        )

    def bollinger_bands(self, period: int = 20, std_dev: int = 2) -> BollingerBandsResult:
        """볼린저 밴드 계산.

        Middle = SMA(period)
        Upper = Middle + std_dev * StdDev(period)
        Lower = Middle - std_dev * StdDev(period)
        """
        if len(self._price_buffer) < period:
            return BollingerBandsResult(None, None, None, None, period, std_dev)

        prices = list(self._price_buffer)[-period:]
        mean = sum(prices) / Decimal(str(period))

        # 표준편차 계산
        variance = sum((p - mean) ** 2 for p in prices) / Decimal(str(period))
        std = variance ** Decimal("0.5")

        upper = mean + Decimal(str(std_dev)) * std
        lower = mean - Decimal(str(std_dev)) * std
        bandwidth = (upper - lower) / mean if mean != 0 else None

        return BollingerBandsResult(
            upper=upper,
            middle=mean,
            lower=lower,
            bandwidth=bandwidth,
            period=period,
            std_dev=std_dev,
        )

    def rsi(self, period: int = 14) -> RSIResult:
        """RSI (Relative Strength Index) 계산.

        RSI = 100 - 100 / (1 + RS)
        RS = Average Gain / Average Loss
        """
        if len(self._price_buffer) < period + 1:
            return RSIResult(None, period)

        prices = list(self._price_buffer)[-(period + 1):]

        gains = []
        losses = []

        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(Decimal("0"))
            else:
                gains.append(Decimal("0"))
                losses.append(abs(change))

        avg_gain = sum(gains) / Decimal(str(period))
        avg_loss = sum(losses) / Decimal(str(period))

        if avg_loss == 0:
            rsi = Decimal("100")
        else:
            rs = avg_gain / avg_loss
            rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))

        return RSIResult(rsi=rsi, period=period)

    def atr(self, period: int = 14) -> Decimal | None:
        """ATR (Average True Range) 계산.

        True Range = max(H-L, |H-PrevClose|, |L-PrevClose|)
        """
        if len(self._ohlcv_buffer) < period + 1:
            return None

        ohlcvs = list(self._ohlcv_buffer)[-(period + 1):]
        true_ranges = []

        for i in range(1, len(ohlcvs)):
            curr = ohlcvs[i]
            prev = ohlcvs[i - 1]

            tr1 = curr.high - curr.low
            tr2 = abs(curr.high - prev.close)
            tr3 = abs(curr.low - prev.close)

            true_range = max(tr1, tr2, tr3)
            true_ranges.append(true_range)

        return sum(true_ranges) / Decimal(str(len(true_ranges)))

    def clear(self) -> None:
        """버퍼 초기화."""
        self._price_buffer.clear()
        self._ohlcv_buffer.clear()


def calculate_sma(prices: list[Decimal], period: int) -> Decimal | None:
    """단순 이동평균 배치 계산."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / Decimal(str(period))


def calculate_ema(prices: list[Decimal], period: int, smoothing: Decimal = Decimal("2")) -> Decimal | None:
    """지수 이동평균 배치 계산."""
    if len(prices) < period:
        return None

    k = smoothing / Decimal(str(period + 1))
    ema = sum(prices[:period]) / Decimal(str(period))

    for price in prices[period:]:
        ema = price * k + ema * (Decimal("1") - k)

    return ema


def calculate_rsi(prices: list[Decimal], period: int = 14) -> Decimal | None:
    """RSI 배치 계산."""
    if len(prices) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(change))

    if len(gains) < period:
        return None

    avg_gain = sum(gains[-period:]) / Decimal(str(period))
    avg_loss = sum(losses[-period:]) / Decimal(str(period))

    if avg_loss == 0:
        return Decimal("100")

    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def calculate_bollinger_bands(prices: list[Decimal], period: int = 20, std_dev: int = 2) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """볼린저 밴드 배치 계산 -> (upper, middle, lower)."""
    if len(prices) < period:
        return None, None, None

    recent = prices[-period:]
    mean = sum(recent) / Decimal(str(period))

    variance = sum((p - mean) ** 2 for p in recent) / Decimal(str(period))
    std = variance ** Decimal("0.5")

    upper = mean + Decimal(str(std_dev)) * std
    lower = mean - Decimal(str(std_dev)) * std

    return upper, mean, lower
