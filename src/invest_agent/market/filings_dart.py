"""DART 공시 조회 - 금융감독원 전자공시시스템 연동."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from invest_agent.domain.models import Evidence, EvidenceType
from invest_agent.market.evidence import (
    CollectedEvidence,
    SourceProvider,
    sanitize_prompt_input,
)

DART_API_BASE = "https://opendart.fss.or.kr/api"
CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"


@dataclass(slots=True)
class DartConfig:
    """DART API 설정."""
    api_key: str | None = None
    timeout_seconds: int = 30
    max_pages: int = 10
    page_size: int = 100

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = os.getenv("DART_API_KEY")


@dataclass(slots=True)
class FilingSearchParams:
    """공시 검색 파라미터."""
    corp_code: str | None = None
    corp_name: str | None = None
    bgn_de: str | None = None
    end_de: str | None = None
    last_reprt_at: str = "N"
    pblntf_ty: str = "A"
    page_no: int = 1
    page_count: int = 100
@dataclass(slots=True)
class DartFiling:
    """DART 공시 원본 데이터."""
    rcept_no: str
    corp_cls: str
    corp_code: str
    corp_name: str
    flr_nm: str
    rcept_dt: str
    rpt_nm: str
    rm: str
    link: str = ""


class DartClient:
    """DART API 클라이언트."""

    def __init__(self, config: DartConfig | None = None):
        self.config = config or DartConfig()
        self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
        self._corp_code_cache: dict[str, str] = {}

    async def close(self):
        await self._client.aclose()

    def _get_api_key(self) -> str:
        if not self.config.api_key:
            raise ValueError("DART_API_KEY가 설정되지 않았습니다.")
        return self.config.api_key

    async def search_filings(self, params: FilingSearchParams) -> list[DartFiling]:
        api_key = self._get_api_key()

        url = f"{DART_API_BASE}/list.json"
        query_params = {
            "crtfc_key": api_key,
            "page_no": params.page_no,
            "page_count": min(params.page_count, self.config.page_size),
        }

        if params.corp_code:
            query_params["corp_code"] = params.corp_code
        if params.corp_name:
            query_params["corp_name"] = params.corp_name
        if params.bgn_de:
            query_params["bgn_de"] = params.bgn_de
        if params.end_de:
            query_params["end_de"] = params.end_de
        if params.last_reprt_at:
            query_params["last_reprt_at"] = params.last_reprt_at
        if params.pblntf_ty:
            query_params["pblntf_ty"] = params.pblntf_ty

        response = await self._client.get(url, params=query_params)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "000":
            if data.get("status") == "013":
                return []
            raise RuntimeError(f"DART API 오류: {data.get('message', 'Unknown error')}")

        filings = []
        for item in data.get("list", []):
            filings.append(DartFiling(
                rcept_no=item.get("rcept_no", ""),
                corp_cls=item.get("corp_cls", ""),
                corp_code=item.get("corp_code", ""),
                corp_name=item.get("corp_name", ""),
                flr_nm=item.get("flr_nm", ""),
                rcept_dt=item.get("rcept_dt", ""),
                rpt_nm=item.get("rpt_nm", ""),
                rm=item.get("rm", ""),
                link=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
            ))

        return filings

    async def get_filing_detail(self, rcept_no: str) -> dict[str, Any] | None:
        api_key = self._get_api_key()

        url = f"{DART_API_BASE}/document.xml"
        params = {"crtfc_key": api_key, "rcept_no": rcept_no}

        response = await self._client.get(url, params=params)
        response.raise_for_status()

        return {"rcept_no": rcept_no, "raw_xml": response.text[:5000]}

    async def resolve_corp_code(self, corp_name: str) -> str | None:
        if corp_name in self._corp_code_cache:
            return self._corp_code_cache[corp_name]

        params = FilingSearchParams(corp_name=corp_name, page_count=1)
        filings = await self.search_filings(params)
        if filings:
            corp_code = filings[0].corp_code
            self._corp_code_cache[corp_name] = corp_code
            return corp_code
        return None

    async def search_recent_filings(
        self,
        corp_name: str,
        days_back: int = 30,
        filing_types: list[str] | None = None,
    ) -> list[DartFiling]:
        from datetime import timedelta

        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days_back)

        params = FilingSearchParams(
            corp_name=corp_name,
            bgn_de=start_date.strftime("%Y%m%d"),
            end_de=end_date.strftime("%Y%m%d"),
            page_count=self.config.page_size,
        )

        filings = await self.search_filings(params)

        if filing_types:
            filings = [f for f in filings if f.rpt_nm in filing_types]

def convert_filing_to_evidence(
    filing: DartFiling,
    thesis_id: UUID | None = None,
    asset_id: str = "",
) -> CollectedEvidence:
    """DART 공시를 Evidence로 변환."""
    observed_at = None
    try:
        if filing.rcept_dt:
            observed_at = datetime.strptime(filing.rcept_dt, "%Y%m%d")
    except ValueError:
        observed_at = datetime.now(UTC)

    evidence_type = _classify_filing_type(filing.rpt_nm)

    content = {
        "rcept_no": filing.rcept_no,
        "corp_name": sanitize_prompt_input(filing.corp_name),
        "rpt_nm": sanitize_prompt_input(filing.rpt_nm),
        "flr_nm": sanitize_prompt_input(filing.flr_nm),
        "rcept_dt": filing.rcept_dt,
        "rm": sanitize_prompt_input(filing.rm),
        "link": filing.link,
    }

    evidence = Evidence(
        id=uuid4(),
        thesis_id=thesis_id or UUID(int=0),
        evidence_type=evidence_type,
        source="DART",
        observed_at=observed_at,
        collected_at=datetime.now(UTC),
        content=content,
        raw_ref=filing.link,
        metadata={
            "corp_code": filing.corp_code,
            "corp_cls": filing.corp_cls,
            "source_provider": SourceProvider.DART.value,
        },
    )

    return CollectedEvidence(
        evidence=evidence,
        source_provider=SourceProvider.DART,
        collected_at=datetime.now(UTC),
        tokens_used=0,
        request_count=1,
    )


def _classify_filing_type(report_name: str) -> EvidenceType:
    """공시 보고서명을 증거 유형으로 분류."""
    report_lower = report_name.lower()

    if any(kw in report_lower for kw in ["사업보고서", "분기보고서", "반기보고서", "결산"]):
        return EvidenceType.FILING
    elif any(kw in report_lower for kw in ["주요사항보고서", "증자", "감자", "합병", "분할", "영업양수도"]):
        return EvidenceType.FILING
    elif any(kw in report_lower for kw in ["지분공시", "대량보유", "변동보고"]):
        return EvidenceType.FILING
    elif any(kw in report_lower for kw in ["발행공시", "전환사채", "신주인수권", "bw", "cb"]):
        return EvidenceType.FILING
    elif any(kw in report_lower for kw in ["재무제표", "손익", "재무상태"]):
        return EvidenceType.FUNDAMENTAL
    else:
        return EvidenceType.FILING
