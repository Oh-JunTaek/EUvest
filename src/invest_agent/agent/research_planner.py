"""Research Planner - 자율 연구 계획 수립 및 실행."""

from __future__ import annotations

from dataclasses import dataclass, field

from invest_agent.agent.context_builder import ContextEnvelope
from invest_agent.ai.protocol import AIRequest, AIResponse
from invest_agent.ai.router import ProviderRouter as AIRouter
from invest_agent.domain.models import EvidenceType, Thesis
from invest_agent.market.evidence import (
    CollectedEvidence,
    ResearchBudget,
    ResearchPlan,
    ResearchResult,
    SourceProvider,
    deduplicate_evidence,
    sanitize_prompt_input,
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

    def __post_init__(self):
        if self.dart_client is None:
            self.dart_client = DartClient()

    def create_plan(
        self,
        thesis: Thesis | None = None,
        asset_id: str = "",
        context: ContextEnvelope | None = None,
        custom_questions: list[str] | None = None,
        required_sources: list[SourceProvider] | None = None,
        budget: ResearchBudget | None = None,
    ) -> ResearchPlan:
        questions = custom_questions or []
        sources = required_sources or [SourceProvider.DART, SourceProvider.FINANCIAL_STATEMENTS]

        if thesis and not custom_questions:
            for ev_type in [EvidenceType.FUNDAMENTAL, EvidenceType.FILING, EvidenceType.NEWS]:
                questions.extend(DEFAULT_RESEARCH_QUESTIONS.get(ev_type, []))

        questions = list(dict.fromkeys(questions))

        return ResearchPlan(
            thesis_id=thesis.id if thesis else None,
            asset_id=asset_id,
            questions=questions[:10],
            required_sources=sources,
            budget=budget or self.default_budget,
            metadata={
                "context_thesis_count": len(context.active_theses) if context else 0,
                "has_falsification_conditions": len(context.falsification_conditions) > 0 if context else False,
            },
        )

    async def execute_plan(self, plan: ResearchPlan) -> ResearchResult:
        collected = []

        if SourceProvider.DART in plan.required_sources and plan.budget.can_request():
            dart_evidence = await self._collect_dart_filings(plan)
            collected.extend(dart_evidence)
            self._consume_budget(plan, dart_evidence)

        if SourceProvider.FINANCIAL_STATEMENTS in plan.required_sources and plan.budget.can_request():
            financial_evidence = await self._collect_financial_statements(plan)
            collected.extend(financial_evidence)
            self._consume_budget(plan, financial_evidence)

        if SourceProvider.NEWS_KR in plan.required_sources and plan.budget.can_request():
            news_evidence = await self._collect_news(plan)
            collected.extend(news_evidence)
            self._consume_budget(plan, news_evidence)

        if SourceProvider.TECHNICAL in plan.required_sources and plan.budget.can_request():
            tech_evidence = await self._collect_technical(plan)
            collected.extend(tech_evidence)
            self._consume_budget(plan, tech_evidence)

        if SourceProvider.MACRO_KR in plan.required_sources and plan.budget.can_request():
            macro_evidence = await self._collect_macro(plan)
            collected.extend(macro_evidence)
            self._consume_budget(plan, macro_evidence)

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
                "sources_used": [s.value for s in plan.required_sources],
            },
        )

        return result


    def _consume_budget(self, plan: ResearchPlan, evidence_list: list[CollectedEvidence]) -> None:
        for ev in evidence_list:
            plan.budget.consume(ev.tokens_used, ev.request_count)

    async def _collect_dart_filings(self, plan: ResearchPlan) -> list[CollectedEvidence]:
        if not self.dart_client:
            return []

        try:
            filings = await self.dart_client.search_recent_filings(
                corp_name=plan.asset_id,
                days_back=30,
            )

            evidence_list = []
            for filing in filings[:20]:
                if not plan.budget.can_request():
                    break
                ev = convert_filing_to_evidence(filing, plan.thesis_id, plan.asset_id)
                evidence_list.append(ev)

            return evidence_list
        except Exception as e:
            return [CollectedEvidence(
                evidence=None,  # type: ignore
                source_provider=SourceProvider.DART,
                metadata={"error": str(e)},
            )]

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
        if not result.has_new_evidence:
            return "신규 수집된 근거 없음."

        evidence_summary = []
        for ev in result.collected[:10]:
            if ev.evidence:
                content_str = str(ev.evidence.content)[:500]
                evidence_summary.append(
                    f"- [{ev.source_provider.value}] {ev.evidence.evidence_type.value}: {content_str}"
                )

        prompt = f"""다음은 {result.asset_id}에 대한 투자 연구 수집 결과입니다.
수집된 근거들을 종합하여 300자 이내 한국어 요약을 작성하세요.

수집 근거:
{chr(10).join(evidence_summary)}

요약:"""

        prompt = sanitize_prompt_input(prompt)

        try:
            request = AIRequest(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3,
            )
            response: AIResponse = await self.ai_router.generate(request)
            return sanitize_prompt_input(response.content)
        except Exception:
            return "AI 요약 생성 실패. 원본 근거 참고 요망."

    async def close(self):
        if self.dart_client:
            await self.dart_client.close()
