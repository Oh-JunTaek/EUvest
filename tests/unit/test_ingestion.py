"""OHLCV 수집·저장 서비스 통합 테스트.

MockProvider를 사용해 네트워크 없이 수집·저장 파이프라인 검증.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from invest_agent.market.ingestion import OHLCVIngestionService
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.market.protocol import (
    MarketDataProvider,
    MarketDataProviderError,
    OHLCVRequest,
    OHLCVResponse,
)
from invest_agent.storage.repositories import OHLCVRepository
from invest_agent.storage.schema import ensure_db


@dataclass(frozen=True)
class MockProviderConfig:
    """MockProvider 설정."""
    should_fail: bool = False
    error_message: str = "Mock error"
    ohlcv_data: list[OHLCV] | None = None
    source: str = "MockProvider"
    available: bool = True


class MockProvider(MarketDataProvider):
    """테스트용 Mock 시장 데이터 공급자."""

    def __init__(self, config: MockProviderConfig | None = None) -> None:
        self.config = config or MockProviderConfig()
        self.call_count = 0
        self.last_request: OHLCVRequest | None = None

    @property
    def name(self) -> str:
        return "MockProvider"

    def is_available(self) -> bool:
        return self.config.available

    def fetch_ohlcv(self, request: OHLCVRequest) -> OHLCVResponse:
        self.call_count += 1
        self.last_request = request

        if self.config.should_fail:
            raise MarketDataProviderError(self.config.error_message)

        ohlcv_list = self.config.ohlcv_data or []

        return OHLCVResponse(
            data=ohlcv_list,
            source=self.config.source,
            fetched_at=datetime.now(UTC),
            asset_id=request.asset_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )


def _make_ohlcv(
    asset_id: str = "KRX:005930",
    market: Market = Market.KRX,
    date: str = "2024-01-02",
    open_price: str = "78200",
    high_price: str = "79000",
    low_price: str = "77500",
    close_price: str = "78500",
    volume: int = 1000000,
) -> OHLCV:
    return OHLCV(
        timestamp=datetime.fromisoformat(date).replace(tzinfo=UTC),
        open=Decimal(open_price),
        high=Decimal(high_price),
        low=Decimal(low_price),
        close=Decimal(close_price),
        volume=volume,
        asset_id=asset_id,
        market=market,
    )

class TestOHLCVIngestionService:
    """OHLCVIngestionService 통합 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        ensure_db(self.db_path)

    def teardown_method(self):
        # DB 연결이 닫히도록 잠시 대기 후 정리
        import gc
        gc.collect()
        import time
        time.sleep(0.1)
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass  # Windows에서 가끔 발생, 무시
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ingest_success(self):
        """정상 수집·저장."""
        ohlcv_list = [
            _make_ohlcv(date='2024-01-02'),
            _make_ohlcv(date='2024-01-03'),
            _make_ohlcv(date='2024-01-04'),
        ]
        provider = MockProvider(MockProviderConfig(ohlcv_data=ohlcv_list))
        service = OHLCVIngestionService(self.db_path, provider=provider)

        result = service.ingest('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31')

        assert result.error is None
        assert result.fetched_count == 3
        assert result.saved_count == 3
        assert result.provider == 'MockProvider'
        assert result.asset_id == 'KRX:005930'
        assert result.market == Market.KRX

        repo = OHLCVRepository(self.db_path)
        for date in ['2024-01-02', '2024-01-03', '2024-01-04']:
            saved = repo.get('KRX:005930', date, 'MockProvider')
            assert saved is not None
            assert saved.asset_id == 'KRX:005930'

    def test_ingest_empty_response_preserves_existing(self):
        """빈 응답 시 기존 데이터 유지."""
        repo = OHLCVRepository(self.db_path)
        repo.save(_make_ohlcv(date='2024-01-02'), provider='MockProvider')

        provider = MockProvider(MockProviderConfig(ohlcv_data=[]))
        service = OHLCVIngestionService(self.db_path, provider=provider)

        result = service.ingest('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31')

        assert result.error is None
        assert result.fetched_count == 0
        assert result.saved_count == 0

        saved = repo.get('KRX:005930', '2024-01-02', 'MockProvider')
        assert saved is not None
        assert saved.open == Decimal('78200')

    def test_ingest_failure_preserves_existing(self):
        """수집 실패 시 기존 데이터 유지."""
        repo = OHLCVRepository(self.db_path)
        repo.save(_make_ohlcv(date='2024-01-02'), provider='MockProvider')

        provider = MockProvider(MockProviderConfig(should_fail=True, error_message='Network error'))
        service = OHLCVIngestionService(self.db_path, provider=provider)

        result = service.ingest('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31')

        assert result.error is not None
        assert 'Network error' in result.error
        assert result.fetched_count == 0
        assert result.saved_count == 0

        saved = repo.get('KRX:005930', '2024-01-02', 'MockProvider')
        assert saved is not None

    def test_ingest_duplicate_prevention(self):
        """동일 기간 재수집 시 중복 방지 (UPSERT)."""
        ohlcv_list = [_make_ohlcv(date='2024-01-02')]
        provider = MockProvider(MockProviderConfig(ohlcv_data=ohlcv_list))
        service = OHLCVIngestionService(self.db_path, provider=provider)

        result1 = service.ingest('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31')
        assert result1.saved_count == 1

        ohlcv_modified = [_make_ohlcv(date='2024-01-02', open_price='80000', close_price='80500')]
        provider.config = MockProviderConfig(ohlcv_data=ohlcv_modified)
        result2 = service.ingest('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31')
        assert result2.saved_count == 1

        repo = OHLCVRepository(self.db_path)
        saved = repo.get('KRX:005930', '2024-01-02', 'MockProvider')
        assert saved is not None
        assert saved.open == Decimal('80000')
        assert saved.close == Decimal('80500')

    def test_ingest_us_market(self):
        """US 시장 데이터 수집·저장."""
        ohlcv = _make_ohlcv(
            asset_id='US:AAPL',
            market=Market.US,
            date='2024-01-02',
            open_price='150.00',
            high_price='155.00',
            low_price='149.00',
            close_price='153.00',
            volume=50000000,
        )
        provider = MockProvider(MockProviderConfig(ohlcv_data=[ohlcv]))
        service = OHLCVIngestionService(self.db_path, provider=provider)

        result = service.ingest('US:AAPL', Market.US, '2024-01-01', '2024-01-31')

        assert result.error is None
        assert result.fetched_count == 1
        assert result.saved_count == 1

        repo = OHLCVRepository(self.db_path)
        saved = repo.get('US:AAPL', '2024-01-02', 'MockProvider')
        assert saved is not None
        assert saved.asset_id == 'US:AAPL'
        assert saved.market == Market.US
        assert saved.open == Decimal('150.00')

    def test_ingest_multiple(self):
        """여러 자산 일괄 수집·저장."""
        ohlcv_krx = [_make_ohlcv(date='2024-01-02')]
        ohlcv_us = [_make_ohlcv(asset_id='US:AAPL', market=Market.US, date='2024-01-02', open_price='150.00', close_price='153.00')]

        class DynamicMockProvider(MockProvider):
            def fetch_ohlcv(self, request: OHLCVRequest) -> OHLCVResponse:
                self.last_request = request
                if request.asset_id == 'KRX:005930':
                    return OHLCVResponse(
                        data=ohlcv_krx,
                        source='MockProvider',
                        fetched_at=datetime.now(UTC),
                        asset_id=request.asset_id,
                        start_date=request.start_date,
                        end_date=request.end_date,
                    )
                else:
                    return OHLCVResponse(
                        data=ohlcv_us,
                        source='MockProvider',
                        fetched_at=datetime.now(UTC),
                        asset_id=request.asset_id,
                        start_date=request.start_date,
                        end_date=request.end_date,
                    )

        provider = DynamicMockProvider()
        service = OHLCVIngestionService(self.db_path, provider=provider)

        requests = [
            ('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31'),
            ('US:AAPL', Market.US, '2024-01-01', '2024-01-31'),
        ]
        results = service.ingest_multiple(requests)

        assert len(results) == 2
        assert all(r.error is None for r in results)
        assert results[0].asset_id == 'KRX:005930'
        assert results[1].asset_id == 'US:AAPL'

        repo = OHLCVRepository(self.db_path)
        assert repo.get('KRX:005930', '2024-01-02', 'MockProvider') is not None
        assert repo.get('US:AAPL', '2024-01-02', 'MockProvider') is not None

    def test_provider_unavailable(self):
        """공급자 사용 불가 시 에러 반환."""
        provider = MockProvider(MockProviderConfig(available=False))
        service = OHLCVIngestionService(self.db_path, provider=provider)

        result = service.ingest('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31')

        assert result.error is not None
        assert '사용할 수 없습니다' in result.error or 'unavailable' in result.error.lower()
        assert result.fetched_count == 0
        assert result.saved_count == 0

    def test_fetched_at_recorded(self):
        """수집 시각이 기록되는지 확인."""
        ohlcv_list = [_make_ohlcv(date='2024-01-02')]
        provider = MockProvider(MockProviderConfig(ohlcv_data=ohlcv_list))
        service = OHLCVIngestionService(self.db_path, provider=provider)

        result = service.ingest('KRX:005930', Market.KRX, '2024-01-01', '2024-01-31')

        assert result.fetched_at is not None
        assert result.fetched_at.tzinfo is not None

        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT fetched_at FROM ohlcv WHERE asset_id = ? AND trade_date = ? AND provider = ?',
                ('KRX:005930', '2024-01-02', 'MockProvider'),
            ).fetchone()
            assert row is not None
            assert row['fetched_at'] is not None
