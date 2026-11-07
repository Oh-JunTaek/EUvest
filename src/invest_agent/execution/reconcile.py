"""대사/정산 - 브로커 ↔ 원장 동기화."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from invest_agent.broker.protocol import Balance, OrderSummary, Position
from invest_agent.execution.order_engine import Order


@dataclass
class ReconcileResult:
    """대사 결과."""
    matched: int
    mismatched: int
    missing_in_broker: int
    missing_in_ledger: int
    details: list[str]
    timestamp: datetime


class Reconciler:
    """주문/포지션/잔고 대사."""

    def __init__(self):
        pass

    def reconcile_orders(
        self,
        ledger_orders: list[Order],
        broker_orders: list[OrderSummary],
    ) -> ReconcileResult:
        """주문 대사."""
        ledger_map = {o.id: o for o in ledger_orders}
        broker_map = {o.order_id: o for o in broker_orders}

        matched = 0
        mismatched = 0
        missing_in_broker = 0
        missing_in_ledger = 0
        details = []

        # 원장에 있는데 브로커에 없는 것
        for order_id, order in ledger_map.items():
            if order_id not in broker_map:
                missing_in_broker += 1
                details.append(f"Missing in broker: {order_id} ({order.status})")
            else:
                broker_order = broker_map[order_id]
                # 상태 비교
                if order.status != broker_order.status:
                    mismatched += 1
                    details.append(f"Status mismatch {order_id}: ledger={order.status}, broker={broker_order.status}")
                # 체결 수량 비교
                elif order.filled_quantity != broker_order.filled_quantity:
                    mismatched += 1
                    details.append(f"Fill qty mismatch {order_id}: ledger={order.filled_quantity}, broker={broker_order.filled_quantity}")
                else:
                    matched += 1

        # 브로커에 있는데 원장에 없는 것
        for order_id in broker_map:
            if order_id not in ledger_map:
                missing_in_ledger += 1
                details.append(f"Missing in ledger: {order_id}")

        return ReconcileResult(
            matched=matched,
            mismatched=mismatched,
            missing_in_broker=missing_in_broker,
            missing_in_ledger=missing_in_ledger,
            details=details,
            timestamp=datetime.now(),
        )

    def reconcile_positions(
        self,
        ledger_positions: list,  # 내부 Position 객체들
        broker_positions: list[Position],
    ) -> ReconcileResult:
        """포지션 대사."""
        # 자산 ID로 매핑
        ledger_map = {p.asset_id: p for p in ledger_positions}
        broker_map = {p.asset_id: p for p in broker_positions}

        matched = 0
        mismatched = 0
        missing_in_broker = 0
        missing_in_ledger = 0
        details = []

        all_assets = set(ledger_map.keys()) | set(broker_map.keys())

        for asset_id in all_assets:
            ledger_pos = ledger_map.get(asset_id)
            broker_pos = broker_map.get(asset_id)

            if ledger_pos and not broker_pos:
                missing_in_broker += 1
                details.append(f"Position missing in broker: {asset_id}")
            elif broker_pos and not ledger_pos:
                missing_in_ledger += 1
                details.append(f"Position missing in ledger: {asset_id}")
            else:
                # 수량 비교
                if ledger_pos.quantity != broker_pos.quantity:
                    mismatched += 1
                    details.append(f"Qty mismatch {asset_id}: ledger={ledger_pos.quantity}, broker={broker_pos.quantity}")
                # 평균가 비교 (소수점 허용)
                elif abs(ledger_pos.avg_price - broker_pos.avg_price) > Decimal("0.01"):
                    mismatched += 1
                    details.append(f"Avg price mismatch {asset_id}: ledger={ledger_pos.avg_price}, broker={broker_pos.avg_price}")
                else:
                    matched += 1

        return ReconcileResult(
            matched=matched,
            mismatched=mismatched,
            missing_in_broker=missing_in_broker,
            missing_in_ledger=missing_in_ledger,
            details=details,
            timestamp=datetime.now(),
        )

    def reconcile_balance(
        self,
        ledger_cash: Decimal,
        broker_balance: Balance,
        tolerance: Decimal = Decimal("1"),
    ) -> ReconcileResult:
        """잔고 대사."""
        diff = abs(ledger_cash - broker_balance.available_cash)

        if diff <= tolerance:
            return ReconcileResult(
                matched=1,
                mismatched=0,
                missing_in_broker=0,
                missing_in_ledger=0,
                details=[f"Balance OK: ledger={ledger_cash}, broker={broker_balance.available_cash}"],
                timestamp=datetime.now(),
            )
        else:
            return ReconcileResult(
                matched=0,
                mismatched=1,
                missing_in_broker=0,
                missing_in_ledger=0,
                details=[f"Balance mismatch: ledger={ledger_cash}, broker={broker_balance.available_cash}, diff={diff}"],
                timestamp=datetime.now(),
            )


def create_reconciler() -> Reconciler:
    return Reconciler()
