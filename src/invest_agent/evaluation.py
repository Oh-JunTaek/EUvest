"""AI 의사결정 사후 평가 모듈.

AI가 기록한 의사결정(BUY, SELL, NO_TRADE)을 사후 시장 가격과 비교하여
방향 적중률과 가격 변화율을 계산한다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from invest_agent.domain.models import Decision, DecisionOutcome, OrderSide
from invest_agent.market.calendar import get_calendar
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.storage.repositories import (
    DecisionRepository,
    OHLCVRepository,
    ThesisRepository,
)


class EvaluationStatus(StrEnum):
    """평가 상태."""
    COMPLETED = "COMPLETED"       # 정상 평가 완료
    PENDING = "PENDING"           # 필요 데이터가 미래에 확정됨
    UNAVAILABLE = "UNAVAILABLE"   # 필요 데이터 없음
    INVALID = "INVALID"           # 잘못된 데이터 (가격 0 이하 등)
    EXCLUDED = "EXCLUDED"         # 방향 적중률 비대상 (NO_TRADE, BLOCKED, ERROR)


@dataclass(slots=True, frozen=True)
class HorizonEvaluation:
    """단일 평가 기간(1D/5D/20D) 결과."""

    horizon_days: int
    price: Decimal | None
    price_date: str | None
    return_pct: Decimal | None
    hit: bool | None  # True=적중, False=미적중, None=중립/제외/대기
    status: EvaluationStatus
    reason: str | None


@dataclass(slots=True, frozen=True)
class DecisionEvaluation:
    """단일 의사결정 평가 결과."""

    decision_id: UUID
    thesis_id: UUID
    asset_id: str
    model_provider: str
    model_name: str
    outcome: DecisionOutcome
    side: OrderSide | None
    decided_at: datetime

    base_price: Decimal | None
    base_price_date: str | None
    base_price_provider: str | None

    horizon_1d: HorizonEvaluation
    horizon_5d: HorizonEvaluation
    horizon_20d: HorizonEvaluation

    # 전체 평가 가능 여부 (모든 기간이 COMPLETED인 경우)
    evaluable: bool
    # 각 기간별 평가 불가 사유
    non_evaluable_reasons: list[str]


@dataclass(slots=True, frozen=True)
class ModelEvaluationSummary:
    """모델별 평가 요약."""

    model_provider: str
    model_name: str
    total_decisions: int
    buy_count: int
    sell_count: int
    no_trade_count: int
    blocked_count: int
    error_count: int

    evaluated_count: int
    pending_count: int
    unevaluable_count: int

    buy_hit_rate_1d: Decimal | None
    sell_hit_rate_1d: Decimal | None
    total_hit_rate_1d: Decimal | None
    hit_rate_1d_denominator: int

    buy_hit_rate_5d: Decimal | None
    sell_hit_rate_5d: Decimal | None
    total_hit_rate_5d: Decimal | None
    hit_rate_5d_denominator: int

    buy_hit_rate_20d: Decimal | None
    sell_hit_rate_20d: Decimal | None
    total_hit_rate_20d: Decimal | None
    hit_rate_20d_denominator: int

    avg_return_1d: Decimal | None
    avg_return_5d: Decimal | None
    avg_return_20d: Decimal | None

    non_evaluable_reasons: list[str]


EVALUATION_HORIZONS = (1, 5, 20)
HORIZON_LABELS = {1: "1d", 5: "5d", 20: "20d"}

MARKET_CLOSE_UTC = {
    "KRX": time(6, 30),
    "US": time(21, 0),
}


def _is_us_dst(dt: datetime) -> bool:
    """미국 DST(서머타임) 적용 여부 판단."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    year = dt.year
    march_start = datetime(year, 3, 8)
    days_until_sunday = (6 - march_start.weekday()) % 7
    dst_start = march_start + timedelta(days=days_until_sunday)
    dst_start = datetime.combine(dst_start, time(7, 0))
    nov_start = datetime(year, 11, 1)
    days_until_sunday = (6 - nov_start.weekday()) % 7
    dst_end_date = nov_start + timedelta(days=days_until_sunday)
    dst_end = datetime.combine(dst_end_date, time(6, 0))
    return dst_start <= dt < dst_end


