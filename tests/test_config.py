import os

from app.config import get_settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("UPSTREAM_PATH", raising=False)
    monkeypatch.delenv("UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("REQUEST_TIMEOUT", raising=False)
    monkeypatch.delenv("SUMMARY_TIMEOUT", raising=False)
    monkeypatch.delenv("MAX_REASONING_CHARS", raising=False)
    monkeypatch.delenv("ALLOW_MODELS", raising=False)
    monkeypatch.delenv("SUMMARY_MODEL_DEFAULT", raising=False)
    monkeypatch.delenv("ENABLE_PARSE_REASONING", raising=False)

    settings = get_settings()

    assert settings.upstream_base_url == "http://localhost:8001"
    assert settings.upstream_path == "/chat/completions"
    assert settings.upstream_api_key is None
    assert settings.request_timeout == 60.0
    assert settings.summary_timeout == 10.0
    assert settings.max_reasoning_chars == 8000
    assert settings.allow_models is None
    assert settings.summary_model_default is None
    assert settings.enable_parse_reasoning is True


def test_settings_overrides(monkeypatch):
    monkeypatch.setenv("UPSTREAM_BASE_URL", "http://example.com")
    monkeypatch.setenv("UPSTREAM_PATH", "/v1/chat")
    monkeypatch.setenv("UPSTREAM_API_KEY", "secret")
    monkeypatch.setenv("REQUEST_TIMEOUT", "12")
    monkeypatch.setenv("SUMMARY_TIMEOUT", "3")
    monkeypatch.setenv("MAX_REASONING_CHARS", "123")
    monkeypatch.setenv("ALLOW_MODELS", "a,b")
    monkeypatch.setenv("SUMMARY_MODEL_DEFAULT", "summary")
    monkeypatch.setenv("ENABLE_PARSE_REASONING", "false")

    settings = get_settings()

    assert settings.upstream_base_url == "http://example.com"
    assert settings.upstream_path == "/v1/chat"
    assert settings.upstream_api_key == "secret"
    assert settings.request_timeout == 12.0
    assert settings.summary_timeout == 3.0
    assert settings.max_reasoning_chars == 123
    assert settings.allow_models == {"a", "b"}
    assert settings.summary_model_default == "summary"
    assert settings.enable_parse_reasoning is False
