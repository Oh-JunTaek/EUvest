"""P0-08 integration test - ContextBuilder, ThesisManager, HandoffSnapshot."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.agent.context_builder import ContextBuilder
from invest_agent.agent.thesis_manager import ThesisManager
from invest_agent.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    RunStatus,
)
from invest_agent.domain.models import (
    AgentRun,
    Decision,
    DecisionOutcome,
    EquitySnapshot,
    OrderRecord,
    Thesis,
)
from invest_agent.storage.repositories import (
    AgentRunRepository,
    DecisionRepository,
    EquitySnapshotRepository,
    HandoffRepository,
    OrderRepository,
    ThesisRepository,
)
from invest_agent.storage.schema import ensure_db


class TestContextBuilder:
    """ContextBuilder integration tests."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        Path(self.temp_dir).rmdir()

    def _create_test_data(self):
        """Create test thesis, run, decision, order, snapshot."""
        thesis = Thesis(
            id=uuid4(),
            asset_id="KRX:005930",
            hypothesis="Samsung will rise",
            rationale="Strong earnings",
            metadata={"price_below": 60000, "timeout_days": 30},
        )
        thesis_repo = ThesisRepository(self.db_path)
        thesis_repo.save(thesis)

        run = AgentRun(
            id=uuid4(),
            status=RunStatus.COMPLETED,
            execution_mode="OFFLINE_SIM",
        )
        run_repo = AgentRunRepository(self.db_path)
        run_repo.save(run)

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            rationale="Buy signal",
            model_provider="fake",
            model_name="fake-model",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo = DecisionRepository(self.db_path)
        decision_repo.save(decision)

        order = OrderRecord(
            id=uuid4(),
            run_id=run.id,
            decision_id=decision.id,
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=70000,
            status=OrderStatus.ACKNOWLEDGED,
        )
        order_repo = OrderRepository(self.db_path)
        order_repo.save(order)

        snapshot = EquitySnapshot(
            id=uuid4(),
            run_id=run.id,
            timestamp=datetime.now(UTC),
            total_equity=100000000,
            cash_balance=50000000,
            positions={"KRX:005930": {"quantity": "100", "avg_price": "70000"}},
            unrealized_pnl=0,
            realized_pnl=0,
        )
        snapshot_repo = EquitySnapshotRepository(self.db_path)
        snapshot_repo.save(snapshot)

        return thesis, run, decision, order, snapshot

    def test_build_context(self):
        """Test ContextBuilder.build_context creates valid ContextEnvelope."""
        thesis, run, decision, order, snapshot = self._create_test_data()

        builder = ContextBuilder(str(self.db_path))
        envelope = builder.build_context(run.id, max_history=10)

        assert envelope.run_id == run.id
        assert len(envelope.active_theses) == 1
        assert envelope.active_theses[0].asset_id == "KRX:005930"
        assert envelope.active_theses[0].hypothesis == "Samsung will rise"
        assert len(envelope.falsification_conditions) == 2
        assert len(envelope.recent_history) == 1
        assert envelope.latest_snapshot is not None
        assert len(envelope.open_orders) == 1
        assert envelope.total_equity == Decimal("100000000")
        assert envelope.available_cash_krw == Decimal("50000000")


