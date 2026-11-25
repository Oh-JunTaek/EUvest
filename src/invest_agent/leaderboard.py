"""AI 모델별 성과 리더보드.

모델 평가 결과를 종합하여 순위를 매기고 리더보드를 생성한다.
평가 불가능한 결과는 순위에서 제외하거나 별도 표시한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from invest_agent.evaluation import (
    evaluate_decisions,
)


@dataclass(slots=True, frozen=True)
class LeaderboardEntry:
    """리더보드 항목."""

    rank: int
    model_provider: str
    model_name: str
    model_label: str  # "provider/model_name" 형식

    # 핵심 지표
    total_hit_rate_1d: Decimal | None
    total_hit_rate_5d: Decimal | None
    total_hit_rate_20d: Decimal | None

    avg_return_1d: Decimal | None
    avg_return_5d: Decimal | None
    avg_return_20d: Decimal | None

    # 평가 품질 지표 (선택된 horizon 기준)
    valid_sample_count: int  # HIT + MISS만 (NEUTRAL, EXCLUDED, PENDING, INVALID, UNAVAILABLE 제외)
    total_decisions: int
    evaluation_rate: Decimal  # valid_sample_count / total_decisions * 100

    # 세부 내역
    buy_count: int
    sell_count: int
    no_trade_count: int
    blocked_count: int
    error_count: int

    # Horizon별 적중/미적중/중립 건수
    hit_count_1d: int
    miss_count_1d: int
    neutral_count_1d: int
    hit_count_5d: int
    miss_count_5d: int
    neutral_count_5d: int
    hit_count_20d: int
    miss_count_20d: int
    neutral_count_20d: int

    # Horizon별 평가 대기/불가 건수
    pending_count_1d: int
    unavailable_count_1d: int
    invalid_count_1d: int
    pending_count_5d: int
    unavailable_count_5d: int
    invalid_count_5d: int
    pending_count_20d: int
    unavailable_count_20d: int
    invalid_count_20d: int


@dataclass(slots=True, frozen=True)
class Leaderboard:
    """모델 성과 리더보드."""

    entries: list[LeaderboardEntry]
    generated_at: str  # ISO 8601
    evaluation_as_of: str | None
    evaluation_horizon: int | None
    evaluation_provider: str | None

    # 필터링 정보
    min_evaluated_decisions: int
    excluded_models: list[str]  # 평가 데이터 부족 등으로 제외된 모델


def _compute_evaluation_rate(evaluated: int, total: int) -> Decimal:
    """평가율 계산."""
    if total == 0:
        return Decimal("0")
    return (Decimal(evaluated) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))


def _model_sort_key(
    entry: LeaderboardEntry,
    primary_horizon: int = 20,
    secondary_metric: Literal["hit_rate", "return"] = "hit_rate",
) -> tuple:
    """모델 정렬 키 생성.

    Args:
        entry: 리더보드 항목
        primary_horizon: 주 정렬 기준 기간 (1, 5, 20)
        secondary_metric: 보조 정렬 지표 ("hit_rate" 또는 "return")

    Returns:
        정렬용 튜플 (높을수록 상위)
    """
    # 주 정렬: 지정된 기간의 적중률 (None은 -1로 처리하여 하위 정렬)
    if primary_horizon == 1:
        primary_hit = entry.total_hit_rate_1d or Decimal("-1")
    elif primary_horizon == 5:
        primary_hit = entry.total_hit_rate_5d or Decimal("-1")
    else:
        primary_hit = entry.total_hit_rate_20d or Decimal("-1")

    # 보조 정렬: 적중률 또는 수익률
    if secondary_metric == "hit_rate":
        hit_rates = [
            entry.total_hit_rate_1d,
            entry.total_hit_rate_5d,
            entry.total_hit_rate_20d,
        ]
        valid_hits = [h for h in hit_rates if h is not None]
        secondary = sum(valid_hits) / len(valid_hits) if valid_hits else Decimal("-1")
    else:
        returns = [
            entry.avg_return_1d,
            entry.avg_return_5d,
            entry.avg_return_20d,
        ]
        valid_returns = [r for r in returns if r is not None]
        secondary = sum(valid_returns) / len(valid_returns) if valid_returns else Decimal("-1")

    eval_rate = entry.evaluation_rate

    return (primary_hit, secondary, eval_rate)


def _get_horizon_hit_rate(entry: LeaderboardEntry, horizon: int) -> Decimal | None:
    """지정된 horizon의 적중률 반환."""
    if horizon == 1:
        return entry.total_hit_rate_1d
    elif horizon == 5:
        return entry.total_hit_rate_5d
    else:
        return entry.total_hit_rate_20d


def _get_horizon_valid_samples(entry: LeaderboardEntry, horizon: int) -> int:
    """지정된 horizon의 유효 표본 수(HIT + MISS) 반환."""
    if horizon == 1:
        return entry.hit_count_1d + entry.miss_count_1d
    elif horizon == 5:
        return entry.hit_count_5d + entry.miss_count_5d
    else:
        return entry.hit_count_20d + entry.miss_count_20d


def _calc_hit_rate(hit: int, miss: int) -> Decimal | None:
    """적중률 계산 (HIT + MISS만 분모)."""
    total = hit + miss
    if total == 0:
        return None
    return (Decimal(hit) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))


def _calc_avg_return(returns: list) -> Decimal | None:
    """평균 수익률 계산."""
    if not returns:
        return None
    return (sum(returns) / len(returns)).quantize(Decimal("0.0001"))


def _process_horizon_stats(
    evals: list,
    entries: list,
    excluded: list,
    model_label: str,
    model_name: str,
    provider_name: str,
    total: int,
    buy_count: int,
    sell_count: int,
    no_trade_count: int,
    blocked_count: int,
    error_count: int,
    min_valid_samples: int,
    primary_horizon: int,
) -> None:
    """Horizon별 통계 처리 및 LeaderboardEntry 생성."""
    # Horizon별 통계 계산
    hit_1d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_1d.hit is True]
    miss_1d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_1d.hit is False]
    neutral_1d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_1d.hit is None]
    pending_1d = [e for e in evals if e.horizon_1d.status.value == "PENDING"]
    unavailable_1d = [e for e in evals if e.horizon_1d.status.value == "UNAVAILABLE"]
    invalid_1d = [e for e in evals if e.horizon_1d.status.value == "INVALID"]

    hit_5d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_5d.hit is True]
    miss_5d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_5d.hit is False]
    neutral_5d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_5d.hit is None]
    pending_5d = [e for e in evals if e.horizon_5d.status.value == "PENDING"]
    unavailable_5d = [e for e in evals if e.horizon_5d.status.value == "UNAVAILABLE"]
    invalid_5d = [e for e in evals if e.horizon_5d.status.value == "INVALID"]

    hit_20d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_20d.hit is True]
    miss_20d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_20d.hit is False]
    neutral_20d = [e for e in evals if e.outcome.value == "TRADE" and e.horizon_20d.hit is None]
    pending_20d = [e for e in evals if e.horizon_20d.status.value == "PENDING"]
    unavailable_20d = [e for e in evals if e.horizon_20d.status.value == "UNAVAILABLE"]
    invalid_20d = [e for e in evals if e.horizon_20d.status.value == "INVALID"]

    hit_count_1d = len(hit_1d)
    miss_count_1d = len(miss_1d)
    neutral_count_1d = len(neutral_1d)
    hit_count_5d = len(hit_5d)
    miss_count_5d = len(miss_5d)
    neutral_count_5d = len(neutral_5d)
    hit_count_20d = len(hit_20d)
    miss_count_20d = len(miss_20d)
    neutral_count_20d = len(neutral_20d)

    pending_count_1d = len(pending_1d)
    unavailable_count_1d = len(unavailable_1d)
    invalid_count_1d = len(invalid_1d)
    pending_count_5d = len(pending_5d)
    unavailable_count_5d = len(unavailable_5d)
    invalid_count_5d = len(invalid_5d)
    pending_count_20d = len(pending_20d)
    unavailable_count_20d = len(unavailable_20d)
    invalid_count_20d = len(invalid_20d)

    # 적중률 계산
    total_hit_rate_1d = _calc_hit_rate(hit_count_1d, miss_count_1d)
    total_hit_rate_5d = _calc_hit_rate(hit_count_5d, miss_count_5d)
    total_hit_rate_20d = _calc_hit_rate(hit_count_20d, miss_count_20d)

    # 평균 수익률 계산
    returns_1d = [e.horizon_1d.return_pct for e in evals if e.horizon_1d.return_pct is not None]
    returns_5d = [e.horizon_5d.return_pct for e in evals if e.horizon_5d.return_pct is not None]
    returns_20d = [e.horizon_20d.return_pct for e in evals if e.horizon_20d.return_pct is not None]

    avg_return_1d = _calc_avg_return(returns_1d)
    avg_return_5d = _calc_avg_return(returns_5d)
    avg_return_20d = _calc_avg_return(returns_20d)

    # 선택된 horizon의 유효 표본 수로 자격 판단
    valid_samples_1d = hit_count_1d + miss_count_1d
    valid_samples_5d = hit_count_5d + miss_count_5d
    valid_samples_20d = hit_count_20d + miss_count_20d

    if primary_horizon == 1:
        valid_samples = valid_samples_1d
    elif primary_horizon == 5:
        valid_samples = valid_samples_5d
    else:
        valid_samples = valid_samples_20d

    if valid_samples < min_valid_samples:
        excluded.append(
            f"{model_label}: 유효 표본 {valid_samples}개 (최소 {min_valid_samples}개 필요, {primary_horizon}D 기준)"
        )
        return

    eval_rate = _compute_evaluation_rate(valid_samples, total)

    entry = LeaderboardEntry(
        rank=0,
        model_provider=provider_name,
        model_name=model_name,
        model_label=model_label,
        total_hit_rate_1d=total_hit_rate_1d,
        total_hit_rate_5d=total_hit_rate_5d,
        total_hit_rate_20d=total_hit_rate_20d,
        avg_return_1d=avg_return_1d,
        avg_return_5d=avg_return_5d,
        avg_return_20d=avg_return_20d,
        valid_sample_count=valid_samples,
        total_decisions=total,
        evaluation_rate=eval_rate,
        buy_count=buy_count,
        sell_count=sell_count,
        no_trade_count=no_trade_count,
        blocked_count=blocked_count,
        error_count=error_count,
        hit_count_1d=hit_count_1d,
        miss_count_1d=miss_count_1d,
        neutral_count_1d=neutral_count_1d,
        hit_count_5d=hit_count_5d,
        miss_count_5d=miss_count_5d,
        neutral_count_5d=neutral_count_5d,
        hit_count_20d=hit_count_20d,
        miss_count_20d=miss_count_20d,
        neutral_count_20d=neutral_count_20d,
        pending_count_1d=pending_count_1d,
        unavailable_count_1d=unavailable_count_1d,
        invalid_count_1d=invalid_count_1d,
        pending_count_5d=pending_count_5d,
        unavailable_count_5d=unavailable_count_5d,
        invalid_count_5d=invalid_count_5d,
        pending_count_20d=pending_count_20d,
        unavailable_count_20d=unavailable_count_20d,
        invalid_count_20d=invalid_count_20d,
    )
    entries.append(entry)


def _create_ranked_entries(entries: list) -> list:
    """순위가 부여된 entries 생성."""
    ranked_entries = []
    for i, entry in enumerate(entries):
        ranked_entries.append(
            LeaderboardEntry(
                rank=i + 1,
                model_provider=entry.model_provider,
                model_name=entry.model_name,
                model_label=entry.model_label,
                total_hit_rate_1d=entry.total_hit_rate_1d,
                total_hit_rate_5d=entry.total_hit_rate_5d,
                total_hit_rate_20d=entry.total_hit_rate_20d,
                avg_return_1d=entry.avg_return_1d,
                avg_return_5d=entry.avg_return_5d,
                avg_return_20d=entry.avg_return_20d,
                valid_sample_count=entry.valid_sample_count,
                total_decisions=entry.total_decisions,
                evaluation_rate=entry.evaluation_rate,
                buy_count=entry.buy_count,
                sell_count=entry.sell_count,
                no_trade_count=entry.no_trade_count,
                blocked_count=entry.blocked_count,
                error_count=entry.error_count,
                hit_count_1d=entry.hit_count_1d,
                miss_count_1d=entry.miss_count_1d,
                neutral_count_1d=entry.neutral_count_1d,
                hit_count_5d=entry.hit_count_5d,
                miss_count_5d=entry.miss_count_5d,
                neutral_count_5d=entry.neutral_count_5d,
                hit_count_20d=entry.hit_count_20d,
                miss_count_20d=entry.miss_count_20d,
                neutral_count_20d=entry.neutral_count_20d,
                pending_count_1d=entry.pending_count_1d,
                unavailable_count_1d=entry.unavailable_count_1d,
                invalid_count_1d=entry.invalid_count_1d,
                pending_count_5d=entry.pending_count_5d,
                unavailable_count_5d=entry.unavailable_count_5d,
                invalid_count_5d=entry.invalid_count_5d,
                pending_count_20d=entry.pending_count_20d,
                unavailable_count_20d=entry.unavailable_count_20d,
                invalid_count_20d=entry.invalid_count_20d,
            )
        )
    return ranked_entries


def build_leaderboard(
    db_path: str,
    limit: int = 50,
    asset: str | None = None,
    horizon: int | None = None,
    as_of: str | None = None,
    provider: str | None = None,
    min_valid_samples: int = 10,
    primary_horizon: int = 5,
    secondary_metric: Literal["hit_rate", "return"] = "hit_rate",
) -> Leaderboard:
    """리더보드 생성.

    Args:
        min_valid_samples: 선택된 horizon의 유효 표본 수(HIT+MISS) 최소값
        primary_horizon: 주 정렬 기준 기간 (기본값: 5일)
    """
    from collections import defaultdict
    from datetime import UTC, datetime

    # horizon이 지정되지 않으면 1,5,20 모두 평가
    eval_horizon = horizon if horizon in (1, 5, 20) else None

    evaluations, _ = evaluate_decisions(
        db_path=db_path,
        limit=limit,
        asset=asset,
        horizon=eval_horizon,
        as_of=datetime.fromisoformat(as_of.replace("Z", "+00:00")) if as_of else None,
        provider=provider,
    )

    entries = []
    excluded = []

    # 모델별 evaluations 그룹화
    model_evals: dict[tuple[str, str], list] = defaultdict(list)
    for eval_result in evaluations:
        key = (eval_result.model_provider, eval_result.model_name)
        model_evals[key].append(eval_result)

    for (provider_name, model_name), evals in model_evals.items():
        model_label = (
            f"{provider_name}/{model_name}"
            if provider_name
            else model_name
        )

        total = len(evals)
        buy_count = sum(1 for e in evals if e.outcome.value == "TRADE" and e.side and e.side.value == "BUY")
        sell_count = sum(1 for e in evals if e.outcome.value == "TRADE" and e.side and e.side.value == "SELL")
        no_trade_count = sum(1 for e in evals if e.outcome.value == "NO_TRADE")
        blocked_count = sum(1 for e in evals if e.outcome.value == "BLOCKED")
        error_count = sum(1 for e in evals if e.outcome.value == "ERROR")

        _process_horizon_stats(evals, entries, excluded, model_label, model_name, provider_name,
                               total, buy_count, sell_count, no_trade_count, blocked_count, error_count,
                               min_valid_samples, primary_horizon)

    entries.sort(
        key=lambda e: _model_sort_key(e, primary_horizon, secondary_metric),
        reverse=True,
    )

    ranked_entries = _create_ranked_entries(entries)

    return Leaderboard(
        entries=ranked_entries,
        generated_at=datetime.now(UTC).isoformat(),
        evaluation_as_of=as_of,
        evaluation_horizon=eval_horizon,
        evaluation_provider=provider,
        min_evaluated_decisions=min_valid_samples,
        excluded_models=excluded,
    )


def print_leaderboard(leaderboard: Leaderboard) -> None:
    """리더보드를 콘솔에 출력."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    if not leaderboard.entries:
        console.print("[yellow]리더보드에 표시할 모델이 없습니다.[/yellow]")
        if leaderboard.excluded_models:
            console.print("\n[bold yellow]제외된 모델:[/bold yellow]")
            for reason in leaderboard.excluded_models:
                console.print(f"  - {reason}")
        return

    table = Table(title="AI 모델 성과 리더보드", show_lines=True)
    table.add_column("순위", justify="center", style="bold cyan", width=5)
    table.add_column("모델", style="cyan", width=30)
    table.add_column("유효표본", justify="right", style="yellow", width=8)
    table.add_column("전체판단", justify="right", style="dim", width=8)
    table.add_column("1D 적중률", justify="right", style="green", width=10)
    table.add_column("5D 적중률", justify="right", style="green", width=10)
    table.add_column("20D 적중률", justify="right", style="green", width=10)
    table.add_column("1D 평균수익", justify="right", style="magenta", width=12)
    table.add_column("5D 평균수익", justify="right", style="magenta", width=12)
    table.add_column("20D 평균수익", justify="right", style="magenta", width=12)
    table.add_column("1D 적/미/중", justify="right", style="dim", width=12)
    table.add_column("5D 적/미/중", justify="right", style="dim", width=12)
    table.add_column("20D 적/미/중", justify="right", style="dim", width=12)
    table.add_column("대기/불가", justify="right", style="dim", width=10)
    table.add_column("BUY", justify="right", width=5)
    table.add_column("SELL", justify="right", width=5)
    table.add_column("NO_TRADE", justify="right", width=8)

    for entry in leaderboard.entries:
        def fmt_rate(val: Decimal | None) -> str:
            if val is None:
                return "—"
            return f"{val:.2f}%"

        def fmt_return(val: Decimal | None) -> str:
            if val is None:
                return "—"
            if val >= 0:
                return f"[green]+{val:.4f}%[/green]"
            return f"[red]{val:.4f}%[/red]"

        def fmt_hmn(hit: int, miss: int, neutral: int) -> str:
            return f"{hit}/{miss}/{neutral}"

        def fmt_pui(pending: int, unavailable: int, invalid: int) -> str:
            total = pending + unavailable + invalid
            return str(total) if total > 0 else "—"

        # 유효 표본 수 / 전체 판단
        sample_total = f"{entry.valid_sample_count}/{entry.total_decisions}"

        table.add_row(
            str(entry.rank),
            entry.model_label,
            f"{entry.evaluation_rate:.1f}%",
            sample_total,
            fmt_rate(entry.total_hit_rate_1d),
            fmt_rate(entry.total_hit_rate_5d),
            fmt_rate(entry.total_hit_rate_20d),
            fmt_return(entry.avg_return_1d),
            fmt_return(entry.avg_return_5d),
            fmt_return(entry.avg_return_20d),
            fmt_hmn(entry.hit_count_1d, entry.miss_count_1d, entry.neutral_count_1d),
            fmt_hmn(entry.hit_count_5d, entry.miss_count_5d, entry.neutral_count_5d),
            fmt_hmn(entry.hit_count_20d, entry.miss_count_20d, entry.neutral_count_20d),
            fmt_pui(
                entry.pending_count_1d + entry.pending_count_5d + entry.pending_count_20d,
                entry.unavailable_count_1d + entry.unavailable_count_5d + entry.unavailable_count_20d,
                entry.invalid_count_1d + entry.invalid_count_5d + entry.invalid_count_20d,
            ),
            str(entry.buy_count),
            str(entry.sell_count),
            str(entry.no_trade_count),
        )

    console.print(table)

    if leaderboard.excluded_models:
        console.print("\n[bold yellow]제외된 모델 (최소 유효 표본 수 미달):[/bold yellow]")
        for reason in leaderboard.excluded_models:
            console.print(f"  - {reason}")

    meta_lines = []
    if leaderboard.evaluation_as_of:
        meta_lines.append(f"평가 기준: {leaderboard.evaluation_as_of}")
    if leaderboard.evaluation_horizon:
        meta_lines.append(f"평가 기간: {leaderboard.evaluation_horizon}거래일")
    if leaderboard.evaluation_provider:
        meta_lines.append(f"공급자: {leaderboard.evaluation_provider}")
    meta_lines.append(f"최소 유효 표본: {leaderboard.min_evaluated_decisions}개 (HIT+MISS)")

    if meta_lines:
        console.print(Panel("\n".join(meta_lines), title="평가 설정", border_style="dim"))


