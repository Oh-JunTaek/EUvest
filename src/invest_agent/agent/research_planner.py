"""Research Planner - 자율 연구 계획 수립 및 실행."""

from __future__ import annotations

from dataclasses import dataclass, field

from invest_agent.agent.context_builder import ContextEnvelope
from invest_agent.ai.router import ProviderRouter as AIRouter
from invest_agent.domain.models import EvidenceType, Thesis
from invest_agent.market.evidence import (
    CollectedEvidence,
    ResearchBudget,
    ResearchPlan,
    ResearchResult,
    SourceProvider,
    deduplicate_evidence,
)
from invest_agent.market.filings_dart import (
    DartClient,
    convert_filing_to_evidence,
)

DEFAULT_RESEARCH_QUESTIONS = {
    EvidenceType.FUNDAMENTAL: [
        "최근 분기 실적(매출, 영업이익, 순이익) 추이는 어떠한가?",
        "재무건전성(부채비율, 유동비율, 이자보상배율)은 양호한가?",
        "현금흐름(영업/투자/재무활동)은 건전한가?",
        "주요 재무비율(ROE, ROA, PBR, PER) 업종 대비 수준은?",
    ],
    EvidenceType.FILING: [
        "최근 공시된 사업보고서/분기보고서의 주요 내용은?",
        "주요사항보고서(증자, 감자, 합병, 분할, 영업양수도) 발생 여부는?",
        "대량보유/지분변동 공시를 통한 주요주주 변동은?",
        "전환사채/신주인수권부사채 등 발행 공시 내역은?",
    ],
    EvidenceType.NEWS: [
        "최근 30일간 기업 관련 주요 뉴스 키워드는?",
        "긍정/부정 뉴스 비중과 시장 반응은?",
        "경쟁사/업종 관련 거시 뉴스 영향은?",
    ],
    EvidenceType.TECHNICAL: [
        "현재 주가 추세(단기/중기/장기 이동평균선 배열)는?",
        "거래량 패턴과 수급 주체(외국인/기관/개인)는?",
        "주요 지지/저항 구간과 기술적 지표(RSI, MACD) 신호는?",
    ],
    EvidenceType.MACRO: [
        "국내/미국 금리 및 환율 추이와 영향은?",
        "업종 관련 거시 지표(산업생산, PMI, 수출입 등)는?",
        "정책/규제 변경 이슈는?",
    ],
}


@dataclass(slots=True)
class ResearchPlanner:
    """자율 연구 계획 수립 및 실행기."""

    ai_router: AIRouter
    dart_client: DartClient | None = None
    default_budget: ResearchBudget = field(default_factory=lambda: ResearchBudget(max_tokens=8000, max_requests=20))

    def create_plan(
        self,
        thesis: Thesis | None = None,
        asset_id: str = "",
        context: ContextEnvelope | None = None,
        custom_questions: list[str] | None = None,
        required_sources: list[SourceProvider] | None = None,
        budget: ResearchBudget | None = None,
    ) -> ResearchPlan:
        questions = list(custom_questions) if custom_questions is not None else []
        sources = list(required_sources) if required_sources is not None else [SourceProvider.DART, SourceProvider.FINANCIAL_STATEMENTS]

        if thesis and not custom_questions:
            for ev_type in [EvidenceType.FUNDAMENTAL, EvidenceType.FILING, EvidenceType.NEWS]:
                questions.extend(DEFAULT_RESEARCH_QUESTIONS.get(ev_type, []))

        questions = list(dict.fromkeys(questions))

        return ResearchPlan(
            thesis_id=thesis.id if thesis else None,
            asset_id=asset_id,
            questions=questions[:10],
            required_sources=sources,
            budget=budget if budget is not None else ResearchBudget(
                max_tokens=self.default_budget.max_tokens, max_requests=self.default_budget.max_requests
            ),
            metadata={
                "context_thesis_count": len(context.active_theses) if context else 0,
                "has_falsification_conditions": len(context.falsification_conditions) > 0 if context else False,
            },
        )

    async def execute_plan(self, plan: ResearchPlan) -> ResearchResult:
        collected = []

        source_status: dict[str, str] = {}
        for source in plan.required_sources:
            if not isinstance(source, SourceProvider):
                source_status["INVALID_SOURCE"] = "UNSUPPORTED"
                continue
            if source.value in source_status:
                continue
            if source == SourceProvider.DART:
                dart_evidence, status = await self._collect_dart_filings(plan)
                collected.extend(dart_evidence)
                source_status[source.value] = status
            else:
                source_status[source.value] = "UNSUPPORTED"

        unique_collected, duplicates_removed = deduplicate_evidence(collected)

        result = ResearchResult(
            plan_id=plan.plan_id,
            thesis_id=plan.thesis_id,
            asset_id=plan.asset_id,
            collected=unique_collected,
            total_tokens=plan.budget.used_tokens,
            total_requests=plan.budget.used_requests,
            duplicates_removed=duplicates_removed,
            has_new_evidence=len(unique_collected) > 0,
            metadata={
                "questions_asked": len(plan.questions),
                "source_status": source_status,
                "status": "BLOCKED" if any(status != "OK" for status in source_status.values()) else "COMPLETED",
            },
        )

        return result


    async def _collect_dart_filings(self, plan: ResearchPlan) -> tuple[list[CollectedEvidence], str]:
        if not self.dart_client:
            return [], "NOT_CONFIGURED"

        parts = plan.asset_id.split(":")
        corp_code = plan.metadata.get("dart_corp_code")
        if len(parts) != 4 or parts[0] != "KRX" or not isinstance(corp_code, str) or len(corp_code) != 8 or not corp_code.isascii() or not corp_code.isdigit():
            return [], "IDENTITY_UNVERIFIED"
        if not plan.budget.can_request(0):
            return [], "BUDGET_EXCEEDED"

        try:
            plan.budget.consume(0, 1)
            filings = await self.dart_client.search_recent_filings(
                corp_code=corp_code,
                days_back=30,
            )

            evidence_list = []
            for filing in filings[:20]:
                if filing.corp_code != corp_code or filing.stock_code != parts[2]:
                    return [], "IDENTITY_MISMATCH"
                if filing.published_at_utc is None:
                    return [], "PUBLICATION_TIME_UNVERIFIED"
                ev = convert_filing_to_evidence(filing, plan.thesis_id, plan.asset_id)
                evidence_list.append(ev)

            return evidence_list, "OK"
        except Exception:
            return [], "COLLECTION_FAILED"

    async def _collect_financial_statements(self, plan: ResearchPlan) -> list[CollectedEvidence]:
        return []

    async def _collect_news(self, plan: ResearchPlan) -> list[CollectedEvidence]:
        return []

    async def _collect_technical(self, plan: ResearchPlan) -> list[CollectedEvidence]:
        return []

    async def _collect_macro(self, plan: ResearchPlan) -> list[CollectedEvidence]:
        return []

    async def generate_research_summary(
        self,
        result: ResearchResult,
        context: ContextEnvelope | None = None,
    ) -> str:
        if result.metadata.get("status") == "BLOCKED":
            return "조사에 실패하거나 지원하지 않는 출처가 있어 판단을 차단해야 합니다."
        if not result.has_new_evidence:
            return "신규 수집된 근거 없음."
        return f"수집된 근거 {len(result.collected)}건. AI 요약은 지원하지 않습니다."

    async def close(self):
        if self.dart_client:
            await self.dart_client.close()
