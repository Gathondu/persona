"""Factory helpers for LLM API clients (Cerebras primary, OpenRouter fallback)."""

from __future__ import annotations

import os
from typing import cast

from cerebras.cloud.sdk import AsyncCerebras, Cerebras
from cerebras.cloud.sdk.types.chat import completion_create_params
from cerebras.cloud.sdk.types.chat.chat_completion import ChatCompletionResponse
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field

from prompt_templates import GUARDRAILS_PROMPT

# Default models match Cerebras docs / common OpenRouter IDs; override via env.
_DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"
_DEFAULT_OPENROUTER_MODEL = "openai/gpt-5.4-nano"

# Max prior turns (user + assistant) sent to the guardrail for context.
GUARDRAIL_HISTORY_MAX_MESSAGES = 24


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


def _build_guardrail_messages(
    msg: str,
    conversation_history: list[dict[str, str]] | None,
) -> list[ChatCompletionMessageParam]:
    """System prompt + prior turns (newest window) + latest user message to classify."""
    trimmed = (conversation_history or [])[-GUARDRAIL_HISTORY_MAX_MESSAGES:]
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": GUARDRAILS_PROMPT},
    ]
    for turn in trimmed:
        role = turn.get("role", "")
        content = turn.get("content", "").strip()
        if not content:
            continue
        if role == "user":
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content})
    messages.append(
        {
            "role": "user",
            "content": (
                "Classify **only** the latest user message below for this chat. "
                "Use prior turns as context for ambiguous or short follow-ups.\n\n"
                f"{msg.strip()}"
            ),
        }
    )
    return messages


def check_prompt_against_guardrails(
    msg: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> tuple[bool, str]:

    class GuardrailsResponse(BaseModel):
        is_valid: bool = Field(..., description="Whether the message is valid")
        new_response: str | None = Field(
            ..., description="Redirect the question towards skills and expertise topics."
        )

    chat_messages = _build_guardrail_messages(msg, conversation_history)

    cerebras_key = os.getenv("CEREBRAS_API_KEY", "").strip()
    common_headers = {
        "HTTP-Referer": os.getenv("APP_URL", "http://localhost:7860"),
        "X-Title": "DNG",
    }
    if cerebras_key:
        cerebras_client = Cerebras(default_headers=common_headers)
        cerebras_messages = cast(
            list[completion_create_params.Message],
            chat_messages,
        )
        response_format: completion_create_params.ResponseFormat = {
            "type": "json_schema",
            "json_schema": {
                "name": "GuardrailsResponse",
                "schema": GuardrailsResponse.model_json_schema(),
                "strict": True,
            },
        }
        cerebras_out = cerebras_client.chat.completions.create(
            model=get_cerebras_model(),
            messages=cerebras_messages,
            temperature=0.4,
            response_format=response_format,
            stream=False,
        )
        cerebras_response = cast(ChatCompletionResponse, cerebras_out)
        raw = cerebras_response.choices[0].message.content
    else:
        openrouter_client = OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.environ["OPENROUTER_BASE_URL"],
            default_headers=common_headers,
        )
        openrouter_response = openrouter_client.chat.completions.parse(
            model=get_openrouter_model(),
            messages=chat_messages,
            temperature=0.4,
            response_format=GuardrailsResponse,
        )
        raw = openrouter_response.choices[0].message.content
    if raw is None:
        msg_err = "Guardrails completion returned no message content"
        raise RuntimeError(msg_err)
    guard_response = GuardrailsResponse.model_validate_json(raw)
    redirect = guard_response.new_response or ""
    return guard_response.is_valid, redirect
