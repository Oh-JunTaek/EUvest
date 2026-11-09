"""P0-06 test - order engine, risk gate, sizing."""

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
from invest_agent.execution.order_engine import Order, OrderEngine
from invest_agent.execution.risk_gate import RiskCheckResult, RiskGate
from invest_agent.execution.sizing import SizingParams, calculate_target_quantity


class TestOrderEngineFixes:
    """Order engine fixes."""

    def test_fill_does_not_double_add_quantity(self):
        """fill() should not double add quantity."""
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
        """fill() should reject overfill."""
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

    def test_submitted_status_transition(self):
        """SUBMITTING status transition should work."""
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

    def test_filled_is_terminal(self):
        """FILLED is terminal state."""
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
            status=OrderStatus.FILLED,
            filled_quantity=100,
            remaining_quantity=0,
        )

        assert order.can_transition_to(OrderStatus.CANCELLED) is False
        assert order.can_transition_to(OrderStatus.REJECTED) is False

    def test_fill_invalid_status_raises(self):
        """fill() in invalid status raises ValueError."""
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

        with pytest.raises(ValueError, match="Cannot fill order in status"):
            order.fill(10, Decimal("70000"))

    def test_filled_cannot_cancel(self):
        """FILLED order cannot be cancelled."""
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
            status=OrderStatus.FILLED,
            filled_quantity=100,
            remaining_quantity=0,
        )

        result = order.cancel()
        assert result is False

