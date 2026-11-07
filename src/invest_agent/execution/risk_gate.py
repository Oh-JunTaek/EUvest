"""위험 게이트 - 주문 실행 전 사전 검증."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from invest_agent.domain.enums import ExecutionMode


class RiskCheckResult(Enum):
    """위험 검사 결과."""
    PASS = "PASS"
    WARN = "WARN"
    REJECT = "REJECT"


@dataclass(frozen=True)
class RiskCheck:
    """개별 위험 검사 항목."""
    name: str
    result: RiskCheckResult
    message: str
    value: Decimal | None = None
    limit: Decimal | None = None


@dataclass(frozen=True)
class RiskGateResult:
    """위험 게이트 종합 결과."""
    overall: RiskCheckResult
    checks: list[RiskCheck]
    order_id: str | None = None

    @property
    def is_approved(self) -> bool:
        return self.overall != RiskCheckResult.REJECT

    @property
    def has_warnings(self) -> bool:
        return any(c.result == RiskCheckResult.WARN for c in self.checks)

class RiskGate:
    def __init__(
        self,
        max_order_notional=None,
        max_daily_loss=None,
        max_portfolio_exposure=None,
        max_order_size_pct=Decimal('0.1'),
        allow_short=False,
    ):
        self.max_order_notional = max_order_notional
        self.max_daily_loss = max_daily_loss
        self.max_portfolio_exposure = max_portfolio_exposure
        self.max_order_size_pct = max_order_size_pct
        self.allow_short = allow_short
        self._daily_pnl = Decimal('0')

    def check_order(
        self,
        sizing_result,
        portfolio_value,
        current_exposure,
        daily_pnl,
        position_qty=0,
        side='BUY',
    ):
        checks = []

        if not sizing_result.feasible:
            checks.append(RiskCheck(
                name='sizing_feasible',
                result=RiskCheckResult.REJECT,
                message=sizing_result.reason,
            ))

        if sizing_result.quantity <= 0:
            checks.append(RiskCheck(
                name='quantity_positive',
                result=RiskCheckResult.REJECT,
                message='주문 수량이 0 이하',
            ))

        if side == 'BUY':
            if sizing_result.cash_required > Decimal('0'):
                checks.append(RiskCheck(
                    name='cash_sufficiency',
                    result=RiskCheckResult.PASS,
                    message='현금 충분',
                    value=sizing_result.cash_required,
                ))
            else:
                checks.append(RiskCheck(
                    name='cash_sufficiency',
                    result=RiskCheckResult.REJECT,
                    message='필요 현금 계산 불가',
                ))

        max_notional = portfolio_value * self.max_order_size_pct
        if sizing_result.notional_base > max_notional:
            checks.append(RiskCheck(
                name='max_order_size',
                result=RiskCheckResult.REJECT,
                message=f'주문 규모 초과: {sizing_result.notional_base} > {max_notional}',
                value=sizing_result.notional_base,
                limit=max_notional,
            ))
        else:
            checks.append(RiskCheck(
                name='max_order_size',
                result=RiskCheckResult.PASS,
                message='주문 규모 적정',
                value=sizing_result.notional_base,
                limit=max_notional,
            ))

        if self.max_order_notional and sizing_result.notional_base > self.max_order_notional:
            checks.append(RiskCheck(
                name='absolute_max_order',
                result=RiskCheckResult.REJECT,
                message=f'절대 주문 한도 초과: {sizing_result.notional_base} > {self.max_order_notional}',
                value=sizing_result.notional_base,
                limit=self.max_order_notional,
            ))

        new_exposure = current_exposure + (sizing_result.notional_base if side == 'BUY' else -sizing_result.notional_base)
        if self.max_portfolio_exposure and abs(new_exposure) > self.max_portfolio_exposure:
            checks.append(RiskCheck(
                name='portfolio_exposure',
                result=RiskCheckResult.REJECT,
                message=f'포트폴리오 익스포저 한도 초과: {new_exposure} > {self.max_portfolio_exposure}',
                value=new_exposure,
                limit=self.max_portfolio_exposure,
            ))
        else:
            checks.append(RiskCheck(
                name='portfolio_exposure',
                result=RiskCheckResult.PASS,
                message='익스포저 한도 내',
                value=new_exposure,
                limit=self.max_portfolio_exposure,
            ))

        if self.max_daily_loss and daily_pnl < -self.max_daily_loss:
            checks.append(RiskCheck(
                name='daily_loss_limit',
                result=RiskCheckResult.REJECT,
                message=f'일일 손실 한도 초과: {daily_pnl} < -{self.max_daily_loss}',
                value=daily_pnl,
                limit=-self.max_daily_loss,
            ))
        elif self.max_daily_loss and daily_pnl < -self.max_daily_loss * Decimal('0.8'):
            checks.append(RiskCheck(
                name='daily_loss_warning',
                result=RiskCheckResult.WARN,
                message=f'일일 손실 경고 임계치 접근: {daily_pnl}',
                value=daily_pnl,
                limit=-self.max_daily_loss,
            ))
        else:
            checks.append(RiskCheck(
                name='daily_loss_limit',
                result=RiskCheckResult.PASS,
                message='일일 손실 한도 내',
                value=daily_pnl,
            ))

        if side == 'SELL' and position_qty <= 0:
            if not self.allow_short:
                checks.append(RiskCheck(
                    name='short_sell_prohibited',
                    result=RiskCheckResult.REJECT,
                    message='공매도 금지: 보유 수량 없음',
                ))
            else:
                checks.append(RiskCheck(
                    name='short_sell_allowed',
                    result=RiskCheckResult.WARN,
                    message='공매도 허용됨 (보유 수량 없음)',
                ))

        has_reject = any(c.result == RiskCheckResult.REJECT for c in checks)
        has_warn = any(c.result == RiskCheckResult.WARN for c in checks)

        if has_reject:
            overall = RiskCheckResult.REJECT
        elif has_warn:
            overall = RiskCheckResult.WARN
        else:
            overall = RiskCheckResult.PASS

        return RiskGateResult(overall=overall, checks=checks)

    def update_daily_pnl(self, pnl):
        self._daily_pnl = pnl

    def get_daily_pnl(self):
        return self._daily_pnl


def create_risk_gate_for_mode(mode):
    if mode == ExecutionMode.OFFLINE_SIM:
        return RiskGate(
            max_order_size_pct=Decimal('0.05'),
            max_daily_loss=Decimal('1000000'),
            max_portfolio_exposure=Decimal('50000000'),
        )
    elif mode == ExecutionMode.KIS_PAPER:
        return RiskGate(
            max_order_size_pct=Decimal('0.1'),
            max_daily_loss=Decimal('5000000'),
            max_portfolio_exposure=Decimal('100000000'),
        )
    elif mode == ExecutionMode.LIVE:
        return RiskGate(
            max_order_size_pct=Decimal('0.05'),
            max_daily_loss=Decimal('2000000'),
            max_portfolio_exposure=Decimal('50000000'),
        )
    else:
        return RiskGate(
            max_order_size_pct=Decimal('0.2'),
            max_daily_loss=Decimal('10000000'),
            max_portfolio_exposure=Decimal('200000000'),
        )
