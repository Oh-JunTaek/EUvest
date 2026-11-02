"""storage 모듈 단위 테스트 - 리포지토리, 스키마, 마이그레이션, 무결성."""

from __future__ import annotations

import os
import tempfile
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
    AgentRunRepository,
    DecisionRepository,
    EquitySnapshotRepository,
    EvidenceRepository,
    HandoffRepository,
    OrderRepository,
    ThesisRepository,
)
from invest_agent.storage.schema import (
    ensure_db,
    get_schema_version,
    init_db,
    migrate,
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

    def test_upsert_preserves_orders(self):
        """판단 업서트 시 연결된 주문이 유지되는지 검증."""
        from invest_agent.storage.repositories import OrderRepository
        from invest_agent.domain.models import OrderRecord, OrderSide, OrderStatus
        from decimal import Decimal

        # 판단 생성 및 저장
        decision = Decision(
            id=uuid4(),
            thesis_id=self.thesis_id,
            run_id=self.run_id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.BUY,
            target_weight_bps=500,
            rationale="Initial rationale",
            model_provider="nvidia",
            model_name="nemotron",
            execution_mode="OFFLINE_SIM",
        )
        self.repo.save(decision)

        # 해당 판단에 연결된 주문 생성
        order_repo = OrderRepository(self.db_path)
        order = OrderRecord(
            id=uuid4(),
            run_id=self.run_id,
            decision_id=decision.id,
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type="LIMIT",
            quantity=Decimal("10"),
            price=Decimal("70000"),
            status=OrderStatus.ACKNOWLEDGED,
        )
        order_repo.save(order)

        # 판단 업데이트 (업서트)
        decision.rationale = "Updated rationale"
        self.repo.save(decision)

        # 판단이 업데이트되었는지 확인
        retrieved_decision = self.repo.get(decision.id)
        assert retrieved_decision.rationale == "Updated rationale"

        # 주문이 그대로 유지되는지 확인 (결정 ID가 변경되지 않아야 함)
        retrieved_order = order_repo.get(order.id)
        assert retrieved_order is not None
        assert retrieved_order.decision_id == decision.id
        assert retrieved_order.quantity == Decimal("10")
        assert retrieved_order.price == Decimal("70000")

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
    """스키마 초기화 및 마이그레이션 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_init_db_creates_all_tables(self):
        init_db(self.db_path)
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        try:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [t[0] for t in tables]
            expected = {"theses", "evidence", "decisions", "agent_runs", "orders", "handoffs", "equity_snapshots", "schema_version"}
            for t in expected:
                assert t in table_names, f"Table {t} not created"
        finally:
            conn.close()

    def test_foreign_keys_enforced(self):
        init_db(self.db_path)
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO evidence (id, thesis_id, evidence_type, source, observed_at, collected_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), str(uuid4()), "PRICE", "test", datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
                )
        finally:
            conn.close()

    def test_schema_version_recorded(self):
        init_db(self.db_path)
        version = get_schema_version(self.db_path)
        assert version == 2

    def test_migrate_idempotent(self):
        init_db(self.db_path)
        migrate(self.db_path)
        version = get_schema_version(self.db_path)
        assert version == 2

    def test_wal_mode_enabled(self):
        init_db(self.db_path)
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.upper() == "WAL"
        finally:
            conn.close()


class TestDataIntegrity:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def test_decimal_precision_preserved_through_roundtrip(self):
        from invest_agent.domain.models import (
            AgentRun,
            Decision,
            DecisionOutcome,
            RunStatus,
            Thesis,
        )
        from invest_agent.storage.repositories import (
            AgentRunRepository,
            DecisionRepository,
            OrderRepository,
            ThesisRepository,
        )

        # Create required foreign key references
        thesis_repo = ThesisRepository(self.db_path)
        thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        thesis_repo.save(thesis)

        run_repo = AgentRunRepository(self.db_path)
        run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        run_repo.save(run)

        decision_repo = DecisionRepository(self.db_path)
        decision = Decision(id=uuid4(), thesis_id=thesis.id, run_id=run.id, outcome=DecisionOutcome.TRADE, rationale="test")
        decision_repo.save(decision)

        repo = OrderRepository(self.db_path)
        order = OrderRecord(
            id=uuid4(),
            run_id=run.id,
            decision_id=decision.id,
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type="LIMIT",
            quantity=Decimal("10.123456789"),
            price=Decimal("70000.12345"),
            status=OrderStatus.ACKNOWLEDGED,
        )
        repo.save(order)
        retrieved = repo.get(order.id)
        assert retrieved.quantity == Decimal("10.123456789")
        assert retrieved.price == Decimal("70000.12345")

    def test_utc_timestamps_preserved(self):
        from invest_agent.storage.repositories import ThesisRepository
        repo = ThesisRepository(self.db_path)
        t = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        repo.save(t)
        retrieved = repo.get(t.id)
        assert retrieved.created_at.tzinfo is None
        assert retrieved.updated_at.tzinfo is None

    def test_execution_mode_recorded(self):
        from invest_agent.storage.repositories import AgentRunRepository
        repo = AgentRunRepository(self.db_path)
        run = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="KIS_PAPER")
        repo.save(run)
        retrieved = repo.get(run.id)
        assert retrieved.execution_mode == "KIS_PAPER"

    def test_duplicate_save_is_upsert(self):
        from invest_agent.storage.repositories import ThesisRepository
        repo = ThesisRepository(self.db_path)
        thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        repo.save(thesis)
        thesis.hypothesis = "H1_updated"
        repo.save(thesis)
        retrieved = repo.get(thesis.id)
        assert retrieved.hypothesis == "H1_updated"

    def test_restrict_delete_thesis_preserves_evidence(self):
        """FK가 RESTRICT이므로 가설 삭제 시 증거가 있으면 삭제 실패해야 함."""
        import sqlite3

        from invest_agent.storage.repositories import EvidenceRepository, ThesisRepository
        thesis_repo = ThesisRepository(self.db_path)
        evidence_repo = EvidenceRepository(self.db_path)

        thesis = Thesis(id=uuid4(), asset_id="KRX:005930", hypothesis="H1", rationale="R1")
        thesis_repo.save(thesis)

        evidence = Evidence(id=uuid4(), thesis_id=thesis.id, evidence_type=EvidenceType.PRICE, source="test", observed_at=datetime.utcnow(), collected_at=datetime.utcnow(), content={})
        evidence_repo.save(evidence)

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("DELETE FROM theses WHERE id = ?", (str(thesis.id),))
            conn.commit()
            assert False, "Should have raised IntegrityError due to RESTRICT FK"
        except sqlite3.IntegrityError:
            pass  # Expected
        finally:
            conn.close()

        # 증거가 그대로 유지되어야 함
        assert evidence_repo.get(evidence.id) is not None




class TestProviderSwitching:
    def test_env_overrides_yaml_when_yaml_is_default(self):
        import tempfile

        from invest_agent.settings import load_settings
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "fake", "model": "fixture-default", "endpoint": None},
            }, f)
            temp_path = f.name
        try:
            os.environ["INVEST_LLM_BASE_URL"] = "https://test.api/v1"
            os.environ["INVEST_LLM_MODEL"] = "test-model"
            os.environ["INVEST_LLM_API_KEY"] = "test-key"
            s = load_settings(temp_path)
            assert s.ai.endpoint == "https://test.api/v1"
            assert s.ai.model == "test-model"
            assert s.ai.api_key.get_secret_value() == "test-key"
        finally:
            os.unlink(temp_path)
            for k in ["INVEST_LLM_BASE_URL", "INVEST_LLM_MODEL", "INVEST_LLM_API_KEY"]:
                os.environ.pop(k, None)

    def test_ollama_provider_from_env(self):
        import tempfile

        from invest_agent.settings import load_settings
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "ollama", "model": "fixture-default"},
            }, f)
            temp_path = f.name
        try:
            os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"
            os.environ["OLLAMA_MODEL"] = "qwen3.5:9b"
            s = load_settings(temp_path)
            assert s.ai.provider == "ollama"
            assert s.ai.endpoint == "http://localhost:11434/v1"
            assert s.ai.model == "qwen3.5:9b"
        finally:
            os.unlink(temp_path)
            for k in ["OLLAMA_BASE_URL", "OLLAMA_MODEL"]:
                os.environ.pop(k, None)

    def test_yaml_explicit_value_not_overridden(self):
        import tempfile

        from invest_agent.settings import load_settings
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "openai_compatible", "model": "explicit-model", "endpoint": "https://explicit.api/v1"},
            }, f)
            temp_path = f.name
        try:
            os.environ["INVEST_LLM_BASE_URL"] = "https://env.api/v1"
            os.environ["INVEST_LLM_MODEL"] = "env-model"
            s = load_settings(temp_path)
            assert s.ai.model == "explicit-model"
            assert s.ai.endpoint == "https://explicit.api/v1"
        finally:
            os.unlink(temp_path)
            for k in ["INVEST_LLM_BASE_URL", "INVEST_LLM_MODEL"]:
                os.environ.pop(k, None)

    def test_secret_keys_not_in_logs(self):
        import tempfile

        from invest_agent.settings import load_settings
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "openai_compatible", "model": "test", "endpoint": "https://api.test/v1", "api_key": "secret-key-123"},
            }, f)
            temp_path = f.name
        try:
            s = load_settings(temp_path)
            assert s.ai.api_key.get_secret_value() == "secret-key-123"
            assert "secret-key-123" not in repr(s)
        finally:
            os.unlink(temp_path)


class TestMigrationFromLegacy:
    """기존 DB(CASCADE FK)에서 신규 DB(RESTRICT FK)로 마이그레이션 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def _create_legacy_db_with_cascade_fk(self):
        """구버전 스키마(CASCADE FK)로 DB 생성."""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            conn.execute('''CREATE TABLE theses (id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, hypothesis TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, metadata TEXT NOT NULL DEFAULT '{ }')''')
            conn.execute('''CREATE TABLE evidence (id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL, evidence_type TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL, collected_at TEXT NOT NULL, content TEXT NOT NULL DEFAULT '{ }', raw_ref TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE decisions (id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL, run_id TEXT NOT NULL, outcome TEXT NOT NULL, side TEXT, target_weight_bps INTEGER, current_weight_bps INTEGER, rationale TEXT NOT NULL, evidence_ids TEXT NOT NULL DEFAULT '[]', model_provider TEXT NOT NULL, model_name TEXT NOT NULL, execution_mode TEXT NOT NULL, decided_at TEXT NOT NULL, error TEXT, metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE CASCADE, FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE agent_runs (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL, execution_mode TEXT NOT NULL, schedule_id TEXT, thesis_ids TEXT NOT NULL DEFAULT '[]', decision_ids TEXT NOT NULL DEFAULT '[]', order_ids TEXT NOT NULL DEFAULT '[]', error TEXT, metadata TEXT NOT NULL DEFAULT '{ }')''')
            conn.execute('''CREATE TABLE orders (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, decision_id TEXT NOT NULL, asset_id TEXT NOT NULL, side TEXT NOT NULL, order_type TEXT NOT NULL, quantity TEXT NOT NULL, price TEXT, status TEXT NOT NULL, broker_order_id TEXT, submitted_at TEXT, acknowledged_at TEXT, filled_at TEXT, filled_quantity TEXT NOT NULL DEFAULT '0', filled_price TEXT, commission TEXT NOT NULL DEFAULT '0', tax TEXT NOT NULL DEFAULT '0', error TEXT, metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE, FOREIGN KEY (decision_id) REFERENCES decisions(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE handoffs (id TEXT PRIMARY KEY, from_run_id TEXT NOT NULL, to_run_id TEXT NOT NULL, thesis_id TEXT NOT NULL, previous_decision_id TEXT NOT NULL, previous_outcome TEXT NOT NULL, new_outcome TEXT NOT NULL, changed INTEGER NOT NULL, change_reason TEXT NOT NULL, model_provider_from TEXT NOT NULL, model_provider_to TEXT NOT NULL, model_name_from TEXT NOT NULL, model_name_to TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY (from_run_id) REFERENCES agent_runs(id) ON DELETE CASCADE, FOREIGN KEY (to_run_id) REFERENCES agent_runs(id) ON DELETE CASCADE, FOREIGN KEY (thesis_id) REFERENCES theses(id) ON DELETE CASCADE, FOREIGN KEY (previous_decision_id) REFERENCES decisions(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE equity_snapshots (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, timestamp TEXT NOT NULL, total_equity TEXT NOT NULL DEFAULT '0', cash_balance TEXT NOT NULL DEFAULT '0', positions TEXT NOT NULL DEFAULT '{ }', unrealized_pnl TEXT NOT NULL DEFAULT '0', realized_pnl TEXT NOT NULL DEFAULT '0', metadata TEXT NOT NULL DEFAULT '{ }', FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE)''')
            conn.execute('''CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))''')
            conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.commit()
        finally:
            conn.close()

    def test_migrate_legacy_db_preserves_data_and_changes_fk_to_restrict(self):
        """구버전 DB 마이그레이션: 데이터 보존 + FK가 RESTRICT로 변경."""
        # 1. 구버전 DB(CASCADE FK) 생성
        self._create_legacy_db_with_cascade_fk()

        # 2. 테스트 데이터 삽입
        import sqlite3
        from uuid import uuid4
        from datetime import datetime
        from decimal import Decimal
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            thesis_id = str(uuid4())
            run_id = str(uuid4())
            decision_id = str(uuid4())
            evidence_id = str(uuid4())
            order_id = str(uuid4())
            handoff_id = str(uuid4())
            snapshot_id = str(uuid4())

            now = datetime.utcnow().isoformat()

            # 가설
            conn.execute(
                "INSERT INTO theses (id, asset_id, hypothesis, rationale, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (thesis_id, "KRX:005930", "Test hypothesis", "Test rationale", now, now),
            )
            # 실행
            conn.execute(
                "INSERT INTO agent_runs (id, started_at, status, execution_mode) VALUES (?, ?, ?, ?)",
                (run_id, now, "COMPLETED", "OFFLINE_SIM"),
            )
            # 판단
            conn.execute(
                "INSERT INTO decisions (id, thesis_id, run_id, outcome, rationale, model_provider, model_name, execution_mode, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (decision_id, thesis_id, run_id, "TRADE", "Test rationale", "nvidia", "nemotron", "OFFLINE_SIM", now),
            )
            # 증거
            conn.execute(
                "INSERT INTO evidence (id, thesis_id, evidence_type, source, observed_at, collected_at, content) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (evidence_id, thesis_id, "PRICE", "test", now, now, '{"price": 70000}'),
            )
            # 주문
            cursor = conn.execute(
                "INSERT INTO orders (id, run_id, decision_id, asset_id, side, order_type, quantity, price, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, run_id, decision_id, "KRX:005930", "BUY", "LIMIT", "10", "70000", "ACKNOWLEDGED"),
            )
            print(f'DEBUG: orders rowcount = {cursor.rowcount}')
            # 인계
            cursor = conn.execute(
                "INSERT INTO handoffs (id, from_run_id, to_run_id, thesis_id, previous_decision_id, previous_outcome, new_outcome, changed, change_reason, model_provider_from, model_provider_to, model_name_from, model_name_to, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (handoff_id, run_id, run_id, thesis_id, decision_id, "NO_TRADE", "TRADE", 1, "test", "fake", "nvidia", "model1", "model2", now),
            )
            print(f'DEBUG: handoffs rowcount = {cursor.rowcount}')
            # 스냅샷
            conn.execute(
                "INSERT INTO equity_snapshots (id, run_id, timestamp, total_equity, cash_balance) VALUES (?, ?, ?, ?, ?)",
                (snapshot_id, run_id, now, "100000000", "50000000"),
            )
            conn.commit()
        finally:
            conn.close()

        # 3. 마이그레이션 실행
        from invest_agent.storage.schema import migrate, get_schema_version
        migrate(self.db_path)

        # 4. 스키마 버전이 2로 업데이트되었는지 확인
        version = get_schema_version(self.db_path)
        assert version == 2

        # 5. FK가 RESTRICT로 변경되었는지 검증 (PRAGMA foreign_key_list)
        conn = sqlite3.connect(str(self.db_path))
        try:
            tables_with_fk = [
                ("evidence", "thesis_id"),
                ("decisions", "thesis_id"),
                ("decisions", "run_id"),
                ("orders", "run_id"),
                ("orders", "decision_id"),
                ("handoffs", "from_run_id"),
                ("handoffs", "to_run_id"),
                ("handoffs", "thesis_id"),
                ("handoffs", "previous_decision_id"),
                ("equity_snapshots", "run_id"),
            ]
            for table, fk_col in tables_with_fk:
                fk_list = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
                # 각 FK에 대해 ON DELETE RESTRICT 확인
                for fk in fk_list:
                    # fk 튜플: (id, seq, table, from, to, on_update, on_delete, match)
                    on_delete = fk[6]
                    assert on_delete == "RESTRICT", f"Table {table} FK {fk_col} should be RESTRICT, got {on_delete}"
        finally:
            conn.close()

        # 6. 데이터가 보존되었는지 검증
        from invest_agent.storage.repositories import (
            ThesisRepository, EvidenceRepository, DecisionRepository,
            AgentRunRepository, OrderRepository, HandoffRepository,
            EquitySnapshotRepository
        )
        thesis_repo = ThesisRepository(self.db_path)
        evidence_repo = EvidenceRepository(self.db_path)
        decision_repo = DecisionRepository(self.db_path)
        run_repo = AgentRunRepository(self.db_path)
        order_repo = OrderRepository(self.db_path)
        handoff_repo = HandoffRepository(self.db_path)
        snapshot_repo = EquitySnapshotRepository(self.db_path)

        assert thesis_repo.get(thesis_id) is not None
        assert evidence_repo.get(evidence_id) is not None
        assert decision_repo.get(decision_id) is not None
        assert run_repo.get(run_id) is not None
        assert order_repo.get(order_id) is not None
        assert handoff_repo.get(handoff_id) is not None
        assert snapshot_repo.get(snapshot_id) is not None

        # 7. 삭제 제한 검증: 자식이 있는 부모 삭제 시 IntegrityError 발생
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # 가설 삭제 시도 (증거가 있으므로 실패해야 함)
            conn.execute("DELETE FROM theses WHERE id = ?", (thesis_id,))
            conn.commit()
            assert False, "Should have raised IntegrityError due to RESTRICT FK"
        except sqlite3.IntegrityError:
            pass  # Expected
        finally:
            conn.close()

        # 8. 자식이 없는 부모는 삭제 가능해야 함
        # 새로운 가설 생성 (자식 없음)
        new_thesis_id = str(uuid4())
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO theses (id, asset_id, hypothesis, rationale, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_thesis_id, "US:AAPL", "New hypothesis", "New rationale", now, now),
            )
            conn.commit()
            # 자식 없으므로 삭제 가능
            conn.execute("DELETE FROM theses WHERE id = ?", (new_thesis_id,))
            conn.commit()
        finally:
            conn.close()
        # 삭제되었는지 확인
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT id FROM theses WHERE id = ?", (new_thesis_id,)).fetchone()
            assert row is None
        finally:
            conn.close()

