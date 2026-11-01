"""Settings loading, precedence and env interpolation."""

from __future__ import annotations

import yaml

from zyko.config.settings import Settings


def test_defaults_when_no_config():
    settings = Settings.load()
    assert settings.get("router.strategy") == "balanced"
    assert settings.get("gateway.port") == 8787


def test_yaml_file_overrides(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"router": {"strategy": "cost"}}), encoding="utf-8")
    settings = Settings.load(path)
    assert settings.get("router.strategy") == "cost"
    assert settings.source == path


def test_env_overrides_yaml(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"router": {"strategy": "cost"}}), encoding="utf-8")
    monkeypatch.setenv("ZYKO_ROUTER_STRATEGY", "latency")
    settings = Settings.load(path)
    assert settings.get("router.strategy") == "latency"


def test_env_interpolation_in_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "abc123")
    path = tmp_path / "config.yaml"
    path.write_text("gateway:\n  api_key: ${SECRET_KEY}\n", encoding="utf-8")
    settings = Settings.load(path)
    assert settings.get("gateway.api_key") == "abc123"


def test_provider_sections(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "providers": {"openai": {"api_key": "sk-x"}, "ollama": {"base_url": "http://localhost:11434"}}
    }), encoding="utf-8")
    settings = Settings.load(path)
    assert settings.provider_setting("openai")["api_key"] == "sk-x"
    assert "openai" in settings.provider_settings
