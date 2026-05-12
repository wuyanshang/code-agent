from __future__ import annotations

from code_agent.config import (
    AppConfig,
    ModelConfig,
    ModelPresetConfig,
    apply_model_preset,
    load_config,
)


def test_apply_model_preset_merges() -> None:
    m = ModelConfig(
        model_name="base-model",
        base_url="https://api.example/v1",
        api_key="root-key",
        timeout_seconds=60,
        presets={
            "fast": ModelPresetConfig(model_name="fast-m", timeout_seconds=30),
            "other": ModelPresetConfig(provider="mock", model_name="m"),
        },
    )
    apply_model_preset(m, "fast")
    assert m.model_name == "fast-m"
    assert m.base_url == "https://api.example/v1"
    assert m.api_key == "root-key"
    assert m.timeout_seconds == 30
    assert "fast" in m.presets

    apply_model_preset(m, "other")
    assert m.provider == "mock"
    assert m.model_name == "m"


def test_apply_model_preset_overrides_base_url() -> None:
    m = ModelConfig(
        model_name="base",
        base_url="https://default/v1",
        api_key="k",
        presets={
            "gw-a": ModelPresetConfig(
                model_name="m-a",
                base_url="https://gateway-a/v1",
                api_key="key-a",
            ),
            "gw-b": ModelPresetConfig(
                model_name="m-b",
                base_url="https://gateway-b/v1",
            ),
        },
    )
    apply_model_preset(m, "gw-a")
    assert m.base_url == "https://gateway-a/v1"
    assert m.api_key == "key-a"
    apply_model_preset(m, "gw-b")
    assert m.base_url == "https://gateway-b/v1"
    assert m.api_key == "key-a"


def test_app_config_presets_from_yaml(tmp_path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text(
        """
model:
  provider: mock
  model_name: ""
  presets:
    p1:
      description: 测试
      model_name: m1
""",
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert "p1" in cfg.model.presets
    assert cfg.model.presets["p1"].model_name == "m1"
    assert cfg.model.presets["p1"].description == "测试"


def test_model_config_empty_presets() -> None:
    cfg = AppConfig()
    assert cfg.model.presets == {}
