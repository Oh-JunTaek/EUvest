"""FDRProvider 단위 테스트.

Mock DataFrame을 사용해 네트워크 없이 KRW/USD OHLCV 변환, 빈 응답, 예외 처리를 검증한다.
네트워크 의존 테스트는 integration_network 마크로 분리.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from invest_agent.market.fdr_provider import FDRProvider, create_fdr_provider
from invest_agent.market.market_data import Market
from invest_agent.market.protocol import MarketDataProviderError, OHLCVRequest


class TestFDRProviderUnit:
    """FDRProvider 단위 테스트 (Mock 사용, 네트워크 없음)."""

    def test_name_property(self):
        """공급자 이름 확인."""
        provider = FDRProvider()
        assert provider.name == "FinanceDataReader"

    def test_is_available(self):
        """사용 가능 여부 확인."""
        provider = FDRProvider()
        assert provider.is_available() is True

    def test_to_fdr_symbol_krx(self):
        """KRX 심볼 변환."""
        provider = FDRProvider()
        assert provider._to_fdr_symbol("KRX:005930", Market.KRX) == "005930"
        assert provider._to_fdr_symbol("005930", Market.KRX) == "005930"
        assert provider._to_fdr_symbol("5930", Market.KRX) == "005930"

    def test_to_fdr_symbol_us(self):
        """US 심볼 변환 (대문자 정규화)."""
        provider = FDRProvider()
        assert provider._to_fdr_symbol("US:AAPL", Market.US) == "AAPL"
        assert provider._to_fdr_symbol("AAPL", Market.US) == "AAPL"
        assert provider._to_fdr_symbol("tsla", Market.US) == "TSLA"

    def test_to_fdr_symbol_invalid_market(self):
        """지원하지 않는 시장 에러."""
        provider = FDRProvider()
        with pytest.raises(ValueError):
            provider._to_fdr_symbol("005930", "INVALID")

    def test_convert_to_ohlcv_krx(self):
        """KRX DataFrame을 OHLCV 리스트로 변환."""
        provider = FDRProvider()
        df = pd.DataFrame({
            "Open": [78200, 78500],
            "High": [79000, 79200],
            "Low": [77500, 78000],
            "Close": [78500, 78800],
            "Volume": [1000000, 1200000],
            "Change": [0.01, -0.02],
        }, index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"]))

        ohlcv_list = provider._convert_to_ohlcv(df, "KRX:005930", Market.KRX)

        assert len(ohlcv_list) == 2
        for ohlcv in ohlcv_list:
            assert ohlcv.asset_id == "KRX:005930"
            assert ohlcv.market == Market.KRX
            assert ohlcv.is_valid()
            assert ohlcv.volume >= 0
            assert ohlcv.timestamp.tzinfo is not None

    def test_convert_to_ohlcv_us(self):
        """US DataFrame을 OHLCV 리스트로 변환."""
        provider = FDRProvider()
        df = pd.DataFrame({
            "Open": [150.0, 152.0],
            "High": [155.0, 158.0],
            "Low": [149.0, 151.0],
            "Close": [153.0, 156.0],
            "Volume": [50000000, 60000000],
            "Change": [0.02, 0.01],
        }, index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"]))

        ohlcv_list = provider._convert_to_ohlcv(df, "US:AAPL", Market.US)

        assert len(ohlcv_list) == 2
        for ohlcv in ohlcv_list:
            assert ohlcv.asset_id == "US:AAPL"
            assert ohlcv.market == Market.US
            assert ohlcv.is_valid()

    def test_convert_to_ohlcv_empty(self):
        """빈 DataFrame 처리."""
        provider = FDRProvider()
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume", "Change"])

        result = provider._convert_to_ohlcv(df, "KRX:005930", Market.KRX)
        assert result == []

    def test_convert_to_ohlcv_invalid_rows(self):
        """잘못된 행이 포함된 DataFrame 처리 (건너뛰기)."""
        provider = FDRProvider()
        df = pd.DataFrame({
            "Open": [78200, "invalid"],
            "High": [79000, 79200],
            "Low": [77500, 78000],
            "Close": [78500, 78800],
            "Volume": [1000000, 1200000],
            "Change": [0.01, -0.02],
        }, index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"]))

        ohlcv_list = provider._convert_to_ohlcv(df, "KRX:005930", Market.KRX)
        # 유효한 행만 포함
        assert len(ohlcv_list) == 1

    def test_fetch_ohlcv_unavailable(self):
        """사용 불가능한 공급자 에러."""
        provider = FDRProvider()
        with patch.object(provider, "is_available", return_value=False):
            request = OHLCVRequest(
                asset_id="KRX:005930",
                start_date="2024-01-01",
                end_date="2024-01-31",
                market=Market.KRX,
            )
            with pytest.raises(MarketDataProviderError, match="FinanceDataReader를 사용할 수 없습니다"):
                provider.fetch_ohlcv(request)

    def test_fetch_ohlcv_network_error(self):
        """네트워크 에러 시 MarketDataProviderError 발생."""
        provider = FDRProvider()
        with patch.object(provider, "_fetch_with_retry", side_effect=Exception("Network error")):
            request = OHLCVRequest(
                asset_id="KRX:005930",
                start_date="2024-01-01",
                end_date="2024-01-31",
                market=Market.KRX,
            )
            with pytest.raises(MarketDataProviderError, match="FDR 조회 실패"):
                provider.fetch_ohlcv(request)

    def test_create_fdr_provider_factory(self):
        """팩토리 함수 동작 확인."""
        provider = create_fdr_provider(request_delay_seconds=0.5, timeout_seconds=10)
        assert isinstance(provider, FDRProvider)
        assert provider._request_delay == 0.5
        assert provider._timeout == 10

    def test_timeout_parameter_stored_but_unused(self):
        """timeout_seconds는 저장되나 FDR 자체는 타임아웃 미지원(문서화)."""
        provider = FDRProvider(timeout_seconds=10)
        assert provider._timeout == 10
        # 현재 구현에서 timeout은 저장만 되고 실제 요청 타임아웃에는 미사용
        # 향후 확장 시 활용 가능
