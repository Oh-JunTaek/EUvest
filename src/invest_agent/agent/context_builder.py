"""Context Builder - 투자 판단에 필요한 컨텍스트 구성."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from invest_agent.domain.models import (
    EquitySnapshot,
    OrderRecord,
)
from invest_agent.storage.repositories import (
    DecisionRepository,
    EquitySnapshotRepository,
    OrderRepository,
    ThesisRepository,
)


@dataclass(slots=True)
class ActiveThesis:
    """활성 가설 정보."""
    thesis_id: UUID
    asset_id: str
    hypothesis: str
    rationale: str
    created_at: datetime
    updated_at: datetime
    is_active: bool
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class FalsificationCondition:
    """기각 조건."""
    condition_id: UUID = field(default_factory=uuid4)
    thesis_id: UUID
    condition_type: str
    threshold_value: Decimal | None = None
    description: str = ""
    is_triggered: bool = False
    triggered_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class RecentHistoryEntry:
    """최근 이력 항목."""
    run_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: str
    decisions: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class ContextEnvelope:
    """투자 판단용 컨텍스트 엔벨로프."""
    run_id: UUID
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    active_theses: list[ActiveThesis] = field(default_factory=list)
    falsification_conditions: list[FalsificationCondition] = field(default_factory=list)
    recent_history: list[RecentHistoryEntry] = field(default_factory=list)
    latest_snapshot: EquitySnapshot | None = None
    open_orders: list[OrderRecord] = field(default_factory=list)
    available_cash_krw: Decimal = Decimal("0")
    available_cash_usd: Decimal = Decimal("0")
    total_equity: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)
class ContextBuilder:
    """ContextEnvelope 구성기."""
    def __init__(self, db_path: str):
        self.thesis_repo = ThesisRepository(db_path)
        self.decision_repo = DecisionRepository(db_path)
        self.order_repo = OrderRepository(db_path)
        self.snapshot_repo = EquitySnapshotRepository(db_path)

    def build_context(self, run_id: UUID, max_history: int = 10, asset_filter: list[str] | None = None) -> ContextEnvelope:
        envelope = ContextEnvelope(run_id=run_id)
        if asset_filter:
            for asset_id in asset_filter:
                theses = self.thesis_repo.get_by_asset(asset_id, active_only=True)
                for thesis in theses:
                    envelope.active_theses.append(self._to_active_thesis(thesis))
        else:
            theses = self.thesis_repo.get_all_active()
            for thesis in theses:
                envelope.active_theses.append(self._to_active_thesis(thesis))

        envelope.falsification_conditions = self._build_falsification_conditions(envelope.active_theses)
        envelope.recent_history = self._build_recent_history(max_history)
        envelope.latest_snapshot = self._get_latest_snapshot()
        envelope.open_orders = self._get_open_orders()

        if envelope.latest_snapshot:
            envelope.available_cash_krw = envelope.latest_snapshot.cash_balance
            envelope.total_equity = envelope.latest_snapshot.total_equity
            envelope.available_cash_usd = self._extract_usd_cash(envelope.latest_snapshot)

        envelope.metadata = {
            "active_thesis_count": len(envelope.active_theses),
            "falsification_condition_count": len(envelope.falsification_conditions),
            "recent_runs_count": len(envelope.recent_history),
            "open_orders_count": len(envelope.open_orders),
        }
        return envelope

    def _to_active_thesis(self, thesis) -> ActiveThesis:
        return ActiveThesis(
            thesis_id=thesis.id,
            asset_id=thesis.asset_id,
            hypothesis=thesis.hypothesis,
            rationale=thesis.rationale,
            created_at=thesis.created_at,
            updated_at=thesis.updated_at,
            is_active=thesis.is_active,
            metadata=thesis.metadata,
        )

    def _build_falsification_conditions(self, active_theses: list[ActiveThesis]) -> list[FalsificationCondition]:
        conditions = []
        for thesis in active_theses:
            metadata = thesis.metadata
            if "price_below" in metadata:
                conditions.append(FalsificationCondition(thesis_id=thesis.thesis_id, condition_type="PRICE_BELOW", threshold_value=Decimal(str(metadata["price_below"])), description=f"{thesis.asset_id} 가격이 {metadata['price_below']} 이하로 하락 시 가설 기각", metadata={"source": "thesis_metadata"}))
            if "price_above" in metadata:
                conditions.append(FalsificationCondition(thesis_id=thesis.thesis_id, condition_type="PRICE_ABOVE", threshold_value=Decimal(str(metadata["price_above"])), description=f"{thesis.asset_id} 가격이 {metadata['price_above']} 이상 상승 시 가설 기각", metadata={"source": "thesis_metadata"}))
            if "fundamental_threshold" in metadata:
                conditions.append(FalsificationCondition(thesis_id=thesis.thesis_id, condition_type="FUNDAMENTAL_CHANGE", description=f"{thesis.asset_id} 펀더멘탈 지표 임계값 초과 시 가설 기각", metadata={"threshold": metadata["fundamental_threshold"]}))
            if "news_keywords" in metadata:
                conditions.append(FalsificationCondition(thesis_id=thesis.thesis_id, condition_type="NEWS_EVENT", description=f"{thesis.asset_id} 관련 부정적 뉴스 감지 시 가설 기각", metadata={"keywords": metadata["news_keywords"]}))
            timeout_days = metadata.get("timeout_days", 30)
            conditions.append(FalsificationCondition(thesis_id=thesis.thesis_id, condition_type="TIMEOUT", description=f"{thesis.asset_id} 가설 유지 기간 {timeout_days}일 초과 시 자동 기각", metadata={"timeout_days": timeout_days}))
        return conditions

    def _build_recent_history(self, max_history: int) -> list[RecentHistoryEntry]:
        runs = self.decision_repo.get_recent_runs(max_history)
        history = []
        for run in runs:
            decisions = self.decision_repo.get_by_run(run.id)
            decision_dicts = [{"decision_id": str(d.id), "outcome": d.outcome.value, "side": d.side.value if d.side else None, "target_weight_bps": d.target_weight_bps, "rationale": d.rationale} for d in decisions]
            orders = self.order_repo.get_by_run(run.id)
            order_dicts = [{"order_id": str(o.id), "asset_id": o.asset_id, "side": o.side.value, "status": o.status.value, "quantity": str(o.quantity), "filled_quantity": str(o.filled_quantity)} for o in orders]
            history.append(RecentHistoryEntry(run_id=run.id, started_at=run.started_at, completed_at=run.completed_at, status=run.status.value, decisions=decision_dicts, orders=order_dicts, error=run.error, metadata=run.metadata))
        return history

    def _get_latest_snapshot(self) -> EquitySnapshot | None:
        recent_runs = self.decision_repo.get_recent_runs(1)
        if not recent_runs:
            return None
        latest_run = recent_runs[0]
        snapshots = self.snapshot_repo.get_by_run(latest_run.id)
        if snapshots:
            return snapshots[0]
        return None

    def _get_open_orders(self) -> list[OrderRecord]:
        return []

    def _extract_usd_cash(self, snapshot: EquitySnapshot) -> Decimal:
        usd_cash = Decimal("0")
        for asset_id, pos in snapshot.positions.items():
            if asset_id.startswith("USD") or asset_id == "CASH_USD":
                usd_cash += Decimal(str(pos.get("quantity", "0")))
        return usd_cash
