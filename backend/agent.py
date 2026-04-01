from __future__ import annotations

import math
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

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

MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5.4-nano")
PLACEHOLDER_FALLBACK = "Share more context, goals, or questions..."
EMBEDDING_SIZE = 128


@dataclass(frozen=True)
class ProfileMatch:
    session_id: str
    text: str
    score: float


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


def embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_SIZE
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if not tokens:
        return vector
    for token in tokens:
        idx = hash(token) % EMBEDDING_SIZE
        vector[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


def extract_profile_facts_from_text(text: str) -> list[str]:
    facts: list[str] = []
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return facts

    patterns = [
        r"\bmy name is ([A-Za-z][A-Za-z .'-]{1,50})",
        r"\bi am ([A-Za-z][A-Za-z .'-]{1,50})\b",
        r"\bi'm ([A-Za-z][A-Za-z .'-]{1,50})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .")
            facts.append(f"Name: {value}")
            break

    company_patterns = [
        r"\bi work at ([A-Za-z0-9][A-Za-z0-9 &.,'-]{1,80})",
        r"\bi am at ([A-Za-z0-9][A-Za-z0-9 &.,'-]{1,80})",
        r"\bfrom ([A-Za-z0-9][A-Za-z0-9 &.,'-]{1,80})",
    ]
    for pattern in company_patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .")
            facts.append(f"Company: {value}")
            break

    role_patterns = [
        r"\bi am a ([A-Za-z][A-Za-z0-9 /-]{2,80})",
        r"\bi'm a ([A-Za-z][A-Za-z0-9 /-]{2,80})",
        r"\bmy role is ([A-Za-z][A-Za-z0-9 /-]{2,80})",
    ]
    for pattern in role_patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .")
            facts.append(f"Role: {value}")
            break

    if "@" in cleaned and "." in cleaned:
        email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cleaned)
        if email_match:
            facts.append(f"Email: {email_match.group(0)}")

    return list(dict.fromkeys(facts))


def select_relevant_profile_facts(
    query_text: str, memories: list[dict[str, object]], top_k: int = 3
) -> list[ProfileMatch]:
    query_embedding = embed_text(query_text)
    matches: list[ProfileMatch] = []
    for memory in memories:
        session_id_obj = memory.get("session_id")
        text_obj = memory.get("text")
        embedding_obj = memory.get("embedding")
        if not isinstance(session_id_obj, str):
            continue
        if not isinstance(text_obj, str):
            continue
        if not isinstance(embedding_obj, list):
            continue
        embedding: list[float] = []
        for value in embedding_obj:
            if isinstance(value, (float, int)):
                embedding.append(float(value))
        if not embedding:
            continue
        score = cosine_similarity(query_embedding, embedding)
        if score > 0.15:
            matches.append(ProfileMatch(session_id=session_id_obj, text=text_obj, score=score))

    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[:top_k]
