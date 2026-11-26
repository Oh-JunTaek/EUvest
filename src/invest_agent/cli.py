"""CLI 진입점 - Typer 기반."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
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

# ---------------------------------------------------------------------------
# Helper functions (from old CLI)
# ---------------------------------------------------------------------------

def _get_status_style(status: str) -> str:
    """상태별 스타일 반환."""
    if status == "COMPLETED":
        return "green"
    elif status in ("BLOCKED", "SKIPPED_ALREADY_RUNNING"):
        return "yellow"
    elif status in ("RECOVERY_REQUIRED", "ERROR"):
        return "red"
    return "blue"

def _parse_asset_id(asset_id: str) -> tuple[str, str]:
    """자산 ID에서 시장 판별."""
    asset_id = asset_id.strip().upper()
    if asset_id.startswith("KRX:"):
        return asset_id, "KRX"
    elif asset_id.startswith("US:"):
        return asset_id, "US"
    else:
        raise ValueError(
            f"지원하지 않는 자산 ID 형식: {asset_id}. "
            f"KRX:종목코드 또는 US:심볼 형식으로 입력하세요."
        )

def _validate_date(date_str: str) -> str:
    """날짜 형식 검증 (YYYY-MM-DD)."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise ValueError(f"잘못된 날짜 형식: {date_str}. YYYY-MM-DD 형식으로 입력하세요.")

# ---------------------------------------------------------------------------
# Decisions app (NEW - from P1-10B-22)
# ---------------------------------------------------------------------------
decisions_app = typer.Typer(name="decisions", help="AI 의사결정 평가")
app.add_typer(decisions_app)

# Leaderboard app (NEW - from P1-10B-23)
# ---------------------------------------------------------------------------
leaderboard_app = typer.Typer(name="leaderboard", help="AI 모델 성과 리더보드")
app.add_typer(leaderboard_app)

# Report app (NEW - from P1-10B-24)
# ---------------------------------------------------------------------------
report_app = typer.Typer(name="report", help="투자 실험 통합 리포트")
app.add_typer(report_app)

# ---------------------------------------------------------------------------
# Decisions app (NEW - from P1-10B-22)
# ---------------------------------------------------------------------------
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
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="평가 기준 시점 (ISO 8601, 기본값: 현재 UTC)")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", "-p", help="OHLCV 공급자 지정 (기본값: 자동)")
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

        as_of_dt = None
        if as_of:
            as_of_dt = datetime.fromisoformat(as_of.replace('Z', '+00:00'))

        evaluations, summaries = evaluate_decisions(
            db_path=db_path,
            limit=limit,
            asset=asset,
            model=model,
            horizon=horizon,
            as_of=as_of_dt,
            provider=provider,
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
    if as_of:
        console.print(f"평가 기준: {as_of}")
    if provider:
        console.print(f"공급자 필터: {provider}")
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

        # Use new HorizonEvaluation structure
        h1 = eval_result.horizon_1d
        h5 = eval_result.horizon_5d
        h20 = eval_result.horizon_20d

        r1d = fmt_return(h1.return_pct)
        r5d = fmt_return(h5.return_pct)
        r20d = fmt_return(h20.return_pct)

        hit_str = "-"
        if eval_result.outcome.value == "TRADE":
            if h1.hit is True:
                hit_str = "[green]적중[/green]"
            elif h1.hit is False:
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


# Leaderboard commands
@leaderboard_app.command("show")
def leaderboard_show(
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
    horizon: Annotated[
        int | None, typer.Option("--horizon", help="평가 기간 필터 (1, 5, 20 중 하나, 기본값: 전체)")
    ] = None,
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="평가 기준 시점 (ISO 8601, 기본값: 현재 UTC)")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", "-p", help="OHLCV 공급자 지정 (기본값: 자동)")
    ] = None,
    min_evaluated: Annotated[
        int, typer.Option("--min-evaluated", help="리더보드 포함 최소 유효 표본 수(HIT+MISS, 기본값: 5)", min=1)
    ] = 5,
    sort_by: Annotated[
        str, typer.Option("--sort-by", help="정렬 기준: hit_rate (적중률) 또는 return (수익률)", case_sensitive=False)
    ] = "hit_rate",
    primary_horizon: Annotated[
        int, typer.Option("--primary-horizon", help="주 정렬 기준 기간 (1, 5, 20, 기본값: 20)", min=1, max=20)
    ] = 20,
    json_output: Annotated[
        bool, typer.Option("--json", "-j", help="JSON 형식으로 출력")
    ] = False,
) -> None:
    """AI 모델 성과 리더보드 표시.

    평가된 모델들을 적중률과 수익률 기준으로 순위 매겨 표시합니다.

    예시:
        uv run invest leaderboard show --db data/agent.db
        uv run invest leaderboard show --db data/agent.db --min-evaluated 10
        uv run invest leaderboard show --db data/agent.db --sort-by return
        uv run invest leaderboard show --db data/agent.db --primary-horizon 5
        uv run invest leaderboard show --db data/agent.db --json
    """
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    try:
        from invest_agent.leaderboard import (
            build_leaderboard,
            leaderboard_to_dict,
            print_leaderboard,
        )

        if sort_by.lower() not in ("hit_rate", "return"):
            console.print(f"[red]잘못된 정렬 기준: {sort_by}. 'hit_rate' 또는 'return'을 사용하세요.[/red]")
            raise typer.Exit(1)

        if primary_horizon not in (1, 5, 20):
            console.print(f"[red]잘못된 평가 기간: {primary_horizon}. 1, 5, 20 중 하나여야 합니다.[/red]")
            raise typer.Exit(1)

        leaderboard = build_leaderboard(
            db_path=db_path,
            limit=limit,
            asset=asset,
            horizon=horizon,
            as_of=as_of,
            provider=provider,
            min_valid_samples=min_evaluated,
            primary_horizon=primary_horizon,
            secondary_metric=sort_by.lower(),
        )

        if json_output:
            import json
            console.print_json(json.dumps(leaderboard_to_dict(leaderboard), ensure_ascii=False, indent=2))
        else:
            print_leaderboard(leaderboard)

    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]리더보드 생성 중 오류: {e}[/red]")
        raise typer.Exit(1)


