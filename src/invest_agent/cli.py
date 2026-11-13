"""CLI 진입점 - Typer 기반."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

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


if __name__ == "__main__":
    app()