def _get_market_close_utc(market: str, trade_date: str) -> datetime:
    """시장별 종가 확정 시각(UTC) 계산."""
    base_date = datetime.fromisoformat(trade_date).date()
    if market == "US":
        check_dt = datetime.combine(base_date, time(0, 0), tzinfo=UTC)
        if _is_us_dst(check_dt):
            close_time = time(20, 0)
        else:
            close_time = time(21, 0)
    else:
        close_time = MARKET_CLOSE_UTC.get(market, time(0, 0))
    return datetime.combine(base_date, close_time).replace(tzinfo=UTC)


def _get_nth_trading_day(
    repo: OHLCVRepository,
    asset_id: str,
    start_date: str,
    n: int,
    provider: str | None = None,
) -> tuple[str | None, Decimal | None]:
    """기준일로부터 N번째 유효 거래일의 날짜와 종가 반환.

    N=1이면 기준일 다음 거래일, N=5이면 5번째 거래일.
    시장 캘린더 기준으로 주말/휴장일 제외된 실제 거래일만 카운트.
    """
    market = Market.KRX if asset_id.startswith("KRX:") else Market.US
    calendar = get_calendar(market)

    # 검색 범위: 넉넉하게 50일 + 버퍼
    end_search = (date.fromisoformat(start_date) + timedelta(days=80)).isoformat()
    ohlcv_list = repo.get_range(asset_id, start_date, end_search, provider=provider)
    if not ohlcv_list:
        return None, None

    # OHLCV 데이터가 있는 날짜만 거래일로 간주 (캘린더와 결합)
    ohlcv_dates = {ohlcv.timestamp.date() for ohlcv in ohlcv_list}
    current = date.fromisoformat(start_date)
    count = 0
    max_iterations = 200  # 최대 200일까지 검색 (안전장치)

    while count < n and max_iterations > 0:
        current = date.fromordinal(current.toordinal() + 1)
        max_iterations -= 1
        if current not in ohlcv_dates:
            continue
        if not calendar.is_business_day(current):
            continue
        count += 1
        if count == n:
            # 해당 날짜의 OHLCV 찾기
            for ohlcv in ohlcv_list:
                if ohlcv.timestamp.date() == current:
                    return current.isoformat(), ohlcv.close
            break

    return None, None


def _check_price_confirmation_time(
    ohlcv: OHLCV | None,
    as_of: datetime,
    boundary_label: str,
    reasons: list[str],
) -> bool:
    """종가 확정 시각 검증 - as_of 기준으로 확인."""
    if ohlcv is None:
        return False
    market_close_utc = _get_market_close_utc(ohlcv.market.value, ohlcv.timestamp.date().isoformat())
    if as_of < market_close_utc:
        reasons.append(
            f"{boundary_label}: 종가 확정 시각({market_close_utc.isoformat()}) 이후 평가 필요 "
            f"(평가 기준: {as_of.isoformat()})"
        )
        return False
    return True


