"""오케스트레이터 - run-once 전체 실행 흐름 관리."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from invest_agent.agent.context_builder import ContextBuilder
from invest_agent.agent.thesis_manager import ThesisManager
from invest_agent.ai.router import ProviderRouter
from invest_agent.broker.mock_broker import MockBroker
from invest_agent.broker.protocol import BrokerProtocol
from invest_agent.domain.enums import (
    AssetType,
    ExecutionMode,
    Market,
    OrderSide,
    OrderStatus,
    OrderType,
    RunStatus,
)
from invest_agent.domain.models import (
    AgentRun,
    Decision,
    DecisionOutcome,
    OrderRecord,
)
from invest_agent.execution.order_engine import create_order_engine
from invest_agent.execution.risk_gate import create_risk_gate_for_mode
from invest_agent.execution.sizing import SizingParams, calculate_target_quantity
from invest_agent.runtime.locking import ExecutionLock, RunStatusTracker
from invest_agent.settings import Settings, get_settings
from invest_agent.storage.repositories import (
    AgentRunRepository,
    DecisionRepository,
    EquitySnapshotRepository,
    OrderRepository,
)
from invest_agent.storage.schema import ensure_db


@dataclass(frozen=True)
class RunOnceResult:
    """run-once 실행 결과."""
    run_id: UUID
    status: RunStatus
    decision_outcome: DecisionOutcome
    orders_created: int
    orders_filled: int
    error: str | None = None
    started_at: datetime = None
    completed_at: datetime = None


class Orchestrator:
    """run-once 실행 오케스트레이터."""

    def __init__(
        self,
        db_path: str,
        settings: Settings | None = None,
        broker: BrokerProtocol | None = None,
    ):
        self.db_path = db_path
        self.settings = settings or get_settings()
        self.broker = broker

        ensure_db(self.db_path)
        self.run_repo = AgentRunRepository(self.db_path)
        self.decision_repo = DecisionRepository(self.db_path)
        self.order_repo = OrderRepository(self.db_path)
        self.snapshot_repo = EquitySnapshotRepository(self.db_path)

        self.context_builder = ContextBuilder(self.db_path)
        self.thesis_manager = ThesisManager(self.db_path)
        self.order_engine = create_order_engine()
        self.router = ProviderRouter()
        self.lock = ExecutionLock(self.db_path)
        self.status_tracker = RunStatusTracker(self.db_path)

        self.risk_gate = create_risk_gate_for_mode(self.settings.execution.mode)

        if self.broker is None:
            self.broker = MockBroker(initial_cash=Decimal("100000000"), db_path=self.db_path)
    async def run_once(
        self,
        run_id: UUID | None = None,
        asset_filter: list[str] | None = None,
        force: bool = False,
    ) -> RunOnceResult:
        run_id = run_id or uuid4()
        started_at = datetime.now(UTC)

        run = AgentRun(
            id=run_id,
            started_at=started_at,
            status=RunStatus.CREATED,
            execution_mode=self.settings.execution.mode.value,
        )
        self.run_repo.save(run)

        if not force:
            try:
                with self.lock.hold(str(run_id), timeout_seconds=0):
                    return await self._execute_run(run, asset_filter, started_at)
            except RuntimeError as e:
                run.status = RunStatus.SKIPPED_ALREADY_RUNNING
                run.completed_at = datetime.now(UTC)
                run.error = str(e)
                self.run_repo.save(run)
                return RunOnceResult(
                    run_id=run_id,
                    status=RunStatus.SKIPPED_ALREADY_RUNNING,
                    decision_outcome=DecisionOutcome.NO_TRADE,
                    orders_created=0,
                    orders_filled=0,
                    error=str(e),
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )
        else:
            return await self._execute_run(run, asset_filter, started_at)

    async def _execute_run(
        self,
        run: AgentRun,
        asset_filter: list[str] | None,
        started_at: datetime,
    ) -> RunOnceResult:
        """run-once 전체 실행 흐름."""
        # OFFLINE_SIM 모드에서만 주문 실행 허용
        if self.settings.execution.mode != ExecutionMode.OFFLINE_SIM:
            return await self._finalize_run(
                run=run,
                status=RunStatus.COMPLETED,
                decision_outcome=DecisionOutcome.NO_TRADE,
                error=f"주문 실행은 OFFLINE_SIM 모드에서만 허용됨 (현재: {self.settings.execution.mode.value})",
                started_at=started_at,
                orders_created=0,
                orders_filled=0,
            )

        try:
            # 1. 컨텍스트 수집
            run.status = RunStatus.COLLECTING
            self.run_repo.save(run)

            # 현재 런용 스냅샷 생성 (리스크 검증용)
            await self._create_initial_snapshot(run)

            envelope = await self._collect_context(run, asset_filter)

            # 2. 결정 생성
            run.status = RunStatus.DECIDING
            self.run_repo.save(run)
            decision = await self._make_decisions(run, envelope)

            # 논문 ID를 run에 저장 (NO_TRADE여도 저장)
            run.thesis_ids = [t.thesis_id for t in envelope.active_theses]
            self.run_repo.save(run)

            if decision is None or decision.outcome == DecisionOutcome.NO_TRADE:
                # 논문이 없거나 NO_TRADE면 바로 완료
                outcome = decision.outcome if decision else DecisionOutcome.NO_TRADE
                return await self._finalize_run(
                    run=run,
                    status=RunStatus.COMPLETED,
                    decision_outcome=outcome,
                    error=None,
                    started_at=started_at,
                    orders_created=0,
                    orders_filled=0,
                )

            # 3. 리스크 검증
            run.status = RunStatus.VALIDATING
            self.run_repo.save(run)
            risk_result = self._validate_risk(run, decision, envelope, envelope.active_theses[0] if envelope.active_theses else None)

            if risk_result.overall.value == "REJECT":
                return await self._finalize_run(
                    run=run,
                    status=RunStatus.COMPLETED,
                    decision_outcome=DecisionOutcome.NO_TRADE,
                    error=self._format_risk_checks(risk_result.checks),
                    started_at=started_at,
                    orders_created=0,
                    orders_filled=0,
                )

            # 4. 주문 실행
            run.status = RunStatus.EXECUTING
            self.run_repo.save(run)
            orders_created, orders_filled = await self._execute_orders(run, decision, envelope)

            # 5. 주문 정산
            run.status = RunStatus.RECONCILING_ORDERS
            self.run_repo.save(run)
            await self._reconcile_orders(run)

            # 6. 완료
            decision_outcome = decision.outcome if decision else DecisionOutcome.NO_TRADE
            return await self._finalize_run(
                run=run,
                status=RunStatus.COMPLETED,
                decision_outcome=decision_outcome,
                error=None,
                started_at=started_at,
                orders_created=orders_created,
                orders_filled=orders_filled,
            )

        except Exception as e:
            return await self._finalize_run(
                run=run,
                status=RunStatus.RECOVERY_REQUIRED,
                decision_outcome=DecisionOutcome.NO_TRADE,
                error=str(e),
                started_at=started_at,
                orders_created=0,
                orders_filled=0,
            )

    async def _collect_context(
        self,
        run: AgentRun,
        asset_filter: list[str] | None,
    ):
        """컨텍스트 수집."""
        return self.context_builder.build_context(run.id, asset_filter=asset_filter)

    async def _create_initial_snapshot(self, run: AgentRun) -> None:
        """초기 스냅샷 생성 (브로커 잔고 기반)."""
        from decimal import Decimal

        from invest_agent.domain.models import EquitySnapshot

        balance = self.broker.get_balance()
        snapshot = EquitySnapshot(
            id=uuid4(),
            run_id=run.id,
            timestamp=datetime.now(UTC),
            total_equity=balance.total_equity,
            cash_balance=balance.available_cash,
            positions={},
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            metadata={},
        )
        self.snapshot_repo.save(snapshot)

    async def _make_decisions(
        self,
        run: AgentRun,
        envelope,
    ):
        """AI 결정 생성."""
        if not envelope.active_theses:
            return None

        thesis = envelope.active_theses[0]
        asset_id = thesis.asset_id

        # 시장 데이터 컨텍스트 확인
        market_ctx = envelope.market_context.get(asset_id)
        if not market_ctx:
            return await self._create_no_trade_decision(
                thesis, run,
                "시장 데이터 컨텍스트가 없습니다 (asset_filter 없이 실행됨)."
            )

        if market_ctx.get("status") != "ok":
            error_msg = market_ctx.get("error", "알 수 없는 시장 데이터 오류")
            status = market_ctx.get("status", "error")
            return await self._create_no_trade_decision(
                thesis, run,
                f"시장 데이터 상태: {status}. {error_msg}"
            )

        market_data = market_ctx.get("data", {})
        is_sufficient = market_data.get("is_sufficient", False)
        if not is_sufficient:
            count = market_data.get("count", 0)
            return await self._create_no_trade_decision(
                thesis, run,
                f"시장 데이터 부족: {count}개 일봉 (최소 20개 필요). 데이터 수집 후 재시도 필요."
            )

        # 데이터 최신성 확인
        is_fresh = market_data.get("is_fresh", False)
        age_days = market_data.get("age_days", 999999)
        if not is_fresh:
            last_trade = market_data.get("last_trade_date", "알 수 없음")
            print(f"DEBUG _make_decisions: stale data detected, age_days={age_days}, last_trade={last_trade}")
            return await self._create_no_trade_decision(
                thesis, run,
                f"시장 데이터가 너무 오래됨: 마지막 거래일 {last_trade}로부터 {age_days}일 경과 (허용: 7일 이내). 최신 데이터 수집 필요."
            )

        # AI 라우터를 통해 구조화된 결정 요청
        from invest_agent.ai.protocol import AIRequest
        from invest_agent.ai.router import ProviderRouter
        from invest_agent.domain.enums import OrderSide
        from invest_agent.domain.models import Decision, DecisionOutcome

        router = ProviderRouter()

        decision_schema = {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": ["TRADE", "NO_TRADE"]},
                "side": {"type": "string", "enum": ["BUY", "SELL"]},
                "target_weight_bps": {"type": "integer"},
                "current_weight_bps": {"type": "integer"},
                "rationale": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["outcome", "rationale"],
        }

        provider = market_data.get("provider", "Unknown")
        last_trade_date = market_data.get("last_trade_date", "Unknown")
        fetched_at = market_data.get("fetched_at", "Unknown")
        data_points = market_data.get("data_points", [])
        recent_bars = data_points[:5]
        bars_text = "\n".join([
            f"  {bp['trade_date']}: O={bp['open']} H={bp['high']} L={bp['low']} C={bp['close']} V={bp['volume']}"
            for bp in recent_bars
        ])

        # 기술적 지표 추출
        indicators = market_data.get("indicators", {})
        sma_5 = indicators.get("sma_5")
        sma_20 = indicators.get("sma_20")
        ema_20 = indicators.get("ema_20")
        rsi_14 = indicators.get("rsi_14")
        bb_upper = indicators.get("bb_upper")
        bb_middle = indicators.get("bb_middle")
        bb_lower = indicators.get("bb_lower")
        bb_bandwidth = indicators.get("bb_bandwidth")
        indicators_calculated_at = indicators.get("calculated_at")
        indicators_data_points = indicators.get("data_points")

        indicators_text = "Technical Indicators (latest values):\n"
        if sma_5 is not None:
            indicators_text += f"  SMA(5): {sma_5}\n"
        else:
            indicators_text += "  SMA(5): N/A (insufficient data)\n"
        if sma_20 is not None:
            indicators_text += f"  SMA(20): {sma_20}\n"
        else:
            indicators_text += "  SMA(20): N/A (insufficient data)\n"
        if ema_20 is not None:
            indicators_text += f"  EMA(20): {ema_20}\n"
        else:
            indicators_text += "  EMA(20): N/A (insufficient data)\n"
        if rsi_14 is not None:
            indicators_text += f"  RSI(14): {rsi_14}\n"
        else:
            indicators_text += "  RSI(14): N/A (insufficient data)\n"
        if bb_upper is not None and bb_middle is not None and bb_lower is not None:
            indicators_text += f"  Bollinger Bands(20,2): Upper={bb_upper}, Middle={bb_middle}, Lower={bb_lower}"
            if bb_bandwidth is not None:
                indicators_text += f", Bandwidth={bb_bandwidth}"
            indicators_text += "\n"
        else:
            indicators_text += "  Bollinger Bands(20,2): N/A (insufficient data)\n"
        if indicators_calculated_at:
            indicators_text += f"  Calculated at: {indicators_calculated_at} (using {indicators_data_points} data points)\n"

        # 투자 이력 추출 (현재 자산만)
        history = envelope.asset_decision_history.get(asset_id, [])
        history_text = "Investment History (most recent first, max 5):\n"
        if history:
            for i, h in enumerate(history, 1):
                side_str = f" {h.side}" if h.side else ""
                target_str = f", target={h.target_weight_bps}bps" if h.target_weight_bps else ""
                current_str = f", current={h.current_weight_bps}bps" if h.current_weight_bps else ""
                date_str = h.decided_at.strftime("%Y-%m-%d %H:%M") if h.decided_at else "unknown"
                history_text += f"  {i}. {date_str} | {h.outcome}{side_str}{target_str}{current_str} | {h.rationale[:120]}\n"
        else:
            history_text += "  No previous decisions for this asset.\n"

        # 기각 조건 추출 (현재 가설만)
        falsification_text = "Falsification Conditions (from thesis metadata):\n"
        thesis_falsifications = [fc for fc in envelope.falsification_conditions if fc.thesis_id == thesis.thesis_id]
        if thesis_falsifications:
            for fc in thesis_falsifications:
                threshold_str = f", threshold={fc.threshold_value}" if fc.threshold_value is not None else ""
                falsification_text += f"  - {fc.condition_type}: {fc.description}{threshold_str}\n"
        else:
            falsification_text += "  No explicit falsification conditions defined.\n"

        # 포트폴리오 스냅샷
        portfolio_text = "Portfolio Snapshot:\n"
        if envelope.latest_snapshot:
            portfolio_text += f"  Total Equity: {envelope.total_equity:,} KRW\n"
            portfolio_text += f"  Available Cash (KRW): {envelope.available_cash_krw:,}\n"
            portfolio_text += f"  Available Cash (USD): {envelope.available_cash_usd:,}\n"
            if hasattr(envelope.latest_snapshot, 'positions') and envelope.latest_snapshot.positions:
                for aid, pos in envelope.latest_snapshot.positions.items():
                    if aid != "CASH_KRW" and aid != "CASH_USD":
                        qty = pos.get("quantity", 0)
                        if qty:
                            portfolio_text += f"  Holding {aid}: {qty}\n"
        else:
            portfolio_text += "  No portfolio snapshot available.\n"

        market_context_text = f"""Market Context for {asset_id}:
Provider: {provider}
Last Trade Date: {last_trade_date}
Data Fetched At: {fetched_at}
Total Bars: {market_data.get('count', 0)} (Sufficient: {is_sufficient})
Recent Bars (newest first):
{bars_text}

{indicators_text}

{history_text}

{falsification_text}

{portfolio_text}

Note: This is historical OHLCV data, not real-time prices. Technical indicators are calculated from stored OHLCV and are for reference only, not definitive buy/sell signals.
Previous decisions are for reference only and do not imply commitment. Changing decisions requires justification. Past history does not guarantee future performance. Insufficient information warrants NO_TRADE.
"""

        request = AIRequest(
            system_prompt="You are an investment decision engine. Output a JSON decision.",
            user_prompt=f"Thesis: {thesis.hypothesis}\nRationale: {thesis.rationale}\n\n{market_context_text}",
            response_format="json",
            max_tokens=1000,
        )

        response = await router.generate_structured(request, decision_schema)

        # 응답 파싱
        import json
        try:
            proposal = json.loads(response.content)
        except json.JSONDecodeError:
            proposal = {"outcome": "NO_TRADE", "rationale": "Failed to parse AI response"}

        outcome = DecisionOutcome(proposal.get("outcome", "NO_TRADE"))
        side = OrderSide(proposal["side"]) if "side" in proposal and proposal["side"] else None

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.thesis_id,
            run_id=run.id,
            outcome=outcome,
            side=side,
            target_weight_bps=proposal.get("target_weight_bps"),
            current_weight_bps=proposal.get("current_weight_bps"),
            rationale=proposal.get("rationale", "AI decision"),
            evidence_ids=proposal.get("evidence_ids", []),
            model_provider=response.provider.value,
            model_name=response.model,
            execution_mode=self.settings.execution.mode.value,
            decided_at=datetime.now(UTC),
        )

        self.decision_repo.save(decision)
        run.decision_ids.append(decision.id)
        self.run_repo.save(run)
        return decision

    async def _create_no_trade_decision(self, thesis, run, rationale: str):
        """NO_TRADE 결정을 생성하고 저장."""
        import asyncio
        from datetime import UTC
        from uuid import uuid4

        from invest_agent.domain.models import Decision, DecisionOutcome
        await asyncio.sleep(0.02)

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.thesis_id,
            run_id=run.id,
            outcome=DecisionOutcome.NO_TRADE,
            rationale=rationale,
            model_provider="orchestrator",
            model_name="internal",
            execution_mode=self.settings.execution.mode.value,
            decided_at=datetime.now(UTC),
        )
        print(f"DEBUG _create_no_trade_decision: saving decision with run_id={run.id}, rationale={rationale[:50]}")
        self.decision_repo.save(decision)
        run.decision_ids.append(decision.id)
        self.run_repo.save(run)
        print(f"DEBUG _create_no_trade_decision: decision saved with id={decision.id}")
        return decision

    def _validate_risk(
        self,
        run: AgentRun,
        decision: Decision,
        envelope,
        thesis,
    ):
        if not envelope.latest_snapshot:
            from invest_agent.execution.risk_gate import RiskCheck, RiskCheckResult, RiskGateResult
            return RiskGateResult(
                overall=RiskCheckResult.REJECT,
                checks=[RiskCheck(
                    name='snapshot_missing',
                    result=RiskCheckResult.REJECT,
                    message='최신 스냅샷 없음',
                )]
            )

        snapshot = envelope.latest_snapshot

        # 시장 데이터(현재가, 환율) 조회
        asset_id = thesis.asset_id
        market_data = self._get_market_data(asset_id)
        if market_data is None:
            from invest_agent.execution.risk_gate import RiskCheck, RiskCheckResult, RiskGateResult
            return RiskGateResult(
                overall=RiskCheckResult.REJECT,
                checks=[RiskCheck(
                    name='market_data_missing',
                    result=RiskCheckResult.REJECT,
                    message=f'시장 데이터 조회 실패: {asset_id} (가격 또는 환율 없음)',
                )]
            )

        price, fx_rate = market_data
        is_us = asset_id.startswith("US:")

        sizing_params = SizingParams(
            target_weight_bps=decision.target_weight_bps or 0,
            current_weight_bps=decision.current_weight_bps or 0,
            portfolio_value=snapshot.total_equity,
            asset_price=price,
            available_cash=snapshot.cash_balance,
            market=Market.US if is_us else Market.KRX,
            asset_type=asset_id.split(':')[1] if ':' in asset_id else 'STOCK',
            side=decision.side or OrderSide.BUY,
            fx_rate=fx_rate,
        )

        sizing_result = calculate_target_quantity(sizing_params)

        position_qty = 0
        for pos in snapshot.positions.values():
            if pos.get('asset_id') == thesis.asset_id or thesis.asset_id in pos:
                position_qty = int(pos.get('quantity', 0))
                break

        return self.risk_gate.check_order(
            sizing_result=sizing_result,
            portfolio_value=snapshot.total_equity,
            current_exposure=Decimal('0'),
            daily_pnl=Decimal('0'),
            position_qty=position_qty,
            side=(decision.side or OrderSide.BUY).value,
        )

    def _format_risk_checks(self, checks) -> str:
        return '; '.join(f'{c.name}: {c.message}' for c in checks if c.result.value == 'REJECT')

    async def _execute_orders(
        self,
        run: AgentRun,
        decision: Decision,
        envelope,
    ) -> tuple[int, int]:
        if decision.outcome != DecisionOutcome.TRADE or not decision.side:
            return 0, 0

        thesis = envelope.active_theses[0]
        snapshot = envelope.latest_snapshot

        if not snapshot:
            return 0, 0

        # 시장 데이터(현재가, 환율) 조회 - 위험 검증과 동일한 값 사용
        asset_id = thesis.asset_id
        market_data = self._get_market_data(asset_id)
        if market_data is None:
            # 시장 데이터가 없으면 주문 실행 안 함
            return 0, 0

        price, fx_rate = market_data
        is_us = asset_id.startswith("US:")

        sizing_params = SizingParams(
            target_weight_bps=decision.target_weight_bps or 0,
            current_weight_bps=decision.current_weight_bps or 0,
            portfolio_value=snapshot.total_equity,
            asset_price=price,
            available_cash=snapshot.cash_balance,
            market=Market.US if is_us else Market.KRX,
            asset_type=asset_id.split(':')[1] if ':' in asset_id else 'STOCK',
            side=decision.side,
            fx_rate=fx_rate,
        )

        sizing_result = calculate_target_quantity(sizing_params)

        if not sizing_result.feasible or sizing_result.quantity <= 0:
            return 0, 0

        # 주문 가격은 현재가 사용 (LIMIT 주문)
        order_price = price

        order = self.order_engine.create_order(
            asset_id=thesis.asset_id,
            market=Market.US if is_us else Market.KRX,
            asset_type=AssetType.STOCK,
            side=decision.side,
            order_type=OrderType.LIMIT,
            quantity=sizing_result.quantity,
            price=order_price,
            idempotency_key=f'{run.id}-{thesis.thesis_id}-{decision.id}',
        )

        self.order_engine.submit_order(order.id, broker_order_id=f'mock-{order.id}')
        self.order_engine.acknowledge_order(order.id, f'mock-{order.id}')

        order_record = OrderRecord(
            id=uuid4(),
            run_id=run.id,
            decision_id=decision.id,
            asset_id=thesis.asset_id,
            side=decision.side,
            order_type=OrderType.LIMIT,
            quantity=Decimal(str(sizing_result.quantity)),
            price=order_price,
            status=OrderStatus.ACKNOWLEDGED,
            broker_order_id=f'mock-{order.id}',
        )
        self.order_repo.save(order_record)
        run.order_ids.append(order_record.id)
        self.run_repo.save(run)

        self.broker.add_order(
            asset_id=thesis.asset_id,
            side=decision.side.value,
            order_type='LIMIT',
            quantity=Decimal(str(sizing_result.quantity)),
            price=order_price,
        )

        mock_order_id = list(self.broker._orders.keys())[-1]
        self.broker.fill_order(mock_order_id, Decimal(str(sizing_result.quantity)), order_price)

        self.order_engine.fill_order(order.id, sizing_result.quantity, order_price)
        order_record.status = OrderStatus.FILLED
        order_record.filled_quantity = Decimal(str(sizing_result.quantity))
        order_record.filled_price = order_price
        order_record.filled_at = datetime.now(UTC)
        self.order_repo.save(order_record)

        return 1, 1

    async def _reconcile_orders(self, run: AgentRun) -> None:
        pass

    def _get_market_data(self, asset_id: str) -> tuple[Decimal, Decimal] | None:
        """자산의 현재가와 환율 조회.

        Args:
            asset_id: 자산 ID (예: 'KRX:005930' 또는 'US:AAPL')

        Returns:
            (price, fx_rate) 튜플. 가격 또는 환율 정보가 없으면 None.
            - price: 자산 현재가 (해당 시장 통화, KRW 또는 USD)
            - fx_rate: 1 시장통화 = fx_rate 기준통화(KRW)
              예: 1 USD = 1300 KRW 이면 fx_rate=1300
              국내 주식(KRX)은 1 KRW = 1 KRW 이므로 fx_rate=1
        """
        # 1. 현재가 조회 (브로커에서)
        quote = self.broker.get_quote(asset_id)
        if quote.price <= 0:
            return None
        price = quote.price

        # 2. 환율 결정
        is_us = asset_id.startswith("US:")
        if is_us:
            fx_rate = self.settings.execution.mock_fx_rate_usd_krw
        else:
            fx_rate = Decimal("1")  # 국내 주식은 KRW 기준

        if fx_rate <= 0:
            return None

        return (price, fx_rate)

    async def _finalize_run(
        self,
        run: AgentRun,
        status: RunStatus,
        decision_outcome: DecisionOutcome,
        error: str | None,
        started_at: datetime,
        orders_created: int,
        orders_filled: int,
    ) -> RunOnceResult:
        completed_at = datetime.now(UTC)
        run.status = status
        run.completed_at = completed_at
        run.error = error
        self.run_repo.save(run)

        return RunOnceResult(
            run_id=run.id,
            status=status,
            decision_outcome=decision_outcome,
            orders_created=orders_created,
            orders_filled=orders_filled,
            error=error,
            started_at=started_at,
            completed_at=completed_at,
        )

def create_orchestrator(db_path: str, settings=None) -> Orchestrator:
    return Orchestrator(db_path, settings)
