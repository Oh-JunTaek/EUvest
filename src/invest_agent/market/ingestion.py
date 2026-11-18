"""OHLCV 수집·저장 서비스.

FDRProvider로 일봉을 조회하고 OHLCVRepository에 저장한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from invest_agent.market.context import MarketContextBuilder
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


@dataclass(frozen=True)
class RefreshResult:
    """자동 갱신 결과."""
    asset_id: str
    market: Market
    action: str                 # "refreshed", "skipped", "error"
    provider: str | None = None
    fetched_count: int = 0
    saved_count: int = 0
    error: str | None = None
    last_trade_date: str | None = None
    age_days: int | None = None
    is_fresh: bool = False
    is_sufficient: bool = False


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

    def refresh_if_needed(
        self,
        asset_id: str,
        market: Market,
        max_age_days: int = 7,
        lookback: int = 20,
        reference_date: datetime | None = None,
    ) -> RefreshResult:
        """필요 시 시장 데이터 자동 갱신.

        데이터가 없거나 오래된 경우(마지막 거래일로부터 max_age_days 초과) FDR로 갱신한다.
        이미 최신 데이터가 충분하면 갱신을 생략한다.

        Args:
            reference_date: 기준일 (None이면 현재 UTC). 테스트용 고정 기준일 지정 가능.

        Args:
            asset_id: 자산 ID (예: "KRX:005930", "US:AAPL")
            market: 시장 (KRX 또는 US)
            max_age_days: 데이터 최대 경과 일수 (기본 7일)
            lookback: 분석에 필요한 최소 데이터 개수 (기본 20개)

        Returns:
            갱신 결과 (action: "refreshed" | "skipped" | "error")
        """
        # MarketContextBuilder로 현재 데이터 상태 확인
        context_builder = MarketContextBuilder(str(self.db_path))

        try:
            context = context_builder.build(
                asset_id=asset_id,
                lookback=lookback,
                max_age_days=max_age_days,
                reference_date=reference_date,
            )
        except ValueError as e:
            # 공급자 충돌 등 명확한 오류인 경우
            if "공급자가 여러 개" in str(e):
                return RefreshResult(
                    asset_id=asset_id,
                    market=market,
                    action="error",
                    error=f"공급자 충돌: {e}. 명시적으로 공급자를 지정하세요.",
                )
            # 데이터가 없음
            context = None

        # 데이터가 없거나 오래됐는지 확인
        if context is None:
            pass  # refresh needed: 데이터 없음
        elif not context.is_fresh:
            pass  # refresh needed: 데이터 오래됨
        elif not context.is_sufficient:
            pass  # refresh needed: 데이터는 최신이지만 개수 부족
        else:
            # 데이터가 최신이고 충분하면 스킵
            return RefreshResult(
                asset_id=asset_id,
                market=market,
                action="skipped",
                provider=context.provider,
                last_trade_date=context.last_trade_date,
                age_days=context.age_days,
                is_fresh=context.is_fresh,
                is_sufficient=context.is_sufficient,
            )

        # 데이터 갱신 필요 - 끝날짜는 기준일, 시작일은 lookback+max_age_days+5일 전으로 설정
        from datetime import UTC, datetime, timedelta
        ref = reference_date or datetime.now(UTC)
        end_date = ref.date().isoformat()
        start_date = (ref.date() - timedelta(days=lookback + max_age_days + 5)).isoformat()

        try:
            ingestion_result = self.ingest(asset_id, market, start_date, end_date)

            if ingestion_result.error:
                return RefreshResult(
                    asset_id=asset_id,
                    market=market,
                    action="error",
                    provider=ingestion_result.provider,
                    error=ingestion_result.error,
                )

            if ingestion_result.saved_count == 0:
                return RefreshResult(
                    asset_id=asset_id,
                    market=market,
                    action="error",
                    provider=ingestion_result.provider,
                    error="수집된 데이터가 없거나 저장되지 않았습니다.",
                )

            # 갱신 후 데이터 상태 재확인
            try:
                updated_context = context_builder.build(
                    asset_id=asset_id,
                    lookback=lookback,
                    max_age_days=max_age_days,
                    reference_date=reference_date,
                )
                # 갱신 후에도 최신이거나 충분하지 않으면 오류
                if not updated_context.is_fresh or not updated_context.is_sufficient:
                    return RefreshResult(
                        asset_id=asset_id,
                        market=market,
                        action="error",
                        provider=updated_context.provider,
                        error=f"갱신 후에도 데이터가 최신이거나 충분하지 않습니다. (fresh={updated_context.is_fresh}, sufficient={updated_context.is_sufficient}, age_days={updated_context.age_days}, count={updated_context.count})",
                        last_trade_date=updated_context.last_trade_date,
                        age_days=updated_context.age_days,
                        is_fresh=updated_context.is_fresh,
                        is_sufficient=updated_context.is_sufficient,
                    )
                return RefreshResult(
                    asset_id=asset_id,
                    market=market,
                    action="refreshed",
                    provider=updated_context.provider,
                    fetched_count=ingestion_result.fetched_count,
                    saved_count=ingestion_result.saved_count,
                    last_trade_date=updated_context.last_trade_date,
                    age_days=updated_context.age_days,
                    is_fresh=updated_context.is_fresh,
                    is_sufficient=updated_context.is_sufficient,
                )
            except ValueError as e:
                # 갱신 후에도 데이터 조회 실패
                return RefreshResult(
                    asset_id=asset_id,
                    market=market,
                    action="error",
                    provider=ingestion_result.provider,
                    error=f"갱신 후 데이터 조회 실패: {e}",
                    fetched_count=ingestion_result.fetched_count,
                    saved_count=ingestion_result.saved_count,
                )

        except Exception as e:
            return RefreshResult(
                asset_id=asset_id,
                market=market,
                action="error",
                provider=self.provider.name,
                error=f"갱신 중 오류 발생: {e}",
            )
