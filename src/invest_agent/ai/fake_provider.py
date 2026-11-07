"""Fake Provider - 테스트용 AI 공급자.

실제 API 호출 없이 결정론적 응답을 반환한다.
"""

from __future__ import annotations

import json
import time

from invest_agent.ai.protocol import (
    AIProvider,
    AIRequest,
    AIResponse,
    LLMProvider,
    ProviderCapabilities,
)


class FakeProvider(AIProvider):
    """테스트용 가짜 AI 공급자.

    - 프롬프트에 따라 결정론적 응답 반환
    - 토큰/콜 예산 추적
    - 지연 시뮬레이션
    """

    def __init__(
        self,
        default_response: dict | None = None,
        latency_ms: int = 10,
        fail_after_calls: int | None = None,
    ):
        self._provider_type = LLMProvider.FAKE
        self._capabilities = ProviderCapabilities(
            supports_json_mode=True,
            supports_function_calling=False,
            supports_streaming=False,
            max_context_tokens=4096,
            max_output_tokens=2048,
        )
        self._default_response = default_response or {"decision": "HOLD", "confidence": 0.5}
        self._latency_ms = latency_ms
        self._call_count = 0
        self._fail_after = fail_after_calls
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_calls = 0
        self._total_latency_ms = 0

    @property
    def provider_type(self) -> LLMProvider:
        return self._provider_type

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def _build_response_content(self, request: AIRequest) -> str:
        """요청 기반 응답 생성."""
        # JSON 모드면 dict 반환
        if request.response_format == "json":
            return json.dumps(self._default_response, ensure_ascii=False)
        return str(self._default_response)

    async def generate(self, request: AIRequest) -> AIResponse:
        start = time.perf_counter()

        # 실패 시뮬레이션
        if self._fail_after is not None and self._call_count >= self._fail_after:
            raise RuntimeError("Simulated provider failure")

        self._call_count += 1

        # 토큰 추정
        input_tokens = self.estimate_tokens(request.system_prompt + request.user_prompt)
        content = self._build_response_content(request)
        output_tokens = self.estimate_tokens(content)

        # 지연 시뮬레이션
        await self._simulate_latency()

        elapsed_ms = int((time.perf_counter() - start) * 1000) + self._latency_ms

        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_calls += 1
        self._total_latency_ms += elapsed_ms

        return AIResponse(
            content=content,
            model="fake-model",
            provider=LLMProvider.FAKE,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            timestamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
            finish_reason="stop",
            raw_response={"call_count": self._call_count},
        )

    async def generate_structured(
        self,
        request: AIRequest,
        schema: dict,
    ) -> AIResponse:
        # 스키마 검증 없이 기본 응답 반환
        return await self.generate(request)

    async def _simulate_latency(self) -> None:
        import asyncio
        await asyncio.sleep(self._latency_ms / 1000)

    def estimate_tokens(self, text: str) -> int:
        # 간단한 추정: 1 토큰 ≈ 4 문자 (영어), 2 문자 (한글)
        korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7a3' or '\u1100' <= c <= '\u11ff')
        other_chars = len(text) - korean_chars
        return (korean_chars // 2) + (other_chars // 4) + 1

    async def health_check(self) -> bool:
        return True

    def get_usage_stats(self) -> dict:
        return {
            "provider": "fake",
            "total_calls": self._total_calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_latency_ms": self._total_latency_ms,
            "avg_latency_ms": self._total_latency_ms / max(1, self._total_calls),
        }

    def set_default_response(self, response: dict) -> None:
        """기본 응답 설정."""
        self._default_response = response

    def reset_stats(self) -> None:
        """통계 초기화."""
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_calls = 0
        self._total_latency_ms = 0
        self._call_count = 0
