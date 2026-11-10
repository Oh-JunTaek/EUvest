"""Thesis Manager - 투자 가설 관리 및 인계 스냅샷."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_agent.agent.context_builder import ActiveThesis, ContextEnvelope, FalsificationCondition
from invest_agent.domain.models import (
    DecisionOutcome,
    Handoff,
    Thesis,
)
from invest_agent.storage.repositories import (
    DecisionRepository,
    HandoffRepository,
    ThesisRepository,
)


@dataclass(slots=True)
class HandoffSnapshot:
    """모델/공급자 교체 시 인계용 스냅샷."""
    from_run_id: UUID
    to_run_id: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    active_theses: list[ActiveThesis] = field(default_factory=list)
    falsification_conditions: list[FalsificationCondition] = field(default_factory=list)

    previous_decision_id: UUID | None = None
    previous_outcome: DecisionOutcome = DecisionOutcome.NO_TRADE
    previous_rationale: str = ""

    model_provider_from: str = ""
    model_name_from: str = ""
    model_provider_to: str = ""
    model_name_to: str = ""

    total_equity: Decimal = Decimal("0")
    available_cash_krw: Decimal = Decimal("0")
    available_cash_usd: Decimal = Decimal("0")
    open_positions: dict[str, dict[str, Any]] = field(default_factory=dict)

    open_orders: list[dict] = field(default_factory=list)

    change_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 딕셔너리 변환."""
        return {
            "from_run_id": str(self.from_run_id),
            "to_run_id": str(self.to_run_id),
            "created_at": self.created_at.isoformat(),
            "active_theses": [
                {
                    "thesis_id": str(t.thesis_id),
                    "asset_id": t.asset_id,
                    "hypothesis": t.hypothesis,
                    "rationale": t.rationale,
                    "created_at": t.created_at.isoformat(),
                    "updated_at": t.updated_at.isoformat(),
                    "is_active": t.is_active,
                    "metadata": t.metadata,
                }
                for t in self.active_theses
            ],
            "falsification_conditions": [
                {
                    "condition_id": str(c.condition_id),
                    "thesis_id": str(c.thesis_id),
                    "condition_type": c.condition_type,
                    "threshold_value": str(c.threshold_value) if c.threshold_value else None,
                    "description": c.description,
                    "is_triggered": c.is_triggered,
                    "triggered_at": c.triggered_at.isoformat() if c.triggered_at else None,
                    "metadata": c.metadata,
                }
                for c in self.falsification_conditions
            ],
            "previous_decision_id": str(self.previous_decision_id) if self.previous_decision_id else None,
            "previous_outcome": self.previous_outcome.value,
            "previous_rationale": self.previous_rationale,
            "model_provider_from": self.model_provider_from,
            "model_name_from": self.model_name_from,
            "model_provider_to": self.model_provider_to,
            "model_name_to": self.model_name_to,
            "total_equity": str(self.total_equity),
            "available_cash_krw": str(self.available_cash_krw),
            "available_cash_usd": str(self.available_cash_usd),
            "open_positions": self.open_positions,
            "open_orders": self.open_orders,
            "change_reason": self.change_reason,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ThesisUpdate:
    """가설 업데이트 정보."""
    thesis_id: UUID
    action: str
    old_hypothesis: str | None = None
    new_hypothesis: str | None = None
    old_rationale: str | None = None
    new_rationale: str | None = None
    trigger_condition: FalsificationCondition | None = None
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
class ThesisManager:
    """투자 가설 생명주기 관리 및 인계 처리."""

    def __init__(self, db_path: str):
        self.thesis_repo = ThesisRepository(db_path)
        self.decision_repo = DecisionRepository(db_path)
        self.handoff_repo = HandoffRepository(db_path)

    def create_thesis(
        self,
        asset_id: str,
        hypothesis: str,
        rationale: str,
        metadata: dict[str, Any] | None = None,
    ) -> Thesis:
        thesis = Thesis(asset_id=asset_id, hypothesis=hypothesis, rationale=rationale, metadata=metadata or {})
        self.thesis_repo.save(thesis)
        return thesis

    def update_thesis(
        self,
        thesis_id: UUID,
        hypothesis: str | None = None,
        rationale: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Thesis | None:
        thesis = self.thesis_repo.get(thesis_id)
        if not thesis:
            return None
        if hypothesis is not None:
            thesis.hypothesis = hypothesis
        if rationale is not None:
            thesis.rationale = rationale
        if metadata is not None:
            thesis.metadata.update(metadata)
        thesis.updated_at = datetime.now(UTC)
        self.thesis_repo.save(thesis)
        return thesis

    def deactivate_thesis(self, thesis_id: UUID) -> bool:
        thesis = self.thesis_repo.get(thesis_id)
        if not thesis:
            return False
        thesis.is_active = False
        thesis.updated_at = datetime.now(UTC)
        self.thesis_repo.save(thesis)
        return True

    def check_falsification(
        self,
        thesis_id: UUID,
        current_price: Decimal | None = None,
        fundamental_data: dict[str, Any] | None = None,
        news_items: list[dict] | None = None,
    ) -> list[FalsificationCondition]:
        thesis = self.thesis_repo.get(thesis_id)
        if not thesis or not thesis.is_active:
            return []

        triggered = []
        metadata = thesis.metadata

        if current_price is not None and "price_below" in metadata:
            threshold = Decimal(str(metadata["price_below"]))
            if current_price <= threshold:
                triggered.append(FalsificationCondition(
                    thesis_id=thesis_id,
                    condition_type="PRICE_BELOW",
                    threshold_value=threshold,
                    description=f"{thesis.asset_id} 가격이 {threshold} 이하로 하락",
                    is_triggered=True,
                    triggered_at=datetime.now(UTC),
                    metadata={"source": "thesis_metadata", "current_price": str(current_price)},
                ))

        if current_price is not None and "price_above" in metadata:
            threshold = Decimal(str(metadata["price_above"]))
            if current_price >= threshold:
                triggered.append(FalsificationCondition(
                    thesis_id=thesis_id,
                    condition_type="PRICE_ABOVE",
                    threshold_value=threshold,
                    description=f"{thesis.asset_id} 가격이 {threshold} 이상 상승",
                    is_triggered=True,
                    triggered_at=datetime.now(UTC),
                    metadata={"source": "thesis_metadata", "current_price": str(current_price)},
                ))

        return triggered

    def create_handoff_snapshot(
        self,
        from_run_id: UUID,
        to_run_id: UUID,
        context: ContextEnvelope,
        previous_decision_id: UUID | None = None,
        model_provider_from: str = "",
        model_name_from: str = "",
        model_provider_to: str = "",
        model_name_to: str = "",
        change_reason: str = "",
    ) -> HandoffSnapshot:
        previous_outcome = DecisionOutcome.NO_TRADE
        previous_rationale = ""
        if previous_decision_id:
            prev_decision = self.decision_repo.get(previous_decision_id)
            if prev_decision:
                previous_outcome = prev_decision.outcome
                previous_rationale = prev_decision.rationale

        total_equity = context.total_equity
        available_cash_krw = context.available_cash_krw
        available_cash_usd = context.available_cash_usd
        open_positions = {}
        if context.latest_snapshot:
            open_positions = context.latest_snapshot.positions

        open_orders = [
            {
                "order_id": str(o.id),
                "asset_id": o.asset_id,
                "side": o.side.value,
                "status": o.status.value,
                "quantity": str(o.quantity),
            }
            for o in context.open_orders
        ]

        snapshot = HandoffSnapshot(
            from_run_id=from_run_id,
            to_run_id=to_run_id,
            active_theses=context.active_theses,
            falsification_conditions=context.falsification_conditions,
            previous_decision_id=previous_decision_id,
            previous_outcome=previous_outcome,
            previous_rationale=previous_rationale,
            model_provider_from=model_provider_from,
            model_name_from=model_name_from,
            model_provider_to=model_provider_to,
            model_name_to=model_name_to,
            total_equity=total_equity,
            available_cash_krw=available_cash_krw,
            available_cash_usd=available_cash_usd,
            open_positions=open_positions,
            open_orders=open_orders,
            change_reason=change_reason,
        )

        handoff = Handoff(
            from_run_id=from_run_id,
            to_run_id=to_run_id,
            thesis_id=context.active_theses[0].thesis_id if context.active_theses else UUID(int=0),
            previous_decision_id=previous_decision_id or UUID(int=0),
            previous_outcome=previous_outcome,
            new_outcome=DecisionOutcome.NO_TRADE,
            changed=bool(change_reason),
            change_reason=change_reason,
            model_provider_from=model_provider_from,
            model_provider_to=model_provider_to,
            model_name_from=model_name_from,
            model_name_to=model_name_to,
        )
        self.handoff_repo.save(handoff)
        return snapshot

    def apply_handoff(self, snapshot: HandoffSnapshot) -> list[ThesisUpdate]:
        updates = []

        for active_thesis in snapshot.active_theses:
            existing = self.thesis_repo.get(active_thesis.thesis_id)

            if existing:
                old_hypothesis = existing.hypothesis
                old_rationale = existing.rationale

                existing.hypothesis = active_thesis.hypothesis
                existing.rationale = active_thesis.rationale
                existing.metadata = active_thesis.metadata
                existing.updated_at = datetime.now(UTC)
                existing.is_active = True

                self.thesis_repo.save(existing)

                updates.append(ThesisUpdate(
                    thesis_id=active_thesis.thesis_id,
                    action="UPDATE",
                    old_hypothesis=old_hypothesis,
                    new_hypothesis=active_thesis.hypothesis,
                    old_rationale=old_rationale,
                    new_rationale=active_thesis.rationale,
                ))
            else:
                thesis = Thesis(
                    id=active_thesis.thesis_id,
                    asset_id=active_thesis.asset_id,
                    hypothesis=active_thesis.hypothesis,
                    rationale=active_thesis.rationale,
                    created_at=active_thesis.created_at,
                    updated_at=active_thesis.updated_at,
                    is_active=active_thesis.is_active,
                    metadata=active_thesis.metadata,
                )
                self.thesis_repo.save(thesis)

                updates.append(ThesisUpdate(
                    thesis_id=active_thesis.thesis_id,
                    action="CREATE",
                    new_hypothesis=active_thesis.hypothesis,
                    new_rationale=active_thesis.rationale,
                ))

        return updates

    def get_active_theses(self, asset_filter: list[str] | None = None) -> list[ActiveThesis]:
        if asset_filter:
            theses = []
            for asset_id in asset_filter:
                theses.extend(self.thesis_repo.get_by_asset(asset_id, active_only=True))
        else:
            theses = self.thesis_repo.get_all_active()

        return [
            ActiveThesis(
                thesis_id=t.id,
                asset_id=t.asset_id,
                hypothesis=t.hypothesis,
                rationale=t.rationale,
                created_at=t.created_at,
                updated_at=t.updated_at,
                is_active=t.is_active,
                metadata=t.metadata,
            )
            for t in theses
        ]