# Report commands
@report_app.command("summary")
def report_summary(
    db_path: Annotated[
        str, typer.Option("--db", "-d", help="SQLite DB 경로")
    ] = "data/agent.db",
    period: Annotated[
        str, typer.Option("--period", "-p", help="리포트 기간 (weekly, monthly, custom)", case_sensitive=False)
    ] = "weekly",
    start: Annotated[
        str | None, typer.Option("--start", help="시작일 (YYYY-MM-DD, custom일 때 필수)")
    ] = None,
    end: Annotated[
        str | None, typer.Option("--end", help="종료일 (YYYY-MM-DD, custom일 때 필수)")
    ] = None,
    as_of: Annotated[
        str | None, typer.Option("--as-of", help="평가 기준 시점 (ISO 8601, 기본값: 현재 UTC)")
    ] = None,
    output: Annotated[
        str | None, typer.Option("--output", "-o", help="출력 파일 경로 (기본값: reports/summary_<period>_<date>.md)")
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="기존 파일 덮어쓰기")
    ] = False,
) -> None:
    """투자 실험 통합 리포트 생성 (주간/월간/사용자 지정).

    주간/월간/사용자 지정 기간의 투자 실험 결과를 종합 리포트로 생성합니다.

    예시:
        uv run invest report summary --db data/agent.db --period weekly
        uv run invest report summary --db data/agent.db --period monthly
        uv run invest report summary --db data/agent.db --period custom --start 2025-01-01 --end 2025-01-31
        uv run invest report summary --db data/agent.db --period weekly --output reports/weekly.md
    """
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    try:
        from invest_agent.reporting.summary import (
            ReportPeriod,
            format_summary_report_markdown,
            generate_summary_report,
        )

        period_enum = ReportPeriod(period.lower())
        start_dt = datetime.fromisoformat(start) if start else None
        end_dt = datetime.fromisoformat(end) if end else None
        as_of_dt = datetime.fromisoformat(as_of.replace('Z', '+00:00')) if as_of else None

        report = generate_summary_report(
            db_path=db_path,
            period=period_enum,
            start=start_dt,
            end=end_dt,
            as_of=as_of_dt,
        )

        markdown = format_summary_report_markdown(report)

        if output is None:
            period_str = period_enum.value
            date_str = datetime.now(UTC).date().isoformat()
            output = f"reports/summary_{period_str}_{date_str}.md"

        output_path = Path(output)
        if output_path.exists() and not overwrite:
            console.print(f"[red]파일이 이미 존재합니다: {output} (--overwrite 옵션 필요)[/red]")
            raise typer.Exit(1)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")

        console.print(f"[green]리포트 생성 완료: {output}[/green]")

    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]리포트 생성 중 오류: {e}[/red]")
        raise typer.Exit(1)


