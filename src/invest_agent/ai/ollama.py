"""Ollama Provider - 로컬 Ollama 서버 연동."""

from __future__ import annotations

import json
import time

import httpx

from invest_agent.ai.protocol import (
    AIProvider,
    AIRequest,
    AIResponse,
    LLMProvider,
    ProviderCapabilities,
)


class OllamaProvider(AIProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        timeout: float = 120.0,
        max_retries: int = 3,
    ):
        self._provider_type = LLMProvider.OLLAMA
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries

        self._capabilities = ProviderCapabilities(
            supports_json_mode=True,
            supports_function_calling=False,
            supports_streaming=True,
            max_context_tokens=8192,
            max_output_tokens=2048,
        )

        self._client: httpx.AsyncClient | None = None
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

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._client

    def _build_payload(self, request: AIRequest, structured: bool = False) -> dict:
        prompt = f"{request.system_prompt}\n\n{request.user_prompt}"

        payload = {
            "model": self._model,
            "prompt": prompt,
            "temperature": request.temperature,
            "num_predict": min(request.max_tokens, self._capabilities.max_output_tokens),
        }

        if request.response_format == "json" or structured:
            payload["format"] = "json"

        if request.stop_sequences:
            payload["stop"] = request.stop_sequences

        return payload

    async def generate(self, request: AIRequest) -> AIResponse:
        return await self._request(request, structured=False)

    async def generate_structured(
        self,
        request: AIRequest,
        schema: dict,
    ) -> AIResponse:
        structured_request = AIRequest(
            system_prompt=request.system_prompt + f"\n\nOutput must match this JSON schema: {json.dumps(schema)}",
            user_prompt=request.user_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format="json",
        )
        return await self._request(structured_request, structured=True)

    async def _request(self, request: AIRequest, structured: bool = False) -> AIResponse:
        client = await self._get_client()
        payload = self._build_payload(request, structured)

        start = time.perf_counter()
        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post("/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()

                elapsed_ms = int((time.perf_counter() - start) * 1000)

                content = data.get("response", "")

                input_tokens = self.estimate_tokens(request.system_prompt + request.user_prompt)
                output_tokens = self.estimate_tokens(content)

                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens
                self._total_calls += 1
                self._total_latency_ms += elapsed_ms

                return AIResponse(
                    content=content,
                    model=data.get("model", self._model),
                    provider=LLMProvider.OLLAMA,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=elapsed_ms,
                    timestamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                    finish_reason="stop",
                    raw_response=data,
                )

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500:
                    await self._wait_before_retry(attempt)
                    continue
                else:
                    raise
            except Exception as e:
                last_error = e
                await self._wait_before_retry(attempt)

        raise RuntimeError(f"Failed after {self._max_retries + 1} attempts: {last_error}")

    async def _wait_before_retry(self, attempt: int) -> None:
        import asyncio
        wait_time = min(2 ** attempt, 30)
        await asyncio.sleep(wait_time)

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4 + 1

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    def get_usage_stats(self) -> dict:
        return {
            "provider": "ollama",
            "model": self._model,
            "total_calls": self._total_calls,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_latency_ms": self._total_latency_ms,
            "avg_latency_ms": self._total_latency_ms / max(1, self._total_calls),
        }

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
