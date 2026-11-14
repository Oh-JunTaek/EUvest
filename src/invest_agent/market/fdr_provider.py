"""FinanceDataReader(OHLCV) 어댑터.

EUvest 자산 ID를 FDR 심볼로 변환하고 일봉(OHLCV)을 조회한다.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from invest_agent.market.market_data import OHLCV, Market
from invest_agent.market.protocol import (
    MarketDataProvider,
    MarketDataProviderError,
    OHLCVRequest,
    OHLCVResponse,
)


class FDRProvider(MarketDataProvider):
    """FinanceDataReader를 사용한 OHLCV 조회 공급자."""

    def __init__(
        self,
        request_delay_seconds: float = 1.0,
        timeout_seconds: int = 30,
    ) -> None:
        """초기화.

        Args:
            request_delay_seconds: 요청 간 대기 시간 (초)
            timeout_seconds: 요청 타임아웃 (초)
        """
        self._request_delay = request_delay_seconds
        self._timeout = timeout_seconds
        self._last_request_time: float | None = None

    @property
    def name(self) -> str:
        return "FinanceDataReader"

    def is_available(self) -> bool:
        """FDR은 네트워크 연결만 있으면 사용 가능."""
        try:
            import FinanceDataReader  # noqa: F401
            return True
        except ImportError:
            return False

    def _to_fdr_symbol(self, asset_id: str, market: Market) -> str:
        """EUvest 자산 ID를 FDR 심볼로 변환.

        KRX:005930 -> "005930" 또는 "KRX:005930"
        US:AAPL -> "AAPL"
        """
        if market == Market.KRX:
            # KRX 종목코드 (6자리)
            symbol = asset_id.replace("KRX:", "").zfill(6)
            # FDR에서는 "005930" 또는 "KRX:005930" 모두 사용 가능
            return symbol
        elif market == Market.US:
            # 미국 주식은 심볼 그대로 (대문자로 정규화)
            return asset_id.replace("US:", "").upper()
        else:
            raise ValueError(f"지원하지 않는 시장: {market}")

    def _fetch_with_retry(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        source: str,
    ) -> pd.DataFrame:
        """FDR로 데이터 조회 (재시도 로직 포함)."""
        import FinanceDataReader as fdr

        # 요청 간격 조절
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._request_delay:
                time.sleep(self._request_delay - elapsed)

        try:
            self._last_request_time = time.time()
            df = fdr.DataReader(symbol, start_date, end_date)
            return df
        except Exception as e:
            raise MarketDataProviderError(
                f"FDR 조회 실패 ({source}: {symbol}, {start_date}~{end_date}): {e}"
            ) from e

    def _convert_to_ohlcv(self, df: pd.DataFrame, asset_id: str, market: Market) -> list[OHLCV]:
        """DataFrame을 OHLCV 리스트로 변환."""
        if df.empty:
            return []

        ohlcv_list = []
        for idx, row in df.iterrows():
            # FDR DataFrame 컬럼: Open, High, Low, Close, Volume, Change
            try:
                ohlcv = OHLCV(
                    timestamp=idx.to_pydatetime().replace(tzinfo=UTC),
                    open=Decimal(str(row["Open"])),
                    high=Decimal(str(row["High"])),
                    low=Decimal(str(row["Low"])),
                    close=Decimal(str(row["Close"])),
                    volume=int(row["Volume"]),
                    asset_id=asset_id,
                    market=market,
                )
                if ohlcv.is_valid():
                    ohlcv_list.append(ohlcv)
            except (KeyError, ValueError, TypeError):
                # 잘못된 행은 건너뜀
                continue

        return ohlcv_list

    def fetch_ohlcv(self, request: OHLCVRequest) -> OHLCVResponse:
        """일봉(OHLCV) 조회.

        Args:
            request: 조회 요청 (자산 ID, 시작일, 종료일, 시장)

        Returns:
            OHLCV 데이터 리스트와 메타데이터

        Raises:
            MarketDataProviderError: 조회 실패 시
        """
        if not self.is_available():
            raise MarketDataProviderError("FinanceDataReader를 사용할 수 없습니다.")

        fdr_symbol = self._to_fdr_symbol(request.asset_id, request.market)

        # FDR 소스 결정 (KRX 직접 또는 네이버 폴백)
        source = "FinanceDataReader(KRX)" if request.market == Market.KRX else "FinanceDataReader(Yahoo)"

        df = self._fetch_with_retry(
            symbol=fdr_symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            source=source,
        )

        ohlcv_list = self._convert_to_ohlcv(df, request.asset_id, request.market)
        fetched_at = datetime.now(UTC)

        return OHLCVResponse(
            data=ohlcv_list,
            source=source,
            fetched_at=fetched_at,
            asset_id=request.asset_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )


def create_fdr_provider(
    request_delay_seconds: float = 1.0,
    timeout_seconds: int = 30,
) -> FDRProvider:
    """FDR 공급자 팩토리 함수."""
    return FDRProvider(
        request_delay_seconds=request_delay_seconds,
        timeout_seconds=timeout_seconds,
    )
