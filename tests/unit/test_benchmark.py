"""시장 벤치마크 비교 단위 테스트."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.benchmark import (
    BenchmarkResult,
    BENCHMARK_SYMBOLS,
    calculate_benchmark_return,
    compare_with_benchmarks,
    format_benchmark_report,
)
from invest_agent.domain.models import PortfolioSnapshot
from invest_agent.market.market_data import Market, OHLCV
from invest_agent.performance import PerformanceInterval, analyze_portfolio_performance
from invest_agent.storage.repositories import (
    CashFlowRepository,
    OHLCVRepository,
    PortfolioSnapshotRepository,
)
from invest_agent.storage.schema import ensure_db


class TestBenchmarkSymbols:
    """벤치마크 심볼 설정 테스트."""

    def test_kospi200_symbol_is_ks200(self):
        """KOSPI 200은 KS200 심볼을 사용해야 함 (KRX:252670 금지)."""
        info = BENCHMARK_SYMBOLS["KOSPI200"]
        assert info["asset_id"] == "KRX:KS200"
        assert info["market"] == Market.KRX
        assert info["currency"] == "KRW"
        assert info["index_type"] == "가격지수"
        assert info["is_index"] is True

    def test_spy_etf_not_sp500_index(self):
        """SP500 대신 SPY ETF로 표시되어야 함."""
        info = BENCHMARK_SYMBOLS["SPY_ETF"]
        assert info["asset_id"] == "US:SPY"
        assert info["market"] == Market.US
        assert info["currency"] == "USD"
        assert info["index_type"] == "ETF 가격수익률 (SPY)"
        assert info["is_index"] is False

class TestCalculateBenchmarkReturn:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        ensure_db(self.db_path)
        self.repo = OHLCVRepository(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def _save_ohlcv(self, asset_id: str, date_str: str, close: Decimal, provider: str = 'TestProvider'):
        ohlcv = OHLCV(
            timestamp=datetime.fromisoformat(date_str).replace(tzinfo=UTC),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000000,
            asset_id=asset_id,
            market=Market.KRX if asset_id.startswith('KRX:') else Market.US,
        )
        self.repo.save(ohlcv, provider=provider)

    def test_normal_kospi200_return(self):
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('300.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        portfolio_start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is True
        assert start_val == Decimal('300.00')
        assert end_val == Decimal('303.00')
        assert start_date == '2025-01-01'
        assert end_date == '2025-01-02'
        assert reasons == []

    def test_missing_start_price(self):
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        portfolio_start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is False
        assert any('시작 기준값: 데이터 없음' in r for r in reasons)

    def test_missing_end_price(self):
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('300.00'))
        """종료 가격 누락 - 포트폴리오 종료일 이후 데이터 없음."""
        portfolio_start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 10, 10, 0, 0, tzinfo=UTC)
        # 종료일을 데이터가 없는 미래로 설정 (2025-01-10)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is False
        assert any('종료 기준값: 데이터 없음' in r for r in reasons)

    def test_zero_price(self):
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('0'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        portfolio_start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is False
        assert any('종가 0 이하' in r for r in reasons)

    def test_negative_price(self):
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('-100'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        portfolio_start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is False
        assert any("시작 기준값: 데이터 무효 (OHLC 검증 실패)" in r for r in reasons)

    def test_future_price_not_used(self):
        self._save_ohlcv('KRX:KS200', '2025-01-03', Decimal('310.00'))
        portfolio_start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is False
        assert any('데이터 없음' in r for r in reasons)

    def test_data_freshness_exceeded(self):
        # 10일 전 데이터 저장 (검색 범위 내이지만 신선도 허용일 초과)
        self._save_ohlcv("KRX:KS200", "2024-12-22", Decimal("300.00"))
        self._save_ohlcv("KRX:KS200", "2024-12-23", Decimal("303.00"))
        # portfolio_start가 2025-01-01이면, 2024-12-22 데이터는 10일 전 데이터
        # max_days_back=10으로 검색 범위를 늘리고, max_freshness_days=5로 신선도 제한
        portfolio_start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 10, 10, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, "KOSPI200", portfolio_start, portfolio_end, max_freshness_days=5, max_days_back=10
        )
    def test_same_day_start_end_blocked(self):
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        portfolio_start = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 2, 15, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is False
        assert any('동일 거래일' in r for r in reasons)

    def test_price_confirmation_time_future_blocked(self):
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-03', Decimal('306.00'))
        portfolio_start = datetime(2025, 1, 2, 5, 0, 0, tzinfo=UTC)
        portfolio_end = datetime(2025, 1, 3, 10, 0, 0, tzinfo=UTC)
        start_val, end_val, start_date, end_date, calc, reasons = calculate_benchmark_return(
            self.repo, 'KOSPI200', portfolio_start, portfolio_end
        )
        assert calc is False
        assert any('종가 확정 시각' in r for r in reasons)
class TestCompareWithBenchmarks:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        ensure_db(self.db_path)
        self.snap_repo = PortfolioSnapshotRepository(self.db_path)
        self.cf_repo = CashFlowRepository(self.db_path)
        self.ohlcv_repo = OHLCVRepository(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def _create_snapshot(self, timestamp: datetime, total_equity: Decimal, equity_complete: bool = True):
        snap = PortfolioSnapshot(
            id=uuid4(),
            timestamp=timestamp,
            total_equity=total_equity,
            equity_complete=equity_complete,
        )
        self.snap_repo.save(snap)
        return snap

    def _save_ohlcv(self, asset_id: str, date_str: str, close: Decimal, provider: str = 'TestProvider'):
        ohlcv = OHLCV(
            timestamp=datetime.fromisoformat(date_str).replace(tzinfo=UTC),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000000,
            asset_id=asset_id,
            market=Market.KRX if asset_id.startswith('KRX:') else Market.US,
        )
        self.ohlcv_repo.save(ohlcv, provider=provider)

    def test_normal_kospi200_comparison(self):
        t1 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 22, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal('100000000'))
        self._create_snapshot(t2, Decimal('101000000'))
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('300.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        self._save_ohlcv('US:SPY', '2025-01-01', Decimal('480.00'))
        self._save_ohlcv('US:SPY', '2025-01-02', Decimal('484.80'))
        results = compare_with_benchmarks(str(self.db_path), limit=10)
        assert len(results) == 2
        kospi_result = next(r for r in results if r.benchmark_name == 'KOSPI200')
        assert kospi_result.benchmark_calculable is True
        assert kospi_result.benchmark_return_pct == Decimal('1.0000')
        assert kospi_result.portfolio_return_pct == Decimal('1.0000')
        assert kospi_result.excess_calculable is True
        assert kospi_result.excess_return_pct == Decimal('0.0000')
        spy_result = next(r for r in results if r.benchmark_name == 'SPY_ETF')
        assert spy_result.benchmark_calculable is True
        assert spy_result.benchmark_return_pct == Decimal('1.0000')
        assert spy_result.excess_calculable is False
        assert any("USD 기준" in r for r in spy_result.non_calculable_reasons)

    def test_portfolio_not_calculable(self):
        t1 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 22, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal('-1000000'))
        self._create_snapshot(t2, Decimal('101000000'))
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('300.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        results = compare_with_benchmarks(str(self.db_path), limit=10)
        kospi_result = next(r for r in results if r.benchmark_name == 'KOSPI200')
        assert kospi_result.portfolio_calculable is False
        assert kospi_result.excess_calculable is False
        assert any('포트폴리오 수익률 계산 불가' in r for r in kospi_result.non_calculable_reasons)

    def test_benchmark_data_missing(self):
        t1 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 22, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal('100000000'))
        self._create_snapshot(t2, Decimal('101000000'))
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('300.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        results = compare_with_benchmarks(str(self.db_path), limit=10)
        assert len(results) == 2
        kospi_result = next(r for r in results if r.benchmark_name == 'KOSPI200')
        assert kospi_result.benchmark_calculable is True
        spy_result = next(r for r in results if r.benchmark_name == 'SPY_ETF')
        assert spy_result.benchmark_calculable is False
        assert any('저장된 공급자 없음' in r for r in spy_result.non_calculable_reasons)

    def test_excess_return_accuracy(self):
        t1 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 22, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal('100000000'))
        self._create_snapshot(t2, Decimal('105000000'))
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('300.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('306.00'))
        results = compare_with_benchmarks(str(self.db_path), limit=10, benchmarks=['KOSPI200'])
        kospi_result = results[0]
        assert kospi_result.portfolio_return_pct == Decimal('5.0000')
        assert kospi_result.benchmark_return_pct == Decimal('2.0000')
        assert kospi_result.excess_return_pct == Decimal('3.0000')

    def test_limit_parameter(self):
        for i in range(5):
            self._create_snapshot(
                datetime(2025, 1, i + 1, 10, 0, 0, tzinfo=UTC),
                Decimal('100000000') + Decimal(str(i * 1000000))
            )
        self._save_ohlcv('KRX:KS200', '2025-01-01', Decimal('300.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-02', Decimal('303.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-03', Decimal('306.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-04', Decimal('309.00'))
        self._save_ohlcv('KRX:KS200', '2025-01-05', Decimal('312.00'))
        results = compare_with_benchmarks(str(self.db_path), limit=2, benchmarks=['KOSPI200'])
        assert len(results) == 2

    def test_empty_database(self):
        results = compare_with_benchmarks(str(self.db_path))
        assert results == []

    def test_db_unchanged_after_analysis(self):
        t1 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 22, 0, 0, tzinfo=UTC)
        self._create_snapshot(t1, Decimal('100000000'))
        self._create_snapshot(t2, Decimal('101000000'))
        snaps_before = self.snap_repo.get_all()
        compare_with_benchmarks(str(self.db_path))
        snaps_after = self.snap_repo.get_all()
        assert len(snaps_after) == len(snaps_before)
        assert snaps_after[0].id == snaps_before[0].id
class TestFormatBenchmarkReport:
    def test_empty_results(self):
        report = format_benchmark_report([])
        assert '비교할 구간이 없습니다' in report

    def test_single_interval_both_benchmarks(self):
        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        results = [
            BenchmarkResult(
                benchmark_name='KOSPI200',
                benchmark_type='KOSPI200',
                benchmark_currency='KRW',
                index_type='가격지수',
                portfolio_start=start,
                portfolio_end=end,
                portfolio_return_pct=Decimal('5.0000'),
                portfolio_calculable=True,
                benchmark_start_value=Decimal('300.00'),
                benchmark_end_value=Decimal('306.00'),
                benchmark_start_date='2025-01-01',
                benchmark_end_date='2025-01-02',
                benchmark_return_pct=Decimal('2.0000'),
                benchmark_calculable=True,
                excess_return_pct=Decimal('3.0000'),
                excess_calculable=True,
                non_calculable_reasons=[],
                data_source='FinanceDataReader (KRX:KS200)',
            ),
            BenchmarkResult(
                benchmark_name='SPY_ETF',
                benchmark_type='SPY_ETF',
                benchmark_currency='USD',
                index_type='ETF 가격수익률 (SPY)',
                portfolio_start=start,
                portfolio_end=end,
                portfolio_return_pct=Decimal('5.0000'),
                portfolio_calculable=True,
                benchmark_start_value=Decimal('480.00'),
                benchmark_end_value=Decimal('484.80'),
                benchmark_start_date='2025-01-01',
                benchmark_end_date='2025-01-02',
                benchmark_return_pct=Decimal('1.0000'),
                benchmark_calculable=True,
                excess_return_pct=None,
                excess_calculable=False,
                non_calculable_reasons=['SPY ETF는 USD 기준이므로 KRW 포트폴리오와 직접 비교 불가 (환율 근거 필요)'],
                data_source='FinanceDataReader (Yahoo Finance: SPY)',
            ),
        ]
        report = format_benchmark_report(results)
        assert '포트폴리오 vs 시장 벤치마크 비교' in report
        assert '5.0000%' in report
        assert 'KOSPI200' in report
        assert 'SPY_ETF' in report
        assert '초과수익률: +3.0000%p' in report
        assert '통화 불일치' in report

class TestBenchmarkCLI:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        ensure_db(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        os.rmdir(self.temp_dir)

    def _run_cli(self, args):
        from typer.testing import CliRunner
        from invest_agent.cli import app
        runner = CliRunner()
        return runner.invoke(app, args)

    def test_cli_benchmark_no_snapshots(self):
        result = self._run_cli(['portfolio', 'benchmark', '--db', str(self.db_path)])
        assert result.exit_code == 0
        assert '비교할 구간이 없습니다' in result.output

    def test_cli_benchmark_with_data(self):
        snap_repo = PortfolioSnapshotRepository(self.db_path)
        ohlcv_repo = OHLCVRepository(self.db_path)
        t1 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 22, 0, 0, tzinfo=UTC)
        snap_repo.save(PortfolioSnapshot(id=uuid4(), timestamp=t1, total_equity=Decimal('100000000')))
        snap_repo.save(PortfolioSnapshot(id=uuid4(), timestamp=t2, total_equity=Decimal('101000000')))
        ohlcv_repo.save(
            OHLCV(timestamp=datetime(2025, 1, 1, tzinfo=UTC), open=Decimal('300'), high=Decimal('300'), low=Decimal('300'), close=Decimal('300'), volume=1000000, asset_id='KRX:KS200', market=Market.KRX),
            provider='TestProvider'
        )
        ohlcv_repo.save(
            OHLCV(timestamp=datetime(2025, 1, 2, tzinfo=UTC), open=Decimal('303'), high=Decimal('303'), low=Decimal('303'), close=Decimal('303'), volume=1000000, asset_id='KRX:KS200', market=Market.KRX),
            provider='TestProvider'
        )
        result = self._run_cli(['portfolio', 'benchmark', '--db', str(self.db_path)])
        assert result.exit_code == 0
        assert '포트폴리오 vs 시장 벤치마크 비교' in result.output
        assert 'KOSPI200' in result.output

    def test_cli_benchmark_option(self):
        snap_repo = PortfolioSnapshotRepository(self.db_path)
        ohlcv_repo = OHLCVRepository(self.db_path)
        t1 = datetime(2025, 1, 1, 22, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 22, 0, 0, tzinfo=UTC)
        snap_repo.save(PortfolioSnapshot(id=uuid4(), timestamp=t1, total_equity=Decimal('100000000')))
        snap_repo.save(PortfolioSnapshot(id=uuid4(), timestamp=t2, total_equity=Decimal('101000000')))
        ohlcv_repo.save(
            OHLCV(timestamp=datetime(2025, 1, 1, tzinfo=UTC), open=Decimal('300'), high=Decimal('300'), low=Decimal('300'), close=Decimal('300'), volume=1000000, asset_id='KRX:KS200', market=Market.KRX),
            provider='TestProvider'
        )
        ohlcv_repo.save(
            OHLCV(timestamp=datetime(2025, 1, 2, tzinfo=UTC), open=Decimal('303'), high=Decimal('303'), low=Decimal('303'), close=Decimal('303'), volume=1000000, asset_id='KRX:KS200', market=Market.KRX),
            provider='TestProvider'
        )
        result = self._run_cli(['portfolio', 'benchmark', '--db', str(self.db_path), '--benchmark', 'KOSPI200'])
        assert result.exit_code == 0
        assert 'KOSPI200' in result.output
        assert 'SPY_ETF' not in result.output
        result = self._run_cli(['portfolio', 'benchmark', '--db', str(self.db_path), '--benchmark', 'SPY_ETF'])
        assert result.exit_code == 0
        assert 'SPY_ETF' in result.output

    def test_cli_benchmark_invalid_option(self):
        result = self._run_cli(['portfolio', 'benchmark', '--db', str(self.db_path), '--benchmark', 'INVALID'])
        assert result.exit_code == 1
        assert '지원하지 않는 벤치마크' in result.output

    def test_cli_benchmark_empty_db(self):
        result = self._run_cli(['portfolio', 'benchmark', '--db', str(self.db_path)])
        assert result.exit_code == 0
        assert '비교할 구간이 없습니다' in result.output
