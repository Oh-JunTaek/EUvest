"""AI 의사결정 사후 평가 모듈.

AI가 기록한 의사결정(BUY, SELL, NO_TRADE)을 사후 시장 가격과 비교하여
방향 적중률과 가격 변화율을 계산한다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from invest_agent.domain.models import Decision, DecisionOutcome, OrderSide
from invest_agent.market.market_data import OHLCV
from invest_agent.storage.repositories import (
    DecisionRepository,
    OHLCVRepository,
    ThesisRepository,
)


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

    horizon_1d_price: Decimal | None
    horizon_1d_return_pct: Decimal | None
    horizon_1d_hit: bool | None
    horizon_1d_reason: str | None

    horizon_5d_price: Decimal | None
    horizon_5d_return_pct: Decimal | None
    horizon_5d_hit: bool | None
    horizon_5d_reason: str | None

    horizon_20d_price: Decimal | None
    horizon_20d_return_pct: Decimal | None
    horizon_20d_hit: bool | None
    horizon_20d_reason: str | None

    evaluable: bool
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
def _is_us_dst(date: datetime) -> bool:
    if date.tzinfo is not None:
        date = date.astimezone(UTC).replace(tzinfo=None)
    year = date.year
    march_start = datetime(year, 3, 8)
    days_until_sunday = (6 - march_start.weekday()) % 7
    dst_start = march_start + timedelta(days=days_until_sunday)
    dst_start = datetime.combine(dst_start, time(7, 0))
    nov_start = datetime(year, 11, 1)
    days_until_sunday = (6 - nov_start.weekday()) % 7
    dst_end_date = nov_start + timedelta(days=days_until_sunday)
    dst_end = datetime.combine(dst_end_date, time(6, 0))
    return dst_start <= date < dst_end


def _get_market_close_utc(market: str, trade_date: str) -> datetime:
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


def _get_closest_ohlcv(
    repo: OHLCVRepository,
    asset_id: str,
    target_dt: datetime,
    provider: str | None = None,
    max_days_back: int = 10,
) -> tuple[OHLCV | None, str | None]:
    target_date = target_dt.date().isoformat()
    search_start = (target_dt - timedelta(days=max_days_back)).date().isoformat()
    ohlcv_list = repo.get_range(asset_id, search_start, target_date)
    if not ohlcv_list:
        return None, None
    for ohlcv in ohlcv_list:
        if ohlcv.timestamp.date() <= target_dt.date():
            return ohlcv, ohlcv.timestamp.date().isoformat()
    return None, None


def _get_trading_day_offset(
    repo: OHLCVRepository,
    asset_id: str,
    start_date: str,
    offset_days: int,
    provider: str | None = None,
) -> tuple[str | None, Decimal | None]:
    end_search = (datetime.fromisoformat(start_date).date() + timedelta(days=50)).isoformat()
    ohlcv_list = repo.get_range(asset_id, start_date, end_search)
    if not ohlcv_list:
        return None, None
    valid_days = [
        ohlcv for ohlcv in ohlcv_list
        if ohlcv.timestamp.date() > datetime.fromisoformat(start_date).date()
    ]
    valid_days.sort(key=lambda x: x.timestamp.date())
    if len(valid_days) < offset_days:
        return None, None
    target = valid_days[offset_days - 1]
    return target.timestamp.date().isoformat(), target.close


def _check_price_confirmation_time(
    ohlcv: OHLCV | None,
    portfolio_boundary: datetime,
    boundary_label: str,
    reasons: list[str],
) -> bool:
    if ohlcv is None:
        return False
    market_close_utc = _get_market_close_utc(ohlcv.market, ohlcv.timestamp.date().isoformat())
    if portfolio_boundary < market_close_utc:
        reasons.append(
            f"{boundary_label}: 종가 확정 시각({market_close_utc.isoformat()}) 이후 평가 필요 "
            f"(평가 경계: {portfolio_boundary.isoformat()})"
        )
        return False
    return True
def evaluate_decision(
    decision: Decision,
    thesis_repo: ThesisRepository,
    ohlcv_repo: OHLCVRepository,
    horizons: tuple[int, ...] = EVALUATION_HORIZONS,
    max_freshness_days: int = 10,
    max_days_back: int = 10,
) -> DecisionEvaluation:
    """단일 의사결정 평가."""
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
            horizon_1d_price=None,
            horizon_1d_return_pct=None,
            horizon_1d_hit=None,
            horizon_1d_reason="Thesis를 찾을 수 없음",
            horizon_5d_price=None,
            horizon_5d_return_pct=None,
            horizon_5d_hit=None,
            horizon_5d_reason="Thesis를 찾을 수 없음",
            horizon_20d_price=None,
            horizon_20d_return_pct=None,
            horizon_20d_hit=None,
            horizon_20d_reason="Thesis를 찾을 수 없음",
            evaluable=False,
            non_evaluable_reasons=["Thesis를 찾을 수 없음"],
        )

    asset_id = thesis.asset_id
    decided_at = decision.decided_at

    base_ohlcv, base_price_date = _get_closest_ohlcv(
        ohlcv_repo, asset_id, decided_at, max_days_back=10
    )

    base_price = None
    base_price_provider = None
    if base_ohlcv:
        base_price = base_ohlcv.close
        base_price_provider = "OHLCV"

    if base_price is None or base_price <= 0:
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
            horizon_1d_price=None,
            horizon_1d_return_pct=None,
            horizon_1d_hit=None,
            horizon_1d_reason="기준 가격 없음 또는 0 이하",
            horizon_5d_price=None,
            horizon_5d_return_pct=None,
            horizon_5d_hit=None,
            horizon_5d_reason="기준 가격 없음 또는 0 이하",
            horizon_20d_price=None,
            horizon_20d_return_pct=None,
            horizon_20d_hit=None,
            horizon_20d_reason="기준 가격 없음 또는 0 이하",
            evaluable=False,
            non_evaluable_reasons=["기준 가격 없음 또는 0 이하"],
        )

    results = {}
    for horizon in horizons:
        price_date, price = _get_trading_day_offset(
            ohlcv_repo, asset_id, base_price_date or "", horizon
        )

        horizon_price = None
        horizon_return = None
        horizon_hit = None
        horizon_reason = None

        if price is None or price_date is None:
            horizon_reason = f"{horizon}거래일 후 가격 데이터 없음"
        else:
            eval_ohlcv, _ = _get_closest_ohlcv(
                ohlcv_repo, asset_id, datetime.fromisoformat(price_date + "T00:00:00").replace(tzinfo=UTC)
            )
            if not _check_price_confirmation_time(eval_ohlcv, decision.decided_at + timedelta(days=horizon * 7), f"{horizon}일 후 평가", []):
                horizon_reason = f"{horizon}일 후 평가: 종가 확정 시각 이후 평가 필요"
            else:
                horizon_price = price
                return_pct = ((price / base_price - Decimal("1")) * Decimal("100")).quantize(Decimal("0.0001"))
                horizon_return = return_pct

                if decision.outcome == DecisionOutcome.TRADE and decision.side == OrderSide.BUY:
                    horizon_hit = return_pct > Decimal("0")
                elif decision.outcome == DecisionOutcome.TRADE and decision.side == OrderSide.SELL:
                    horizon_hit = return_pct < Decimal("0")
                else:
                    horizon_hit = None

        results[horizon] = {
            "price": horizon_price,
            "date": price_date,
            "return_pct": horizon_return,
            "hit": horizon_hit,
            "reason": horizon_reason,
        }

    evaluable = all(r["price"] is not None for r in results.values())
    non_evaluable_reasons = [r["reason"] for r in results.values() if r["price"] is None]

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
        horizon_1d_price=results.get(1, {}).get("price"),
        horizon_1d_return_pct=results.get(1, {}).get("return_pct"),
        horizon_1d_hit=results.get(1, {}).get("hit"),
        horizon_1d_reason=results.get(1, {}).get("reason"),
        horizon_5d_price=results.get(5, {}).get("price"),
        horizon_5d_return_pct=results.get(5, {}).get("return_pct"),
        horizon_5d_hit=results.get(5, {}).get("hit"),
        horizon_5d_reason=results.get(5, {}).get("reason"),
        horizon_20d_price=results.get(20, {}).get("price"),
        horizon_20d_return_pct=results.get(20, {}).get("return_pct"),
        horizon_20d_hit=results.get(20, {}).get("hit"),
        horizon_20d_reason=results.get(20, {}).get("reason"),
        evaluable=evaluable,
        non_evaluable_reasons=non_evaluable_reasons,
    )
def evaluate_decisions(
    db_path: str,
    limit: int = 50,
    asset: str | None = None,
    model: str | None = None,
    horizon: int | None = None,
) -> tuple[list[DecisionEvaluation], list[ModelEvaluationSummary]]:
    """최근 N개 의사결정 평가."""
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
        eval_result = evaluate_decision(decision, thesis_repo, ohlcv_repo)
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
        unevaluable = sum(1 for e in evals if not e.evaluable)

        buy_1d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY and e.horizon_1d_hit is not None]
        sell_1d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_1d_hit is not None]
        buy_hit_1d = sum(1 for e in buy_1d if e.horizon_1d_hit)
        sell_hit_1d = sum(1 for e in sell_1d if e.horizon_1d_hit)
        total_1d = len(buy_1d) + len(sell_1d)
        total_hit_1d = buy_hit_1d + sell_hit_1d

        buy_hit_rate_1d = (Decimal(buy_hit_1d) / Decimal(len(buy_1d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_1d else None
        sell_hit_rate_1d = (Decimal(sell_hit_1d) / Decimal(len(sell_1d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_1d else None
        total_hit_rate_1d = (Decimal(total_hit_1d) / Decimal(total_1d) * Decimal("100")).quantize(Decimal("0.01")) if total_1d else None

        buy_5d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY and e.horizon_5d_hit is not None]
        sell_5d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_5d_hit is not None]
        buy_hit_5d = sum(1 for e in buy_5d if e.horizon_5d_hit)
        sell_hit_5d = sum(1 for e in sell_5d if e.horizon_5d_hit)
        total_5d = len(buy_5d) + len(sell_5d)
        total_hit_5d = buy_hit_5d + sell_hit_5d

        buy_hit_rate_5d = (Decimal(buy_hit_5d) / Decimal(len(buy_5d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_5d else None
        sell_hit_rate_5d = (Decimal(sell_hit_5d) / Decimal(len(sell_5d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_5d else None
        total_hit_rate_5d = (Decimal(total_hit_5d) / Decimal(total_5d) * Decimal("100")).quantize(Decimal("0.01")) if total_5d else None

        buy_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.BUY and e.horizon_20d_hit is not None]
        sell_20d = [e for e in evals if e.outcome == DecisionOutcome.TRADE and e.side == OrderSide.SELL and e.horizon_20d_hit is not None]
        buy_hit_20d = sum(1 for e in buy_20d if e.horizon_20d_hit)
        sell_hit_20d = sum(1 for e in sell_20d if e.horizon_20d_hit)
        total_20d = len(buy_20d) + len(sell_20d)
        total_hit_20d = buy_hit_20d + sell_hit_20d

        buy_hit_rate_20d = (Decimal(buy_hit_20d) / Decimal(len(buy_20d)) * Decimal("100")).quantize(Decimal("0.01")) if buy_20d else None
        sell_hit_rate_20d = (Decimal(sell_hit_20d) / Decimal(len(sell_20d)) * Decimal("100")).quantize(Decimal("0.01")) if sell_20d else None
        total_hit_rate_20d = (Decimal(total_hit_20d) / Decimal(total_20d) * Decimal("100")).quantize(Decimal("0.01")) if total_20d else None

        returns_1d = [e.horizon_1d_return_pct for e in evals if e.horizon_1d_return_pct is not None]
        returns_5d = [e.horizon_5d_return_pct for e in evals if e.horizon_5d_return_pct is not None]
        returns_20d = [e.horizon_20d_return_pct for e in evals if e.horizon_20d_return_pct is not None]

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
            pending_count=0,
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
