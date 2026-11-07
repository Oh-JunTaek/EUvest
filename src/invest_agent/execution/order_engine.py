"""주문 엔진 - 주문 생명주기 관리, 멱등성, 상태 머신."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from invest_agent.domain.enums import OrderSide, OrderStatus, OrderType
from invest_agent.market.market_data import AssetType, Market, round_price


class OrderEventType(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class OrderEvent:
    event_type: OrderEventType
    timestamp: datetime
    quantity: int | None = None
    price: Decimal | None = None
    message: str = ""
    broker_order_id: str | None = None


@dataclass
class Order:
    id: str
    idempotency_key: str
    asset_id: str
    market: Market
    asset_type: AssetType
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: Decimal | None
    status: OrderStatus
    filled_quantity: int = 0
    avg_fill_price: Decimal | None = None
    remaining_quantity: int = 0
    broker_order_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    submitted_at: datetime | None = None
    acknowledged_at: datetime | None = None
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    rejected_reason: str | None = None
    events: list[OrderEvent] = field(default_factory=list)

    def __post_init__(self):
        self.remaining_quantity = self.quantity - self.filled_quantity

    def can_transition_to(self, new_status: OrderStatus) -> bool:
        valid_transitions = {
            OrderStatus.INTENT_CREATED: {OrderStatus.PRECHECKED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
            OrderStatus.PRECHECKED: {OrderStatus.RESERVED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
            OrderStatus.RESERVED: {OrderStatus.SUBMITTING, OrderStatus.REJECTED, OrderStatus.CANCELLED},
            OrderStatus.SUBMITTING: {OrderStatus.ACKNOWLEDGED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
            OrderStatus.ACKNOWLEDGED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.UNKNOWN},
            OrderStatus.PARTIALLY_FILLED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED},
            OrderStatus.FILLED: {OrderStatus.CANCELLED},
            OrderStatus.CANCELLED: set(),
            OrderStatus.REJECTED: set(),
            OrderStatus.UNKNOWN: {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
            OrderStatus.MANUAL_REVIEW: {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
        }
        return new_status in valid_transitions.get(self.status, set())

    def transition_to(self, new_status: OrderStatus, **kwargs) -> bool:
        if not self.can_transition_to(new_status):
            return False

        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now(UTC)

        if new_status == OrderStatus.SUBMITTED:
            self.submitted_at = self.updated_at
        elif new_status == OrderStatus.ACKNOWLEDGED:
            self.acknowledged_at = self.updated_at
        elif new_status == OrderStatus.FILLED:
            self.filled_at = self.updated_at
        elif new_status == OrderStatus.CANCELLED:
            self.cancelled_at = self.updated_at

        event = OrderEvent(
            event_type=OrderEventType(new_status.value),
            timestamp=self.updated_at,
            quantity=kwargs.get("quantity"),
            price=kwargs.get("price"),
            message=kwargs.get("message", f"Status changed: {old_status} -> {new_status}"),
            broker_order_id=kwargs.get("broker_order_id"),
        )
        self.events.append(event)
        return True

    def fill(self, fill_qty: int, fill_price: Decimal) -> bool:
        if fill_qty <= 0 or fill_qty > self.remaining_quantity:
            return False

        if self.filled_quantity == 0:
            self.avg_fill_price = fill_price
        else:
            total_value = self.avg_fill_price * Decimal(str(self.filled_quantity)) + fill_price * Decimal(str(fill_qty))
            self.filled_quantity += fill_qty
            self.avg_fill_price = total_value / Decimal(str(self.filled_quantity))

        self.filled_quantity += fill_qty
        self.remaining_quantity = self.quantity - self.filled_quantity
        self.updated_at = datetime.now(UTC)

        new_status = OrderStatus.FILLED if self.remaining_quantity == 0 else OrderStatus.PARTIALLY_FILLED
        self.transition_to(new_status, quantity=fill_qty, price=fill_price, message=f"Filled {fill_qty} @ {fill_price}")
        return True

    def cancel(self, reason: str = "User cancelled") -> bool:
        if self.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return False
        return self.transition_to(OrderStatus.CANCELLED, message=reason)


class OrderEngine:
    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._idempotency_index: dict[str, str] = {}
        self._broker_order_index: dict[str, str] = {}

    def create_order(
        self,
        asset_id: str,
        market: Market,
        asset_type: AssetType,
        side: OrderSide,
        order_type: OrderType,
        quantity: int,
        price: Decimal | None = None,
        idempotency_key: str | None = None,
    ) -> Order:
        if idempotency_key and idempotency_key in self._idempotency_index:
            existing_id = self._idempotency_index[idempotency_key]
            return self._orders[existing_id]

        if order_type == OrderType.LIMIT and price is None:
            raise ValueError("지정가 주문에는 가격이 필요합니다")

        if price is not None:
            price = round_price(market, price, "down" if side == OrderSide.BUY else "up")

        order_id = str(uuid4())
        if not idempotency_key:
            idempotency_key = f"idemp_{order_id}"

        order = Order(
            id=order_id,
            idempotency_key=idempotency_key,
            asset_id=asset_id,
            market=market,
            asset_type=asset_type,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.INTENT_CREATED,
        )

        self._orders[order_id] = order
        self._idempotency_index[idempotency_key] = order_id

        return order

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def get_order_by_idempotency(self, key: str) -> Order | None:
        order_id = self._idempotency_index.get(key)
        if order_id:
            return self._orders.get(order_id)
        return None

    def get_order_by_broker_id(self, broker_order_id: str) -> Order | None:
        order_id = self._broker_order_index.get(broker_order_id)
        if order_id:
            return self._orders.get(order_id)
        return None

    def submit_order(self, order_id: str, broker_order_id: str | None = None) -> bool:
        order = self._orders.get(order_id)
        if not order:
            return False

        if not order.transition_to(OrderStatus.PRECHECKED):
            return False

        if not order.transition_to(OrderStatus.RESERVED):
            return False

        if not order.transition_to(OrderStatus.SUBMITTING, broker_order_id=broker_order_id):
            return False

        if broker_order_id:
            order.broker_order_id = broker_order_id
            self._broker_order_index[broker_order_id] = order_id

        return order.transition_to(OrderStatus.ACKNOWLEDGED, broker_order_id=broker_order_id)

    def acknowledge_order(self, order_id: str, broker_order_id: str) -> bool:
        order = self._orders.get(order_id)
        if not order:
            return False

        order.broker_order_id = broker_order_id
        self._broker_order_index[broker_order_id] = order_id

        return order.transition_to(OrderStatus.ACKNOWLEDGED, broker_order_id=broker_order_id)

    def fill_order(self, order_id: str, fill_qty: int, fill_price: Decimal) -> bool:
        order = self._orders.get(order_id)
        if not order:
            return False
        return order.fill(fill_qty, fill_price)

    def cancel_order(self, order_id: str, reason: str = "User cancelled") -> bool:
        order = self._orders.get(order_id)
        if not order:
            return False
        return order.cancel(reason)

    def reject_order(self, order_id: str, reason: str) -> bool:
        order = self._orders.get(order_id)
        if not order:
            return False
        order.rejected_reason = reason
        return order.transition_to(OrderStatus.REJECTED, message=reason)

    def get_active_orders(self) -> list[Order]:
        active_statuses = {
            OrderStatus.INTENT_CREATED,
            OrderStatus.PRECHECKED,
            OrderStatus.RESERVED,
            OrderStatus.SUBMITTING,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.UNKNOWN,
        }
        return [o for o in self._orders.values() if o.status in active_statuses]

    def get_orders_by_status(self, status: OrderStatus) -> list[Order]:
        return [o for o in self._orders.values() if o.status == status]


def create_order_engine() -> OrderEngine:
    return OrderEngine()
