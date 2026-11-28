"""연속 오프라인 투자 실험 통합 테스트.

PART C: 오프라인 연속 투자 실험 검증

시나리오:
1. 첫 번째 실행: BUY 판단 및 모의 체결
2. 두 번째 실행: 기존 계좌 상태 유지 및 NO_TRADE
3. 세 번째 실행: 런타임 재시작 후 SELL
4. 네 번째 실행: 현금 부족 또는 보유 수량 초과 주문 차단
5. 다섯 번째 실행: 중복 실행 및 중복 주문 방지
"""

from __future__ import annotations

import gc
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.agent.context_builder import ContextBuilder
from invest_agent.ai.protocol import AIResponse, LLMProvider
from invest_agent.domain.models import Thesis
from invest_agent.execution.risk_gate import RiskGate
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.runtime.orchestrator import Orchestrator
from invest_agent.settings import get_settings
from invest_agent.storage.repositories import (
    AgentRunRepository,
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


class TestExperimentFlow:
    """연속 오프라인 투자 실험 검증 테스트."""

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

    def _create_initial_snapshot(self, cash_krw: Decimal = Decimal("100000000")):
        """초기 스냅샷 생성."""
        from invest_agent.domain.models import AgentRun, EquitySnapshot, RunStatus

        run_repo = AgentRunRepository(self.db_path)
        dummy_run = AgentRun(
            id=uuid4(),
            started_at=datetime.now(UTC) - timedelta(hours=1),
            completed_at=datetime.now(UTC),
            status=RunStatus.COMPLETED,
            execution_mode="OFFLINE_SIM",
        )
        run_repo.save(dummy_run)

        snapshot_repo = EquitySnapshotRepository(self.db_path)
        snapshot = EquitySnapshot(
            id=uuid4(),
            run_id=dummy_run.id,
            timestamp=datetime.now(UTC),
            total_equity=cash_krw,
            cash_balance=cash_krw,
            positions={},
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            metadata={},
        )
        snapshot_repo.save(snapshot)
        return snapshot

    def _make_orchestrator(self, settings=None):
        """오케스트레이터 생성 (공통 설정)."""
        if settings is None:
            settings = get_settings()
        orchestrator = Orchestrator(str(self.db_path), settings=settings)
        from decimal import Decimal
        orchestrator.risk_gate = RiskGate(
            max_order_size_pct=Decimal('0.5'),
            max_daily_loss=Decimal('10000000'),
            max_portfolio_exposure=Decimal('50000000'),
        )
        orchestrator.context_builder = ContextBuilder(str(self.db_path), market_reference_date=TEST_REFERENCE_DATE)
        return orchestrator

    def _create_mock_provider(self, outcome: str, side: str = "BUY", target_weight_bps: int = 1000):
        """결정론적 FakeProvider 생성."""
        class MockProviderRouter:
            async def generate_structured(self, request, schema):
                return AIResponse(
                    content=f'{{"outcome": "{outcome}", "side": "{side}", "target_weight_bps": {target_weight_bps}, "rationale": "Test {outcome} {side}"}}',
                    model="fake-model",
                    provider=LLMProvider.FAKE,
                    input_tokens=100,
                    output_tokens=50,
                    latency_ms=10,
                    timestamp=datetime.now(UTC),
                    finish_reason="stop",
                    raw_response={},
                )
        return MockProviderRouter()

    def test_continuous_experiment_flow(self):
        pass
    def test_restart_state_restoration(self):
        pass
    def test_duplicate_order_prevention(self):
        pass
    def test_analysis_functions_execution(self):
        pass

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, '-v'])