# JSON 직렬화를 위한 헬퍼
def leaderboard_to_dict(leaderboard: Leaderboard) -> dict:
    """리더보드를 딕셔너리로 변환 (JSON 직렬화용).

    Decimal 값은 문자열로 변환하여 정밀도 보존.
    0 값은 "0" 문자열로, None은 null로 직렬화.
    """
    def dec_str(val: Decimal | None) -> str | None:
        """Decimal을 문자열로 변환 (0도 '0'으로 보존)."""
        if val is None:
            return None
        return str(val)

    return {
        "generated_at": leaderboard.generated_at,
        "evaluation_as_of": leaderboard.evaluation_as_of,
        "evaluation_horizon": leaderboard.evaluation_horizon,
        "evaluation_provider": leaderboard.evaluation_provider,
        "min_valid_samples": leaderboard.min_evaluated_decisions,
        "excluded_models": leaderboard.excluded_models,
        "entries": [
            {
                "rank": e.rank,
                "model_provider": e.model_provider,
                "model_name": e.model_name,
                "model_label": e.model_label,
                "total_hit_rate_1d": dec_str(e.total_hit_rate_1d),
                "total_hit_rate_5d": dec_str(e.total_hit_rate_5d),
                "total_hit_rate_20d": dec_str(e.total_hit_rate_20d),
                "avg_return_1d": dec_str(e.avg_return_1d),
                "avg_return_5d": dec_str(e.avg_return_5d),
                "avg_return_20d": dec_str(e.avg_return_20d),
                "valid_sample_count": e.valid_sample_count,
                "total_decisions": e.total_decisions,
                "evaluation_rate": dec_str(e.evaluation_rate),
                "buy_count": e.buy_count,
                "sell_count": e.sell_count,
                "no_trade_count": e.no_trade_count,
                "blocked_count": e.blocked_count,
                "error_count": e.error_count,
                "hit_count_1d": e.hit_count_1d,
                "miss_count_1d": e.miss_count_1d,
                "neutral_count_1d": e.neutral_count_1d,
                "hit_count_5d": e.hit_count_5d,
                "miss_count_5d": e.miss_count_5d,
                "neutral_count_5d": e.neutral_count_5d,
                "hit_count_20d": e.hit_count_20d,
                "miss_count_20d": e.miss_count_20d,
                "neutral_count_20d": e.neutral_count_20d,
                "pending_count_1d": e.pending_count_1d,
                "unavailable_count_1d": e.unavailable_count_1d,
                "invalid_count_1d": e.invalid_count_1d,
                "pending_count_5d": e.pending_count_5d,
                "unavailable_count_5d": e.unavailable_count_5d,
                "invalid_count_5d": e.invalid_count_5d,
                "pending_count_20d": e.pending_count_20d,
                "unavailable_count_20d": e.unavailable_count_20d,
                "invalid_count_20d": e.invalid_count_20d,
            }
            for e in leaderboard.entries
        ],
    }
