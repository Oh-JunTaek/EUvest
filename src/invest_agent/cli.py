"""CLI 진입점 - Typer 기반."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from invest_agent.broker.mock_broker import MockBroker
from invest_agent.market.ingestion import OHLCVIngestionService
from invest_agent.market.market_data import Market

app = typer.Typer(
    name="invest",
    help="EUvest 투자 에이전트 CLI",
    add_completion=False,
)

console = Console(force_terminal=True)

# Portfolio app
market_app = typer.Typer(name="market", help="시장 데이터 수집 및 조회")
app.add_typer(market_app)

market_app = typer.Typer(name="market", help="시장 데이터 수집 및 조회")
app.add_typer(market_app)

portfolio_app = typer.Typer(name="portfolio", help="포트폴리오 현황 및 손익 조회")
app.add_typer(portfolio_app)


def _parse_asset_id(asset_id: str) -> tuple[str, Market]:
    """자산 ID에서 시장 판별.

    Args:
        asset_id: 자산 ID (예: \"KRX:005930\", \"US:AAPL\")

    Returns:
        (정규화된 자산 ID, 시장)

    Raises:
        ValueError: 지원하지 않는 자산 ID 형식
    """
    asset_id = asset_id.strip().upper()
    if asset_id.startswith("KRX:"):
        return asset_id, Market.KRX
    elif asset_id.startswith("US:"):
        return asset_id, Market.US
    else:
        raise ValueError(
            f"지원하지 않는 자산 ID 형식: {asset_id}. "
            f"KRX:종목코드 또는 US:티커 형식으로 입력하세요."
        )


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

    if not Path(db_path).exists():
        console.print(f"[red]DB 파일이 없습니다: {db_path}[/red]")
        raise typer.Exit(1)

    # MockBroker 생성 (읽기 전용)
    broker = MockBroker(db_path=db_path)

    try:
        balance = broker.get_balance()
        positions = broker.get_positions()
    finally:
        broker.close()

    # 헤더 출력
    console.print("[bold cyan]OFFLINE_SIM 포트폴리오 현황[/bold cyan]")
    console.print("기준 통화: KRW")
    console.print(f"데이터 기준 시각: {balance.updated_at.isoformat() if balance.updated_at else 'N/A'}")
    console.print("가격/환율 출처: MockBroker 내부 상태 (시뮬레이션용)")
    console.print()

    # 현금 잔고
    console.print("[green]현금 잔고[/green]")
    console.print(f"  KRW 가용 현금: {balance.available_cash:,.0f} KRW")
    if hasattr(balance, 'cash_usd') and balance.cash_usd:
        console.print(f"  USD 현금 잔고: {balance.cash_usd:,.2f} USD")
    else:
        console.print("  USD 현금 잔고: 확인 불가 (MockBroker 별도 관리)")
    console.print()

    # 총 평가액
    console.print("[green]총 포트폴리오 평가액[/green]")
    console.print(f"  총 평가액: {balance.total_equity:,.0f} KRW")
    console.print()

    # 보유 종목
    if positions:
        console.print(f"[green]보유 종목 ({len(positions)}개)[/green]")
        table = Table(title="보유 종목 상세")
        table.add_column("자산 ID", style="cyan")
        table.add_column("수량", justify="right", style="yellow")
        table.add_column("평균 매입가", justify="right", style="green")
        table.add_column("평가가격", justify="right", style="green")
        table.add_column("평가금액(KRW)", justify="right", style="magenta")
        table.add_column("미실현 손익(KRW)", justify="right", style="red")

        for pos in positions:
            asset_id = pos.asset_id
            qty = pos.quantity
            avg_price = pos.avg_price
            curr_price = pos.current_price
            market_value = pos.market_value
            unrealized = pos.unrealized_pnl
            currency = pos.currency

            # 표시용 통화 및 가격
            price_display = f"{curr_price:,.2f} {currency}"
            avg_display = f"{avg_price:,.2f} {currency}"
            mkt_display = f"{market_value:,.0f} KRW"
            unreal_display = f"{unrealized:,.0f} KRW"
            if unrealized >= 0:
                unreal_display = f"[green]{unreal_display}[/green]"
            else:
                unreal_display = f"[red]{unreal_display}[/red]"

            table.add_row(asset_id, f"{qty:,.0f}", avg_display, price_display, mkt_display, unreal_display)

        # Capture table output using a recording console
        print("DEBUG: before table capture", file=sys.stdout)
        try:
            table_console = Console(record=True, force_terminal=True, force_interactive=True)
            table_console.print(table)
            table_output = table_console.export_text()
            print(f"DEBUG table_output: {repr(table_output)}", file=sys.stdout)
            print(table_output, file=sys.stdout)
            print(f"DEBUG positions count: {len(positions)}", file=sys.stdout)
            print("DEBUG: after table print", file=sys.stdout)
        except Exception as e:
            print(f"DEBUG: exception in table capture: {e}", file=sys.stdout)
            import traceback
            traceback.print_exc(file=sys.stdout)
    else:
        console.print("[yellow]보유 종목 없음[/yellow]")

    console.print()
    console.print("[dim]참고: 이는 OFFLINE_SIM 시뮬레이션 평가액입니다. 실계좌 평가액과 다릅니다.[/dim]")
    console.print("[dim]미실현 손익만 표시되며, 실현 손익은 별도 거래 내역에서 확인하세요.[/dim]")
    console.print("[dim]누적 수익률, TWR, XIRR, MDD 등은 입출금 기록이 불충분해 계산하지 않습니다.[/dim]")

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

if __name__ == "__main__":
    app()
