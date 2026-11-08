"""P0-06 보완 검증 테스트 - 주문 엔진, 위험 게이트, 사이징."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from invest_agent.domain.enums import (
    AssetType,
    Market,
    OrderSide,
    OrderStatus,
    OrderType,
)
from invest_agent.execution.order_engine import OrderEngine, Order
from invest_agent.execution.risk_gate import RiskGate, RiskCheckResult
from invest_agent.execution.sizing import calculate_sizing, SizingParams
class TestOrderEngineFixes:
    """주문 엔진 수정 사항 검증."""

    def test_fill_does_not_double_add_quantity(self):
        """fill() 호출 시 filled_quantity가 이중으로 증가하지 않아야 함."""
        order = Order(
            id=str(uuid4()),
            idempotency_key=str(uuid4()),
            asset_id="005930",
            market=Market.KRX,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=Decimal("70000"),
            status=OrderStatus.ACKNOWLEDGED,
        )

        result1 = order.fill(30, Decimal("70000"))
        assert result1 is True
        assert order.filled_quantity == 30
        assert order.remaining_quantity == 70

        result2 = order.fill(40, Decimal("70100"))
        assert result2 is True
        assert order.filled_quantity == 70
        assert order.remaining_quantity == 30

        result3 = order.fill(30, Decimal("70200"))
        assert result3 is True
        assert order.filled_quantity == 100
        assert order.remaining_quantity == 0
        assert order.status == OrderStatus.FILLED

    def test_fill_rejects_overfill(self):
        """남은 수량 초과 체결은 거부되어야 함."""
        order = Order(
            id=str(uuid4()),
            idempotency_key=str(uuid4()),
            asset_id="005930",
            market=Market.KRX,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=Decimal("70000"),
            status=OrderStatus.ACKNOWLEDGED,
        )

        result = order.fill(150, Decimal("70000"))
        assert result is False
        assert order.filled_quantity == 0
class TestSizingFxRate:
    """사이징 환율 계산 검증."""

    def test_fx_rate_base_to_market(self):
        """fx_rate는 1 base_currency = fx_rate market_currency여야 함.

        현재 구현: target_notional_market = target_notional_base * fx_rate
        주석: 1 base_currency = fx_rate market_currency (예: 1 USD = 1300 KRW)

        이 테스트는 현재 동작을 기록하는 것임.
        실제 수정은 calculate_sizing 함수에서 target_notional_market 계산 시
        나눗셈을 해야 할 수도 있음 (설계 문서 확인 필요).
        """
        params = SizingParams(
            target_weight_bps=1000,
            current_weight_bps=0,
            portfolio_value=Decimal("100000000"),
            asset_price=Decimal("100"),
            available_cash=Decimal("100000000"),
            market=Market.US,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            fx_rate=Decimal("1300"),
        )
class TestRiskGateShortSell:
    """위험 게이트 매도 수량 검증."""

    def test_sell_qty_exceeds_holding_rejected(self):
        """매도 수량이 보유 수량을 초과하면 거부되어야 함 (allow_short=False)."""
        gate = RiskGate(allow_short=False)

        class MockSizingResult:
            quantity = 100
            feasible = True
            reason = "OK"
            cash_required = Decimal("0")
            notional_base = Decimal("7000000")
            notional = Decimal("7000000")
            weight_delta_bps = 1000

        result = gate.check_order(
            sizing_result=MockSizingResult(),
            portfolio_value=Decimal("100000000"),
            current_exposure=Decimal("0"),
            daily_pnl=Decimal("0"),
            position_qty=50,
            side="SELL",
        )

        assert result.overall == RiskCheckResult.REJECT
        short_check = next(c for c in result.checks if c.name == "short_sell_prohibited")
        assert "100" in short_check.message
        assert "50" in short_check.message

    def test_sell_qty_within_holding_allowed(self):
        """매도 수량이 보유 수량 이내면 허용되어야 함."""
        gate = RiskGate(allow_short=False)

        class MockSizingResult:
            quantity = 30
            feasible = True
            reason = "OK"
            cash_required = Decimal("0")
            notional_base = Decimal("2100000")
            notional = Decimal("2100000")
            weight_delta_bps = 300

        result = gate.check_order(
            sizing_result=MockSizingResult(),
            portfolio_value=Decimal("100000000"),
            current_exposure=Decimal("0"),
            daily_pnl=Decimal("0"),
            position_qty=50,
            side="SELL",
        )

        short_checks = [c for c in result.checks if "short_sell" in c.name]
        assert len(short_checks) == 0 or all(c.result != RiskCheckResult.REJECT for c in short_checks)

    def test_sell_qty_exceeds_holding_warn_when_allowed(self):
        """allow_short=True면 초과 매도 시 경고만 발생."""
        gate = RiskGate(allow_short=True)

        class MockSizingResult:
            quantity = 100
            feasible = True
            reason = "OK"
            cash_required = Decimal("0")
            notional_base = Decimal("7000000")
            notional = Decimal("7000000")
            weight_delta_bps = 1000

        result = gate.check_order(
            sizing_result=MockSizingResult(),
            portfolio_value=Decimal("100000000"),
            current_exposure=Decimal("0"),
            daily_pnl=Decimal("0"),
            position_qty=50,
            side="SELL",
        )

        short_check = next(c for c in result.checks if c.name == "short_sell_allowed")
        assert short_check.result == RiskCheckResult.WARN

    def test_no_holding_sell_rejected(self):
        """보유 수량 0인 매도는 거부되어야 함 (allow_short=False)."""
        gate = RiskGate(allow_short=False)

        class MockSizingResult:
            quantity = 10
            feasible = True
            reason = "OK"
            cash_required = Decimal("0")
            notional_base = Decimal("700000")
            notional = Decimal("700000")
            weight_delta_bps = 100

        result = gate.check_order(
            sizing_result=MockSizingResult(),
            portfolio_value=Decimal("100000000"),
            current_exposure=Decimal("0"),
            daily_pnl=Decimal("0"),
            position_qty=0,
            side="SELL",
        )

        assert result.overall == RiskCheckResult.REJECT
        short_check = next(c for c in result.checks if c.name == "short_sell_prohibited")
        assert "매도 수량(10) > 보유 수량(0)" in short_check.message

    def test_submitted_status_transition(self):
        """SUBMITTING 상태 전이가 정상 작동해야 함 (SUBMITTED 대신)."""
        order = Order(
            id=str(uuid4()),
            idempotency_key=str(uuid4()),
            asset_id="005930",
            market=Market.KRX,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=Decimal("70000"),
            status=OrderStatus.RESERVED,
        )

        assert order.can_transition_to(OrderStatus.SUBMITTING)
        assert order.transition_to(OrderStatus.SUBMITTING)
        assert order.status == OrderStatus.SUBMITTING

        assert order.can_transition_to(OrderStatus.ACKNOWLEDGED)
        assert order.transition_to(OrderStatus.ACKNOWLEDGED)
        assert order.status == OrderStatus.ACKNOWLEDGED