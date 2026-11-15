"""MarketContextBuilder 단위 테스트."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from invest_agent.market.context import MarketContextBuilder
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.storage.repositories import OHLCVRepository
from invest_agent.storage.schema import ensure_db


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
    from datetime import UTC, datetime
    from decimal import Decimal
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

class TestMarketContextBuilder:
    """MarketContextBuilder 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        ensure_db(self.db_path)

    def teardown_method(self):
        import gc
        import shutil
        gc.collect()
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_data(self, asset_id: str, provider: str, dates: list[str], market: Market = Market.KRX):
        """테스트 데이터 시드."""
        repo = OHLCVRepository(self.db_path)
        for i, date in enumerate(dates):
            repo.save(
                _make_ohlcv(
                    asset_id=asset_id,
                    market=market,
                    date=date,
                    open_price=str(78000 + i * 100),
                    high_price=str(79000 + i * 100),
                    low_price=str(77000 + i * 100),
                    close_price=str(78500 + i * 100),
                    volume=1000000 + i * 100000,
                ),
                provider=provider,
            )

    def test_build_basic(self):
        """기본 컨텍스트 구성."""
        self._seed_data('KRX:005930', 'TestProvider', ['2024-01-02', '2024-01-03', '2024-01-04'])

        builder = MarketContextBuilder(self.db_path)
        context = builder.build('KRX:005930')

        assert context.asset_id == 'KRX:005930'
        assert context.market == Market.KRX
        assert context.provider == 'TestProvider'
        assert context.count == 3
        assert context.last_trade_date == '2024-01-04'
        assert context.fetched_at is not None
        assert not context.is_sufficient

    def test_build_with_lookback(self):
        """lookback 옵션 테스트."""
        dates = [f'2024-01-{d:02d}' for d in range(2, 32)]
        self._seed_data('KRX:005930', 'TestProvider', dates)

        builder = MarketContextBuilder(self.db_path)
        context = builder.build('KRX:005930', lookback=20)

        assert context.count == 20
        assert context.is_sufficient
        assert context.last_trade_date == '2024-01-31'
        assert context.data_points[0].trade_date == '2024-01-31'
        assert context.data_points[-1].trade_date == '2024-01-12'

    def test_build_explicit_provider(self):
        """명시적 공급자 지정."""
        self._seed_data('KRX:005930', 'ProviderA', ['2024-01-02', '2024-01-03'])
        self._seed_data('KRX:005930', 'ProviderB', ['2024-01-04', '2024-01-05'])

        builder = MarketContextBuilder(self.db_path)

        context_a = builder.build('KRX:005930', provider='ProviderA')
        assert context_a.provider == 'ProviderA'
        assert context_a.count == 2
        assert context_a.last_trade_date == '2024-01-03'

        context_b = builder.build('KRX:005930', provider='ProviderB')
        assert context_b.provider == 'ProviderB'
        assert context_b.count == 2
        assert context_b.last_trade_date == '2024-01-05'

    def test_build_multiple_providers_requires_explicit(self):
        """여러 공급자일 때 미지정 시 에러."""
        self._seed_data('KRX:005930', 'ProviderA', ['2024-01-02'])
        self._seed_data('KRX:005930', 'ProviderB', ['2024-01-03'])

        builder = MarketContextBuilder(self.db_path)

        with pytest.raises(ValueError, match='공급자가 여러 개입니다'):
            builder.build('KRX:005930')

    def test_build_invalid_provider_raises(self):
        """존재하지 않는 공급자 지정 시 에러."""
        self._seed_data('KRX:005930', 'ProviderA', ['2024-01-02'])

        builder = MarketContextBuilder(self.db_path)

        with pytest.raises(ValueError, match='지정하신 공급자'):
            builder.build('KRX:005930', provider='NonExistent')

    def test_build_no_data_raises(self):
        """데이터 없을 때 에러."""
        builder = MarketContextBuilder(self.db_path)

        with pytest.raises(ValueError, match='저장된 데이터가 없습니다'):
            builder.build('KRX:999999')

    def test_build_us_market(self):
        """US 시장 데이터."""
        self._seed_data(
            'US:AAPL', 'TestProvider',
            ['2024-01-02', '2024-01-03'],
            market=Market.US,
        )

        builder = MarketContextBuilder(self.db_path)
        context = builder.build('US:AAPL')

        assert context.asset_id == 'US:AAPL'
        assert context.market == Market.US
        assert context.count == 2

    def test_data_points_structure(self):
        """데이터 포인트 구조 검증."""
        self._seed_data('KRX:005930', 'TestProvider', ['2024-01-02'])

        builder = MarketContextBuilder(self.db_path)
        context = builder.build('KRX:005930')

        dp = context.data_points[0]
        assert dp.trade_date == '2024-01-02'
        assert dp.open == 78000
        assert dp.high == 79000
        assert dp.low == 77000
        assert dp.close == 78500
        assert dp.volume == 1000000

    def test_to_dict(self):
        """to_dict 직렬화."""
        self._seed_data('KRX:005930', 'TestProvider', ['2024-01-02'])

        builder = MarketContextBuilder(self.db_path)
        context = builder.build('KRX:005930')

        d = context.to_dict()
        assert d['asset_id'] == 'KRX:005930'
        assert d['market'] == 'KRX'
        assert d['provider'] == 'TestProvider'
        assert len(d['data_points']) == 1
        assert d['data_points'][0]['trade_date'] == '2024-01-02'
        assert d['count'] == 1

    def test_get_available_providers(self):
        """사용 가능 공급자 목록."""
        self._seed_data('KRX:005930', 'ProviderA', ['2024-01-02'])
        self._seed_data('KRX:005930', 'ProviderB', ['2024-01-03'])

        builder = MarketContextBuilder(self.db_path)
        providers = builder.get_available_providers('KRX:005930')

        assert providers == ['ProviderA', 'ProviderB']

    def test_has_data(self):
        """데이터 존재 여부."""
        self._seed_data('KRX:005930', 'ProviderA', ['2024-01-02'])

        builder = MarketContextBuilder(self.db_path)
        assert builder.has_data('KRX:005930')
        assert builder.has_data('KRX:005930', provider='ProviderA')
        assert not builder.has_data('KRX:005930', provider='ProviderB')
        assert not builder.has_data('KRX:999999')
