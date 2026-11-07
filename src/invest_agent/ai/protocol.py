"""AI Provider 프로토콜 - 표준 인터페이스 정의."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from invest_agent.domain.enums import LLMProvider


@dataclass(frozen=True)
class AIRequest:
    """AI 요청 표준 형식."""
    system_prompt: str
    user_prompt: str
    temperature: float = 0.1
    max_tokens: int = 2000
    stop_sequences: list[str] | None = None
    response_format: str = "json"  # "json" or "text"
    metadata: dict | None = None


@dataclass(frozen=True)
class AIResponse:
    """AI 응답 표준 형식."""
    content: str
    model: str
    provider: LLMProvider
    input_tokens: int
    output_tokens: int
    latency_ms: int
    timestamp: datetime
    finish_reason: str = "stop"
    raw_response: dict | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    """공급자 능력 정보."""
    supports_json_mode: bool = True
    supports_function_calling: bool = False
    supports_streaming: bool = False
    max_context_tokens: int = 4096
    max_output_tokens: int = 2048


class AIProvider(ABC):
    """AI 공급자 추상 인터페이스."""

    @property
    @abstractmethod
    def provider_type(self) -> LLMProvider:
        """공급자 타입."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """공급자 능력."""
        ...

    @abstractmethod
    async def generate(self, request: AIRequest) -> AIResponse:
        """단일 생성 요청."""
        ...

    @abstractmethod
    async def generate_structured(
        self,
        request: AIRequest,
        schema: dict,
    ) -> AIResponse:
        """구조화된 출력(JSON 스키마 준수)."""
        ...

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """토큰 수 추정."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """연결 상태 확인."""
        ...

    @abstractmethod
    def get_usage_stats(self) -> dict:
        """사용량 통계."""
        ...


class ProviderRegistry:
    """공급자 레지스트리."""

    def __init__(self):
        self._providers: dict[LLMProvider, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.provider_type] = provider

    def get(self, provider_type: LLMProvider) -> AIProvider | None:
        return self._providers.get(provider_type)

    def list_providers(self) -> list[LLMProvider]:
        return list(self._providers.keys())


# 전역 레지스트리
_global_registry = ProviderRegistry()


def get_registry() -> ProviderRegistry:
    return _global_registry


def register_provider(provider: AIProvider) -> None:
    _global_registry.register(provider)


def get_provider(provider_type: LLMProvider) -> AIProvider | None:
    return _global_registry.get(provider_type)
