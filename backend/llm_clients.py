"""Factory helpers for LLM API clients (Cerebras primary, OpenRouter fallback)."""

from __future__ import annotations

import os

from cerebras.cloud.sdk import AsyncCerebras
from openai import AsyncOpenAI

# Default models match Cerebras docs / common OpenRouter IDs; override via env.
_DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"
_DEFAULT_OPENROUTER_MODEL = "openai/gpt-5.4-nano"


def create_cerebras_client() -> AsyncCerebras | None:
    """Return AsyncCerebras when ``CEREBRAS_API_KEY`` is set; otherwise ``None`` (OpenRouter-only)."""
    key = os.getenv("CEREBRAS_API_KEY", "").strip()
    if not key:
        return None
    return AsyncCerebras(
        api_key=key,
        default_headers={
            "HTTP-Referer": os.getenv("APP_URL", "http://localhost:7860"),
            "X-Title": "DNG",
        },
    )


def create_openrouter_client() -> AsyncOpenAI:
    """OpenAI-compatible client pointed at OpenRouter (required for fallback)."""
    return AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": os.getenv("APP_URL", "http://localhost:7860"),
            "X-Title": "DNG",
        },
    )


def get_cerebras_model() -> str:
    return os.getenv("CEREBRAS_MODEL", _DEFAULT_CEREBRAS_MODEL).strip() or _DEFAULT_CEREBRAS_MODEL


def get_openrouter_model() -> str:
    return (
        os.getenv("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL).strip()
        or _DEFAULT_OPENROUTER_MODEL
    )
