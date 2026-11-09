"""P0-08 integration test - ContextBuilder, ThesisManager, HandoffSnapshot."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.agent.context_builder import ContextBuilder
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
