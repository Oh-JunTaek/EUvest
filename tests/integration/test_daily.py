"""일일 리포트 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from invest_agent.domain.enums import OrderSide, OrderStatus, OrderType, RunStatus
from invest_agent.domain.models import AgentRun, Decision, DecisionOutcome, OrderRecord
from invest_agent.reporting.daily import (
    DailyReport,
    format_daily_report_markdown,
    generate_daily_report,
)
from invest_agent.storage.repositories import (
    AgentRunRepository,
    DecisionRepository,
    OrderRepository,
)
from invest_agent.storage.schema import ensure_db


@pytest.fixture
def setup_db(tmp_path):
    """테스트용 DB 설정."""
    db_path = str(tmp_path / 'test.db')
    ensure_db(db_path)
    return db_path


def test_generate_daily_report_empty(setup_db):
    """실행 기록이 없는 날짜의 리포트 생성."""
    target_date = datetime.now(UTC)
    report = generate_daily_report(setup_db, target_date)

    assert isinstance(report, DailyReport)
    assert report.date == target_date.date().isoformat()
    assert report.total_runs == 0
    assert report.successful_runs == 0
    assert report.failed_runs == 0
    assert report.blocked_runs == 0
    assert report.total_orders_created == 0
    assert report.total_orders_filled == 0
    assert report.total_decisions == 0
    assert len(report.run_summaries) == 0
    assert len(report.errors) == 0


def test_generate_daily_report_with_runs(setup_db):
    """실행 기록이 있는 날짜의 리포트 생성."""
    run_repo = AgentRunRepository(setup_db)
    decision_repo = DecisionRepository(setup_db)
    order_repo = OrderRepository(setup_db)
    from invest_agent.storage.repositories import ThesisRepository
    thesis_repo = ThesisRepository(setup_db)
    from invest_agent.domain.models import Thesis

    # Use a fixed date late in the day to avoid date boundary issues when subtracting hours
    target_date = datetime(2026, 11, 14, 23, 0, 0, tzinfo=UTC)

    # 성공한 실행 1개
    thesis1 = Thesis(
        id=uuid4(),
        asset_id="KRX:005930",
        hypothesis="Test hypothesis",
        rationale="Test rationale",
        created_at=target_date - timedelta(days=1),
        updated_at=target_date - timedelta(days=1),
        is_active=True,
    )
    thesis_repo.save(thesis1)

    run1 = AgentRun(
        id=uuid4(),
        started_at=target_date - timedelta(hours=2),
        completed_at=target_date - timedelta(hours=1),
        status=RunStatus.COMPLETED,
        execution_mode='OFFLINE_SIM',
        thesis_ids=[thesis1.id],
        decision_ids=[uuid4()],
        order_ids=[uuid4()],
    )
    run_repo.save(run1)

    # 결정 추가
    decision1 = Decision(
        id=run1.decision_ids[0],
        thesis_id=thesis1.id,
        run_id=run1.id,
        outcome=DecisionOutcome.TRADE,
        side=OrderSide.BUY,
        target_weight_bps=1000,
        current_weight_bps=0,
        rationale="Test rationale",
        evidence_ids=[],
        model_provider="fake",
        model_name="fixture-default",
        execution_mode="OFFLINE_SIM",
        decided_at=target_date - timedelta(hours=1, minutes=30),
    )
    decision_repo.save(decision1)

    # 주문 추가
    order1 = OrderRecord(
        id=run1.order_ids[0],
        run_id=run1.id,
        decision_id=decision1.id,
        asset_id="KRX:005930",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        price=100000,
        status=OrderStatus.FILLED,
        broker_order_id="mock-1",
        submitted_at=target_date - timedelta(hours=1, minutes=15),
        acknowledged_at=target_date - timedelta(hours=1, minutes=10),
        filled_at=target_date - timedelta(hours=1, minutes=5),
        filled_quantity=10,
        filled_price=100000,
    )
    order_repo.save(order1)

    # 차단된 실행 1개
    run2 = AgentRun(
        id=uuid4(),
        started_at=target_date - timedelta(hours=4),
        completed_at=target_date - timedelta(hours=3),
        status=RunStatus.BLOCKED,
        execution_mode='OFFLINE_SIM',
        thesis_ids=[],
        decision_ids=[],
        order_ids=[],
        error="Another execution is already running",
    )
    run_repo.save(run2)

    # 실패한 실행 1개
    run3 = AgentRun(
        id=uuid4(),
        started_at=target_date - timedelta(hours=6),
        completed_at=target_date - timedelta(hours=5),
        status=RunStatus.RECOVERY_REQUIRED,
        execution_mode='OFFLINE_SIM',
        thesis_ids=[uuid4()],
        decision_ids=[],
        order_ids=[],
        error="DB connection failed",
    )
    run_repo.save(run3)

    report = generate_daily_report(setup_db, target_date)

    assert report.total_runs == 3
    assert report.successful_runs == 1
    assert report.blocked_runs == 1
    assert report.failed_runs == 1
    assert report.total_decisions == 1
    assert report.total_orders_created == 1
    assert report.total_orders_filled == 1
    assert len(report.run_summaries) == 3
    assert len(report.errors) == 1
    assert "DB connection failed" in report.errors[0]


def test_format_daily_report_markdown(setup_db):
    """Markdown 포맷팅 테스트."""
    target_date = datetime.now(UTC)
    report = generate_daily_report(setup_db, target_date)

    markdown = format_daily_report_markdown(report)

    assert f"# 일일 투자 리포트 - {target_date.date().isoformat()}" in markdown
    assert "## 요약" in markdown
    assert "| 총 실행 횟수 | 0 |" in markdown


def test_format_daily_report_markdown_with_runs(setup_db):
    """실행 기록이 있는 리포트 Markdown 포맷팅."""
    run_repo = AgentRunRepository(setup_db)
    target_date = datetime.now(UTC)

    run = AgentRun(
        id=uuid4(),
        started_at=target_date - timedelta(hours=1),
        completed_at=target_date,
        status=RunStatus.COMPLETED,
        execution_mode='OFFLINE_SIM',
        thesis_ids=[uuid4()],
        decision_ids=[uuid4()],
        order_ids=[uuid4()],
    )
    run_repo.save(run)

    report = generate_daily_report(setup_db, target_date)
    markdown = format_daily_report_markdown(report)

    assert "## 실행 상세" in markdown
    assert "| 실행 ID |" in markdown
    assert str(run.id)[:8] in markdown
    assert "COMPLETED" in markdown
