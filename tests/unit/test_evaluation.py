"""AI 의사결정 평가 모듈 단위 테스트."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from invest_agent.domain.models import (
    AgentRun,
    Decision,
    DecisionOutcome,
    OrderSide,
    RunStatus,
    Thesis,
)
from invest_agent.evaluation import (
    _is_us_dst,
    evaluate_decision,
    evaluate_decisions,
)
from invest_agent.market.market_data import OHLCV, Market
from invest_agent.storage.repositories import (
    AgentRunRepository,
    DecisionRepository,
    OHLCVRepository,
    ThesisRepository,
)
from invest_agent.storage.schema import ensure_db


class TestEvaluationHelpers:
    """헬퍼 함수 테스트."""

    def test_is_us_dst(self):
        """미국 DST 판별 테스트."""
        # 2025년 3월 9일 (DST 시작) 이전
        assert _is_us_dst(datetime(2025, 3, 8, 12, 0, 0, tzinfo=UTC)) is False
        # 2025년 3월 9일 (DST 시작) 이후
        assert _is_us_dst(datetime(2025, 3, 9, 12, 0, 0, tzinfo=UTC)) is True
        # 2025년 11월 2일 (DST 종료) 이전
        assert _is_us_dst(datetime(2025, 11, 1, 12, 0, 0, tzinfo=UTC)) is True
        # 2025년 11월 2일 (DST 종료) 이후
        assert _is_us_dst(datetime(2025, 11, 3, 12, 0, 0, tzinfo=UTC)) is False



class TestEvaluateDecision:
    """단일 의사결정 평가 테스트."""

    def _create_test_db(self):
        """테스트용 DB 생성."""
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "test.db"
        ensure_db(db_path)

        decision_repo = DecisionRepository(db_path)
        thesis_repo = ThesisRepository(db_path)
        ohlcv_repo = OHLCVRepository(db_path)
        run_repo = AgentRunRepository(db_path)

        # AgentRun 생성 (decisions의 FK를 만족시키기 위해 필요)
        run = AgentRun(
            id=uuid4(),
            started_at=datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC),
            status=RunStatus.COMPLETED,
            execution_mode="OFFLINE_SIM",
        )
        run_repo.save(run)

        # Thesis 생성
        thesis = Thesis(
            id=uuid4(),
            asset_id="KRX:005930",
            hypothesis="삼성전자 상승 예상",
            rationale="반도체 슈퍼사이클 진입",
            created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        )
        thesis_repo.save(thesis)

        # 충분한 OHLCV 데이터 (25거래일)
        for i in range(1, 26):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=datetime(2025, 1, i, 6, 30, 0, tzinfo=UTC),
                    open=Decimal("70000") + Decimal(str(i * 100)),
                    high=Decimal("71000") + Decimal(str(i * 100)),
                    low=Decimal("69500") + Decimal(str(i * 100)),
                    close=Decimal("70500") + Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
                ),
                provider="TestProvider",
            )

        return db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo
    def test_sell_correct_prediction(self):
        """SELL 판단 후 하락 -> 적중."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 하락 시나리오
        for i in range(1, 26):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=datetime(2025, 1, i, 6, 30, 0, tzinfo=UTC),
                    open=Decimal("80000") - Decimal(str(i * 100)),
                    high=Decimal("81000") - Decimal(str(i * 100)),
                    low=Decimal("79500") - Decimal(str(i * 100)),
                    close=Decimal("80500") - Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
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

        as_of = datetime(2025, 1, 26, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.evaluable is True
        assert eval_result.horizon_1d_hit is True  # 1일 후 하락
        assert eval_result.horizon_5d_hit is True  # 5일 후 하락
        assert eval_result.horizon_20d_hit is True  # 20일 후 하락
        assert eval_result.horizon_1d_return_pct < Decimal("0")

    def test_sell_wrong_prediction(self):
        """SELL 판단 후 상승 -> 미적중."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 상승 시나리오
        for i in range(1, 26):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=datetime(2025, 1, i, 6, 30, 0, tzinfo=UTC),
                    open=Decimal("70000") + Decimal(str(i * 100)),
                    high=Decimal("71000") + Decimal(str(i * 100)),
                    low=Decimal("69500") + Decimal(str(i * 100)),
                    close=Decimal("70500") + Decimal(str(i * 100)),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
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

        as_of = datetime(2025, 1, 26, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.evaluable is True
        assert eval_result.horizon_1d_hit is False  # 1일 후 상승
        assert eval_result.horizon_5d_hit is False  # 5일 후 상승
        assert eval_result.horizon_20d_hit is False  # 20일 후 상승

    def test_neutral_return(self):
        """가격 변화율 0 -> 중립 (적중률 분모 제외)."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        # 가격 변동 없음
        for i in range(1, 26):
            ohlcv_repo.save(
                OHLCV(
                    timestamp=datetime(2025, 1, i, 6, 30, 0, tzinfo=UTC),
                    open=Decimal("70000"),
                    high=Decimal("70000"),
                    low=Decimal("70000"),
                    close=Decimal("70000"),
                    volume=1000000,
                    asset_id="KRX:005930",
                    market=Market.KRX,
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

        as_of = datetime(2025, 1, 26, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.evaluable is True
        assert eval_result.horizon_1d_hit is None  # 중립 -> None
        assert eval_result.horizon_5d_hit is None
        assert eval_result.horizon_20d_hit is None
        assert eval_result.horizon_1d_return_pct == Decimal("0")

    def test_no_trade_excluded(self):
        """NO_TRADE는 방향 적중률에서 제외."""
        db_path, thesis, run, decision_repo, thesis_repo, ohlcv_repo = self._create_test_db()

        decision = Decision(
            id=uuid4(),
            thesis_id=thesis.id,
            run_id=run.id,
            outcome=DecisionOutcome.NO_TRADE,
            side=None,
            model_provider="anthropic",
            model_name="claude-3",
            decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            rationale="관망",
            execution_mode="OFFLINE_SIM",
        )
        decision_repo.save(decision)

        as_of = datetime(2025, 1, 26, 12, 0, 0, tzinfo=UTC)

        eval_result = evaluate_decision(
            decision, thesis_repo, ohlcv_repo, as_of=as_of, provider="TestProvider"
        )

        assert eval_result.evaluable is True
        assert eval_result.horizon_1d_hit is None
        assert eval_result.horizon_5d_hit is None
        assert eval_result.horizon_20d_hit is None


class TestEvaluateDecisions:
    """여러 의사결정 일괄 평가 테스트."""

    def test_evaluate_multiple_decisions(self):
        """여러 의사결정 평가."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            ensure_db(db_path)

            decision_repo = DecisionRepository(db_path)
            thesis_repo = ThesisRepository(db_path)
            ohlcv_repo = OHLCVRepository(db_path)
            run_repo = AgentRunRepository(db_path)

            # AgentRun 생성 (decisions의 FK를 만족시키기 위해 필요)
            run = AgentRun(
                id=uuid4(),
                started_at=datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC),
                status=RunStatus.COMPLETED,
                execution_mode="OFFLINE_SIM",
            )
            run_repo.save(run)

            # Thesis 생성
            thesis = Thesis(
                id=uuid4(),
                asset_id="KRX:005930",
                hypothesis="테스트",
                rationale="테스트",
                created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
            )
            thesis_repo.save(thesis)

            # OHLCV 데이터
            for i in range(1, 26):
                ohlcv_repo.save(
                    OHLCV(
                        timestamp=datetime(2025, 1, i, 6, 30, 0, tzinfo=UTC),
                        open=Decimal("70000") + Decimal(str(i * 100)),
                        high=Decimal("71000") + Decimal(str(i * 100)),
                        low=Decimal("69500") + Decimal(str(i * 100)),
                        close=Decimal("70500") + Decimal(str(i * 100)),
                        volume=1000000,
                        asset_id="KRX:005930",
                        market=Market.KRX,
                    ),
                    provider="TestProvider",
                )

            # BUY 결정 2개
            for _ in range(2):
                decision = Decision(
                    id=uuid4(),
                    thesis_id=thesis.id,
                    run_id=run.id,
                    outcome=DecisionOutcome.TRADE,
                    side=OrderSide.BUY,
                    model_provider="openai",
                    model_name="gpt-4",
                    decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                    rationale="매수",
                    execution_mode="OFFLINE_SIM",
                )
                decision_repo.save(decision)

            # SELL 결정 1개 (틀린 예측)
            decision = Decision(
                id=uuid4(),
                thesis_id=thesis.id,
                run_id=run.id,
                outcome=DecisionOutcome.TRADE,
                side=OrderSide.SELL,
                model_provider="openai",
                model_name="gpt-4",
                decided_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
                rationale="매도",
                execution_mode="OFFLINE_SIM",
            )
            decision_repo.save(decision)

            # NO_TRADE 1개
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

            as_of = datetime(2025, 1, 26, 12, 0, 0, tzinfo=UTC)

            evaluations, summaries = evaluate_decisions(
                db_path=db_path,
                limit=10,
                as_of=as_of,
                provider="TestProvider",
            )

            assert len(evaluations) == 4
            assert len(summaries) == 1
            summary = summaries[0]
            assert summary.model_provider == "openai"
            assert summary.model_name == "gpt-4"
            assert summary.total_decisions == 4
            assert summary.buy_count == 2
            assert summary.sell_count == 1
            assert summary.no_trade_count == 1
            assert summary.evaluated_count == 4
            assert summary.unevaluable_count == 0

            # BUY 2개 모두 적중, SELL 1개 미적중 -> BUY 100%, SELL 0%, 전체 66.67%
            assert summary.buy_hit_rate_1d == Decimal("100.00")
            assert summary.sell_hit_rate_1d == Decimal("0.00")
            assert summary.total_hit_rate_1d == Decimal("66.67")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
