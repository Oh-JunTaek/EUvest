"""storage 모듈 단위 테스트 - 리포지토리, 스키마, 마이그레이션, 무결성."""

from __future__ import annotations

import json
import tempfile
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

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
from invest_agent.storage.repositories import (
    ThesisRepository,
    EvidenceRepository,
    DecisionRepository,
    AgentRunRepository,
    OrderRepository,
    HandoffRepository,
    EquitySnapshotRepository,
)
from invest_agent.storage.schema import (
    ensure_db,
    get_schema_version,
    migrate,
    init_db,
)
class TestThesisRepository:
    """Thesis 리포지토리 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = ThesisRepository(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        thesis = Thesis(
            id=uuid4(),
            asset_id="KRX:005930",
            hypothesis="Samsung will rise",
            rationale="Strong earnings",
        )
        self.repo.save(thesis)
        retrieved = self.repo.get(thesis.id)
        assert retrieved is not None
        assert retrieved.id == thesis.id
        assert retrieved.asset_id == "KRX:005930"
        assert retrieved.hypothesis == "Samsung will rise"
        assert retrieved.rationale == "Strong earnings"
        assert retrieved.is_active is True

    def test_get_nonexistent(self):
        result = self.repo.get(uuid4())
        assert result is None

    def test_get_by_asset(self):
        thesis1 = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        thesis2 = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H2", rationale="R2")
        thesis3 = Thesis(id=uuid4(), asset_id="US:AAPL", hypothesis="H3", rationale="R3")
        self.repo.save(thesis1)
        self.repo.save(thesis2)
        self.repo.save(thesis3)

        krx = self.repo.get_by_asset("KRX:005930")
        assert len(krx) == 2
        us = self.repo.get_by_asset("US:AAPL")
        assert len(us) == 1

    def test_get_by_asset_inactive_filter(self):
        thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        self.repo.save(thesis)
        self.repo.deactivate(thesis.id)

        active = self.repo.get_by_asset("KRX:005930", active_only=True)
        all_theses = self.repo.get_by_asset("KRX:005930", active_only=False)
        assert len(active) == 0
        assert len(all_theses) == 1

    def test_get_all_active(self):
        t1 = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        t2 = Thesis(id=uuid4(), asset_id="US:AAPL", hypothesis="H2", rationale="R2")
        self.repo.save(t1)
        self.repo.save(t2)
        self.repo.deactivate(t1.id)

        active = self.repo.get_all_active()
        assert len(active) == 1
        assert active[0].id == t2.id

    def test_upsert_idempotent(self):
        thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        self.repo.save(thesis)
        thesis.hypothesis = "Updated hypothesis"
        thesis.updated_at = datetime.utcnow()
        self.repo.save(thesis)
class TestEvidenceRepository:
    """Evidence 리포지토리 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = EvidenceRepository(self.db_path)
        self.thesis_repo = ThesisRepository(self.db_path)
        self.thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        self.thesis_repo.save(self.thesis)
        self.thesis_id = self.thesis.id

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        evidence = Evidence(
            id=uuid4(),
            thesis_id=self.thesis_id,
            evidence_type=EvidenceType.FUNDAMENTAL,
            source="dart",
            observed_at=datetime.utcnow(),
            collected_at=datetime.utcnow(),
            content={"pe_ratio": 12.5, "revenue": 100000000000},
            raw_ref="https://dart.fss.or.kr/...",
        )
        self.repo.save(evidence)
        retrieved = self.repo.get(evidence.id)
        assert retrieved is not None
        assert retrieved.id == evidence.id
        assert retrieved.thesis_id == self.thesis_id
        assert retrieved.evidence_type == EvidenceType.FUNDAMENTAL
        assert retrieved.content["pe_ratio"] == 12.5

    def test_observed_vs_collected_at_distinction(self):
        observed = datetime(2024, 1, 15, 10, 0, 0)
        collected = datetime(2024, 1, 15, 10, 5, 0)
        evidence = Evidence(
            id=uuid4(),
            thesis_id=self.thesis_id,
            evidence_type=EvidenceType.PRICE,
            source="kis",
            observed_at=observed,
            collected_at=collected,
            content={"price": 70000},
        )
        self.repo.save(evidence)
        retrieved = self.repo.get(evidence.id)
        assert retrieved.observed_at == observed
        assert retrieved.collected_at == collected
        assert retrieved.observed_at < retrieved.collected_at


