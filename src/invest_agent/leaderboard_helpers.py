"""Helper functions for leaderboard."""

from __future__ import annotations

from decimal import Decimal


def _calc_hit_rate(hit: int, miss: int) -> Decimal | None:
    """적중률 계산 (HIT + MISS만 분모)."""
    total = hit + miss
    if total == 0:
        return None
    return (Decimal(hit) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))


def _calc_avg_return(returns: list) -> Decimal | None:
    """평균 수익률 계산."""
    if not returns:
        return None
    return (sum(returns) / len(returns)).quantize(Decimal("0.0001"))
