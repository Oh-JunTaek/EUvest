"""Orchestrator 시장 데이터 분기 로직 검증 테스트."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from invest_agent.agent.context_builder import ContextBuilder
from invest_agent.ai.protocol import AIRequest, AIResponse, LLMProvider
from invest_agent.domain.enums import RunStatus
from invest_agent.domain.models import AgentRun, DecisionOutcome, EquitySnapshot, Thesis
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.runtime.orchestrator import Orchestrator
from invest_agent.settings import get_settings
from invest_agent.storage.repositories import (
    AgentRunRepository,
    EquitySnapshotRepository,
    ThesisRepository,
)
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


def _seed_ohlcv_data(db_path: Path, asset_id: str, provider: str, dates: list[str], market: Market = Market.KRX):
    """OHLCV 테스트 데이터 시드."""
    from invest_agent.storage.repositories import OHLCVRepository
    repo = OHLCVRepository(db_path)
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


class TestOrchestratorMarketContextGating:
    """Orchestrator 시장 데이터 분기 로직 테스트."""

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

    def _create_test_setup(self, asset_id: str = "KRX:005930"):
        """테스트용 가설, 실행, 스냅샷 생성."""
        thesis = Thesis(
            id=uuid4(),
            asset_id=asset_id,
            hypothesis="Test will rise",
            rationale="Strong fundamentals",
            metadata={"price_below": 70000, "timeout_days": 30},
        )
        thesis_repo = ThesisRepository(self.db_path)
        thesis_repo.save(thesis)

        run = AgentRun(
            id=uuid4(),
            status=RunStatus.COMPLETED,
            execution_mode="OFFLINE_SIM",
        )
        run_repo = AgentRunRepository(self.db_path)
        run_repo.save(run)

        snapshot = EquitySnapshot(
            id=uuid4(),
            run_id=run.id,
            timestamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
            total_equity=Decimal("100000000"),
            cash_balance=Decimal("50000000"),
            positions={asset_id: {"quantity": "100", "avg_price": "70000"}},
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
        )
        snapshot_repo = EquitySnapshotRepository(self.db_path)
        snapshot_repo.save(snapshot)

        return thesis, run

    def test_market_context_included_in_ai_request(self):
        """정상 시장 데이터일 때 해당 종목 OHLCV가 AI 요청에 포함되는지."""
        import asyncio

        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        thesis, run = self._create_test_setup("KRX:005930")

        builder = ContextBuilder(str(self.db_path), market_lookback=20)
        envelope = builder.build_context(run.id, asset_filter=["KRX:005930"])

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)

        captured_request = {}

        async def mock_generate_structured(self, request: AIRequest, schema: dict) -> AIResponse:
            captured_request["request"] = request
            return AIResponse(
                content='{"outcome": "TRADE", "side": "BUY", "target_weight_bps": 1000, "rationale": "Test"}',
                model="fake-model",
                provider=LLMProvider.FAKE,
                input_tokens=100,
                output_tokens=50,
                latency_ms=10,
                timestamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                finish_reason="stop",
                raw_response={},
            )

        async def run_test():
            with patch("invest_agent.ai.router.ProviderRouter.generate_structured", mock_generate_structured):
                return await orchestrator._make_decisions(run, envelope)

        decision = asyncio.run(run_test())

        assert decision is not None
        assert decision.outcome == DecisionOutcome.TRADE

        request = captured_request.get("request")
        assert request is not None
        assert isinstance(request, AIRequest)

        user_prompt = request.user_prompt
        assert "Market Context for KRX:005930" in user_prompt
        assert "Provider: TestProvider" in user_prompt
        assert "Total Bars: 20" in user_prompt
        assert "Sufficient: True" in user_prompt
        assert "Note: This is historical OHLCV data, not real-time prices" in user_prompt
        assert "2024-01-31" in user_prompt

    def test_no_market_data_returns_no_trade(self):
        """데이터 없음 시 AI 호출 없이 NO_TRADE."""
        import asyncio

        thesis, run = self._create_test_setup("KRX:999999")

        builder = ContextBuilder(str(self.db_path))
        envelope = builder.build_context(run.id, asset_filter=["KRX:999999"])

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)

        async def mock_generate_structured(self, request: AIRequest, schema: dict) -> AIResponse:
            pytest.fail("AI가 호출되어서는 안 됨")

        async def run_test():
            with patch("invest_agent.ai.router.ProviderRouter.generate_structured", mock_generate_structured):
                return await orchestrator._make_decisions(run, envelope)

        decision = asyncio.run(run_test())

        assert decision is not None
        assert decision.outcome == DecisionOutcome.NO_TRADE
        # market_ctx가 존재하지만 status가 "no_data"인 경우
        assert "시장 데이터 상태: no_data" in decision.rationale
        assert "저장된 데이터가 없습니다" in decision.rationale
        assert decision.model_provider == "orchestrator"
        assert decision.model_name == "internal"

    def test_provider_conflict_returns_no_trade(self):
        """공급자 충돌 시 AI 호출 없이 NO_TRADE."""
        import asyncio

        _seed_ohlcv_data(self.db_path, "KRX:005930", "ProviderA", ["2024-01-02", "2024-01-03"])
        _seed_ohlcv_data(self.db_path, "KRX:005930", "ProviderB", ["2024-01-04", "2024-01-05"])

        thesis, run = self._create_test_setup("KRX:005930")

        builder = ContextBuilder(str(self.db_path))
        envelope = builder.build_context(run.id, asset_filter=["KRX:005930"])

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)

        async def mock_generate_structured(self, request: AIRequest, schema: dict) -> AIResponse:
            pytest.fail("AI가 호출되어서는 안 됨")

        async def run_test():
            with patch("invest_agent.ai.router.ProviderRouter.generate_structured", mock_generate_structured):
                return await orchestrator._make_decisions(run, envelope)

        decision = asyncio.run(run_test())

        assert decision is not None
        assert decision.outcome == DecisionOutcome.NO_TRADE
        assert "provider_conflict" in decision.rationale or "공급자가 여러 개입니다" in decision.rationale

    def test_insufficient_data_returns_no_trade(self):
        """데이터 부족 시 AI 호출 없이 NO_TRADE."""
        import asyncio

        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"])

        thesis, run = self._create_test_setup("KRX:005930")

        builder = ContextBuilder(str(self.db_path), market_lookback=20)
        envelope = builder.build_context(run.id, asset_filter=["KRX:005930"])

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)

        async def mock_generate_structured(self, request: AIRequest, schema: dict) -> AIResponse:
            pytest.fail("AI가 호출되어서는 안 됨")

        async def run_test():
            with patch("invest_agent.ai.router.ProviderRouter.generate_structured", mock_generate_structured):
                return await orchestrator._make_decisions(run, envelope)

        decision = asyncio.run(run_test())

        assert decision is not None
        assert decision.outcome == DecisionOutcome.NO_TRADE
        assert "시장 데이터 부족" in decision.rationale
        assert "5개" in decision.rationale

    def test_other_asset_data_not_mixed(self):
        """다른 종목 데이터가 프롬프트에 섞이지 않는지."""
        import asyncio

        dates_5930 = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates_5930)

        dates_0660 = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:000660", "TestProvider", dates_0660)

        thesis, run = self._create_test_setup("KRX:005930")

        builder = ContextBuilder(str(self.db_path), market_lookback=20)
        envelope = builder.build_context(run.id, asset_filter=["KRX:005930"])

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)

        captured_request = {}

        async def mock_generate_structured(self, request: AIRequest, schema: dict) -> AIResponse:
            captured_request["request"] = request
            return AIResponse(
                content='{"outcome": "TRADE", "side": "BUY", "target_weight_bps": 1000, "rationale": "Test"}',
                model="fake-model",
                provider=LLMProvider.FAKE,
                input_tokens=100,
                output_tokens=50,
                latency_ms=10,
                timestamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                finish_reason="stop",
                raw_response={},
            )

        async def run_test():
            with patch("invest_agent.ai.router.ProviderRouter.generate_structured", mock_generate_structured):
                return await orchestrator._make_decisions(run, envelope)

        decision = asyncio.run(run_test())

        assert decision is not None
        assert decision.outcome == DecisionOutcome.TRADE

        user_prompt = captured_request["request"].user_prompt
        assert "Market Context for KRX:005930" in user_prompt
        assert "KRX:000660" not in user_prompt

    def test_without_asset_filter_no_market_context(self):
        """asset_filter 없이 실행 시 시장 컨텍스트 없음 -> NO_TRADE."""
        import asyncio

        thesis, run = self._create_test_setup("KRX:005930")
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", ["2024-01-02"])

        builder = ContextBuilder(str(self.db_path))
        envelope = builder.build_context(run.id)

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)

        async def mock_generate_structured(self, request: AIRequest, schema: dict) -> AIResponse:
            pytest.fail("AI가 호출되어서는 안 됨")

        async def run_test():
            with patch("invest_agent.ai.router.ProviderRouter.generate_structured", mock_generate_structured):
                return await orchestrator._make_decisions(run, envelope)

        decision = asyncio.run(run_test())

        assert decision is not None
        assert decision.outcome == DecisionOutcome.NO_TRADE
        assert "asset_filter 없이 실행됨" in decision.rationale