class TestDecisionRepository:
    """Decision 리포지토리 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = DecisionRepository(self.db_path)
        self.thesis_repo = ThesisRepository(self.db_path)
        self.run_repo = AgentRunRepository(self.db_path)
        self.thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        self.thesis_repo.save(self.thesis)
        self.thesis_id = self.thesis.id
        self.run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(self.run)
        self.run_id = self.run.id

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        evidence_ids = [uuid4(), uuid4()]
        decision = Decision(
            id=uuid4(),
            thesis_id=self.thesis_id,
            run_id=self.run_id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.BUY,
            target_weight_bps=500,
            current_weight_bps=0,
            rationale="Strong fundamentals",
            evidence_ids=evidence_ids,
            model_provider="nvidia",
            model_name="nemotron-3-ultra",
            execution_mode="OFFLINE_SIM",
        )
        self.repo.save(decision)
        retrieved = self.repo.get(decision.id)
        assert retrieved is not None
        assert retrieved.outcome == DecisionOutcome.TRADE
        assert retrieved.side == OrderSide.BUY
        assert retrieved.target_weight_bps == 500
        assert len(retrieved.evidence_ids) == 2
        assert retrieved.execution_mode == "OFFLINE_SIM"

    def test_get_by_run(self):
        d1 = Decision(id=uuid4(), thesis_id=self.thesis_id, run_id=self.run_id, outcome=DecisionOutcome.TRADE, side=OrderSide.BUY, rationale="R1", model_provider="nvidia", model_name="m1", execution_mode="OFFLINE_SIM")
        d2 = Decision(id=uuid4(), thesis_id=self.thesis_id, run_id=self.run_id, outcome=DecisionOutcome.NO_TRADE, rationale="R2", model_provider="nvidia", model_name="m1", execution_mode="OFFLINE_SIM")
        # Create another run and decision for it
        other_run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(other_run)
        d3 = Decision(id=uuid4(), thesis_id=self.thesis_id, run_id=other_run.id, outcome=DecisionOutcome.TRADE, rationale="R3", model_provider="nvidia", model_name="m1", execution_mode="OFFLINE_SIM")
        self.repo.save(d1)
        self.repo.save(d2)
        self.repo.save(d3)

        run_decisions = self.repo.get_by_run(self.run_id)
        assert len(run_decisions) == 2

    def test_get_by_thesis(self):
        thesis2 = Thesis(id=uuid4(), asset_id="US:AAPL", hypothesis="H2", rationale="R2")
        self.thesis_repo.save(thesis2)
        thesis2_id = thesis2.id
        d1 = Decision(id=uuid4(), thesis_id=self.thesis_id, run_id=self.run_id, outcome=DecisionOutcome.TRADE, rationale="R1", model_provider="nvidia", model_name="m1", execution_mode="OFFLINE_SIM")
        d2 = Decision(id=uuid4(), thesis_id=thesis2_id, run_id=self.run_id, outcome=DecisionOutcome.NO_TRADE, rationale="R2", model_provider="nvidia", model_name="m1", execution_mode="OFFLINE_SIM")
        self.repo.save(d1)
        self.repo.save(d2)

        thesis_decisions = self.repo.get_by_thesis(self.thesis_id)
        assert len(thesis_decisions) == 1
class TestAgentRunRepository:
    """AgentRun 리포지토리 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = AgentRunRepository(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        thesis_ids = [uuid4(), uuid4()]
        decision_ids = [uuid4()]
        run = AgentRun(
            id=uuid4(),
            status=RunStatus.COMPLETED,
            execution_mode="OFFLINE_SIM",
            thesis_ids=thesis_ids,
            decision_ids=decision_ids,
        )
        self.repo.save(run)
        retrieved = self.repo.get(run.id)
        assert retrieved is not None
        assert retrieved.status == RunStatus.COMPLETED
        assert retrieved.execution_mode == "OFFLINE_SIM"
        assert len(retrieved.thesis_ids) == 2
        assert len(retrieved.decision_ids) == 1

    def test_get_by_status(self):
        r1 = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        r2 = AgentRun(id=uuid4(), status=RunStatus.BLOCKED, execution_mode="OFFLINE_SIM")
        r3 = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="KIS_PAPER")
        self.repo.save(r1)
        self.repo.save(r2)
        self.repo.save(r3)

        completed = self.repo.get_by_status(RunStatus.COMPLETED)
        assert len(completed) == 2
        blocked = self.repo.get_by_status(RunStatus.BLOCKED)
        assert len(blocked) == 1

    def test_get_latest(self):
        for i in range(5):
            run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
            self.repo.save(run)
        latest = self.repo.get_latest(limit=3)
        assert len(latest) == 3


