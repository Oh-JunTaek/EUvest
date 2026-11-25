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

    # 평가 품질 지표
    evaluated_count: int
    total_decisions: int
    evaluation_rate: Decimal  # evaluated_count / total_decisions * 100

    # 세부 내역
    buy_count: int
    sell_count: int
    no_trade_count: int
    blocked_count: int
    error_count: int


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


def build_leaderboard(
    db_path: str,
    limit: int = 50,
    asset: str | None = None,
    horizon: int | None = None,
    as_of: str | None = None,
    provider: str | None = None,
    min_evaluated_decisions: int = 5,
    primary_horizon: int = 20,
    secondary_metric: Literal["hit_rate", "return"] = "hit_rate",
) -> Leaderboard:
    """리더보드 생성."""
    from datetime import UTC, datetime

    evaluations, summaries = evaluate_decisions(
        db_path=db_path,
        limit=limit,
        asset=asset,
        horizon=horizon,
        as_of=datetime.fromisoformat(as_of.replace("Z", "+00:00")) if as_of else None,
        provider=provider,
    )

    entries = []
    excluded = []

    for summary in summaries:
        model_label = (
            f"{summary.model_provider}/{summary.model_name}"
            if summary.model_provider
            else summary.model_name
        )

        if summary.evaluated_count < min_evaluated_decisions:
            excluded.append(
                f"{model_label}: 평가 완료 {summary.evaluated_count}개 (최소 {min_evaluated_decisions}개 필요)"
            )
            continue

        eval_rate = _compute_evaluation_rate(summary.evaluated_count, summary.total_decisions)

        entry = LeaderboardEntry(
            rank=0,
            model_provider=summary.model_provider,
            model_name=summary.model_name,
            model_label=model_label,
            total_hit_rate_1d=summary.total_hit_rate_1d,
            total_hit_rate_5d=summary.total_hit_rate_5d,
            total_hit_rate_20d=summary.total_hit_rate_20d,
            avg_return_1d=summary.avg_return_1d,
            avg_return_5d=summary.avg_return_5d,
            avg_return_20d=summary.avg_return_20d,
            evaluated_count=summary.evaluated_count,
            total_decisions=summary.total_decisions,
            evaluation_rate=eval_rate,
            buy_count=summary.buy_count,
            sell_count=summary.sell_count,
            no_trade_count=summary.no_trade_count,
            blocked_count=summary.blocked_count,
            error_count=summary.error_count,
        )
        entries.append(entry)

    entries.sort(
        key=lambda e: _model_sort_key(e, primary_horizon, secondary_metric),
        reverse=True,
    )

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
                evaluated_count=entry.evaluated_count,
                total_decisions=entry.total_decisions,
                evaluation_rate=entry.evaluation_rate,
                buy_count=entry.buy_count,
                sell_count=entry.sell_count,
                no_trade_count=entry.no_trade_count,
                blocked_count=entry.blocked_count,
                error_count=entry.error_count,
            )
        )

    return Leaderboard(
        entries=ranked_entries,
        generated_at=datetime.now(UTC).isoformat(),
        evaluation_as_of=as_of,
        evaluation_horizon=horizon,
        evaluation_provider=provider,
        min_evaluated_decisions=min_evaluated_decisions,
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
    table.add_column("평가율", justify="right", style="yellow", width=8)
    table.add_column("완료/전체", justify="right", style="dim", width=10)
    table.add_column("1D 적중률", justify="right", style="green", width=10)
    table.add_column("5D 적중률", justify="right", style="green", width=10)
    table.add_column("20D 적중률", justify="right", style="green", width=10)
    table.add_column("1D 평균수익", justify="right", style="magenta", width=12)
    table.add_column("5D 평균수익", justify="right", style="magenta", width=12)
    table.add_column("20D 평균수익", justify="right", style="magenta", width=12)
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

        table.add_row(
            str(entry.rank),
            entry.model_label,
            f"{entry.evaluation_rate:.1f}%",
            f"{entry.evaluated_count}/{entry.total_decisions}",
            fmt_rate(entry.total_hit_rate_1d),
            fmt_rate(entry.total_hit_rate_5d),
            fmt_rate(entry.total_hit_rate_20d),
            fmt_return(entry.avg_return_1d),
            fmt_return(entry.avg_return_5d),
            fmt_return(entry.avg_return_20d),
            str(entry.buy_count),
            str(entry.sell_count),
            str(entry.no_trade_count),
        )

    console.print(table)

    if leaderboard.excluded_models:
        console.print("\n[bold yellow]제외된 모델 (최소 평가 완료 결정 수 미달):[/bold yellow]")
        for reason in leaderboard.excluded_models:
            console.print(f"  - {reason}")

    meta_lines = []
    if leaderboard.evaluation_as_of:
        meta_lines.append(f"평가 기준: {leaderboard.evaluation_as_of}")
    if leaderboard.evaluation_horizon:
        meta_lines.append(f"평가 기간: {leaderboard.evaluation_horizon}거래일")
    if leaderboard.evaluation_provider:
        meta_lines.append(f"공급자: {leaderboard.evaluation_provider}")
    meta_lines.append(f"최소 평가 완료 결정: {leaderboard.min_evaluated_decisions}개")

    if meta_lines:
        console.print(Panel("\n".join(meta_lines), title="평가 설정", border_style="dim"))


# JSON 직렬화를 위한 헬퍼
def leaderboard_to_dict(leaderboard: Leaderboard) -> dict:
    """리더보드를 딕셔너리로 변환 (JSON 직렬화용)."""
    return {
        "generated_at": leaderboard.generated_at,
        "evaluation_as_of": leaderboard.evaluation_as_of,
        "evaluation_horizon": leaderboard.evaluation_horizon,
        "evaluation_provider": leaderboard.evaluation_provider,
        "min_evaluated_decisions": leaderboard.min_evaluated_decisions,
        "excluded_models": leaderboard.excluded_models,
        "entries": [
            {
                "rank": e.rank,
                "model_provider": e.model_provider,
                "model_name": e.model_name,
                "model_label": e.model_label,
                "total_hit_rate_1d": str(e.total_hit_rate_1d) if e.total_hit_rate_1d else None,
                "total_hit_rate_5d": str(e.total_hit_rate_5d) if e.total_hit_rate_5d else None,
                "total_hit_rate_20d": str(e.total_hit_rate_20d) if e.total_hit_rate_20d else None,
                "avg_return_1d": str(e.avg_return_1d) if e.avg_return_1d else None,
                "avg_return_5d": str(e.avg_return_5d) if e.avg_return_5d else None,
                "avg_return_20d": str(e.avg_return_20d) if e.avg_return_20d else None,
                "evaluated_count": e.evaluated_count,
                "total_decisions": e.total_decisions,
                "evaluation_rate": str(e.evaluation_rate),
                "buy_count": e.buy_count,
                "sell_count": e.sell_count,
                "no_trade_count": e.no_trade_count,
                "blocked_count": e.blocked_count,
                "error_count": e.error_count,
            }
            for e in leaderboard.entries
        ],
    }
