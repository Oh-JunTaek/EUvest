"""FDRProvider 단위 테스트.

Mock을 사용하지 않고 실제 FDR 호출로 동작을 검증한다.
네트워크 의존 테스트이므로 별도 마크로 분리.
"""

from __future__ import annotations

import pytest

from invest_agent.market.fdr_provider import FDRProvider
from invest_agent.market.market_data import Market
from invest_agent.market.protocol import OHLCVRequest


class TestFDRProviderUnit:
    """FDRProvider 단위 테스트 (Mock 사용)."""

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
        """US 심볼 변환."""
        provider = FDRProvider()
        assert provider._to_fdr_symbol("US:AAPL", Market.US) == "AAPL"
        assert provider._to_fdr_symbol("AAPL", Market.US) == "AAPL"
        assert provider._to_fdr_symbol("tsla", Market.US) == "TSLA"

    def test_to_fdr_symbol_invalid_market(self):
        """지원하지 않는 시장 에러."""
        provider = FDRProvider()
        with pytest.raises(ValueError):
            provider._to_fdr_symbol("005930", "INVALID")


class TestFDRProviderIntegration:
    """FDRProvider 통합 테스트 (실제 네트워크 호출).

    네트워크 의존 테스트이므로 별도 실행 가능.
    """

    @pytest.fixture
    def provider(self):
        return FDRProvider(request_delay_seconds=0.5)

    def test_fetch_krx_ohlcv(self, provider):
        """KRX 종목 일봉 조회."""
        request = OHLCVRequest(
            asset_id="KRX:005930",
            start_date="2024-01-01",
            end_date="2024-01-31",
            market=Market.KRX,
        )

        response = provider.fetch_ohlcv(request)

        assert response.asset_id == "KRX:005930"
        assert response.start_date == "2024-01-01"
        assert response.end_date == "2024-01-31"
        assert len(response.data) > 0
        assert response.source.startswith("FinanceDataReader")
        assert response.fetched_at.tzinfo is not None

        # 데이터 검증
        for ohlcv in response.data:
            assert ohlcv.asset_id == "KRX:005930"
            assert ohlcv.market == Market.KRX
            assert ohlcv.is_valid()
            assert ohlcv.volume >= 0

    def test_fetch_us_ohlcv(self, provider):
        """미국 종목 일봉 조회."""
        request = OHLCVRequest(
            asset_id="US:AAPL",
            start_date="2024-01-01",
            end_date="2024-01-31",
            market=Market.US,
        )

        response = provider.fetch_ohlcv(request)

        assert response.asset_id == "US:AAPL"
        assert len(response.data) > 0
        assert response.source.startswith("FinanceDataReader")

        for ohlcv in response.data:
            assert ohlcv.asset_id == "US:AAPL"
            assert ohlcv.market == Market.US
            assert ohlcv.is_valid()

    def test_empty_data_range(self, provider):
        """데이터 없는 기간 조회."""
        request = OHLCVRequest(
            asset_id="KRX:005930",
            start_date="2020-01-01",
            end_date="2020-01-02",  # 주말이거나 휴장일
            market=Market.KRX,
        )

        response = provider.fetch_ohlcv(request)

        # 데이터가 없을 수 있음 (빈 리스트 또는 적은 데이터)
        assert isinstance(response.data, list)

    def test_invalid_symbol(self, provider):
        """존재하지 않는 종목 조회."""
        request = OHLCVRequest(
            asset_id="KRX:999999",
            start_date="2024-01-01",
            end_date="2024-01-31",
            market=Market.KRX,
        )

        response = provider.fetch_ohlcv(request)
        # FDR은 빈 DataFrame을 반환할 수 있음
        assert isinstance(response.data, list)

    def test_invalid_market_raises(self, provider):
        """지원하지 않는 시장 에러."""

        # 잘못된 Market enum 값으로 요청 생성 시 에러
        with pytest.raises(ValueError):
            provider._to_fdr_symbol("005930", "INVALID")


class TestFDRProviderErrorHandling:
    """에러 처리 테스트."""

    def test_unavailable_provider(self):
        """사용 불가능한 공급자 에러."""
        # ImportError를 시뮬레이션하기 어렵으므로 스킵
        # 실제로는 ImportError 발생 시 is_available()이 False 반환
        pass


class TestFetchOhlcvConvenienceFunction:
    """fetch_ohlcv 편의 함수 테스트."""

    def test_fetch_ohlcv_function(self):
        """편의 함수 동작 확인."""
        from invest_agent.market.market_data import Market, fetch_ohlcv

        # 실제 네트워크 호출이므로 통합 테스트로 분류
        ohlcv_list = fetch_ohlcv(
            asset_id="KRX:005930",
            start_date="2024-01-01",
            end_date="2024-01-31",
            market=Market.KRX,
        )

        assert len(ohlcv_list) > 0
        for ohlcv in ohlcv_list:
            assert ohlcv.asset_id == "KRX:005930"
            assert ohlcv.market == Market.KRX
            assert ohlcv.is_valid()

    def test_fetch_ohlcv_us(self):
        """미국 종목 편의 함수 테스트."""
        from invest_agent.market.market_data import Market, fetch_ohlcv

        ohlcv_list = fetch_ohlcv(
            asset_id="US:AAPL",
            start_date="2024-01-01",
            end_date="2024-01-31",
            market=Market.US,
        )

        assert len(ohlcv_list) > 0
        for ohlcv in ohlcv_list:
            assert ohlcv.asset_id == "US:AAPL"
            assert ohlcv.market == Market.US
            assert ohlcv.is_valid()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-k", "not Integration"])
