"""CLI 진입점."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="invest",
    help="개인용 AI 자율투자 실험 시스템 (OFFLINE_SIM 기본)",
    no_args_is_help=True,
)

# Decisions app
decisions_app = typer.Typer(name="decisions", help="AI 의사결정 평가")
app.add_typer(decisions_app)

@decisions_app.command("evaluate")
def decisions_evaluate(
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="조회할 의사결정 개수 (기본값: 50)", min=1, max=200),
    ] = 50,
    db_path: Annotated[
        str, typer.Option("--db", "-d", help="SQLite DB 경로")
    ] = "data/agent.db",
    asset: Annotated[
        str | None, typer.Option("--asset", "-a", help="특정 종목만 평가 (예: KRX:005930)")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="특정 모델만 평가")
    ] = None,
    horizon: Annotated[
        int | None, typer.Option("--horizon", help="표시할 평가 기간 (1, 5, 20 중 하나, 기본값: 전체)")
    ] = None,
) -> None:
    """AI 의사결정 사후 평가 (방향 적중률, 가격 변화율).

    기록된 BUY/SELL/NO_TRADE 판단과 사후 시장 가격을 비교하여
    방향 적중률과 가격 변화율을 계산합니다.

    예시:
        uv run invest decisions evaluate --db data/agent.db
        uv run invest decisions evaluate --db data/agent.db --limit 100
        uv run invest decisions evaluate --db data/agent.db --asset KRX:005930
        uv run invest decisions evaluate --db data/agent.db --horizon 1
    """
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    try:
        from invest_agent.evaluation import evaluate_decisions

        evaluations, summaries = evaluate_decisions(
            db_path=db_path,
            limit=limit,
            asset=asset,
            model=model,
            horizon=horizon,
        )
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]의사결정 평가 중 오류: {e}[/red]")
        raise typer.Exit(1)

    if not evaluations:
        console.print("[yellow]평가할 의사결정 기록이 없습니다.[/yellow]")
        console.print("[dim]먼저 AI 에이전트를 실행하여 의사결정을 기록하세요.[/dim]")
        return

    console.print("[bold cyan]AI 의사결정 사후 평가[/bold cyan]")
    console.print(f"조회 개수: {len(evaluations)}개 (최신순)")
    if asset:
        console.print(f"종목 필터: {asset}")
    if model:
        console.print(f"모델 필터: {model}")
    if horizon:
        console.print(f"표시 기간: {horizon}거래일")
    console.print()

    # 개별 평가 결과 출력
    table = Table(title="의사결정별 평가 결과")
    table.add_column("판단 시각", style="cyan", justify="center")
    table.add_column("종목", style="green")
    table.add_column("모델", style="blue")
    table.add_column("판단", style="bold")
    table.add_column("기준가", justify="right", style="yellow")
    table.add_column("1D 변화율", justify="right", style="red")
    table.add_column("5D 변화율", justify="right", style="red")
    table.add_column("20D 변화율", justify="right", style="red")
    table.add_column("적중 여부", justify="center", style="magenta")

    for eval_result in evaluations:
        decided_str = eval_result.decided_at.strftime("%Y-%m-%d %H:%M")
        asset_short = eval_result.asset_id
        model_name = (
            f"{eval_result.model_provider}/{eval_result.model_name}"
            if eval_result.model_provider
            else eval_result.model_name or "-"
        )

        if eval_result.outcome.value == "TRADE":
            side_str = eval_result.side.value if eval_result.side else "?"
            decision_str = (
                f"[green]{side_str}[/green]"
                if side_str == "BUY"
                else f"[red]{side_str}[/red]"
            )
        elif eval_result.outcome.value == "NO_TRADE":
            decision_str = "[yellow]NO_TRADE[/yellow]"
        elif eval_result.outcome.value == "BLOCKED":
            decision_str = "[orange1]BLOCKED[/orange1]"
        elif eval_result.outcome.value == "ERROR":
            decision_str = "[red]ERROR[/red]"
        else:
            decision_str = eval_result.outcome.value

        base_price_str = (
            f"{eval_result.base_price:,.2f}" if eval_result.base_price else "-"
        )

        def fmt_return(val):
            if val is None:
                return "-"
            if val >= 0:
                return f"[green]+{val:.2f}%[/green]"
            else:
                return f"[red]{val:.2f}%[/red]"

        r1d = fmt_return(eval_result.horizon_1d_return_pct)
        r5d = fmt_return(eval_result.horizon_5d_return_pct)
        r20d = fmt_return(eval_result.horizon_20d_return_pct)

        hit_str = "-"
        if eval_result.outcome.value == "TRADE":
            if eval_result.horizon_1d_hit is True:
                hit_str = "[green]적중[/green]"
            elif eval_result.horizon_1d_hit is False:
                hit_str = "[red]미적중[/red]"
            else:
                hit_str = "[yellow]대기[/yellow]"
        elif eval_result.outcome.value == "NO_TRADE":
            hit_str = "[dim]관망[/dim]"
        else:
            hit_str = "[dim]제외[/dim]"

        table.add_row(
            decided_str,
            asset_short,
            model_name,
            decision_str,
            base_price_str,
            r1d,
            r5d,
            r20d,
            hit_str,
        )

    console.print(table)
    console.print()

    # 모델별 요약 출력
    if summaries:
        console.print("[bold cyan]모델별 평가 요약[/bold cyan]")
        summary_table = Table(title="모델별 방향 적중률")
        summary_table.add_column("모델", style="cyan")
        summary_table.add_column("총 판단", justify="right")
        summary_table.add_column("BUY", justify="right")
        summary_table.add_column("SELL", justify="right")
        summary_table.add_column("NO_TRADE", justify="right")
        summary_table.add_column("평가 불가", justify="right")
        summary_table.add_column("1D 적중률", justify="right")
        summary_table.add_column("5D 적중률", justify="right")
        summary_table.add_column("20D 적중률", justify="right")
        summary_table.add_column("평균 1D 수익률", justify="right")
        summary_table.add_column("평균 5D 수익률", justify="right")
        summary_table.add_column("평균 20D 수익률", justify="right")

        for s in summaries:
            model_label = (
                f"{s.model_provider}/{s.model_name}"
                if s.model_provider
                else s.model_name
            )

            def fmt_rate(val):
                if val is None:
                    return "-"
                return f"{val:.2f}%"

            def fmt_avg(val):
                if val is None:
                    return "-"
                return f"{val:.4f}%"

            summary_table.add_row(
                model_label,
                str(s.total_decisions),
                str(s.buy_count),
                str(s.sell_count),
                str(s.no_trade_count),
                str(s.unevaluable_count),
                fmt_rate(s.total_hit_rate_1d),
                fmt_rate(s.total_hit_rate_5d),
                fmt_rate(s.total_hit_rate_20d),
                fmt_avg(s.avg_return_1d),
                fmt_avg(s.avg_return_5d),
                fmt_avg(s.avg_return_20d),
            )

        console.print(summary_table)
        console.print()

        # 평가 불가 사유 출력
        all_reasons = set()
        for s in summaries:
            all_reasons.update(s.non_evaluable_reasons)
        if all_reasons:
            console.print("[bold yellow]평가 불가 사유:[/bold yellow]")
            for reason in sorted(all_reasons):
                console.print(f"  - {reason}")

    console.print(
        "[dim]참고: 이는 방향 적중률(가격 방향 예측 정확도)입니다. "
        "실제 매매 수익률(수수료, 세금, 체결가 반영)과 다릅니다.[/dim]"
    )
    console.print(
        "[dim]NO_TRADE, BLOCKED, ERROR는 방향 적중률 분모에서 제외됩니다.[/dim]"
    )
    console.print(
        "[dim]가격 변화율 0은 중립으로 분류되며 적중률 분모에서 제외됩니다.[/dim]"
    )


console = Console()


if __name__ == "__main__":
    app()
