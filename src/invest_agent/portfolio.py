"""포트폴리오 평가 공통 유틸리티.

CLI 명령어와 스냅샷 저장 간에 공통으로 사용되는 계산 로직을 제공한다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PortfolioValuation:
    """포트폴리오 평가 결과."""

    timestamp: str
    db_updated_at: str | None
    cash_krw: Decimal
    cash_usd: Decimal
    fx_rate: Decimal
    total_equity: Decimal
    equity_complete: bool
    equity_parts: list[tuple[str, Decimal | None]]
    positions: list[dict[str, Any]]
    unrealized_pnl: Decimal


@dataclass(slots=True)
class PortfolioPosition:
    """포트폴리오 보유 종목 원본 데이터 (표시용 포맷팅과 분리)."""

    asset_id: str
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    currency: str
    market_value_krw: Decimal
    unrealized_krw: Decimal


def calculate_portfolio_valuation(db_path: str | Path) -> PortfolioValuation:
    """DB에서 포트폴리오 평가액을 계산한다.

    Args:
        db_path: SQLite DB 경로

    Returns:
        PortfolioValuation: 평가 결과

    Raises:
        FileNotFoundError: DB 파일이 없는 경우
        ValueError: mock_account 레코드가 없는 경우
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DB 파일이 없습니다: {db_path}")

    # SQLite 읽기 전용 연결
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 계좌 정보 조회 (환율, 갱신 시각 포함)
    account_row = cursor.execute(
        "SELECT cash_krw, cash_usd, fx_rate_usd_krw, updated_at "
        "FROM mock_account WHERE id = 'default'"
    ).fetchone()

    if not account_row:
        conn.close()
        raise ValueError("mock_account 레코드가 없습니다: default")

    cash_krw = Decimal(account_row["cash_krw"])
    cash_usd = Decimal(account_row["cash_usd"])
    fx_rate = Decimal(account_row["fx_rate_usd_krw"])
    db_updated_at = account_row["updated_at"]

    # 환율 검증 (비정상적으로 높거나 낮은 값 방지)
    if fx_rate <= 0 or fx_rate > Decimal("10000"):
        raise ValueError(f"비정상적인 환율: {fx_rate} (1~10000 범위 필요)")

    # 포지션 조회
    positions = cursor.execute(
        "SELECT asset_id, quantity, avg_price, current_price, currency "
        "FROM mock_positions WHERE quantity > 0"
    ).fetchall()

    conn.close()

    # 조회 시각
    query_time = datetime.now(UTC).isoformat()

    # 총 평가액 계산 - 확인된 값만 합산
    total_equity = cash_krw
    equity_complete = True
    equity_parts: list[tuple[str, Decimal | None]] = []
    position_objects: list[PortfolioPosition] = []
    total_unrealized = Decimal("0")

    # KRW 현금
    equity_parts.append(("KRW 현금", cash_krw))

    # USD 현금 환산
    if cash_usd is not None:
        usd_krw = cash_usd * fx_rate
        total_equity += usd_krw
        equity_parts.append((f"USD 현금 ({fx_rate:,.0f} KRW/USD)", usd_krw))
    else:
        equity_complete = False
        equity_parts.append(("USD 현금", None))

    for pos in positions:
        asset_id = pos["asset_id"]
        qty = Decimal(pos["quantity"])
        avg_price = Decimal(pos["avg_price"])
        curr_price = Decimal(pos["current_price"])
        currency = pos["currency"]

        # 통화 검증
        if currency not in ("KRW", "USD"):
            raise ValueError(f"지원하지 않는 통화: {currency} (KRW/USD만 지원)")

        market_value = qty * curr_price
        if currency == "USD":
            market_value_krw = market_value * fx_rate
            currency_label = f"USD ({fx_rate:,.0f} KRW/USD)"
        else:
            market_value_krw = market_value
            currency_label = "KRW"

        unrealized = qty * (curr_price - avg_price)
        if currency == "USD":
            unrealized_krw = unrealized * fx_rate
        else:
            unrealized_krw = unrealized

        total_equity += market_value_krw
        total_unrealized += unrealized_krw
        equity_parts.append((f"{asset_id} 평가액 ({currency_label})", market_value_krw))

        # 원본 Decimal 데이터 저장 (스냅샷 저장용)
        position_objects.append(PortfolioPosition(
            asset_id=asset_id,
            quantity=qty,
            avg_price=avg_price,
            current_price=curr_price,
            currency=currency,
            market_value_krw=market_value_krw,
            unrealized_krw=unrealized_krw,
        ))

    return PortfolioValuation(
        timestamp=query_time,
        db_updated_at=db_updated_at,
        cash_krw=cash_krw,
        cash_usd=cash_usd,
        fx_rate=fx_rate,
        total_equity=total_equity,
        equity_complete=equity_complete,
        equity_parts=equity_parts,
        positions=position_objects,  # type: ignore[arg-type]
        unrealized_pnl=total_unrealized,
    )


