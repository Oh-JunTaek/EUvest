"""settings.py 단위 테스트."""

import os
import tempfile

import pytest
import yaml

from invest_agent.domain.enums import BrokerEnvironment, ExecutionMode, LLMProvider
from invest_agent.settings import (
    AIConfig,
    AssetTypeConfig,
    BrokerConfig,
    CapitalConfig,
    ExecutionConfig,
    MarketConfig,
    Settings,
    get_settings,
    load_settings,
    reset_settings,
)


class TestExecutionConfig:
    """실행 설정 검증."""

    def test_default_offline_sim(self):
        cfg = ExecutionConfig()
        assert cfg.mode == ExecutionMode.OFFLINE_SIM
        assert cfg.allow_live_orders is False
        assert cfg.kill_switch is True
        assert cfg.order_type == "LIMIT_ONLY"

    def test_live_mode_requires_allow_live(self):
        with pytest.raises(ValueError, match="allow_live_orders=true"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.LIVE, allow_live_orders=False),
                broker=BrokerConfig(environment=BrokerEnvironment.LIVE),
            )

    def test_live_mode_requires_kill_switch_false(self):
        with pytest.raises(ValueError, match="kill_switch=false"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.LIVE, allow_live_orders=True, kill_switch=True),
                broker=BrokerConfig(environment=BrokerEnvironment.LIVE),
            )

    def test_kis_paper_mode_blocks_live_orders(self):
        with pytest.raises(ValueError, match="allow_live_orders=false"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.KIS_PAPER, allow_live_orders=True),
                broker=BrokerConfig(environment=BrokerEnvironment.PAPER),
            )

    def test_offline_sim_blocks_live_orders(self):
        with pytest.raises(ValueError, match="allow_live_orders=false"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.OFFLINE_SIM, allow_live_orders=True),
                broker=BrokerConfig(environment=BrokerEnvironment.MOCK),
            )

class TestMarketConfig:
    def test_default_markets_enabled(self):
        cfg = MarketConfig()
        assert cfg.KRX is True
        assert cfg.US is True

class TestAssetTypeConfig:
    def test_default_leveraged_blocked(self):
        cfg = AssetTypeConfig()
        assert cfg.LEVERAGED_ETF is False
        assert cfg.INVERSE_ETF is False
        assert cfg.DERIVATIVE is False

    def test_default_stock_etf_enabled(self):
        cfg = AssetTypeConfig()
        assert cfg.STOCK is True
        assert cfg.ETF is True

class TestCapitalConfig:
    def test_default_cash_only(self):
        cfg = CapitalConfig()
        assert cfg.cash_only is True
        assert cfg.allow_margin is False
        assert cfg.allow_short is False

class TestAIConfig:
    def test_default_fake_provider(self):
        cfg = AIConfig()
        assert cfg.provider == LLMProvider.FAKE
        assert cfg.fallback_enabled is False

    def test_ollama_provider(self):
        cfg = AIConfig(provider=LLMProvider.OLLAMA, model="qwen3.5:9b")
        assert cfg.provider == LLMProvider.OLLAMA

class TestBrokerConfig:
    def test_default_mock_environment(self):
        cfg = BrokerConfig()
        assert cfg.environment == BrokerEnvironment.MOCK

    def test_paper_environment(self):
        cfg = BrokerConfig(environment=BrokerEnvironment.PAPER)
        assert cfg.environment == BrokerEnvironment.PAPER

