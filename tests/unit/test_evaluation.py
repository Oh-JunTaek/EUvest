"""AI 의사결정 평가 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from invest_agent.domain.models import (
    Decision,
    DecisionOutcome,
    OrderSide,
    Thesis,
)
from invest_agent.evaluation import (
    EvaluationStatus,
    evaluate_decision,
)
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.storage.repositories import (
    DecisionRepository,
    OHLCVRepository,
    ThesisRepository,
)
from invest_agent.storage.schema import ensure_db


class TestEvaluateDecision:
    """단일 의사결정 평가 테스트."""

    def _create_test_db(self):
        """테스트용 임시 DB 및 데이터 생성."""
        import tempfile

        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "test.db"
        ensure_db(db_path)

        thesis_repo = ThesisRepository(db_path)
        ohlcv_repo = OHLCVRepository(db_path)
        decision_repo = DecisionRepository(db_path)

        # 가설 생성
        thesis = Thesis(
            id=uuid4(),
            asset_id="KRX:005930",
            hypothesis="삼성전자 주가 상승 예상",
            rationale="반도체 업황 개선",
        )
        thesis_repo.save(thesis)

        # 실행 기록 생성
        from invest_agent.domain.models import AgentRun, RunStatus

        run = AgentRun(
            id=uuid4(),
            started_at=datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC),
            status=RunStatus.COMPLETED,
            execution_mode="OFFLINE_SIM",
        )
        from invest_agent.storage.repositories import AgentRunRepository
        run_repo = AgentRunRepository(db_path)
        run_repo.save(run)

        return db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo
    def test_sell_correct_prediction(self):
        """SELL 판단 후 하락 -> 적중."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 하락 시나리오
        base_date = datetime(2025, 1, 1, 6, 30, 0, tzinfo=UTC)
        for i in range(50):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=base_date + timedelta(days=i),
                    open=Decimal("80000") - Decimal(str(i * 100)),
                    high=Decimal("81000") - Decimal(str(i * 100)),
                    low=Decimal("79500") - Decimal(str(i * 100)),
                    close=Decimal("80500") - Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                    provider="TestProvider",
                ),
                provider="TestProvider",
            )

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.SELL,
            model_provider="openai",
            model_name="gpt-4",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="매도 추천",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        as_of = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.evaluable is True
        assert eval_result.horizon_1d.hit is True  # 1일 후 하락
        assert eval_result.horizon_5d.hit is True  # 5일 후 하락
        assert eval_result.horizon_20d.hit is True  # 20일 후 하락
        assert eval_result.horizon_1d.return_pct < Decimal("0")

    def test_sell_wrong_prediction(self):
        """SELL 판단 후 상승 -> 미적중."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 상승 시나리오
        base_date = datetime(2025, 1, 1, 6, 30, 0, tzinfo=UTC)
        for i in range(50):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=base_date + timedelta(days=i),
                    open=Decimal("70000") + Decimal(str(i * 100)),
                    high=Decimal("71000") + Decimal(str(i * 100)),
                    low=Decimal("69500") + Decimal(str(i * 100)),
                    close=Decimal("70500") + Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                    provider="TestProvider",
                ),
                provider="TestProvider",
            )

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.SELL,
            model_provider="openai",
            model_name="gpt-4",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="매도 추천",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        as_of = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.evaluable is True
        assert eval_result.horizon_1d.hit is False  # 1일 후 상승
        assert eval_result.horizon_5d.hit is False  # 5일 후 상승
        assert eval_result.horizon_20d.hit is False  # 20일 후 상승

    def test_neutral_return(self):
        """가격 변화율 0 -> 중립 (적중률 분모 제외)."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 가격 변동 없음
        base_date = datetime(2025, 1, 1, 6, 30, 0, tzinfo=UTC)
        for i in range(50):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=base_date + timedelta(days=i),
                    open=Decimal("75000"),
                    high=Decimal("75500"),
                    low=Decimal("74500"),
                    close=Decimal("75000"),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                    provider="TestProvider",
                ),
                provider="TestProvider",
            )

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.BUY,
            model_provider="openai",
            model_name="gpt-4",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="매수 추천",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        as_of = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.evaluable is True
        assert eval_result.horizon_1d.hit is None  # 중립
        assert eval_result.horizon_5d.hit is None  # 중립
        assert eval_result.horizon_20d.hit is None  # 중립

    def test_no_trade_excluded(self):
        """NO_TRADE는 방향 적중률 평가 제외."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        base_date = datetime(2025, 1, 1, 6, 30, 0, tzinfo=UTC)
        for i in range(50):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=base_date + timedelta(days=i),
                    open=Decimal("75000"),
                    high=Decimal("75500"),
                    low=Decimal("74500"),
                    close=Decimal("75000"),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                    provider="TestProvider",
                ),
                provider="TestProvider",
            )

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.NO_TRADE,
            side=None,
            model_provider="openai",
            model_name="gpt-4",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="관망",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        as_of = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.horizon_1d.status == EvaluationStatus.EXCLUDED
        assert eval_result.horizon_5d.status == EvaluationStatus.EXCLUDED
        assert eval_result.horizon_20d.status == EvaluationStatus.EXCLUDED

    def test_future_price_blocked(self):
        """판단 시점 이후 미래 가격은 사용 불가 (PENDING)."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 과거 데이터만 저장 (1/1 ~ 1/25)
        base_date = datetime(2025, 1, 1, 6, 30, 0, tzinfo=UTC)
        for i in range(25):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=base_date + timedelta(days=i),
                    open=Decimal("75000"),
                    high=Decimal("75500"),
                    low=Decimal("74500"),
                    close=Decimal("75000") + Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                    provider="TestProvider",
                ),
                provider="TestProvider",
            )

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.BUY,
            model_provider="openai",
            model_name="gpt-4",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="매수 추천",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        # 1/6 평가 기준 (1/5 데이터만 있음 -> 5일 후 데이터 없음)
        as_of = datetime(2025, 1, 6, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        # 1D는 데이터가 있으니 평가 가능, 5D/20D는 데이터 없음
        assert eval_result.horizon_1d.status in (EvaluationStatus.COMPLETED, EvaluationStatus.UNAVAILABLE)
        # 5일/20일 후 데이터가 없으므로 PENDING (데이터는 있지만 as_of 시점에서 종가 확정 전)
        assert eval_result.horizon_5d.status == EvaluationStatus.PENDING
        assert eval_result.horizon_20d.status == EvaluationStatus.UNAVAILABLE

    def test_provider_mismatch(self):
        """서로 다른 공급자 데이터는 혼합되지 않음."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # Provider A 데이터 저장
        base_date = datetime(2025, 1, 1, 6, 30, 0, tzinfo=UTC)
        for i in range(50):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=base_date + timedelta(days=i),
                    open=Decimal("75000"),
                    high=Decimal("75500"),
                    low=Decimal("74500"),
                    close=Decimal("75000") + Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                    provider="ProviderA",
                ),
                provider="ProviderA",
            )

        # Provider B 데이터 저장 (다른 가격)
        for i in range(50):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=base_date + timedelta(days=i),
                    open=Decimal("80000"),
                    high=Decimal("80500"),
                    low=Decimal("79500"),
                    close=Decimal("80000") - Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                    provider="ProviderB",
                ),
                provider="ProviderB",
            )

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.BUY,
            model_provider="openai",
            model_name="gpt-4",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="매수 추천",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        as_of = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)

        # ProviderA로 평가
        eval_a = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="ProviderA"
        )
        # ProviderB로 평가
        eval_b = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="ProviderB"
        )

        # ProviderA는 상승이므로 적중, ProviderB는 하락이므로 미적중
        assert eval_a.horizon_1d.hit is True
        assert eval_b.horizon_1d.hit is False

    def test_invalid_base_price(self):
        """기준 가격이 0 이하이면 INVALID."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 가격 데이터 없음
        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.TRADE,
            side=OrderSide.BUY,
            model_provider="openai",
            model_name="gpt-4",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="매수 추천",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        as_of = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.horizon_1d.status == EvaluationStatus.INVALID
        assert eval_result.evaluable is False
