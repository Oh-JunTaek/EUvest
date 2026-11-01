"""도메인 모델 - 투자 시스템의 핵심 데이터 구조."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class DecisionOutcome(StrEnum):
    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    INTENT_CREATED = "INTENT_CREATED"
    PRECHECKED = "PRECHECKED"
    REJECTED = "REJECTED"
    RESERVED = "RESERVED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNKNOWN = "UNKNOWN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class EvidenceType(StrEnum):
    PRICE = "PRICE"
    FUNDAMENTAL = "FUNDAMENTAL"
    NEWS = "NEWS"
    TECHNICAL = "TECHNICAL"
    FILING = "FILING"
    MACRO = "MACRO"
    OTHER = "OTHER"


@dataclass(slots=True)
class Thesis:
    id: UUID = field(default_factory=uuid4)
    asset_id: str = ""
    hypothesis: str = ""
    rationale: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())
    updated_at: datetime = field(default_factory=lambda: datetime.utcnow())
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Evidence:
    id: UUID = field(default_factory=uuid4)
    thesis_id: UUID = UUID(int=0)
    evidence_type: EvidenceType = EvidenceType.OTHER
    source: str = ""
    observed_at: datetime = field(default_factory=lambda: datetime.utcnow())
    collected_at: datetime = field(default_factory=lambda: datetime.utcnow())
    content: dict[str, Any] = field(default_factory=dict)
    raw_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Decision:
    id: UUID = field(default_factory=uuid4)
    thesis_id: UUID = UUID(int=0)
    run_id: UUID = UUID(int=0)
    outcome: DecisionOutcome = DecisionOutcome.NO_TRADE
    side: OrderSide | None = None
    target_weight_bps: int | None = None
    current_weight_bps: int | None = None
    rationale: str = ""
    evidence_ids: list[UUID] = field(default_factory=list)
    model_provider: str = ""
    model_name: str = ""
    execution_mode: str = ""
    decided_at: datetime = field(default_factory=lambda: datetime.utcnow())
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RunStatus(StrEnum):
    CREATED = "CREATED"
    RECONCILING = "RECONCILING"
    COLLECTING = "COLLECTING"
    DECIDING = "DECIDING"
    VALIDATING = "VALIDATING"
    EXECUTING = "EXECUTING"
    RECONCILING_ORDERS = "RECONCILING_ORDERS"
    COMPLETED = "COMPLETED"
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SKIPPED_ALREADY_RUNNING = "SKIPPED_ALREADY_RUNNING"
@dataclass(slots=True)
class AgentRun:
    id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.utcnow())
    completed_at: datetime | None = None
    status: RunStatus = RunStatus.CREATED
    execution_mode: str = ""
    schedule_id: str | None = None
    thesis_ids: list[UUID] = field(default_factory=list)
    decision_ids: list[UUID] = field(default_factory=list)
    order_ids: list[UUID] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRecord:
    id: UUID = field(default_factory=uuid4)
    run_id: UUID = UUID(int=0)
    decision_id: UUID = UUID(int=0)
    asset_id: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: str = "LIMIT"
    quantity: Decimal = Decimal("0")
    price: Decimal | None = None
    status: OrderStatus = OrderStatus.INTENT_CREATED
    broker_order_id: str | None = None
    submitted_at: datetime | None = None
    acknowledged_at: datetime | None = None
    filled_at: datetime | None = None
    filled_quantity: Decimal = Decimal("0")
    filled_price: Decimal | None = None
    commission: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Handoff:
    id: UUID = field(default_factory=uuid4)
    from_run_id: UUID = UUID(int=0)
    to_run_id: UUID = UUID(int=0)
    thesis_id: UUID = UUID(int=0)
    previous_decision_id: UUID = UUID(int=0)
    previous_outcome: DecisionOutcome = DecisionOutcome.NO_TRADE
    new_outcome: DecisionOutcome = DecisionOutcome.NO_TRADE
    changed: bool = False
    change_reason: str = ""
    model_provider_from: str = ""
    model_provider_to: str = ""
    model_name_from: str = ""
    model_name_to: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())


@dataclass(slots=True)
class EquitySnapshot:
    id: UUID = field(default_factory=uuid4)
    run_id: UUID = UUID(int=0)
    timestamp: datetime = field(default_factory=lambda: datetime.utcnow())
    total_equity: Decimal = Decimal("0")
    cash_balance: Decimal = Decimal("0")
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)


ThesisId = UUID
EvidenceId = UUID
DecisionId = UUID
RunId = UUID
OrderId = UUID
HandoffId = UUID
SnapshotId = UUID
