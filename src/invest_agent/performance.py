"""포트폴리오 성과 분석 모듈.

스냅샷과 입출금 원장을 결합하여 입출금 조정된 성과를 계산한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path


@dataclass(slots=True)
class PerformanceInterval:
    """성과 분석 구간."""

    start_snapshot: object
    end_snapshot: object
    start_cashflows: list
    end_cashflows: list

    start_value: Decimal
    end_value: Decimal
    total_deposits_krw: Decimal
    total_withdrawals_krw: Decimal
    net_external_flow: Decimal
    weighted_external_flow: Decimal
    adjusted_change: Decimal | None
    period_return_pct: Decimal | None
    calculable: bool
    non_calculable_reasons: list[str]


def _sum_cashflows_by_currency(cashflows: list, currency: str) -> tuple[Decimal, Decimal]:
    """특정 통화의 입금/출금 합계.

    Args:
        cashflows: 현금흐름 리스트
        currency: 통화 코드 (KRW, USD)

    Returns:
        (총입금액, 총출금액)
    """
    deposits = Decimal("0")
    withdrawals = Decimal("0")
    for cf in cashflows:
        if cf.currency == currency:
            if cf.flow_type == "DEPOSIT":
                deposits += cf.amount
            elif cf.flow_type == "WITHDRAWAL":
                withdrawals += cf.amount
    return deposits, withdrawals


def _calculate_modified_dietz_return(
    start_value: Decimal,
    end_value: Decimal,
    cashflows: list,
    start_time: datetime,
    end_time: datetime,
) -> tuple[Decimal | None, Decimal | None, list[str]]:
    """Modified Dietz 방식 기간 수익률 계산.

    Args:
        start_value: 기간 시작 평가액
        end_value: 기간 종료 평가액
        cashflows: 구간 내 현금흐름 리스트 (start < cf <= end)
        start_time: 구간 시작 시각
        end_time: 구간 종료 시각

    Returns:
        (period_return_pct, weighted_external_flow, non_calculable_reasons)
        계산 불가 시 (None, None, reasons)
    """
    reasons = []

    # 총 기간 (초 단위)
    total_seconds = (end_time - start_time).total_seconds()
    if total_seconds <= 0:
        reasons.append("구간 길이가 0 이하")
        return None, None, reasons

    # 가중 외부 현금흐름 계산
    weighted_flow = Decimal("0")
    for cf in cashflows:
        if cf.currency != "KRW":
            continue
        # 현금흐름 발생 이후 남은 기간의 비율
        elapsed = (cf.occurred_at - start_time).total_seconds()
        if elapsed < 0:
            elapsed = Decimal("0")
        weight = Decimal(str(1 - elapsed / total_seconds))
        if cf.flow_type == "DEPOSIT":
            weighted_flow += cf.amount * weight
        elif cf.flow_type == "WITHDRAWAL":
            weighted_flow -= cf.amount * weight

    # 분모: 시작 평가액 + 가중 외부 현금흐름
    denominator = start_value + weighted_flow

    if denominator <= 0:
        reasons.append("분모가 0 이하 (시작 평가액 + 가중 외부 현금흐름)")
        return None, None, reasons

    # 분자: 종료 평가액 - 시작 평가액 - 순 외부 현금흐름 (KRW만)
    net_external_flow_krw = Decimal("0")
    for cf in cashflows:
        if cf.currency == "KRW":
            if cf.flow_type == "DEPOSIT":
                net_external_flow_krw += cf.amount
            elif cf.flow_type == "WITHDRAWAL":
                net_external_flow_krw -= cf.amount

    numerator = end_value - start_value - net_external_flow_krw

    # 수익률 계산 (소수점 4자리까지)
    period_return = (numerator / denominator * Decimal("100")).quantize(Decimal("0.0001"))

    return period_return, weighted_flow.quantize(Decimal("0.01")), []


def _check_snapshot_completeness(snapshot: object) -> tuple[bool, list[str]]:
    """스냅샷 완전성 검증.

    Args:
        snapshot: 포트폴리오 스냅샷

    Returns:
        (완전여부, 불완전사유리스트)
    """
    reasons = []
    if not snapshot.equity_complete:
        reasons.append("평가 불완전(equity_complete=False)")
    if snapshot.total_equity < 0:
        reasons.append("총평가액이 음수")
    return len(reasons) == 0, reasons


def analyze_portfolio_performance(
    db_path: str,
    limit: int = 30,
) -> list[PerformanceInterval]:
    """포트폴리오 성과 분석.

    연속된 두 스냅샷 구간별로 입출금 조정 성과를 계산한다.

    Args:
        db_path: SQLite DB 경로
        limit: 분석할 구간 수 (기본값: 30)

    Returns:
        최신순으로 정렬된 PerformanceInterval 리스트
    """
    from invest_agent.storage.repositories import (
        CashFlowRepository,
        PortfolioSnapshotRepository,
    )

    # DB 파일 확인
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DB 파일이 없습니다: {db_path}")

    # 리포지토리 초기화
    snapshot_repo = PortfolioSnapshotRepository(db_path)
    cashflow_repo = CashFlowRepository(db_path)

    # 전체 스냅샷 조회 (최신순)
    snapshots = snapshot_repo.get_all()
    if len(snapshots) < 2:
        return []

    # 전체 입출금 조회 (최신순)
    cashflows = cashflow_repo.get_all()
    cashflows_sorted = sorted(cashflows, key=lambda cf: cf.occurred_at, reverse=True)

    intervals = []

    # 스냅샷은 이미 최신순으로 정렬되어 있음 (get_all() 반환)
    for i in range(min(limit, len(snapshots) - 1)):
        end_snap = snapshots[i]

        # 시작 스냅샷 찾기 (더 과거의 스냅샷)
        start_snap = None
        for j in range(i + 1, len(snapshots)):
            if snapshots[j].timestamp < end_snap.timestamp:
                start_snap = snapshots[j]
                break

        if not start_snap:
            break

        # 구간 경계 검증
        if start_snap.timestamp >= end_snap.timestamp:
            continue  # 유효하지 않은 구간 건너뛰기

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
                if cf.flow_type == "DEPOSIT":
                    interval_deposits_krw += cf.amount
                elif cf.flow_type == "WITHDRAWAL":
                    interval_withdrawals_krw += cf.amount

        net_external_flow = interval_deposits_krw - interval_withdrawals_krw
        adjusted_change = end_value - start_value - net_external_flow if calculable else None

        # Modified Dietz 수익률 계산
        weighted_external_flow = Decimal("0")
        period_return_pct = None
        if calculable:
            period_return_pct, weighted_external_flow, dietz_reasons = _calculate_modified_dietz_return(
                start_value=start_value,
                end_value=end_value,
                cashflows=interval_cashflows,
                start_time=start_snap.timestamp,
                end_time=end_snap.timestamp,
            )
            if dietz_reasons:
                calculable = False
                period_return_pct = None
                non_calculable_reasons.extend(dietz_reasons)

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
            weighted_external_flow=weighted_external_flow,
            adjusted_change=adjusted_change,
            period_return_pct=period_return_pct,
            calculable=calculable,
            non_calculable_reasons=non_calculable_reasons,
        )
        intervals.append(interval)

    return intervals


def format_performance_report(intervals: list[PerformanceInterval]) -> str:
    """성과 분석 결과를 사람이 읽기 쉬운 문자열로 포맷.

    Args:
        intervals: 분석 구간 리스트

    Returns:
        포맷된 리포트 문자열
    """
    if not intervals:
        return "분석할 구간이 없습니다. (스냅샷이 2개 미만입니다.)"

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
        lines.append(f"  순외부현금흐름: {interval.net_external_flow:+,} KRW")

        if interval.calculable:
            lines.append(f"  가중 외부 현금흐름: {interval.weighted_external_flow:+,} KRW")
            lines.append(f"  입출금 조정 자산 변화액: {interval.adjusted_change:+,} KRW")
            if interval.period_return_pct is not None:
                lines.append(f"  [green]Modified Dietz 기간 수익률: {interval.period_return_pct:+.4f}%[/green]")
            else:
                lines.append("  [yellow]Modified Dietz 기간 수익률: 계산 불가[/yellow]")
            lines.append("  계산 방법: Modified Dietz (시간 가중 현금흐름)")
        else:
            lines.append("  가중 외부 현금흐름: 계산 불가")
            lines.append("  입출금 조정 자산 변화액: 계산 불가")
            lines.append("  Modified Dietz 기간 수익률: 계산 불가")
            for reason in interval.non_calculable_reasons:
                lines.append(f"    - {reason}")

        lines.append(f"  계산 가능 여부: {'[green]가능[/green]' if interval.calculable else '[yellow]불가능[/yellow]'}")
        lines.append("")

    return "\n".join(lines)
