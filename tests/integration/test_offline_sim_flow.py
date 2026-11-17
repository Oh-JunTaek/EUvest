from __future__ import annotations

import asyncio
import gc
import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from invest_agent.agent.context_builder import ContextBuilder
from invest_agent.ai.protocol import AIResponse, LLMProvider
from invest_agent.domain.enums import OrderStatus, RunStatus
from invest_agent.domain.models import DecisionOutcome, Thesis
from invest_agent.execution.risk_gate import RiskGate
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.runtime.orchestrator import Orchestrator
from invest_agent.settings import get_settings
from invest_agent.storage.repositories import (
    DecisionRepository,
    OHLCVRepository,
    OrderRepository,
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


# 테스트용 고정 기준일 (2024-02-01로 설정하여 2024-01 데이터가 최신으로 판정되도록)
TEST_REFERENCE_DATE = datetime(2024, 2, 1, tzinfo=UTC)


class TestOfflineSimFlow:
    """OFFLINE_SIM 실행 흐름 검증 테스트."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test.db'
        ensure_db(self.db_path)

    def teardown_method(self):
        gc.collect()
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError:
                pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_thesis_and_snapshot(self, asset_id: str = "KRX:005930"):
        """테스트용 가설과 스냅샷 생성 (run은 생성하지 않음)."""
        thesis = Thesis(
            id=uuid4(),
            asset_id=asset_id,
            hypothesis="Test will rise",
            rationale="Strong fundamentals",
            metadata={"price_below": 70000, "timeout_days": 30},
        )
        thesis_repo = ThesisRepository(self.db_path)
        thesis_repo.save(thesis)
        return thesis

    def test_offline_sim_normal_data_creates_trade(self):
        """정상 데이터(20개 이상, 7일 이내) 시 TRADE 결정 생성 및 주문 체결 검증."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        self._create_thesis_and_snapshot("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        from invest_agent.ai.protocol import AIResponse, LLMProvider

        class MockProviderRouter:
            async def generate_structured(self, request, schema):
                return AIResponse(
                    content='{"outcome": "TRADE", "side": "BUY", "target_weight_bps": 1000, "rationale": "Test buy"}',
                    model="fake-model",
                    provider=LLMProvider.FAKE,
                    input_tokens=100,
                    output_tokens=50,
                    latency_ms=10,
                    timestamp=datetime.now(UTC),
                    finish_reason="stop",
                    raw_response={},
                )

        with patch("invest_agent.ai.router.ProviderRouter.generate_structured", MockProviderRouter().generate_structured):
            result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"]))

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.TRADE
        assert result.orders_created == 1
        assert result.orders_filled == 1

        decision_repo = DecisionRepository(self.db_path)
        decisions = decision_repo.get_by_run(result.run_id)
        assert len(decisions) == 1
        assert decisions[0].outcome == DecisionOutcome.TRADE
        assert decisions[0].side == "BUY"

        order_repo = OrderRepository(self.db_path)
        orders = order_repo.get_by_run(result.run_id)
        assert len(orders) == 1
        assert orders[0].status == OrderStatus.FILLED
        assert orders[0].filled_quantity is not None
        assert orders[0].filled_price is not None

        balance = orchestrator.broker.get_balance()
        # 현금이 감소했는지 확인 (매수 비용만큼)
        assert balance.total_cash < Decimal("100000000")
        positions = orchestrator.broker.get_positions()
        # positions는 리스트이므로 asset_id로 검색
        krx_position = next((p for p in positions if p.asset_id == "KRX:005930"), None)
        assert krx_position is not None
        assert krx_position.quantity > 0

    def test_offline_sim_no_market_data_returns_no_trade(self):
        """데이터 없음 시 NO_TRADE, 주문 생성 없음."""
        self._create_thesis_and_snapshot("KRX:999999")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000000'), max_portfolio_exposure=Decimal('50000000'))

        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:999999"]))

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.NO_TRADE
        assert result.orders_created == 0
        assert result.orders_filled == 0

        from invest_agent.storage.repositories import DecisionRepository
        decision_repo = DecisionRepository(self.db_path)
        decisions = decision_repo.get_by_run(result.run_id)
        assert len(decisions) == 1
        assert "시장 데이터 상태: no_data" in decisions[0].rationale

    def test_offline_sim_stale_data_returns_no_trade(self):
        """오래된 데이터(7일 초과) 시 NO_TRADE, 주문 생성 없음."""
        dates = [f"2024-01-{d:02d}" for d in range(1, 21)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        self._create_thesis_and_snapshot("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"]))

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.NO_TRADE
        assert result.orders_created == 0
        assert result.orders_filled == 0

        from invest_agent.storage.repositories import DecisionRepository
        decision_repo = DecisionRepository(self.db_path)
        decisions = decision_repo.get_by_run(result.run_id)
        assert len(decisions) == 1
        assert "시장 데이터가 너무 오래됨" in decisions[0].rationale
        assert "2024-01-20" in decisions[0].rationale

    def test_offline_sim_future_date_returns_no_trade(self):
        """미래 거래일(age_days < 0) 시 NO_TRADE."""
        from datetime import datetime, timedelta
        dates = []
        start = datetime(2024, 1, 17)
        for i in range(20):
            d = start + timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d"))
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        self._create_thesis_and_snapshot("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"]))

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.NO_TRADE
        assert result.orders_created == 0
        assert result.orders_filled == 0

        from invest_agent.storage.repositories import DecisionRepository
        decision_repo = DecisionRepository(self.db_path)
        decisions = decision_repo.get_by_run(result.run_id)
        assert len(decisions) == 1
        assert "시장 데이터가 너무 오래됨" in decisions[0].rationale

    def test_offline_sim_no_fdr_network_call(self):
        """FDR 네트워크 호출 없이 MockProvider로 동작 - FDR 호출 시 테스트 실패."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        self._create_thesis_and_snapshot("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        # finance_datareader 모듈이 설치되지 않았을 수도 있으므로, FDR 공급자 내부에서 사용하는 DataReader를 패치
        call_count = {"count": 0}

        def mock_data_reader(*args, **kwargs):
            call_count["count"] += 1
            raise AssertionError("FDR DataReader가 호출되었습니다. OFFLINE_SIM에서는 네트워크 호출이 없어야 합니다.")

        # FDRProvider 내부에서 사용하는 FinanceDataReader 모듈을 패치
        # 함수 내부에서 `import FinanceDataReader as fdr`로 import하므로, sys.modules를 패치
        import types

        # FinanceDataReader 모듈 목킹
        mock_fdr = types.ModuleType('FinanceDataReader')
        mock_fdr.DataReader = mock_data_reader

        with patch.dict('sys.modules', {'FinanceDataReader': mock_fdr}):
            with patch("invest_agent.ai.router.ProviderRouter._init_providers", lambda self: None):
                with patch("invest_agent.ai.router.ProviderRouter.generate_structured", new_callable=AsyncMock) as mock_generate:
                    mock_generate.return_value = AIResponse(
                        content='{"outcome": "TRADE", "side": "BUY", "target_weight_bps": 1000, "rationale": "Test buy"}',
                        model="fake-model",
                        provider=LLMProvider.FAKE,
                        input_tokens=100,
                        output_tokens=50,
                        latency_ms=10,
                        timestamp=datetime.now(UTC),
                        finish_reason="stop",
                        raw_response={},
                    )
                    result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"]))

        assert call_count["count"] == 0, "FDR 네트워크 호출이 감지되었습니다"

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.TRADE

    def test_offline_sim_no_kis_api_call(self):
        """KIS API 호출 없이 동작 (OFFLINE_SIM 모드) - KIS 호출 시 테스트 실패."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        self._create_thesis_and_snapshot("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        import builtins

        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if 'kis' in name.lower():
                raise AssertionError(f"KIS 모듈 '{name}' import 시도 감지. OFFLINE_SIM에서는 KIS API를 사용하지 않아야 합니다.")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            with patch("invest_agent.ai.router.ProviderRouter.generate_structured", new_callable=AsyncMock) as mock_generate:
                mock_generate.return_value = AIResponse(
                    content='{"outcome": "TRADE", "side": "BUY", "target_weight_bps": 1000, "rationale": "Test buy"}',
                    model="fake-model",
                    provider=LLMProvider.FAKE,
                    input_tokens=100,
                    output_tokens=50,
                    latency_ms=10,
                    timestamp=datetime.now(UTC),
                    finish_reason="stop",
                    raw_response={},
                )
                result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"]))

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.TRADE
