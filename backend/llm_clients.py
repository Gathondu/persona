"""Factory helpers for LLM API clients (Cerebras primary, OpenRouter fallback)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from cerebras.cloud.sdk import AsyncCerebras, Cerebras
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, Field

from prompt_templates import GUARDRAILS_PROMPT

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
        base_url=os.environ["OPENROUTER_BASE_URL"],
        default_headers={
            "HTTP-Referer": os.getenv("APP_URL", "http://localhost:7860"),
            "X-Title": "DNG",
        },
    )


def get_cerebras_model() -> str:
    return os.getenv("CEREBRAS_MODEL", _DEFAULT_CEREBRAS_MODEL).strip()


def get_openrouter_model() -> str:
    return os.getenv("OPENROUTER_MODEL", _DEFAULT_OPENROUTER_MODEL).strip()


def check_prompt_against_guardrails(msg: str) -> tuple[bool, str]:

    @dataclass(frozen=True)
    class GuardrailsResponse(BaseModel):
        is_valid: bool = Field(..., description="Whether the message is valid")
        new_response: str | None = Field(
            ..., description="Redirect the question towards skills and expertise topics."
        )

    cerebras_key = os.getenv("CEREBRAS_API_KEY", "").strip()
    client = (
        Cerebras(
            default_headers={
                "HTTP-Referer": os.getenv("APP_URL", "http://localhost:7860"),
                "X-Title": "DNG",
            }
        )
        if cerebras_key
        else OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.environ["OPENROUTER_BASE_URL"],
            default_headers={
                "HTTP-Referer": os.getenv("APP_URL", "http://localhost:7860"),
                "X-Title": "DNG",
            },
        )
    )
    response = client.chat.completions.parse(
        model=get_openrouter_model() if isinstance(client, OpenAI) else get_cerebras_model(),
        messages=[
            {"role": "system", "content": GUARDRAILS_PROMPT},
            {"role": "user", "content": msg},
        ],
        temperature=0.4,
        response_format=GuardrailsResponse,
    )
    guard_response = GuardrailsResponse.model_validate_json(response.choices[0].message.content)
    return guard_response.is_valid, guard_response.new_response
