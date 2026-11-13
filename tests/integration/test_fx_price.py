"""FX 환율 및 가격 처리 통합 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from invest_agent.broker.mock_broker import MockBroker
from invest_agent.domain.enums import RunStatus
from invest_agent.domain.models import AgentRun, EquitySnapshot, Thesis
from invest_agent.runtime.orchestrator import create_orchestrator
from invest_agent.settings import Settings
from invest_agent.storage.repositories import (
    AgentRunRepository,
    EquitySnapshotRepository,
    ThesisRepository,
)
from invest_agent.storage.schema import ensure_db


@pytest.fixture
def setup_db(tmp_path):
    db_path = str(tmp_path / 'test.db')
    ensure_db(db_path)
    return db_path


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def krw_thesis_with_snapshot(setup_db, settings):
    thesis_repo = ThesisRepository(setup_db)
    run_repo = AgentRunRepository(setup_db)
    snapshot_repo = EquitySnapshotRepository(setup_db)

    thesis = Thesis(
        id=uuid4(),
        asset_id="KRX:005930",
        hypothesis="테스트",
        rationale="테스트",
        created_at=datetime.now(UTC) - timedelta(days=1),
        updated_at=datetime.now(UTC) - timedelta(days=1),
        is_active=True,
    )
    thesis_repo.save(thesis)

    dummy_run = AgentRun(
        id=uuid4(),
        started_at=datetime.now(UTC) - timedelta(hours=1),
        completed_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        execution_mode="OFFLINE_SIM",
    )
    run_repo.save(dummy_run)

    snapshot = EquitySnapshot(
        id=uuid4(),
        run_id=dummy_run.id,
        timestamp=datetime.now(UTC),
        total_equity=Decimal("100000000"),
        cash_balance=Decimal("100000000"),
        positions={},
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        metadata={},
    )
    snapshot_repo.save(snapshot)

    broker = MockBroker(initial_cash=Decimal("100000000"))
    broker.set_quote("KRX:005930", Decimal("75000"))

    return thesis, broker


@pytest.fixture
def usd_thesis_with_snapshot(setup_db, settings):
    thesis_repo = ThesisRepository(setup_db)
    run_repo = AgentRunRepository(setup_db)
    snapshot_repo = EquitySnapshotRepository(setup_db)

    thesis = Thesis(
        id=uuid4(),
        asset_id="US:AAPL",
        hypothesis="테스트",
        rationale="테스트",
        created_at=datetime.now(UTC) - timedelta(days=1),
        updated_at=datetime.now(UTC) - timedelta(days=1),
        is_active=True,
    )
    thesis_repo.save(thesis)

    dummy_run = AgentRun(
        id=uuid4(),
        started_at=datetime.now(UTC) - timedelta(hours=1),
        completed_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        execution_mode="OFFLINE_SIM",
    )
    run_repo.save(dummy_run)

    snapshot = EquitySnapshot(
        id=uuid4(),
        run_id=dummy_run.id,
        timestamp=datetime.now(UTC),
        total_equity=Decimal("100000000"),
        cash_balance=Decimal("100000000"),
        positions={},
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        metadata={},
    )
    snapshot_repo.save(snapshot)

    broker = MockBroker(initial_cash=Decimal("100000000"))
    broker.set_quote("US:AAPL", Decimal("180"))

    return thesis, broker


async def run_orchestrator_once(db_path, settings, broker=None, asset_filter=None, force=True):
    orchestrator = create_orchestrator(db_path, settings)
    if broker:
        orchestrator.broker = broker
    # 테스트용: 주문 크기 제한 완화 (5% -> 50%)
    from decimal import Decimal

    from invest_agent.execution.risk_gate import RiskGate
    orchestrator.risk_gate = RiskGate(
        max_order_size_pct=Decimal('0.5'),
        max_daily_loss=Decimal('1000000'),
        max_portfolio_exposure=Decimal('50000000'),
    )
    return await orchestrator.run_once(asset_filter=asset_filter, force=force)


def test_krw_stock_buy_uses_broker_quote(setup_db, settings, krw_thesis_with_snapshot):
    import asyncio
    thesis, broker = krw_thesis_with_snapshot
    result = asyncio.run(run_orchestrator_once(
        setup_db, settings, broker=broker, asset_filter=["KRX:005930"], force=True
    ))
    assert result.status == RunStatus.COMPLETED
    assert result.error is None


def test_usd_stock_buy_uses_broker_quote_and_fx_rate(setup_db, settings, usd_thesis_with_snapshot):
    import asyncio
    thesis, broker = usd_thesis_with_snapshot
    result = asyncio.run(run_orchestrator_once(
        setup_db, settings, broker=broker, asset_filter=["US:AAPL"], force=True
    ))
    assert result.status == RunStatus.COMPLETED
    assert result.error is None


def test_missing_quote_blocks_order(setup_db, settings):
    import asyncio
    from decimal import Decimal

    from invest_agent.domain.models import AgentRun, EquitySnapshot, Thesis
    from invest_agent.storage.repositories import (
        AgentRunRepository,
        EquitySnapshotRepository,
        ThesisRepository,
    )

    thesis_repo = ThesisRepository(setup_db)
    run_repo = AgentRunRepository(setup_db)
    snapshot_repo = EquitySnapshotRepository(setup_db)

    thesis = Thesis(
        id=uuid4(),
        asset_id="KRX:999999",
        hypothesis="테스트",
        rationale="테스트",
        created_at=datetime.now(UTC) - timedelta(days=1),
        updated_at=datetime.now(UTC) - timedelta(days=1),
        is_active=True,
    )
    thesis_repo.save(thesis)

    dummy_run = AgentRun(
        id=uuid4(),
        started_at=datetime.now(UTC) - timedelta(hours=1),
        completed_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        execution_mode="OFFLINE_SIM",
    )
    run_repo.save(dummy_run)

    snapshot = EquitySnapshot(
        id=uuid4(),
        run_id=dummy_run.id,
        timestamp=datetime.now(UTC),
        total_equity=Decimal("100000000"),
        cash_balance=Decimal("100000000"),
        positions={},
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        metadata={},
    )
    snapshot_repo.save(snapshot)

    broker = MockBroker(initial_cash=Decimal("100000000"))
    broker.set_quote("KRX:999999", Decimal("0"))

    result = asyncio.run(run_orchestrator_once(
        setup_db, settings, broker=broker, asset_filter=["KRX:999999"], force=True
    ))

    assert result.status == RunStatus.COMPLETED
    assert result.orders_created == 0


def test_invalid_fx_rate_blocks_order(setup_db, settings):
    import asyncio
    from decimal import Decimal

    from invest_agent.domain.models import AgentRun, EquitySnapshot, Thesis
    from invest_agent.storage.repositories import (
        AgentRunRepository,
        EquitySnapshotRepository,
        ThesisRepository,
    )

    thesis_repo = ThesisRepository(setup_db)
    run_repo = AgentRunRepository(setup_db)
    snapshot_repo = EquitySnapshotRepository(setup_db)

    thesis = Thesis(
        id=uuid4(),
        asset_id="US:TEST",
        hypothesis="테스트",
        rationale="테스트",
        created_at=datetime.now(UTC) - timedelta(days=1),
        updated_at=datetime.now(UTC) - timedelta(days=1),
        is_active=True,
    )
    thesis_repo.save(thesis)

    dummy_run = AgentRun(
        id=uuid4(),
        started_at=datetime.now(UTC) - timedelta(hours=1),
        completed_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        execution_mode="OFFLINE_SIM",
    )
    run_repo.save(dummy_run)

    snapshot = EquitySnapshot(
        id=uuid4(),
        run_id=dummy_run.id,
        timestamp=datetime.now(UTC),
        total_equity=Decimal("100000000"),
        cash_balance=Decimal("100000000"),
        positions={},
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        metadata={},
    )
    snapshot_repo.save(snapshot)

    custom_settings = Settings()
    custom_settings.execution.mock_fx_rate_usd_krw = Decimal("0")

    broker = MockBroker(initial_cash=Decimal("100000000"))
    broker.set_quote("US:TEST", Decimal("100"))

    result = asyncio.run(run_orchestrator_once(
        setup_db, custom_settings, broker=broker, asset_filter=["US:TEST"], force=True
    ))

    assert result.status == RunStatus.COMPLETED
    assert result.orders_created == 0
