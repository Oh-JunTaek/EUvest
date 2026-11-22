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
    PerformanceInterval,
    analyze_portfolio_performance,
    format_performance_report,
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

    def test_usd_cashflow_non_calculable(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101000000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            CashFlowType.DEPOSIT, "USD", Decimal("1000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is False
        assert interval.adjusted_change is None
        assert any("USD" in r for r in interval.non_calculable_reasons)

    def test_incomplete_snapshot_non_calculable(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"), equity_complete=False)
        self._create_snapshot(t2, Decimal("101000000"))

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is False
        assert interval.adjusted_change is None
        assert any("불완전" in r for r in interval.non_calculable_reasons)

    def test_negative_equity_non_calculable(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("-1000000"))
        self._create_snapshot(t2, Decimal("101000000"))

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is False
        assert any("음수" in r for r in interval.non_calculable_reasons)

    def test_interval_boundary_exclude_start_include_end(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101000000"))
        self._create_cashflow(t1, CashFlowType.DEPOSIT, "KRW", Decimal("1000000"))
        self._create_cashflow(t2, CashFlowType.DEPOSIT, "KRW", Decimal("1000000"))

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.total_deposits_krw == Decimal("1000000")

    def test_same_timestamp_snapshots_skipped(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t1, Decimal("100500000"))
        self._create_snapshot(t2, Decimal("101000000"))

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1

    def test_limit_parameter(self):
        for i in range(5):
            self._create_snapshot(
                datetime(2025, 1, i + 1, 10, 0, 0, tzinfo=UTC),
                Decimal("100000000") + Decimal(str(i * 1000000))
            )

        intervals = analyze_portfolio_performance(str(self.db_path), limit=2)
        assert len(intervals) == 2

    def test_db_unchanged_after_analysis(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101000000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            CashFlowType.DEPOSIT, "KRW", Decimal("1000000")
        )

        snaps_before = self.snapshot_repo.get_all()
        cfs_before = self.cashflow_repo.get_all()

        analyze_portfolio_performance(str(self.db_path))

        snaps_after = self.snapshot_repo.get_all()
        cfs_after = self.cashflow_repo.get_all()

        assert len(snaps_after) == len(snaps_before)
        assert len(cfs_after) == len(cfs_before)
        assert snaps_after[0].id == snaps_before[0].id
        assert cfs_after[0].id == cfs_before[0].id

    def test_modified_dietz_no_cashflows(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101000000"))

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.weighted_external_flow == Decimal("0")
        assert interval.period_return_pct == Decimal("1.0000")

    def test_modified_dietz_mid_period_deposit(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101500000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC),
            CashFlowType.DEPOSIT, "KRW", Decimal("1000000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.weighted_external_flow == Decimal("500000.00")
        assert interval.period_return_pct == Decimal("0.4975")

    def test_modified_dietz_early_deposit(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101500000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC),
            CashFlowType.DEPOSIT, "KRW", Decimal("1000000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.weighted_external_flow > Decimal("900000")
        assert interval.weighted_external_flow < Decimal("1000000")

    def test_modified_dietz_late_deposit(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101500000"))
        self._create_cashflow(
            datetime(2025, 1, 2, 9, 0, 0, tzinfo=UTC),
            CashFlowType.DEPOSIT, "KRW", Decimal("1000000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.weighted_external_flow > Decimal("0")
        assert interval.weighted_external_flow < Decimal("100000")

    def test_modified_dietz_withdrawal(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("99500000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC),
            CashFlowType.WITHDRAWAL, "KRW", Decimal("1000000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.weighted_external_flow == Decimal("-500000.00")
        assert interval.period_return_pct == Decimal("0.5025")

    def test_modified_dietz_denominator_zero_or_negative(self):
        """분모 0 이하: 계산 불가.

        시작 평가액이 0이고 초반에 큰 출금이 발생하면
        시작 평가액 + 가중 외부 현금흐름 <= 0이 되어 계산 불가.
        """
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("0"))
        self._create_snapshot(t2, Decimal("1000000"))
        # 초반에 큰 출금 발생 (가중치 높음) -> 분모가 음수
        self._create_cashflow(
            datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC),
            CashFlowType.WITHDRAWAL, "KRW", Decimal("1000000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is False
        assert interval.period_return_pct is None
        assert any("분모" in r for r in interval.non_calculable_reasons)

    def test_modified_dietz_zero_duration(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t1, Decimal("101000000"))

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 0

    def test_mixed_deposit_withdrawal(self):
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal("100000000"))
        self._create_snapshot(t2, Decimal("101500000"))
        self._create_cashflow(
            datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            CashFlowType.DEPOSIT, "KRW", Decimal("2000000")
        )
        self._create_cashflow(
            datetime(2025, 1, 1, 14, 0, 0, tzinfo=UTC),
            CashFlowType.WITHDRAWAL, "KRW", Decimal("500000")
        )

        intervals = analyze_portfolio_performance(str(self.db_path))
        assert len(intervals) == 1
        interval = intervals[0]
        assert interval.calculable is True
        assert interval.total_deposits_krw == Decimal("2000000")
        assert interval.total_withdrawals_krw == Decimal("500000")
        assert interval.net_external_flow == Decimal("1500000")
        assert interval.adjusted_change == Decimal("0")


class TestFormatPerformanceReport:
    """리포트 포맷팅 테스트."""

    def test_empty_intervals(self):
        """빈 구간: 안내 메시지."""
        report = format_performance_report([])
        assert "분석할 구간이 없습니다" in report

    def test_single_interval_calculable(self):
        """계산 가능 구간: 전체 필드 출력."""
        from datetime import UTC, datetime
        from decimal import Decimal
        from uuid import uuid4

        from invest_agent.domain.models import PortfolioSnapshot

        snap1 = PortfolioSnapshot(
            id=uuid4(),
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            total_equity=Decimal("100000000"),
        )
        snap2 = PortfolioSnapshot(
            id=uuid4(),
            timestamp=datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC),
            total_equity=Decimal("101000000"),
        )
        interval = PerformanceInterval(
            start_snapshot=snap1,
            end_snapshot=snap2,
            start_cashflows=[],
            end_cashflows=[],
            start_value=Decimal("100000000"),
            end_value=Decimal("101000000"),
            total_deposits_krw=Decimal("0"),
            total_withdrawals_krw=Decimal("0"),
            net_external_flow=Decimal("0"),
            weighted_external_flow=Decimal("0"),
            adjusted_change=Decimal("1000000"),
            period_return_pct=Decimal("0.9901"),
            calculable=True,
            non_calculable_reasons=[],
        )
        report = format_performance_report([interval])
        assert "포트폴리오 성과 분석" in report
        assert "100,000,000" in report
        assert "101,000,000" in report
        assert "가능" in report

    def test_single_interval_non_calculable(self):
        """계산 불가 구간: 사유 출력."""
        from datetime import UTC, datetime
        from decimal import Decimal
        from uuid import uuid4

        from invest_agent.domain.models import PortfolioSnapshot

        snap1 = PortfolioSnapshot(
            id=uuid4(),
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            total_equity=Decimal("100000000"),
        )
        snap2 = PortfolioSnapshot(
            id=uuid4(),
            timestamp=datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC),
            total_equity=Decimal("101000000"),
        )
        interval = PerformanceInterval(
            start_snapshot=snap1,
            end_snapshot=snap2,
            start_cashflows=[],
            end_cashflows=[],
            start_value=Decimal("100000000"),
            end_value=Decimal("101000000"),
            total_deposits_krw=Decimal("0"),
            total_withdrawals_krw=Decimal("0"),
            net_external_flow=Decimal("0"),
            weighted_external_flow=Decimal("0"),
            adjusted_change=None,
            period_return_pct=None,
            calculable=False,
            non_calculable_reasons=["시작 스냅샷 불완전: 평가 불완전"],
        )
        report = format_performance_report([interval])
        assert "불가능" in report
        assert "계산 불가" in report
        assert "불완전" in report


class TestPerformanceCLI:
    """portfolio performance CLI 명령어 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def _run_cli(self, args):
        """Typer 앱 실행 헬퍼."""
        from typer.testing import CliRunner

        from invest_agent.cli import app

        runner = CliRunner()
        return runner.invoke(app, args)

    def test_cli_performance_no_snapshots(self):
        """스냅샷 없음: 적절한 메시지."""
        result = self._run_cli(["portfolio", "performance", "--db", str(self.db_path)])
        assert result.exit_code == 0
        assert "분석할 구간이 없습니다" in result.output

    def test_cli_performance_with_data(self):
        """데이터 있을 때: 정상 출력."""
        snap_repo = PortfolioSnapshotRepository(self.db_path)
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        snap_repo.save(PortfolioSnapshot(id=uuid4(), timestamp=t1, total_equity=Decimal("100000000")))
        snap_repo.save(PortfolioSnapshot(id=uuid4(), timestamp=t2, total_equity=Decimal("101000000")))

        result = self._run_cli(["portfolio", "performance", "--db", str(self.db_path)])
        assert result.exit_code == 0
        assert "포트폴리오 성과 분석" in result.output
        assert "100,000,000" in result.output
        assert "101,000,000" in result.output

    def test_cli_performance_limit_option(self):
        """--limit 옵션 동작."""
        snap_repo = PortfolioSnapshotRepository(self.db_path)
        for i in range(5):
            snap_repo.save(PortfolioSnapshot(
                id=uuid4(),
                timestamp=datetime(2025, 1, i + 1, 10, 0, 0, tzinfo=UTC),
                total_equity=Decimal("100000000") + Decimal(str(i * 1000000))
            ))

        result = self._run_cli(["portfolio", "performance", "--db", str(self.db_path), "--limit", "2"])
        assert result.exit_code == 0
        assert "분석 구간 수: 2개" in result.output
