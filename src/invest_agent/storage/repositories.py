from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from invest_agent.domain.models import (
    AgentRun,
    Decision,
    DecisionOutcome,
    EquitySnapshot,
    Evidence,
    EvidenceType,
    Handoff,
    OrderRecord,
    OrderSide,
    OrderStatus,
    RunStatus,
    Thesis,
)
from invest_agent.storage.schema import ensure_db


class ThesisRepository:
    """투자 가설 리포지토리."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_db(self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save(self, thesis: Thesis) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO theses
                (id, asset_id, hypothesis, rationale, created_at, updated_at, is_active, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    asset_id=excluded.asset_id,
                    hypothesis=excluded.hypothesis,
                    rationale=excluded.rationale,
                    updated_at=excluded.updated_at,
                    is_active=excluded.is_active,
                    metadata=excluded.metadata
                """,
                (
                    str(thesis.id),
                    thesis.asset_id,
                    thesis.hypothesis,
                    thesis.rationale,
                    thesis.created_at.isoformat(),
                    thesis.updated_at.isoformat(),
                    1 if thesis.is_active else 0,
                    json.dumps(thesis.metadata),
                ),
            )
            conn.commit()

    def get(self, thesis_id: UUID) -> Thesis | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM theses WHERE id = ?", (str(thesis_id),)).fetchone()
            if not row:
                return None
            return self._row_to_thesis(row)

    def get_by_asset(self, asset_id: str, active_only: bool = True) -> list[Thesis]:
        with self._conn() as conn:
            query = "SELECT * FROM theses WHERE asset_id = ?"
            params = [asset_id]
            if active_only:
                query += " AND is_active = 1"
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_thesis(row) for row in rows]

    def get_all_active(self) -> list[Thesis]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM theses WHERE is_active = 1 ORDER BY created_at DESC").fetchall()
            return [self._row_to_thesis(row) for row in rows]

    def deactivate(self, thesis_id: UUID) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE theses SET is_active = 0, updated_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), str(thesis_id)),
            )
            conn.commit()

    def _row_to_thesis(self, row: sqlite3.Row) -> Thesis:
        return Thesis(
            id=UUID(row["id"]),
            asset_id=row["asset_id"],
            hypothesis=row["hypothesis"],
            rationale=row["rationale"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            is_active=bool(row["is_active"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )


class EvidenceRepository:
    """증거 리포지토리."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_db(self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save(self, evidence: Evidence) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO evidence
                (id, thesis_id, evidence_type, source, observed_at, collected_at, content, raw_ref, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    thesis_id=excluded.thesis_id,
                    evidence_type=excluded.evidence_type,
                    source=excluded.source,
                    observed_at=excluded.observed_at,
                    collected_at=excluded.collected_at,
                    content=excluded.content,
                    raw_ref=excluded.raw_ref,
                    metadata=excluded.metadata
                """,
                (
                    str(evidence.id),
                    str(evidence.thesis_id),
                    evidence.evidence_type.value,
                    evidence.source,
                    evidence.observed_at.isoformat(),
                    evidence.collected_at.isoformat(),
                    json.dumps(evidence.content),
                    evidence.raw_ref,
                    json.dumps(evidence.metadata),
                ),
            )
            conn.commit()

    def get(self, evidence_id: UUID) -> Evidence | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (str(evidence_id),)).fetchone()
            if not row:
                return None
            return self._row_to_evidence(row)

    def get_by_thesis(self, thesis_id: UUID) -> list[Evidence]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE thesis_id = ? ORDER BY observed_at DESC",
                (str(thesis_id),),
            ).fetchall()
            return [self._row_to_evidence(row) for row in rows]

    def _row_to_evidence(self, row: sqlite3.Row) -> Evidence:
        return Evidence(
            id=UUID(row["id"]),
            thesis_id=UUID(row["thesis_id"]),
            evidence_type=EvidenceType(row["evidence_type"]),
            source=row["source"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            collected_at=datetime.fromisoformat(row["collected_at"]),
            content=json.loads(row["content"]) if row["content"] else {},
            raw_ref=row["raw_ref"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )


class DecisionRepository:
    """의사결정 리포지토리."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_db(self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save(self, decision: Decision) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO decisions
                (id, thesis_id, run_id, outcome, side, target_weight_bps, current_weight_bps,
                 rationale, evidence_ids, model_provider, model_name, execution_mode, decided_at, error, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    thesis_id=excluded.thesis_id,
                    run_id=excluded.run_id,
                    outcome=excluded.outcome,
                    side=excluded.side,
                    target_weight_bps=excluded.target_weight_bps,
                    current_weight_bps=excluded.current_weight_bps,
                    rationale=excluded.rationale,
                    evidence_ids=excluded.evidence_ids,
                    model_provider=excluded.model_provider,
                    model_name=excluded.model_name,
                    execution_mode=excluded.execution_mode,
                    decided_at=excluded.decided_at,
                    error=excluded.error,
                    metadata=excluded.metadata
                """,
                (
                    str(decision.id),
                    str(decision.thesis_id),
                    str(decision.run_id),
                    decision.outcome.value,
                    decision.side.value if decision.side else None,
                    decision.target_weight_bps,
                    decision.current_weight_bps,
                    decision.rationale,
                    json.dumps([str(eid) for eid in decision.evidence_ids]),
                    decision.model_provider,
                    decision.model_name,
                    decision.execution_mode,
                    decision.decided_at.isoformat(),
                    decision.error,
                    json.dumps(decision.metadata),
                ),
            )
            conn.commit()

    def get(self, decision_id: UUID) -> Decision | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM decisions WHERE id = ?", (str(decision_id),)).fetchone()
            if not row:
                return None
            return self._row_to_decision(row)

    def get_by_run(self, run_id: UUID) -> list[Decision]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE run_id = ? ORDER BY decided_at DESC",
                (str(run_id),),
            ).fetchall()
            return [self._row_to_decision(row) for row in rows]

    def get_by_thesis(self, thesis_id: UUID) -> list[Decision]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE thesis_id = ? ORDER BY decided_at DESC",
                (str(thesis_id),),
            ).fetchall()
            return [self._row_to_decision(row) for row in rows]

    def _row_to_decision(self, row: sqlite3.Row) -> Decision:
        return Decision(
            id=UUID(row["id"]),
            thesis_id=UUID(row["thesis_id"]),
            run_id=UUID(row["run_id"]),
            outcome=DecisionOutcome(row["outcome"]),
            side=OrderSide(row["side"]) if row["side"] else None,
            target_weight_bps=row["target_weight_bps"],
            current_weight_bps=row["current_weight_bps"],
            rationale=row["rationale"],
            evidence_ids=[UUID(eid) for eid in json.loads(row["evidence_ids"])] if row["evidence_ids"] else [],
            model_provider=row["model_provider"],
            model_name=row["model_name"],
            execution_mode=row["execution_mode"],
            decided_at=datetime.fromisoformat(row["decided_at"]),
            error=row["error"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )


class AgentRunRepository:
    """실행 기록 리포지토리."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_db(self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save(self, run: AgentRun) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs
                (id, started_at, completed_at, status, execution_mode, schedule_id,
                 thesis_ids, decision_ids, order_ids, error, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    status=excluded.status,
                    execution_mode=excluded.execution_mode,
                    schedule_id=excluded.schedule_id,
                    thesis_ids=excluded.thesis_ids,
                    decision_ids=excluded.decision_ids,
                    order_ids=excluded.order_ids,
                    error=excluded.error,
                    metadata=excluded.metadata
                """,
                (
                    str(run.id),
                    run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.status.value,
                    run.execution_mode,
                    run.schedule_id,
                    json.dumps([str(tid) for tid in run.thesis_ids]),
                    json.dumps([str(did) for did in run.decision_ids]),
                    json.dumps([str(oid) for oid in run.order_ids]),
                    run.error,
                    json.dumps(run.metadata),
                ),
            )
            conn.commit()

    def get(self, run_id: UUID) -> AgentRun | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (str(run_id),)).fetchone()
            if not row:
                return None
            return self._row_to_run(row)

    def get_latest(self, limit: int = 10) -> list[AgentRun]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_run(row) for row in rows]

    def get_by_status(self, status: RunStatus) -> list[AgentRun]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE status = ? ORDER BY started_at DESC",
                (status.value,),
            ).fetchall()
            return [self._row_to_run(row) for row in rows]

    def _row_to_run(self, row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            id=UUID(row["id"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            status=RunStatus(row["status"]),
            execution_mode=row["execution_mode"],
            schedule_id=row["schedule_id"],
            thesis_ids=[UUID(tid) for tid in json.loads(row["thesis_ids"])] if row["thesis_ids"] else [],
            decision_ids=[UUID(did) for did in json.loads(row["decision_ids"])] if row["decision_ids"] else [],
            order_ids=[UUID(oid) for oid in json.loads(row["order_ids"])] if row["order_ids"] else [],
            error=row["error"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
class OrderRepository:
    """주문 기록 리포지토리."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_db(self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save(self, order: OrderRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO orders
                (id, run_id, decision_id, asset_id, side, order_type, quantity, price, status,
                 broker_order_id, submitted_at, acknowledged_at, filled_at, filled_quantity,
                 filled_price, commission, tax, error, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    run_id=excluded.run_id,
                    decision_id=excluded.decision_id,
                    asset_id=excluded.asset_id,
                    side=excluded.side,
                    order_type=excluded.order_type,
                    quantity=excluded.quantity,
                    price=excluded.price,
                    status=excluded.status,
                    broker_order_id=excluded.broker_order_id,
                    submitted_at=excluded.submitted_at,
                    acknowledged_at=excluded.acknowledged_at,
                    filled_at=excluded.filled_at,
                    filled_quantity=excluded.filled_quantity,
                    filled_price=excluded.filled_price,
                    commission=excluded.commission,
                    tax=excluded.tax,
                    error=excluded.error,
                    metadata=excluded.metadata
                """,
                (
                    str(order.id),
                    str(order.run_id),
                    str(order.decision_id),
                    order.asset_id,
                    order.side.value,
                    order.order_type,
                    str(order.quantity),
                    str(order.price) if order.price else None,
                    order.status.value,
                    order.broker_order_id,
                    order.submitted_at.isoformat() if order.submitted_at else None,
                    order.acknowledged_at.isoformat() if order.acknowledged_at else None,
                    order.filled_at.isoformat() if order.filled_at else None,
                    str(order.filled_quantity),
                    str(order.filled_price) if order.filled_price else None,
                    str(order.commission),
                    str(order.tax),
                    order.error,
                    json.dumps(order.metadata),
                ),
            )
            conn.commit()

    def get(self, order_id: UUID) -> OrderRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (str(order_id),)).fetchone()
            if not row:
                return None
            return self._row_to_order(row)

    def get_by_run(self, run_id: UUID) -> list[OrderRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE run_id = ? ORDER BY submitted_at DESC",
                (str(run_id),),
            ).fetchall()
            return [self._row_to_order(row) for row in rows]

    def get_by_decision(self, decision_id: UUID) -> list[OrderRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE decision_id = ? ORDER BY submitted_at DESC",
                (str(decision_id),),
            ).fetchall()
            return [self._row_to_order(row) for row in rows]

    def _row_to_order(self, row: sqlite3.Row) -> OrderRecord:
        return OrderRecord(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            decision_id=UUID(row["decision_id"]),
            asset_id=row["asset_id"],
            side=OrderSide(row["side"]),
            order_type=row["order_type"],
            quantity=Decimal(row["quantity"]),
            price=Decimal(row["price"]) if row["price"] else None,
            status=OrderStatus(row["status"]),
            broker_order_id=row["broker_order_id"],
            submitted_at=datetime.fromisoformat(row["submitted_at"]) if row["submitted_at"] else None,
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row["acknowledged_at"] else None,
            filled_at=datetime.fromisoformat(row["filled_at"]) if row["filled_at"] else None,
            filled_quantity=Decimal(row["filled_quantity"]),
            filled_price=Decimal(row["filled_price"]) if row["filled_price"] else None,
            commission=Decimal(row["commission"]),
            tax=Decimal(row["tax"]),
            error=row["error"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
class HandoffRepository:
    """인계 기록 리포지토리."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_db(self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save(self, handoff: Handoff) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO handoffs
                (id, from_run_id, to_run_id, thesis_id, previous_decision_id,
                 previous_outcome, new_outcome, changed, change_reason,
                 model_provider_from, model_provider_to, model_name_from, model_name_to, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    from_run_id=excluded.from_run_id,
                    to_run_id=excluded.to_run_id,
                    thesis_id=excluded.thesis_id,
                    previous_decision_id=excluded.previous_decision_id,
                    previous_outcome=excluded.previous_outcome,
                    new_outcome=excluded.new_outcome,
                    changed=excluded.changed,
                    change_reason=excluded.change_reason,
                    model_provider_from=excluded.model_provider_from,
                    model_provider_to=excluded.model_provider_to,
                    model_name_from=excluded.model_name_from,
                    model_name_to=excluded.model_name_to,
                    created_at=excluded.created_at
                """,
                (
                    str(handoff.id),
                    str(handoff.from_run_id),
                    str(handoff.to_run_id),
                    str(handoff.thesis_id),
                    str(handoff.previous_decision_id),
                    handoff.previous_outcome.value,
                    handoff.new_outcome.value,
                    1 if handoff.changed else 0,
                    handoff.change_reason,
                    handoff.model_provider_from,
                    handoff.model_provider_to,
                    handoff.model_name_from,
                    handoff.model_name_to,
                    handoff.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, handoff_id: UUID) -> Handoff | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id = ?", (str(handoff_id),)).fetchone()
            if not row:
                return None
            return self._row_to_handoff(row)

    def get_by_thesis(self, thesis_id: UUID) -> list[Handoff]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM handoffs WHERE thesis_id = ? ORDER BY created_at DESC",
                (str(thesis_id),),
            ).fetchall()
            return [self._row_to_handoff(row) for row in rows]

    def _row_to_handoff(self, row: sqlite3.Row) -> Handoff:
        return Handoff(
            id=UUID(row["id"]),
            from_run_id=UUID(row["from_run_id"]),
            to_run_id=UUID(row["to_run_id"]),
            thesis_id=UUID(row["thesis_id"]),
            previous_decision_id=UUID(row["previous_decision_id"]),
            previous_outcome=DecisionOutcome(row["previous_outcome"]),
            new_outcome=DecisionOutcome(row["new_outcome"]),
            changed=bool(row["changed"]),
            change_reason=row["change_reason"],
            model_provider_from=row["model_provider_from"],
            model_provider_to=row["model_provider_to"],
            model_name_from=row["model_name_from"],
            model_name_to=row["model_name_to"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
class EquitySnapshotRepository:
    """자산 평가 스냅샷 리포지토리."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        ensure_db(self.db_path)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save(self, snapshot: EquitySnapshot) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO equity_snapshots
                (id, run_id, timestamp, total_equity, cash_balance, positions,
                 unrealized_pnl, realized_pnl, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    run_id=excluded.run_id,
                    timestamp=excluded.timestamp,
                    total_equity=excluded.total_equity,
                    cash_balance=excluded.cash_balance,
                    positions=excluded.positions,
                    unrealized_pnl=excluded.unrealized_pnl,
                    realized_pnl=excluded.realized_pnl,
                    metadata=excluded.metadata
                """,
                (
                    str(snapshot.id),
                    str(snapshot.run_id),
                    snapshot.timestamp.isoformat(),
                    str(snapshot.total_equity),
                    str(snapshot.cash_balance),
                    json.dumps(snapshot.positions),
                    str(snapshot.unrealized_pnl),
                    str(snapshot.realized_pnl),
                    json.dumps(snapshot.metadata),
                ),
            )
            conn.commit()

    def get(self, snapshot_id: UUID) -> EquitySnapshot | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM equity_snapshots WHERE id = ?", (str(snapshot_id),)).fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    def get_by_run(self, run_id: UUID) -> list[EquitySnapshot]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM equity_snapshots WHERE run_id = ? ORDER BY timestamp DESC",
                (str(run_id),),
            ).fetchall()
            return [self._row_to_snapshot(row) for row in rows]

    def get_latest(self, run_id: UUID) -> EquitySnapshot | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM equity_snapshots WHERE run_id = ? ORDER BY timestamp DESC LIMIT 1",
                (str(run_id),),
            ).fetchone()
            if not row:
                return None
            return self._row_to_snapshot(row)

    def _row_to_snapshot(self, row: sqlite3.Row) -> EquitySnapshot:
        return EquitySnapshot(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
            total_equity=Decimal(row["total_equity"]),
            cash_balance=Decimal(row["cash_balance"]),
            positions=json.loads(row["positions"]) if row["positions"] else {},
            unrealized_pnl=Decimal(row["unrealized_pnl"]),
            realized_pnl=Decimal(row["realized_pnl"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