def _evaluate_single_horizon(
    decision: Decision,
    base_price: Decimal,
    base_price_date: str,
    base_price_provider: str | None,
    horizon_days: int,
    repo: OHLCVRepository,
    asset_id: str,
    provider: str | None,
    as_of: datetime,
) -> HorizonEvaluation:
    """단일 평가 기간(1D/5D/20D) 평가."""
    # NO_TRADE, BLOCKED, ERROR는 방향 적중률 평가 제외
    if decision.outcome != DecisionOutcome.TRADE or decision.side is None:
        return HorizonEvaluation(
            horizon_days=horizon_days,
            price=None,
            price_date=None,
            return_pct=None,
            hit=None,
            status=EvaluationStatus.EXCLUDED,
            reason=f"방향 적중률 평가 제외: {decision.outcome.value}",
        )

    # N번째 거래일 종가 조회
    price_date, price = _get_nth_trading_day(repo, asset_id, base_price_date, horizon_days, provider=provider)

    if price is None or price_date is None:
        return HorizonEvaluation(
            horizon_days=horizon_days,
            price=None,
            price_date=None,
            return_pct=None,
            hit=None,
            status=EvaluationStatus.UNAVAILABLE,
            reason=f"{horizon_days}거래일 후 가격 데이터 없음",
        )

    # 평가 대상 종가의 확정 시각 검증
    eval_ohlcv, _ = _get_closest_ohlcv(
        repo, asset_id,
        datetime.fromisoformat(price_date + "T00:00:00").replace(tzinfo=UTC),
        provider=provider
    )
    reasons: list[str] = []
    if not _check_price_confirmation_time(eval_ohlcv, as_of, f"{horizon_days}거래일 후 평가", reasons):
        return HorizonEvaluation(
            horizon_days=horizon_days,
            price=None,
            price_date=price_date,
            return_pct=None,
            hit=None,
            status=EvaluationStatus.PENDING,
            reason=reasons[0] if reasons else f"{horizon_days}거래일 후 평가: 종가 확정 시각 이후 평가 필요",
        )

    # 가격 변화율 계산
    return_pct = ((price / base_price - Decimal("1")) * Decimal("100")).quantize(Decimal("0.0001"))

    # 적중 여부 판단
    hit: bool | None = None
    if decision.side == OrderSide.BUY:
        if return_pct > Decimal("0"):
            hit = True
        elif return_pct < Decimal("0"):
            hit = False
        else:
            hit = None  # NEUTRAL
    elif decision.side == OrderSide.SELL:
        if return_pct < Decimal("0"):
            hit = True
        elif return_pct > Decimal("0"):
            hit = False
        else:
            hit = None  # NEUTRAL

    return HorizonEvaluation(
        horizon_days=horizon_days,
        price=price,
        price_date=price_date,
        return_pct=return_pct,
        hit=hit,
        status=EvaluationStatus.COMPLETED,
        reason=None,
    )


def _get_closest_ohlcv(
    repo: OHLCVRepository,
    asset_id: str,
    target_dt: datetime,
    provider: str | None = None,
    max_days_back: int = 10,
) -> tuple[OHLCV | None, str | None]:
    """기준 시점 이전/당일의 가장 가까운 OHLCV 조회."""
    target_date = target_dt.date().isoformat()
    search_start = (target_dt - timedelta(days=max_days_back)).date().isoformat()
    ohlcv_list = repo.get_range(asset_id, search_start, target_date, provider=provider)
    if not ohlcv_list:
        return None, None
    for ohlcv in ohlcv_list:
        if ohlcv.timestamp.date() <= target_dt.date():
            return ohlcv, ohlcv.timestamp.date().isoformat()
    return None, None


