"""주간·월간 투자 실험 통합 리포트.

판단 평가, 리더보드, 포트폴리오 성과, 시장 벤치마크를 하나의 보고서로 통합한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from invest_agent.benchmark import (
    compare_with_benchmarks,
)
from invest_agent.domain.models import DecisionOutcome, OrderSide, RunStatus
from invest_agent.evaluation import (
    DecisionEvaluation,
    EvaluationStatus,
    evaluate_decision,
)
from invest_agent.performance import (
    analyze_portfolio_performance,
)
from invest_agent.storage.repositories import (
    AgentRunRepository,
    CashFlowRepository,
    DecisionRepository,
    EquitySnapshotRepository,
    OHLCVRepository,
    PortfolioSnapshotRepository,
    ThesisRepository,
)


class ReportPeriod(StrEnum):
    """리포트 주기."""
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


@dataclass(frozen=True)
class PeriodBounds:
    """기간 경계."""
    start: datetime
    end: datetime
    period_type: ReportPeriod
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass(frozen=True)
class ExperimentInfo:
    """실험 기본 정보."""
    period: PeriodBounds
    generated_at: datetime
    evaluation_as_of: datetime | None
    execution_mode: str
    models_used: list[str]
    markets: list[str]
    assets: list[str]


@dataclass(frozen=True)
class ActivitySummary:
    """AI 활동 요약."""
    total_runs: int
    successful_runs: int
    failed_runs: int
    blocked_runs: int
    total_decisions: int
    buy_count: int
    sell_count: int
    no_trade_count: int
    blocked_count: int
    error_count: int
    decisions_by_model: dict[str, int]


@dataclass(frozen=True)
class JudgmentPerformance:
    """AI 판단 성과."""
    hit_rate_1d: Decimal | None
    hit_rate_5d: Decimal | None
    hit_rate_20d: Decimal | None
    hit_rate_1d_denominator: int
    hit_rate_5d_denominator: int
    hit_rate_20d_denominator: int
    neutral_count_1d: int
    neutral_count_5d: int
    neutral_count_20d: int
    completed_count: int
    pending_count: int
    unavailable_count: int
    invalid_count: int
    excluded_count: int
    model_leaderboard: list[dict]
    data_quality_notes: list[str]


@dataclass(frozen=True)
class PortfolioPerformance:
    """포트폴리오 성과."""
    start_equity: Decimal | None
    end_equity: Decimal | None
    external_cash_flow: Decimal
    adjusted_pnl: Decimal | None
    period_return_pct: Decimal | None
    cash_krw: Decimal
    cash_usd: Decimal
    positions_summary: list[dict]
    equity_completeness: bool
    period_return_calculable: bool
    non_calculable_reasons: list[str]


@dataclass(frozen=True)
class MarketBenchmark:
    """시장 벤치마크 비교."""
    kospi200_return_pct: Decimal | None
    spy_return_pct: Decimal | None
    benchmark_currency: str
    price_as_of: str | None
    excess_return_pct: Decimal | None
    comparison_notes: list[str]


@dataclass(frozen=True)
class OperationsQuality:
    """운영 품질 및 해석 참고사항."""
    risk_blocks: list[str]
    market_data_gaps: list[str]
    provider_mismatches: list[str]
    incomplete_equity: list[str]
    pending_evaluations: int
    interpretation_notes: list[str]


@dataclass(frozen=True)
class SummaryReport:
    """통합 리포트."""
    experiment_info: ExperimentInfo
    activity_summary: ActivitySummary
    judgment_performance: JudgmentPerformance
    portfolio_performance: PortfolioPerformance
    market_benchmark: MarketBenchmark
    operations_quality: OperationsQuality


def get_period_bounds(
    period: ReportPeriod,
    start: datetime | None = None,
    end: datetime | None = None,
) -> PeriodBounds:
    """기간 경계 계산."""
    now = datetime.now(UTC)

    if period == ReportPeriod.WEEKLY:
        end_dt = end or now
        start_dt = start or (end_dt - timedelta(days=6))
        label = f"주간 ({start_dt.date().isoformat()} ~ {end_dt.date().isoformat()})"
    elif period == ReportPeriod.MONTHLY:
        end_dt = end or now
        start_dt = start or (end_dt - timedelta(days=29))
        label = f"월간 ({start_dt.date().isoformat()} ~ {end_dt.date().isoformat()})"
    else:
        if not start or not end:
            raise ValueError("Custom 기간은 start와 end가 모두 필요합니다")
        start_dt = start
        end_dt = end
        label = f"사용자지정 ({start_dt.date().isoformat()} ~ {end_dt.date().isoformat()})"

    return PeriodBounds(
        start=start_dt.replace(hour=0, minute=0, second=0, microsecond=0),
        end=end_dt.replace(hour=23, minute=59, second=59, microsecond=999999),
        period_type=period,
        label=label,
    )


def _get_decisions_in_period(
    decision_repo: DecisionRepository,
    thesis_repo: ThesisRepository,
    ohlcv_repo: OHLCVRepository,
    period: PeriodBounds,
    as_of: datetime | None,
) -> list[DecisionEvaluation]:
    """기간 내 의사결정 조회 및 평가.

    DecisionRepository.get_by_date_range를 사용하여 기간 조건을 적용한 직접 조회 수행.
    평가와 리더보드가 동일한 판단 집합을 사용하도록 함.
    """
    decisions = decision_repo.get_by_date_range(period.start, period.end)

    evaluations = []
    for d in decisions:
        eval_result = evaluate_decision(
            decision=d,
            thesis_repo=thesis_repo,
            ohlcv_repo=ohlcv_repo,
            as_of=as_of,
        )
        evaluations.append(eval_result)

    return evaluations


def _build_activity_summary(
    evaluations: list[DecisionEvaluation],
    run_repo: AgentRunRepository,
    period: PeriodBounds,
) -> ActivitySummary:
    """AI 활동 요약 구성."""
    runs = run_repo.get_by_date_range(period.start, period.end)

    total_runs = len(runs)
    successful_runs = sum(1 for r in runs if r.status == RunStatus.COMPLETED)
    failed_runs = sum(1 for r in runs if r.status in (RunStatus.RECOVERY_REQUIRED,))
    blocked_runs = sum(1 for r in runs if r.status == RunStatus.BLOCKED)

    total_decisions = len(evaluations)
    buy_count = sum(1 for e in evaluations if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY)
    sell_count = sum(1 for e in evaluations if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL)
    no_trade_count = sum(1 for e in evaluations if e.outcome == DecisionOutcome.NO_TRADE)
    blocked_count = sum(1 for e in evaluations if e.outcome == DecisionOutcome.BLOCKED)
    error_count = sum(1 for e in evaluations if e.outcome == DecisionOutcome.ERROR)

    decisions_by_model = {}
    for e in evaluations:
        key = f"{e.model_provider}/{e.model_name}" if e.model_provider else e.model_name
        decisions_by_model[key] = decisions_by_model.get(key, 0) + 1

    return ActivitySummary(
        total_runs=total_runs,
        successful_runs=successful_runs,
        failed_runs=failed_runs,
        blocked_runs=blocked_runs,
        total_decisions=total_decisions,
        buy_count=buy_count,
        sell_count=sell_count,
        no_trade_count=no_trade_count,
        blocked_count=blocked_count,
        error_count=error_count,
        decisions_by_model=decisions_by_model,
    )


def _build_judgment_performance(
    evaluations: list[DecisionEvaluation],
    db_path: str,
    period: PeriodBounds,
    as_of: datetime | None,
    ohlcv_repo: OHLCVRepository,
) -> JudgmentPerformance:
    """AI 판단 성과 구성.

    중립(0% 변화)은 HIT/MISS에서 제외하여 별도 집계.
    평가 대기(PENDING)와 불가(UNAVAILABLE/INVALID)는 중립에 포함하지 않음.
    중립은 정상 평가가 완료된(COMPLETED) 0% 가격 변화만 해당.
    리더보드는 보고서와 동일한 기간 필터링된 판단 집합을 사용.
    """
    trade_evals = [e for e in evaluations if e.outcome == DecisionOutcome.TRADE]

    def calc_hit_rate(horizon: str) -> tuple[Decimal | None, int, int]:
        hit_attr = f"horizon_{horizon}"
        hits = sum(1 for e in trade_evals if getattr(e, hit_attr).hit is True)
        misses = sum(1 for e in trade_evals if getattr(e, hit_attr).hit is False)
        # 중립: 정상 평가 완료(COMPLETED)면서 hit이 None인 경우만 (0% 가격 변화)
        neutrals = sum(
            1
            for e in trade_evals
            if getattr(e, hit_attr).hit is None
            and getattr(e, hit_attr).status == EvaluationStatus.COMPLETED
        )
        total = hits + misses
        rate = (Decimal(hits) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01")) if total > 0 else None
        return rate, total, neutrals

    hit_rate_1d, denom_1d, neutral_1d = calc_hit_rate("1d")
    hit_rate_5d, denom_5d, neutral_5d = calc_hit_rate("5d")
    hit_rate_20d, denom_20d, neutral_20d = calc_hit_rate("20d")

    completed = sum(1 for e in evaluations if e.evaluable)
    pending = sum(1 for e in evaluations if not e.evaluable and any(
        getattr(e, f"horizon_{h}").status == EvaluationStatus.PENDING for h in ["1d", "5d", "20d"]
    ))
    unavailable = sum(1 for e in evaluations if not e.evaluable and any(
        getattr(e, f"horizon_{h}").status == EvaluationStatus.UNAVAILABLE for h in ["1d", "5d", "20d"]
    ))
    invalid = sum(1 for e in evaluations if not e.evaluable and any(
        getattr(e, f"horizon_{h}").status == EvaluationStatus.INVALID for h in ["1d", "5d", "20d"]
    ))
    excluded = sum(1 for e in evaluations if e.outcome in (DecisionOutcome.NO_TRADE, DecisionOutcome.BLOCKED, DecisionOutcome.ERROR))

    # 리더보드: 보고서와 동일한 판단 집합(evaluations) 사용
    leaderboard_entries = []

    notes = []
    if pending > 0:
        notes.append(f"평가 대기(PENDING) {pending}건: 종가 확정 시각 이후 평가 필요")
    if unavailable > 0:
        notes.append(f"데이터 없음(UNAVAILABLE) {unavailable}건: OHLCV 데이터 누락")
    if invalid > 0:
        notes.append(f"잘못된 데이터(INVALID) {invalid}건: 기준가격 0 이하 등")

    return JudgmentPerformance(
        hit_rate_1d=hit_rate_1d,
        hit_rate_5d=hit_rate_5d,
        hit_rate_20d=hit_rate_20d,
        hit_rate_1d_denominator=denom_1d,
        hit_rate_5d_denominator=denom_5d,
        hit_rate_20d_denominator=denom_20d,
        neutral_count_1d=neutral_1d,
        neutral_count_5d=neutral_5d,
        neutral_count_20d=neutral_20d,
        completed_count=completed,
        pending_count=pending,
        unavailable_count=unavailable,
        invalid_count=invalid,
        excluded_count=excluded,
        model_leaderboard=leaderboard_entries,
        data_quality_notes=notes,
    )


def _build_portfolio_performance(
    db_path: str,
    period: PeriodBounds,
) -> PortfolioPerformance:
    """포트폴리오 성과 구성 - performance.py의 Modified Dietz 계산 재사용.

    실제 시작/종료 스냅샷, 해당 구간의 외부 현금흐름, 입출금 시점별 가중치,
    KRW/USD 및 환율 근거, 평가 완전성, 원장 완전성을 모두 고려.
    필수 데이터가 없으면 계산 불가로 표시.
    """

    equity_repo = EquitySnapshotRepository(db_path)
    portfolio_snapshot_repo = PortfolioSnapshotRepository(db_path)
    cashflow_repo = CashFlowRepository(db_path)

    snapshots = equity_repo.get_by_date_range(period.start, period.end)
    snapshots.sort(key=lambda s: s.timestamp)

    start_equity = snapshots[0].total_equity if snapshots else None
    end_equity = snapshots[-1].total_equity if snapshots else None

    cashflows = cashflow_repo.get_by_time_range(period.start, period.end, limit=1000)
    deposits = sum(cf.amount for cf in cashflows if cf.flow_type.value == "DEPOSIT")
    withdrawals = sum(cf.amount for cf in cashflows if cf.flow_type.value == "WITHDRAWAL")
    external_cash_flow = deposits - withdrawals

    try:
        perf_intervals = analyze_portfolio_performance(db_path, limit=100)
        target_interval = None
        for interval in perf_intervals:
            if interval.start_snapshot.timestamp >= period.start and interval.end_snapshot.timestamp <= period.end:
                target_interval = interval
                break
    except Exception:
        perf_intervals = []
        target_interval = None

    period_return_pct = None
    adjusted_pnl = None
    period_return_calculable = False
    non_calculable_reasons = []

    if target_interval and target_interval.calculable:
        period_return_pct = target_interval.period_return_pct
        adjusted_pnl = target_interval.adjusted_change
        period_return_calculable = True
    else:
        if not target_interval:
            non_calculable_reasons.append("리포트 기간에 해당하는 스냅샷 구간이 없음 (최소 2개 필요)")
        else:
            non_calculable_reasons.extend(target_interval.non_calculable_reasons)

    equity_completeness = True
    for s in snapshots:
        if not s.equity_complete:
            equity_completeness = False
            break

    # 기간 내 마지막 포트폴리오 스냅샷 사용 (절대 최신이 아닌)
    period_portfolio_snaps = portfolio_snapshot_repo.get_by_date_range(period.start, period.end)
    if period_portfolio_snaps:
        period_portfolio_snaps.sort(key=lambda s: s.timestamp)
        last_portfolio_snap = period_portfolio_snaps[-1]
        cash_krw = last_portfolio_snap.cash_krw
        cash_usd = last_portfolio_snap.cash_usd
    else:
        last_snapshot = snapshots[-1] if snapshots else None
        cash_krw = last_snapshot.cash_balance if last_snapshot else Decimal("0")
        cash_usd = Decimal("0")

    positions = []
    if snapshots and snapshots[-1].positions:
        for asset_id, pos in snapshots[-1].positions.items():
            positions.append({
                "asset_id": asset_id,
                "quantity": pos.get("quantity", "0"),
                "avg_price": pos.get("avg_price", "0"),
                "current_price": pos.get("current_price", "0"),
                "currency": pos.get("currency", "KRW"),
            })

    return PortfolioPerformance(
        start_equity=start_equity,
        end_equity=end_equity,
        external_cash_flow=external_cash_flow,
        adjusted_pnl=adjusted_pnl,
        period_return_pct=period_return_pct,
        cash_krw=cash_krw,
        cash_usd=cash_usd,
        positions_summary=positions,
        equity_completeness=equity_completeness,
        period_return_calculable=period_return_calculable,
        non_calculable_reasons=non_calculable_reasons,
    )


def _build_market_benchmark(
    db_path: str,
    period: PeriodBounds,
    portfolio_return: Decimal | None,
    portfolio_calculable: bool,
) -> MarketBenchmark:
    """시장 벤치마크 비교 구성 - benchmark.py의 compare_with_benchmarks 재사용.

    저장된 OHLCV만 사용, 외부 공급자 호출 없음.
    데이터가 없거나 정확성을 입증할 수 없다면 계산 불가로 표시.
    """
    notes = []
    kospi200_return_pct = None
    spy_return_pct = None
    excess_return_pct = None
    price_as_of = None

    try:
        benchmark_results = compare_with_benchmarks(
            db_path=db_path,
            limit=100,
            benchmarks=["KOSPI200", "SPY_ETF"],
            provider=None,
            max_freshness_days=5,
        )
        for result in benchmark_results:
            if result.portfolio_start >= period.start and result.portfolio_end <= period.end:
                if result.benchmark_name == "KOSPI200":
                    kospi200_return_pct = result.benchmark_return_pct
                    if result.excess_calculable and result.excess_return_pct is not None:
                        excess_return_pct = result.excess_return_pct
                    price_as_of = result.benchmark_end_date
                    if not result.benchmark_calculable:
                        notes.extend(result.non_calculable_reasons)
                elif result.benchmark_name == "SPY_ETF":
                    spy_return_pct = result.benchmark_return_pct
                    if not result.benchmark_calculable:
                        notes.extend(result.non_calculable_reasons)
    except Exception as e:
        notes.append(f"벤치마크 계산 오류: {e}")

    if not kospi200_return_pct and not spy_return_pct:
        notes.append("벤치마크 데이터 없음 또는 계산 불가 (저장된 OHLCV 부족)")

    return MarketBenchmark(
        kospi200_return_pct=kospi200_return_pct,
        spy_return_pct=spy_return_pct,
        benchmark_currency="KRW",
        price_as_of=price_as_of,
        excess_return_pct=excess_return_pct,
        comparison_notes=notes,
    )


def _build_operations_quality(
    evaluations: list[DecisionEvaluation],
    period: PeriodBounds,
) -> OperationsQuality:
    """운영 품질 및 해석 참고사항 구성."""
    risk_blocks = []
    market_data_gaps = []
    provider_mismatches = []
    incomplete_equity = []

    pending = sum(1 for e in evaluations if any(
        getattr(e, f"horizon_{h}").status == EvaluationStatus.PENDING for h in ["1d", "5d", "20d"]
    ))
    unavailable = sum(1 for e in evaluations if any(
        getattr(e, f"horizon_{h}").status == EvaluationStatus.UNAVAILABLE for h in ["1d", "5d", "20d"]
    ))
    invalid = sum(1 for e in evaluations if any(
        getattr(e, f"horizon_{h}").status == EvaluationStatus.INVALID for h in ["1d", "5d", "20d"]
    ))

    if pending > 0:
        market_data_gaps.append(f"평가 대기(PENDING) {pending}건: 종가 확정 시각 이후 평가 필요")
    if unavailable > 0:
        market_data_gaps.append(f"OHLCV 데이터 없음(UNAVAILABLE): {unavailable}건")
    if invalid > 0:
        market_data_gaps.append(f"잘못된 데이터(INVALID): {invalid}건")

    interpretation_notes = [
        "판단 적중률은 HIT+MISS 표본만으로 산출, 중립(0% 변화)은 분모에서 제외",
        "NO_TRADE, BLOCKED, ERROR는 방향 적중률 평가에서 제외",
        "기준가격 0 또는 데이터 없음은 평가 불가로 분류",
        "포트폴리오 성과는 Modified Dietz(시간가중 현금흐름) 방식 사용",
        "벤치마크 비교는 저장된 OHLCV만 사용, 외부 API 호출 없음",
    ]

    return OperationsQuality(
        risk_blocks=risk_blocks,
        market_data_gaps=market_data_gaps,
        provider_mismatches=provider_mismatches,
        incomplete_equity=incomplete_equity,
        pending_evaluations=pending,
        interpretation_notes=interpretation_notes,
    )


def _build_experiment_info(
    period: PeriodBounds,
    evaluation_as_of: datetime | None,
    evaluations: list[DecisionEvaluation],
) -> ExperimentInfo:
    """실험 기본 정보 구성."""
    models = set()
    markets = set()
    assets = set()

    for e in evaluations:
        model_label = f"{e.model_provider}/{e.model_name}" if e.model_provider else e.model_name
        models.add(model_label)
        if e.asset_id.startswith("KRX:"):
            markets.add("KRX")
        elif e.asset_id.startswith("US:"):
            markets.add("US")
        assets.add(e.asset_id)

    return ExperimentInfo(
        period=period,
        generated_at=datetime.now(UTC),
        evaluation_as_of=evaluation_as_of,
        execution_mode="OFFLINE_SIM",
        models_used=sorted(models),
        markets=sorted(markets),
        assets=sorted(assets),
    )


def generate_summary_report(
    db_path: str,
    period: ReportPeriod = ReportPeriod.WEEKLY,
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
) -> SummaryReport:
    """통합 리포트 생성."""
    period_bounds = get_period_bounds(period, start, end)

    decision_repo = DecisionRepository(db_path)
    run_repo = AgentRunRepository(db_path)
    thesis_repo = ThesisRepository(db_path)

    ohlcv_repo = OHLCVRepository(db_path)
    evaluations = _get_decisions_in_period(decision_repo, thesis_repo, ohlcv_repo, period_bounds, as_of)

    experiment_info = _build_experiment_info(period_bounds, as_of, evaluations)
    activity_summary = _build_activity_summary(evaluations, run_repo, period_bounds)
    judgment_performance = _build_judgment_performance(evaluations, db_path, period_bounds, as_of, ohlcv_repo)
    portfolio_performance = _build_portfolio_performance(db_path, period_bounds)
    market_benchmark = _build_market_benchmark(
        db_path, period_bounds, portfolio_performance.period_return_pct, portfolio_performance.period_return_calculable
    )
    operations_quality = _build_operations_quality(evaluations, period_bounds)

    return SummaryReport(
        experiment_info=experiment_info,
        activity_summary=activity_summary,
        judgment_performance=judgment_performance,
        portfolio_performance=portfolio_performance,
        market_benchmark=market_benchmark,
        operations_quality=operations_quality,
    )


def format_summary_report_markdown(report: SummaryReport) -> str:
    """통합 리포트를 Markdown으로 포맷팅."""
    def fmt_rate(val: Decimal | None) -> str:
        if val is None:
            return chr(0x2014)
        return f"{val:.2f}%"

    def fmt_decimal(val: Decimal | None, decimals: int = 0) -> str:
        if val is None:
            return chr(0x2014)
        if decimals == 0:
            return f"{val:,.0f}"
        return f"{val:,.{decimals}f}"

    lines = [
        f"# 투자 실험 통합 리포트 - {report.experiment_info.period.label}",
        "",
        f"**생성 시각:** {report.experiment_info.generated_at.isoformat()}",
        f"**평가 기준:** {report.experiment_info.evaluation_as_of.isoformat() if report.experiment_info.evaluation_as_of else '현재'}",
        f"**실행 모드:** {report.experiment_info.execution_mode}",
        "",
        "## I. 실험 기본 정보",
        "",
        "| 항목 | 값 |",
        "|------|-----|",
        f"| 리포트 기간 | {report.experiment_info.period.label} |",
        f"| 생성 시각 | {report.experiment_info.generated_at.isoformat()} |",
        f"| 평가 기준 시각 | {report.experiment_info.evaluation_as_of.isoformat() if report.experiment_info.evaluation_as_of else '현재'} |",
        f"| 실행 모드 | {report.experiment_info.execution_mode} |",
        f"| 사용 모델 | {', '.join(report.experiment_info.models_used) or '없음'} |",
        f"| 대상 시장 | {', '.join(report.experiment_info.markets) or '없음'} |",
        f"| 대상 종목 | {', '.join(report.experiment_info.assets) or '없음'} |",
        "",
        "## II. AI 활동 요약",
        "",
        "| 지표 | 값 |",
        "|------|-----|",
        f"| 총 실행 횟수 | {report.activity_summary.total_runs} |",
        f"| 성공 (COMPLETED) | {report.activity_summary.successful_runs} |",
        f"| 실패 (ERROR/RECOVERY) | {report.activity_summary.failed_runs} |",
        f"| 차단 (BLOCKED) | {report.activity_summary.blocked_runs} |",
        f"| 전체 판단 건수 | {report.activity_summary.total_decisions} |",
        f"| BUY | {report.activity_summary.buy_count} |",
        f"| SELL | {report.activity_summary.sell_count} |",
        f"| NO_TRADE | {report.activity_summary.no_trade_count} |",
        f"| BLOCKED | {report.activity_summary.blocked_count} |",
        f"| ERROR | {report.activity_summary.error_count} |",
        "",
    ]

    if report.activity_summary.decisions_by_model:
        lines.extend([
            "### 모델별 판단 건수",
            "",
            "| 모델 | 건수 |",
            "|------|-----|",
        ])
        for model, count in report.activity_summary.decisions_by_model.items():
            lines.append(f"| {model} | {count} |")
        lines.append("")

    jp = report.judgment_performance
    lines.extend([
        "## III. AI 판단 성과",
        "",
        "### 방향 적중률",
        "",
        "| 기간 | 적중률 | 유효 표본(HIT+MISS) | 중립(0% 변화) |",
        "|------|--------|---------------------|--------------|",
    ])
    lines.append(f"| 1일(1D) | {fmt_rate(jp.hit_rate_1d)} | {jp.hit_rate_1d_denominator} | {jp.neutral_count_1d} |")
    lines.append(f"| 5일(5D) | {fmt_rate(jp.hit_rate_5d)} | {jp.hit_rate_5d_denominator} | {jp.neutral_count_5d} |")
    lines.append(f"| 20일(20D) | {fmt_rate(jp.hit_rate_20d)} | {jp.hit_rate_20d_denominator} | {jp.neutral_count_20d} |")
    lines.append("")

    lines.extend([
        "### 평가 상태 요약",
        "",
        f"- 평가 완료(HIT/MISS): {jp.completed_count}건",
        f"- 평가 대기(PENDING): {jp.pending_count}건",
        f"- 데이터 없음(UNAVAILABLE): {jp.unavailable_count}건",
        f"- 잘못된 데이터(INVALID): {jp.invalid_count}건",
        f"- 적중률 산출 제외(NO_TRADE/BLOCKED/ERROR): {jp.excluded_count}건",
        "",
    ])

    if jp.model_leaderboard:
        lines.extend([
            "### 모델별 리더보드 (5D 적중률 기준, 최소 10 표본)",
            "",
            "| 순위 | 모델 | 유효표본 | 1D 적중률 | 5D 적중률 | 20D 적중률 |",
            "|------|------|----------|-----------|-----------|------------|",
        ])
        for entry in jp.model_leaderboard[:10]:
            lines.append(
                f"| {entry['rank']} | {entry['model_label']} | "
                f"{entry['valid_sample_count']} | "
                f"{fmt_rate(Decimal(entry['total_hit_rate_1d'])) if entry['total_hit_rate_1d'] else chr(0x2014)} | "
                f"{fmt_rate(Decimal(entry['total_hit_rate_5d'])) if entry['total_hit_rate_5d'] else chr(0x2014)} | "
                f"{fmt_rate(Decimal(entry['total_hit_rate_20d'])) if entry['total_hit_rate_20d'] else chr(0x2014)} |"
            )
        lines.append("")

    if jp.data_quality_notes:
        lines.extend([
            "### 데이터 품질 참고사항",
            "",
        ])
        for note in jp.data_quality_notes:
            lines.append(f"- {note}")
        lines.append("")

    pp = report.portfolio_performance
    lines.extend([
        "## IV. 포트폴리오 성과",
        "",
        "| 항목 | 값 |",
        "|------|-----|",
        f"| 기간 시작 평가액 | {fmt_decimal(pp.start_equity)} KRW |" if pp.start_equity else f"| 기간 시작 평가액 | {chr(0x2014)} |",
        f"| 기간 종료 평가액 | {fmt_decimal(pp.end_equity)} KRW |" if pp.end_equity else f"| 기간 종료 평가액 | {chr(0x2014)} |",
        f"| 순외부현금흐름 | {fmt_decimal(pp.external_cash_flow)} KRW |",
        f"| 입출금 조정 손익 | {fmt_decimal(pp.adjusted_pnl)} KRW |" if pp.adjusted_pnl else f"| 입출금 조정 손익 | {chr(0x2014)} |",
        f"| 기간 수익률 (Modified Dietz) | {fmt_rate(pp.period_return_pct)} |" if pp.period_return_calculable else "| 기간 수익률 | 계산 불가 |",
        f"| 평가 완전성 | {'완전' if pp.equity_completeness else '불완전'} |",
        "",
    ])


    if pp.non_calculable_reasons:
        lines.append("### 수익률 계산 불가 사유")
        lines.append("")
        for reason in pp.non_calculable_reasons:
            lines.append(f"- {reason}")
        lines.append("")

    if pp.positions_summary:
        lines.extend([
            "### 보유 종목 상세",
            "",
            "| 종목 | 수량 | 평균단가 | 현재가 | 통화 |",
            "|------|------|----------|--------|------|",
        ])
        for pos in pp.positions_summary:
            lines.append(f"| {pos['asset_id']} | {pos['quantity']} | {pos['avg_price']} | {pos['current_price']} | {pos['currency']} |")
        lines.append("")

    lines.extend([
        f"| KRW 현금 | {fmt_decimal(pp.cash_krw)} KRW |",
        f"| USD 현금 | {fmt_decimal(pp.cash_usd, 2)} USD |" if pp.cash_usd else f"| USD 현금 | {chr(0x2014)} (데이터 없음) |",
        "",
    ])

    mb = report.market_benchmark
    lines.extend([
        "## V. 시장 벤치마크 비교",
        "",
        f"- KOSPI 200: {fmt_rate(mb.kospi200_return_pct)}",
        f"- SPY ETF: {fmt_rate(mb.spy_return_pct)}",
        f"- 초과수익률: {fmt_rate(mb.excess_return_pct)}",
        f"- 기준 통화: {mb.benchmark_currency}",
        f"- 가격 기준일: {mb.price_as_of or chr(0x2014)}",
        "",
    ])

    for note in mb.comparison_notes:
        lines.append(f"- {note}")
    lines.append("")

    oq = report.operations_quality
    lines.extend([
        "## VI. 운영 품질 및 해석 참고사항",
        "",
    ])

    if oq.market_data_gaps:
        lines.append("### 시장 데이터 공백")
        for gap in oq.market_data_gaps:
            lines.append(f"- {gap}")
        lines.append("")

    if oq.risk_blocks:
        lines.append("### 위험관리 차단")
        for block in oq.risk_blocks:
            lines.append(f"- {block}")
        lines.append("")

    lines.append("### 해석 참고사항")
    for note in oq.interpretation_notes:
        lines.append(f"- {note}")
    lines.append("")

    return "\n".join(lines)








def save_summary_report(
    db_path: str,
    period: ReportPeriod = ReportPeriod.WEEKLY,
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
    output_path: str | None = None,
    overwrite: bool = False,
) -> str:
    """통합 리포트 생성 후 파일로 저장."""
    report = generate_summary_report(db_path, period, start, end, as_of)
    markdown = format_summary_report_markdown(report)

    if output_path is None:
        period_str = period.value
        date_str = datetime.now(UTC).date().isoformat()
        output_path = f"reports/summary_{period_str}_{date_str}.md"

    path = Path(output_path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"파일이 이미 존재합니다: {output_path} (--overwrite 옵션 필요)")

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return str(path)
