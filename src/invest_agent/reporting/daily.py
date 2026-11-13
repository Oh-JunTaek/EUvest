"""일일 리포트 생성 - Markdown 형식."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from invest_agent.storage.repositories import (
    AgentRunRepository,
    DecisionRepository,
    EquitySnapshotRepository,
    OrderRepository,
)


@dataclass
class RunSummary:
    """단일 실행 요약."""
    run_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: str
    execution_mode: str
    decision_outcome: str
    orders_created: int
    orders_filled: int
    error: str | None
    thesis_count: int
    decision_count: int


@dataclass
class DailyReport:
    """일일 리포트."""
    date: str
    generated_at: datetime
    total_runs: int
    successful_runs: int
    failed_runs: int
    blocked_runs: int
    total_orders_created: int
    total_orders_filled: int
    total_decisions: int
    run_summaries: list[RunSummary]
    errors: list[str]


def generate_daily_report(
    db_path: str,
    target_date: datetime | None = None,
) -> DailyReport:
    """일일 리포트 생성.

    Args:
        db_path: SQLite DB 경로
        target_date: 대상 날짜 (기본값: 오늘 UTC)

    Returns:
        DailyReport 객체
    """
    if target_date is None:
        target_date = datetime.now(UTC)

    date_str = target_date.date().isoformat()

    run_repo = AgentRunRepository(db_path)
    decision_repo = DecisionRepository(db_path)
    order_repo = OrderRepository(db_path)
    EquitySnapshotRepository(db_path)

    # 해당 날짜의 실행 기록 조회
    runs = run_repo.get_by_date(target_date)

    run_summaries = []
    errors = []
    total_orders_created = 0
    total_orders_filled = 0
    total_decisions = 0
    successful_runs = 0
    failed_runs = 0
    blocked_runs = 0

    for run in runs:
        # 결정 조회
        decisions = decision_repo.get_by_run(run.id)
        decision_count = len(decisions)
        total_decisions += decision_count

        # 주문 조회
        orders = order_repo.get_by_run(run.id)
        orders_created = len(orders)
        orders_filled = sum(1 for o in orders if o.status.value == "FILLED")
        total_orders_created += orders_created
        total_orders_filled += orders_filled

        # 논문 수
        thesis_count = len(run.thesis_ids)

        # 결정 결과 (가장 최근 결정 기준)
        decision_outcome = "NONE"
        if decisions:
            decision_outcome = decisions[-1].outcome.value

        summary = RunSummary(
            run_id=run.id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status.value,
            execution_mode=run.execution_mode,
            decision_outcome=decision_outcome,
            orders_created=orders_created,
            orders_filled=orders_filled,
            error=run.error,
            thesis_count=thesis_count,
            decision_count=decision_count,
        )
        run_summaries.append(summary)

        # 상태별 카운트
        if run.status.value == "COMPLETED":
            successful_runs += 1
        elif run.status.value == "BLOCKED":
            blocked_runs += 1
        elif run.status.value in ("RECOVERY_REQUIRED", "ERROR"):
            failed_runs += 1
            if run.error:
                errors.append(f"Run {run.id}: {run.error}")

    total_runs = len(runs)

    return DailyReport(
        date=date_str,
        generated_at=datetime.now(UTC),
        total_runs=total_runs,
        successful_runs=successful_runs,
        failed_runs=failed_runs,
        blocked_runs=blocked_runs,
        total_orders_created=total_orders_created,
        total_orders_filled=total_orders_filled,
        total_decisions=total_decisions,
        run_summaries=run_summaries,
        errors=errors,
    )


def format_daily_report_markdown(report: DailyReport) -> str:
    """일일 리포트를 Markdown 문자열로 포맷팅."""
    lines = [
        f"# 일일 투자 리포트 - {report.date}",
        "",
        f"**생성 시각:** {report.generated_at.isoformat()}",
        "",
        "## 요약",
        "",
        "| 지표 | 값 |",
        "|------|-----|",
        f"| 총 실행 횟수 | {report.total_runs} |",
        f"| 성공 (COMPLETED) | {report.successful_runs} |",
        f"| 실패 (FAILED/ERROR) | {report.failed_runs} |",
        f"| 차단 (BLOCKED) | {report.blocked_runs} |",
        f"| 총 결정 수 | {report.total_decisions} |",
        f"| 생성된 주문 | {report.total_orders_created} |",
        f"| 체결된 주문 | {report.total_orders_filled} |",
        "",
    ]

    if report.run_summaries:
        lines.append("## 실행 상세")
        lines.append("")
        lines.append("| 실행 ID | 시작 시각 | 상태 | 모드 | 결정 결과 | 논문 수 | 결정 수 | 주문(생성/체결) | 에러 |")
        lines.append("|---------|-----------|------|------|-----------|---------|---------|------------------|------|")

        for run in report.run_summaries:
            started = run.started_at.strftime("%H:%M:%S") if run.started_at else "-"
            run.completed_at.strftime("%H:%M:%S") if run.completed_at else "-"
            error_str = run.error[:50] + "..." if run.error and len(run.error) > 50 else (run.error or "-")

            lines.append(
                f"| {str(run.run_id)[:8]}... | {started} | {run.status} | "
                f"{run.execution_mode} | {run.decision_outcome} | "
                f"{run.thesis_count} | {run.decision_count} | "
                f"{run.orders_created}/{run.orders_filled} | {error_str} |"
            )
        lines.append("")

    if report.errors:
        lines.append("## 에러 요약")
        lines.append("")
        for err in report.errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines)


def save_daily_report(
    db_path: str,
    target_date: datetime | None = None,
    output_path: str | None = None,
) -> str:
    """일일 리포트 생성 후 파일로 저장.

    Args:
        db_path: SQLite DB 경로
        target_date: 대상 날짜
        output_path: 출력 파일 경로 (None이면 자동 생성)

    Returns:
        저장된 파일 경로
    """
    report = generate_daily_report(db_path, target_date)
    markdown = format_daily_report_markdown(report)

    if output_path is None:
        date_str = (target_date or datetime.now(UTC)).date().isoformat()
        output_path = f"reports/daily_{date_str}.md"

    from pathlib import Path
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return output_path