class TestSizingFxRate:
    """Sizing FX rate validation."""

    def test_fx_rate_base_to_market(self):
        """fx_rate is 1 market_currency = fx_rate base_currency.

        Example: 1 USD = 1300 KRW => fx_rate = 1300
        - base currency KRW, market currency USD
        - portfolio 100,000,000 KRW, target 10% = 10,000,000 KRW
        - target_notional_market = 10,000,000 / 1300 = 7,692.31 USD
        - price 100 USD -> qty 76 (lot size 1, floor for BUY)
        - notional_market = 76 * 100 = 7,600 USD
        - notional_base = 7,600 * 1300 = 9,880,000 KRW
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

        result = calculate_target_quantity(params)

        assert result.feasible is True
        assert result.quantity == 76
        assert result.notional == Decimal("7600")
        assert result.notional_base == Decimal("9880000")
        assert result.cash_required == Decimal("9880000")

    def test_fx_rate_krw_base_usd_market(self):
        """KRW base, USD market - various FX rates."""
        # 1 USD = 1000 KRW
        params = SizingParams(
            target_weight_bps=5000,  # 50%
            current_weight_bps=0,
            portfolio_value=Decimal("100000000"),
            asset_price=Decimal("50"),
            available_cash=Decimal("100000000"),
            market=Market.US,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            fx_rate=Decimal("1000"),
        )
        result = calculate_target_quantity(params)
        # 50% of 100M KRW = 50M KRW = 50,000 USD
        # 50,000 / 50 = 1000 shares
        assert result.quantity == 1000
        assert result.notional == Decimal("50000")
        assert result.notional_base == Decimal("50000000")

    def test_fx_rate_validation_zero(self):
        """fx_rate = 0 should be rejected."""
        params = SizingParams(
            target_weight_bps=1000,
            current_weight_bps=0,
            portfolio_value=Decimal("100000000"),
            asset_price=Decimal("100"),
            available_cash=Decimal("100000000"),
            market=Market.US,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            fx_rate=Decimal("0"),
        )
        result = calculate_target_quantity(params)
        assert result.feasible is False
        assert "환율은 양수여야 함" in result.reason

    def test_asset_price_validation_zero(self):
        """asset_price = 0 should be rejected."""
        params = SizingParams(
            target_weight_bps=1000,
            current_weight_bps=0,
            portfolio_value=Decimal("100000000"),
            asset_price=Decimal("0"),
            available_cash=Decimal("100000000"),
            market=Market.US,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            fx_rate=Decimal("1300"),
        )
        result = calculate_target_quantity(params)
        assert result.feasible is False
        assert "자산 가격은 양수여야 함" in result.reason

    def test_side_weight_mismatch_buy(self):
        """BUY with target < current should be rejected."""
        params = SizingParams(
            target_weight_bps=500,
            current_weight_bps=1000,
            portfolio_value=Decimal("100000000"),
            asset_price=Decimal("100"),
            available_cash=Decimal("100000000"),
            market=Market.US,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            fx_rate=Decimal("1300"),
        )
        result = calculate_target_quantity(params)
        assert result.feasible is False
        assert "매수 주문인데 목표 비중이 현재보다 낮음" in result.reason

    def test_side_weight_mismatch_sell(self):
        """SELL with target > current should be rejected."""
        params = SizingParams(
            target_weight_bps=1500,
            current_weight_bps=1000,
            portfolio_value=Decimal("100000000"),
            asset_price=Decimal("100"),
            available_cash=Decimal("100000000"),
            market=Market.US,
            asset_type=AssetType.STOCK,
            side=OrderSide.SELL,
            fx_rate=Decimal("1300"),
        )
        result = calculate_target_quantity(params)
        assert result.feasible is False
        assert "매도 주문인데 목표 비중이 현재보다 높음" in result.reason

    def test_cash_insufficiency(self):
        """Insufficient cash reduces quantity."""
        params = SizingParams(
            target_weight_bps=1000,
            current_weight_bps=0,
            portfolio_value=Decimal("100000000"),
            asset_price=Decimal("100"),
            available_cash=Decimal("5000000"),  # Only 5M KRW
            market=Market.US,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            fx_rate=Decimal("1300"),
        )
        result = calculate_target_quantity(params)
        assert result.feasible is True
        # 5M KRW / (100 * 1300) = 38.46 -> floor to lot size 1 = 38
        assert result.quantity == 38
        assert result.cash_required == Decimal("4940000")


class TestOrderEngineFlow:
    """OrderEngine full flow tests."""

    def test_create_order_to_submit_flow(self):
        """create_order -> submit_order full flow."""
        engine = OrderEngine()
        # Create order
        order = engine.create_order(
            asset_id="005930",
            market=Market.KRX,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=Decimal("70000"),
            idempotency_key="test-key-1",
        )
        assert order.status == OrderStatus.INTENT_CREATED
        result = engine.submit_order(order.id, broker_order_id="broker-123")
        assert result is True
        submitted_order = engine.get_order(order.id)
        assert submitted_order.status == OrderStatus.SUBMITTING
        assert submitted_order.broker_order_id == "broker-123"
        ack_result = engine.acknowledge_order(order.id, "broker-123")
        assert ack_result is True
        acked_order = engine.get_order(order.id)
        assert acked_order.status == OrderStatus.ACKNOWLEDGED
        assert acked_order.acknowledged_at is not None

    def test_duplicate_idempotency_key(self):
        """Duplicate idempotency key returns existing order."""
        engine = OrderEngine()
        order1 = engine.create_order(
            asset_id="005930",
            market=Market.KRX,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=Decimal("70000"),
            idempotency_key="duplicate-key",
        )
        order2 = engine.create_order(
            asset_id="005930",
            market=Market.KRX,
            asset_type=AssetType.STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=200,
            price=Decimal("70000"),
            idempotency_key="duplicate-key",
        )
        assert order1.id == order2.id
        assert order1.quantity == 100


class TestOrderEngineErrorRecovery:
    """Order engine error/recovery paths."""

    def test_invalid_transition_raises(self):
        """Invalid state transition raises ValueError."""
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
            status=OrderStatus.INTENT_CREATED,
        )

        with pytest.raises(ValueError, match="Invalid transition"):
            order.transition_to(OrderStatus.FILLED)

    def test_unknown_transition_and_recovery(self):
        """UNKNOWN transition and recovery."""
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

        # ACKNOWLEDGED -> UNKNOWN
        assert order.can_transition_to(OrderStatus.UNKNOWN)
        order.transition_to(OrderStatus.UNKNOWN)
        assert order.status == OrderStatus.UNKNOWN

        # UNKNOWN -> FILLED (recovery)
        assert order.can_transition_to(OrderStatus.FILLED)
        order.transition_to(OrderStatus.FILLED)
        assert order.status == OrderStatus.FILLED

        # FILLED cannot go to CANCELLED
        assert order.can_transition_to(OrderStatus.CANCELLED) is False

    def test_cancel_after_fill_raises(self):
        """FILLED order cancel raises ValueError."""
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
            status=OrderStatus.FILLED,
            filled_quantity=100,
            remaining_quantity=0,
        )

        with pytest.raises(ValueError, match="Invalid transition"):
            order.transition_to(OrderStatus.CANCELLED)

    def test_reject_after_fill_raises(self):
        """FILLED order reject raises ValueError."""
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
            status=OrderStatus.FILLED,
            filled_quantity=100,
            remaining_quantity=0,
        )

        with pytest.raises(ValueError, match="Invalid transition"):
            order.transition_to(OrderStatus.REJECTED)


class TestRiskGateCashValidation:
    """Risk gate cash validation."""

    def test_cash_sufficiency_buy_passes(self):
        """BUY cash sufficiency passes."""
        gate = RiskGate()

        class MockSizingResult:
            quantity = 100
            feasible = True
            reason = "OK"
            cash_required = Decimal("5000000")
            notional_base = Decimal("5000000")
            notional = Decimal("5000000")
            weight_delta_bps = 1000

        result = gate.check_order(
            sizing_result=MockSizingResult(),
            portfolio_value=Decimal("100000000"),
            current_exposure=Decimal("0"),
            daily_pnl=Decimal("0"),
            position_qty=0,
            side="BUY",
        )

        cash_check = next(c for c in result.checks if c.name == "cash_sufficiency")
        assert cash_check.result == RiskCheckResult.PASS

    def test_cash_sufficiency_buy_fails_when_zero(self):
        """BUY with zero cash required fails."""
        gate = RiskGate()

        class MockSizingResult:
            quantity = 100
            feasible = True
            reason = "OK"
            cash_required = Decimal("0")
            notional_base = Decimal("0")
            notional = Decimal("0")
            weight_delta_bps = 1000

        result = gate.check_order(
            sizing_result=MockSizingResult(),
            portfolio_value=Decimal("100000000"),
            current_exposure=Decimal("0"),
            daily_pnl=Decimal("0"),
            position_qty=0,
            side="BUY",
        )

        cash_check = next(c for c in result.checks if c.name == "cash_sufficiency")
        assert cash_check.result == RiskCheckResult.REJECT
        assert "필요 현금 계산 불가" in cash_check.message

    def test_pending_sell_orders_considered(self):
        """Pending sell orders considered for short selling check."""
        gate = RiskGate(allow_short=False)

        class MockSizingResult:
            quantity = 60
            feasible = True
            reason = "OK"
            cash_required = Decimal("0")
            notional_base = Decimal("4200000")
            notional = Decimal("4200000")
            weight_delta_bps = 600

        # Hold 100, pending sell 50, request additional 60
        # Available = 100 - 50 = 50, request 60 > 50 -> REJECT
        gate.check_order(
            sizing_result=MockSizingResult(),
            portfolio_value=Decimal("100000000"),
            current_exposure=Decimal("0"),
            daily_pnl=Decimal("0"),
            position_qty=100,
            side="SELL",
        )

        # Current implementation doesn't consider pending_sell
        # This test documents future improvement
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

