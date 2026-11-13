"""MockBroker - 키 없이 동작하는 테스트용 브로커 구현."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from invest_agent.broker.protocol import (
    Balance,
    BrokerProtocol,
    OrderSummary,
    Position,
    Quote,
)


class MockBroker(BrokerProtocol):
    """테스트/개발용 Mock 브로커.

    KIS API 키 없이도 동작하며, 설정된 시나리오 데이터를 반환한다.
    """

    def __init__(
        self,
        initial_cash: Decimal = Decimal("100000000"),
        initial_positions: dict[str, Decimal] | None = None,
        quotes: dict[str, Decimal] | None = None,
        fx_rate_usd_krw: Decimal = Decimal("1300"),
    ):
        self._environment = "MOCK"
        self._connected = True

        # 계좌 상태 (KRW 기준 현금 + USD 현금 분리)
        self._cash_krw = initial_cash
        self._cash_usd = Decimal("0")
        self._positions: dict[str, dict] = {}
        self._quotes: dict[str, Decimal] = quotes or {}
        self._orders: dict[str, dict] = {}
        self._fx_rate_usd_krw = fx_rate_usd_krw

        # 초기 포지션 설정
        if initial_positions:
            for asset_id, qty in initial_positions.items():
                price = self._quotes.get(asset_id, Decimal("10000"))
                self._positions[asset_id] = {
                    "quantity": qty,
                    "avg_price": price,
                    "current_price": price,
                    "currency": "USD" if asset_id.startswith("US:") else "KRW",
                }

    def set_fx_rate(self, fx_rate: Decimal) -> None:
        """환율 설정."""
        self._fx_rate_usd_krw = fx_rate

    def _convert_usd_to_krw(self, usd_amount: Decimal) -> Decimal:
        """USD를 KRW로 환산."""
        return usd_amount * self._fx_rate_usd_krw

    def _convert_krw_to_usd(self, krw_amount: Decimal) -> Decimal:
        """KRW를 USD로 환산."""
        if self._fx_rate_usd_krw == 0:
            return Decimal("0")
        return krw_amount / self._fx_rate_usd_krw

    @property
    def environment(self) -> str:
        return self._environment

    @property
    def is_connected(self) -> bool:
        return self._connected

    def health_check(self) -> bool:
        return self._connected

    def get_balance(self) -> Balance:
        # 총자산 계산 (모든 포지션을 KRW로 환산)
        total_equity = self._cash_krw
        for pos in self._positions.values():
            qty = pos["quantity"]
            curr_price = pos["current_price"]
            currency = pos.get("currency", "KRW")
            if currency == "USD":
                total_equity += qty * curr_price * self._fx_rate_usd_krw
            else:
                total_equity += qty * curr_price

        return Balance(
            currency="KRW",
            total_cash=self._cash_krw,
            available_cash=self._cash_krw,
            total_equity=total_equity,
            updated_at=datetime.now(UTC),
        )

    def get_positions(self) -> list[Position]:
        result = []
        for asset_id, pos in self._positions.items():
            qty = pos["quantity"]
            avg_price = pos["avg_price"]
            curr_price = pos["current_price"]
            currency = pos.get("currency", "KRW")
            market_value = qty * curr_price
            if currency == "USD":
                market_value = market_value * self._fx_rate_usd_krw
            result.append(Position(
                asset_id=asset_id,
                quantity=qty,
                avg_price=avg_price,
                current_price=curr_price,
                market_value=market_value,
                unrealized_pnl=qty * (curr_price - avg_price) * (self._fx_rate_usd_krw if currency == "USD" else Decimal("1")),
                currency=currency,
            ))
        return result

    def get_quote(self, asset_id: str) -> Quote:
        price = self._quotes.get(asset_id, Decimal("10000"))
        return Quote(
            asset_id=asset_id,
            price=price,
            bid=price - Decimal("10"),
            ask=price + Decimal("10"),
            volume=100000,
            timestamp=datetime.now(UTC),
        )

    def get_orders(self, status_filter: str | None = None) -> list[OrderSummary]:
        orders = list(self._orders.values())
        if status_filter:
            orders = [o for o in orders if o["status"] == status_filter]

        return [
            OrderSummary(
                order_id=o["order_id"],
                asset_id=o["asset_id"],
                side=o["side"],
                order_type=o["order_type"],
                quantity=o["quantity"],
                price=o["price"],
                status=o["status"],
                filled_quantity=o["filled_quantity"],
                filled_price=o["filled_price"],
                created_at=o["created_at"],
                updated_at=o["updated_at"],
            )
            for o in orders
        ]

    def get_order(self, order_id: str) -> OrderSummary | None:
        o = self._orders.get(order_id)
        if not o:
            return None
        return OrderSummary(
            order_id=o["order_id"],
            asset_id=o["asset_id"],
            side=o["side"],
            order_type=o["order_type"],
            quantity=o["quantity"],
            price=o["price"],
            status=o["status"],
            filled_quantity=o["filled_quantity"],
            filled_price=o["filled_price"],
            created_at=o["created_at"],
            updated_at=o["updated_at"],
        )

    # 테스트 헬퍼 메서드들
    def set_quote(self, asset_id: str, price: Decimal) -> None:
        """시세 설정."""
        self._quotes[asset_id] = price
        if asset_id in self._positions:
            self._positions[asset_id]["current_price"] = price

    def set_position(self, asset_id: str, quantity: Decimal, avg_price: Decimal) -> None:
        """포지션 설정."""
        self._positions[asset_id] = {
            "quantity": quantity,
            "avg_price": avg_price,
            "current_price": self._quotes.get(asset_id, avg_price),
        }

    def add_order(
        self,
        asset_id: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> str:
        """주문 추가 (테스트용)."""
        order_id = str(uuid4())
        now = datetime.now(UTC)
        self._orders[order_id] = {
            "order_id": order_id,
            "asset_id": asset_id,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "price": price,
            "status": "ACKNOWLEDGED",
            "filled_quantity": Decimal("0"),
            "filled_price": None,
            "created_at": now,
            "updated_at": now,
        }
        return order_id

    def fill_order(self, order_id: str, filled_qty: Decimal, filled_price: Decimal) -> bool:
        """주문 체결 처리 (테스트용)."""
        if order_id not in self._orders:
            return False
        o = self._orders[order_id]
        o["filled_quantity"] = filled_qty
        o["filled_price"] = filled_price
        o["status"] = "FILLED" if filled_qty >= o["quantity"] else "PARTIALLY_FILLED"
        o["updated_at"] = datetime.now(UTC)

        # 자산 통화 확인
        asset_id = o["asset_id"]
        is_usd = asset_id.startswith("US:")

        # 현금/포지션 업데이트
        if o["side"] == "BUY":
            if is_usd:
                # USD 자산: filled_price는 USD, KRW로 환산하여 현금 차감
                cost_krw = filled_qty * filled_price * self._fx_rate_usd_krw
                self._cash_krw -= cost_krw
            else:
                # KRW 자산: filled_price는 KRW
                cost_krw = filled_qty * filled_price
                self._cash_krw -= cost_krw

            if asset_id in self._positions:
                pos = self._positions[asset_id]
                pos["quantity"] += filled_qty
                # 평균 단가 업데이트 (가중 평균)
                total_qty = pos["quantity"]
                pos["avg_price"] = (
                    (pos["avg_price"] * (total_qty - filled_qty)) + (filled_price * filled_qty)
                ) / total_qty
            else:
                self._positions[asset_id] = {
                    "quantity": filled_qty,
                    "avg_price": filled_price,
                    "current_price": filled_price,
                    "currency": "USD" if is_usd else "KRW",
                }
        else:  # SELL
            if is_usd:
                proceeds_krw = filled_qty * filled_price * self._fx_rate_usd_krw
                self._cash_krw += proceeds_krw
            else:
                proceeds_krw = filled_qty * filled_price
                self._cash_krw += proceeds_krw

            if asset_id in self._positions:
                pos = self._positions[asset_id]
                pos["quantity"] -= filled_qty
                if pos["quantity"] <= 0:
                    del self._positions[asset_id]
            else:
                # 포지션이 없는데 매도하는 경우 (공매도 시뮬레이션)
                pass

        return True

    def cancel_order(self, order_id: str) -> bool:
        """주문 취소 (테스트용)."""
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
            self._orders[order_id]["updated_at"] = datetime.now(UTC)
            return True
        return False
