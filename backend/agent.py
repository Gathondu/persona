from __future__ import annotations

import logging
import math
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from hashlib import sha256

from dotenv import load_dotenv
from openai.types.chat import ChatCompletionMessageParam

from llm_clients import (
    create_cerebras_client,
    create_openrouter_client,
    get_cerebras_model,
    get_openrouter_model,
)
from prompt_templates import SYSTEM_PROMPT

load_dotenv(override=True)

logger = logging.getLogger(__name__)

_cerebras_client = create_cerebras_client()
_openrouter_client = create_openrouter_client()

PLACEHOLDER_FALLBACK = "Share more context, goals, or questions..."
EMBEDDING_SIZE = 128


@dataclass(frozen=True)
class ProfileMatch:
    session_id: str
    text: str
    score: float


def _with_system_prompt(
    messages: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    full_messages: list[ChatCompletionMessageParam] = []
    if SYSTEM_PROMPT:
        full_messages.append({"role": "system", "content": SYSTEM_PROMPT})
    full_messages.extend(messages)
    return full_messages


async def _stream_openrouter(
    full_messages: list[ChatCompletionMessageParam],
) -> AsyncIterator[str]:
    stream = await _openrouter_client.chat.completions.create(
        model=get_openrouter_model(),
        messages=full_messages,
        stream=True,
    )
    async for chunk in stream:
        choice = chunk.choices[0]
        delta = choice.delta
        if delta.content is not None:
            yield delta.content


async def _stream_cerebras(
    full_messages: list[ChatCompletionMessageParam],
) -> AsyncIterator[str]:
    if _cerebras_client is None:
        raise RuntimeError("Cerebras client not configured")
    stream = await _cerebras_client.chat.completions.create(
        model=get_cerebras_model(),
        messages=full_messages,
        stream=True,
    )
    async for chunk in stream:
        choice = chunk.choices[0]
        delta = choice.delta
        if delta.content is not None:
            yield delta.content


async def stream_response(
    messages: list[ChatCompletionMessageParam],
) -> AsyncIterator[str]:
    """Stream token chunks: Cerebras first, OpenRouter if Cerebras fails before any token."""
    full_messages = _with_system_prompt(messages)

    if _cerebras_client is None:
        async for token in _stream_openrouter(full_messages):
            yield token
        return

    emitted = False
    try:
        async for token in _stream_cerebras(full_messages):
            emitted = True
            yield token
    except Exception:
        if emitted:
            raise
        logger.warning(
            "Cerebras streaming failed before first token; falling back to OpenRouter",
            exc_info=True,
        )
        async for token in _stream_openrouter(full_messages):
            yield token


def _normalize_placeholder_text(content: str) -> str:
    text = content.strip()
    if not text:
        return PLACEHOLDER_FALLBACK
    return text.replace("\n", " ")[:80]


async def generate_placeholder(
    messages: list[ChatCompletionMessageParam],
) -> str:
    """Generate a short, context-aware input placeholder (Cerebras, then OpenRouter)."""
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

    if _cerebras_client is not None:
        try:
            response = await _cerebras_client.chat.completions.create(
                model=get_cerebras_model(),
                messages=placeholder_messages,
                stream=False,
            )
            content = response.choices[0].message.content or ""
            return _normalize_placeholder_text(content)
        except Exception:
            logger.warning(
                "Cerebras placeholder generation failed; falling back to OpenRouter",
                exc_info=True,
            )

    response = await _openrouter_client.chat.completions.create(
        model=get_openrouter_model(),
        messages=placeholder_messages,
        stream=False,
    )
    content = response.choices[0].message.content or ""
    return _normalize_placeholder_text(content)


def embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_SIZE
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if not tokens:
        return vector
    for token in tokens:
        digest = sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], byteorder="big") % EMBEDDING_SIZE
        vector[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


def _clean_name_value(raw_value: str) -> str:
    value = raw_value.strip(" .")
    value = re.split(r"[,.!?]", value, maxsplit=1)[0]
    value = re.split(
        r"\s+\b(?:and|but)\b\s+",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(
        r"\s+\b(?:i am|i'm|my role is|i work at|looking for)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.sub(r"\b(?:and|an)\s*$", "", value, flags=re.IGNORECASE)
    return " ".join(value.split()).strip(" .")


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
            value = _clean_name_value(match.group(1))
            if value:
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
    query_lower = query_text.lower()
    matches: list[ProfileMatch] = []

    requested_labels: set[str] = set()
    if any(keyword in query_lower for keyword in ("name", "call me", "who am i")):
        requested_labels.add("name")
    if any(keyword in query_lower for keyword in ("company", "work at", "where do i work")):
        requested_labels.add("company")
    if any(keyword in query_lower for keyword in ("role", "job title", "position")):
        requested_labels.add("role")
    if "email" in query_lower:
        requested_labels.add("email")

    for memory in memories:
        session_id_obj = memory.get("session_id")
        text_obj = memory.get("text")
        if not isinstance(session_id_obj, str):
            continue
        if not isinstance(text_obj, str):
            continue

        score = cosine_similarity(query_embedding, embed_text(text_obj))
        label = ""
        if ":" in text_obj:
            label = text_obj.split(":", 1)[0].strip().lower()
        canonical_text = text_obj
        if label == "name":
            raw_name = text_obj.split(":", 1)[1].strip() if ":" in text_obj else text_obj
            cleaned_name = _clean_name_value(raw_name)
            if cleaned_name:
                canonical_text = f"Name: {cleaned_name}"
                score = cosine_similarity(query_embedding, embed_text(canonical_text))
        if label in requested_labels:
            score = max(score, 1.0)

        if score > 0.12:
            matches.append(ProfileMatch(session_id=session_id_obj, text=canonical_text, score=score))

    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[:top_k]
