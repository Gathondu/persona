"""DynamoDB persistence for AWS Lambda / production."""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_MESSAGES_TABLE = os.environ["DYNAMODB_MESSAGES_TABLE"]
_PROFILE_TABLE = os.environ["DYNAMODB_PROFILE_TABLE"]

_ddb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"))


def _messages_table() -> Any:
    return _ddb.Table(_MESSAGES_TABLE)


def _profile_table() -> Any:
    return _ddb.Table(_PROFILE_TABLE)


def _mem_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _new_message_sort_key() -> str:
    return f"{time.time_ns():020d}#{uuid.uuid4().hex[:12]}"


def _floats_to_decimal(xs: list[float]) -> list[Decimal]:
    return [Decimal(str(x)) for x in xs]


def _decimal_to_float(xs: list[Any]) -> list[float]:
    return [float(x) for x in xs]


def init_db() -> None:
    """Verify tables exist (Terraform creates them)."""
    client = _ddb.meta.client
    client.describe_table(TableName=_MESSAGES_TABLE)
    client.describe_table(TableName=_PROFILE_TABLE)


def get_history(session_id: str, limit: int | None = None) -> list[dict[str, str]]:
    table = _messages_table()
    if limit is None:
        items: list[dict[str, Any]] = []
        qkwargs: dict[str, Any] = {
            "KeyConditionExpression": "session_id = :s",
            "ExpressionAttributeValues": {":s": session_id},
            "ScanIndexForward": True,
        }
        resp = table.query(**qkwargs)
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = table.query(
                **qkwargs,
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
        return [{"role": i["role"], "content": i["content"]} for i in items]

    resp = table.query(
        KeyConditionExpression="session_id = :s",
        ExpressionAttributeValues={":s": session_id},
        ScanIndexForward=False,
        Limit=limit,
    )
    items = list(reversed(resp.get("Items", [])))
    return [{"role": i["role"], "content": i["content"]} for i in items]


def save_message(session_id: str, role: str, content: str) -> None:
    _messages_table().put_item(
        Item={
            "session_id": session_id,
            "message_id": _new_message_sort_key(),
            "role": role,
            "content": content,
        }
    )


def _delete_all_messages(session_id: str) -> None:
    table = _messages_table()
    resp = table.query(
        KeyConditionExpression="session_id = :s",
        ExpressionAttributeValues={":s": session_id},
        ProjectionExpression="session_id, message_id",
    )
    keys = [
        {"session_id": i["session_id"], "message_id": i["message_id"]}
        for i in resp.get("Items", [])
    ]
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression="session_id = :s",
            ExpressionAttributeValues={":s": session_id},
            ExclusiveStartKey=resp["LastEvaluatedKey"],
            ProjectionExpression="session_id, message_id",
        )
        keys.extend(
            {"session_id": i["session_id"], "message_id": i["message_id"]}
            for i in resp.get("Items", [])
        )
    with table.batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)


def _delete_profile_partition(session_id: str) -> None:
    table = _profile_table()
    resp = table.query(
        KeyConditionExpression="session_id = :s",
        ExpressionAttributeValues={":s": session_id},
        ProjectionExpression="session_id, mem_key",
    )
    keys = [
        {"session_id": i["session_id"], "mem_key": i["mem_key"]}
        for i in resp.get("Items", [])
    ]
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            KeyConditionExpression="session_id = :s",
            ExpressionAttributeValues={":s": session_id},
            ExclusiveStartKey=resp["LastEvaluatedKey"],
            ProjectionExpression="session_id, mem_key",
        )
        keys.extend(
            {"session_id": i["session_id"], "mem_key": i["mem_key"]}
            for i in resp.get("Items", [])
        )
    with table.batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)


def _delete_profile_by_source_session(source_session_id: str) -> None:
    table = _profile_table()
    try:
        resp = table.query(
            IndexName="BySourceSession",
            KeyConditionExpression="source_session_id = :src",
            ExpressionAttributeValues={":src": source_session_id},
            ProjectionExpression="session_id, mem_key",
        )
    except ClientError as exc:
        logger.warning("GSI query failed: %s", exc)
        return
    keys = [
        {"session_id": i["session_id"], "mem_key": i["mem_key"]}
        for i in resp.get("Items", [])
    ]
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            IndexName="BySourceSession",
            KeyConditionExpression="source_session_id = :src",
            ExpressionAttributeValues={":src": source_session_id},
            ExclusiveStartKey=resp["LastEvaluatedKey"],
            ProjectionExpression="session_id, mem_key",
        )
        keys.extend(
            {"session_id": i["session_id"], "mem_key": i["mem_key"]}
            for i in resp.get("Items", [])
        )
    with table.batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)


def delete_session(session_id: str) -> None:
    _delete_all_messages(session_id)
    _delete_profile_partition(session_id)
    _delete_profile_by_source_session(session_id)


def upsert_profile_memory(
    session_id: str,
    source_session_id: str,
    text: str,
    embedding: list[float],
) -> None:
    mk = _mem_key(text)
    now = str(time.time_ns())
    owner_mem = f"{session_id}#{mk}"
    item = {
        "session_id": session_id,
        "mem_key": mk,
        "source_session_id": source_session_id,
        "owner_mem": owner_mem,
        "text": text,
        "embedding": _floats_to_decimal(embedding),
        "updated_at": now,
    }
    _profile_table().put_item(Item=item)


def get_profile_memories(session_ids: list[str], limit_per_session: int = 25) -> list[dict[str, object]]:
    if not session_ids:
        return []

    cap = limit_per_session * len(session_ids)
    table = _profile_table()
    merged: list[dict[str, Any]] = []

    for sid in session_ids:
        resp = table.query(
            KeyConditionExpression="session_id = :s",
            ExpressionAttributeValues={":s": sid},
            ScanIndexForward=False,
            Limit=cap,
        )
        merged.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = table.query(
                KeyConditionExpression="session_id = :s",
                ExpressionAttributeValues={":s": sid},
                ScanIndexForward=False,
                ExclusiveStartKey=resp["LastEvaluatedKey"],
                Limit=cap,
            )
            merged.extend(resp.get("Items", []))

    def sort_key(it: dict[str, Any]) -> int:
        raw = it.get("updated_at", "0")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    merged.sort(key=sort_key, reverse=True)
    merged = merged[:cap]

    result: list[dict[str, object]] = []
    for row in merged:
        emb = row.get("embedding", [])
        result.append(
            {
                "session_id": row["session_id"],
                "source_session_id": row["source_session_id"],
                "text": row["text"],
                "embedding": _decimal_to_float(list(emb)),
            }
        )
    return result
