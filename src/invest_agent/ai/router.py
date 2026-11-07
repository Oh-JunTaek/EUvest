"""AI Provider 라우터 - 폴백, 예산 관리, 시크릿 차단."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from invest_agent.ai.fake_provider import FakeProvider
from invest_agent.ai.ollama import OllamaProvider
from invest_agent.ai.openai_compatible import OpenAICompatibleProvider
from invest_agent.ai.protocol import (
    AIRequest,
    AIResponse,
    LLMProvider,
    get_registry,
)
from invest_agent.settings import LLMProvider as SettingsLLMProvider
from invest_agent.settings import get_settings


@dataclass
class BudgetConfig:
    max_input_tokens_per_run: int = 12000
    max_output_tokens_per_run: int = 2500
    max_calls_per_run: int = 4
    max_calls_per_day: int = 20
    max_input_tokens_per_day: int = 50000
    max_output_tokens_per_day: int = 10000


@dataclass
class UsageTracker:
    run_input_tokens: int = 0
    run_output_tokens: int = 0
    run_calls: int = 0
    day_input_tokens: int = 0
    day_output_tokens: int = 0
    day_calls: int = 0
    last_reset: datetime = field(default_factory=lambda: datetime.now(UTC))

    def reset_run(self) -> None:
        self.run_input_tokens = 0
        self.run_output_tokens = 0
        self.run_calls = 0

    def reset_day(self) -> None:
        self.day_input_tokens = 0
        self.day_output_tokens = 0
        self.day_calls = 0
        self.last_reset = datetime.now(UTC)

    def check_and_consume(
        self,
        input_tokens: int,
        output_tokens: int,
        budget: BudgetConfig,
    ) -> tuple[bool, str]:
        now = datetime.now(UTC)
        if (now - self.last_reset).days >= 1:
            self.reset_day()

        if self.run_calls >= budget.max_calls_per_run:
            return False, f"Run call limit exceeded: {self.run_calls}/{budget.max_calls_per_run}"
        if self.run_input_tokens + input_tokens > budget.max_input_tokens_per_run:
            return False, "Run input token limit exceeded"
        if self.run_output_tokens + output_tokens > budget.max_output_tokens_per_run:
            return False, "Run output token limit exceeded"

        if self.day_calls >= budget.max_calls_per_day:
            return False, f"Daily call limit exceeded: {self.day_calls}/{budget.max_calls_per_day}"
        if self.day_input_tokens + input_tokens > budget.max_input_tokens_per_day:
            return False, "Daily input token limit exceeded"
        if self.day_output_tokens + output_tokens > budget.max_output_tokens_per_day:
            return False, "Daily output token limit exceeded"

        self.run_input_tokens += input_tokens
        self.run_output_tokens += output_tokens
        self.run_calls += 1
        self.day_input_tokens += input_tokens
        self.day_output_tokens += output_tokens
        self.day_calls += 1

        return True, "OK"

    def get_remaining_run(self, budget: BudgetConfig) -> dict:
        return {
            "calls": max(0, budget.max_calls_per_run - self.run_calls),
            "input_tokens": max(0, budget.max_input_tokens_per_run - self.run_input_tokens),
            "output_tokens": max(0, budget.max_output_tokens_per_run - self.run_output_tokens),
        }

    def get_remaining_day(self, budget: BudgetConfig) -> dict:
        return {
            "calls": max(0, budget.max_calls_per_day - self.day_calls),
            "input_tokens": max(0, budget.max_input_tokens_per_day - self.day_input_tokens),
            "output_tokens": max(0, budget.max_output_tokens_per_day - self.day_output_tokens),
        }


class SecretFilter:
    API_KEY_PATTERNS = [
        re.compile(r'(sk-[a-zA-Z0-9]{32,})'),
        re.compile(r'(Bearer\s+[a-zA-Z0-9\-_]{20,})'),
        re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9\-_]{20,})', re.IGNORECASE),
        re.compile(r'(secret[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9\-_]{20,})', re.IGNORECASE),
        re.compile(r'(password["\']?\s*[:=]\s*["\']?[a-zA-Z0-9\-_]{8,})', re.IGNORECASE),
    ]

    @classmethod
    def filter(cls, text: str) -> str:
        result = text
        for pattern in cls.API_KEY_PATTERNS:
            result = pattern.sub('[REDACTED]', result)
        return result

    @classmethod
    def filter_dict(cls, data: dict) -> dict:
        result = {}
        for k, v in data.items():
            if isinstance(v, str):
                result[k] = cls.filter(v)
            elif isinstance(v, dict):
                result[k] = cls.filter_dict(v)
            elif isinstance(v, list):
                result[k] = [cls.filter_dict(i) if isinstance(i, dict) else cls.filter(i) if isinstance(i, str) else i for i in v]
            else:
                result[k] = v
        return result

class ProviderRouter:
    def __init__(self, budget: BudgetConfig | None = None):
        self._budget = budget or BudgetConfig()
        self._usage = UsageTracker()
        self._registry = get_registry()
        self._initialized = False

    def _init_providers(self) -> None:
        if self._initialized:
            return

        settings = get_settings()
        ai_config = settings.ai

        primary = self._map_provider(ai_config.provider)

        if primary == LLMProvider.OPENAI_COMPATIBLE:
            if ai_config.endpoint and ai_config.api_key:
                provider = OpenAICompatibleProvider(
                    api_key=ai_config.api_key.get_secret_value(),
                    base_url=ai_config.endpoint,
                    model=ai_config.model,
                    timeout=ai_config.timeout_seconds,
                )
                self._registry.register(provider)

        elif primary == LLMProvider.OLLAMA:
            provider = OllamaProvider(
                model=ai_config.model,
            )
            self._registry.register(provider)

        fake = FakeProvider()
        self._registry.register(fake)

        self._initialized = True

    def _map_provider(self, provider: SettingsLLMProvider) -> LLMProvider:
        mapping = {
            SettingsLLMProvider.FAKE: LLMProvider.FAKE,
            SettingsLLMProvider.OPENAI_COMPATIBLE: LLMProvider.OPENAI_COMPATIBLE,
            SettingsLLMProvider.OLLAMA: LLMProvider.OLLAMA,
            SettingsLLMProvider.NVIDIA: LLMProvider.OPENAI_COMPATIBLE,
        }
        return mapping.get(provider, LLMProvider.FAKE)

    def _map_provider(self, provider: SettingsLLMProvider) -> LLMProvider:
        mapping = {
            SettingsLLMProvider.FAKE: LLMProvider.FAKE,
            SettingsLLMProvider.OPENAI_COMPATIBLE: LLMProvider.OPENAI_COMPATIBLE,
            SettingsLLMProvider.OLLAMA: LLMProvider.OLLAMA,
            SettingsLLMProvider.NVIDIA: LLMProvider.OPENAI_COMPATIBLE,
        }
        return mapping.get(provider, LLMProvider.FAKE)

    async def generate(
        self,
        request: AIRequest,
        preferred_provider: LLMProvider | None = None,
    ) -> AIResponse:
        self._init_providers()

        est_input = self._estimate_tokens(request.system_prompt + request.user_prompt)
        est_output = min(request.max_tokens, 2000)

        ok, msg = self._usage.check_and_consume(est_input, est_output, self._budget)
        if not ok:
            raise RuntimeError(f'Budget exceeded: {msg}')

        providers_to_try = []
        if preferred_provider:
            providers_to_try.append(preferred_provider)
        providers_to_try.extend([LLMProvider.OPENAI_COMPATIBLE, LLMProvider.OLLAMA, LLMProvider.FAKE])

        last_error = None
        for provider_type in providers_to_try:
            provider = self._registry.get(provider_type)
            if not provider:
                continue

            try:
                if not await provider.health_check():
                    continue

                response = await provider.generate(request)

                response.content = SecretFilter.filter(response.content)
                if response.raw_response:
                    response.raw_response = SecretFilter.filter_dict(response.raw_response)

                return response

            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f'All providers failed: {last_error}')

    async def generate_structured(
        self,
        request: AIRequest,
        schema: dict,
        preferred_provider: LLMProvider | None = None,
    ) -> AIResponse:
        self._init_providers()

        est_input = self._estimate_tokens(request.system_prompt + request.user_prompt)
        est_output = min(request.max_tokens, 2000)

        ok, msg = self._usage.check_and_consume(est_input, est_output, self._budget)
        if not ok:
            raise RuntimeError(f'Budget exceeded: {msg}')

        providers_to_try = []
        if preferred_provider:
            providers_to_try.append(preferred_provider)
        providers_to_try.extend([LLMProvider.OPENAI_COMPATIBLE, LLMProvider.OLLAMA, LLMProvider.FAKE])

        last_error = None
        for provider_type in providers_to_try:
            provider = self._registry.get(provider_type)
            if not provider:
                continue

            try:
                if not await provider.health_check():
                    continue

                response = await provider.generate_structured(request, schema)

                response.content = SecretFilter.filter(response.content)
                if response.raw_response:
                    response.raw_response = SecretFilter.filter_dict(response.raw_response)

                return response

            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f'All providers failed for structured output: {last_error}')

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4 + 1

    def get_usage_stats(self) -> dict:
        return {
            'run': self._usage.get_remaining_run(self._budget),
            'day': self._usage.get_remaining_day(self._budget),
            'total_calls': self._usage.run_calls,
        }

    def reset_run_budget(self) -> None:
        self._usage.reset_run()

    async def close(self) -> None:
        for provider in self._registry.list_providers():
            p = self._registry.get(provider)
            if p and hasattr(p, 'close'):
                await p.close()
