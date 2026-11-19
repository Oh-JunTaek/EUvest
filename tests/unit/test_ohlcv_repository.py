"""OHLCVRepository 단위 테스트.

임시 SQLite DB를 사용해 OHLCV 저장/조회/삭제 기능을 검증한다.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from invest_agent.market.market_data import OHLCV, Market
from invest_agent.storage.repositories import OHLCVRepository
from invest_agent.storage.schema import ensure_db, get_schema_version


class TestOHLCVRepository:
    """OHLCVRepository 단위 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        ensure_db(self.db_path)
        self.repo = OHLCVRepository(self.db_path)

    def teardown_method(self):
        if self.db_path.exists():
            self.db_path.unlink()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_ohlcv(self, asset_id: str = "KRX:005930", market: Market = Market.KRX, date: str = "2024-01-02") -> OHLCV:
        return OHLCV(
            timestamp=datetime.fromisoformat(date).replace(tzinfo=UTC),
            open=Decimal("78200"),
            high=Decimal("79000"),
            low=Decimal("77500"),
            close=Decimal("78500"),
            volume=1000000,
            asset_id=asset_id,
            market=market,
        )

    def test_save_and_get_single(self):
        """단일 OHLCV 저장 및 조회."""
        ohlcv = self._make_ohlcv()
        self.repo.save(ohlcv, provider="FinanceDataReader")

        retrieved = self.repo.get("KRX:005930", "2024-01-02", "FinanceDataReader")
        assert retrieved is not None
        assert retrieved.asset_id == "KRX:005930"
        assert retrieved.market == Market.KRX
        assert retrieved.open == Decimal("78200")
        assert retrieved.high == Decimal("79000")
        assert retrieved.low == Decimal("77500")
        assert retrieved.close == Decimal("78500")
        assert retrieved.volume == 1000000
        assert retrieved.timestamp.date().isoformat() == "2024-01-02"

    def test_save_batch(self):
        """배치 저장."""
        ohlcv_list = [
            self._make_ohlcv(date="2024-01-02"),
            self._make_ohlcv(date="2024-01-03"),
            self._make_ohlcv(date="2024-01-04"),
        ]
        saved = self.repo.save_batch(ohlcv_list, provider="FinanceDataReader")
        assert saved == 3

        for date in ["2024-01-02", "2024-01-03", "2024-01-04"]:
            retrieved = self.repo.get("KRX:005930", date, "FinanceDataReader")
            assert retrieved is not None
            assert retrieved.timestamp.date().isoformat() == date

    def test_upsert_prevents_duplicates(self):
        """동일 키로 UPSERT 시 중복 방지."""
        ohlcv1 = self._make_ohlcv(date="2024-01-02")
        ohlcv1_modified = OHLCV(
            timestamp=datetime.fromisoformat("2024-01-02").replace(tzinfo=UTC),
            open=Decimal("80000"),
            high=Decimal("81000"),
            low=Decimal("79000"),
            close=Decimal("80500"),
            volume=2000000,
            asset_id="KRX:005930",
            market=Market.KRX,
        )

        self.repo.save(ohlcv1, provider="FinanceDataReader")
        self.repo.save(ohlcv1_modified, provider="FinanceDataReader")

        retrieved = self.repo.get("KRX:005930", "2024-01-02", "FinanceDataReader")
        assert retrieved is not None
        assert retrieved.open == Decimal("80000")
        assert retrieved.volume == 2000000

    def test_get_range(self):
        """날짜 범위 조회."""
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
        for d in dates:
            self.repo.save(self._make_ohlcv(date=d), provider="FinanceDataReader")

        result = self.repo.get_range("KRX:005930", "2024-01-01", "2024-01-31", "FinanceDataReader")
        assert len(result) == 5
        assert result[0].timestamp.date().isoformat() == "2024-01-08"

        result = self.repo.get_range("KRX:005930", "2024-01-03", "2024-01-05", "FinanceDataReader")
        assert len(result) == 3
        assert result[0].timestamp.date().isoformat() == "2024-01-05"

    def test_get_latest(self):
        """최신 OHLCV 조회."""
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        for d in dates:
            self.repo.save(self._make_ohlcv(date=d), provider="FinanceDataReader")

        latest = self.repo.get_latest("KRX:005930", "FinanceDataReader")
        assert latest is not None
        assert latest.timestamp.date().isoformat() == "2024-01-04"

        latest = self.repo.get_latest("KRX:005930")
        assert latest is not None
        assert latest.timestamp.date().isoformat() == "2024-01-04"

    def test_get_providers(self):
        """공급자 목록 조회."""
        self.repo.save(self._make_ohlcv(date="2024-01-02"), provider="FinanceDataReader")
        self.repo.save(self._make_ohlcv(date="2024-01-02"), provider="KIS")
        self.repo.save(self._make_ohlcv(date="2024-01-03"), provider="FinanceDataReader")

        providers = self.repo.get_providers("KRX:005930")
        assert set(providers) == {"FinanceDataReader", "KIS"}

    def test_delete(self):
        """단일 삭제."""
        self.repo.save(self._make_ohlcv(date="2024-01-02"), provider="FinanceDataReader")
        self.repo.save(self._make_ohlcv(date="2024-01-03"), provider="FinanceDataReader")

        deleted = self.repo.delete("KRX:005930", "2024-01-02", "FinanceDataReader")
        assert deleted is True

        retrieved = self.repo.get("KRX:005930", "2024-01-02", "FinanceDataReader")
        assert retrieved is None

        retrieved = self.repo.get("KRX:005930", "2024-01-03", "FinanceDataReader")
        assert retrieved is not None

    def test_delete_range(self):
        """범위 삭제."""
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        for d in dates:
            self.repo.save(self._make_ohlcv(date=d), provider="FinanceDataReader")

        deleted = self.repo.delete_range("KRX:005930", "2024-01-03", "2024-01-04", "FinanceDataReader")
        assert deleted == 2

        assert self.repo.get("KRX:005930", "2024-01-03", "FinanceDataReader") is None
        assert self.repo.get("KRX:005930", "2024-01-04", "FinanceDataReader") is None
        assert self.repo.get("KRX:005930", "2024-01-02", "FinanceDataReader") is not None
        assert self.repo.get("KRX:005930", "2024-01-05", "FinanceDataReader") is not None

    def test_us_market(self):
        """US 시장 데이터 저장/조회."""
        ohlcv = OHLCV(
            timestamp=datetime.fromisoformat("2024-01-02").replace(tzinfo=UTC),
            open=Decimal("150.00"),
            high=Decimal("155.00"),
            low=Decimal("149.00"),
            close=Decimal("153.00"),
            volume=50000000,
            asset_id="US:AAPL",
            market=Market.US,
        )
        self.repo.save(ohlcv, provider="FinanceDataReader(Yahoo)")

        retrieved = self.repo.get("US:AAPL", "2024-01-02", "FinanceDataReader(Yahoo)")
        assert retrieved is not None
        assert retrieved.asset_id == "US:AAPL"
        assert retrieved.market == Market.US
        assert retrieved.open == Decimal("150.00")
        assert retrieved.close == Decimal("153.00")

    def test_decimal_precision(self):
        """Decimal 정밀도 유지 확인."""
        ohlcv = OHLCV(
            timestamp=datetime.fromisoformat("2024-01-02").replace(tzinfo=UTC),
            open=Decimal("123.456789"),
            high=Decimal("124.567890"),
            low=Decimal("122.345678"),
            close=Decimal("123.987654"),
            volume=1000000,
            asset_id="KRX:005930",
            market=Market.KRX,
        )
        self.repo.save(ohlcv, provider="FinanceDataReader")

        retrieved = self.repo.get("KRX:005930", "2024-01-02", "FinanceDataReader")
        assert retrieved is not None
        assert retrieved.open == Decimal("123.456789")
        assert retrieved.high == Decimal("124.567890")
        assert retrieved.low == Decimal("122.345678")
        assert retrieved.close == Decimal("123.987654")

    def test_nonexistent_returns_none(self):
        """존재하지 않는 데이터 조회 시 None 반환."""
        result = self.repo.get("KRX:005930", "2024-01-02", "FinanceDataReader")
        assert result is None

        result = self.repo.get_range("KRX:005930", "2024-01-01", "2024-01-31", "FinanceDataReader")
        assert result == []

        result = self.repo.get_latest("KRX:005930", "FinanceDataReader")
        assert result is None

    def test_schema_version_is_current(self):
        """마이그레이션 후 스키마 버전이 현재 버전이어야 함."""
        version = get_schema_version(self.db_path)
        from invest_agent.storage.schema import SCHEMA_VERSION
        assert version == SCHEMA_VERSION
