"""OHLCV 수집·저장 서비스.

FDRProvider로 일봉을 조회하고 OHLCVRepository에 저장한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from invest_agent.market.fdr_provider import create_fdr_provider
from invest_agent.market.market_data import Market
from invest_agent.market.protocol import MarketDataProvider, MarketDataProviderError, OHLCVRequest
from invest_agent.storage.repositories import OHLCVRepository


@dataclass(frozen=True)
class IngestionResult:
    """수집·저장 결과."""
    asset_id: str
    market: Market
    start_date: str
    end_date: str
    provider: str
    fetched_count: int          # FDR에서 조회된 행 수
    saved_count: int            # DB에 저장된/업데이트된 행 수
    fetched_at: datetime        # 데이터 수집 시각
    error: str | None = None    # 에러 메시지 (실패 시)


class OHLCVIngestionService:
    """OHLCV 수집·저장 서비스.

    FDRProvider로 데이터를 조회하고 OHLCVRepository에 저장한다.
    """

    def __init__(
        self,
        db_path: str | Path,
        provider: MarketDataProvider | None = None,
    ) -> None:
        """초기화.

        Args:
            db_path: SQLite DB 경로
            provider: 시장 데이터 공급자 (None이면 기본 FDRProvider 사용)
        """
        self.db_path = Path(db_path)
        self.provider = provider or create_fdr_provider()
        self.repository = OHLCVRepository(self.db_path)

    def ingest(
        self,
        asset_id: str,
        market: Market,
        start_date: str,
        end_date: str,
    ) -> IngestionResult:
        """일봉 데이터 수집 및 저장.

        Args:
            asset_id: 자산 ID (예: "KRX:005930", "US:AAPL")
            market: 시장 (KRX 또는 US)
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)

        Returns:
            수집·저장 결과
        """
        # 공급자 사용 가능 여부 확인
        if not self.provider.is_available():
            return IngestionResult(
                asset_id=asset_id,
                market=market,
                start_date=start_date,
                end_date=end_date,
                provider=self.provider.name,
                fetched_count=0,
                saved_count=0,
                fetched_at=datetime.now(UTC),
                error=f"공급자 {self.provider.name}을(를) 사용할 수 없습니다.",
            )

        request = OHLCVRequest(
            asset_id=asset_id,
            start_date=start_date,
            end_date=end_date,
            market=market,
        )

        try:
            response = self.provider.fetch_ohlcv(request)
        except MarketDataProviderError as e:
            return IngestionResult(
                asset_id=asset_id,
                market=market,
                start_date=start_date,
                end_date=end_date,
                provider=self.provider.name,
                fetched_count=0,
                saved_count=0,
                fetched_at=datetime.now(UTC),
                error=str(e),
            )

        ohlcv_list = response.data
        fetched_count = len(ohlcv_list)

        # 빈 응답인 경우 저장하지 않고 기존 데이터 유지
        if fetched_count == 0:
            return IngestionResult(
                asset_id=asset_id,
                market=market,
                start_date=start_date,
                end_date=end_date,
                provider=response.source,
                fetched_count=0,
                saved_count=0,
                fetched_at=response.fetched_at,
                error=None,
            )

        # 배치 저장 (UPSERT로 중복 방지)
        saved_count = self.repository.save_batch(
            ohlcv_list=ohlcv_list,
            provider=response.source,
            fetched_at=response.fetched_at,
        )

        return IngestionResult(
            asset_id=asset_id,
            market=market,
            start_date=start_date,
            end_date=end_date,
            provider=response.source,
            fetched_count=fetched_count,
            saved_count=saved_count,
            fetched_at=response.fetched_at,
            error=None,
        )

    def ingest_multiple(
        self,
        requests: list[tuple[str, Market, str, str]],
    ) -> list[IngestionResult]:
        """여러 자산에 대해 일괄 수집·저장.

        Args:
            requests: (asset_id, market, start_date, end_date) 튜플 리스트

        Returns:
            각 자산별 수집·저장 결과 리스트
        """
        results = []
        for asset_id, market, start_date, end_date in requests:
            result = self.ingest(asset_id, market, start_date, end_date)
            results.append(result)
        return results
