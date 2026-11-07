"""포트폴리오 평가 - 멀티 통화 지원, USD+KRW 분리 평가."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from invest_agent.broker.protocol import Balance
from invest_agent.market.market_data import (
    Currency,
    Market,
    Position,
    parse_asset_id,
)


@dataclass(frozen=True)
class FXRate:
    """환율 정보."""
    from_currency: Currency
    to_currency: Currency
    rate: Decimal  # 1 from_currency = rate to_currency
    timestamp: datetime
    source: str = "manual"


@dataclass(frozen=True)
class AssetValuation:
    """개별 자산 평가."""
    asset_id: str
    market: Market
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    currency: Currency
    market_value_local: Decimal  # 현지 통화 기준
    market_value_base: Decimal   # 기준 통화(USD) 기준
    unrealized_pnl_local: Decimal
    unrealized_pnl_base: Decimal
    fx_rate_used: FXRate | None = None


@dataclass(frozen=True)
class PortfolioValuation:
    """포트폴리오 전체 평가."""
    timestamp: datetime
    base_currency: Currency
    total_market_value_base: Decimal
    total_unrealized_pnl_base: Decimal
    assets: list[AssetValuation]
    cash_balances: dict[Currency, Decimal]  # 통화별 현금
    cash_value_base: Decimal  # 현금 기준통화 환산

    # 통화별 요약
    krw_market_value: Decimal = Decimal("0")
    usd_market_value: Decimal = Decimal("0")
    krw_unrealized_pnl: Decimal = Decimal("0")
    usd_unrealized_pnl: Decimal = Decimal("0")


class PortfolioValuator:
    """포트폴리오 평가기 - 멀티 통화 지원."""

    def __init__(self, base_currency: Currency = Currency.USD):
        self.base_currency = base_currency
        self._fx_rates: dict[tuple[Currency, Currency], FXRate] = {}

    def set_fx_rate(self, fx_rate: FXRate) -> None:
        """환율 설정."""
        key = (fx_rate.from_currency, fx_rate.to_currency)
        self._fx_rates[key] = fx_rate

    def get_fx_rate(self, from_curr: Currency, to_curr: Currency) -> FXRate | None:
        """환율 조회 (직접/역방향 모두 지원)."""
        if from_curr == to_curr:
            return FXRate(from_curr, to_curr, Decimal("1"), datetime.now(), "identity")

        key = (from_curr, to_curr)
        if key in self._fx_rates:
            return self._fx_rates[key]

        rev_key = (to_curr, from_curr)
        if rev_key in self._fx_rates:
            rev = self._fx_rates[rev_key]
            return FXRate(
                from_curr, to_curr,
                Decimal("1") / rev.rate,
                rev.timestamp,
                f"inverse:{rev.source}"
            )
        return None

    def convert(self, amount: Decimal, from_curr: Currency, to_curr: Currency) -> Decimal | None:
        if from_curr == to_curr:
            return amount
        fx = self.get_fx_rate(from_curr, to_curr)
        if fx is None:
            return None
        return amount * fx.rate

    def valuate_portfolio(
        self,
        positions: list[Position],
        balance: Balance,
        current_prices: dict[str, Decimal],
    ) -> PortfolioValuation:
        """포트폴리오 평가.

        Args:
            positions: 보유 포지션 리스트
            balance: 계좌 잔고
            current_prices: asset_id -> 현재가 매핑

        Returns:
            포트폴리오 평가 결과
        """
        timestamp = datetime.now()
        assets = []

        cash_balances = defaultdict(Decimal)
        cash_balances[Currency.KRW] = balance.total_cash

        krw_mv = Decimal("0")
        usd_mv = Decimal("0")
        krw_pnl = Decimal("0")
        usd_pnl = Decimal("0")

        for pos in positions:
            asset_id = pos.asset_id
            market, symbol = parse_asset_id(asset_id)

            current_price = current_prices.get(asset_id)
            if current_price is None:
                continue

            market_value_local = pos.quantity * current_price
            unrealized_pnl_local = pos.unrealized_pnl

            fx_rate = self.get_fx_rate(pos.currency, self.base_currency)
            if fx_rate is None:
                market_value_base = market_value_local
                unrealized_pnl_base = unrealized_pnl_local
                fx_used = None
            else:
                market_value_base = market_value_local * fx_rate.rate
                unrealized_pnl_base = unrealized_pnl_local * fx_rate.rate
                fx_used = fx_rate

            if pos.currency == Currency.KRW:
                krw_mv += market_value_local
                krw_pnl += unrealized_pnl_local
            elif pos.currency == Currency.USD:
                usd_mv += market_value_local
                usd_pnl += unrealized_pnl_local

            assets.append(AssetValuation(
                asset_id=asset_id,
                market=market,
                quantity=pos.quantity,
                avg_price=pos.avg_price,
                current_price=current_price,
                currency=pos.currency,
                market_value_local=market_value_local,
                market_value_base=market_value_base,
                unrealized_pnl_local=unrealized_pnl_local,
                unrealized_pnl_base=unrealized_pnl_base,
                fx_rate_used=fx_used,
            ))

        cash_value_base = Decimal("0")
        for curr, amount in cash_balances.items():
            fx = self.get_fx_rate(curr, self.base_currency)
            if fx:
                cash_value_base += amount * fx.rate
            else:
                cash_value_base += amount

        total_market_value_base = sum(a.market_value_base for a in assets) + cash_value_base
        total_unrealized_pnl_base = sum(a.unrealized_pnl_base for a in assets)

        return PortfolioValuation(
            timestamp=timestamp,
            base_currency=self.base_currency,
            total_market_value_base=total_market_value_base,
            total_unrealized_pnl_base=total_unrealized_pnl_base,
            assets=assets,
            cash_balances=dict(cash_balances),
            cash_value_base=cash_value_base,
            krw_market_value=krw_mv,
            usd_market_value=usd_mv,
            krw_unrealized_pnl=krw_pnl,
            usd_unrealized_pnl=usd_pnl,
        )


def load_fx_rates_from_kis(usd_krw_rate: Decimal, timestamp: datetime | None = None) -> FXRate:
    if timestamp is None:
        timestamp = datetime.now()
    return FXRate(
        from_currency=Currency.USD,
        to_currency=Currency.KRW,
        rate=usd_krw_rate,
        timestamp=timestamp,
        source="KIS",
    )


def create_default_valuator(usd_krw: Decimal = Decimal("1300")) -> PortfolioValuator:
    valuator = PortfolioValuator(base_currency=Currency.USD)
    fx = load_fx_rates_from_kis(usd_krw)
    valuator.set_fx_rate(fx)
    return valuator