@report_app.command("daily")
def report_daily(
    db_path: Annotated[
        str, typer.Option("--db", "-d", help="SQLite DB 경로")
    ] = "data/agent.db",
    date: Annotated[
        str | None, typer.Option("--date", help="기준일 (YYYY-MM-DD, 기본값: 오늘)")
    ] = None,
    output: Annotated[
        str | None, typer.Option("--output", "-o", help="출력 파일 경로 (미지정 시 콘솔 출력)")
    ] = None,
) -> None:
    """일일 투자 실험 리포트 생성."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    if date is None:
        target_date = datetime.now(UTC)
    else:
        target_date = datetime.fromisoformat(date)

    from invest_agent.reporting.daily import format_daily_report_markdown, generate_daily_report

    console.print("[bold cyan]일일 리포트 생성[/bold cyan]")
    console.print(f"기준일: {target_date.date().isoformat()}")
    console.print()

    try:
        report = generate_daily_report(db_path=db_path, target_date=target_date)
        report_md = format_daily_report_markdown(report)
    except Exception as e:
        console.print(f"[red]리포트 생성 실패: {e}[/red]")
        raise typer.Exit(1)

    if output:
        out_path = Path(output)
        if out_path.exists():
            console.print(f"[red]파일이 이미 존재합니다: {output}[/red]")
            console.print("[dim]덮어쓰기를 원하면 파일을 삭제 후 다시 실행하세요.[/dim]")
            raise typer.Exit(1)
        out_path.write_text(report_md, encoding="utf-8")
        console.print(f"[green]리포트 저장 완료: {output}[/green]")
    else:
        console.print(report_md)


# ---------------------------------------------------------------------------
# Run app
# ---------------------------------------------------------------------------
run_app = typer.Typer(name="run", help="AI 에이전트 실행")
app.add_typer(run_app)

@run_app.command("once")
def run_once(
    mode: str = typer.Option(
        "offline-sim",
        "--mode",
        "-m",
        help="실행 모드 (offline-sim, backtest, kis-paper, live)",
        case_sensitive=False,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="중복 실행 방지 잠금 무시",
    ),
    asset_filter: str | None = typer.Option(
        None,
        "--asset-filter",
        "-a",
        help="처리할 자산 필터 (쉼표로 구분)",
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="설정 파일 경로",
    ),
) -> None:
    """AI 에이전트 1회 실행 (자동 투자 종합 파이프라인)."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    import asyncio

    from invest_agent.runtime.orchestrator import create_orchestrator
    from invest_agent.settings import load_settings

    settings = load_settings(config) if config else None
    from invest_agent.domain.enums import ExecutionMode
    try:
        exec_mode = ExecutionMode(mode.upper().replace("-", "_"))
    except ValueError:
        console.print(f"[red]Invalid mode: {mode}[/red]")
        console.print(f"Valid modes: {[m.value for m in ExecutionMode]}")
        raise typer.Exit(1)

    asset_filter_list = None
    if asset_filter:
        asset_filter_list = [a.strip().upper() for a in asset_filter.split(",") if a.strip()]

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    from invest_agent.storage.schema import ensure_db
    ensure_db(db_path)

    orchestrator = create_orchestrator(db_path, settings) if settings else create_orchestrator(db_path)

    console.print("[bold cyan]AI 에이전트 1회 실행[/bold cyan]")
    console.print(f"DB: {db_path}")
    console.print(f"실행 모드: {exec_mode.value}")
    console.print()

    try:
        result = asyncio.run(orchestrator.run_once(
            asset_filter=asset_filter_list,
            force=force,
        ))

        console.print("[green]실행 완료[/green]")
        console.print(f"상태: {result.status.value}")
        console.print(f"소요 시간: {result.duration_seconds:.1f}초")
        console.print(f"판단 수: {len(result.decisions)}")
        if result.orders:
            console.print(f"주문 수: {len(result.orders)}")
        if result.error:
            console.print(f"[yellow]경고: {result.error}[/yellow]")
    except RuntimeError as e:
        if "already running" in str(e):
            console.print("[red]이미 실행 중인 작업이 있습니다.[/red]")
            console.print("[dim]--force 옵션으로 강제 실행하거나 기존 작업 완료를 기다리세요.[/dim]")
        else:
            console.print(f"[red]실행 실패: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]실행 중 오류: {e}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Health app
# ---------------------------------------------------------------------------
health_app = typer.Typer(name="health", help="시스템 상태 점검")
app.add_typer(health_app)

@health_app.command("check")
def health_check(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    config: str | None = typer.Option(None, "--config", "-c", help="설정 파일 경로"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 형식으로 출력"),
) -> None:
    """시스템 종합 건강 상태 점검."""
    from invest_agent.operations.health import check_system_health
    from invest_agent.settings import load_settings

    settings = load_settings(config) if config else None
    from invest_agent.settings import get_settings
    if not settings:
        settings = get_settings()

    console.print("[bold cyan]시스템 건강 상태 점검[/bold cyan]")
    console.print(f"DB: {db_path}")
    console.print()

    result = check_system_health(db_path=db_path, settings=settings, broker=None)

    if json_output:
        import json
        output = {
            "is_healthy": result.is_healthy,
            "broker_connected": result.broker_connected,
            "db_accessible": result.db_accessible,
            "last_run_status": result.last_run_status,
            "last_run_at": result.last_run_at.isoformat() if result.last_run_at else None,
            "error": result.error,
        }
        console.print_json(json.dumps(output))
    else:
        table = Table(title="건강 상태")
        table.add_column("항목", style="cyan")
        table.add_column("상태", justify="center")
        table.add_column("상세", style="dim")

        items = [
            ("DB 접근", result.db_accessible, "-"),
            ("브로커 연결", result.broker_connected, "-"),
        ]
        if result.last_run_status:
            items.append(("최근 실행 상태", True, result.last_run_status))
        if result.last_run_at:
            items.append(("최근 실행 시각", True, result.last_run_at.isoformat()))
        if result.error:
            items.append(("오류", False, result.error))

        for name, status, detail in items:
            status_str = "[green]OK[/green]" if status else "[red]FAIL[/red]"
            table.add_row(name, status_str, detail)

        console.print(table)
        console.print()

        if result.is_healthy:
            console.print("[green]전체 상태: 정상[/green]")
        else:
            console.print("[red]전체 상태: 문제 있음[/red]")
            raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Status app
# ---------------------------------------------------------------------------
status_app = typer.Typer(name="status", help="현재 상태 조회")
app.add_typer(status_app)

@status_app.command("show")
def status_show(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    limit: int = typer.Option(10, "--limit", "-l", help="최근 실행 기록 조회 개수"),
) -> None:
    """현재 시스템 상태 요약 조회."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.storage.repositories import (
        AgentRunRepository,
        DecisionRepository,
        ThesisRepository,
    )

    run_repo = AgentRunRepository(db_path)
    decision_repo = DecisionRepository(db_path)
    thesis_repo = ThesisRepository(db_path)

    latest_run = run_repo.get_latest()
    latest_decisions = decision_repo.get_latest(limit)
    active_theses = thesis_repo.get_active()

    console.print("[bold cyan]시스템 상태 요약[/bold cyan]")
    console.print(f"DB: {db_path}")
    console.print()

    if latest_run:
        console.print("[bold]최근 실행[/bold]")
        console.print(f"  Run ID: {latest_run.id}")
        console.print(f"  상태: {latest_run.status.value}")
        console.print(f"  시작: {latest_run.started_at}")
        console.print(f"  모드: {latest_run.execution_mode}")
        console.print()

    console.print(f"[bold]최근 판단 (최대 {limit}개)[/bold]")
    if latest_decisions:
        table = Table()
        table.add_column("시각", style="cyan")
        table.add_column("종목", style="green")
        table.add_column("판단", style="bold")
        table.add_column("모델", style="blue")
        for d in latest_decisions:
            thesis = thesis_repo.get(d.thesis_id)
            asset = thesis.asset_id if thesis else "알 수 없음"
            side_str = d.side.value if d.side else d.outcome.value
            table.add_row(
                d.decided_at.strftime("%Y-%m-%d %H:%M"),
                asset,
                side_str,
                f"{d.model_provider}/{d.model_name}",
            )
        console.print(table)
    else:
        console.print("  판단 기록 없음")
    console.print()

    console.print(f"[bold]활성 가설 ({len(active_theses)}개)[/bold]")
    if active_theses:
        for t in active_theses:
            console.print(f"  - {t.asset_id}: {t.hypothesis[:50]}...")
    else:
        console.print("  없음")


# ---------------------------------------------------------------------------
# Market app
# ---------------------------------------------------------------------------
market_app = typer.Typer(name="market", help="시장 데이터 관리")
app.add_typer(market_app)

@market_app.command("fetch")
def market_fetch(
    asset: str = typer.Option(..., "--asset", "-a", help="종목 코드 (예: KRX:005930, US:AAPL)"),
    start: str = typer.Option(..., "--start", "-s", help="시작일 (YYYY-MM-DD)"),
    end: str | None = typer.Option(None, "--end", "-e", help="종료일 (YYYY-MM-DD, 기본값: 오늘)"),
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    provider: str = typer.Option("auto", "--provider", "-p", help="데이터 공급자 (auto, fdr, yfinance)"),
) -> None:
    """시장 데이터 수집 및 저장."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.market.fdr_provider import fetch_and_store_ohlcv

    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    console.print("[bold cyan]시장 데이터 수집[/bold cyan]")
    console.print(f"종목: {asset}")
    console.print(f"기간: {start} ~ {end}")
    console.print(f"공급자: {provider}")
    console.print()

    try:
        count = fetch_and_store_ohlcv(
            asset_id=asset,
            start_date=start,
            end_date=end,
            db_path=db_path,
            provider=provider,
        )
        console.print(f"[green]수집 완료: {count}건 저장[/green]")
    except Exception as e:
        console.print(f"[red]수집 실패: {e}[/red]")
        raise typer.Exit(1)

@market_app.command("show")
def market_show(
    asset: str = typer.Option(..., "--asset", "-a", help="자산 ID (예: KRX:005930, US:AAPL)"),
    limit: int = typer.Option(30, "--limit", "-l", help="조회할 일수 (기본값: 30)"),
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="데이터 공급자 필터"),
) -> None:
    """저장된 시장 데이터 조회."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    # 입력 검증
    try:
        normalized_asset, market = _parse_asset_id(asset)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if limit < 1:
        console.print("[red]limit은 1 이상이어야 합니다.[/red]")
        raise typer.Exit(1)

    from invest_agent.storage.repositories import OHLCVRepository

    repo = OHLCVRepository(db_path)

    # 저장된 공급자 목록 확인
    providers = repo.get_providers(normalized_asset)
    if not providers:
        console.print(f"[yellow]해당 자산의 저장된 데이터가 없습니다: {normalized_asset}[/yellow]")
        raise typer.Exit(0)

    console.print(f"[blue]Showing OHLCV for {normalized_asset} ({market})...[/blue]")
    console.print(f"  DB: {db_path}")
    console.print(f"  Limit: {limit}")
    console.print(f"  Providers: {', '.join(providers)}")

    # 최신 데이터 조회 (공급자별로 최신 limit개씩)
    all_rows = []
    for prov in providers:
        rows = repo.get_range(
            asset_id=normalized_asset,
            start_date="1900-01-01",
            end_date="2100-12-31",
            provider=prov,
        )
        # limit만큼만 가져오기
        for row in rows[:limit]:
            all_rows.append((prov, row))

    # 날짜 내림차순 정렬
    all_rows.sort(key=lambda x: x[1].timestamp, reverse=True)
    all_rows = all_rows[:limit]

    if not all_rows:
        console.print("[yellow]조회된 데이터가 없습니다.[/yellow]")
        raise typer.Exit(0)

    # 테이블 출력
    table = Table(title=f"OHLCV Data: {normalized_asset}", show_lines=True, expand=True)
    table.add_column("Date", style="cyan", justify="center", no_wrap=True, min_width=12)
    table.add_column("Open", style="green", justify="right", no_wrap=True, min_width=12)
    table.add_column("High", style="green", justify="right", no_wrap=True, min_width=12)
    table.add_column("Low", style="red", justify="right", no_wrap=True, min_width=12)
    table.add_column("Close", style="bold", justify="right", no_wrap=True, min_width=12)
    table.add_column("Volume", style="blue", justify="right", no_wrap=True, min_width=12)
    table.add_column("Provider", style="magenta", no_wrap=True, min_width=15)

    for prov, ohlcv in all_rows:
        date_str = ohlcv.timestamp.date().isoformat()
        table.add_row(
            date_str,
            f"{ohlcv.open:,.2f}",
            f"{ohlcv.high:,.2f}",
            f"{ohlcv.low:,.2f}",
            f"{ohlcv.close:,.2f}",
            f"{ohlcv.volume:,}",
            prov,
        )

    console.print(table)

@market_app.command("refresh")
def market_refresh(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    days: int = typer.Option(5, "--days", help="최근 N일 데이터 갱신 (기본값: 5)"),
    provider: str = typer.Option("auto", "--provider", "-p", help="데이터 공급자"),
) -> None:
    """최근 시장 데이터 갱신 (누락분 보충)."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.market.fdr_provider import refresh_recent_ohlcv

    console.print("[bold cyan]최근 시장 데이터 갱신[/bold cyan]")
    console.print(f"갱신 기간: 최근 {days}일")
    console.print()

    try:
        count = refresh_recent_ohlcv(db_path=db_path, days=days, provider=provider)
        console.print(f"[green]갱신 완료: {count}건 추가/수정[/green]")
    except Exception as e:
        console.print(f"[red]갱신 실패: {e}[/red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# DB app
# ---------------------------------------------------------------------------
db_app = typer.Typer(name="db", help="데이터베이스 관리")
app.add_typer(db_app)

@db_app.command("migrate")
def db_migrate(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    target_version: int | None = typer.Option(None, "--target", "-t", help="목표 스키마 버전 (기본값: 최신)"),
) -> None:
    """데이터베이스 스키마 마이그레이션 실행."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.storage.schema import SCHEMA_VERSION, get_schema_version, migrate

    current = get_schema_version(db_path)
    target = target_version or SCHEMA_VERSION

    console.print("[bold cyan]데이터베이스 마이그레이션[/bold cyan]")
    console.print(f"현재 버전: {current}")
    console.print(f"목표 버전: {target}")
    console.print()

    if current == target:
        console.print("[yellow]이미 최신 버전입니다.[/yellow]")
        return

    if current > target:
        console.print("[red]다운그레이드는 지원하지 않습니다.[/red]")
        raise typer.Exit(1)

    try:
        migrate(db_path, target)
        console.print(f"[green]마이그레이션 완료: v{current} -> v{target}[/green]")
    except Exception as e:
        console.print(f"[red]마이그레이션 실패: {e}[/red]")
        raise typer.Exit(1)

@db_app.command("version")
def db_version(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
) -> None:
    """데이터베이스 스키마 버전 조회."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.storage.schema import SCHEMA_VERSION, get_schema_version

    current = get_schema_version(db_path)
    console.print(f"현재 스키마 버전: {current}")
    console.print(f"최신 스키마 버전: {SCHEMA_VERSION}")

    if current < SCHEMA_VERSION:
        console.print("[yellow]마이그레이션이 필요합니다. 'invest db migrate'를 실행하세요.[/yellow]")


# ---------------------------------------------------------------------------
# Portfolio app
# ---------------------------------------------------------------------------
portfolio_app = typer.Typer(name="portfolio", help="포트폴리오 관리")
app.add_typer(portfolio_app)

@portfolio_app.command("show")
def portfolio_show(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    fx_rate: float = typer.Option(1300.0, "--fx-rate", help="USD/KRW 환율 (기본값: 1300)"),
) -> None:
    """현재 포트폴리오 평가액 조회 (모의 계좌 기반)."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.portfolio import get_portfolio_valuation

    console.print("[bold cyan]포트폴리오 평가[/bold cyan]")
    console.print(f"DB: {db_path}")
    console.print(f"적용 환율: {fx_rate:,.0f} KRW/USD")
    console.print()

    try:
        valuation = get_portfolio_valuation(db_path=db_path, fx_rate_usd_krw=Decimal(str(fx_rate)))
    except Exception as e:
        console.print(f"[red]평가 실패: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]총 평가액: {valuation.total_equity:,.0f} KRW[/bold]")
    console.print()

    table = Table(title="보유 현황")
    table.add_column("구분", style="cyan")
    table.add_column("금액", justify="right", style="bold")
    table.add_column("비중", justify="right", style="yellow")

    table.add_row("KRW 현금", f"{valuation.cash_krw:,.0f} KRW", f"{valuation.cash_krw / valuation.total_equity * 100:.1f}%")
    table.add_row("USD 현금", f"{valuation.cash_usd:,.2f} USD ({valuation.cash_usd * Decimal(str(fx_rate)):,.0f} KRW)", f"{valuation.cash_usd * Decimal(str(fx_rate)) / valuation.total_equity * 100:.1f}%")

    if valuation.positions:
        for pos in valuation.positions:
            mkt_val = pos.quantity * pos.current_price
            krw_val = mkt_val * (Decimal(str(fx_rate)) if pos.currency == "USD" else Decimal("1"))
            table.add_row(
                f"{pos.asset_id} ({pos.quantity:,.4f}주 @ {pos.current_price:,.0f} {pos.currency})",
                f"{krw_val:,.0f} KRW",
                f"{krw_val / valuation.total_equity * 100:.1f}%",
            )

    console.print(table)
    console.print()

    table2 = Table(title="손익 요약")
    table2.add_column("항목", style="cyan")
    table2.add_column("금액", justify="right", style="bold")

    table2.add_row("미실현 손익", f"{valuation.unrealized_pnl:,.0f} KRW")
    if valuation.unrealized_pnl >= 0:
        console.print("[green]미실현 손익: 플러스[/green]")
    else:
        console.print("[red]미실현 손익: 마이너스[/red]")

@portfolio_app.command("snapshot")
def portfolio_snapshot(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    fx_rate: float = typer.Option(1300.0, "--fx-rate", help="USD/KRW 환율"),
    complete: bool = typer.Option(True, "--complete/--incomplete", help="전체 평가 완료 여부 (기본값: 완료)"),
) -> None:
    """포트폴리오 평가 스냅샷 저장."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.portfolio import get_portfolio_valuation
    from invest_agent.storage.repositories import PortfolioSnapshotRepository

    console.print("[bold cyan]포트폴리오 스냅샷 저장[/bold cyan]")
    console.print(f"DB: {db_path}")
    console.print(f"적용 환율: {fx_rate:,.0f} KRW/USD")
    console.print()

    try:
        valuation = get_portfolio_valuation(db_path=db_path, fx_rate_usd_krw=Decimal(str(fx_rate)))

        repo = PortfolioSnapshotRepository(db_path)
        repo.save(
            total_equity=valuation.total_equity,
            cash_krw=valuation.cash_krw,
            cash_usd=valuation.cash_usd,
            fx_rate_usd_krw=Decimal(str(fx_rate)),
            positions={p.asset_id: {"quantity": str(p.quantity), "avg_price": str(p.avg_price), "current_price": str(p.current_price), "currency": p.currency} for p in valuation.positions},
            unrealized_pnl=valuation.unrealized_pnl,
            equity_complete=complete,
        )

        console.print(f"[green]스냅샷 저장 완료: 총 {valuation.total_equity:,.0f} KRW[/green]")
        if not complete:
            console.print("[yellow]주의: 불완전 평가로 저장되었습니다.[/yellow]")
    except Exception as e:
        console.print(f"[red]스냅샷 저장 실패: {e}[/red]")
        raise typer.Exit(1)

@portfolio_app.command("history")
def portfolio_history(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    limit: int = typer.Option(30, "--limit", "-l", help="조회할 기록 개수 (기본값: 30)", min=1, max=100),
) -> None:
    """포트폴리오 평가 이력 조회."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.storage.repositories import PortfolioSnapshotRepository

    repo = PortfolioSnapshotRepository(db_path)
    snapshots = repo.get_latest(limit + 1)

    if not snapshots:
        console.print("[yellow]저장된 포트폴리오 평가 이력이 없습니다.[/yellow]")
        console.print("[dim]먼저 'invest portfolio snapshot'으로 스냅샷을 저장하세요.[/dim]")
        return

    display_snapshots = snapshots[:limit]

    console.print("[bold cyan]포트폴리오 평가 이력[/bold cyan]")
    console.print("기준 통화: KRW")
    console.print(f"조회 개수: {len(display_snapshots)}개 (최신순)")
    console.print()

    table = Table(title="포트폴리오 평가 이력")
    table.add_column("기록 시각", style="cyan", justify="center")
    table.add_column("총 평가액", justify="right", style="bold")
    table.add_column("KRW 현금", justify="right", style="green")
    table.add_column("USD 현금", justify="right", style="green")
    table.add_column("미실현 손익", justify="right", style="red")
    table.add_column("변화액", justify="right", style="yellow")
    table.add_column("상태", style="magenta")

    snap_list = snapshots

    for idx, snap in enumerate(display_snapshots):
        equity_str = f"{snap.total_equity:,.0f} KRW"
        krw_str = f"{snap.cash_krw:,.0f} KRW"
        usd_str = f"{snap.cash_usd:,.2f} USD" if snap.cash_usd != 0 else "0.00 USD"
        unreal_str = f"{snap.unrealized_pnl:,.0f} KRW"
        if snap.unrealized_pnl >= 0:
            unreal_str = f"[green]{unreal_str}[/green]"
        else:
            unreal_str = f"[red]{unreal_str}[/red]"

        prev_snap = None
        if idx + 1 < len(display_snapshots):
            prev_snap = display_snapshots[idx + 1]
        elif idx + 1 < len(snap_list):
            prev_snap = snap_list[idx + 1]

        if prev_snap is not None:
            if not snap.equity_complete or not prev_snap.equity_complete:
                diff_str = "[yellow]계산 불가[/yellow]"
            else:
                diff = snap.total_equity - prev_snap.total_equity
                diff_str = f"{diff:+,.0f} KRW"
                if diff >= 0:
                    diff_str = f"[green]{diff_str}[/green]"
                else:
                    diff_str = f"[red]{diff_str}[/red]"
        else:
            diff_str = "—"

        status = "완전" if snap.equity_complete else "[yellow]불완전[/yellow]"

        table.add_row(
            snap.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            equity_str,
            krw_str,
            usd_str,
            unreal_str,
            diff_str,
            status,
        )

    console.print(table)
    console.print()
    console.print("[dim]참고: 변화액은 단순 평가액 차이입니다. 입출금이 반영되지 않았으므로 투자 수익/수익률로 해석하지 마세요.[/dim]")
    console.print("[dim]미실현 손익만 표시되며, 실현 손익은 별도 거래 내역에서 확인하세요.[/dim]")
    console.print("[dim]불완전 평가 기록이 포함된 변화는 '계산 불가'로 표시됩니다.[/dim]")

@portfolio_app.command("deposit")
def portfolio_deposit(
    amount: str = typer.Option(..., "--amount", "-a", help="입금액 (양수)"),
    currency: str = typer.Option("KRW", "--currency", "-c", help="통화 (KRW 또는 USD)"),
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="중복 방지 키 (자동 생성 가능)"),
) -> None:
    """현금 입금 기록."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from datetime import UTC, datetime
    from decimal import Decimal
    from uuid import uuid4

    from invest_agent.storage.schema import get_connection

    amt = Decimal(amount)
    if amt <= 0:
        console.print("[red]입금액은 양수여야 합니다.[/red]")
        raise typer.Exit(1)

    if currency not in ("KRW", "USD"):
        console.print("[red]통화는 KRW 또는 USD여야 합니다.[/red]")
        raise typer.Exit(1)

    key = idempotency_key or str(uuid4())
    conn = get_connection(db_path)

    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT id FROM cash_flows WHERE idempotency_key = ?", (key,)).fetchone()
        if existing:
            console.print("[yellow]동일한 멱등 키로 이미 기록된 입금입니다.[/yellow]")
            conn.rollback()
            return

        if currency == "KRW":
            row = conn.execute("SELECT cash_krw FROM mock_account WHERE id = 'default'").fetchone()
            before = Decimal(row[0]) if row else Decimal("0")
            after = before + amt
            conn.execute("UPDATE mock_account SET cash_krw = ?, updated_at = ? WHERE id = 'default'", (str(after), datetime.now(UTC).isoformat()))
        else:
            row = conn.execute("SELECT cash_usd FROM mock_account WHERE id = 'default'").fetchone()
            before = Decimal(row[0]) if row else Decimal("0")
            after = before + amt
            conn.execute("UPDATE mock_account SET cash_usd = ?, updated_at = ? WHERE id = 'default'", (str(after), datetime.now(UTC).isoformat()))

        conn.execute(
            """INSERT INTO cash_flows (id, idempotency_key, occurred_at, recorded_at, flow_type, currency, amount, balance_before, balance_after)
               VALUES (?, ?, ?, ?, 'DEPOSIT', ?, ?, ?, ?)""",
            (str(uuid4()), key, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), currency, str(amt), str(before), str(after)),
        )
        conn.commit()
        console.print(f"[green]입금 기록 완료: {amt:,.0f} {currency} (잔액: {after:,.0f} {currency})[/green]")
    except Exception as e:
        conn.rollback()
        console.print(f"[red]입금 기록 실패: {e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

@portfolio_app.command("withdraw")
def portfolio_withdraw(
    amount: str = typer.Option(..., "--amount", "-a", help="출금액 (양수)"),
    currency: str = typer.Option("KRW", "--currency", "-c", help="통화 (KRW 또는 USD)"),
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="중복 방지 키 (자동 생성 가능)"),
) -> None:
    """현금 출금 기록."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from datetime import UTC, datetime
    from decimal import Decimal
    from uuid import uuid4

    from invest_agent.storage.schema import get_connection

    amt = Decimal(amount)
    if amt <= 0:
        console.print("[red]출금액은 양수여야 합니다.[/red]")
        raise typer.Exit(1)

    if currency not in ("KRW", "USD"):
        console.print("[red]통화는 KRW 또는 USD여야 합니다.[/red]")
        raise typer.Exit(1)

    key = idempotency_key or str(uuid4())
    conn = get_connection(db_path)

    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT id FROM cash_flows WHERE idempotency_key = ?", (key,)).fetchone()
        if existing:
            console.print("[yellow]동일한 멱등 키로 이미 기록된 출금입니다.[/yellow]")
            conn.rollback()
            return

        if currency == "KRW":
            row = conn.execute("SELECT cash_krw FROM mock_account WHERE id = 'default'").fetchone()
            before = Decimal(row[0]) if row else Decimal("0")
            if before < amt:
                console.print("[red]잔액 부족[/red]")
                conn.rollback()
                raise typer.Exit(1)
            after = before - amt
            conn.execute("UPDATE mock_account SET cash_krw = ?, updated_at = ? WHERE id = 'default'", (str(after), datetime.now(UTC).isoformat()))
        else:
            row = conn.execute("SELECT cash_usd FROM mock_account WHERE id = 'default'").fetchone()
            before = Decimal(row[0]) if row else Decimal("0")
            if before < amt:
                console.print("[red]잔액 부족[/red]")
                conn.rollback()
                raise typer.Exit(1)
            after = before - amt
            conn.execute("UPDATE mock_account SET cash_usd = ?, updated_at = ? WHERE id = 'default'", (str(after), datetime.now(UTC).isoformat()))

        conn.execute(
            """INSERT INTO cash_flows (id, idempotency_key, occurred_at, recorded_at, flow_type, currency, amount, balance_before, balance_after)
               VALUES (?, ?, ?, ?, 'WITHDRAWAL', ?, ?, ?, ?)""",
            (str(uuid4()), key, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), currency, str(amt), str(before), str(after)),
        )
        conn.commit()
        console.print(f"[green]출금 기록 완료: {amt:,.0f} {currency} (잔액: {after:,.0f} {currency})[/green]")
    except Exception as e:
        conn.rollback()
        console.print(f"[red]출금 기록 실패: {e}[/red]")
        raise typer.Exit(1)
    finally:
        conn.close()

@portfolio_app.command("cashflows")
def portfolio_cashflows(
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    limit: int = typer.Option(30, "--limit", "-l", help="조회할 기록 개수 (기본값: 30)", min=1, max=100),
) -> None:
    """입출금 원장 조회."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.storage.repositories import CashFlowRepository

    repo = CashFlowRepository(db_path)
    flows = repo.get_latest(limit)

    if not flows:
        console.print("[yellow]입출금 기록이 없습니다.[/yellow]")
        return

    console.print("[bold cyan]입출금 원장[/bold cyan]")
    console.print(f"조회 개수: {len(flows)}개 (최신순)")
    console.print()

    table = Table(title="입출금 기록")
    table.add_column("발생 시각", style="cyan", justify="center")
    table.add_column("유형", style="bold", justify="center")
    table.add_column("통화", justify="center")
    table.add_column("금액", justify="right", style="yellow")
    table.add_column("거래 전 잔고", justify="right", style="blue")
    table.add_column("거래 후 잔고", justify="right", style="blue")
    table.add_column("멱등성 키", style="dim")

    for cf in flows:
        flow_str = cf.flow_type.value
        if cf.flow_type.value == "DEPOSIT":
            flow_str = f"[green]{flow_str}[/green]"
        else:
            flow_str = f"[red]{flow_str}[/red]"

        table.add_row(
            cf.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
            flow_str,
            cf.currency,
            f"{cf.amount:,.0f} {cf.currency}",
            f"{cf.balance_before:,.0f} {cf.currency}",
            f"{cf.balance_after:,.0f} {cf.currency}",
            cf.idempotency_key[:20] + "..." if len(cf.idempotency_key) > 20 else cf.idempotency_key,
        )

    console.print(table)
    console.print()

@portfolio_app.command("performance")
def portfolio_performance(
    limit: int = typer.Option(30, "--limit", "-l", help="조회할 구간 개수 (기본값: 30)", min=1, max=100),
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
) -> None:
    """포트폴리오 입출금 조정 성과 분석."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    try:
        from invest_agent.performance import (
            analyze_portfolio_performance,
            format_performance_report,
        )
        intervals = analyze_portfolio_performance(db_path, limit)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]성과 분석 중 오류: {e}[/red]")
        raise typer.Exit(1)

    report = format_performance_report(intervals)
    console.print(report)

@portfolio_app.command("benchmark")
def portfolio_benchmark(
    limit: int = typer.Option(30, "--limit", "-l", help="비교할 평가 구간 개수 (기본값: 30)", min=1, max=100),
    db_path: str = typer.Option("data/agent.db", "--db", "-d", help="SQLite DB 경로"),
    benchmark: str = typer.Option("all", "--benchmark", "-b", help="비교할 벤치마크 (KOSPI200, SPY_ETF, all)", case_sensitive=False),
    provider: str | None = typer.Option(None, "--provider", "-p", help="데이터 공급자 (기본값: 자동)"),
    max_freshness_days: int = typer.Option(5, "--max-freshness-days", help="벤치마크 데이터 최대 허용 경과 일수 (기본값: 5)", min=0, max=30),
) -> None:
    """포트폴리오 수익률을 시장 벤치마크(KOSPI 200, S&P 500)와 비교."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    bench_list = []
    if benchmark.lower() == "all":
        bench_list = ["KOSPI200", "SPY_ETF"]
    elif benchmark.upper() in ("KOSPI200", "SPY_ETF"):
        bench_list = [benchmark.upper()]
    else:
        console.print(f"[red]지원하지 않는 벤치마크: {benchmark}[/red]")
        console.print("지원: KOSPI200, SPY_ETF, all")
        raise typer.Exit(1)

    try:
        from invest_agent.benchmark import compare_with_benchmarks, format_benchmark_report
        results = compare_with_benchmarks(
            db_path=db_path,
            limit=limit,
            benchmarks=bench_list,
            provider=provider,
            max_freshness_days=max_freshness_days,
        )
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]벤치마크 비교 중 오류: {e}[/red]")
        raise typer.Exit(1)

    report = format_benchmark_report(results)
    console.print(report)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Console & Main
# ---------------------------------------------------------------------------
console = Console()


if __name__ == "__main__":
    app()
