"""주문 사이징 - 목표 비중/현금 → 주문 수량 변환."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from invest_agent.domain.enums import OrderSide
from invest_agent.market.market_data import (
    AssetType,
    Market,
    get_lot_size,
    round_price,
    validate_quantity,
)


@dataclass(frozen=True)
class SizingParams:
    """사이징 파라미터."""
    target_weight_bps: int      # 목표 비중 (basis points, 10000 = 100%)
    current_weight_bps: int     # 현재 비중 (basis points)
    portfolio_value: Decimal    # 총 포트폴리오 가치 (기준 통화)
    asset_price: Decimal        # 자산 현재가 (해당 시장 통화)
    available_cash: Decimal     # 가용 현금 (해당 시장 통화)
    market: Market              # 시장
    asset_type: AssetType       # 자산 유형
    side: OrderSide             # 매수/매도
    fx_rate: Decimal = Decimal("1")  # 1 base_currency = fx_rate market_currency (예: 1 USD = 1300 KRW)


@dataclass(frozen=True)
class SizingResult:
    """사이징 결과."""
    quantity: int               # 주문 수량 (lot 단위 반올림)
    notional: Decimal           # 주문 명목가액 (시장 통화)
    notional_base: Decimal      # 주문 명목가액 (기준 통화)
    weight_delta_bps: int       # 비중 변화 (bps)
    cash_required: Decimal      # 필요 현금 (시장 통화, 매수 시 양수)
    feasible: bool              # 실행 가능 여부
    reason: str                 # 불가 시 사유


def calculate_target_quantity(params: SizingParams) -> SizingResult:
    """목표 비중 달성 필요 수량 계산.

    Args:
        params: 사이징 파라미터

    Returns:
        계산된 주문 수량과 관련 정보
    """
    # 비중 차이 계산 (bps)
    weight_delta_bps = params.target_weight_bps - params.current_weight_bps

    # 매도인 경우 현재 보유량 확인 필요 (여기서는 목표 비중 기준으로 계산)
    if weight_delta_bps == 0:
        return SizingResult(
            quantity=0,
            notional=Decimal("0"),
            notional_base=Decimal("0"),
            weight_delta_bps=0,
            cash_required=Decimal("0"),
            feasible=True,
            reason="비중 변경 없음",
        )

    # 목표 명목가액 계산 (기준 통화)
    target_notional_base = params.portfolio_value * Decimal(str(abs(weight_delta_bps))) / Decimal("10000")

    # 시장 통화로 환산
    target_notional_market = target_notional_base * params.fx_rate

    # 필요 수량 계산 (소수점 허용 후 lot 단위 반올림)
    raw_quantity = target_notional_market / params.asset_price

    # Lot size 적용
    lot = get_lot_size(params.market, params.asset_type)
    lot_size = lot.lot_size
    min_qty = lot.min_quantity

    # 수량을 lot 단위로 반올림 (내림으로 안전한 쪽)
    if params.side == OrderSide.BUY:
        quantity = int(raw_quantity // lot_size) * lot_size
    else:
        quantity = int((raw_quantity + lot_size - 1) // lot_size) * lot_size  # 올림

    if quantity < min_qty:
        return SizingResult(
            quantity=0,
            notional=Decimal("0"),
            notional_base=Decimal("0"),
            weight_delta_bps=weight_delta_bps,
            cash_required=Decimal("0"),
            feasible=False,
            reason=f"최소 주문 수량 미달: {quantity} < {min_qty}",
        )

    # 수량 유효성 검사
    if not validate_quantity(params.market, params.asset_type, quantity):
        return SizingResult(
            quantity=0,
            notional=Decimal("0"),
            notional_base=Decimal("0"),
            weight_delta_bps=weight_delta_bps,
            cash_required=Decimal("0"),
            feasible=False,
            reason="주문 수량 유효성 검사 실패",
        )

    # 호가 단위로 가격 반올림 (매수: 내림, 매도: 올림)
    direction = "down" if params.side == OrderSide.BUY else "up"
    rounded_price = round_price(params.market, params.asset_price, direction)

    # 최종 명목가액
    notional_market = rounded_price * Decimal(str(quantity))
    notional_base = notional_market / params.fx_rate

    # 현금 필요액
    cash_required = notional_market if params.side == OrderSide.BUY else Decimal("0")

    # 가용 현금 확인
    if params.side == OrderSide.BUY and cash_required > params.available_cash:
        # 가용 현금에 맞춰 수량 축소
        max_qty = int((params.available_cash / rounded_price) // lot_size) * lot_size
        if max_qty >= min_qty:
            quantity = max_qty
            notional_market = rounded_price * Decimal(str(quantity))
            notional_base = notional_market / params.fx_rate
            cash_required = notional_market
        else:
            return SizingResult(
                quantity=0,
                notional=Decimal("0"),
                notional_base=Decimal("0"),
                weight_delta_bps=weight_delta_bps,
                cash_required=Decimal("0"),
                feasible=False,
                reason=f"가용 현금 부족: 필요 {cash_required}, 보유 {params.available_cash}",
            )

    return SizingResult(
        quantity=quantity,
        notional=notional_market,
        notional_base=notional_base,
        weight_delta_bps=weight_delta_bps,
        cash_required=cash_required,
        feasible=True,
        reason="OK",
    )


def calculate_sizing(
    target_weight_bps: int,
    current_weight_bps: int,
    portfolio_value: Decimal,
    asset_price: Decimal,
    available_cash: Decimal,
    market: Market,
    asset_type: AssetType,
    side: OrderSide,
    fx_rate: Decimal = Decimal("1"),
) -> SizingResult:
    """편의 함수: 파라미터 직접 전달."""
    params = SizingParams(
        target_weight_bps=target_weight_bps,
        current_weight_bps=current_weight_bps,
        portfolio_value=portfolio_value,
        asset_price=asset_price,
        available_cash=available_cash,
        market=market,
        asset_type=asset_type,
        side=side,
        fx_rate=fx_rate,
    )
    return calculate_target_quantity(params)
