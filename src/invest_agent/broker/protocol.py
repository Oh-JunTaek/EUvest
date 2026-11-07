"""브로커 프로토콜 - 브로커 인터페이스 정의.

이 모듈은 모든 브로커 구현이 준수해야 하는 프로토콜(인터페이스)을 정의한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class Balance:
    """계좌 잔고."""
    currency: str
    total_cash: Decimal
    available_cash: Decimal
    total_equity: Decimal
    updated_at: datetime


@dataclass(frozen=True)
class Position:
    """보유 포지션."""
    asset_id: str
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    currency: str


@dataclass(frozen=True)
class Quote:
    """현재가 호가."""
    asset_id: str
    price: Decimal
    bid: Decimal | None
    ask: Decimal | None
    volume: int | None
    timestamp: datetime


@dataclass(frozen=True)
class OrderSummary:
    """주문 요약."""
    order_id: str
    asset_id: str
    side: Literal["BUY", "SELL"]
    order_type: Literal["LIMIT", "MARKET"]
    quantity: Decimal
    price: Decimal | None
    status: str
    filled_quantity: Decimal
    filled_price: Decimal | None
    created_at: datetime
    updated_at: datetime


class BrokerProtocol(ABC):
    """브로커 추상 인터페이스 (읽기 전용)."""

    @abstractmethod
    def get_balance(self) -> Balance:
        """계좌 잔고 조회."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """보유 포지션 목록 조회."""
        ...

    @abstractmethod
    def get_quote(self, asset_id: str) -> Quote:
        """현재가 조회."""
        ...

    @abstractmethod
    def get_orders(self, status_filter: str | None = None) -> list[OrderSummary]:
        """주문 내역 조회."""
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> OrderSummary | None:
        """단일 주문 조회."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """연결 상태 확인."""
        ...

    @property
    @abstractmethod
    def environment(self) -> Literal["MOCK", "PAPER", "LIVE"]:
        """브로커 환경."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """연결 여부."""
        ...