def evaluate_decision(
    decision: Decision,
    thesis_repo: ThesisRepository,
    ohlcv_repo: OHLCVRepository,
    horizons: tuple[int, ...] = EVALUATION_HORIZONS,
    max_freshness_days: int = 10,
    max_days_back: int = 10,
    as_of: datetime | None = None,
    provider: str | None = None,
) -> DecisionEvaluation:
    """단일 의사결정 평가.

    Args:
        decision: 평가할 의사결정
        thesis_repo: 가설 리포지토리
        ohlcv_repo: OHLCV 리포지토리
        horizons: 평가 기간 (거래일 단위)
        max_freshness_days: 데이터 최대 경과 일수
        max_days_back: 과거 데이터 검색 범위
        as_of: 평가 기준 시점 (기본값: 현재 UTC). 이 시점 이후 확정되는 가격은 사용하지 않음.
        provider: OHLCV 공급자 지정. 지정 시 해당 공급자 데이터만 사용.
    """
    thesis = thesis_repo.get(decision.thesis_id)
    if not thesis:
        return DecisionEvaluation(
            decision_id=decision.id,
            thesis_id=decision.thesis_id,
            asset_id="",
            model_provider=decision.model_provider,
            model_name=decision.model_name,
            outcome=decision.outcome,
            side=decision.side,
            decided_at=decision.decided_at,
            base_price=None,
            base_price_date=None,
            base_price_provider=None,
            horizon_1d=HorizonEvaluation(1, None, None, None, None, EvaluationStatus.UNAVAILABLE, "Thesis를 찾을 수 없음"),
            horizon_5d=HorizonEvaluation(5, None, None, None, None, EvaluationStatus.UNAVAILABLE, "Thesis를 찾을 수 없음"),
            horizon_20d=HorizonEvaluation(20, None, None, None, None, EvaluationStatus.UNAVAILABLE, "Thesis를 찾을 수 없음"),
            evaluable=False,
            non_evaluable_reasons=["Thesis를 찾을 수 없음"],
        )

    asset_id = thesis.asset_id
    decided_at = decision.decided_at

    # as_of가 없으면 현재 UTC 사용
    if as_of is None:
        as_of = datetime.now(UTC)

    # 기준 가격 조회 (결정 시점 이전/당일 가장 가까운 종가)
    base_ohlcv, base_price_date = _get_closest_ohlcv(
        ohlcv_repo, asset_id, decided_at, provider=provider, max_days_back=max_days_back
    )

    base_price = None
    base_price_provider = None
    if base_ohlcv:
        base_price = base_ohlcv.close
        base_price_provider = base_ohlcv.provider

    # 기준 가격 검증
    if base_price is None or base_price <= Decimal("0"):
        return DecisionEvaluation(
            decision_id=decision.id,
            thesis_id=decision.thesis_id,
            asset_id=asset_id,
            model_provider=decision.model_provider,
            model_name=decision.model_name,
            outcome=decision.outcome,
            side=decision.side,
            decided_at=decided_at,
            base_price=base_price,
            base_price_date=base_price_date,
            base_price_provider=base_price_provider,
            horizon_1d=HorizonEvaluation(1, None, None, None, None, EvaluationStatus.INVALID, "기준 가격 없음 또는 0 이하"),
            horizon_5d=HorizonEvaluation(5, None, None, None, None, EvaluationStatus.INVALID, "기준 가격 없음 또는 0 이하"),
            horizon_20d=HorizonEvaluation(20, None, None, None, None, EvaluationStatus.INVALID, "기준 가격 없음 또는 0 이하"),
            evaluable=False,
            non_evaluable_reasons=["기준 가격 없음 또는 0 이하"],
        )

    # 기준 가격의 확정 시각 검증
    base_reasons: list[str] = []
    if not _check_price_confirmation_time(base_ohlcv, as_of, "기준 가격", base_reasons):
        return DecisionEvaluation(
            decision_id=decision.id,
            thesis_id=decision.thesis_id,
            asset_id=asset_id,
            model_provider=decision.model_provider,
            model_name=decision.model_name,
            outcome=decision.outcome,
            side=decision.side,
            decided_at=decided_at,
            base_price=base_price,
            base_price_date=base_price_date,
            base_price_provider=base_price_provider,
            horizon_1d=HorizonEvaluation(1, None, None, None, None, EvaluationStatus.PENDING, base_reasons[0]),
            horizon_5d=HorizonEvaluation(5, None, None, None, None, EvaluationStatus.PENDING, base_reasons[0]),
            horizon_20d=HorizonEvaluation(20, None, None, None, None, EvaluationStatus.PENDING, base_reasons[0]),
            evaluable=False,
            non_evaluable_reasons=base_reasons,
        )

    # 각 평가 기간별 계산
    h1 = _evaluate_single_horizon(decision, base_price, base_price_date, base_price_provider, 1, ohlcv_repo, asset_id, provider, as_of)
    h5 = _evaluate_single_horizon(decision, base_price, base_price_date, base_price_provider, 5, ohlcv_repo, asset_id, provider, as_of)
    h20 = _evaluate_single_horizon(decision, base_price, base_price_date, base_price_provider, 20, ohlcv_repo, asset_id, provider, as_of)

    # 전체 평가 가능 여부: 모든 기간이 COMPLETED인 경우
    all_completed = all(h.status == EvaluationStatus.COMPLETED for h in [h1, h5, h20])
    non_eval_reasons = [h.reason for h in [h1, h5, h20] if h.status != EvaluationStatus.COMPLETED and h.reason]

    return DecisionEvaluation(
        decision_id=decision.id,
        thesis_id=decision.thesis_id,
        asset_id=asset_id,
        model_provider=decision.model_provider,
        model_name=decision.model_name,
        outcome=decision.outcome,
        side=decision.side,
        decided_at=decided_at,
        base_price=base_price,
        base_price_date=base_price_date,
        base_price_provider=base_price_provider,
        horizon_1d=h1,
        horizon_5d=h5,
        horizon_20d=h20,
        evaluable=all_completed,
        non_evaluable_reasons=non_eval_reasons,
    )


