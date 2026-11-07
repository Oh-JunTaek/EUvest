"""시장 데이터 모듈 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

import pytest

from invest_agent.market.market_data import (
    MARKET_TRADING_HOURS,
    OHLCV,
    AssetType,
    Currency,
    Market,
    Quote,
    get_lot_size,
    normalize_asset_id,
    parse_asset_id,
    round_price,
    to_market_time,
    to_utc,
    validate_quantity,
)


class TestMarketDataEnums:
    def test_market_enum(self):
        assert Market.KRX == "KRX"
        assert Market.US == "US"
    def test_asset_type_enum(self):
        assert AssetType.STOCK == "STOCK"
        assert AssetType.ETF == "ETF"
        assert AssetType.LEVERAGED_ETF == "LEVERAGED_ETF"
        assert AssetType.INVERSE_ETF == "INVERSE_ETF"
        assert AssetType.DERIVATIVE == "DERIVATIVE"
    def test_currency_enum(self):
        assert Currency.KRW == "KRW"
        assert Currency.USD == "USD"


class TestTradingHours:
    def test_krx_trading_hours(self):
        hours = MARKET_TRADING_HOURS[Market.KRX]
        assert hours.market_open == time(9, 0)
        assert hours.market_close == time(15, 30)
        assert hours.is_trading_time(time(9, 0)) is True
        assert hours.is_trading_time(time(10, 0)) is True
        assert hours.is_trading_time(time(15, 29)) is True
        assert hours.is_trading_time(time(15, 30)) is False
        assert hours.is_trading_time(time(8, 59)) is False
    def test_us_trading_hours(self):
        hours = MARKET_TRADING_HOURS[Market.US]
        assert hours.market_open == time(9, 30)
        assert hours.market_close == time(16, 0)
        assert hours.is_trading_time(time(9, 30)) is True
        assert hours.is_trading_time(time(15, 59)) is True
        assert hours.is_trading_time(time(16, 0)) is False

class TestLotSize:
    def test_krx_lot_size(self):
        lot = get_lot_size(Market.KRX, AssetType.STOCK)
        assert lot.min_quantity == 1
        assert lot.lot_size == 1
        assert lot.validate_quantity(1) is True
        assert lot.validate_quantity(100) is True
    def test_us_lot_size(self):
        lot = get_lot_size(Market.US, AssetType.STOCK)
        assert lot.min_quantity == 1
        assert lot.lot_size == 1
        assert lot.validate_quantity(1) is True
        assert lot.validate_quantity(10) is True
    def test_validate_quantity_function(self):
        assert validate_quantity(Market.KRX, AssetType.STOCK, 100) is True

class TestPriceTick:
    def test_krx_price_tick_rounding(self):
        assert round_price(Market.KRX, Decimal('3000')) == Decimal('3000')
        assert round_price(Market.KRX, Decimal('7002')) == Decimal('7000')
        assert round_price(Market.KRX, Decimal('7003')) == Decimal('7000')
        assert round_price(Market.KRX, Decimal('7008')) == Decimal('7010')
        assert round_price(Market.KRX, Decimal('30005')) == Decimal('30000')
        assert round_price(Market.KRX, Decimal('30026')) == Decimal('30050')
    def test_us_price_tick_rounding(self):
        assert round_price(Market.US, Decimal('0.50005')) == Decimal('0.5001')
        assert round_price(Market.US, Decimal('150.005')) == Decimal('150.01')
        assert round_price(Market.US, Decimal('150.004')) == Decimal('150.00')
    def test_round_price_direction(self):
        assert round_price(Market.KRX, Decimal('7002'), 'up') == Decimal('7010')
        assert round_price(Market.KRX, Decimal('7003'), 'down') == Decimal('7000')


class TestOHLCV:
    def test_ohlcv_creation(self):
        ohlcv = OHLCV(
            timestamp=datetime(2024, 1, 1, 9, 0),
            open=Decimal('70000'),
            high=Decimal('71000'),
            low=Decimal('69500'),
            close=Decimal('70500'),
            volume=1000000,
            asset_id='KRX:005930',
            market=Market.KRX,
        )
        assert ohlcv.asset_id == 'KRX:005930'
        assert ohlcv.market == Market.KRX
    def test_ohlcv_validation(self):
        ohlcv = OHLCV(
            timestamp=datetime.now(),
            open=Decimal('70000'),
            high=Decimal('71000'),
            low=Decimal('69500'),
            close=Decimal('70500'),
            volume=1000000,
            asset_id='KRX:005930',
            market=Market.KRX,
        )
        assert ohlcv.is_valid() is True
        ohlcv_invalid = OHLCV(
            timestamp=datetime.now(),
            open=Decimal('70000'),
            high=Decimal('69000'),
            low=Decimal('69500'),
            close=Decimal('70500'),
            volume=1000000,
            asset_id='KRX:005930',
            market=Market.KRX,
        )
        assert ohlcv_invalid.is_valid() is False
    def test_typical_price(self):
        ohlcv = OHLCV(
            timestamp=datetime.now(),
            open=Decimal('70000'),
            high=Decimal('71000'),
            low=Decimal('69500'),
            close=Decimal('70500'),
            volume=1000000,
            asset_id='KRX:005930',
            market=Market.KRX,
        )
        expected = (Decimal('71000') + Decimal('69500') + Decimal('70500')) / Decimal('3')
        assert ohlcv.typical_price() == expected
    def test_vwap_price(self):
        ohlcv = OHLCV(
            timestamp=datetime.now(),
            open=Decimal('70000'),
            high=Decimal('71000'),
            low=Decimal('69500'),
            close=Decimal('70500'),
            volume=1000000,
            asset_id='KRX:005930',
            market=Market.KRX,
        )
        expected = (Decimal('70000') + Decimal('71000') + Decimal('69500') + Decimal('70500')) / Decimal('4')
        assert ohlcv.vwap_price() == expected

class TestQuote:
    def test_quote_spread(self):
        quote = Quote(
            asset_id='KRX:005930',
            market=Market.KRX,
            price=Decimal('70000'),
            bid=Decimal('69990'),
            ask=Decimal('70010'),
            bid_size=100,
            ask_size=200,
            volume=1000000,
            timestamp=datetime.now(),
        )
        assert quote.spread() == Decimal('20')
        assert quote.mid_price() == Decimal('70000')
    def test_quote_without_bid_ask(self):
        quote = Quote(
            asset_id='KRX:005930',
            market=Market.KRX,
            price=Decimal('70000'),
            bid=None,
            ask=None,
            bid_size=None,
            ask_size=None,
            volume=1000000,
            timestamp=datetime.now(),
        )
        assert quote.spread() is None
        assert quote.mid_price() == Decimal('70000')

class TestAssetIdNormalization:
    def test_normalize_krx(self):
        assert normalize_asset_id('005930', Market.KRX) == 'KRX:005930'
        assert normalize_asset_id('5930', Market.KRX) == 'KRX:005930'
        assert normalize_asset_id('KRX:005930', Market.KRX) == 'KRX:005930'
    def test_normalize_us(self):
        assert normalize_asset_id('AAPL', Market.US) == 'US:AAPL'
        assert normalize_asset_id('US:AAPL', Market.US) == 'US:AAPL'
        assert normalize_asset_id('tsla', Market.US) == 'US:TSLA'
    def test_parse_asset_id(self):
        market, symbol = parse_asset_id('KRX:005930')
        assert market == Market.KRX
        assert symbol == '005930'
        market, symbol = parse_asset_id('US:AAPL')
        assert market == Market.US
        assert symbol == 'AAPL'
    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            parse_asset_id('INVALID')

class TestTimeConversion:
    def test_to_market_time(self):
        utc_dt = datetime(2024, 1, 1, 0, 0, tzinfo=__import__('datetime').timezone.utc)
        krx_dt = to_market_time(utc_dt, Market.KRX)
        assert krx_dt.hour == 9
    def test_to_utc(self):
        krx_dt = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
        utc_dt = to_utc(krx_dt, Market.KRX)
        assert utc_dt.tzinfo is not None

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
