from __future__ import annotations

from dataclasses import dataclass
import os


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value is not None else default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


@dataclass(frozen=True)
class Settings:
    upstream_base_url: str
    upstream_path: str
    upstream_api_key: str | None
    request_timeout: float
    summary_timeout: float
    max_reasoning_chars: int
    allow_models: set[str] | None
    summary_model_default: str | None
    enable_parse_reasoning: bool


def get_settings() -> Settings:
    allow_models_raw = _get_env("ALLOW_MODELS")
    allow_models = (
        {m.strip() for m in allow_models_raw.split(",") if m.strip()}
        if allow_models_raw
        else None
    )

    summary_model_default = _get_env("SUMMARY_MODEL_DEFAULT")

    return Settings(
        upstream_base_url=_get_env("UPSTREAM_BASE_URL", "http://localhost:8001"),
        upstream_path=_get_env("UPSTREAM_PATH", "/chat/completions"),
        upstream_api_key=_get_env("UPSTREAM_API_KEY"),
        request_timeout=_get_float("REQUEST_TIMEOUT", 60.0),
        summary_timeout=_get_float("SUMMARY_TIMEOUT", 10.0),
        max_reasoning_chars=_get_int("MAX_REASONING_CHARS", 8000),
        allow_models=allow_models,
        summary_model_default=summary_model_default,
        enable_parse_reasoning=_get_env("ENABLE_PARSE_REASONING", "true").lower()
        in {"1", "true", "yes"},
    )
