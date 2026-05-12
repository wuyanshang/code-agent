from code_agent.config import AppConfig, load_config


def test_load_config_defaults_to_mock() -> None:
    config = AppConfig()
    assert config.model.provider == "mock"


def test_env_provider_override(monkeypatch) -> None:
    monkeypatch.setenv("CODE_AGENT_PROVIDER", "mock")
    config = load_config("config/default.yaml")
    assert config.model.provider == "mock"
