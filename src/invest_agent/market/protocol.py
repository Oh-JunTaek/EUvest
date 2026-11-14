"""시장 데이터 공급자 프로토콜."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from invest_agent.market.market_data import OHLCV, Market


@dataclass(frozen=True)
class OHLCVRequest:
    """OHLCV 조회 요청."""
    asset_id: str                    # 예: "KRX:005930", "US:AAPL"
    start_date: str                  # "YYYY-MM-DD"
    end_date: str                    # "YYYY-MM-DD"
    market: Market                   # KRX 또는 US


@dataclass(frozen=True)
class OHLCVResponse:
    """OHLCV 조회 응답."""
    data: list[OHLCV]                # 일봉 데이터 리스트
    source: str                      # 데이터 소스 (예: "FinanceDataReader", "KIS")
    fetched_at: datetime             # 데이터 수집 시각 (UTC)
    asset_id: str                    # 요청한 자산 ID
    start_date: str                  # 조회 시작일
    end_date: str                    # 조회 종료일


class MarketDataProviderError(Exception):
    """시장 데이터 공급자 오류."""
    pass


class MarketDataProvider(ABC):
    """시장 데이터 공급자 프로토콜."""

    @property
    @abstractmethod
    def name(self) -> str:
        """공급자 이름."""
        ...

    @abstractmethod
    def fetch_ohlcv(self, request: OHLCVRequest) -> OHLCVResponse:
        """일봉(OHLCV) 조회.

        Args:
            request: 조회 요청 (자산 ID, 시작일, 종료일, 시장)

        Returns:
            OHLCV 데이터 리스트와 메타데이터

        Raises:
            MarketDataProviderError: 조회 실패 시
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """공급자 사용 가능 여부 확인."""
        ...
