"""새 저장 계약의 값 검증. 과거 기록을 자동 변환하지 않는다."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class AssetInput(BaseModel):
    """시장과 거래소를 포함하는 자산 저장 입력."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    asset_id: str
    market: Literal["KRX", "US"]
    venue: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    asset_type: Literal["STOCK", "ETF", "DOMESTIC_BOND", "FOREIGN_BOND"]
    currency: Literal["KRW", "USD"]
    leveraged: bool = Field(strict=True)
    trading_enabled: bool = Field(default=False, strict=True)
    eligibility_status: Literal["VERIFIED", "UNVERIFIED", "UNSUPPORTED", "BLOCKED"]

    @model_validator(mode="after")
    def identity_matches(self) -> "AssetInput":
        if any(":" in part or part != part.strip() for part in (self.venue, self.symbol)):
            raise ValueError("거래소 또는 종목 식별자가 잘못되었습니다")
        if self.asset_id != f"{self.market}:{self.venue}:{self.symbol}:{self.asset_type}":
            raise ValueError("자산 식별자와 시장·거래소·종목·상품이 일치하지 않습니다")
        return self


class RunInput(BaseModel):
    """현재 상태에 고정할 실행 기록."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    run_id: str = Field(min_length=1)
    state_version: int = Field(ge=0, strict=True)
    mode: Literal["OFFLINE_SIM", "BACKTEST", "KIS_PAPER", "LIVE"]
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    started_utc: AwareDatetime

    @field_validator("started_utc", mode="before")
    @classmethod
    def reject_numeric_timestamp(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            raise ValueError("숫자 시각은 허용되지 않습니다")
        return value

    @field_validator("run_id", "provider", "model", "input_hash")
    @classmethod
    def run_fields_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("실행 식별 정보는 비어 있을 수 없습니다")
        return value


class ThesisInput(BaseModel):
    """변경 이력을 보존하는 가설 버전."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    thesis_id: str = Field(min_length=1)
    version: int = Field(ge=1, strict=True)
    horizon_days: int = Field(ge=1, strict=True)
    asset_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    premise: str = Field(min_length=1)
    invalidation: list[str]
    evidence_ids: list[str]

    @field_validator("thesis_id", "asset_id", "status", "premise")
    @classmethod
    def thesis_fields_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("가설 필드는 비어 있을 수 없습니다")
        return value

    @field_validator("invalidation", "evidence_ids")
    @classmethod
    def no_empty_list_entries(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("빈 목록 항목은 허용되지 않습니다")
        if len(set(values)) != len(values):
            raise ValueError("중복 목록 항목은 허용되지 않습니다")
        return values


class EvidenceInput(BaseModel):
    """시점과 출처를 포함하는 불변 증거."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    evidence_id: str = Field(min_length=1)
    asset_ids: list[str] = Field(min_length=1)
    source_url: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    published_at_utc: AwareDatetime
    retrieved_at_utc: AwareDatetime
    text_excerpt: str
    content_hash: str = Field(min_length=1)

    @field_validator("published_at_utc", "retrieved_at_utc", mode="before")
    @classmethod
    def reject_numeric_timestamp(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            raise ValueError("숫자 시각은 허용되지 않습니다")
        return value

    @field_validator("evidence_id", "source_url", "publisher", "content_hash")
    @classmethod
    def fields_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("증거의 출처·식별 정보는 비어 있을 수 없습니다")
        return value

    @model_validator(mode="after")
    def valid_assets_and_times(self) -> "EvidenceInput":
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("증거의 자산 ID는 중복될 수 없습니다")
        if any(len(asset_id.split(":")) != 4 or any(not part.strip() for part in asset_id.split(":")) for asset_id in self.asset_ids):
            raise ValueError("증거의 자산 ID가 잘못되었습니다")
        if self.published_at_utc > self.retrieved_at_utc:
            raise ValueError("증거 발표 시각이 수집 시각보다 늦습니다")
        return self


class OrderIntentInput(BaseModel):
    """저장할 intent. 위험 검증을 통과했다는 의미는 아니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    intent_id: str
    decision_id: str
    asset_id: str
    side: Literal["BUY", "SELL"]
    qty: Decimal
    limit_price: Decimal
    currency: Literal["KRW", "USD"]
    mode: Literal["OFFLINE_SIM", "BACKTEST", "KIS_PAPER", "LIVE"]
    idempotency_key: str

    @field_validator("intent_id", "decision_id", "idempotency_key")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("빈 식별자는 허용되지 않습니다")
        return value

    @field_validator("asset_id")
    @classmethod
    def asset_identity(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 4 or any(not part or part != part.strip() for part in parts):
            raise ValueError("asset_id는 market:venue:symbol:type 형식이어야 합니다")
        return value

    @field_validator("qty", "limit_price", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("금액과 수량에 float 또는 bool을 사용할 수 없습니다")
        return value

    @field_validator("qty", "limit_price")
    @classmethod
    def positive_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("금액과 수량은 유한한 양수여야 합니다")
        return value


class DecisionItemLink(BaseModel):
    """스키마 검증 후 intent와 연결할 판단 항목."""

    asset_id: str
    side: Literal["BUY", "SELL"]


class DecisionLink(BaseModel):
    """스키마 검증 후 상태 및 주문 방향과 비교하는 판단 필드."""

    run_id: str
    state_version: int
    as_of_utc: AwareDatetime
    action: Literal["TRADE", "NO_TRADE"]
    items: list[DecisionItemLink]


def utc_text(value: datetime) -> str:
    """시간대 없는 시간은 ValueError로 거부하고 UTC로 직렬화한다."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시간대가 없는 시각은 허용되지 않습니다")
    return value.astimezone(UTC).isoformat()
