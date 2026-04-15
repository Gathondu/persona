from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field

from agent import (
    PLACEHOLDER_FALLBACK,
    embed_text,
    extract_profile_facts_from_text,
    generate_placeholder,
    select_relevant_profile_facts,
    stream_response,
)
from llm_clients import check_prompt_against_guardrails
from memory import (
    delete_session,
    get_history,
    get_profile_memories,
    init_db,
    save_message,
    upsert_profile_memory,
)

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("Database initialised.")
    yield


app = FastAPI(title="DNG", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    known_session_ids: list[str] = Field(default_factory=list)


class PlaceholderRequest(BaseModel):
    session_id: str


class PlaceholderResponse(BaseModel):
    placeholder: str


class DeleteSessionResponse(BaseModel):
    success: bool


def _to_chat_message(role: str, content: str) -> ChatCompletionMessageParam:
    if role == "user":
        return {"role": "user", "content": content}
    if role == "assistant":
        return {"role": "assistant", "content": content}
    raise ValueError(f"Unsupported chat role in history: {role}")


def _dedupe_sessions(session_id: str, known_session_ids: list[str]) -> list[str]:
    seen: set[str] = {session_id}
    deduped: list[str] = [session_id]
    for known in known_session_ids:
        trimmed = known.strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        deduped.append(trimmed)
    return deduped


async def _sse_stream(
    session_id: str, user_message: str, known_session_ids: list[str]
) -> AsyncIterator[str]:
    raw_history = get_history(session_id)
    history: list[ChatCompletionMessageParam] = []
    for item in raw_history:
        try:
            history.append(_to_chat_message(item["role"], item["content"]))
        except ValueError:
            logger.warning("Skipping unsupported history role: %s", item["role"])

    session_scope = _dedupe_sessions(session_id, known_session_ids)
    memories = get_profile_memories(session_scope)
    profile_matches = select_relevant_profile_facts(user_message, memories, top_k=3)
    if profile_matches:
        facts = "\n".join(f"- {match.text}" for match in profile_matches)
        history.append(
            {
                "role": "system",
                "content": (
                    "Use these known profile facts when relevant. "
                    "Do not mention they came from previous sessions.\n"
                    f"{facts}"
                ),
            }
        )

    if raw_history:
        history.append(
            {
                "role": "system",
                "content": (
                    "The conversation has already started. Continue naturally without "
                    "re-greeting, re-introducing yourself, or repeating welcome language."
                ),
            }
        )

    history.append(_to_chat_message("user", user_message))

    save_message(session_id, "user", user_message)
    facts_from_message = extract_profile_facts_from_text(user_message)
    for fact in facts_from_message:
        upsert_profile_memory(
            session_id=session_id,
            source_session_id=session_id,
            text=fact,
            embedding=embed_text(fact),
        )
    for match in profile_matches:
        if match.session_id == session_id:
            continue
        upsert_profile_memory(
            session_id=session_id,
            source_session_id=match.session_id,
            text=match.text,
            embedding=embed_text(match.text),
        )

    full_reply = ""
    try:
        async for token in stream_response(history):
            full_reply += token
            payload = json.dumps({"token": token})
            yield f"data: {payload}\n\n"
    except Exception as exc:
        logger.exception("LLM streaming error: %s", exc)
        error_payload = json.dumps({"error": str(exc)})
        yield f"data: {error_payload}\n\n"
        return

    if full_reply:
        save_message(session_id, "assistant", full_reply)

    yield "data: [DONE]\n\n"


@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    msg = request.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    save_message(request.session_id, "user", msg)

    proceed, corrected_response = check_prompt_against_guardrails(msg)

    async def get_corrected_response_stream(response: str) -> AsyncIterator[str]:
        words = response.split(" ")

        for word in words:
            payload_json = json.dumps({"token": f"{word} "})
            yield f"data: {payload_json} \n\n"
            await asyncio.sleep(0.05)

    if not proceed:
        save_message(request.session_id, "assistant", corrected_response)
        return StreamingResponse(
            get_corrected_response_stream(corrected_response),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return StreamingResponse(
        _sse_stream(request.session_id, msg, request.known_session_ids),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/history/{session_id}")
async def history(session_id: str) -> list[dict[str, str]]:
    return get_history(session_id)


@app.post("/placeholder", response_model=PlaceholderResponse)
async def placeholder(request: PlaceholderRequest) -> PlaceholderResponse:
    recent_history = get_history(request.session_id, limit=8)
    if not recent_history:
        return PlaceholderResponse(placeholder=PLACEHOLDER_FALLBACK)

    messages: list[ChatCompletionMessageParam] = []
    for item in recent_history:
        try:
            messages.append(_to_chat_message(item["role"], item["content"]))
        except ValueError:
            logger.warning("Skipping unsupported history role: %s", item["role"])

    try:
        suggested = await generate_placeholder(messages)
    except Exception as exc:
        logger.exception("Placeholder generation failed: %s", exc)
        suggested = PLACEHOLDER_FALLBACK

    return PlaceholderResponse(placeholder=suggested)


@app.delete("/sessions/{session_id}", response_model=DeleteSessionResponse)
async def delete_session_route(session_id: str) -> DeleteSessionResponse:
    delete_session(session_id)
    return DeleteSessionResponse(success=True)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    logger.warning(
        "Static directory '%s' not found. Run 'npm run build' in frontend/ first.",
        STATIC_DIR,
    )
