"""시장 벤치마크 비교 모듈.

포트폴리오 성과를 시장 지수(KOSPI 200, S&P 500)와 비교하여
초과수익률을 계산한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from typing import Literal

from invest_agent.market.market_data import OHLCV, Market
from invest_agent.performance import analyze_portfolio_performance
from invest_agent.storage.repositories import OHLCVRepository


@dataclass(slots=True, frozen=True)
class BenchmarkResult:
    """벤치마크 비교 결과."""

    benchmark_name: str
    benchmark_type: Literal["KOSPI200", "SP500"]
    benchmark_currency: str  # "KRW" 또는 "USD"
    index_type: str  # "가격지수" 또는 "총수익지수"

    portfolio_start: datetime
    portfolio_end: datetime
    portfolio_return_pct: Decimal | None
    portfolio_calculable: bool

    benchmark_start_value: Decimal | None
    benchmark_end_value: Decimal | None
    benchmark_start_date: str | None  # 실제 사용된 가격 날짜
    benchmark_end_date: str | None
    benchmark_return_pct: Decimal | None
    benchmark_calculable: bool

    excess_return_pct: Decimal | None  # 초과수익률 (%p)
    excess_calculable: bool

    non_calculable_reasons: list[str]
    data_source: str


BENCHMARK_SYMBOLS = {
    "KOSPI200": {"asset_id": "KRX:252670", "market": Market.KRX, "currency": "KRW", "index_type": "가격지수", "source": "FinanceDataReader (KRX)"},
    "SP500": {"asset_id": "US:SPY", "market": Market.US, "currency": "USD", "index_type": "가격지수 (ETF SPY 기준)", "source": "FinanceDataReader (Yahoo Finance)"},
}


def _get_closest_ohlcv(
    repo: OHLCVRepository,
    asset_id: str,
    target_dt: datetime,
    provider: str | None = None,
    max_days_back: int = 5,
) -> tuple[OHLCV | None, str | None]:
    target_date = target_dt.date().isoformat()
    search_start = (target_dt - timedelta(days=max_days_back)).date().isoformat()
    ohlcv_list = repo.get_range(asset_id, search_start, target_date, provider)
    if not ohlcv_list:
        return None, None
    for ohlcv in ohlcv_list:
        if ohlcv.timestamp.date() <= target_dt.date():
            return ohlcv, ohlcv.timestamp.date().isoformat()
    return None, None

def _validate_ohlcv(ohlcv: OHLCV | None, label: str, reasons: list[str]) -> bool:
    if ohlcv is None:
        reasons.append(f'{label}: 데이터 없음')
        return False
    if not ohlcv.is_valid():
        reasons.append(f'{label}: 데이터 무효 (OHLC 검증 실패)')
        return False
    if ohlcv.close <= 0:
        reasons.append(f'{label}: 종가 0 이하')
        return False
    return True

def calculate_benchmark_return(
    repo: OHLCVRepository,
    benchmark_name: str,
    portfolio_start: datetime,
    portfolio_end: datetime,
    provider: str | None = None,
    max_freshness_days: int = 5,
) -> tuple[Decimal | None, Decimal | None, str | None, str | None, bool, list[str]]:
    if benchmark_name not in BENCHMARK_SYMBOLS:
        return None, None, None, None, False, [f'알 수 없는 벤치마크: {benchmark_name}']
    info = BENCHMARK_SYMBOLS[benchmark_name]
    asset_id = info['asset_id']
    if provider is None:
        providers = repo.get_providers(asset_id)
        if not providers:
            return None, None, None, None, False, [f'{benchmark_name}: 저장된 공급자 없음']
        provider = providers[0]
    reasons = []
    start_ohlcv, start_date = _get_closest_ohlcv(repo, asset_id, portfolio_start, provider, max_freshness_days)
    end_ohlcv, end_date = _get_closest_ohlcv(repo, asset_id, portfolio_end, provider, max_freshness_days)
    if not _validate_ohlcv(start_ohlcv, '시작 기준값', reasons):
        return None, None, None, None, False, reasons
    if not _validate_ohlcv(end_ohlcv, '종료 기준값', reasons):
        return None, None, None, None, False, reasons
    if start_date:
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC)
        if portfolio_start - start_dt > timedelta(days=max_freshness_days):
            reasons.append(f'시작 기준값 데이터가 너무 오래됨 ({(portfolio_start - start_dt).days}일 경과, 허용: {max_freshness_days}일)')
            return None, None, None, None, False, reasons
    if end_date:
        end_dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC)
        if portfolio_end - end_dt > timedelta(days=max_freshness_days):
            reasons.append(f'종료 기준값 데이터가 너무 오래됨 ({(portfolio_end - end_dt).days}일 경과, 허용: {max_freshness_days}일)')
            return None, None, None, None, False, reasons
    start_value = start_ohlcv.close
    end_value = end_ohlcv.close
    if start_value <= 0:
        reasons.append('시작 기준값이 0 이하')
        return None, None, None, None, False, reasons
    ((end_value / start_value - Decimal('1')) * Decimal('100')).quantize(Decimal('0.0001'))
    return start_value, end_value, start_date, end_date, True, []

def compare_with_benchmarks(
    db_path: str,
    limit: int = 30,
    benchmarks: list[str] | None = None,
    provider: str | None = None,
    max_freshness_days: int = 5,
) -> list[BenchmarkResult]:
    if not Path(db_path).exists():
        raise FileNotFoundError(f'DB 파일이 없습니다: {db_path}')
    if benchmarks is None:
        benchmarks = ['KOSPI200', 'SP500']
    portfolio_intervals = analyze_portfolio_performance(db_path, limit)
    if not portfolio_intervals:
        return []
    ohlcv_repo = OHLCVRepository(db_path)
    results = []
    for interval in portfolio_intervals:
        portfolio_start = interval.start_snapshot.timestamp
        portfolio_end = interval.end_snapshot.timestamp
        portfolio_return = interval.period_return_pct
        portfolio_calculable = interval.calculable
        for bench_name in benchmarks:
            info = BENCHMARK_SYMBOLS.get(bench_name, {})
            bench_start_val, bench_end_val, bench_start_date, bench_end_date, bench_calc, bench_reasons = calculate_benchmark_return(
                ohlcv_repo, bench_name, portfolio_start, portfolio_end, provider, max_freshness_days
            )
            excess_return = None
            excess_calculable = False
            excess_reasons = []
            if portfolio_calculable and portfolio_return is not None and bench_calc and bench_start_val is not None and bench_end_val is not None:
                if bench_name == 'KOSPI200':
                    bench_return = ((bench_end_val / bench_start_val - Decimal('1')) * Decimal('100')).quantize(Decimal('0.0001'))
                    excess_return = (portfolio_return - bench_return).quantize(Decimal('0.0001'))
                    excess_calculable = True
                elif bench_name == 'SP500':
                    excess_reasons.append('SP500은 USD 기준이므로 KRW 포트폴리오와 직접 비교 불가 (환율 근거 필요)')
                else:
                    excess_reasons.append('알 수 없는 벤치마크')
            else:
                if not portfolio_calculable:
                    excess_reasons.append('포트폴리오 수익률 계산 불가')
                if not bench_calc:
                    excess_reasons.extend(bench_reasons)
            all_reasons = []
            if not portfolio_calculable:
                all_reasons.extend(interval.non_calculable_reasons)
            if not bench_calc:
                all_reasons.extend(bench_reasons)
            if not excess_calculable:
                all_reasons.extend(excess_reasons)
            result = BenchmarkResult(
                benchmark_name=bench_name,
                benchmark_type=bench_name,
                benchmark_currency=info.get('currency', ''),
                index_type=info.get('index_type', ''),
                portfolio_start=portfolio_start,
                portfolio_end=portfolio_end,
                portfolio_return_pct=portfolio_return,
                portfolio_calculable=portfolio_calculable,
                benchmark_start_value=bench_start_val,
                benchmark_end_value=bench_end_val,
                benchmark_start_date=bench_start_date,
                benchmark_end_date=bench_end_date,
                benchmark_return_pct=((bench_end_val / bench_start_val - Decimal('1')) * Decimal('100')).quantize(Decimal('0.0001')) if bench_calc and bench_start_val and bench_start_val > 0 else None,
                benchmark_calculable=bench_calc,
                excess_return_pct=excess_return,
                excess_calculable=excess_calculable,
                non_calculable_reasons=all_reasons,
                data_source=info.get('source', ''),
            )
            results.append(result)
    return results

def format_benchmark_report(results: list[BenchmarkResult]) -> str:
    if not results:
        return '비교할 구간이 없습니다. (포트폴리오 스냅샷이 2개 미만 또는 벤치마크 데이터 없음)'
    output_lines = []
    def print_line(line: str = ''):
        output_lines.append(line)
    print_line('[bold cyan]포트폴리오 vs 시장 벤치마크 비교[/bold cyan]')
    print_line(f'분석 구간 수: {len(set((r.portfolio_start, r.portfolio_end) for r in results))}개')
    print_line('')
    for (start, end), group in groupby(results, key=lambda r: (r.portfolio_start, r.portfolio_end)):
        interval_results = list(group)
        start_str = start.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end.strftime('%Y-%m-%d %H:%M:%S')
        print_line(f'[bold]구간: {start_str} ~ {end_str}[/bold]')
        portfolio_result = interval_results[0]
        if portfolio_result.portfolio_calculable and portfolio_result.portfolio_return_pct is not None:
            print_line(f'  EUvest Modified Dietz 수익률: [green]{portfolio_result.portfolio_return_pct:+.4f}%[/green]')
        else:
            print_line('  EUvest Modified Dietz 수익률: [yellow]계산 불가[/yellow]')
            for reason in portfolio_result.non_calculable_reasons:
                if not any(r in reason for r in ['벤치마크', 'SP500', 'USD', '환율']):
                    print_line(f'    - {reason}')
        print_line('')
        for result in interval_results:
            print_line(f'  [bold]{result.benchmark_name} ({result.benchmark_currency}, {result.index_type})[/bold]')
            print_line(f'    데이터 출처: {result.data_source}')
            if result.benchmark_calculable:
                print_line(f'    기준값: {result.benchmark_start_value:,.2f} ({result.benchmark_start_date}) -> {result.benchmark_end_value:,.2f} ({result.benchmark_end_date})')
                if result.benchmark_return_pct is not None:
                    print_line(f'    [green]벤치마크 수익률: {result.benchmark_return_pct:+.4f}%[/green]')
                else:
                    print_line('    [yellow]벤치마크 수익률: 계산 불가[/yellow]')
            else:
                print_line('    [yellow]벤치마크 수익률: 계산 불가[/yellow]')
                for reason in result.non_calculable_reasons:
                    print_line(f'      - {reason}')
            if result.excess_calculable and result.excess_return_pct is not None:
                color = 'green' if result.excess_return_pct >= 0 else 'red'
                print_line(f'    [{color}]초과수익률: {result.excess_return_pct:+.4f}%p[/{color}]')
                print_line('    [dim]비교 기준: Modified Dietz (시간가중) vs 벤치마크 단순 보유 수익률[/dim]')
            elif result.benchmark_name == 'SP500':
                print_line('    [yellow]초과수익률: 비교 불가 (통화 불일치: 포트폴리오 KRW vs 벤치마크 USD)[/yellow]')
                print_line(f'    [dim]참고: USD 기준 SP500 수익률 {result.benchmark_return_pct}% (환율 적용 시 KRW 환산 가능)[/dim]')
            else:
                print_line('    [yellow]초과수익률: 비교 불가[/yellow]')
                for reason in result.non_calculable_reasons:
                    if '초과' in reason or '비교' in reason or '통화' in reason:
                        print_line(f'      - {reason}')
            print_line('')
    return '\n'.join(output_lines)