def evaluate_decisions(
    db_path: str,
    limit: int = 50,
    asset: str | None = None,
    model: str | None = None,
    horizon: int | None = None,
    as_of: datetime | None = None,
    provider: str | None = None,
) -> tuple[list[DecisionEvaluation], list[ModelEvaluationSummary]]:
    """최근 N개 의사결정 평가.

    Args:
        db_path: SQLite DB 경로
        limit: 조회할 의사결정 개수
        asset: 특정 종목만 평가 (예: KRX:005930)
        model: 특정 모델만 평가
        horizon: 표시할 평가 기간 (1, 5, 20 중 하나)
        as_of: 평가 기준 시점 (기본값: 현재 UTC)
        provider: OHLCV 공급자 지정
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(f"DB 파일이 없습니다: {db_path}")

    thesis_repo = ThesisRepository(db_path)
    ohlcv_repo = OHLCVRepository(db_path)
    decision_repo = DecisionRepository(db_path)

    decisions = decision_repo.get_latest(limit)

    if asset:
        thesis_repo = ThesisRepository(db_path)
        filtered = []
        for d in decisions:
            thesis = thesis_repo.get(d.thesis_id)
            if thesis and thesis.asset_id == asset:
                filtered.append(d)
        decisions = filtered

    if model:
        decisions = [d for d in decisions if d.model_name == model or d.model_provider == model]

    evaluations = []
    for decision in decisions:
        eval_result = evaluate_decision(
            decision,
            thesis_repo,
            ohlcv_repo,
            as_of=as_of,
            provider=provider,
        )
        evaluations.append(eval_result)

    model_summaries = _compute_model_summaries(evaluations)

    return evaluations, model_summaries


def _compute_model_summaries(evaluations: list[DecisionEvaluation]) -> list[ModelEvaluationSummary]:
    """모델별 평가 요약 계산."""
    model_groups: dict[tuple[str, str], list[DecisionEvaluation]] = defaultdict(list)
    for eval_result in evaluations:
        key = (eval_result.model_provider, eval_result.model_name)
        model_groups[key].append(eval_result)

    summaries = []

    for (provider, name), evals in model_groups.items():
        total = len(evals)
        buy_count = sum(1 for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY)
        sell_count = sum(1 for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL)
        no_trade_count = sum(1 for e in evals if e.outcome == DecisionOutcome.NO_TRADE)
        blocked_count = sum(1 for e in evals if e.outcome == DecisionOutcome.BLOCKED)
        error_count = sum(1 for e in evals if e.outcome == DecisionOutcome.ERROR)

        evaluated = sum(1 for e in evals if e.evaluable)
        pending = sum(1 for e in evals if not e.evaluable and any(
            h.status == EvaluationStatus.PENDING for h in [e.horizon_1d, e.horizon_5d, e.horizon_20d]
        ))
        unevaluable = sum(1 for e in evals if not e.evaluable and not any(
            h.status == EvaluationStatus.PENDING for h in [e.horizon_1d, e.horizon_5d, e.horizon_20d]
        ))

        # 1D 적중률 계산
        buy_1d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY and e.horizon_1d.hit is not None]
        sell_1d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_1d.hit is not None]
        buy_hit_1d = sum(1 for e in buy_1d if e.horizon_1d.hit)
        sell_hit_1d = sum(1 for e in sell_1d if e.horizon_1d.hit)
        total_1d = len(buy_1d) + len(sell_1d)
        total_hit_1d = buy_hit_1d + sell_hit_1d

        buy_hit_rate_1d = (Decimal(buy_hit_1d) / Decimal(len(buy_1d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_1d else None
        sell_hit_rate_1d = (Decimal(sell_hit_1d) / Decimal(len(sell_1d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_1d else None
        total_hit_rate_1d = (Decimal(total_hit_1d) / Decimal(total_1d) * Decimal("100")).quantize(Decimal("0.01")) if total_1d else None

        # 5D 적중률 계산
        buy_5d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY and e.horizon_5d.hit is not None]
        sell_5d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_5d.hit is not None]
        buy_hit_5d = sum(1 for e in buy_5d if e.horizon_5d.hit)
        sell_hit_5d = sum(1 for e in sell_5d if e.horizon_5d.hit)
        total_5d = len(buy_5d) + len(sell_5d)
        total_hit_5d = buy_hit_5d + sell_hit_5d

        buy_hit_rate_5d = (Decimal(buy_hit_5d) / Decimal(len(buy_5d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_5d else None
        sell_hit_rate_5d = (Decimal(sell_hit_5d) / Decimal(len(sell_5d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_5d else None
        total_hit_rate_5d = (Decimal(total_hit_5d) / Decimal(total_5d) * Decimal("100")).quantize(Decimal("0.01")) if total_5d else None

        # 20D 적중률 계산
        buy_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY and e.horizon_20d.hit is not None]
        sell_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_20d.hit is not None]
        buy_hit_20d = sum(1 for e in buy_20d if e.horizon_20d.hit)
        sell_hit_20d = sum(1 for e in sell_20d if e.horizon_20d.hit)
        total_20d = len(buy_20d) + len(sell_20d)
        total_hit_20d = buy_hit_20d + sell_hit_20d

        buy_hit_rate_20d = (Decimal(buy_hit_20d) / Decimal(len(buy_20d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_20d else None
        sell_hit_rate_20d = (Decimal(sell_hit_20d) / Decimal(len(sell_20d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_20d else None
        total_hit_rate_20d = (Decimal(total_hit_20d) / Decimal(total_20d) * Decimal("100")).quantize(Decimal("0.01")) if total_20d else None

        # 평균 수익률 (가격 변화율)
        returns_1d = [e.horizon_1d.return_pct for e in evals if e.horizon_1d.return_pct is not None]
        returns_5d = [e.horizon_5d.return_pct for e in evals if e.horizon_5d.return_pct is not None]
        returns_20d = [e.horizon_20d.return_pct for e in evals if e.horizon_20d.return_pct is not None]

        avg_return_1d = (sum(returns_1d) / len(returns_1d)).quantize(Decimal("0.0001")) if returns_1d else None
        avg_return_5d = (sum(returns_5d) / len(returns_5d)).quantize(Decimal("0.0001")) if returns_5d else None
        avg_return_20d = (sum(returns_20d) / len(returns_20d)).quantize(Decimal("0.0001")) if returns_20d else None

        non_eval_reasons = []
        for e in evals:
            if not e.evaluable:
                non_eval_reasons.extend(e.non_evaluable_reasons)

        summary = ModelEvaluationSummary(
            model_provider=provider,
            model_name=name,
            total_decisions=total,
            buy_count=buy_count,
            sell_count=sell_count,
            no_trade_count=no_trade_count,
            blocked_count=blocked_count,
            error_count=error_count,
            evaluated_count=evaluated,
            pending_count=pending,
            unevaluable_count=unevaluable,
            buy_hit_rate_1d=buy_hit_rate_1d,
            sell_hit_rate_1d=sell_hit_rate_1d,
            total_hit_rate_1d=total_hit_rate_1d,
            hit_rate_1d_denominator=total_1d,
            buy_hit_rate_5d=buy_hit_rate_5d,
            sell_hit_rate_5d=sell_hit_rate_5d,
            total_hit_rate_5d=total_hit_rate_5d,
            hit_rate_5d_denominator=total_5d,
            buy_hit_rate_20d=buy_hit_rate_20d,
            sell_hit_rate_20d=sell_hit_rate_20d,
            total_hit_rate_20d=total_hit_rate_20d,
            hit_rate_20d_denominator=total_20d,
            avg_return_1d=avg_return_1d,
            avg_return_5d=avg_return_5d,
            avg_return_20d=avg_return_20d,
            non_evaluable_reasons=list(set(non_eval_reasons)),
        )
        summaries.append(summary)

    return summaries
