import base64

# Part 2: TestProviderSwitching class
content = """

class TestProviderSwitching:
    def test_env_overrides_yaml_when_yaml_is_default(self):
        from invest_agent.settings import load_settings
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "fake", "model": "fixture-default", "endpoint": None},
            }, f)
            temp_path = f.name
        try:
            os.environ["INVEST_LLM_BASE_URL"] = "https://test.api/v1"
            os.environ["INVEST_LLM_MODEL"] = "test-model"
            os.environ["INVEST_LLM_API_KEY"] = "test-key"
            s = load_settings(temp_path)
            assert s.ai.endpoint == "https://test.api/v1"
            assert s.ai.model == "test-model"
            assert s.ai.api_key == "test-key"
        finally:
            os.unlink(temp_path)
            for k in ["INVEST_LLM_BASE_URL", "INVEST_LLM_MODEL", "INVEST_LLM_API_KEY"]:
                os.environ.pop(k, None)

    def test_ollama_provider_from_env(self):
        from invest_agent.settings import load_settings
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "ollama", "model": "fixture-default"},
            }, f)
            temp_path = f.name
        try:
            os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"
            os.environ["OLLAMA_MODEL"] = "qwen3.5:9b"
            s = load_settings(temp_path)
            assert s.ai.provider == "ollama"
            assert s.ai.endpoint == "http://localhost:11434/v1"
            assert s.ai.model == "qwen3.5:9b"
        finally:
            os.unlink(temp_path)
            for k in ["OLLAMA_BASE_URL", "OLLAMA_MODEL"]:
                os.environ.pop(k, None)

    def test_yaml_explicit_value_not_overridden(self):
        from invest_agent.settings import load_settings
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "openai_compatible", "model": "explicit-model", "endpoint": "https://explicit.api/v1"},
            }, f)
            temp_path = f.name
        try:
            os.environ["INVEST_LLM_BASE_URL"] = "https://env.api/v1"
            os.environ["INVEST_LLM_MODEL"] = "env-model"
            s = load_settings(temp_path)
            assert s.ai.model == "explicit-model"
            assert s.ai.endpoint == "https://explicit.api/v1"
        finally:
            os.unlink(temp_path)
            for k in ["INVEST_LLM_BASE_URL", "INVEST_LLM_MODEL"]:
                os.environ.pop(k, None)

    def test_secret_keys_not_in_logs(self):
        from invest_agent.settings import load_settings
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml
            yaml.dump({
                "schema_version": "1.0",
                "execution": {"mode": "OFFLINE_SIM", "kill_switch": True},
                "ai": {"provider": "openai_compatible", "model": "test", "endpoint": "https://api.test/v1", "api_key": "secret-key-123"},
            }, f)
            temp_path = f.name
        try:
            s = load_settings(temp_path)
            assert s.ai.api_key == "secret-key-123"
            assert "secret-key-123" not in repr(s)
        finally:
            os.unlink(temp_path)


"""
# Encode and save part 2
import base64
encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
with open('append_part2.b64', 'w') as f:
    f.write(encoded)
print('Part 2 encoded')