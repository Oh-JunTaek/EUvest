"""헬스 체크 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from invest_agent.broker.mock_broker import MockBroker
from invest_agent.domain.enums import RunStatus
from invest_agent.domain.models import AgentRun
from invest_agent.operations.health import HealthStatus, check_health
from invest_agent.settings import Settings
from invest_agent.storage.repositories import AgentRunRepository
from invest_agent.storage.schema import ensure_db


def test_health_check_db_only(tmp_path):
    """DB만 있는 경우 헬스 체크 성공."""
    db_path = str(tmp_path / 'test.db')
    settings = Settings()
    ensure_db(db_path)

    # 최근 실행 기록 추가
    run_repo = AgentRunRepository(db_path)
    run = AgentRun(
        id=uuid4(),
        started_at=datetime.now(UTC),
        status=RunStatus.COMPLETED,
        execution_mode='OFFLINE_SIM',
    )
    run_repo.save(run)

    result = check_health(db_path, settings, broker=None)

    assert isinstance(result, HealthStatus)
    assert result.is_healthy is True
    assert result.db_accessible is True
    assert result.broker_connected is False  # broker가 없음
    assert result.last_run_status == 'COMPLETED'
    assert result.last_run_at is not None
    assert result.error is None


def test_health_check_with_mock_broker(tmp_path):
    """MockBroker와 함께 헬스 체크 성공."""
    db_path = str(tmp_path / 'test.db')
    settings = Settings()
    ensure_db(db_path)

    broker = MockBroker(initial_cash=100000000)

    result = check_health(db_path, settings, broker=broker)

    assert result.is_healthy is True
    assert result.db_accessible is True
    assert result.broker_connected is True
    assert result.error is None


def test_health_check_db_error(tmp_path):
    """DB 접근 실패 시 헬스 체크 실패 (ensure_db 예외 발생 시뮬레이션)."""
    db_path = str(tmp_path / 'test.db')
    settings = Settings()

    # ensure_db가 예외를 발생시키도록 모킹
    with patch('invest_agent.operations.health.ensure_db', side_effect=PermissionError("Permission denied")):
        result = check_health(db_path, settings, broker=None)

    assert result.is_healthy is False
    assert result.db_accessible is False
    assert result.error is not None
    assert 'DB error' in result.error


def test_health_check_no_recent_runs(tmp_path):
    """최근 실행 기록이 없는 경우."""
    db_path = str(tmp_path / 'test.db')
    settings = Settings()
    ensure_db(db_path)

    result = check_health(db_path, settings, broker=None)

    assert result.is_healthy is True
    assert result.last_run_status is None
    assert result.last_run_at is None
