from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import stream_response
from memory import get_history, init_db, save_message

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("Database initialised.")
    yield


app = FastAPI(title="My AI Double", lifespan=lifespan)


class ChatRequest(BaseModel):
    session_id: str
    message: str


async def _sse_stream(session_id: str, user_message: str) -> AsyncIterator[str]:
    history = get_history(session_id)
    history.append({"role": "user", "content": user_message})

    save_message(session_id, "user", user_message)

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
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    return StreamingResponse(
        _sse_stream(request.session_id, request.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/history/{session_id}")
async def history(session_id: str) -> list[dict[str, str]]:
    return get_history(session_id)


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
