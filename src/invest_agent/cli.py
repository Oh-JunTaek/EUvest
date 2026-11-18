"""CLI 진입점 - Typer 기반."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from invest_agent.market.ingestion import OHLCVIngestionService
from invest_agent.market.market_data import Market
from invest_agent.operations.health import check_health
from invest_agent.reporting.daily import save_daily_report
from invest_agent.runtime.orchestrator import create_orchestrator
from invest_agent.settings import get_settings
from invest_agent.storage.schema import ensure_db

app = typer.Typer(
    name="invest",
    help="EUvest 투자 에이전트 CLI",
    add_completion=False,
)
console = Console()


@app.command()
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
    """단일 실행 사이클 수행 (run-once)."""
    import asyncio

    # 설정 로드
    if config:
        from invest_agent.settings import load_settings
        settings = load_settings(config)
    else:
        settings = get_settings()

    # 실행 모드 검증
    from invest_agent.domain.enums import ExecutionMode
    try:
        exec_mode = ExecutionMode(mode.upper().replace("-", "_"))
    except ValueError:
        console.print(f"[red]Invalid mode: {mode}[/red]")
        console.print(f"Valid modes: {[m.value for m in ExecutionMode]}")
        raise typer.Exit(1)

    # 설정의 실행 모드와 일치하는지 확인
    if settings.execution.mode != exec_mode:
        console.print(f"[yellow]Warning: Config mode ({settings.execution.mode.value}) differs from CLI mode ({exec_mode.value})[/yellow]")

    # 자산 필터 파싱
    asset_filter_list = None
    if asset_filter:
        asset_filter_list = [a.strip().upper() for a in asset_filter.split(",") if a.strip()]

    # DB 초기화
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    ensure_db(db_path)

    # 오케스트레이터 생성 및 실행
    orchestrator = create_orchestrator(db_path, settings)

    console.print("[blue]Starting run-once...[/blue]")
    console.print(f"  Mode: {exec_mode.value}")
    console.print(f"  DB: {db_path}")
    console.print(f"  Force: {force}")
    if asset_filter_list:
        console.print(f"  Asset filter: {asset_filter_list}")

    try:
        result = asyncio.run(orchestrator.run_once(
            asset_filter=asset_filter_list,
            force=force,
        ))

        # 결과 출력
        console.print("\n[green]Run completed![/green]")
        console.print(f"  Run ID: {result.run_id}")
        console.print(f"  Status: {result.status.value}")
        console.print(f"  Decision: {result.decision_outcome.value}")
        console.print(f"  Orders created: {result.orders_created}")
        console.print(f"  Orders filled: {result.orders_filled}")
        if result.error:
            console.print(f"  Error: {result.error}")

        if result.status.value in ("FAILED", "ERROR", "RECOVERY_REQUIRED"):
            raise typer.Exit(1)

    except RuntimeError as e:
        console.print(f"[red]Execution blocked: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Execution failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def health(
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
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="JSON 형식으로 출력",
    ),
) -> None:
    """시스템 헬스 체크."""
    if config:
        from invest_agent.settings import load_settings
        settings = load_settings(config)
    else:
        settings = get_settings()

    # 브로커 없이 DB만 체크
    result = check_health(db_path, settings, broker=None)

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
        if result.is_healthy:
            console.print("[green]✓ System healthy[/green]")
        else:
            console.print("[red]✗ System unhealthy[/red]")

        console.print(f"  DB accessible: {'✓' if result.db_accessible else '✗'}")
        console.print(f"  Broker connected: {'✓' if result.broker_connected else '✗'}")
        if result.last_run_status:
            console.print(f"  Last run status: {result.last_run_status}")
        if result.last_run_at:
            console.print(f"  Last run at: {result.last_run_at.isoformat()}")
        if result.error:
            console.print(f"  Error: {result.error}")

    if not result.is_healthy:
        raise typer.Exit(1)


@app.command()
def report(
    date: str | None = typer.Option(
        None,
        "--date",
        help="대상 날짜 (YYYY-MM-DD, 기본값: 오늘)",
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="출력 파일 경로",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="설정 파일 경로",
    ),
) -> None:
    """일일 리포트 생성 및 저장."""
    from datetime import UTC, datetime

    if config:
        from invest_agent.settings import load_settings
        load_settings(config)
    else:
        get_settings()

    target_date = None
    if date:
        try:
            target_date = datetime.fromisoformat(date).replace(tzinfo=UTC)
        except ValueError:
            console.print(f"[red]Invalid date format: {date}. Use YYYY-MM-DD[/red]")
            raise typer.Exit(1)

    try:
        saved_path = save_daily_report(db_path, target_date, output)
        console.print(f"[green]Daily report saved to: {saved_path}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to generate report: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def status(
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        "-r",
        help="특정 실행 ID 조회",
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-l",
        help="최근 실행 기록 조회 개수",
    ),
) -> None:
    """실행 상태 조회."""
    from invest_agent.storage.repositories import AgentRunRepository

    ensure_db(db_path)
    run_repo = AgentRunRepository(db_path)

    if run_id:
        run = run_repo.get(UUID(run_id))
        if not run:
            console.print(f"[red]Run not found: {run_id}[/red]")
            raise typer.Exit(1)
        _print_run(run)
    else:
        runs = run_repo.get_latest(limit)
        if not runs:
            console.print("[yellow]No runs found[/yellow]")
            return

        table = Table(title=f"Latest {len(runs)} Runs")
        table.add_column("Run ID", style="cyan")
        table.add_column("Started", style="dim")
        table.add_column("Status", style="bold")
        table.add_column("Mode")
        table.add_column("Decisions")
        table.add_column("Orders")
        table.add_column("Error")

        for run in runs:
            started = run.started_at.strftime("%Y-%m-%d %H:%M:%S")
            status_style = _get_status_style(run.status.value)
            table.add_row(
                str(run.id)[:8] + "...",
                started,
                f"[{status_style}]{run.status.value}[/{status_style}]",
                run.execution_mode,
                str(len(run.decision_ids)),
                str(len(run.order_ids)),
                run.error[:30] + "..." if run.error and len(run.error) > 30 else (run.error or "-"),
            )

        console.print(table)


def _get_status_style(status: str) -> str:
    """상태별 스타일 반환."""
    if status == "COMPLETED":
        return "green"
    elif status in ("BLOCKED", "SKIPPED_ALREADY_RUNNING"):
        return "yellow"
    elif status in ("RECOVERY_REQUIRED", "ERROR"):
        return "red"
    return "blue"


def _print_run(run) -> None:
    """단일 실행 상세 출력."""
    from rich.panel import Panel

    lines = [
        f"Run ID: {run.id}",
        f"Started: {run.started_at.isoformat()}",
        f"Completed: {run.completed_at.isoformat() if run.completed_at else 'N/A'}",
        f"Status: {run.status.value}",
        f"Mode: {run.execution_mode}",
        f"Theses: {len(run.thesis_ids)}",
        f"Decisions: {len(run.decision_ids)}",
        f"Orders: {len(run.order_ids)}",
    ]
    if run.error:
        lines.append(f"Error: {run.error}")

    console.print(Panel("\n".join(lines), title="Run Details", border_style="blue"))


# === Market Command Group ===

market_app = typer.Typer(name="market", help="시장 데이터 수집 및 조회")
app.add_typer(market_app)


def _parse_asset_id(asset_id: str) -> tuple[str, Market]:
    """자산 ID에서 시장 판별.

    Args:
        asset_id: 자산 ID (예: "KRX:005930", "US:AAPL")

    Returns:
        (정규화된 자산 ID, 시장)

    Raises:
        ValueError: 지원하지 않는 시장 형식
    """
    asset_id = asset_id.strip().upper()
    if asset_id.startswith("KRX:"):
        return asset_id, Market.KRX
    elif asset_id.startswith("US:"):
        return asset_id, Market.US
    else:
        raise ValueError(
            f"지원하지 않는 자산 ID 형식: {asset_id}. "
            f"KRX:종목코드 또는 US:심볼 형식으로 입력하세요."
        )


def _validate_date(date_str: str) -> str:
    """날짜 형식 검증 (YYYY-MM-DD).

    Args:
        date_str: 날짜 문자열

    Returns:
        검증된 날짜 문자열

    Raises:
        ValueError: 잘못된 날짜 형식
    """
    from datetime import datetime

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise ValueError(f"잘못된 날짜 형식: {date_str}. YYYY-MM-DD 형식으로 입력하세요.")


@market_app.command("fetch")
def market_fetch(
    asset: str = typer.Option(
        ...,
        "--asset",
        "-a",
        help="자산 ID (예: KRX:005930, US:AAPL)",
    ),
    start: str = typer.Option(
        ...,
        "--start",
        "-s",
        help="시작일 (YYYY-MM-DD)",
    ),
    end: str = typer.Option(
        ...,
        "--end",
        "-e",
        help="종료일 (YYYY-MM-DD)",
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """OHLCV 일봉 데이터 수집 및 저장.

    FDR(FinanceDataReader)을 통해 일봉을 조회하고 SQLite에 저장합니다.

    예시:
        uv run invest market fetch --asset KRX:005930 --start 2024-01-01 --end 2024-01-31
        uv run invest market fetch --asset US:AAPL --start 2024-01-01 --end 2024-01-31
    """
    from pathlib import Path

    # 입력 검증
    try:
        normalized_asset, market = _parse_asset_id(asset)
        start_date = _validate_date(start)
        end_date = _validate_date(end)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if start_date > end_date:
        console.print("[red]시작일이 종료일보다 늦을 수 없습니다.[/red]")
        raise typer.Exit(1)

    # DB 초기화
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    ensure_db(db_path)

    console.print(f"[blue]Fetching OHLCV for {normalized_asset} ({market.value})...[/blue]")
    console.print(f"  Period: {start_date} ~ {end_date}")
    console.print(f"  DB: {db_path}")

    # 수집 서비스 실행
    service = OHLCVIngestionService(db_path)
    result = service.ingest(normalized_asset, market, start_date, end_date)

    # 결과 출력
    if result.error:
        console.print(f"[red]Failed: {result.error}[/red]")
        raise typer.Exit(1)

    console.print("[green]Success![/green]")
    console.print(f"  Provider: {result.provider}")
    console.print(f"  Fetched: {result.fetched_count} rows")
    console.print(f"  Saved:   {result.saved_count} rows")
    console.print(f"  Fetched at: {result.fetched_at.isoformat()}")


@market_app.command("show")
def market_show(
    asset: str = typer.Option(
        ...,
        "--asset",
        "-a",
        help="자산 ID (예: KRX:005930, US:AAPL)",
    ),
    limit: int = typer.Option(
        5,
        "--limit",
        "-l",
        help="출력할 일봉 개수 (기본값: 5)",
        min=1,
        max=100,
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """저장된 OHLCV 일봉 데이터 조회.

    SQLite에 저장된 일봉 데이터를 최신순으로 출력합니다.

    예시:
        uv run invest market show --asset KRX:005930
        uv run invest market show --asset US:AAPL --limit 10
    """
    from pathlib import Path

    from invest_agent.storage.repositories import OHLCVRepository

    # 입력 검증
    try:
        normalized_asset, market = _parse_asset_id(asset)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if limit < 1:
        console.print("[red]limit은 1 이상이어야 합니다.[/red]")
        raise typer.Exit(1)

    # DB 존재 확인
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[blue]Showing OHLCV for {normalized_asset} ({market.value})...[/blue]")
    console.print(f"  DB: {db_path}")
    console.print(f"  Limit: {limit}")

    # 리포지토리로 조회
    repo = OHLCVRepository(db_path)

    # 저장된 공급자 목록 확인
    providers = repo.get_providers(normalized_asset)
    if not providers:
        console.print(f"[yellow]해당 자산의 저장된 데이터가 없습니다: {normalized_asset}[/yellow]")
        raise typer.Exit(0)

    console.print(f"  Providers: {', '.join(providers)}")

    # 최신 데이터 조회 (공급자별로 최신 limit개씩)
    all_rows = []
    for provider in providers:
        rows = repo.get_range(
            asset_id=normalized_asset,
            start_date="1900-01-01",
            end_date="2100-12-31",
            provider=provider,
        )
        # limit만큼만 가져오기
        for row in rows[:limit]:
            all_rows.append((provider, row))

    # 날짜 내림차순 정렬
    all_rows.sort(key=lambda x: x[1].timestamp, reverse=True)
    all_rows = all_rows[:limit]

    if not all_rows:
        console.print("[yellow]조회된 데이터가 없습니다.[/yellow]")
        raise typer.Exit(0)

    # 테이블 출력
    table = Table(title=f"OHLCV Data: {normalized_asset}")
    table.add_column("Date", style="cyan", justify="center")
    table.add_column("Open", style="green", justify="right")
    table.add_column("High", style="green", justify="right")
    table.add_column("Low", style="red", justify="right")
    table.add_column("Close", style="bold", justify="right")
    table.add_column("Volume", style="blue", justify="right")
    table.add_column("Provider", style="magenta")

    for provider, ohlcv in all_rows:
        date_str = ohlcv.timestamp.date().isoformat()
        table.add_row(
            date_str,
            f"{ohlcv.open:,.2f}",
            f"{ohlcv.high:,.2f}",
            f"{ohlcv.low:,.2f}",
            f"{ohlcv.close:,.2f}",
            f"{ohlcv.volume:,}",
            provider,
        )

    console.print(table)



@market_app.command("refresh")
def market_refresh(
    asset: str = typer.Option(
        ...,
        "--asset",
        "-a",
        help="자산 ID (예: KRX:005930, US:AAPL)",
    ),
    max_age_days: int = typer.Option(
        7,
        "--max-age-days",
        help="데이터 최대 경과 일수 (기본값: 7)",
        min=0,
        max=365,
    ),
    lookback: int = typer.Option(
        20,
        "--lookback",
        help="분석에 필요한 최소 데이터 개수 (기본값: 20)",
        min=1,
        max=200,
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """시장 데이터 자동 갱신.

    데이터가 없거나 오래된 경우(마지막 거래일로부터 max_age_days 초과) FDR로 갱신합니다.
    이미 최신 데이터가 충분하면 갱신을 생략합니다.

    예시:
        uv run invest market refresh --asset KRX:005930
        uv run invest market refresh --asset US:AAPL --max-age-days 7 --lookback 20
    """
    from pathlib import Path

    # 입력 검증
    try:
        normalized_asset, market = _parse_asset_id(asset)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if max_age_days < 0:
        console.print("[red]max-age-days는 0 이상이어야 합니다.[/red]")
        raise typer.Exit(1)

    if lookback < 1:
        console.print("[red]lookback은 1 이상이어야 합니다.[/red]")
        raise typer.Exit(1)

    # DB 존재 확인
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[blue]Checking market data for {normalized_asset} ({market.value})...[/blue]")
    console.print(f"  DB: {db_path}")
    console.print(f"  Max age days: {max_age_days}")
    console.print(f"  Lookback: {lookback}")

    # 수집 서비스 생성 및 실행
    from invest_agent.market.ingestion import OHLCVIngestionService
    ingestion_service = OHLCVIngestionService(db_path)

    console.print("  Checking data freshness...")
    result = ingestion_service.refresh_if_needed(
        asset_id=normalized_asset,
        market=market,
        max_age_days=max_age_days,
        lookback=lookback,
    )

    # 결과 출력
    if result.action == "skipped":
        console.print("\n[green]Data is fresh, skipping refresh.[/green]")
        console.print(f"  Provider: {result.provider}")
        console.print(f"  Last trade date: {result.last_trade_date}")
        console.print(f"  Age: {result.age_days} days")
        console.print(f"  Fresh: {result.is_fresh}")
        console.print(f"  Sufficient: {result.is_sufficient}")
    elif result.action == "refreshed":
        console.print("\n[green]Data refreshed successfully![/green]")
        console.print(f"  Provider: {result.provider}")
        console.print(f"  Fetched: {result.fetched_count} rows")
        console.print(f"  Saved: {result.saved_count} rows")
        if result.last_trade_date:
            console.print(f"  Last trade date: {result.last_trade_date}")
        if result.age_days is not None:
            console.print(f"  Age: {result.age_days} days")
        console.print(f"  Fresh: {result.is_fresh}")
        console.print(f"  Sufficient: {result.is_sufficient}")
    else:  # error
        console.print("\n[red]Refresh failed: {result.error}[/red]")
        raise typer.Exit(1)

if __name__ == "__main__":
    app()
