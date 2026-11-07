"""DART 공시 조회 - 금융감독원 전자공시시스템 연동."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

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
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: int = 30
    max_pages: int = 10
    page_size: int = 100

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = os.getenv("OPENDART_API_KEY") or os.getenv("DART_API_KEY")


@dataclass(slots=True)
class FilingSearchParams:
    """공시 검색 파라미터."""
    corp_code: str | None = None
    corp_name: str | None = None
    bgn_de: str | None = None
    end_de: str | None = None
    last_reprt_at: str = "N"
    pblntf_ty: str | None = None
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
    stock_code: str = ""
    published_at_utc: datetime | None = None


class DartClient:
    """DART API 클라이언트."""

    def __init__(self, config: DartConfig | None = None, transport: httpx.MockTransport | None = None):
        self.config = config or DartConfig()
        self._mock_only = isinstance(transport, httpx.MockTransport)
        self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds, transport=transport)

    async def close(self):
        await self._client.aclose()

    def _get_api_key(self) -> str:
        if not self.config.api_key:
            raise ValueError("OpenDART 인증키가 설정되지 않았습니다.")
        return self.config.api_key

    async def search_filings(self, params: FilingSearchParams) -> list[DartFiling]:
        if not params.corp_code or len(params.corp_code) != 8 or not params.corp_code.isascii() or not params.corp_code.isdigit():
            raise ValueError("검증된 8자리 DART 고유번호가 필요합니다")
        if params.corp_name:
            raise ValueError("회사명으로 공시검색 고유번호를 추정할 수 없습니다")
        if not self._mock_only:
            raise RuntimeError("DART_NETWORK_DISABLED_PENDING_SECRET_LOG_REVIEW")
        api_key = self._get_api_key()

        url = f"{DART_API_BASE}/list.json"
        query_params = {
            "crtfc_key": api_key,
            "page_no": params.page_no,
            "page_count": min(params.page_count, self.config.page_size),
        }

        if params.corp_code:
            query_params["corp_code"] = params.corp_code
        if params.bgn_de:
            query_params["bgn_de"] = params.bgn_de
        if params.end_de:
            query_params["end_de"] = params.end_de
        if params.last_reprt_at:
            query_params["last_reprt_at"] = params.last_reprt_at
        if params.pblntf_ty:
            query_params["pblntf_ty"] = params.pblntf_ty

        try:
            response = await self._client.get(url, params=query_params)
            response.raise_for_status()
        except httpx.HTTPError:
            raise RuntimeError("DART_HTTP_ERROR") from None
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("DART_INVALID_RESPONSE") from None
        if not isinstance(data, dict):
            raise RuntimeError("DART_INVALID_RESPONSE")

        if data.get("status") != "000":
            if data.get("status") == "013":
                return []
            raise RuntimeError("DART_API_ERROR")

        pages = data.get("total_page")
        if not str(pages).isascii() or not str(pages).isdigit() or int(pages) < 1:
            raise RuntimeError("DART_INVALID_RESPONSE")
        if int(pages) > params.page_no:
            raise RuntimeError("DART_PAGINATION_UNSUPPORTED")
        if not isinstance(data.get("list"), list) or any(not isinstance(item, dict) for item in data["list"]):
            raise RuntimeError("DART_INVALID_RESPONSE")

        filings = []
        for item in data.get("list", []):
            filings.append(DartFiling(
                rcept_no=item.get("rcept_no", ""),
                corp_cls=item.get("corp_cls", ""),
                corp_code=item.get("corp_code", ""),
                corp_name=item.get("corp_name", ""),
                flr_nm=item.get("flr_nm", ""),
                rcept_dt=item.get("rcept_dt", ""),
                rpt_nm=item.get("report_nm", ""),
                rm=item.get("rm", ""),
                link=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
                stock_code=item.get("stock_code", ""),
            ))

        return filings

    async def get_filing_detail(self, rcept_no: str) -> dict[str, Any] | None:
        raise NotImplementedError("DART 원본 ZIP 처리 및 검증은 아직 지원하지 않습니다")

    async def resolve_corp_code(self, corp_name: str) -> str | None:
        raise NotImplementedError("공식 고유번호 ZIP 매핑은 아직 지원하지 않습니다")

    async def search_recent_filings(
        self,
        corp_code: str,
        days_back: int = 30,
        filing_types: list[str] | None = None,
    ) -> list[DartFiling]:
        from datetime import timedelta

        if days_back < 0:
            raise ValueError("조회 기간은 음수일 수 없습니다")

        end_date = datetime.now(ZoneInfo("Asia/Seoul"))
        start_date = end_date - timedelta(days=days_back)

        params = FilingSearchParams(
            corp_code=corp_code,
            bgn_de=start_date.strftime("%Y%m%d"),
            end_de=end_date.strftime("%Y%m%d"),
            page_count=self.config.page_size,
        )

        filings = await self.search_filings(params)

        if filing_types:
            filings = [f for f in filings if f.rpt_nm in filing_types]
        return filings

def convert_filing_to_evidence(
    filing: DartFiling,
    thesis_id: UUID | None = None,
    asset_id: str = "",
) -> CollectedEvidence:
    """DART 공시를 Evidence로 변환."""
    observed_at = filing.published_at_utc
    if observed_at is None or observed_at.utcoffset() is None:
        raise ValueError("공시 발표 시각을 확인할 수 없습니다")
    observed_at = observed_at.astimezone(UTC)
    if observed_at > datetime.now(UTC):
        raise ValueError("미래 시각의 공시는 사용할 수 없습니다")
    if observed_at.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d") != filing.rcept_dt:
        raise ValueError("공시 발표 시각과 접수일이 일치하지 않습니다")
    parts = asset_id.split(":")
    if (len(parts) != 4 or parts[0] != "KRX" or parts[2] != filing.stock_code
            or len(filing.corp_code) != 8 or not filing.corp_code.isascii() or not filing.corp_code.isdigit()
            or len(filing.rcept_no) != 14 or not filing.rcept_no.isascii() or not filing.rcept_no.isdigit()):
        raise ValueError("공시와 자산 식별자가 일치하지 않습니다")
    link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={filing.rcept_no}"

    evidence_type = _classify_filing_type(filing.rpt_nm)

    content = {
        "rcept_no": filing.rcept_no,
        "corp_name": sanitize_prompt_input(filing.corp_name),
        "rpt_nm": sanitize_prompt_input(filing.rpt_nm),
        "flr_nm": sanitize_prompt_input(filing.flr_nm),
        "rcept_dt": filing.rcept_dt,
        "rm": sanitize_prompt_input(filing.rm),
        "link": link,
    }

    evidence = Evidence(
        id=uuid4(),
        thesis_id=thesis_id or UUID(int=0),
        evidence_type=evidence_type,
        source="DART",
        observed_at=observed_at,
        collected_at=datetime.now(UTC),
        content=content,
        raw_ref=link,
        metadata={
            "corp_code": filing.corp_code,
            "corp_cls": filing.corp_cls,
            "source_provider": SourceProvider.DART.value,
            "asset_id": asset_id,
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
