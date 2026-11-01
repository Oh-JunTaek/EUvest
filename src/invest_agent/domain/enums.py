"""도메인 열거형 - 투자 시스템 전역에서 사용하는 상수들."""

from enum import StrEnum


class Market(StrEnum):
    """지원 시장."""

    KRX = "KRX"
    US = "US"


class AssetType(StrEnum):
    """자산 유형."""

    STOCK = "STOCK"
    ETF = "ETF"
    DOMESTIC_BOND = "DOMESTIC_BOND"
    FOREIGN_BOND = "FOREIGN_BOND"
    LEVERAGED_ETF = "LEVERAGED_ETF"
    INVERSE_ETF = "INVERSE_ETF"
    DERIVATIVE = "DERIVATIVE"


class ExecutionMode(StrEnum):
    """실행 모드 - docs/00_SCOPE_AND_DECISIONS.md 섹션 C 준수."""

    BACKTEST = "BACKTEST"
    OFFLINE_SIM = "OFFLINE_SIM"
    KIS_PAPER = "KIS_PAPER"
    LIVE = "LIVE"


class RunStatus(StrEnum):
    """단일 실행 상태 - docs/01_ARCHITECTURE.md 상태 기계 준수."""

    CREATED = "CREATED"
    RECONCILING = "RECONCILING"
    COLLECTING = "COLLECTING"
    DECIDING = "DECIDING"
    VALIDATING = "VALIDATING"
    EXECUTING = "EXECUTING"
    RECONCILING_ORDERS = "RECONCILING_ORDERS"
    COMPLETED = "COMPLETED"
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SKIPPED_ALREADY_RUNNING = "SKIPPED_ALREADY_RUNNING"


class OrderSide(StrEnum):
    """주문 방향."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """주문 유형 - 초기 LIMIT_ONLY 강제."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    """주문 상태 - docs/06_ORDERS_AND_RISK.md 상태 기계 준수."""

    INTENT_CREATED = "INTENT_CREATED"
    PRECHECKED = "PRECHECKED"
    REJECTED = "REJECTED"
    RESERVED = "RESERVED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNKNOWN = "UNKNOWN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class CashFlowType(StrEnum):
    """현금흐름 유형 - docs/03_INTERFACES_AND_SCHEMA.md 섹션 C 준수."""

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    FX = "FX"
    FEE = "FEE"
    TAX = "TAX"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    REALIZED_PNL = "REALIZED_PNL"


class LLMProvider(StrEnum):
    """LLM 공급자."""

    FAKE = "fake"
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA = "ollama"
    NVIDIA = "nvidia"


class BrokerEnvironment(StrEnum):
    """브로커 환경."""

    MOCK = "MOCK"
    PAPER = "PAPER"
    LIVE = "LIVE"


class AssetEligibility(StrEnum):
    """자산 거래 적격성."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"