class TestSettingsValidation:
    def test_default_offline_sim_valid(self):
        s = Settings()
        assert s.execution.mode == ExecutionMode.OFFLINE_SIM
        assert s.is_offline_mode()

    def test_live_mode_requires_live_broker(self):
        with pytest.raises(ValueError, match="broker.environment가 LIVE여야 함"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.LIVE, allow_live_orders=True, kill_switch=False),
                broker=BrokerConfig(environment=BrokerEnvironment.PAPER),
            )

    def test_live_mode_requires_allow_live_true(self):
        with pytest.raises(ValueError, match="allow_live_orders=true"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.LIVE, allow_live_orders=False, kill_switch=False),
                broker=BrokerConfig(environment=BrokerEnvironment.LIVE),
            )

    def test_live_mode_requires_kill_switch_false(self):
        with pytest.raises(ValueError, match="kill_switch=false"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.LIVE, allow_live_orders=True, kill_switch=True),
                broker=BrokerConfig(environment=BrokerEnvironment.LIVE),
            )

    def test_kis_paper_requires_paper_broker(self):
        with pytest.raises(ValueError, match="broker.environment가 PAPER여야 함"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.KIS_PAPER),
                broker=BrokerConfig(environment=BrokerEnvironment.MOCK),
            )

    def test_offline_sim_blocks_live_orders(self):
        with pytest.raises(ValueError, match="allow_live_orders=false"):
            Settings(
                execution=ExecutionConfig(mode=ExecutionMode.OFFLINE_SIM, allow_live_orders=True),
                broker=BrokerConfig(environment=BrokerEnvironment.MOCK),
            )

    def test_offline_sim_may_explicitly_release_kill_switch(self):
        assert Settings(execution={"kill_switch": False}).execution.kill_switch is False

    def test_offline_rejects_paper_broker(self):
        with pytest.raises(ValueError, match="MOCK이어야"):
            Settings(broker={"environment": "PAPER"})

    @pytest.mark.parametrize("field", ["allow_margin", "allow_credit", "allow_short", "allow_loans"])
    def test_forbidden_capital_modes(self, field):
        with pytest.raises(ValueError, match="금지"):
            CapitalConfig(**{field: True})

    def test_cash_only_cannot_be_disabled(self):
        with pytest.raises(ValueError, match="cash_only"):
            CapitalConfig(cash_only=False)

    def test_universe_cannot_be_changed_by_ai(self):
        with pytest.raises(ValueError, match="자동 변경 금지"):
            Settings(universe={"ai_may_auto_add_to_allowlist": True})

    def test_derivatives_rejected(self):
        with pytest.raises(ValueError, match="파생상품"):
            Settings(asset_types={"DERIVATIVE": True})

    @pytest.mark.parametrize("scheduler", [{"overlap_policy": "QUEUE"}, {"catch_up_missed_runs": True}])
    def test_schedule_cannot_queue_or_catch_up(self, scheduler):
        with pytest.raises(ValueError, match="재시도 금지"):
            Settings(scheduler=scheduler)

    def test_kis_paper_allows_scheduler(self):
        s = Settings(
            execution=ExecutionConfig(mode=ExecutionMode.KIS_PAPER),
            broker=BrokerConfig(environment=BrokerEnvironment.PAPER),
            scheduler={"enabled": True},
        )
        assert s.scheduler.enabled is True

class TestLoadSettings:
    def test_load_from_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                {
                    "schema_version": "1.0",
                    "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                    "markets": {"KRX": True, "US": False},
                },
                f,
            )
            temp_path = f.name

        try:
            s = load_settings(temp_path)
            assert s.execution.mode == ExecutionMode.OFFLINE_SIM
            assert s.execution.kill_switch is True
            assert s.markets.KRX is True
            assert s.markets.US is False
        finally:
            os.unlink(temp_path)

    def test_missing_config_raises(self):
        with pytest.raises(FileNotFoundError):
            load_settings("nonexistent.yaml")

class TestSettingsSingleton:
    def test_get_settings_returns_instance(self, monkeypatch):
        monkeypatch.setattr("invest_agent.settings.load_settings", lambda: Settings(_env_file=None))
        reset_settings()
        s = get_settings()
        assert isinstance(s, Settings)
        assert get_settings() is s

    def test_reset_settings(self, monkeypatch):
        monkeypatch.setattr("invest_agent.settings.load_settings", lambda: Settings(_env_file=None))
        reset_settings()
        assert get_settings() is not None
        reset_settings()

class TestModeChecks:
    def test_is_live_mode(self):
        s = Settings(
            execution=ExecutionConfig(mode=ExecutionMode.LIVE, allow_live_orders=True, kill_switch=False),
            broker=BrokerConfig(environment=BrokerEnvironment.LIVE),
        )
        assert s.is_live_mode() is True

    def test_is_paper_mode(self):
        s = Settings(
            execution=ExecutionConfig(mode=ExecutionMode.KIS_PAPER),
            broker=BrokerConfig(environment=BrokerEnvironment.PAPER),
        )
        assert s.is_paper_mode() is True

    def test_is_offline_mode(self):
        s = Settings()
        assert s.is_offline_mode() is True

class TestAllowedAssets:
    def test_get_allowed_asset_ids(self):
        s = Settings(universe={"allowed_assets": ["KRX:005930", "US:AAPL"]})
        assets = s.get_allowed_asset_ids()
        assert "KRX:005930" in assets
        assert "US:AAPL" in assets

    def test_empty_allowed_assets(self):
        s = Settings()
        assert s.get_allowed_asset_ids() == []

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
