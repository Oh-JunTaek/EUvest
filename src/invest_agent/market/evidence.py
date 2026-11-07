"""Evidence/Research Pipeline - 근거 수집·정규화·중복 제거."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from invest_agent.domain.models import Evidence, EvidenceType


class SourceProvider(StrEnum):
    """허용된 데이터 공급자."""
    DART = "DART"              # 금융감독원 전자공시
    KRX = "KRX"                # 한국거래소
    FINANCIAL_STATEMENTS = "FINANCIAL_STATEMENTS"  # 재무제표
    NEWS_KR = "NEWS_KR"        # 국내 뉴스
    NEWS_US = "NEWS_US"        # 해외 뉴스
    MACRO_KR = "MACRO_KR"      # 국내 거시지표
    MACRO_US = "MACRO_US"      # 해외 거시지표
    TECHNICAL = "TECHNICAL"    # 기술적 분석
    COMPANY_FILING = "COMPANY_FILING"  # 기업 공시


@dataclass(slots=True)
class ResearchBudget:
    """연구 예산 관리."""
    max_tokens: int = 8000          # 총 입력 토큰 제한
    max_requests: int = 20          # 총 요청 횟수 제한
    used_tokens: int = 0
    used_requests: int = 0

    def __post_init__(self) -> None:
        values = (self.max_tokens, self.max_requests, self.used_tokens, self.used_requests)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("예산과 사용량은 0 이상의 정수여야 합니다")
        if self.used_tokens > self.max_tokens or self.used_requests > self.max_requests:
            raise ValueError("초기 사용량이 예산을 초과했습니다")

    def can_request(self, estimated_tokens: int = 500) -> bool:
        if type(estimated_tokens) is not int or estimated_tokens < 0:
            raise ValueError("토큰 예상치는 0 이상의 정수여야 합니다")
        return (self.used_requests < self.max_requests and
                self.used_tokens + estimated_tokens <= self.max_tokens)

    def consume(self, tokens: int, requests: int = 1) -> None:
        if type(tokens) is not int or type(requests) is not int or tokens < 0 or requests < 0:
            raise ValueError("사용량은 0 이상의 정수여야 합니다")
        if self.used_tokens + tokens > self.max_tokens or self.used_requests + requests > self.max_requests:
            raise ValueError("연구 예산 초과")
        self.used_tokens += tokens
        self.used_requests += requests


@dataclass(slots=True)
class ResearchPlan:
    """연구 계획."""
    plan_id: UUID = field(default_factory=uuid4)
    thesis_id: UUID | None = None
    asset_id: str = ""
    questions: list[str] = field(default_factory=list)
    required_sources: list[SourceProvider] = field(default_factory=list)
    budget: ResearchBudget = field(default_factory=ResearchBudget)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollectedEvidence:
    """수집된 증거 (Evidence 확장)."""
    evidence: Evidence
    source_provider: SourceProvider
    collected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tokens_used: int = 0
    request_count: int = 1
    is_duplicate: bool = False
    duplicate_of: UUID | None = None
    relevance_score: float = 1.0  # 0.0 ~ 1.0


@dataclass(slots=True)
class ResearchResult:
    """연구 결과."""
    plan_id: UUID
    thesis_id: UUID | None
    asset_id: str
    collected: list[CollectedEvidence] = field(default_factory=list)
    total_tokens: int = 0
    total_requests: int = 0
    duplicates_removed: int = 0
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    has_new_evidence: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_evidence_by_type(self, evidence_type: EvidenceType) -> list[CollectedEvidence]:
        return [e for e in self.collected if e.evidence.evidence_type == evidence_type]

    def get_unique_sources(self) -> list[SourceProvider]:
        return list(set(e.source_provider for e in self.collected))


def deduplicate_evidence(
    evidence_list: list[CollectedEvidence],
    similarity_threshold: float = 0.85
) -> tuple[list[CollectedEvidence], int]:
    """출처와 내용이 동일한 증거만 제거한다. 유사도 인수는 기존 호출 호환용이다."""
    unique = []
    removed = 0

    for ev in evidence_list:
        is_dup = False
        for existing in unique:
            if (ev.source_provider == existing.source_provider
                    and ev.evidence.raw_ref == existing.evidence.raw_ref
                    and _is_similar(ev.evidence.content, existing.evidence.content, similarity_threshold)):
                is_dup = True
                ev.is_duplicate = True
                ev.duplicate_of = existing.evidence.id
                removed += 1
                break

        if not is_dup:
            unique.append(ev)

    return unique, removed


def _is_similar(content1: dict[str, Any], content2: dict[str, Any], threshold: float) -> bool:
    """모든 값이 같은 경우만 중복으로 취급한다."""
    return bool(content1) and content1 == content2


def sanitize_prompt_input(text: str | None, max_length: int = 10000) -> str:
    """길이와 일부 문구만 정리한다. 명령 주입 차단 보장은 아니다."""
    if max_length < 0:
        raise ValueError("최대 길이는 음수일 수 없습니다")
    if not text:
        return ""

    # 위험 패턴 차단 (먼저 처리)
    dangerous_patterns = [
        "ignore previous instructions",
        "ignore all previous",
        "system prompt",
        "you are now",
        "pretend to be",
        "act as",
        "roleplay",
        "###",
        "<<<",
        ">>>",
        "```",
        "SYSTEM:",
        "ASSISTANT:",
        "USER:",
    ]

    import re

    for pattern in dangerous_patterns:
        text = re.sub(re.escape(pattern), "[FILTERED]", text, flags=re.IGNORECASE)

    # 길이 제한 (마지막에 처리)
    if len(text) > max_length:
        # 트렁케이션 마커를 위한 공간 확보
        truncate_at = max_length - len("...[truncated]")
        if truncate_at > 0:
            text = text[:truncate_at] + "...[truncated]"
        else:
            text = text[:max_length]

    return text


def extract_publication_timestamp(content: dict[str, Any]) -> datetime | None:
    """공개 자료에서 발표 시각 추출."""
    timestamp_fields = [
        "published_at", "publishedAt", "pub_date", "pubDate",
        "disclosure_date", "disclosureDate",
    ]

    for ts_field in timestamp_fields:
        if ts_field in content:
            value = content[ts_field]
            if isinstance(value, str):
                try:
                    # ISO 포맷 파싱 시도
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.utcoffset() is not None:
                        return parsed.astimezone(UTC)
                except ValueError:
                    pass
            elif isinstance(value, datetime):
                if value.utcoffset() is not None:
                    return value.astimezone(UTC)

    return None