class TestHandoffSnapshot:
    """HandoffSnapshot tests."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        Path(self.temp_dir).rmdir()

    def _create_test_data(self):
        """Create test thesis, run, decision, order, snapshot."""
        thesis = Thesis(
            id=uuid4(),
            asset_id="KRX:005930",
            hypothesis="Samsung will rise",
            rationale="Strong earnings",
            metadata={"price_below": 60000, "timeout_days": 30},
        )
        thesis_repo = ThesisRepository(self.db_path)
        thesis_repo.save(thesis)

        run = AgentRun(
            id=uuid4(),
            status=RunStatus.COMPLETED,
            execution_mode="OFFLINE_SIM",
        )
        run_repo = AgentRunRepository(self.db_path)
        run_repo.save(run)

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            rationale="Buy signal",
            model_provider="fake",
            model_name="fake-model",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo = DecisionRepository(self.db_path)
        decision_repo.save(decision)

        order = OrderRecord(
            id=uuid4(),
            run_id=run.id,
            decision_id=decision.id,
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=70000,
            status=OrderStatus.ACKNOWLEDGED,
        )
        order_repo = OrderRepository(self.db_path)
        order_repo.save(order)

        snapshot = EquitySnapshot(
            id=uuid4(),
            run_id=run.id,
            timestamp=datetime.now(UTC),
            total_equity=100000000,
            cash_balance=50000000,
            positions={"KRX:005930": {"quantity": "100", "avg_price": "70000"}},
            unrealized_pnl=0,
            realized_pnl=0,
        )
        snapshot_repo = EquitySnapshotRepository(self.db_path)
        snapshot_repo.save(snapshot)

        return thesis, run, decision, order, snapshot

    def test_handoff_snapshot_to_dict(self):
        """Test HandoffSnapshot.to_dict() serialization."""
        thesis, run, decision, order, snapshot = self._create_test_data()

        builder = ContextBuilder(str(self.db_path))
        envelope = builder.build_context(run.id, max_history=10)

        manager = ThesisManager(str(self.db_path))
        to_run = AgentRun(id=uuid4(), status=RunStatus.CREATED, execution_mode="OFFLINE_SIM")
        run_repo = AgentRunRepository(self.db_path)
        run_repo.save(to_run)

        handoff = manager.create_handoff_snapshot(
            from_run_id=run.id,
            to_run_id=to_run.id,
            context=envelope,
            previous_decision_id=decision.id,
            model_provider_from="fake",
            model_provider_to="nvidia",
            model_name_from="fake-model",
            model_name_to="nemotron-3-ultra",
            change_reason="Model upgrade",
        )

        # Test to_dict
        data = handoff.to_dict()
        assert data["from_run_id"] == str(run.id)
        assert data["model_provider_from"] == "fake"
        assert data["model_provider_to"] == "nvidia"
        assert data["change_reason"] == "Model upgrade"
        assert len(data["active_theses"]) == 1
        assert len(data["falsification_conditions"]) == 2
        assert data["total_equity"] == "100000000"
        assert len(data["open_orders"]) == 1

    def test_handoff_persisted_in_db(self):
        """Test Handoff is saved to SQLite and can be retrieved."""
        thesis, run, decision, order, snapshot = self._create_test_data()

        builder = ContextBuilder(str(self.db_path))
        envelope = builder.build_context(run.id, max_history=10)

        manager = ThesisManager(str(self.db_path))
        to_run = AgentRun(id=uuid4(), status=RunStatus.CREATED, execution_mode="OFFLINE_SIM")
        run_repo = AgentRunRepository(self.db_path)
        run_repo.save(to_run)

        manager.create_handoff_snapshot(
            from_run_id=run.id,
            to_run_id=to_run.id,
            context=envelope,
            previous_decision_id=decision.id,
            model_provider_from="fake",
            model_provider_to="nvidia",
            model_name_from="fake-model",
            model_name_to="nemotron-3-ultra",
            change_reason="Model upgrade",
        )

        # Verify Handoff was saved to DB
        handoff_repo = HandoffRepository(self.db_path)
        saved_handoffs = handoff_repo.get_by_thesis(thesis.id)
        assert len(saved_handoffs) == 1
        saved = saved_handoffs[0]
        assert saved.from_run_id == run.id
        assert saved.model_provider_from == "fake"
        assert saved.model_provider_to == "nvidia"
        assert saved.change_reason == "Model upgrade"


class TestModelHandoff:
    """A->B->A model handoff integration test."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        Path(self.temp_dir).rmdir()

    def test_model_handoff_a_to_b_to_a(self):
        """Test full A->B->A model handoff preserves thesis and history."""
        thesis = Thesis(
            id=uuid4(),
            asset_id="KRX:005930",
            hypothesis="Samsung will rise",
            rationale="Strong earnings",
            metadata={"price_below": 60000, "timeout_days": 30},
        )
        thesis_repo = ThesisRepository(self.db_path)
        thesis_repo.save(thesis)

        run_a = AgentRun(id=uuid4(), status=RunStatus.COMPLETED, execution_mode="OFFLINE_SIM")
        run_repo = AgentRunRepository(self.db_path)
        run_repo.save(run_a)

        decision_a = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run_a.id,
            outcome=DecisionOutcome.TRADE,
            rationale="Buy signal",
            model_provider="fake",
            model_name="fake-model",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo = DecisionRepository(self.db_path)
        decision_repo.save(decision_a)

        order_a = OrderRecord(
            id=uuid4(),
            run_id=run_a.id,
            decision_id=decision_a.id,
            asset_id="KRX:005930",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=70000,
            status=OrderStatus.ACKNOWLEDGED,
        )
        order_repo = OrderRepository(self.db_path)
        order_repo.save(order_a)

        snapshot_a = EquitySnapshot(
            id=uuid4(),
            run_id=run_a.id,
            timestamp=datetime.now(UTC),
            total_equity=100000000,
            cash_balance=50000000,
            positions={"KRX:005930": {"quantity": "100", "avg_price": "70000"}},
            unrealized_pnl=0,
            realized_pnl=0,
        )
        snapshot_repo = EquitySnapshotRepository(self.db_path)
        snapshot_repo.save(snapshot_a)

        builder = ContextBuilder(str(self.db_path))
        envelope_a = builder.build_context(run_a.id, max_history=10)

        manager = ThesisManager(str(self.db_path))

        # Create run_b (to_run for A->B) and save it first
        run_b = AgentRun(id=uuid4(), status=RunStatus.CREATED, execution_mode="OFFLINE_SIM")
        run_repo.save(run_b)

        handoff_a_to_b = manager.create_handoff_snapshot(
            from_run_id=run_a.id,
            to_run_id=run_b.id,
            context=envelope_a,
            previous_decision_id=decision_a.id,
            model_provider_from="fake",
            model_provider_to="nvidia",
            model_name_from="fake-model",
            model_name_to="nemotron-3-ultra",
            change_reason="Model upgrade for better reasoning",
        )

        updates_ab = manager.apply_handoff(handoff_a_to_b)
        assert len(updates_ab) == 1

        handoff_repo = HandoffRepository(self.db_path)
        handoffs_ab = handoff_repo.get_by_thesis(thesis.id)
        assert len(handoffs_ab) == 1
        assert handoffs_ab[0].model_provider_from == "fake"
        assert handoffs_ab[0].model_provider_to == "nvidia"

        # Update run_b to COMPLETED with nvidia decision
        run_b.status = RunStatus.COMPLETED
        run_repo.save(run_b)

        decision_b = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run_b.id,
            outcome=DecisionOutcome.NO_TRADE,
            rationale="Re-evaluated, holding",
            model_provider="nvidia",
            model_name="nemotron-3-ultra",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision_b)

        snapshot_b = EquitySnapshot(
            id=uuid4(),
            run_id=run_b.id,
            timestamp=datetime.now(UTC),
            total_equity=100000000,
            cash_balance=50000000,
            positions={"KRX:005930": {"quantity": "100", "avg_price": "70000"}},
            unrealized_pnl=0,
            realized_pnl=0,
        )
        snapshot_repo.save(snapshot_b)

        envelope_b = builder.build_context(run_b.id, max_history=10)

        # Create run_c (to_run for B->A) and save it first
        run_c = AgentRun(id=uuid4(), status=RunStatus.CREATED, execution_mode="OFFLINE_SIM")
        run_repo.save(run_c)

        handoff_b_to_a = manager.create_handoff_snapshot(
            from_run_id=run_b.id,
            to_run_id=run_c.id,
            context=envelope_b,
            previous_decision_id=decision_b.id,
            model_provider_from="nvidia",
            model_provider_to="fake",
            model_name_from="nemotron-3-ultra",
            model_name_to="fake-model",
            change_reason="Rollback to stable model",
        )

        updates_ba = manager.apply_handoff(handoff_b_to_a)
        assert len(updates_ba) == 1

        handoffs_all = handoff_repo.get_by_thesis(thesis.id)
        assert len(handoffs_all) == 2
        providers_from = [h.model_provider_from for h in handoffs_all]
        providers_to = [h.model_provider_to for h in handoffs_all]
        assert "fake" in providers_from
        assert "nvidia" in providers_from
        assert "nvidia" in providers_to
        assert "fake" in providers_to

        thesis_final = thesis_repo.get(thesis.id)
        assert thesis_final is not None
        assert thesis_final.is_active is True
        assert thesis_final.hypothesis == "Samsung will rise"
        assert thesis_final.rationale == "Strong earnings"

        envelope_final = builder.build_context(run_b.id, max_history=10)
        assert len(envelope_final.recent_history) == 3

        dict_ab = handoff_a_to_b.to_dict()
        dict_ba = handoff_b_to_a.to_dict()
        assert dict_ab["model_provider_from"] == "fake"
        assert dict_ab["model_provider_to"] == "nvidia"
        assert dict_ba["model_provider_from"] == "nvidia"
        assert dict_ba["model_provider_to"] == "fake"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
