"""AI 분석용 시장 데이터 컨텍스트 빌더.

저장된 OHLCV를 AI 분석에 활용할 수 있는 구조화된 데이터로 변환한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from invest_agent.market.market_data import Market
from invest_agent.storage.repositories import OHLCVRepository


@dataclass(frozen=True)
class OHLCVDataPoint:
    """단일 일봉 데이터 포인트."""
    trade_date: str          # YYYY-MM-DD
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class MarketContext:
    """AI 분석용 시장 컨텍스트."""
    asset_id: str
    market: Market
    provider: str
    data_points: list[OHLCVDataPoint]   # 최신순 (최신 데이터가 첫 번째)
    last_trade_date: str | None         # 가장 최근 거래일
    fetched_at: datetime | None         # 데이터 수집 시각 (DB 저장 시점)
    count: int                          # 데이터 포인트 수
    is_sufficient: bool                 # 분석에 충분한 데이터 여부 (기본 20개 이상)
    is_fresh: bool                      # 데이터 최신성 여부 (기본 7일 이내)
    age_days: int                       # 마지막 거래일부터 오늘까지 경과 일수

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환 (JSON 직렬화용)."""
        return {
            "asset_id": self.asset_id,
            "market": self.market.value,
            "provider": self.provider,
            "data_points": [
                {
                    "trade_date": dp.trade_date,
                    "open": str(dp.open),
                    "high": str(dp.high),
                    "low": str(dp.low),
                    "close": str(dp.close),
                    "volume": dp.volume,
                }
                for dp in self.data_points
            ],
            "last_trade_date": self.last_trade_date,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "count": self.count,
            "is_sufficient": self.is_sufficient,
            "is_fresh": self.is_fresh,
            "age_days": self.age_days,
        }


class MarketContextBuilder:
    """시장 컨텍스트 빌더.

    OHLCVRepository에서 데이터를 읽어 MarketContext를 구성한다.
    """

    DEFAULT_LOOKBACK = 20  # 기본 조회 일수
    DEFAULT_MAX_AGE_DAYS = 7  # 기본 최대 데이터 경과 일수

    def __init__(self, db_path: str | Path) -> None:
        """초기화.

        Args:
            db_path: SQLite DB 경로
        """
        self.repository = OHLCVRepository(db_path)

    @staticmethod
    def _calculate_age_days(last_trade_date: str | None, reference_date: datetime | None = None) -> int:
        """마지막 거래일로부터 경과 일수 계산.

        Args:
            last_trade_date: 마지막 거래일 (YYYY-MM-DD)
            reference_date: 기준일 (None이면 현재 UTC 날짜)

        Returns:
            경과 일수 (데이터 없으면 큰 값 반환)
        """
        if not last_trade_date:
            return 999999
        if reference_date is None:
            reference_date = datetime.now(UTC)
        try:
            last_date = datetime.fromisoformat(last_trade_date).replace(tzinfo=UTC)
            return (reference_date.date() - last_date.date()).days
        except ValueError:
            return 999999

    def build(
        self,
        asset_id: str,
        provider: str | None = None,
        lookback: int = DEFAULT_LOOKBACK,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
        reference_date: datetime | None = None,
    ) -> MarketContext:
        if max_age_days < 0:
            raise ValueError("max_age_days는 0 이상이어야 합니다.")
        """시장 컨텍스트 구성.

        Args:
            asset_id: 자산 ID (예: "KRX:005930", "US:AAPL")
            provider: 명시적 공급자 지정 (None이면 단일 공급자만 있을 때 자동 선택)
            lookback: 조회할 일봉 개수 (기본 20)

        Returns:
            MarketContext 객체

        Raises:
            ValueError: 공급자가 여러 개인데 미지정, 또는 데이터 없음
        """
        # 저장된 공급자 목록 확인
        providers = self.repository.get_providers(asset_id)

        if not providers:
            raise ValueError(f"저장된 데이터가 없습니다: {asset_id}")

        # 공급자 결정
        if provider is None:
            if len(providers) > 1:
                raise ValueError(
                    f"공급자가 여러 개입니다. 명시적으로 지정하세요: {providers}"
                )
            selected_provider = providers[0]
        else:
            if provider not in providers:
                raise ValueError(
                    f"지정하신 공급자 '{provider}'의 데이터가 없습니다. "
                    f"사용 가능한 공급자: {providers}"
                )
            selected_provider = provider

        # 데이터 조회 (최신순)
        ohlcv_list = self.repository.get_range(
            asset_id=asset_id,
            start_date="1900-01-01",
            end_date="2100-12-31",
            provider=selected_provider,
        )

        # lookback 개수만큼 제한
        ohlcv_list = ohlcv_list[:lookback]

        if not ohlcv_list:
            raise ValueError(f"조회된 데이터가 없습니다: {asset_id} ({selected_provider})")

        # 데이터 포인트 변환
        data_points = [
            OHLCVDataPoint(
                trade_date=ohlcv.timestamp.date().isoformat(),
                open=ohlcv.open,
                high=ohlcv.high,
                low=ohlcv.low,
                close=ohlcv.close,
                volume=ohlcv.volume,
            )
            for ohlcv in ohlcv_list
        ]

        # 메타데이터 구성
        last_trade_date = ohlcv_list[0].timestamp.date().isoformat() if ohlcv_list else None

        # DB에서 fetched_at 조회 (첫 번째 행의 fetched_at 사용)
        fetched_at = self._get_fetched_at(asset_id, selected_provider)

        # 최신성 판정
        if reference_date is None:
            ref_date = datetime.now(UTC)
        else:
            ref_date = reference_date
        age_days = self._calculate_age_days(last_trade_date, ref_date)
        # 미래 거래일(age_days < 0)은 최신 데이터로 인정하지 않음
        is_fresh = 0 <= age_days <= max_age_days

        return MarketContext(
            asset_id=asset_id,
            market=ohlcv_list[0].market,
            provider=selected_provider,
            data_points=data_points,
            last_trade_date=last_trade_date,
            fetched_at=fetched_at,
            count=len(data_points),
            is_sufficient=len(data_points) >= lookback,
            is_fresh=is_fresh,
            age_days=age_days,
        )

    def _get_fetched_at(self, asset_id: str, provider: str) -> datetime | None:
        """가장 최근 데이터의 fetched_at 조회."""
        import sqlite3

        with sqlite3.connect(str(self.repository.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT fetched_at FROM ohlcv WHERE asset_id = ? AND provider = ? ORDER BY trade_date DESC LIMIT 1",
                (asset_id, provider),
            ).fetchone()
            if row and row["fetched_at"]:
                return datetime.fromisoformat(row["fetched_at"])
            return None

    def get_available_providers(self, asset_id: str) -> list[str]:
        """자산에 대해 사용 가능한 공급자 목록 반환."""
        return self.repository.get_providers(asset_id)

    def has_data(self, asset_id: str, provider: str | None = None) -> bool:
        """데이터 존재 여부 확인."""
        providers = self.repository.get_providers(asset_id)
        if not providers:
            return False
        if provider is None:
            return True
        return provider in providers
