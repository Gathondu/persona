from __future__ import annotations

import os
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from prompt_templates import SYSTEM_PROMPT

load_dotenv(override=True)

_client = AsyncOpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": os.getenv("APP_URL", "http://localhost:7860"),
        "X-Title": "DNG",
    },
)

MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
PLACEHOLDER_FALLBACK = "Share more context, goals, or questions..."


async def stream_response(
    messages: list[ChatCompletionMessageParam],
) -> AsyncIterator[str]:
    """Stream token chunks from the LLM via OpenRouter."""
    full_messages: list[ChatCompletionMessageParam] = []
    if SYSTEM_PROMPT:
        full_messages.append({"role": "system", "content": SYSTEM_PROMPT})
    full_messages.extend(messages)

    stream = await _client.chat.completions.create(
        model=MODEL,
        messages=full_messages,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content is not None:
            yield delta.content


async def generate_placeholder(
    messages: list[ChatCompletionMessageParam],
) -> str:
    """Generate a short, context-aware input placeholder."""
    placeholder_messages: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": (
                "Generate one concise text-box placeholder for the user's next message. "
                "Use the conversation context, stay professional, avoid greetings, "
                "and return plain text only with no quotes. Keep it under 80 characters."
            ),
        },
    ]
    placeholder_messages.extend(messages)
    placeholder_messages.append(
        {
            "role": "user",
            "content": "Create the best placeholder for the user's next message.",
        }
    )

    response = await _client.chat.completions.create(
        model=MODEL,
        messages=placeholder_messages,
        stream=False,
    )
    content = response.choices[0].message.content or ""
    text = content.strip()
    if not text:
        return PLACEHOLDER_FALLBACK
    return text.replace("\n", " ")[:80]
