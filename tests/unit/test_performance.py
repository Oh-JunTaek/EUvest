"""포트폴리오 성과 분석 단위 테스트."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.domain.models import (
    CashFlow,
    CashFlowType,
    PortfolioSnapshot,
)
from invest_agent.performance import (
    analyze_portfolio_performance,
)
from invest_agent.storage.repositories import (
    CashFlowRepository,
    PortfolioSnapshotRepository,
)
from invest_agent.storage.schema import ensure_db


class TestPerformanceAnalysis:
    """성과 분석 핵심 로직 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.snapshot_repo = PortfolioSnapshotRepository(self.db_path)
        self.cashflow_repo = CashFlowRepository(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def _create_snapshot(self, timestamp: datetime, total_equity: Decimal, equity_complete: bool = True) -> PortfolioSnapshot:
        snapshot = PortfolioSnapshot(
            id=uuid4(),
            timestamp=timestamp,
            total_equity=total_equity,
            equity_complete=equity_complete,
        )
        self.snapshot_repo.save(snapshot)
        return snapshot

    def _create_cashflow(self, occurred_at: datetime, flow_type: CashFlowType, currency: str, amount: Decimal) -> CashFlow:
        cf = CashFlow(
            id=uuid4(),
            idempotency_key=f"test_{uuid4().hex[:8]}",
            occurred_at=occurred_at,
            recorded_at=datetime.now(UTC),
            flow_type=flow_type,
            currency=currency,
            amount=amount,
            balance_before=Decimal("100000000"),
            balance_after=Decimal("100000000") + amount,
        )
        self.cashflow_repo.save(cf)
        return cf

    def test_no_snapshots(self):
        intervals = analyze_portfolio_performance(str(self.db_path))
        assert intervals == []

    def test_one_snapshot(self):
        self._create_snapshot(datetime.now(UTC), Decimal("100000000"))
        intervals = analyze_portfolio_performance(str(self.db_path))
        assert intervals == []

    def test_two_snapshots_no_cashflows(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101000000"))

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.start_value == Decimal("100000000")
        assert interval.end_value == Decimal("101000000")
        assert interval.net_external_flow == Decimal("0")
        assert interval.adjusted_change == Decimal("1000000")

    def test_krw_deposit(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101000000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            CashFlowType.DEPOSIT, "KRW", Decimal("1000000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.total_deposits_krw == Decimal("1000000")
        assert interval.total_withdrawals_krw == Decimal("0")
        assert interval.net_external_flow == Decimal("1000000")
        assert interval.adjusted_change == Decimal("0")

    def test_krw_withdrawal(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("99000000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            CashFlowType.WITHDRAWAL, "KRW", Decimal("1000000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.total_deposits_krw == Decimal("0")
        assert interval.total_withdrawals_krw == Decimal("1000000")
        assert interval.net_external_flow == Decimal("-1000000")
        assert interval.adjusted_change == Decimal("0")