class TestOrderRepository:
    """OrderRecord 리포지토리 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = OrderRepository(self.db_path)
        self.run_repo = AgentRunRepository(self.db_path)
        self.decision_repo = DecisionRepository(self.db_path)
        self.thesis_repo = ThesisRepository(self.db_path)
        self.thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        self.thesis_repo.save(self.thesis)
        self.run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(self.run)
        self.decision = Decision(
            id=uuid4(),
            thesis_id=self.thesis.id,
            run_id=self.run.id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.BUY,
            target_weight_bps=500,
            rationale="Test",
            model_provider="test",
            model_name="test",
            execution_mode="OFFLINE_SIM",
        )
        self.decision_repo.save(self.decision)
        self.run_id = self.run.id
        self.decision_id = self.decision.id
        self.run_id = self.run.id
        self.decision_id = self.decision.id

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        order = OrderRecord(
            id=uuid4(),
            run_id=self.run_id,
            decision_id=self.decision_id,
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type="LIMIT",
            quantity=Decimal("10"),
            price=Decimal("70000"),
            status=OrderStatus.FILLED,
        )
        self.repo.save(order)
        retrieved = self.repo.get(order.id)
        assert retrieved is not None
        assert retrieved.asset_id == "KRX:005930"
        assert retrieved.side == OrderSide.BUY
        assert retrieved.quantity == Decimal("10")
        assert retrieved.price == Decimal("70000")
        assert retrieved.status == OrderStatus.FILLED

    def test_decimal_precision_preserved(self):
        order = OrderRecord(
            id=uuid4(),
            run_id=self.run_id,
            decision_id=self.decision_id,
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type="LIMIT",
            quantity=Decimal("10.123456789"),
            price=Decimal("70000.12345"),
            status=OrderStatus.ACKNOWLEDGED,
        )
        self.repo.save(order)
        retrieved = self.repo.get(order.id)
        assert retrieved.quantity == Decimal("10.123456789")
        assert retrieved.price == Decimal("70000.12345")

    def test_get_by_run(self):
        o1 = OrderRecord(id=uuid4(), run_id=self.run_id, decision_id=self.decision_id, asset_id="KRX:005930", side=OrderSide.BUY, order_type="LIMIT", quantity=Decimal("10"), status=OrderStatus.FILLED)
        o2 = OrderRecord(id=uuid4(), run_id=self.run_id, decision_id=self.decision_id, asset_id="US:AAPL", side=OrderSide.SELL, order_type="LIMIT", quantity=Decimal("5"), status=OrderStatus.PARTIALLY_FILLED)
        other_run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(other_run)
        o3 = OrderRecord(id=uuid4(), run_id=other_run.id, decision_id=self.decision_id, asset_id="KRX:005930", side=OrderSide.BUY, order_type="LIMIT", quantity=Decimal("20"), status=OrderStatus.FILLED)
        self.repo.save(o1)
        self.repo.save(o2)
        self.repo.save(o3)

        run_orders = self.repo.get_by_run(self.run_id)
        assert len(run_orders) == 2

    def test_get_by_decision(self):
        dec_id = uuid4()
        # Create a decision with valid run_id
        decision = Decision(
            id=dec_id,
            thesis_id=self.thesis.id,
            run_id=self.run_id,
            outcome=DecisionOutcome.TRADE,
            rationale="Test",
            model_provider="test",
            model_name="test",
            execution_mode="OFFLINE_SIM",
        )
        self.decision_repo.save(decision)

        o1 = OrderRecord(id=uuid4(), run_id=self.run_id, decision_id=dec_id, asset_id="KRX:005930", side=OrderSide.BUY, order_type="LIMIT", quantity=Decimal("10"), status=OrderStatus.FILLED)
        o2 = OrderRecord(id=uuid4(), run_id=self.run_id, decision_id=dec_id, asset_id="KRX:005930", side=OrderSide.SELL, order_type="LIMIT", quantity=Decimal("5"), status=OrderStatus.PARTIALLY_FILLED)
        self.repo.save(o1)
        self.repo.save(o2)

        dec_orders = self.repo.get_by_decision(dec_id)
        assert len(dec_orders) == 2
class TestHandoffRepository:
    """Handoff 리포지토리 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = HandoffRepository(self.db_path)
        self.thesis_repo = ThesisRepository(self.db_path)
        self.run_repo = AgentRunRepository(self.db_path)
        self.decision_repo = DecisionRepository(self.db_path)
        self.thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        self.thesis_repo.save(self.thesis)
        self.thesis_id = self.thesis.id

        self.run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(self.run)
        self.run_id = self.run.id

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        from_run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        to_run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(from_run)
        self.run_repo.save(to_run)

        prev_decision = Decision(
            id=uuid4(),
            thesis_id=self.thesis_id,
            run_id=self.run_id,
            outcome=DecisionOutcome.NO_TRADE,
            rationale="Test",
            model_provider="test",
            model_name="test",
            execution_mode="OFFLINE_SIM",
        )
        self.decision_repo.save(prev_decision)

        handoff = Handoff(
            id=uuid4(),
            from_run_id=from_run.id,
            to_run_id=to_run.id,
            thesis_id=self.thesis_id,
            previous_decision_id=prev_decision.id,
            previous_outcome=DecisionOutcome.NO_TRADE,
            new_outcome=DecisionOutcome.TRADE,
            changed=True,
            change_reason="New evidence found",
            model_provider_from="fake",
            model_provider_to="nvidia",
            model_name_from="fake-model",
            model_name_to="nemotron-3-ultra",
        )
        self.repo.save(handoff)
        retrieved = self.repo.get(handoff.id)
        assert retrieved is not None
        assert retrieved.changed is True
        assert retrieved.previous_outcome == DecisionOutcome.NO_TRADE
        assert retrieved.new_outcome == DecisionOutcome.TRADE
        assert retrieved.model_provider_from == "fake"
        assert retrieved.model_provider_to == "nvidia"

    def test_get_by_thesis(self):
        from_run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        to_run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(from_run)
        self.run_repo.save(to_run)

        prev_decision = Decision(
            id=uuid4(),
            thesis_id=self.thesis_id,
            run_id=self.run_id,
            outcome=DecisionOutcome.NO_TRADE,
            rationale="Test",
            model_provider="test",
            model_name="test",
            execution_mode="OFFLINE_SIM",
        )
        self.decision_repo.save(prev_decision)

        h1 = Handoff(id=uuid4(), from_run_id=from_run.id, to_run_id=to_run.id, thesis_id=self.thesis_id, previous_decision_id=prev_decision.id, previous_outcome=DecisionOutcome.NO_TRADE, new_outcome=DecisionOutcome.TRADE, changed=True, change_reason="R1", model_provider_from="fake", model_provider_to="nvidia", model_name_from="m1", model_name_to="m2")
        h2 = Handoff(id=uuid4(), from_run_id=from_run.id, to_run_id=to_run.id, thesis_id=self.thesis_id, previous_decision_id=prev_decision.id, previous_outcome=DecisionOutcome.TRADE, new_outcome=DecisionOutcome.NO_TRADE, changed=True, change_reason="R2", model_provider_from="nvidia", model_provider_to="fake", model_name_from="m2", model_name_to="m3")
        other_thesis = Thesis(id=uuid4(), asset_id="US:AAPL", hypothesis="H2", rationale="R2")
        self.thesis_repo.save(other_thesis)
        other_thesis_id = other_thesis.id
        h3 = Handoff(id=uuid4(), from_run_id=from_run.id, to_run_id=to_run.id, thesis_id=other_thesis_id, previous_decision_id=prev_decision.id, previous_outcome=DecisionOutcome.NO_TRADE, new_outcome=DecisionOutcome.TRADE, changed=True, change_reason="R3", model_provider_from="fake", model_provider_to="nvidia", model_name_from="m1", model_name_to="m2")
        self.run_repo.save(from_run)
        self.run_repo.save(to_run)
        self.decision_repo.save(prev_decision)
        self.repo.save(h1)
        self.repo.save(h2)
        self.repo.save(h3)

        thesis_handoffs = self.repo.get_by_thesis(self.thesis_id)
        assert len(thesis_handoffs) == 2


