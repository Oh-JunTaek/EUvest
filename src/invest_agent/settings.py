"""설정 모델 - Pydantic v2 기반, 환경변수/YAML 로드 및 검증."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 파일을 os.environ에 로드 (모델 밸리데이터에서 사용 가능하도록)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from invest_agent.domain.enums import (
    BrokerEnvironment,
    ExecutionMode,
    LLMProvider,
)


class MarketConfig(BaseModel):
    KRX: bool = True
    US: bool = True


class AssetTypeConfig(BaseModel):
    STOCK: bool = True
    ETF: bool = True
    DOMESTIC_BOND: bool = False
    FOREIGN_BOND: bool = False
    LEVERAGED_ETF: bool = False
    INVERSE_ETF: bool = False
    DERIVATIVE: bool = False


class MarketDataConfig(BaseModel):
    """시장 데이터 공급자 설정."""
    provider: Literal["fdr", "kis"] = "fdr"
    fdr_request_delay_seconds: float = Field(default=1.0, ge=0.1, le=10.0)
    fdr_timeout_seconds: int = Field(default=30, ge=5, le=300)
    cache_ttl_seconds: int = Field(default=3600, ge=60, le=86400)  # 1시간 기본


class CapitalConfig(BaseModel):
    cash_only: bool = True
    allow_margin: bool = False
    allow_credit: bool = False
    allow_short: bool = False
    allow_loans: bool = False
    allow_auto_fx_conversion: bool = False
    max_order_notional: int | None = Field(default=None, ge=0)
    max_daily_loss: int | None = Field(default=None, ge=0)
    max_portfolio_exposure: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _enforce_cash_only(self) -> CapitalConfig:
        if not self.cash_only or any((self.allow_margin, self.allow_credit, self.allow_short, self.allow_loans)):
            raise ValueError("cash_only 필수, 신용·미수·공매도·차입 금지")
        return self


class UniverseConfig(BaseModel):
    allowed_assets: list[str] = Field(default_factory=list)
    ai_may_auto_add_to_allowlist: bool = False

    @model_validator(mode="after")
    def _forbid_auto_allowlist(self) -> UniverseConfig:
        if self.ai_may_auto_add_to_allowlist:
            raise ValueError("AI의 허용 목록 자동 변경 금지")
        return self


class SchedulerConfig(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=1, le=1440)
    overlap_policy: Literal["SKIP", "QUEUE"] = "SKIP"
    catch_up_missed_runs: bool = False
    max_research_rounds: int = Field(default=3, ge=0, le=10)


class AIConfig(BaseModel):
    provider: LLMProvider = LLMProvider.FAKE
    model: str = "fixture-default"
    fallback_enabled: bool = False
    max_calls_per_run: int = Field(default=4, ge=0, le=50)
    max_calls_per_day: int = Field(default=20, ge=0, le=500)
    max_input_tokens: int = Field(default=12000, ge=0)
    max_output_tokens: int = Field(default=2500, ge=0)
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    live_use_verified: bool = False
    endpoint: str | None = None
    api_key: SecretStr | None = None

    def __repr__(self) -> str:
        # 민감한 정보 마스킹 (SecretStr는 자동으로 마스킹됨)
        api_key_display = self.api_key.get_secret_value() if self.api_key else None
        return (f"AIConfig(provider={self.provider!r}, model={self.model!r}, "
                f"endpoint={self.endpoint!r}, api_key={'***' if api_key_display else None}, "
                f"fallback_enabled={self.fallback_enabled!r}, "
                f"max_calls_per_run={self.max_calls_per_run!r}, "
                f"max_calls_per_day={self.max_calls_per_day!r}, "
                f"max_input_tokens={self.max_input_tokens!r}, "
                f"max_output_tokens={self.max_output_tokens!r}, "
                f"timeout_seconds={self.timeout_seconds!r}, "
                f"live_use_verified={self.live_use_verified!r})")


class BrokerConfig(BaseModel):
    name: str = "KIS"
    environment: BrokerEnvironment = BrokerEnvironment.MOCK
    account_alias: str = "KIS_PRIMARY"
    quote_max_age_seconds: int | None = None
    live_allowed_products: list[str] = Field(default_factory=list)


class StorageConfig(BaseModel):
    db_path: str = "data/investor.db"
    log_dir: str = "data/logs"
    reports_dir: str = "data/reports"
    timezone_display: str = "Asia/Seoul"


class ReportsConfig(BaseModel):
    base_currency: str = "KRW"
    include_benchmarks: bool = True


class ExecutionConfig(BaseModel):
    mode: ExecutionMode = ExecutionMode.OFFLINE_SIM
    allow_live_orders: bool = False
    kill_switch: bool = True
    require_broker_reconciliation: bool = True
    order_type: Literal["LIMIT_ONLY", "LIMIT", "MARKET"] = "LIMIT_ONLY"
    market_sessions: Literal["REGULAR_ONLY", "ALL"] = "REGULAR_ONLY"
    # Mock FX rate for OFFLINE_SIM (1 USD = X KRW)
    mock_fx_rate_usd_krw: Decimal = Field(default=Decimal("1300"), ge=0)
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        validate_default=True,
    )

    schema_version: str = "1.0"
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    markets: MarketConfig = Field(default_factory=MarketConfig)
    asset_types: AssetTypeConfig = Field(default_factory=AssetTypeConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    capital: CapitalConfig = Field(default_factory=CapitalConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)

    @field_validator("execution", mode="before")
    @classmethod
    def _coerce_execution_mode(cls, v: Any) -> ExecutionConfig:
        if isinstance(v, dict):
            return ExecutionConfig(**v)
        return v

    @field_validator("markets", mode="before")
    @classmethod
    def _coerce_markets(cls, v: Any) -> MarketConfig:
        if isinstance(v, dict):
            return MarketConfig(**v)
        return v

    @field_validator("asset_types", mode="before")
    @classmethod
    def _coerce_asset_types(cls, v: Any) -> AssetTypeConfig:
        if isinstance(v, dict):
            return AssetTypeConfig(**v)
        return v

    @field_validator("market_data", mode="before")
    @classmethod
    def _coerce_market_data(cls, v: Any) -> MarketDataConfig:
        if isinstance(v, dict):
            return MarketDataConfig(**v)
        return v

    @field_validator("capital", mode="before")
    @classmethod
    def _coerce_capital(cls, v: Any) -> CapitalConfig:
        if isinstance(v, dict):
            return CapitalConfig(**v)
        return v

    @field_validator("universe", mode="before")
    @classmethod
    def _coerce_universe(cls, v: Any) -> UniverseConfig:
        if isinstance(v, dict):
            return UniverseConfig(**v)
        return v

    @field_validator("scheduler", mode="before")
    @classmethod
    def _coerce_scheduler(cls, v: Any) -> SchedulerConfig:
        if isinstance(v, dict):
            return SchedulerConfig(**v)
        return v

    @field_validator("ai", mode="before")
    @classmethod
    def _coerce_ai(cls, v: Any) -> AIConfig:
        if isinstance(v, dict):
            return AIConfig(**v)
        return v

    @field_validator("broker", mode="before")
    @classmethod
    def _coerce_broker(cls, v: Any) -> BrokerConfig:
        if isinstance(v, dict):
            return BrokerConfig(**v)
        return v

    @field_validator("storage", mode="before")
    @classmethod
    def _coerce_storage(cls, v: Any) -> StorageConfig:
        if isinstance(v, dict):
            return StorageConfig(**v)
        return v

    @field_validator("reports", mode="before")
    @classmethod
    def _coerce_reports(cls, v: Any) -> ReportsConfig:
        if isinstance(v, dict):
            return ReportsConfig(**v)
        return v
    @model_validator(mode="before")
    @classmethod
    def _map_invest_llm_env(cls, v: Any) -> Any:
        """INVEST_LLM_* 환경변수를 AI 설정으로 매핑. YAML의 null/빈 값은 환경변수로 덮어쓰기."""
        if not isinstance(v, dict):
            return v

        import os

        ai_config = v.get("ai", {})
        if isinstance(ai_config, dict):
            # INVEST_LLM_BASE_URL -> endpoint (YAML이 null이거나 없는 경우에만)
            if not ai_config.get("endpoint"):
                env_endpoint = os.getenv("INVEST_LLM_BASE_URL")
                if env_endpoint:
                    ai_config["endpoint"] = env_endpoint

            # INVEST_LLM_MODEL -> model (YAML이 fixture-default이거나 없는 경우에만)
            if not ai_config.get("model") or ai_config.get("model") == "fixture-default":
                env_model = os.getenv("INVEST_LLM_MODEL")
                if env_model:
                    ai_config["model"] = env_model

            # INVEST_LLM_API_KEY -> api_key (YAML에 없는 경우에만)
            if not ai_config.get("api_key"):
                env_api_key = os.getenv("INVEST_LLM_API_KEY")
                if env_api_key:
                    ai_config["api_key"] = env_api_key

            # OLLAMA_BASE_URL -> endpoint (provider가 ollama이고 YAML이 null인 경우)
            if ai_config.get("provider") == "ollama" and not ai_config.get("endpoint"):
                ollama_url = os.getenv("OLLAMA_BASE_URL")
                if ollama_url:
                    ai_config["endpoint"] = ollama_url

            # OLLAMA_MODEL -> model (provider가 ollama이고 YAML이 fixture-default인 경우)
            if ai_config.get("provider") == "ollama" and (not ai_config.get("model") or ai_config.get("model") == "fixture-default"):
                ollama_model = os.getenv("OLLAMA_MODEL")
                if ollama_model:
                    ai_config["model"] = ollama_model

            # provider가 명시되지 않았고 INVEST_LLM_*이 있으면 openai_compatible로 추정
            if not ai_config.get("provider") and (os.getenv("INVEST_LLM_BASE_URL") or os.getenv("INVEST_LLM_MODEL")):
                ai_config["provider"] = "openai_compatible"

            v["ai"] = ai_config

        return v

    @model_validator(mode="after")
    def _validate_mode_consistency(self) -> Settings:
        exec_mode = self.execution.mode
        broker_env = self.broker.environment
        allow_live = self.execution.allow_live_orders
        kill_switch = self.execution.kill_switch

        if exec_mode == ExecutionMode.LIVE:
            if broker_env != BrokerEnvironment.LIVE:
                raise ValueError(
                    f"LIVE 모드에서는 broker.environment가 LIVE여야 함 (현재: {broker_env})"
                )
            if not allow_live:
                raise ValueError("LIVE 모드에서는 execution.allow_live_orders=true 여야 함")
            if kill_switch:
                raise ValueError("LIVE 모드에서는 kill_switch=false 여야 함")

        if exec_mode == ExecutionMode.KIS_PAPER:
            if broker_env != BrokerEnvironment.PAPER:
                raise ValueError(
                    f"KIS_PAPER 모드에서는 broker.environment가 PAPER여야 함 (현재: {broker_env})"
                )
            if allow_live:
                raise ValueError("KIS_PAPER 모드에서는 allow_live_orders=false 여야 함")

        if exec_mode in (ExecutionMode.OFFLINE_SIM, ExecutionMode.BACKTEST):
            if broker_env != BrokerEnvironment.MOCK:
                raise ValueError(
                    f"{exec_mode} 모드에서는 broker.environment가 MOCK이어야 함 (현재: {broker_env})"
                )
            if allow_live:
                raise ValueError(f"{exec_mode} 모드에서는 allow_live_orders=false 여야 함")

        if self.asset_types.DERIVATIVE:
            raise ValueError("파생상품은 초기 범위 밖")
        if self.scheduler.overlap_policy != "SKIP" or self.scheduler.catch_up_missed_runs:
            raise ValueError("중복 실행 및 누락 실행 재시도 금지")

        return self

    def is_live_mode(self) -> bool:
        return self.execution.mode == ExecutionMode.LIVE

    def is_paper_mode(self) -> bool:
        return self.execution.mode == ExecutionMode.KIS_PAPER

    def is_offline_mode(self) -> bool:
        return self.execution.mode in (ExecutionMode.OFFLINE_SIM, ExecutionMode.BACKTEST)

    def get_allowed_asset_ids(self) -> list[str]:
        return [a.strip().upper() for a in self.universe.allowed_assets if a.strip()]


def load_settings(config_path: str | Path | None = None) -> Settings:
    if config_path is None:
        config_path = Path("config/settings.local.yaml")

    path = Path(config_path)
    if not path.exists():
        example_path = Path("config/settings.example.yaml")
        if example_path.exists():
            raise FileNotFoundError(
                f"설정 파일 없음: {path}\n"
                f"  → {example_path}를 복사하여 {path}로 생성하세요.\n"
                f"  → 복사 명령: copy {example_path} {path} (Windows) 또는 cp {example_path} {path} (Linux/Mac)\n"
                f"  → 이후 .env 파일에 API 키 등 비밀값을 설정하세요."
            )
        raise FileNotFoundError(f"설정 파일 없음: {path}. 예제 파일도 없습니다.")

    import yaml

    with open(path, encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f) or {}

    return Settings(**yaml_data)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
