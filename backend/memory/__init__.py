"""Chat memory backend: SQLite (local) or DynamoDB (AWS)."""

from __future__ import annotations

import os

_BACKEND = os.getenv("MEMORY_BACKEND", "sqlite").strip().lower()

if _BACKEND == "dynamodb":
    from .dynamodb_backend import (
        delete_session,
        get_history,
        get_profile_memories,
        init_db,
        save_message,
        upsert_profile_memory,
    )
elif _BACKEND == "sqlite":
    from .sqlite_backend import (
        delete_session,
        get_history,
        get_profile_memories,
        init_db,
        save_message,
        upsert_profile_memory,
    )
else:
    raise ValueError(
        f"Invalid MEMORY_BACKEND={_BACKEND!r}; expected 'sqlite' or 'dynamodb'."
    )

__all__ = [
    "delete_session",
    "get_history",
    "get_profile_memories",
    "init_db",
    "save_message",
    "upsert_profile_memory",
]
