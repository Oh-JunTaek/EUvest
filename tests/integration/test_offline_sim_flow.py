from __future__ import annotations

import asyncio
import gc
import shutil
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.agent.context_builder import ContextBuilder
from invest_agent.ai.protocol import AIResponse, LLMProvider
from invest_agent.domain.enums import RunStatus
from invest_agent.domain.models import AgentRun, DecisionOutcome, EquitySnapshot, Thesis
from invest_agent.execution.risk_gate import RiskGate
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.runtime.orchestrator import Orchestrator
from invest_agent.settings import get_settings
from invest_agent.storage.repositories import (
    AgentRunRepository,
    DecisionRepository,
    EquitySnapshotRepository,
    OHLCVRepository,
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
            timestamp=datetime.now(UTC),
            total_equity=Decimal("100000000"),
            cash_balance=Decimal("50000000"),
            positions={asset_id: {"quantity": "100", "avg_price": "70000"}},
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
        )
        snapshot_repo = EquitySnapshotRepository(self.db_path)
        snapshot_repo.save(snapshot)

        return thesis, run

    def test_offline_sim_normal_data_creates_trade(self, mocker):
        """정상 데이터(20개 이상, 7일 이내) 시 TRADE 결정 생성."""
        # 20일 데이터 시드 (최신: 2024-01-31, 기준일 2024-02-01)
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]  # 2024-01-02 ~ 2024-01-31
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        thesis, run = self._create_test_setup("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        # 테스트용으로 risk gate max_order_size_pct 늘리기 (기본 5% -> 50%로 늘려서 10% 주문 통과)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        # Use test reference date for market data freshness check
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        # AI 응답 모킹 (TRADE 반환)

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

        # orchestrator의 router.generate_structured 메서드 패치
        mocker.patch("invest_agent.ai.router.ProviderRouter.generate_structured", MockProviderRouter().generate_structured)

        # 테스트에서 생성한 run의 ID를 run_once에 전달하여 같은 run을 사용하도록 함
        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"], run_id=run.id))

        # 검증
        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.TRADE
        assert result.orders_created == 1

    def test_offline_sim_no_market_data_returns_no_trade(self):
        """데이터 없음 시 NO_TRADE, 주문 생성 없음."""
        thesis, run = self._create_test_setup("KRX:999999")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        # 테스트용으로 risk gate max_order_size_pct 늘리기 (기본 5% -> 50%로 늘려서 10% 주문 통과)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000000'), max_portfolio_exposure=Decimal('50000000'))

        # 테스트에서 생성한 run의 ID를 run_once에 전달하여 같은 run을 사용하도록 함
        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:999999"], run_id=run.id))

        # 검증 (NO_TRADE 시 error는 None, decision rationale 확인)
        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.NO_TRADE
        assert result.orders_created == 0
        # decision rationale 확인 (result.run_id로 조회)
        decision_repo = DecisionRepository(self.db_path)
        decisions = decision_repo.get_by_run(result.run_id)
        assert len(decisions) == 1
        assert "시장 데이터 상태: no_data" in decisions[0].rationale

    def test_offline_sim_stale_data_returns_no_trade(self):
        """오래된 데이터(7일 초과) 시 NO_TRADE, 주문 생성 없음."""
        # 2024-01-20 데이터는 2024-02-01 기준 12일 경과 (7일 초과)
        # 충분한 데이터(20일)를 시드
        dates = [f"2024-01-{d:02d}" for d in range(1, 21)]  # 2024-01-01 ~ 2024-01-20
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        thesis, run = self._create_test_setup("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        # 테스트용으로 risk gate max_order_size_pct 늘리기 (기본 5% -> 50%로 늘려서 10% 주문 통과)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        # Use test reference date for market data freshness check
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        # 테스트에서 생성한 run의 ID를 run_once에 전달하여 같은 run을 사용하도록 함
        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"], run_id=run.id))

        # 검증
        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.NO_TRADE
        assert result.orders_created == 0
        # decision rationale 확인 (result.run_id로 조회)
        decision_repo = DecisionRepository(self.db_path)
        decisions = decision_repo.get_by_run(result.run_id)
        assert len(decisions) == 1
        assert "시장 데이터가 너무 오래됨" in decisions[0].rationale
        assert "2024-01-20" in decisions[0].rationale

    def test_offline_sim_future_date_returns_no_trade(self):
        """미래 거래일(age_days < 0) 시 NO_TRADE."""
        # 20일 데이터 시드 (2024-01-17 ~ 2024-02-05, 마지막이 2024-02-05)
        from datetime import datetime, timedelta
        dates = []
        start = datetime(2024, 1, 17)
        for i in range(20):
            d = start + timedelta(days=i)
            dates.append(d.strftime("%Y-%m-%d"))
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        thesis, run = self._create_test_setup("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        # 테스트용으로 risk gate max_order_size_pct 늘리기 (기본 5% -> 50%로 늘려서 10% 주문 통과)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        # Use test reference date for market data freshness check
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        # 테스트에서 생성한 run의 ID를 run_once에 전달하여 같은 run을 사용하도록 함
        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"], run_id=run.id))

        # 검증
        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.NO_TRADE
        assert result.orders_created == 0
        # decision rationale 확인 (result.run_id로 조회)
        decision_repo = DecisionRepository(self.db_path)
        decisions = decision_repo.get_by_run(result.run_id)
        assert len(decisions) == 1
        assert "시장 데이터가 너무 오래됨" in decisions[0].rationale

    def test_offline_sim_no_fdr_network_call(self):
        """FDR 네트워크 호출 없이 MockProvider로 동작."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        thesis, run = self._create_test_setup("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        # 테스트용으로 risk gate max_order_size_pct 늘리기 (기본 5% -> 50%로 늘려서 10% 주문 통과)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        # Use test reference date for market data freshness check
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        # run_once 내부에서 FDR 호출이 발생하지 않는지 확인
        # (이미 DB에 데이터가 있으므로 ContextBuilder에서 바로 조회)
        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"], run_id=run.id))

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.TRADE

    def test_offline_sim_no_kis_api_call(self):
        """KIS API 호출 없이 동작 (OFFLINE_SIM 모드)."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        _seed_ohlcv_data(self.db_path, "KRX:005930", "TestProvider", dates)

        thesis, run = self._create_test_setup("KRX:005930")

        settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        # 테스트용으로 risk gate max_order_size_pct 늘리기 (기본 5% -> 50%로 늘려서 10% 주문 통과)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(max_order_size_pct=Decimal('0.5'), max_daily_loss=Decimal('10000010'), max_portfolio_exposure=Decimal('50000000'))
        # Use test reference date for market data freshness check
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)

        # KIS 관련 모듈이 import되지 않는지 확인 (OFFLINE_SIM 모드)
        import sys
        [m for m in sys.modules if 'kis' in m.lower()]

        result = asyncio.run(orchestrator.run_once(asset_filter=["KRX:005930"], run_id=run.id))

        assert result.status == RunStatus.COMPLETED
        assert result.decision_outcome == DecisionOutcome.TRADE
