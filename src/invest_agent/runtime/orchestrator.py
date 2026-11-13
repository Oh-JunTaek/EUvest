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
            self.broker = MockBroker(initial_cash=Decimal("100000000"))
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
            # 논문이 없으면 None 반환 (NO_TRADE로 처리됨)
            return None

        # 첫 번째 논문에 대해 결정 요청
        thesis = envelope.active_theses[0]

        # AI 라우터를 통해 구조화된 결정 요청
        from invest_agent.ai.protocol import AIRequest
        from invest_agent.ai.router import ProviderRouter
        from invest_agent.domain.enums import OrderSide
        from invest_agent.domain.models import Decision, DecisionOutcome

        router = ProviderRouter()

        # 결정 스키마
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

        request = AIRequest(
            system_prompt="You are an investment decision engine. Output a JSON decision.",
            user_prompt=f"Thesis: {thesis.hypothesis}\nRationale: {thesis.rationale}",
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

        sizing_params = SizingParams(
            target_weight_bps=decision.target_weight_bps or 0,
            current_weight_bps=decision.current_weight_bps or 0,
            portfolio_value=snapshot.total_equity,
            asset_price=Decimal('100000'),
            available_cash=snapshot.cash_balance,
            market=Market.KRX if 'KRX' in envelope.active_theses[0].asset_id else Market.US,
            asset_type=envelope.active_theses[0].asset_id.split(':')[1] if ':' in envelope.active_theses[0].asset_id else 'STOCK',
            side=decision.side or OrderSide.BUY,
            fx_rate=Decimal('1300') if 'US' in envelope.active_theses[0].asset_id else Decimal('1'),
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

        sizing_params = SizingParams(
            target_weight_bps=decision.target_weight_bps or 0,
            current_weight_bps=decision.current_weight_bps or 0,
            portfolio_value=snapshot.total_equity,
            asset_price=Decimal('100000'),
            available_cash=snapshot.cash_balance,
            market=Market.KRX if 'KRX' in thesis.asset_id else Market.US,
            asset_type=thesis.asset_id.split(':')[1] if ':' in thesis.asset_id else 'STOCK',
            side=decision.side,
            fx_rate=Decimal('1300') if 'US' in thesis.asset_id else Decimal('1'),
        )

        sizing_result = calculate_target_quantity(sizing_params)

        if not sizing_result.feasible or sizing_result.quantity <= 0:
            return 0, 0

        order = self.order_engine.create_order(
            asset_id=thesis.asset_id,
            market=Market.KRX if 'KRX' in thesis.asset_id else Market.US,
            asset_type=AssetType.STOCK,
            side=decision.side,
            order_type=OrderType.LIMIT,
            quantity=sizing_result.quantity,
            price=Decimal('100000'),
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
            price=Decimal('100000'),
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
            price=Decimal('100000'),
        )

        mock_order_id = list(self.broker._orders.keys())[-1]
        self.broker.fill_order(mock_order_id, Decimal(str(sizing_result.quantity)), Decimal('100000'))

        self.order_engine.fill_order(order.id, sizing_result.quantity, Decimal('100000'))
        order_record.status = OrderStatus.FILLED
        order_record.filled_quantity = Decimal(str(sizing_result.quantity))
        order_record.filled_price=Decimal('100000')
        order_record.filled_at = datetime.now(UTC)
        self.order_repo.save(order_record)

        return 1, 1

    async def _reconcile_orders(self, run: AgentRun) -> None:
        pass

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
