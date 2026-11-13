"""헬스 체크 - 시스템 상태 검증."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from invest_agent.broker.protocol import BrokerProtocol
from invest_agent.settings import Settings
from invest_agent.storage.repositories import AgentRunRepository
from invest_agent.storage.schema import ensure_db


@dataclass
class HealthStatus:
    """헬스 체크 결과."""
    is_healthy: bool
    broker_connected: bool
    db_accessible: bool
    last_run_status: str | None
    last_run_at: datetime | None
    error: str | None = None


def check_health(
    db_path: str,
    settings: Settings,
    broker: BrokerProtocol | None = None,
) -> HealthStatus:
    """전체 시스템 헬스 체크 수행."""
    errors = []
    db_ok = False
    last_run_status = None
    last_run_at = None

    try:
        # 모듈 레벨에서 이미 import됨
        ensure_db(db_path)
        run_repo = AgentRunRepository(db_path)
        recent = run_repo.get_latest(1)
        if recent:
            last_run_status = recent[0].status.value
            last_run_at = recent[0].started_at
        db_ok = True
    except Exception as e:
        errors.append(f"DB error: {e}")
        db_ok = False

    broker_ok = False
    if broker:
        try:
            broker_ok = broker.health_check()
        except Exception as e:
            errors.append(f"Broker error: {e}")

    is_healthy = db_ok and (broker_ok or broker is None) and len(errors) == 0

    return HealthStatus(
        is_healthy=is_healthy,
        broker_connected=broker_ok,
        db_accessible=db_ok,
        last_run_status=last_run_status,
        last_run_at=last_run_at,
        error="; ".join(errors) if errors else None,
    )