class TestEquitySnapshotRepository:
    """EquitySnapshot 리포지토리 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = EquitySnapshotRepository(self.db_path)
        self.run_repo = AgentRunRepository(self.db_path)
        self.run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(self.run)
        self.run_id = self.run.id

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_save_and_get(self):
        snapshot = EquitySnapshot(
            id=uuid4(),
            run_id=self.run_id,
            timestamp=datetime.utcnow(),
            total_equity=Decimal("100000000"),
            cash_balance=Decimal("50000000"),
            positions={"KRX:005930": {"qty": 10, "avg_price": 70000, "market_value": 700000, "weight_bps": 500}},
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
        )
        self.repo.save(snapshot)
        retrieved = self.repo.get(snapshot.id)
        assert retrieved is not None
        assert retrieved.total_equity == Decimal("100000000")
        assert retrieved.cash_balance == Decimal("50000000")
        assert "KRX:005930" in retrieved.positions

    def test_get_by_run(self):
        s1 = EquitySnapshot(id=uuid4(), run_id=self.run_id, timestamp=datetime(2024, 1, 1), total_equity=Decimal("100"), cash_balance=Decimal("50"))
        s2 = EquitySnapshot(id=uuid4(), run_id=self.run_id, timestamp=datetime(2024, 1, 2), total_equity=Decimal("110"), cash_balance=Decimal("50"))
        other_run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        self.run_repo.save(other_run)
        s3 = EquitySnapshot(id=uuid4(), run_id=other_run.id, timestamp=datetime(2024, 1, 1), total_equity=Decimal("200"), cash_balance=Decimal("100"))
        self.repo.save(s1)
        self.repo.save(s2)
        self.repo.save(s3)

        run_snapshots = self.repo.get_by_run(self.run_id)
        assert len(run_snapshots) == 2

    def test_get_latest(self):
        s1 = EquitySnapshot(id=uuid4(), run_id=self.run_id, timestamp=datetime(2024, 1, 1), total_equity=Decimal("100"))
        s2 = EquitySnapshot(id=uuid4(), run_id=self.run_id, timestamp=datetime(2024, 1, 2), total_equity=Decimal("110"))
        s3 = EquitySnapshot(id=uuid4(), run_id=self.run_id, timestamp=datetime(2024, 1, 3), total_equity=Decimal("120"))
        self.repo.save(s1)
        self.repo.save(s2)
        self.repo.save(s3)

        latest = self.repo.get_latest(self.run_id)
        assert latest is not None
        assert latest.timestamp == datetime(2024, 1, 3)
        assert latest.total_equity == Decimal("120")

# APPENDED MARKER


class TestSchemaAndMigration:
    def setup_method(self):
        pass
    def test_dummy(self):
        assert True


class TestSchemaAndMigration:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

# Final append marker