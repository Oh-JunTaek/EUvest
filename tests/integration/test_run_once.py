"""run-once 통합 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from invest_agent.domain.enums import RunStatus
from invest_agent.domain.models import Thesis
from invest_agent.runtime.orchestrator import create_orchestrator
from invest_agent.settings import Settings
from invest_agent.storage.repositories import (
    AgentRunRepository,
    ThesisRepository,
)
from invest_agent.storage.schema import ensure_db


@pytest.fixture
def setup_db(tmp_path):
    """테스트용 DB 설정."""
    db_path = str(tmp_path / 'test.db')
    ensure_db(db_path)
    return db_path


@pytest.fixture
def settings():
    """테스트용 설정."""
    return Settings()


@pytest.fixture
def sample_thesis(setup_db):
    """샘플 논문 생성."""
    thesis_repo = ThesisRepository(setup_db)
    thesis = Thesis(
        id=uuid4(),
        asset_id="KRX:005930",
        hypothesis="삼성전자 반도체 업황 개선 예상",
        rationale="메모리 가격 상승 사이클 진입",
        created_at=datetime.now(UTC) - timedelta(days=1),
        updated_at=datetime.now(UTC) - timedelta(days=1),
        is_active=True,
    )
    thesis_repo.save(thesis)
    return thesis


@pytest.fixture
def sample_thesis_with_snapshot(setup_db, sample_thesis):
    """스냅샷이 있는 논문 생성."""
    from decimal import Decimal

    from invest_agent.domain.models import AgentRun, EquitySnapshot, RunStatus
    from invest_agent.storage.repositories import AgentRunRepository, EquitySnapshotRepository

    # 더미 런 생성
    run_repo = AgentRunRepository(setup_db)
    dummy_run = AgentRun(
        id=uuid4(),
        started_at=datetime.now(UTC) - timedelta(hours=1),
        completed_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        execution_mode="OFFLINE_SIM",
    )
    run_repo.save(dummy_run)

    snapshot_repo = EquitySnapshotRepository(setup_db)
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
    return sample_thesis


async def run_orchestrator_once(db_path, settings, asset_filter=None, force=False):
    """오케스트레이터 run_once 실행 헬퍼."""
    orchestrator = create_orchestrator(db_path, settings)
    return await orchestrator.run_once(asset_filter=asset_filter, force=force)


def test_run_once_offline_sim_no_thesis(setup_db, settings):
    """논문이 없는 경우 run-once 실행 (NO_TRADE 예상)."""
    import asyncio

    result = asyncio.run(run_orchestrator_once(setup_db, settings, force=True))

    assert result.status == RunStatus.COMPLETED
    assert result.decision_outcome.value == "NO_TRADE"
    assert result.orders_created == 0
    assert result.orders_filled == 0
    assert result.error is None


def test_run_once_offline_sim_with_thesis(setup_db, settings, sample_thesis_with_snapshot):
    """논문이 있는 경우 run-once 실행."""
    import asyncio

    result = asyncio.run(run_orchestrator_once(setup_db, settings, force=True))

    assert result.status == RunStatus.COMPLETED
    # 논문이 있으면 TRADE 또는 NO_TRADE 가능
    assert result.decision_outcome.value in ("TRADE", "NO_TRADE")
    assert result.error is None


def test_run_once_blocked_without_force(setup_db, settings, sample_thesis_with_snapshot):
    """force=False일 때 중복 실행 차단 (동시 실행 시)."""
    import asyncio

    orchestrator = create_orchestrator(setup_db, settings)

    # 두 실행을 동시에 시작 - 첫 번째가 잠금을 얻고 두 번째는 차단됨
    async def run_twice():
        task1 = asyncio.create_task(orchestrator.run_once(force=False))
        # 약간의 지연으로 첫 번째가 잠금을 얻도록 함
        await asyncio.sleep(0.01)
        task2 = asyncio.create_task(orchestrator.run_once(force=False))

        result1 = await task1
        result2 = await task2
        return result1, result2

    result1, result2 = asyncio.run(run_twice())

    # 하나는 성공, 하나는 차단
    statuses = {result1.status, result2.status}
    assert RunStatus.COMPLETED in statuses
    assert RunStatus.SKIPPED_ALREADY_RUNNING in statuses


def test_run_once_force_overrides_lock(setup_db, settings, sample_thesis_with_snapshot):
    """force=True로 잠금 무시하고 실행."""
    import asyncio

    orchestrator = create_orchestrator(setup_db, settings)

    # 첫 번째 실행
    result1 = asyncio.run(orchestrator.run_once(force=True))
    assert result1.status == RunStatus.COMPLETED

    # force=True로 두 번째 실행 - 성공해야 함
    result2 = asyncio.run(orchestrator.run_once(force=True))
    assert result2.status == RunStatus.COMPLETED
    assert result2.run_id != result1.run_id


def test_run_once_asset_filter(setup_db, settings, sample_thesis_with_snapshot):
    """자산 필터 테스트."""
    import asyncio

    # 일치하는 필터
    result1 = asyncio.run(run_orchestrator_once(
        setup_db, settings, asset_filter=["KRX:005930"], force=True
    ))
    assert result1.status == RunStatus.COMPLETED

    # 일치하지 않는 필터
    result2 = asyncio.run(run_orchestrator_once(
        setup_db, settings, asset_filter=["KRX:000660"], force=True
    ))
    assert result2.status == RunStatus.COMPLETED
    assert result2.decision_outcome.value == "NO_TRADE"


def test_run_once_creates_run_record(setup_db, settings, sample_thesis_with_snapshot):
    """run-once 실행 시 DB에 기록 생성."""
    import asyncio

    run_repo = AgentRunRepository(setup_db)

    result = asyncio.run(run_orchestrator_once(setup_db, settings, force=True))

    # DB에서 실행 기록 조회
    run = run_repo.get(result.run_id)
    assert run is not None
    assert run.status == RunStatus.COMPLETED
    assert run.execution_mode == "OFFLINE_SIM"
    assert run.completed_at is not None
    assert len(run.thesis_ids) >= 1


def test_run_once_multiple_runs_independent(setup_db, settings, sample_thesis_with_snapshot):
    """여러 실행이 독립적으로 수행됨."""
    import asyncio

    orchestrator = create_orchestrator(setup_db, settings)

    results = []
    for _ in range(3):
        result = asyncio.run(orchestrator.run_once(force=True))
        results.append(result)
        assert result.status == RunStatus.COMPLETED

    # 모든 실행 ID가 달라야 함
    run_ids = [r.run_id for r in results]
    assert len(set(run_ids)) == 3

    # DB에 3개 기록
    run_repo = AgentRunRepository(setup_db)
    all_runs = run_repo.get_latest(10)
    assert len(all_runs) >= 3


def test_health_check_after_run(settings):
    """실행 후 헬스 체크."""
    import asyncio
    import tempfile
    from decimal import Decimal
    from pathlib import Path
    from uuid import uuid4

    from invest_agent.domain.models import AgentRun, EquitySnapshot, RunStatus, Thesis
    from invest_agent.operations.health import check_health
    from invest_agent.runtime.orchestrator import create_orchestrator
    from invest_agent.storage.repositories import (
        AgentRunRepository,
        EquitySnapshotRepository,
        ThesisRepository,
    )
    from invest_agent.storage.schema import ensure_db

    # 별도 DB 사용
    tmp = Path(tempfile.mkdtemp())
    db_path = str(tmp / 'test.db')
    ensure_db(db_path)

    # 논문 및 스냅샷 설정
    thesis_repo = ThesisRepository(db_path)
    thesis = Thesis(
        id=uuid4(),
        asset_id="KRX:005930",
        hypothesis="Test hypothesis",
        rationale="Test rationale",
        created_at=datetime.now(UTC) - timedelta(days=1),
        updated_at=datetime.now(UTC) - timedelta(days=1),
        is_active=True,
    )
    thesis_repo.save(thesis)

    # 더미 런 및 스냅샷 생성
    run_repo = AgentRunRepository(db_path)
    dummy_run = AgentRun(
        id=uuid4(),
        started_at=datetime.now(UTC) - timedelta(hours=1),
        completed_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        execution_mode="OFFLINE_SIM",
    )
    run_repo.save(dummy_run)

    snapshot_repo = EquitySnapshotRepository(db_path)
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

    # 실행 전 헬스 체크
    health_before = check_health(db_path, settings)
    assert health_before.is_healthy
    assert health_before.last_run_status == "COMPLETED"  # 더미 런이 있음

    # 실행
    orchestrator = create_orchestrator(db_path, settings)
    asyncio.run(orchestrator.run_once(force=True))

    # 실행 후 헬스 체크
    health_after = check_health(db_path, settings)
    assert health_after.is_healthy
    assert health_after.last_run_status == "COMPLETED"
    assert health_after.last_run_at is not None
