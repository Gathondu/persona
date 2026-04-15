"""SQLite persistence for local development."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "chat_history.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session ON messages (session_id, id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profile_memories (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                text            TEXT NOT NULL,
                embedding_json  TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, text)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_profile_session ON profile_memories (session_id, id)"
        )


def get_history(session_id: str, limit: int | None = None) -> list[dict[str, str]]:
    with _get_conn() as conn:
        if limit is None:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT role, content FROM ("
                    "SELECT id, role, content FROM messages "
                    "WHERE session_id = ? ORDER BY id DESC LIMIT ?"
                    ") ORDER BY id ASC"
                ),
                (session_id, limit),
            ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def save_message(session_id: str, role: str, content: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )


def delete_session(session_id: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute(
            "DELETE FROM profile_memories WHERE session_id = ? OR source_session_id = ?",
            (session_id, session_id),
        )


def upsert_profile_memory(
    session_id: str,
    source_session_id: str,
    text: str,
    embedding: list[float],
) -> None:
    embedding_json = json.dumps(embedding)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO profile_memories (session_id, source_session_id, text, embedding_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, text)
            DO UPDATE SET
              source_session_id = excluded.source_session_id,
              embedding_json = excluded.embedding_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            (session_id, source_session_id, text, embedding_json),
        )


def get_profile_memories(session_ids: list[str], limit_per_session: int = 25) -> list[dict[str, object]]:
    if not session_ids:
        return []

    placeholders = ", ".join(["?"] * len(session_ids))
    params: tuple[object, ...] = tuple(session_ids) + (limit_per_session * len(session_ids),)
    with _get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT session_id, source_session_id, text, embedding_json, updated_at "
                "FROM profile_memories "
                f"WHERE session_id IN ({placeholders}) "
                "ORDER BY updated_at DESC "
                "LIMIT ?"
            ),
            params,
        ).fetchall()

    result: list[dict[str, object]] = []
    for row in rows:
        result.append(
            {
                "session_id": row["session_id"],
                "source_session_id": row["source_session_id"],
                "text": row["text"],
                "embedding": json.loads(row["embedding_json"]),
            }
        )
    return result
