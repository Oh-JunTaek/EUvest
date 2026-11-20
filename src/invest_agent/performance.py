"""포트폴리오 성과 분석 모듈.

OFFLINE_SIM 환경에서 포트폴리오 스냅샷과 입출금 원장을 결합하여
입출금 조정된 자산 변화액을 분석한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from invest_agent.domain.models import CashFlow, CashFlowType, PortfolioSnapshot
from invest_agent.storage.repositories import (
    CashFlowRepository,
    PortfolioSnapshotRepository,
)


@dataclass(slots=True)
class PerformanceInterval:
    """성과 분석 구간."""

    start_snapshot: PortfolioSnapshot
    end_snapshot: PortfolioSnapshot
    start_cashflows: list
    end_cashflows: list

    start_value: Decimal
    end_value: Decimal
    total_deposits_krw: Decimal
    total_withdrawals_krw: Decimal
    net_external_flow: Decimal
    adjusted_change: Decimal | None
    calculable: bool
    non_calculable_reasons: list[str]


def _sum_cashflows_by_currency(cashflows: list[CashFlow], currency: str) -> tuple[Decimal, Decimal]:
    """특정 통화의 입금/출금 합계.

    Returns:
        (total_deposits, total_withdrawals)
    """
    deposits = Decimal("0")
    withdrawals = Decimal("0")
    for cf in cashflows:
        if cf.currency == currency:
            if cf.flow_type == CashFlowType.DEPOSIT:
                deposits += cf.amount
            elif cf.flow_type == CashFlowType.WITHDRAWAL:
                withdrawals += cf.amount
    return deposits, withdrawals


def _check_snapshot_completeness(snapshot: PortfolioSnapshot) -> tuple[bool, list[str]]:
    """스냅샷 완전성 검증.

    Returns:
        (is_complete, reasons_if_incomplete)
    """
    reasons = []
    if not snapshot.equity_complete:
        reasons.append("평가 불완전(equity_complete=False)")
    if snapshot.total_equity < 0:
        reasons.append("총평가액이 음수")
    return len(reasons) == 0, reasons
def analyze_portfolio_performance(
    db_path: str | Path,
    limit: int = 30,
) -> list[PerformanceInterval]:
    """포트폴리오 성과 분석.

    Args:
        db_path: SQLite DB 경로
        limit: 분석할 구간 수 (기본값: 30)

    Returns:
        최신순으로 정렬된 PerformanceInterval 리스트
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DB 파일이 없습니다: {db_path}")

    snapshot_repo = PortfolioSnapshotRepository(db_path)
    cashflow_repo = CashFlowRepository(db_path)

    snapshots = snapshot_repo.get_all()
    if not snapshots:
        return []

    cashflows = cashflow_repo.get_all()
    if not cashflows:
        return []

    # 현금흐름을 occurred_at 기준으로 정렬 (최신순)
    cashflows_sorted = sorted(cashflows, key=lambda cf: cf.occurred_at, reverse=True)

    intervals = []

    # 스냅샷은 이미 최신순으로 정렬되어 있음 (get_all() 반환)
    for i in range(min(limit, len(snapshots))):
        end_snap = snapshots[i]

        # 시작 스냅샷 찾기 (더 과거의 스냅샷)
        start_snap = None
        for j in range(i + 1, len(snapshots)):
            if snapshots[j].timestamp < end_snap.timestamp:
                start_snap = snapshots[j]
                break

        if not start_snap:
            break

        # 구간에 속하는 현금흐름 필터링 (start < cf <= end)
        interval_cashflows = [
            cf for cf in cashflows_sorted
            if start_snap.timestamp < cf.occurred_at <= end_snap.timestamp
        ]

        # 시작 시점 이전의 현금흐름도 순외부현금흐름에 포함
        before_cashflows = [
            cf for cf in cashflows_sorted
            if cf.occurred_at <= start_snap.timestamp
        ]

        # 완전성 검증
        start_complete, start_reasons = _check_snapshot_completeness(start_snap)
        end_complete, end_reasons = _check_snapshot_completeness(end_snap)

        calculable = start_complete and end_complete
        non_calculable_reasons = []
        if not start_complete:
            non_calculable_reasons.append(f"시작 스냅샷 불완전: {', '.join(start_reasons)}")
        if not end_complete:
            non_calculable_reasons.append(f"종료 스냅샷 불완전: {', '.join(end_reasons)}")

        # USD 입출금이 있는 경우 환율 근거 확인
        usd_cashflows = [cf for cf in interval_cashflows if cf.currency == "USD"]
        if usd_cashflows:
            calculable = False
            non_calculable_reasons.append("USD 입출금이 있으나 환율 근거가 없어 KRW 환산 불가")

        # 평가액
        start_value = start_snap.total_equity
        end_value = end_snap.total_equity

        # 구간 내 현금흐름 집계 (KRW만)
        interval_deposits_krw = Decimal("0")
        interval_withdrawals_krw = Decimal("0")
        for cf in interval_cashflows:
            if cf.currency == "KRW":
                if cf.flow_type == CashFlowType.DEPOSIT:
                    interval_deposits_krw += cf.amount
                elif cf.flow_type == CashFlowType.WITHDRAWAL:
                    interval_withdrawals_krw += cf.amount

        net_external_flow = interval_deposits_krw - interval_withdrawals_krw
        adjusted_change = end_value - start_value - net_external_flow if calculable else None

        interval = PerformanceInterval(
            start_snapshot=start_snap,
            end_snapshot=end_snap,
            start_cashflows=before_cashflows,
            end_cashflows=interval_cashflows,
            start_value=start_value,
            end_value=end_value,
            total_deposits_krw=interval_deposits_krw,
            total_withdrawals_krw=interval_withdrawals_krw,
            net_external_flow=net_external_flow,
            adjusted_change=adjusted_change,
            calculable=calculable,
            non_calculable_reasons=non_calculable_reasons,
        )
        intervals.append(interval)

    return intervals


def format_performance_report(intervals: list[PerformanceInterval]) -> str:
    """성과 분석 결과를 사람이 읽기 쉬운 문자열로 포맷."""
    if not intervals:
        return "분석할 구간이 없습니다."

    lines = []
    lines.append("[bold cyan]포트폴리오 성과 분석 (입출금 조정)[/bold cyan]")
    lines.append(f"분석 구간 수: {len(intervals)}개 (최신순)")
    lines.append("")

    for i, interval in enumerate(intervals):
        start_ts = interval.start_snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        end_ts = interval.end_snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        lines.append(f"[bold]구간 {i + 1}: {start_ts} ~ {end_ts}[/bold]")
        lines.append(f"  시작 평가액: {interval.start_value:,.0f} KRW")
        lines.append(f"  종료 평가액: {interval.end_value:,.0f} KRW")
        lines.append(f"  총 입금액: {interval.total_deposits_krw:,.0f} KRW")
        lines.append(f"  총 출금액: {interval.total_withdrawals_krw:,.0f} KRW")
        lines.append(f"  순외부현금흐름: {interval.net_external_flow:+,0f} KRW")

        if interval.calculable:
            lines.append(f"  [green]입출금 조정 자산 변화액: {interval.adjusted_change:+,0f} KRW[/green]")
        else:
            lines.append("  [yellow]입출금 조정 자산 변화액: 계산 불가[/yellow]")
            for reason in interval.non_calculable_reasons:
                lines.append(f"    - {reason}")

        lines.append(f"  계산 가능 여부: {'[green]가능[/green]' if interval.calculable else '[yellow]불가능[/yellow]'}")
        lines.append("")

    return "\n".join(lines)
