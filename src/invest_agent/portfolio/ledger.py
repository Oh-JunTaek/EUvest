"""현금 원장 - 예약/사용/해제, 멀티 통화, 감사 로그."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from invest_agent.domain.enums import Currency


class LedgerEntryType(StrEnum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ORDER_RESERVE = "ORDER_RESERVE"
    ORDER_RELEASE = "ORDER_RELEASE"
    ORDER_FILL = "ORDER_FILL"
    FEE = "FEE"
    TAX = "TAX"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    FX = "FX"


@dataclass
class LedgerEntry:
    id: str
    entry_type: LedgerEntryType
    currency: Currency
    amount: Decimal
    balance_after: Decimal
    reference_id: str | None = None
    description: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)


class CashLedger:
    def __init__(self):
        self._balances: dict[Currency, Decimal] = defaultdict(Decimal)
        self._entries: list[LedgerEntry] = []
        self._reservations: dict[str, Decimal] = {}

    def get_balance(self, currency: Currency) -> Decimal:
        return self._balances[currency]

    def get_available(self, currency: Currency) -> Decimal:
        total = self._balances[currency]
        reserved = sum(self._reservations.values())
        return total - reserved

    def get_reserved(self, order_id: str) -> Decimal:
        return self._reservations.get(order_id, Decimal("0"))

    def deposit(
        self,
        currency: Currency,
        amount: Decimal,
        reference_id: str | None = None,
        description: str = "입금",
    ) -> LedgerEntry:
        if amount <= 0:
            raise ValueError("입금액은 양수여야 합니다")

        self._balances[currency] += amount
        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.DEPOSIT,
            currency=currency,
            amount=amount,
            balance_after=self._balances[currency],
            reference_id=reference_id,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def withdraw(
        self,
        currency: Currency,
        amount: Decimal,
        reference_id: str | None = None,
        description: str = "출금",
    ) -> LedgerEntry:
        if amount <= 0:
            raise ValueError("출금액은 양수여야 합니다")

        available = self.get_available(currency)
        if amount > available:
            raise ValueError(f"가용 잔고 부족: {available} < {amount}")

        self._balances[currency] -= amount
        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.WITHDRAWAL,
            currency=currency,
            amount=-amount,
            balance_after=self._balances[currency],
            reference_id=reference_id,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def reserve_for_order(
        self,
        order_id: str,
        currency: Currency,
        amount: Decimal,
        description: str = "주문 예약",
    ) -> LedgerEntry:
        if amount <= 0:
            raise ValueError("예약액은 양수여야 합니다")

        available = self.get_available(currency)
        if amount > available:
            raise ValueError(f"가용 잔고 부족: {available} < {amount}")

        self._reservations[order_id] = amount
        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.ORDER_RESERVE,
            currency=currency,
            amount=-amount,
            balance_after=self.get_available(currency),
            reference_id=order_id,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def release_reservation(
        self,
        order_id: str,
        currency: Currency,
        description: str = "주문 예약 해제",
    ) -> LedgerEntry | None:
        amount = self._reservations.pop(order_id, Decimal("0"))
        if amount == 0:
            return None

        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.ORDER_RELEASE,
            currency=currency,
            amount=amount,
            balance_after=self.get_available(currency),
            reference_id=order_id,
            description=description,
        )
        self._entries.append(entry)
        return entry
    def fill_order(
        self,
        order_id: str,
        currency: Currency,
        amount: Decimal,
        side: str,
        description: str = '주문 체결',
    ) -> LedgerEntry:
        self.release_reservation(order_id, currency)

        if side == 'BUY':
            if amount > self.get_available(currency):
                raise ValueError(f'가용 잔고 부족: {self.get_available(currency)} < {amount}')
            self._balances[currency] -= amount
            entry_amount = -amount
        else:
            self._balances[currency] += amount
            entry_amount = amount

        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.ORDER_FILL,
            currency=currency,
            amount=entry_amount,
            balance_after=self._balances[currency],
            reference_id=order_id,
            description=f'{description} ({side})',
        )
        self._entries.append(entry)
        return entry

    def charge_fee(
        self,
        currency: Currency,
        amount: Decimal,
        reference_id: str | None = None,
        description: str = '수수료',
    ) -> LedgerEntry:
        if amount <= 0:
            raise ValueError('수수료는 양수여야 합니다')

        if amount > self.get_available(currency):
            raise ValueError(f'가용 잔고 부족: {self.get_available(currency)} < {amount}')

        self._balances[currency] -= amount
        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.FEE,
            currency=currency,
            amount=-amount,
            balance_after=self._balances[currency],
            reference_id=reference_id,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def charge_tax(
        self,
        currency: Currency,
        amount: Decimal,
        reference_id: str | None = None,
        description: str = '세금',
    ) -> LedgerEntry:
        if amount <= 0:
            raise ValueError('세금은 양수여야 합니다')

        if amount > self.get_available(currency):
            raise ValueError(f'가용 잔고 부족: {self.get_available(currency)} < {amount}')

        self._balances[currency] -= amount
        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.TAX,
            currency=currency,
            amount=-amount,
            balance_after=self._balances[currency],
            reference_id=reference_id,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def add_dividend(
        self,
        currency: Currency,
        amount: Decimal,
        reference_id: str | None = None,
        description: str = '배당',
    ) -> LedgerEntry:
        if amount <= 0:
            raise ValueError('배당금은 양수여야 합니다')

        self._balances[currency] += amount
        entry = LedgerEntry(
            id=str(uuid4()),
            entry_type=LedgerEntryType.DIVIDEND,
            currency=currency,
            amount=amount,
            balance_after=self._balances[currency],
            reference_id=reference_id,
            description=description,
        )
        self._entries.append(entry)
        return entry

    def get_entries(
        self,
        currency: Currency | None = None,
        entry_type: LedgerEntryType | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[LedgerEntry]:
        result = self._entries

        if currency:
            result = [e for e in result if e.currency == currency]
        if entry_type:
            result = [e for e in result if e.entry_type == entry_type]
        if start_time:
            result = [e for e in result if e.timestamp >= start_time]
        if end_time:
            result = [e for e in result if e.timestamp <= end_time]

        return result

    def get_entries_by_order(self, order_id: str) -> list[LedgerEntry]:
        return [e for e in self._entries if e.reference_id == order_id]

    def get_statement(
        self,
        currency: Currency,
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        entries = self.get_entries(currency=currency, start_time=start_time, end_time=end_time)

        deposits = sum(e.amount for e in entries if e.amount > 0)
        withdrawals = sum(-e.amount for e in entries if e.amount < 0)

        return {
            'currency': currency,
            'period_start': start_time,
            'period_end': end_time,
            'opening_balance': self._get_balance_at(currency, start_time),
            'closing_balance': self._balances[currency],
            'total_deposits': deposits,
            'total_withdrawals': withdrawals,
            'net_change': deposits - withdrawals,
            'entry_count': len(entries),
        }

    def _get_balance_at(self, currency: Currency, timestamp: datetime) -> Decimal:
        balance = Decimal('0')
        for entry in self._entries:
            if entry.currency == currency and entry.timestamp <= timestamp:
                balance += entry.amount
        return balance

    def audit(self) -> dict:
        issues = []

        for currency in Currency:
            calculated = sum(e.amount for e in self._entries if e.currency == currency)
            actual = self._balances[currency]
            if calculated != actual:
                issues.append(f'{currency}: 계산 잔고 {calculated} != 실제 잔고 {actual}')

        for order_id, amount in self._reservations.items():
            if amount <= 0:
                issues.append(f'예약 금액 0 이하: {order_id} = {amount}')

        return {
            'is_valid': len(issues) == 0,
            'issues': issues,
            'total_entries': len(self._entries),
            'balances': dict(self._balances),
            'active_reservations': len(self._reservations),
        }


def create_cash_ledger() -> CashLedger:
    return CashLedger()
