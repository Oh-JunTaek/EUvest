"""시장 데이터 공급자 팩토리."""

from __future__ import annotations

from invest_agent.market.fdr_provider import create_fdr_provider
from invest_agent.market.protocol import MarketDataProvider
from invest_agent.settings import MarketDataConfig, get_settings


def create_market_data_provider(config: MarketDataConfig | None = None) -> MarketDataProvider:
    """설정에 따른 시장 데이터 공급자 생성.

    Args:
        config: 시장 데이터 설정 (None이면 전역 설정 사용)

    Returns:
        시장 데이터 공급자 인스턴스

    Raises:
        ValueError: 지원하지 않는 공급자 타입
    """
    if config is None:
        config = get_settings().market_data

    provider_type = config.provider.lower()

    if provider_type == "fdr":
        return create_fdr_provider(
            request_delay_seconds=config.fdr_request_delay_seconds,
            timeout_seconds=config.fdr_timeout_seconds,
        )
    elif provider_type == "kis":
        # TODO: KIS 공급자 구현 시 추가
        raise NotImplementedError("KIS 공급자는 아직 구현되지 않았습니다.")
    else:
        raise ValueError(f"지원하지 않는 시장 데이터 공급자: {config.provider}")


def get_market_data_provider() -> MarketDataProvider:
    """전역 설정을 사용한 시장 데이터 공급자 싱글톤 조회."""
    # 모듈 레벨에서 캐싱
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = create_market_data_provider()
    return _provider_instance


_provider_instance: MarketDataProvider | None = None


def reset_market_data_provider() -> None:
    """공급자 인스턴스 리셋 (테스트용)."""
    global _provider_instance
    _provider_instance = None
