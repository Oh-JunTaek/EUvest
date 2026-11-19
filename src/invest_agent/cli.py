"""CLI 진입점 - Typer 기반."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from invest_agent.broker.mock_broker import MockBroker
from invest_agent.domain.models import CashFlowType
from invest_agent.market.ingestion import OHLCVIngestionService
from invest_agent.market.market_data import Market
from invest_agent.operations.health import check_health
from invest_agent.portfolio import calculate_portfolio_valuation
from invest_agent.reporting.daily import save_daily_report
from invest_agent.runtime.orchestrator import create_orchestrator
from invest_agent.settings import get_settings
from invest_agent.storage.repositories import PortfolioSnapshotRepository
from invest_agent.storage.schema import ensure_db, migrate

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
        console.print(f"\n[red]Refresh failed: {result.error}[/red]")
        raise typer.Exit(1)


# DB app
db_app = typer.Typer(name="db", help="데이터베이스 관리")
app.add_typer(db_app)


@db_app.command("migrate")
def db_migrate(
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="백업 확인 없이 강제 실행 (비권장)",
    ),
) -> None:
    """기존 v4 DB를 v5로 마이그레이션.

    portfolio_snapshots 테이블을 추가합니다.
    마이그레이션 전 자동으로 백업을 생성합니다.

    예시:
        uv run invest db migrate --db data/agent.db
    """
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    # 현재 스키마 버전 확인
    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    conn.close()

    if row is None:
        console.print("[red]스키마 버전 정보를 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    current_version = row[0]
    from invest_agent.storage.schema import SCHEMA_VERSION

    if current_version == SCHEMA_VERSION:
        console.print(f"[green]이미 최신 스키마 버전({SCHEMA_VERSION})입니다.[/green]")
        return

    if current_version < 4 or current_version > SCHEMA_VERSION:
        console.print(f"[red]지원하지 않는 마이그레이션: v{current_version} -> v{SCHEMA_VERSION}[/red]")
        raise typer.Exit(1)

    console.print(f"[blue]마이그레이션 시작: v{current_version} -> v{SCHEMA_VERSION}[/blue]")
    console.print(f"  대상 DB: {db_path}")
    console.print(f"  현재 버전: {current_version}")
    console.print(f"  목표 버전: {SCHEMA_VERSION}")

    if not force:
        console.print("[yellow]마이그레이션 전 백업이 자동 생성됩니다.[/yellow]")
        console.print("[yellow]계속하시겠습니까? (y/N):[/yellow] ", end="")
        import sys
        response = sys.stdin.readline().strip().lower()
        if response != "y":
            console.print("[red]취소되었습니다.[/red]")
            raise typer.Exit(1)

    try:
        migrate(db_path)
    except sqlite3.OperationalError as e:
        if "잠금" in str(e) or "lock" in str(e).lower():
            console.print(f"[red]DB가 다른 프로세스에 의해 잠겨 있습니다. 다른 연결을 종료 후 재시도하세요: {e}[/red]")
        else:
            console.print(f"[red]마이그레이션 실패: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]마이그레이션 실패: {e}[/red]")
        raise typer.Exit(1)

    # 검증
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()

    if row and row[0] == SCHEMA_VERSION:
        console.print(f"[green]마이그레이션 완료: v{SCHEMA_VERSION}[/green]")
        console.print(f"  테이블 수: {len(tables)}")
        if any(t[0] == "portfolio_snapshots" for t in tables):
            console.print("  portfolio_snapshots 테이블: 생성됨")
    else:
        console.print("[red]마이그레이션 후 검증 실패[/red]")
        raise typer.Exit(1)


# Portfolio app
portfolio_app = typer.Typer(name="portfolio", help="포트폴리오 현황 및 손익 조회")
app.add_typer(portfolio_app)


@portfolio_app.command("show")
def portfolio_show(
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """OFFLINE_SIM 포트폴리오 현황 및 손익 조회.

    MockBroker 계좌의 현금, 보유 종목, 평가액, 미실현 손익을 출력합니다.
    실시간 시세 조회나 주문 실행은 하지 않습니다.

    예시:
        uv run invest portfolio show --db data/agent.db
    """
    try:
        valuation = calculate_portfolio_valuation(db_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 헤더 출력
    console.print("[bold cyan]OFFLINE_SIM 포트폴리오 현황[/bold cyan]")
    console.print("기준 통화: KRW")
    console.print(f"조회 시각: {valuation.timestamp}")
    if valuation.db_updated_at:
        console.print(f"DB 갱신 시각: {valuation.db_updated_at}")
    console.print(f"적용 환율: 1 USD = {valuation.fx_rate:,.0f} KRW (DB 저장값)")
    console.print("가격/환율 출처: MockBroker 내부 상태 (시뮬레이션용)")
    console.print()

    # 현금 잔고
    console.print("[green]현금 잔고[/green]")
    console.print(f"  KRW 가용 현금: {valuation.cash_krw:,.0f} KRW")
    if valuation.cash_usd == 0:
        console.print("  USD 현금 잔고: 0.00 USD")
    else:
        console.print(f"  USD 현금 잔고: {valuation.cash_usd:,.2f} USD")
    console.print()

    # 총 평가액 출력
    console.print("[green]총 포트폴리오 평가액[/green]")
    for label, value in valuation.equity_parts:
        if value is not None:
            console.print(f"  {label}: {value:,.0f} KRW")
        else:
            console.print(f"  {label}: 미확인")

    if valuation.equity_complete:
        console.print(f"  [bold]총 평가액: {valuation.total_equity:,.0f} KRW[/bold]")
    else:
        console.print(f"  [yellow]총 평가액: {valuation.total_equity:,.0f} KRW (일부 항목 미확인, 불완전)[/yellow]")
    console.print()

    # 보유 종목
    if valuation.positions:
        console.print(f"[green]보유 종목 ({len(valuation.positions)}개)[/green]")
        table = Table(title="보유 종목 상세")
        table.add_column("자산 ID", style="cyan")
        table.add_column("수량", justify="right", style="yellow")
        table.add_column("평균 매입가", justify="right", style="green")
        table.add_column("평가가격", justify="right", style="green")
        table.add_column("평가금액(KRW)", justify="right", style="magenta")
        table.add_column("미실현 손익(KRW)", justify="right", style="red")

        for pos in valuation.positions:
            # PortfolioPosition 객체에서 표시용 문자열 생성
            avg_display = f"{pos.avg_price:,.2f} {pos.currency}"
            price_display = f"{pos.current_price:,.2f} {pos.currency}"
            mkt_display = f"{pos.market_value_krw:,.0f} KRW"
            unreal_display = f"{pos.unrealized_krw:,.0f} KRW"
            if pos.unrealized_krw >= 0:
                unreal_display = f"[green]{unreal_display}[/green]"
            else:
                unreal_display = f"[red]{unreal_display}[/red]"

            table.add_row(
                pos.asset_id,
                f"{pos.quantity:,.0f}",
                avg_display,
                price_display,
                mkt_display,
                unreal_display,
            )

        console.print(table)
    else:
        console.print("[yellow]보유 종목 없음[/yellow]")

    console.print()
    console.print("[dim]참고: 이는 OFFLINE_SIM 시뮬레이션 평가액입니다. 실계좌 평가액과 다릅니다.[/dim]")
    console.print("[dim]미실현 손익만 표시되며, 실현 손익은 별도 거래 내역에서 확인하세요.[/dim]")
    console.print("[dim]누적 수익률, TWR, XIRR, MDD 등은 입출금 기록이 불충분해 계산하지 않습니다.[/dim]")


@portfolio_app.command("snapshot")
def portfolio_snapshot(
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """현재 포트폴리오 상태를 스냅샷으로 저장.

    MockBroker 계좌의 현재 평가액을 포트폴리오 평가 이력으로 기록합니다.
    이 명령은 계좌 상태를 변경하지 않습니다 (읽기 전용).

    예시:
        uv run invest portfolio snapshot --db data/agent.db
    """
    try:
        valuation = calculate_portfolio_valuation(db_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # 포트폴리오 스냅샷 저장
    repo = PortfolioSnapshotRepository(db_path)

    from uuid import uuid4

    from invest_agent.domain.models import PortfolioSnapshot

    snapshot = PortfolioSnapshot(
        id=uuid4(),
        timestamp=datetime.fromisoformat(valuation.timestamp.replace("Z", "+00:00")) if valuation.timestamp.endswith("Z") else datetime.fromisoformat(valuation.timestamp),
        cash_krw=valuation.cash_krw,
        cash_usd=valuation.cash_usd,
        fx_rate_usd_krw=valuation.fx_rate,
        total_equity=valuation.total_equity,
        positions={
            pos.asset_id: {
                "quantity": str(pos.quantity),
                "avg_price": str(pos.avg_price),
                "current_price": str(pos.current_price),
                "currency": pos.currency,
                "market_value_krw": str(pos.market_value_krw),
                "unrealized_krw": str(pos.unrealized_krw),
            }
            for pos in valuation.positions  # type: ignore[attr-defined]
        },
        unrealized_pnl=valuation.unrealized_pnl,
        equity_complete=valuation.equity_complete,
        metadata={
            "db_updated_at": valuation.db_updated_at,
            "query_time": valuation.timestamp,
        },
    )

    repo.save(snapshot)

    console.print("[green]포트폴리오 스냅샷 저장 완료[/green]")
    console.print(f"  스냅샷 ID: {snapshot.id}")
    console.print(f"  기록 시각: {snapshot.timestamp.isoformat()}")
    console.print(f"  총 평가액: {snapshot.total_equity:,.0f} KRW")
    if not snapshot.equity_complete:
        console.print("  [yellow]주의: 평가 불완전 (일부 항목 미확인)[/yellow]")


@portfolio_app.command("history")
def portfolio_history(
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
    limit: int = typer.Option(
        30,
        "--limit",
        "-l",
        help="조회할 기록 개수 (기본값: 30)",
        min=1,
        max=100,
    ),
) -> None:
    """포트폴리오 평가 이력 조회.

    저장된 포트폴리오 스냅샷을 최신순으로 출력합니다.
    이전 기록 대비 평가액 변화도 함께 표시합니다.

    예시:
        uv run invest portfolio history --db data/agent.db
        uv run invest portfolio history --db data/agent.db --limit 10
    """
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    repo = PortfolioSnapshotRepository(db_path)
    # limit+1개를 조회하여 가장 오래된 표시 레코드의 변화액도 정확히 계산
    snapshots = repo.get_latest(limit + 1)

    if not snapshots:
        console.print("[yellow]저장된 포트폴리오 평가 이력이 없습니다.[/yellow]")
        console.print("[dim]먼저 'invest portfolio snapshot'으로 스냅샷을 저장하세요.[/dim]")
        return

    # 표시할 레코드만 자르기 (limit 개)
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

    # 전체 스냅샷 리스트에서 이전 레코드 찾기용 인덱스 맵 생성
    # snapshots는 최신순 정렬되어 있음
    snap_list = snapshots  # 이미 최신순

    for idx, snap in enumerate(display_snapshots):
        equity_str = f"{snap.total_equity:,.0f} KRW"
        krw_str = f"{snap.cash_krw:,.0f} KRW"
        usd_str = f"{snap.cash_usd:,.2f} USD" if snap.cash_usd != 0 else "0.00 USD"
        unreal_str = f"{snap.unrealized_pnl:,.0f} KRW"
        if snap.unrealized_pnl >= 0:
            unreal_str = f"[green]{unreal_str}[/green]"
        else:
            unreal_str = f"[red]{unreal_str}[/red]"

        # 이전(과거) 레코드 찾기: display_snapshots에서 idx+1이 존재하면 그것, 없으면 snapshots에서 찾기
        prev_snap = None
        if idx + 1 < len(display_snapshots):
            prev_snap = display_snapshots[idx + 1]
        elif idx + 1 < len(snap_list):
            prev_snap = snap_list[idx + 1]

        if prev_snap is not None:
            # 둘 중 하나라도 불완전하면 계산 불가
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
    amount: str = typer.Option(
        ...,
        "--amount",
        "-a",
        help="입금액 (양수)",
    ),
    currency: str = typer.Option(
        "KRW",
        "--currency",
        "-c",
        help="통화 (KRW 또는 USD)",
        case_sensitive=False,
    ),
    idempotency_key: str | None = typer.Option(
        None,
        "--idempotency-key",
        "-k",
        help="멱등성 키 (미제공 시 자동 생성)",
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """모의 계좌에 입금."""

    from decimal import InvalidOperation

    try:
        amount_dec = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        console.print(f"[red]잘못된 금액: {amount}[/red]")
        raise typer.Exit(1)

    if amount_dec <= 0:
        console.print("[red]입금액은 양수여야 합니다[/red]")
        raise typer.Exit(1)

    currency = currency.upper()
    if currency not in ("KRW", "USD"):
        console.print(f"[red]지원하지 않는 통화: {currency}[/red]")
        raise typer.Exit(1)

    try:
        broker = MockBroker(db_path=db_path)
        cash_flow = broker.deposit(
            amount=amount_dec,
            currency=currency,
            idempotency_key=idempotency_key,
        )
        broker.close()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]입금 처리 중 오류: {e}[/red]")
        raise typer.Exit(1)

    console.print("[green]입금 완료[/green]")
    console.print(f"  ID: {cash_flow.id}")
    console.print(f"  멱등성 키: {cash_flow.idempotency_key}")
    console.print(f"  발생 시각: {cash_flow.occurred_at.isoformat()}")
    console.print(f"  종류: 입금 ({cash_flow.flow_type.value})")
    console.print(f"  통화: {cash_flow.currency}")
    console.print(f"  금액: {cash_flow.amount:,.0f} {cash_flow.currency}")
    console.print(f"  입금 전 잔고: {cash_flow.balance_before:,.0f} {cash_flow.currency}")
    console.print(f"  입금 후 잔고: {cash_flow.balance_after:,.0f} {cash_flow.currency}")


@portfolio_app.command("withdraw")
def portfolio_withdraw(
    amount: str = typer.Option(
        ...,
        "--amount",
        "-a",
        help="출금액 (양수)",
    ),
    currency: str = typer.Option(
        "KRW",
        "--currency",
        "-c",
        help="통화 (KRW 또는 USD)",
        case_sensitive=False,
    ),
    idempotency_key: str | None = typer.Option(
        None,
        "--idempotency-key",
        "-k",
        help="멱등성 키 (미제공 시 자동 생성)",
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """모의 계좌에서 출금."""
    from decimal import InvalidOperation

    try:
        amount_dec = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        console.print(f"[red]잘못된 금액: {amount}[/red]")
        raise typer.Exit(1)

    if amount_dec <= 0:
        console.print("[red]출금액은 양수여야 합니다[/red]")
        raise typer.Exit(1)

    currency = currency.upper()
    if currency not in ("KRW", "USD"):
        console.print(f"[red]지원하지 않는 통화: {currency}[/red]")
        raise typer.Exit(1)

    try:
        broker = MockBroker(db_path=db_path)
        cash_flow = broker.withdraw(
            amount=amount_dec,
            currency=currency,
            idempotency_key=idempotency_key,
        )
        broker.close()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]출금 처리 중 오류: {e}[/red]")
        raise typer.Exit(1)

    console.print("[green]출금 완료[/green]")
    console.print(f"  ID: {cash_flow.id}")
    console.print(f"  멱등성 키: {cash_flow.idempotency_key}")
    console.print(f"  발생 시각: {cash_flow.occurred_at.isoformat()}")
    console.print(f"  종류: 출금 ({cash_flow.flow_type.value})")
    console.print(f"  통화: {cash_flow.currency}")
    console.print(f"  금액: {cash_flow.amount:,.0f} {cash_flow.currency}")
    console.print(f"  출금 전 잔고: {cash_flow.balance_before:,.0f} {cash_flow.currency}")
    console.print(f"  출금 후 잔고: {cash_flow.balance_after:,.0f} {cash_flow.currency}")


@portfolio_app.command("cashflows")
def portfolio_cashflows(
    limit: int = typer.Option(
        30,
        "--limit",
        "-l",
        help="조회할 기록 개수 (기본값: 30)",
        min=1,
        max=100,
    ),
    currency: str | None = typer.Option(
        None,
        "--currency",
        "-c",
        help="통화 필터 (KRW 또는 USD)",
        case_sensitive=False,
    ),
    flow_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="입금/출금 필터 (DEPOSIT 또는 WITHDRAWAL)",
        case_sensitive=False,
    ),
    db_path: str = typer.Option(
        "data/agent.db",
        "--db",
        "-d",
        help="SQLite DB 경로",
    ),
) -> None:
    """입출금 원장 조회."""
    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    from invest_agent.storage.repositories import CashFlowRepository

    repo = CashFlowRepository(db_path)

    if currency:
        currency = currency.upper()
        if currency not in ("KRW", "USD"):
            console.print(f"[red]지원하지 않는 통화: {currency}[/red]")
            raise typer.Exit(1)
        cash_flows = repo.get_by_currency(currency, limit)
    elif flow_type:
        flow_type = flow_type.upper()
        if flow_type not in ("DEPOSIT", "WITHDRAWAL"):
            console.print(f"[red]지원하지 않는 타입: {flow_type}[/red]")
            raise typer.Exit(1)
        cash_flows = repo.get_by_flow_type(CashFlowType(flow_type), limit)
    else:
        cash_flows = repo.get_latest(limit)

    if not cash_flows:
        console.print("[yellow]저장된 입출금 기록이 없습니다.[/yellow]")
        return

    console.print("[bold cyan]입출금 원장[/bold cyan]")
    console.print("기준 통화: KRW/USD")
    console.print(f"조회 개수: {len(cash_flows)}개 (최신순)")
    console.print()

    table = Table(title="입출금 원장")
    table.add_column("발생 시각", style="cyan", justify="center")
    table.add_column("종류", justify="center", style="bold")
    table.add_column("통화", justify="center")
    table.add_column("금액", justify="right", style="green")
    table.add_column("거래 전 잔고", justify="right", style="blue")
    table.add_column("거래 후 잔고", justify="right", style="blue")
    table.add_column("멱등성 키", style="dim")

    for cf in cash_flows:
        flow_str = cf.flow_type.value
        if cf.flow_type == CashFlowType.DEPOSIT:
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


if __name__ == "__main__":
    app()
